"""Fournisseurs de sites : fixtures (mock), ParaglidingEarth (libre), FFVL (clé), SpotAir (désactivé).

ParaglidingEarth — structure réelle constatée (tests/fixtures/paraglidingearth_bbox_annecy*.json) :
`https://www.paraglidingearth.com/api/geojson/getBoundingBoxSites.php?north&south&east&west&limit&style=detailled`
(UNIQUEMENT en https://www. : le domaine sans www et le http sont refusés par certains proxys) →
GeoJSON FeatureCollection de DÉCOLLAGES (`place` = « paragliding takeoff ») ; `properties` toutes en
chaînes : name, takeoff_altitude (« -1 » si inconnue), N/NE/…/NW (« 0 » non, « 1 » possible,
« 2 » bon), paragliding, hanggliding, soaring, xc, thermals, pge_site_id, pge_link (http://…),
ffvl_site_id (« 0 » si non lié à une fiche FFVL), takeoff_description, going_there, flight_rules,
comments, weather, landing_lat/landing_lng (« » si absent) et un objet `landing`
{landing_name, landing_lat, landing_lng, landing_altitude, landing_description} quand l'atterro est
documenté. Coordonnées GeoJSON [lon, lat]. Pas d'atterro autonome dans cette API : un atterro PGE
est toujours celui d'un déco (plusieurs décos peuvent partager le même atterro → dédoublonné).

Statut « officiel » (contrat `Site.official` / `Site.landing_kind`, cahier §12.7) — PGE n'a pas de
drapeau officiel ; règle retenue (à valider par l'expert) :
- déco `official` si lié à une fiche FFVL (`ffvl_site_id` > 0) ou fiche complète (altitude connue ET
  au moins une orientation notée), et pas de mot « sauvage / non officiel / interdit… » dans le nom ;
- sinon fiche sommaire → `official = False` (site communautaire, à vérifier) ;
- atterro documenté d'un déco officiel → `landing_kind = "official"`, sinon `"community"`.
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
# revue (m) : mots entiers seulement (« La Ferme de Chosal », « Ancienne carrière » ne sont pas des sites fermés)
CLOSED_RE = re.compile(r"\b(?:fermée?s?|site fermé|closed|interdite?s?|forbidden)\b", re.IGNORECASE)
UNOFFICIAL_WORDS = ("sauvage", "non officiel", "non-officiel", "unofficial", "wild", "interdit", "forbidden")
PGE_BASE_URL = "https://www.paraglidingearth.com"


def site_extra(**fields) -> dict:
    """Champs du contrat ajoutés au modèle `Site` au fil des versions (`official`, `landing_kind`) :
    transmis seulement si le modèle les déclare (compatibilité avec une version antérieure du modèle)."""
    known = getattr(Site, "model_fields", {})
    return {k: v for k, v in fields.items() if k in known}


def fixture_sites() -> tuple[list[Site], dict[str, SiteMeta]]:
    sites: list[Site] = []
    meta: dict[str, SiteMeta] = {}
    for raw in fixture_sites_raw():
        m = raw.get("meta") or {}
        data = {k: v for k, v in raw.items() if k != "meta"}
        is_landing = data.get("kind") in ("landing", "both")
        defaults = site_extra(official=True, landing_kind="official" if is_landing else None)
        site = Site(source="fixture", **{**defaults, **data})
        sites.append(site)
        meta[site.id] = SiteMeta(big_valley=m.get("big_valley"), top_landing=bool(m.get("top_landing")))
    return sites, meta


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v


def _text(x) -> str | None:
    """Texte PGE nettoyé (CRLF, espaces) ; None si vide."""
    if x is None:
        return None
    t = str(x).replace("\r\n", "\n").replace("\r", "\n").strip()
    t = re.sub(r"[ \t]+", " ", t)
    return t or None


def pge_rated(props: dict) -> tuple[set[str], set[str]]:
    """(secteurs PGE notés ≥ 1, secteurs notés 2 = « bon »)."""
    rated = {s for s in PGE_SECTORS if (_num(props.get(s)) or 0) >= 1}
    good = {s for s in PGE_SECTORS if (_num(props.get(s)) or 0) >= 2}
    return rated, good


def _pge_sectors(props: dict) -> tuple[set[str], bool]:
    """(secteurs retenus, orientation incertaine). Revue 7.3 : (a) dès 6 secteurs notés sur 8, la notation PGE n'est
    pas une orientation ; (b) on préfère alors les secteurs notés 2 (« bon ») s'ils sont moins de 6 ; sinon
    l'orientation est incertaine (le moteur la déduit de l'exposition MNT ou écarte le site). Moins de 6 secteurs
    notés : tous sont gardés (Forclaz : N et NW notés 2, W noté 1 = axe principal du déco)."""
    rated, good = pge_rated(props)
    n = rules.ORIENTATION_UNCERTAIN_MIN_SECTORS
    if len(rated) < n:
        return rated, False
    if 0 < len(good) < n:
        return good, False
    return rated, True


def pge_orientation_uncertain(props: dict) -> bool:
    return _pge_sectors(props)[1]


def pge_orientations(props: dict) -> list[str]:
    """Secteurs PGE (8, notés 0/1/2) → rose 16 points ; secteur intermédiaire si ses deux voisins sont notés (voir
    `_pge_sectors` pour le choix des secteurs)."""
    rated, _ = _pge_sectors(props)
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


def https_link(url: str | None) -> str | None:
    """Liens PGE en https://www (le http et le domaine sans www sont refusés par certains proxys)."""
    if not url:
        return None
    u = url.strip().replace("http://", "https://", 1)
    return u.replace("https://paraglidingearth.com", "https://www.paraglidingearth.com", 1)


def _is_closed(name: str) -> bool:
    return CLOSED_RE.search(name) is not None


def _flag(props: dict, key: str) -> bool:
    return str(props.get(key) or "0").strip() not in ("0", "", "false", "False", "None")


def pge_official(props: dict, name: str, altitude: float | None, orientations: list[str]) -> bool:
    """Déco PGE « référencé » (voir docstring du module) : fiche FFVL liée ou fiche complète."""
    low = name.lower()
    if any(w in low for w in UNOFFICIAL_WORDS):
        return False
    if (_num(props.get("ffvl_site_id")) or 0) > 0:
        return True
    return altitude is not None and altitude > 0 and bool(orientations)


def parse_pge(data) -> tuple[list[Site], dict[str, SiteMeta]]:
    if not isinstance(data, dict) or not isinstance(data.get("features"), list):
        raise ProviderError("ParaglidingEarth : réponse sans 'features'")
    sites: list[Site] = []
    meta: dict[str, SiteMeta] = {}
    seen: set[str] = set()
    for f in data["features"]:
        if not isinstance(f, dict):
            continue
        props = f.get("properties") or {}
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = _num(coords[0]), _num(coords[1])
        if lat is None or lon is None or (lat, lon) == (0.0, 0.0):
            continue
        if not _flag(props, "paragliding") and "paragliding" in props:
            continue  # site delta uniquement
        pid = str(props.get("pge_site_id") or f.get("id") or f"{lat:.4f},{lon:.4f}")
        if pid in seen:
            continue  # même site renvoyé deux fois
        seen.add(pid)
        name = _text(props.get("name")) or f"Site PGE {pid}"
        alt = _num(props.get("takeoff_altitude"))
        alt = alt if alt is not None and alt > 0 else None
        orientations = pge_orientations(props)
        official = pge_official(props, name, alt, orientations)
        url = https_link(props.get("pge_link")) or f"{PGE_BASE_URL}/?site={pid}"
        place = str(props.get("place") or "").lower()
        kind = "landing" if "landing" in place and "takeoff" not in place else "takeoff"
        types = ["local"]
        if _flag(props, "soaring"):
            types.append("ridge_soaring")
        if _flag(props, "xc"):
            types.append("cross_country")
        landing_ids: list[str] = []
        ldg = props.get("landing") if isinstance(props.get("landing"), dict) else {}
        llat = _num(ldg.get("landing_lat") or props.get("landing_lat"))
        llon = _num(ldg.get("landing_lng") or props.get("landing_lng"))
        if kind == "takeoff" and llat is not None and llon is not None and (llat, llon) != (0.0, 0.0):
            lalt = _num(ldg.get("landing_altitude"))
            lid = f"pge:{pid}:landing"
            lname = _text(ldg.get("landing_name"))
            if lname and lname.lower() in ("null", "none", "-"):  # revue 7.21 : atterro PGE nommé « null »
                lname = f"Atterrissage PGE n° {pid}"
            lname = lname or f"Atterro de {name}"
            sites.append(
                Site(
                    id=lid,
                    name=lname,
                    kind="landing",
                    lat=llat,
                    lon=llon,
                    elevation_m=lalt if lalt is not None and lalt > 0 else -1.0,
                    orientations=[],
                    difficulty=None,
                    flight_types=[],
                    description=_text(ldg.get("landing_description")),
                    access=None,
                    restrictions=None,
                    status="unknown",
                    source="paraglidingearth",
                    url=url,
                    associated_landing_ids=[],
                    **site_extra(official=official, landing_kind="official" if official else "community"),
                )
            )
            landing_ids.append(lid)
        status = "closed" if _is_closed(name) else "unknown"
        sites.append(
            Site(
                id=f"pge:{pid}",
                name=name,
                kind=kind,
                lat=lat,
                lon=lon,
                elevation_m=alt if alt is not None else -1.0,
                orientations=orientations if kind == "takeoff" else [],
                difficulty=None,
                flight_types=types if kind == "takeoff" else [],
                description=_text(props.get("takeoff_description")) or _text(props.get("comments")),
                access=_text(props.get("going_there")),
                restrictions=_text(props.get("flight_rules")),
                status=status,
                source="paraglidingearth",
                url=url,
                associated_landing_ids=landing_ids,
                **site_extra(
                    official=official,
                    landing_kind=("official" if official else "community") if kind == "landing" else None,
                ),
            )
        )
        m = SiteMeta()
        if kind == "takeoff" and pge_orientation_uncertain(props):
            m.orientation_uncertain = True
            m.orientation_note = f"ParaglidingEarth : {len(pge_rated(props)[0])} secteurs notés sur 8"
        elif kind == "takeoff" and len(pge_rated(props)[0]) >= rules.ORIENTATION_UNCERTAIN_MIN_SECTORS:
            m.orientation_note = "ParaglidingEarth : secteurs notés « bon » retenus"
        meta[f"pge:{pid}"] = m
    return sites, meta


class ParaglidingEarthSites:
    name = "ParaglidingEarth"
    LIMIT = 500

    def __init__(self, client: httpx.AsyncClient, base_url: str):
        self.client = client
        # https://www. obligatoire (le http et le domaine nu sont refusés par certains proxys)
        self.base_url = https_link(base_url.rstrip("/")) or base_url

    async def fetch(self, bbox: tuple[float, float, float, float]) -> tuple[list[Site], dict[str, SiteMeta]]:
        min_lon, min_lat, max_lon, max_lat = bbox
        params = {
            "north": f"{max_lat:.4f}",
            "south": f"{min_lat:.4f}",
            "east": f"{max_lon:.4f}",
            "west": f"{min_lon:.4f}",
            "limit": str(self.LIMIT),
            "style": "detailled",  # sic (orthographe de l'API) : fiche complète avec l'atterro
        }
        data = await get_json(self.client, f"{self.base_url}/getBoundingBoxSites.php", params)
        return parse_pge(data)


# ---------------------------------------------------------------------------------------------
# FFVL (clé API requise — format non vérifié faute de clé : parseur défensif)
# ---------------------------------------------------------------------------------------------
def parse_ffvl_terrains(data) -> list[Site]:
    from app.geo import parse_orientations

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("terrains") or data.get("data") or []
    else:
        items = []
    out = []
    for it in items:
        lat = _num(it.get("latitude") or it.get("lat"))
        lon = _num(it.get("longitude") or it.get("lon") or it.get("lng"))
        if lat is None or lon is None:
            continue
        typ = str(it.get("site_type") or it.get("type") or "").lower()
        kind = "landing" if "atterr" in typ else "takeoff"
        sid = str(it.get("suid") or it.get("id") or it.get("site_id"))
        out.append(
            Site(
                id=f"ffvl:{sid}",
                name=str(it.get("toponym") or it.get("nom") or it.get("name") or f"FFVL {sid}"),
                kind=kind,
                lat=lat,
                lon=lon,
                elevation_m=_num(it.get("altitude") or it.get("alt")) or -1.0,
                orientations=parse_orientations(it.get("orientation") or it.get("orientations")),
                difficulty=None,
                flight_types=["local"],
                description=it.get("description"),
                access=it.get("acces") or it.get("access"),
                restrictions=it.get("consignes") or it.get("restrictions"),
                status="open",
                source="ffvl",
                url=it.get("url"),
                associated_landing_ids=[],
                **site_extra(official=True, landing_kind="official" if kind == "landing" else None),
            )
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
        sites = [
            s for s in parse_ffvl_terrains(data) if min_lat <= s.lat <= max_lat and min_lon <= s.lon <= max_lon
        ]
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


def completeness(s: Site) -> int:
    """Qualité d'une fiche (pour garder la plus complète de deux doublons d'une même source)."""
    score = 0
    score += 2 if getattr(s, "official", False) else 0
    score += 1 if s.elevation_m > 0 else 0
    score += 1 if s.orientations else 0
    score += 1 if s.associated_landing_ids else 0
    score += 1 if s.description else 0
    return score


def merge_sites(groups: list[list[Site]]) -> list[Site]:
    """Fusion dédoublonnée (< 300 m et nom proche ou orientations communes, ou < 100 m), en gardant la
    source prioritaire puis la fiche la plus complète ; les références d'atterros fusionnés sont
    réécrites vers l'atterro conservé."""
    all_sites = sorted(
        (s for g in groups for s in g), key=lambda s: (SOURCE_PRIORITY.get(s.source, 9), -completeness(s))
    )
    kept: list[Site] = []
    alias: dict[str, str] = {}
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
            continue
        alias[s.id] = dup.id
        # complète les champs manquants de la fiche conservée
        for f in ("description", "access", "restrictions", "url"):
            if getattr(dup, f) is None and getattr(s, f) is not None:
                setattr(dup, f, getattr(s, f))
        if dup.elevation_m <= 0 < s.elevation_m:
            dup.elevation_m = s.elevation_m
        if not dup.orientations and s.orientations:
            dup.orientations = list(s.orientations)
        fields = getattr(type(dup), "model_fields", {})
        if "official" in fields and getattr(s, "official", False) and not dup.official:
            dup.official = True
            if "landing_kind" in fields and dup.kind in ("landing", "both"):
                dup.landing_kind = "official"
        for lid in s.associated_landing_ids:
            if lid not in dup.associated_landing_ids:
                dup.associated_landing_ids.append(lid)
    if alias:
        for k in kept:
            ids: list[str] = []
            for lid in k.associated_landing_ids:
                lid = alias.get(lid, lid)
                if lid not in ids and lid != k.id:
                    ids.append(lid)
            k.associated_landing_ids = ids
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
            higher = ldg.elevation_m > 0 and s.elevation_m > 0 and ldg.elevation_m > s.elevation_m
            if higher and ldg.id != s.id and s.kind != "both":
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
        s.deduced_landing_ids = list(s.associated_landing_ids)
