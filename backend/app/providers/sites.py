"""Fournisseurs de sites : fixtures (mock), ParaglidingEarth (libre), FFVL (clé), SpotAir (désactivé).

ParaglidingEarth — structure réelle constatée (tests/fixtures/paraglidingearth_bbox_annecy.json) :
`getBoundingBoxSites.php?north&south&east&west&limit&style=detailled` → GeoJSON FeatureCollection ;
`properties` en chaînes : name, takeoff_altitude ("-1" si inconnue), N/NE/…/NW ("0" | "1" | "2"),
paragliding, soaring, xc, thermals, pge_site_id, pge_link, takeoff_description, going_there,
flight_rules, et un objet `landing` {landing_name, landing_lat, landing_lng, landing_altitude, …}
(absent si pas d'atterro). Coordonnées GeoJSON [lon, lat].
"""

from __future__ import annotations

import difflib
import re
import unicodedata

import httpx

from app.engine import rules
from app.engine.context import SiteMeta
from app.geo import haversine_km
from app.models import COMPASS_16, Site
from app.providers.base import ProviderDisabled, ProviderError, get_json
from app.providers.fixture_data import fixture_sites_raw

PGE_SECTORS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
CLOSED_WORDS = ("fermé", "ferme ", "closed", "interdit", "ancien", "forbidden")


def fixture_sites() -> tuple[list[Site], dict[str, SiteMeta]]:
    sites: list[Site] = []
    meta: dict[str, SiteMeta] = {}
    for raw in fixture_sites_raw():
        m = raw.get("meta") or {}
        data = {k: v for k, v in raw.items() if k != "meta"}
        site = Site(source="fixture", **data)
        sites.append(site)
        meta[site.id] = SiteMeta(big_valley=m.get("big_valley"), top_landing=bool(m.get("top_landing")))
    return sites, meta


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v


def pge_orientations(props: dict) -> list[str]:
    """Secteurs PGE (8, notés 0/1/2) → rose 16 points ; secteur intermédiaire si ses deux voisins sont notés."""
    rated = {s for s in PGE_SECTORS if (_num(props.get(s)) or 0) >= 1}
    if len(rated) == 8:
        return list(COMPASS_16)
    out = []
    for i, sec in enumerate(COMPASS_16):
        if i % 2 == 0:
            if sec in rated:
                out.append(sec)
        else:
            a, b = COMPASS_16[i - 1], COMPASS_16[(i + 1) % 16]
            if a in rated and b in rated:
                out.append(sec)
    return out


def _is_closed(name: str) -> bool:
    n = name.lower()
    return any(w in n for w in CLOSED_WORDS)


def parse_pge(data) -> tuple[list[Site], dict[str, SiteMeta]]:
    if not isinstance(data, dict) or "features" not in data:
        raise ProviderError("ParaglidingEarth : réponse sans 'features'")
    sites: list[Site] = []
    meta: dict[str, SiteMeta] = {}
    for f in data["features"]:
        props = f.get("properties") or {}
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = float(coords[0]), float(coords[1])
        if str(props.get("paragliding", "1")) == "0":
            continue
        pid = str(props.get("pge_site_id") or f.get("id"))
        name = (props.get("name") or f"Site PGE {pid}").strip()
        alt = _num(props.get("takeoff_altitude"))
        types = ["local"]
        if str(props.get("soaring")) == "1":
            types.append("ridge_soaring")
        if str(props.get("xc")) == "1":
            types.append("cross_country")
        landing_ids: list[str] = []
        ldg = props.get("landing") or {}
        llat = _num(ldg.get("landing_lat") or props.get("landing_lat"))
        llon = _num(ldg.get("landing_lng") or props.get("landing_lng"))
        if llat is not None and llon is not None and (llat, llon) != (0.0, 0.0):
            lalt = _num(ldg.get("landing_altitude"))
            lid = f"pge:{pid}:landing"
            lname = (ldg.get("landing_name") or "").strip() or f"Atterro de {name}"
            sites.append(
                Site(
                    id=lid, name=lname, kind="landing", lat=llat, lon=llon,
                    elevation_m=lalt if lalt is not None and lalt > 0 else -1.0,
                    orientations=[], difficulty=None, flight_types=[],
                    description=(ldg.get("landing_description") or None), access=None, restrictions=None,
                    status="unknown", source="paraglidingearth", url=props.get("pge_link"), associated_landing_ids=[],
                )  # fmt: skip
            )
            landing_ids.append(lid)
        status = "closed" if _is_closed(name) else "unknown"
        sites.append(
            Site(
                id=f"pge:{pid}", name=name, kind="takeoff", lat=lat, lon=lon,
                elevation_m=alt if alt is not None and alt > 0 else -1.0,
                orientations=pge_orientations(props), difficulty=None, flight_types=types,
                description=(props.get("takeoff_description") or props.get("comments") or None),
                access=(props.get("going_there") or None), restrictions=(props.get("flight_rules") or None),
                status=status, source="paraglidingearth", url=props.get("pge_link"), associated_landing_ids=landing_ids,
            )  # fmt: skip
        )
        meta[f"pge:{pid}"] = SiteMeta()
    return sites, meta


class ParaglidingEarthSites:
    name = "ParaglidingEarth"

    def __init__(self, client: httpx.AsyncClient, base_url: str):
        self.client = client
        self.base_url = base_url.rstrip("/")

    async def fetch(self, bbox: tuple[float, float, float, float]) -> tuple[list[Site], dict[str, SiteMeta]]:
        min_lon, min_lat, max_lon, max_lat = bbox
        params = {
            "north": f"{max_lat:.4f}",
            "south": f"{min_lat:.4f}",
            "east": f"{max_lon:.4f}",
            "west": f"{min_lon:.4f}",
            "limit": "200",
            "style": "detailled",
        }
        data = await get_json(self.client, f"{self.base_url}/getBoundingBoxSites.php", params)
        return parse_pge(data)


# ---------------------------------------------------------------------------------------------
# FFVL (clé API requise — format non vérifié faute de clé : parseur défensif)
# ---------------------------------------------------------------------------------------------
def parse_ffvl_terrains(data) -> list[Site]:
    items = data if isinstance(data, list) else (data.get("terrains") or data.get("data") or []) if isinstance(data, dict) else []
    out = []
    for it in items:
        lat = _num(it.get("latitude") or it.get("lat"))
        lon = _num(it.get("longitude") or it.get("lon") or it.get("lng"))
        if lat is None or lon is None:
            continue
        typ = str(it.get("site_type") or it.get("type") or "").lower()
        kind = "landing" if "atterr" in typ else "takeoff"
        from app.geo import parse_orientations

        sid = str(it.get("suid") or it.get("id") or it.get("site_id"))
        out.append(
            Site(
                id=f"ffvl:{sid}", name=str(it.get("toponym") or it.get("nom") or it.get("name") or f"FFVL {sid}"),
                kind=kind, lat=lat, lon=lon, elevation_m=_num(it.get("altitude") or it.get("alt")) or -1.0,
                orientations=parse_orientations(it.get("orientation") or it.get("orientations")),
                difficulty=None, flight_types=["local"], description=it.get("description"),
                access=it.get("acces") or it.get("access"), restrictions=it.get("consignes") or it.get("restrictions"),
                status="open", source="ffvl", url=it.get("url"), associated_landing_ids=[],
            )  # fmt: skip
        )
    return out


class FfvlSites:
    name = "FFVL (terrains)"

    def __init__(self, client: httpx.AsyncClient, api_url: str, api_key: str | None):
        self.client = client
        self.api_url = api_url
        self.api_key = api_key

    async def fetch(self, bbox) -> tuple[list[Site], dict[str, SiteMeta]]:
        if not self.api_key:
            raise ProviderDisabled("clé FFVL absente")
        data = await get_json(self.client, self.api_url, {"base": "terrains", "mode": "json", "key": self.api_key})
        min_lon, min_lat, max_lon, max_lat = bbox
        sites = [s for s in parse_ffvl_terrains(data) if min_lat <= s.lat <= max_lat and min_lon <= s.lon <= max_lon]
        return sites, {}


class SpotAirSites:
    """SpotAir n'a pas d'API publique : adaptateur prêt, activé seulement avec un accord (URL + clé)."""

    name = "SpotAir"

    def __init__(self, client: httpx.AsyncClient, api_url: str | None, api_key: str | None):
        self.client = client
        self.api_url = api_url
        self.api_key = api_key

    async def fetch(self, bbox) -> tuple[list[Site], dict[str, SiteMeta]]:
        if not (self.api_url and self.api_key):
            raise ProviderDisabled("pas d'API publique SpotAir (accord / partenariat nécessaire)")
        raise ProviderDisabled("format SpotAir à définir avec le partenaire")


# ---------------------------------------------------------------------------------------------
# Fusion / dédoublonnage / association déco ↔ atterro
# ---------------------------------------------------------------------------------------------
SOURCE_PRIORITY = {"fixture": 0, "ffvl": 1, "paraglidingearth": 2, "spotair": 3}


def _norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


def similar_names(a: str, b: str) -> bool:
    na, nb = _norm_name(a), _norm_name(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    ta, tb = set(na.split()), set(nb.split())
    if ta & tb - {"de", "la", "le", "du", "des", "deco", "atterro", "atterrissage", "takeoff"}:
        return True
    return difflib.SequenceMatcher(None, na, nb).ratio() >= 0.6


def merge_sites(groups: list[list[Site]]) -> list[Site]:
    """Fusion dédoublonnée (< 300 m et nom proche, ou < 100 m), en gardant la source prioritaire."""
    all_sites = sorted((s for g in groups for s in g), key=lambda s: SOURCE_PRIORITY.get(s.source, 9))
    kept: list[Site] = []
    for s in all_sites:
        dup = None
        for k in kept:
            if (k.kind == "landing") != (s.kind == "landing"):
                continue
            d = haversine_km(s.lat, s.lon, k.lat, k.lon) * 1000
            same_orient = bool(set(s.orientations) & set(k.orientations)) or not s.orientations or not k.orientations
            if d < 100 or (d < 300 and (similar_names(s.name, k.name) or same_orient)):
                dup = k
                break
        if dup is None:
            kept.append(s)
        else:
            # complète les champs manquants de la source prioritaire
            for f in ("description", "access", "restrictions", "url"):
                if getattr(dup, f) is None and getattr(s, f) is not None:
                    setattr(dup, f, getattr(s, f))
            for lid in s.associated_landing_ids:
                if lid not in dup.associated_landing_ids:
                    dup.associated_landing_ids.append(lid)
    return kept


def associate_landings(sites: list[Site], max_glide: float = 6.0) -> None:
    """Associe à chaque déco sans atterro les atterros < 8 km, dénivelé ≥ 150 m, finesse requise ≤ 6
    (règle PGE c du lot expert 3.8) ; supprime les associations incohérentes (atterro plus haut, g)."""
    landings = [s for s in sites if s.kind in ("landing", "both")]
    by_id = {s.id: s for s in sites}
    for s in sites:
        if s.kind == "landing":
            continue
        valid = []
        for lid in s.associated_landing_ids:
            ldg = by_id.get(lid)
            if ldg is None:
                continue
            if ldg.elevation_m > 0 and s.elevation_m > 0 and ldg.elevation_m > s.elevation_m and ldg.id != s.id and s.kind != "both":
                continue  # atterro plus haut que le déco : erreur de données
            valid.append(lid)
        s.associated_landing_ids = valid
        if valid:
            continue
        cands = []
        for ldg in landings:
            if ldg.id == s.id:
                continue
            d = haversine_km(s.lat, s.lon, ldg.lat, ldg.lon)
            drop = s.elevation_m - ldg.elevation_m
            if d <= rules.ASSOCIATED_LANDING_MAX_KM and drop >= rules.ASSOCIATED_LANDING_MIN_DROP_M:
                req = d * 1000 / max(1.0, drop - 100)
                if req <= max_glide:
                    cands.append((req, ldg.id))
        s.associated_landing_ids = [lid for _, lid in sorted(cands)[:3]]
