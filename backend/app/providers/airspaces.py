"""Espaces aériens : OpenAIP (clé gratuite) > fichiers OpenAir locaux > fixtures de démonstration.

OpenAIP v2 — structure réelle constatée (tests/fixtures/openaip_airspaces_annecy.json) :
`GET /api/airspaces?bbox=minLon,minLat,maxLon,maxLat&limit&page` (en-tête `x-openaip-api-key`) →
`{items, limit, page, nextPage}` (pas de totalCount) ; item : name, type (entier), icaoClass (entier),
lowerLimit/upperLimit = {value, unit, referenceDatum}, geometry (GeoJSON Polygon), activity, byNotam…
Codes : unit 0 = m, 1 = ft, 6 = FL ; referenceDatum 0 = GND (sol), 1 = MSL, 2 = STD (niveau de vol) ;
icaoClass 0 A, 1 B, 2 C, 3 D, 4 E, 5 F, 6 G, 8 non classé (SIV, zones R/D/P…).
Types (champ `type`) : 0 autre, 1 R, 2 D, 3 P, 4 CTR, 5 TMZ, 6 RMZ, 7 TMA, 8 TRA, 9 TSA, 10 FIR,
11 UIR, 12 ADIZ, 13 ATZ, 14 MATZ, 15 AWY, 16 MTR, 17 alerte, 18 avertissement, 19 protégée,
20 HTZ, 21 secteur vol à voile, 22 TRP, 23 TIZ, 24 TIA, 25 MTA, 26 CTA, 27 secteur ACC,
28 activité sportive / loisir, 29 survol basse altitude restreint, 30 MRT, 31 TFR, 32 secteur VFR,
33 secteur FIS (= SIV en France), 34 LTA, 35 UTA. Type inconnu → « OTHER ».
SIV / FIS (33), FIR, UIR, ACC : information seulement (jamais un danger) — classe exposée « SIV ».
Conversion : FL × 100 ft × 0,3048 (atmosphère standard, approximation sans QNH) ; plancher « sol » :
hauteur + altitude du terrain si connue (sinon hauteur seule, signalée AGL).
Pagination : `page`/`nextPage` suivis au plus `MAX_PAGES` fois ; arrêt si `nextPage` absent, nul,
non croissant ou page vide. Doublons (même `_id`) éliminés. OpenAIP est derrière Cloudflare (429
possible) : l'appelant limite à un appel toutes les 5 min, sans boucle de nouvelle tentative.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import httpx
from shapely.geometry import Polygon, shape
from shapely.geometry.base import BaseGeometry

from app.engine.context import Airspace
from app.geo import destination
from app.providers.base import ProviderDisabled, ProviderError, get_json
from app.providers.fixture_data import fixture_airspaces

FT = 0.3048
NM_KM = 1.852
ICAO_CLASS = {0: "A", 1: "B", 2: "C", 3: "D", 4: "E", 5: "F", 6: "G", 8: "UNCLASSIFIED"}
OPENAIP_TYPE = {
    0: "OTHER", 1: "R", 2: "D", 3: "P", 4: "CTR", 5: "TMZ", 6: "RMZ", 7: "TMA", 8: "TRA", 9: "TSA",
    10: "FIR", 11: "UIR", 12: "ADIZ", 13: "ATZ", 14: "MATZ", 15: "AWY", 16: "MTR", 17: "ALERT",
    18: "WARNING", 19: "PROTECTED", 20: "HTZ", 21: "GLIDING_SECTOR", 22: "TRP", 23: "TIZ", 24: "TIA",
    25: "MTA", 26: "CTA", 27: "ACC", 28: "SPORT", 29: "LOW_OVERFLIGHT", 30: "MRT", 31: "TFR",
    32: "VFR_SECTOR", 33: "SIV", 34: "LTA", 35: "UTA",
}  # fmt: skip
OPENAIP_UNIT_M, OPENAIP_UNIT_FT, OPENAIP_UNIT_FL = 0, 1, 6
OPENAIP_DATUM_GND, OPENAIP_DATUM_MSL, OPENAIP_DATUM_STD = 0, 1, 2
ACTIVATION_TYPES = ("R", "D", "TRA", "TSA")


def _int(x, default: int) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def limit_to_m(value: float, unit: int, datum: int) -> tuple[float, bool]:
    """Limite OpenAIP → (altitude en m, référencée sol ?).

    unit 0 = m, 1 = ft, 6 = FL (niveau de vol, toujours STD) ; datum 0 = GND (sol), 1 = MSL, 2 = STD.
    Une limite en ft/m rapportée à STD est convertie comme une altitude pression (≈ AMSL en atmosphère
    standard). Unité inconnue : pieds (cas le plus fréquent).
    """
    if unit == OPENAIP_UNIT_FL:
        return value * 100 * FT, False
    meters = value if unit == OPENAIP_UNIT_M else value * FT
    return meters, datum == OPENAIP_DATUM_GND


def _airspace_class(icao: int, typ: str) -> str:
    cls = ICAO_CLASS.get(icao, "UNCLASSIFIED")
    if cls == "UNCLASSIFIED":
        if typ in ("R", "D", "P"):
            return {"R": "R", "D": "Q", "P": "P"}[typ]
        if typ == "SIV":
            return "SIV"
    return cls


def _clean_geometry(raw) -> BaseGeometry | None:
    try:
        geom = shape(raw)
    except Exception:
        return None
    if geom.is_empty:
        return None
    if not geom.is_valid:
        geom = geom.buffer(0)  # anneau auto-intersectant : réparation minimale
    return None if geom.is_empty else geom


def parse_openaip(data, terrain=None) -> tuple[list[Airspace], int | None]:
    """Page OpenAIP → (espaces, page suivante ou None)."""
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ProviderError("OpenAIP : réponse sans 'items'")
    out = []
    for it in data["items"]:
        if not isinstance(it, dict):
            continue
        geom = _clean_geometry(it.get("geometry"))
        if geom is None:
            continue
        typ = OPENAIP_TYPE.get(_int(it.get("type"), 0), "OTHER")
        lo = it.get("lowerLimit") or {}
        hi = it.get("upperLimit") or {}
        floor_raw = float(lo.get("value") or 0)
        floor, floor_agl = limit_to_m(floor_raw, _int(lo.get("unit"), 1), _int(lo.get("referenceDatum"), 1))
        ceil_raw = float(hi.get("value") or 0)
        ceil, ceil_agl = limit_to_m(ceil_raw, _int(hi.get("unit"), 1), _int(hi.get("referenceDatum"), 1))
        floor_agl = floor_agl and floor_raw > 0  # « SFC / 0 ft GND » = sol, pas une hauteur à convertir
        if terrain is not None and (floor_agl or ceil_agl):
            c = geom.representative_point()
            ground = terrain(c.y, c.x) or 0.0
            if floor_agl:
                floor += ground
            if ceil_agl:
                ceil += ground
        cls = _airspace_class(_int(it.get("icaoClass"), 8), typ)
        by_notam = bool(it.get("byNotam") or it.get("onRequest") or it.get("onDemand"))
        out.append(
            Airspace(
                name=str(it.get("name") or "Espace aérien").strip(),
                airspace_class=cls,
                type=typ,
                floor_m=round(floor),
                ceiling_m=round(ceil),
                geometry=geom,
                floor_agl=floor_agl,
                activity_known=not (typ in ACTIVATION_TYPES or by_notam),
                active=False,
            )
        )
    nxt = data.get("nextPage")
    page = _int(data.get("page"), 0)
    nxt_i = _int(nxt, 0) if nxt not in (None, "", False) else 0
    has_more = bool(data["items"]) and nxt_i > page
    return out, (nxt_i if has_more else None)


class OpenAipAirspaces:
    name = "OpenAIP"
    MAX_PAGES = 5
    PAGE_SIZE = 500

    def __init__(self, client: httpx.AsyncClient, url: str, api_key: str | None):
        self.client = client
        self.url = url.rstrip("/")
        self.api_key = api_key

    async def fetch(self, bbox, terrain=None) -> list[Airspace]:
        if not self.api_key:
            raise ProviderDisabled("clé OpenAIP absente")
        out: list[Airspace] = []
        seen: set[tuple] = set()
        page = 1
        headers = {"x-openaip-api-key": self.api_key}
        for _ in range(self.MAX_PAGES):
            params = {"bbox": ",".join(f"{x:.4f}" for x in bbox), "limit": str(self.PAGE_SIZE), "page": str(page)}
            data = await get_json(self.client, f"{self.url}/airspaces", params, headers=headers)
            items, nxt = parse_openaip(data, terrain)
            for a in items:
                key = (a.name, a.type, a.floor_m, a.ceiling_m, round(a.geometry.area, 8))
                if key in seen:
                    continue
                seen.add(key)
                out.append(a)
            if nxt is None:
                break
            page = nxt
        return out


# ---------------------------------------------------------------------------------------------
# OpenAir (format texte des fichiers XCTrack / XCSoar)
# ---------------------------------------------------------------------------------------------
_COORD = re.compile(
    r"(\d{1,2})[:\s](\d{1,2}(?:\.\d+)?)(?:[:\s](\d{1,2}(?:\.\d+)?))?\s*([NS])\s*[, ]?\s*"
    r"(\d{1,3})[:\s](\d{1,2}(?:\.\d+)?)(?:[:\s](\d{1,2}(?:\.\d+)?))?\s*([EW])",
    re.IGNORECASE,
)


def parse_openair_coord(s: str) -> tuple[float, float]:
    m = _COORD.search(s)
    if not m:
        raise ValueError(f"coordonnée OpenAir illisible : {s!r}")
    d1, m1, s1, ns, d2, m2, s2, ew = m.groups()
    lat = float(d1) + float(m1) / 60 + (float(s1) / 3600 if s1 else 0)
    lon = float(d2) + float(m2) / 60 + (float(s2) / 3600 if s2 else 0)
    if ns.upper() == "S":
        lat = -lat
    if ew.upper() == "W":
        lon = -lon
    return lat, lon


def parse_openair_altitude(s: str) -> tuple[float, bool]:
    """(mètres, référencé sol ?). SFC/GND → 0 sol ; FL ; ft / m ; AGL/ASFC/GND → sol ; défaut ft AMSL."""
    t = s.strip().upper().replace(" ", "")
    if t in ("SFC", "GND", "0", "SURFACE"):
        return 0.0, True
    if t.startswith("UNL"):
        return 99999.0, False
    m = re.match(r"^FL(\d+(?:\.\d+)?)", t)
    if m:
        return float(m.group(1)) * 100 * FT, False
    m = re.match(r"^(\d+(?:\.\d+)?)(FT|F|M)?(AMSL|MSL|AGL|ASFC|SFC|GND|ALT)?", t)
    if not m:
        raise ValueError(f"altitude OpenAir illisible : {s!r}")
    val = float(m.group(1))
    unit = m.group(2) or "FT"
    ref = m.group(3) or "AMSL"
    meters = val if unit == "M" else val * FT
    return meters, ref in ("AGL", "ASFC", "SFC", "GND")


@dataclass
class _OpenAirBlock:
    cls: str = ""
    name: str = ""
    typ: str | None = None
    floor: tuple[float, bool] = (0.0, True)
    ceiling: tuple[float, bool] = (99999.0, False)


def _arc(center, r_km, a0, a1, clockwise: bool, step: float = 5.0) -> list[tuple[float, float]]:
    pts = []
    if clockwise:
        sweep = (a1 - a0) % 360 or 360
        n = max(2, int(sweep / step))
        for i in range(n + 1):
            pts.append(destination(center[0], center[1], a0 + sweep * i / n, r_km))
    else:
        sweep = (a0 - a1) % 360 or 360
        n = max(2, int(sweep / step))
        for i in range(n + 1):
            pts.append(destination(center[0], center[1], a0 - sweep * i / n, r_km))
    return pts


def _bearing_dist(center, pt) -> tuple[float, float]:
    from app.geo import bearing_deg, haversine_km

    return bearing_deg(center[0], center[1], pt[0], pt[1]), haversine_km(center[0], center[1], pt[0], pt[1])


# classes OpenAir non OACI (AC …) → (classe exposée, type)
_OPENAIR_AC = {
    "CTR": ("D", "CTR"),  # CTR françaises : classe D (quelques C) → interdites sans clairance
    "GP": ("P", "P"),  # glider prohibited
    "RMZ": ("UNCLASSIFIED", "RMZ"),
    "TMZ": ("UNCLASSIFIED", "TMZ"),
    "W": ("UNCLASSIFIED", "WAVE"),
    "UNC": ("UNCLASSIFIED", "OTHER"),
    "UNCLASSIFIED": ("UNCLASSIFIED", "OTHER"),
    "SIV": ("SIV", "SIV"),
    "FIS": ("SIV", "SIV"),
}


def _openair_class_type(blk: _OpenAirBlock) -> tuple[str, str]:
    cls = (blk.cls or "UNCLASSIFIED").upper()
    name = blk.name.upper()
    if cls in _OPENAIR_AC:
        cls, typ = _OPENAIR_AC[cls]
    else:
        typ = "CTR" if "CTR" in name else "TMA" if "TMA" in name else "SIV" if name.startswith("SIV") else cls
    if blk.typ:
        typ = blk.typ.upper()
    return cls, typ


def parse_openair(text: str, terrain=None) -> list[Airspace]:
    """Analyse un fichier OpenAir : AC, AN, AY, AL, AH, DP, V X=, V D=, DA, DB, DC."""
    out: list[Airspace] = []
    blk: _OpenAirBlock | None = None
    pts: list[tuple[float, float]] = []
    circle: tuple[tuple[float, float], float] | None = None
    center: tuple[float, float] | None = None
    clockwise = True

    def flush() -> None:
        nonlocal blk, pts, circle
        if blk is None:
            return
        geom: BaseGeometry | None = None
        if circle is not None:
            c, r = circle
            ring = [destination(c[0], c[1], a, r) for a in range(0, 360, 5)]
            geom = Polygon([(lo, la) for la, lo in ring])
        elif len(pts) >= 3:
            geom = Polygon([(lo, la) for la, lo in pts])
        if geom is not None and geom.is_valid and not geom.is_empty:
            floor, f_agl = blk.floor
            ceil, c_agl = blk.ceiling
            if terrain is not None and (f_agl or c_agl):
                rp = geom.representative_point()
                ground = terrain(rp.y, rp.x) or 0.0
                if f_agl and floor > 0:
                    floor += ground
                if c_agl:
                    ceil += ground
            cls, typ = _openair_class_type(blk)
            out.append(
                Airspace(
                    name=blk.name or "Espace aérien",
                    airspace_class=cls,
                    type=typ,
                    floor_m=round(floor),
                    ceiling_m=round(min(ceil, 99999)),
                    geometry=geom,
                    floor_agl=f_agl and floor > 0,
                    activity_known=cls not in ("R", "Q") and typ not in ("R", "Q", "ZRT", "TRA", "TSA"),
                    active=False,
                )
            )
        blk, pts, circle = None, [], None

    for raw in text.splitlines():
        line = raw.split("*", 1)[0].strip() if not raw.strip().startswith("*") else ""
        if not line:
            continue
        key, _, rest = line.partition(" ")
        key = key.upper()
        rest = rest.strip()
        if key == "AC":
            flush()
            blk = _OpenAirBlock(cls=rest.upper())
            center, clockwise = None, True
        elif blk is None:
            continue
        elif key == "AN":
            blk.name = rest
        elif key == "AY":
            blk.typ = rest.upper()
        elif key == "AL":
            blk.floor = parse_openair_altitude(rest)
        elif key == "AH":
            blk.ceiling = parse_openair_altitude(rest)
        elif key == "V":
            k, _, v = rest.partition("=")
            k = k.strip().upper()
            if k == "X":
                center = parse_openair_coord(v)
            elif k == "D":
                clockwise = v.strip() != "-"
        elif key == "DP":
            pts.append(parse_openair_coord(rest))
        elif key == "DC" and center is not None:
            circle = (center, float(rest.split()[0]) * NM_KM)
        elif key == "DA" and center is not None:
            r_nm, a0, a1 = (float(x) for x in rest.replace(" ", "").split(",")[:3])
            pts += _arc(center, r_nm * NM_KM, a0, a1, clockwise)
        elif key == "DB" and center is not None:
            c1, c2 = rest.split(",", 1) if "," in rest else (rest, rest)
            p1, p2 = parse_openair_coord(c1), parse_openair_coord(c2)
            b1, r1 = _bearing_dist(center, p1)
            b2, _ = _bearing_dist(center, p2)
            pts.append(p1)
            pts += _arc(center, r1, b1, b2, clockwise)[1:-1]
            pts.append(p2)
    flush()
    return out


def read_openair_text(path: Path) -> str:
    """Fichier OpenAir en UTF-8, sinon Windows-1252 / Latin-1 (fréquent pour les fichiers français)."""
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


class OpenAirFiles:
    name = "Fichiers OpenAir locaux"

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self._cache: list[Airspace] | None = None
        self._mtime: float | None = None

    def files(self) -> list[Path]:
        if not self.directory.is_dir():
            return []
        return sorted(p for p in self.directory.iterdir() if p.suffix.lower() in (".txt", ".openair", ".air"))

    def load(self, terrain=None) -> list[Airspace]:
        files = self.files()
        if not files:
            raise ProviderDisabled(f"aucun fichier OpenAir dans {self.directory}")
        mtime = max(p.stat().st_mtime for p in files)
        if self._cache is not None and self._mtime == mtime:
            return self._cache
        out: list[Airspace] = []
        for p in files:
            out += parse_openair(read_openair_text(p), terrain)
        self._cache, self._mtime = out, mtime
        return out

    def fetch(self, bbox, terrain=None) -> list[Airspace]:
        from shapely.geometry import box

        b = box(*bbox)
        return [a for a in self.load(terrain) if a.geometry.intersects(b)]


def fixture_airspace_list(bbox=None) -> list[Airspace]:
    from shapely.geometry import box

    out = []
    b = box(*bbox) if bbox else None
    for f in fixture_airspaces()["features"]:
        p = f["properties"]
        g = shape(f["geometry"])
        if b is not None and not g.intersects(b):
            continue
        out.append(
            Airspace(
                name=p["name"],
                airspace_class=p["airspace_class"],
                type=p["type"],
                floor_m=float(p["floor_m"]),
                ceiling_m=float(p["ceiling_m"]),
                geometry=g,
                activity_known=p["type"] not in ("R", "D", "ZRT"),
                active=False,
            )
        )
    return out


def airspace_feature(a: Airspace) -> dict:
    from shapely.geometry import mapping

    return {
        "type": "Feature",
        "geometry": mapping(a.geometry),
        "properties": {
            "name": a.name,
            "airspace_class": a.airspace_class,
            "type": a.type,
            "floor_m": round(a.floor_m),
            "ceiling_m": round(a.ceiling_m),
            "floor_reference": "GND" if a.floor_agl else "AMSL",
        },
    }


