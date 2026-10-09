"""Atterros candidats hors sites officiels (CDC §12.7) : atterros communautaires et champs détectés.

Deux sources :
- **OpenStreetMap via l'API Overpass** (désactivable : `OVERPASS_ENABLED`, `OVERPASS_URL`). Deux requêtes :
  (1) prairies / prés / terres agricoles (`landuse=meadow|grass|farmland`, `natural=grassland`) et atterros vol libre
  (`free_flying:site=landing`) dans la zone ; (2) obstacles autour des champs retenus : lignes électriques et câbles
  (`power=line|minor_line|cable`, `aerialway`), forêts et bâtiments (`natural=wood`, `landuse=forest`, `building`),
  eau (`natural=water`, `waterway`), routes (`highway`). Taille (rectangle orienté minimal, corrigé du taux de
  remplissage), grand axe, distance du bord du champ à chaque type d'obstacle et obstacles dans l'axe d'approche
  sont calculés avec shapely dans une projection locale métrique. Une ligne électrique absente d'OSM n'est pas
  une preuve d'absence : la distance reste « non cartographiée » (sous-score 50 + avertissement, §12.7).
- **Fixtures de démonstration** (`app/fixtures/landing_spots.json`) : terrains FICTIFS, utilisés seulement en mode
  démo (DATA_MODE=mock, ou repli quand les sites eux-mêmes sont ceux de démonstration).

Licence OSM : © les contributeurs d'OpenStreetMap, ODbL 1.0 (https://www.openstreetmap.org/copyright).
"""

from __future__ import annotations

import math
from typing import Any

import httpx
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

from app.engine import rules
from app.engine.landings import ApproachObstacle, LandingSpot
from app.geo import LocalProjection, haversine_km
from app.models import Site
from app.providers.base import ProviderDisabled, ProviderError
from app.providers.fixture_data import load_json

OSM_ATTRIBUTION = "OpenStreetMap (Overpass) — © les contributeurs d'OpenStreetMap, licence ODbL 1.0"
OSM_COPYRIGHT_URL = "https://www.openstreetmap.org/copyright"
FIELD_LANDUSE = ("meadow", "grass", "farmland")
SURFACE_FR = {
    "meadow": "pré",
    "grass": "herbe",
    "farmland": "terre agricole (cultures possibles)",
    "grassland": "prairie naturelle",
}
ROAD_TYPES = ("motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "service",
              "track", "living_street")  # fmt: skip
MAX_FIELDS = 30  # champs retenus pour la requête d'obstacles (les plus grands, puis les plus proches)


# =============================================================================================
# Fixtures de démonstration
# =============================================================================================
def _spot_from_dict(d: dict, demo: bool, source: str) -> LandingSpot:
    kind = d.get("landing_kind", "field")
    site = Site(
        id=d["id"], name=d["name"], kind="landing", lat=float(d["lat"]), lon=float(d["lon"]),
        elevation_m=float(d.get("elevation_m", -1)), orientations=[], difficulty=None, flight_types=[],
        description=d.get("description"), access=d.get("access"), restrictions=None, status="unknown", source=source,
        url=d.get("url"), associated_landing_ids=[], official=False, landing_kind=kind,
    )  # fmt: skip
    size = d.get("size_m")
    clear = d.get("clearances_m")
    clearances: dict[str, float | None] = {}
    if isinstance(clear, dict):
        clearances = {k: (None if v is None else float(v)) for k, v in clear.items()}
    return LandingSpot(
        site=site,
        kind=kind,
        size=(float(size["length"]), float(size["width"])) if size else None,
        axis_deg=d.get("axis_deg"),
        slope_pct=d.get("slope_pct"),
        surface=d.get("surface"),
        community_usage=d.get("community_usage", "unknown"),
        access=d.get("access"),
        road_m=clearances.get("road"),
        clearances=clearances,
        clearance_bearings={k: float(v) for k, v in (d.get("clearance_bearings") or {}).items()},
        approach=[
            ApproachObstacle(float(o["bearing_deg"]), float(o["height_m"]), float(o["distance_m"]), o["label"])
            for o in d.get("approach_obstacles") or []
        ],
        demo=demo,
    )


def fixture_landing_spots(bbox: tuple[float, float, float, float] | None = None) -> list[LandingSpot]:
    """Terrains de démonstration (fictifs) dans la bbox (min_lon, min_lat, max_lon, max_lat)."""
    out = []
    for d in load_json("landing_spots.json")["spots"]:
        if bbox is not None:
            min_lon, min_lat, max_lon, max_lat = bbox
            if not (min_lat <= d["lat"] <= max_lat and min_lon <= d["lon"] <= max_lon):
                continue
        out.append(_spot_from_dict(d, demo=True, source="fixture"))
    return out


# =============================================================================================
# Overpass : requêtes
# =============================================================================================
def _bbox_clause(bbox: tuple[float, float, float, float]) -> str:
    min_lon, min_lat, max_lon, max_lat = bbox
    return f"{min_lat:.5f},{min_lon:.5f},{max_lat:.5f},{max_lon:.5f}"


def fields_query(bbox: tuple[float, float, float, float], timeout_s: int = 25) -> str:
    b = _bbox_clause(bbox)
    return (
        f"[out:json][timeout:{timeout_s}];("
        f'way["landuse"~"^({"|".join(FIELD_LANDUSE)})$"]({b});'
        f'way["natural"="grassland"]({b});'
        f'node["free_flying:site"~"landing"]({b});'
        f'way["free_flying:site"~"landing"]({b});'
        ");out geom;"
    )


def obstacles_query(way_ids: list[int], timeout_s: int = 25) -> str:
    r = rules.OSM_OBSTACLE_SEARCH_M
    near = max(r["trees_buildings"], rules.UNOFFICIAL_LANDING_MIN["approach_free_m"])  # axe d'approche : 150 m
    ids = ",".join(str(i) for i in way_ids)
    return (
        f"[out:json][timeout:{timeout_s}];way(id:{ids})->.f;("
        f'way(around.f:{r["power_line"]})["power"~"^(line|minor_line|cable)$"];'
        f'way(around.f:{r["power_line"]})["aerialway"];'
        f'way(around.f:{near})["natural"~"^(wood|tree_row)$"];'
        f'way(around.f:{near})["landuse"="forest"];'
        f'way(around.f:{near})["building"];'
        f'way(around.f:{r["water"]})["natural"="water"];'
        f'way(around.f:{r["water"]})["waterway"~"^(river|canal|stream|riverbank)$"];'
        f'way(around.f:{r["road"]})["highway"~"^({"|".join(ROAD_TYPES)})$"];'
        ");out geom;"
    )


# =============================================================================================
# Overpass : géométrie
# =============================================================================================
class _Proj:
    """Projection locale en mètres."""

    def __init__(self, lat0: float, lon0: float) -> None:
        self.p = LocalProjection(lat0, lon0)

    def xy(self, lat: float, lon: float) -> tuple[float, float]:
        x, y = self.p.to_xy(lat, lon)
        return x * 1000.0, y * 1000.0

    def latlon(self, x: float, y: float) -> tuple[float, float]:
        return self.p.to_latlon(x / 1000.0, y / 1000.0)


def _coords(el: dict) -> list[tuple[float, float]]:
    return [(g["lat"], g["lon"]) for g in el.get("geometry") or [] if "lat" in g and "lon" in g]


def _geom(el: dict, proj: _Proj, area: bool) -> BaseGeometry | None:
    pts = [proj.xy(la, lo) for la, lo in _coords(el)]
    if len(pts) < 2:
        return None
    closed = len(pts) >= 4 and pts[0] == pts[-1]
    if area and closed:
        poly = Polygon(pts)
        return poly if poly.is_valid else poly.buffer(0)
    return LineString(pts)


def obstacle_category(tags: dict) -> tuple[str, str, float] | None:
    """(catégorie de distance minimale, libellé, hauteur typique m) d'un obstacle OSM."""
    h = rules.OBSTACLE_TYPICAL_HEIGHT_M
    if tags.get("power") in ("line", "minor_line", "cable"):
        return "power_line", "ligne électrique", h["power_line"]
    if "aerialway" in tags:
        return "power_line", "câble (remontée mécanique)", h["aerialway"]
    if tags.get("natural") in ("wood", "tree_row") or tags.get("landuse") == "forest":
        return "trees_buildings", "forêt", h["forest"]
    if "building" in tags:
        return "trees_buildings", "bâtiment", h["building"]
    if tags.get("natural") == "water" or "waterway" in tags:
        return "water", "eau", 0.0
    if tags.get("highway") in ROAD_TYPES:
        return "road", "route", 0.0
    return None


def field_dimensions(poly: Polygon) -> tuple[float, float, float]:
    """(longueur, largeur, axe en degrés 0..180) : rectangle orienté minimal, dimensions réduites de √(taux de
    remplissage) quand le champ est irrégulier (prudence : la surface réellement posable est plus petite)."""
    rect = poly.minimum_rotated_rectangle
    c = list(rect.exterior.coords)
    e1 = (c[1][0] - c[0][0], c[1][1] - c[0][1])
    e2 = (c[2][0] - c[1][0], c[2][1] - c[1][1])
    l1, l2 = math.hypot(*e1), math.hypot(*e2)
    long_e = e1 if l1 >= l2 else e2
    length, width = max(l1, l2), min(l1, l2)
    fill = poly.area / rect.area if rect.area > 0 else 1.0
    if fill < 0.85:
        k = math.sqrt(max(0.3, fill))
        length, width = length * k, width * k
    axis = (math.degrees(math.atan2(long_e[0], long_e[1])) + 360.0) % 180.0
    return length, width, axis


def _bearing_xy(a: tuple[float, float], b: tuple[float, float]) -> float:
    return (math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) + 360.0) % 360.0


def analyze_field(poly: Polygon, obstacles: list[tuple[BaseGeometry, str, str, float]]) -> dict[str, Any]:
    """Distances du bord du champ aux obstacles (par catégorie), caps, obstacles dans l'axe d'approche."""
    length, width, axis = field_dimensions(poly)
    cen = (poly.centroid.x, poly.centroid.y)
    clear: dict[str, float | None] = {}
    bearings: dict[str, float] = {}
    for cat in ("power_line", "trees_buildings", "water", "road"):
        best: tuple[float, BaseGeometry] | None = None
        for g, c, _, _ in obstacles:
            if c != cat:
                continue
            d = poly.distance(g)
            if best is None or d < best[0]:
                best = (d, g)
        if best is None:
            if cat != "power_line":  # ligne électrique non trouvée ≠ absente (OSM incomplet) : clé absente
                clear[cat] = None
            continue
        clear[cat] = round(best[0], 0)
        p = nearest_points(poly, best[1])[1]
        bearings[cat] = round(_bearing_xy(cen, (p.x, p.y)))
    approach: list[ApproachObstacle] = []
    free_m = rules.UNOFFICIAL_LANDING_MIN["approach_free_m"]
    for side in (axis, (axis + 180.0) % 360.0):
        ux, uy = math.sin(math.radians(side)), math.cos(math.radians(side))
        end = (cen[0] + ux * length / 2.0, cen[1] + uy * length / 2.0)
        corridor = LineString([end, (end[0] + ux * free_m, end[1] + uy * free_m)]).buffer(width / 2.0, cap_style=2)
        worst: ApproachObstacle | None = None
        for g, cat, label, h in obstacles:
            if cat not in ("power_line", "trees_buildings") or h <= 0 or not g.intersects(corridor):
                continue
            d = poly.distance(g.intersection(corridor))
            ob = ApproachObstacle(round(side), h, round(d), label)
            if worst is None or (h * 5 - d) > (worst.height_m * 5 - worst.distance_m):
                worst = ob
        if worst is not None:
            approach.append(worst)
    return {"length": length, "width": width, "axis": axis, "clearances": clear, "bearings": bearings,
            "approach": approach}  # fmt: skip


def parse_fields(data: dict, center: tuple[float, float]) -> tuple[list[dict], list[dict]]:
    """Réponse Overpass (1re requête) → (champs candidats, atterros vol libre isolés). Champs ≥ 100 × 30 m."""
    if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
        raise ProviderError("Overpass : réponse sans 'elements'")
    proj = _Proj(*center)
    fields: list[dict] = []
    ff: list[dict] = []
    lmin, wmin = rules.FIELD_MIN_DETECT_M
    for el in data["elements"]:
        tags = el.get("tags") or {}
        is_ff = "landing" in str(tags.get("free_flying:site", ""))
        if el.get("type") == "node" and is_ff:
            ff.append({"id": f"osm:node/{el['id']}", "lat": el["lat"], "lon": el["lon"], "name": tags.get("name")})
            continue
        if el.get("type") != "way":
            continue
        g = _geom(el, proj, area=True)
        if not isinstance(g, Polygon) or g.is_empty:
            if is_ff and g is not None:
                c = g.centroid
                la, lo = proj.latlon(c.x, c.y)
                ff.append({"id": f"osm:way/{el['id']}", "lat": la, "lon": lo, "name": tags.get("name")})
            continue
        length, width, axis = field_dimensions(g)
        if not is_ff and (length < lmin or width < wmin):
            continue
        c = g.centroid
        la, lo = proj.latlon(c.x, c.y)
        land = tags.get("landuse") or tags.get("natural") or "meadow"
        fields.append({
            "way_id": int(el["id"]), "id": f"osm:way/{el['id']}", "lat": la, "lon": lo, "poly": g,
            "length": length, "width": width, "axis": axis, "surface": SURFACE_FR.get(land, "prairie"),
            "name": tags.get("name"), "free_flying": is_ff, "crop": land == "farmland",
        })  # fmt: skip
    # un atterro vol libre (nœud) posé dans un champ fait du champ un atterro communautaire
    for f in ff[:]:
        p = Point(*proj.xy(f["lat"], f["lon"]))
        host = next((x for x in fields if x["poly"].buffer(20).contains(p)), None)
        if host is not None:
            host["free_flying"] = True
            host["name"] = host["name"] or f.get("name")
            ff.remove(f)
    return fields, ff


def parse_obstacles(data: dict, center: tuple[float, float]) -> list[tuple[BaseGeometry, str, str, float]]:
    if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
        raise ProviderError("Overpass : réponse sans 'elements'")
    proj = _Proj(*center)
    out = []
    for el in data["elements"]:
        if el.get("type") != "way":
            continue
        tags = el.get("tags") or {}
        cat = obstacle_category(tags)
        if cat is None:
            continue
        g = _geom(el, proj, area=cat[0] in ("trees_buildings", "water") and "waterway" not in tags)
        if g is None or g.is_empty:
            continue
        out.append((g, *cat))
    return out


def build_spots(fields: list[dict], ff: list[dict], obstacles, center: tuple[float, float]) -> list[LandingSpot]:
    out: list[LandingSpot] = []
    for f in fields:
        a = analyze_field(f["poly"], obstacles)
        kind = "community" if f["free_flying"] else "field"
        name = f["name"] or ("Atterro vol libre OSM" if kind == "community" else f"Champ OSM ({f['surface']})")
        site = Site(
            id=f["id"], name=name, kind="landing", lat=round(f["lat"], 6), lon=round(f["lon"], 6), elevation_m=-1.0,
            orientations=[], difficulty=None, flight_types=[], description=None, access=None, restrictions=None,
            status="unknown", source="osm", url=f"https://www.openstreetmap.org/way/{f['way_id']}",
            associated_landing_ids=[], official=False, landing_kind=kind,
        )  # fmt: skip
        road = a["clearances"].get("road")
        out.append(LandingSpot(
            site=site, kind=kind, size=(round(a["length"]), round(a["width"])), axis_deg=round(a["axis"]),
            slope_pct=None, surface=f["surface"], community_usage="unknown",
            access=None if road is None else f"route à {road:.0f} m", road_m=road, clearances=a["clearances"],
            clearance_bearings=a["bearings"], approach=a["approach"],
        ))  # fmt: skip
    for f in ff:
        site = Site(
            id=f["id"], name=f.get("name") or "Atterro vol libre (OSM)", kind="landing", lat=round(f["lat"], 6),
            lon=round(f["lon"], 6), elevation_m=-1.0, orientations=[], difficulty=None, flight_types=[],
            description=None, access=None, restrictions=None, status="unknown", source="osm",
            url=f"https://www.openstreetmap.org/{f['id'].split(':', 1)[1]}", associated_landing_ids=[],
            official=False, landing_kind="community",
        )  # fmt: skip
        out.append(LandingSpot(site=site, kind="community", community_usage="unknown"))
    return out


class OverpassLandings:
    """Adaptateur Overpass (désactivé par défaut : l'API n'est pas joignable depuis tous les environnements)."""

    name = "OpenStreetMap (Overpass)"

    def __init__(self, client: httpx.AsyncClient, url: str, enabled: bool, timeout_s: float = 25.0) -> None:
        self.client = client
        self.url = url
        self.enabled = enabled
        self.timeout_s = timeout_s

    async def _post(self, query: str) -> dict:
        try:
            r = await self.client.post(self.url, data={"data": query}, timeout=self.timeout_s + 5)
        except httpx.HTTPError as e:
            raise ProviderError(f"Overpass injoignable : {type(e).__name__}: {e}") from e
        if r.status_code != 200:
            err = ProviderError(f"Overpass : HTTP {r.status_code} {r.text[:120]!r}")
            err.http_status = r.status_code
            raise err
        try:
            return r.json()
        except ValueError as e:
            raise ProviderError("Overpass : réponse non JSON") from e

    async def fetch(self, bbox: tuple[float, float, float, float], center: tuple[float, float]) -> list[LandingSpot]:
        if not self.enabled:
            raise ProviderDisabled("Overpass désactivé (OVERPASS_ENABLED=false)")
        fields, ff = parse_fields(await self._post(fields_query(bbox, int(self.timeout_s))), center)
        fields.sort(key=lambda f: (-(f["free_flying"]), haversine_km(center[0], center[1], f["lat"], f["lon"])))
        fields = fields[:MAX_FIELDS]
        obstacles = []
        if fields:
            obstacles = parse_obstacles(
                await self._post(obstacles_query([f["way_id"] for f in fields], int(self.timeout_s))), center
            )
        return build_spots(fields, ff, obstacles, center)
