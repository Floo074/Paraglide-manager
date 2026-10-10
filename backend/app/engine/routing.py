"""Construction des routes (plouf, local thermique, soaring, cross) et contrôles de finesse.

Formules (cahier des charges §2.3, §5, §14) :
- finesse de calcul sol (§14, `app.engine.glidewind`) : vent RENCONTRÉ sur chaque branche du plané (tranches d'altitude
  traversées, brise d'atterro à l'heure d'arrivée, vent du déco, profil au-dessus du déco), travers payé
  (V_sol = √(V² − w⊥²) + w∥), vent arrière crédité en partie, face majorée par les rafales, accélérateur selon le
  niveau ; f_plané = L / Σ (L_i / f_i) ;
- hauteur disponible = altitude du point − (altitude atterro + marge d'arrivée), marge bornée à 25 %
  du dénivelé ; required_ratio = longueur réelle du chemin / hauteur disponible ; margin_ok = required ≤ available ;
- cross : « toujours un atterro dans le cône » vérifié tous les 500 m :
  alt_sécurité(p) = min_a [alt_a + marge + dist(p, a) / finesse_sol(p→a)] ≤ plafond utile − 300 m.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import pairwise

from app.engine import rules
from app.engine.airspace import Projector, route_conflicts, route_sensitive_conflict
from app.engine.conditions import dir_label
from app.engine.context import DataContext, ReliefPoint
from app.engine.glidewind import (
    GlideWind,
    as_source,
    au,
    compute_glide,
    legs_of,
    plouf_minutes,
    quarter,
    uniform_finesse,
    zpa_bearings,
)
from app.geo import angle_diff, bearing_deg, destination, haversine_km, sector_to_deg
from app.meteo.solar import sun_azimuth_deg, sun_elevation_deg
from app.models import Site, Waypoint

Coord = tuple[float, float, float]  # (lon, lat, alt) — ordre GeoJSON


@dataclass(slots=True)
class GlideCheck:
    required_ratio: float
    available_ratio: float
    margin_ok: bool
    terrain_ok: bool = True
    landing_name: str | None = None
    calm_ratio: float = 0.0  # finesse de calcul en air calme (même k, même f), §14.7
    wind: GlideWind | None = None  # vent sur le plané (§14) ; None : top landing ou glide non calculé
    expected_arrival_m: float | None = None  # hauteur d'arrivée attendue (vent prévu à 100 %, 0,90 × polaire)
    dist_km: float = 0.0  # longueur réelle du chemin (contournements compris)
    level: str = ""
    detour_zones: list[str] | None = None  # zones interdites contournées par ce plané

    @property
    def penetration_ok(self) -> bool:
        return self.wind is None or self.wind.penetration_ok

    @property
    def ratio(self) -> float:
        if self.available_ratio <= 0 or not self.penetration_ok:
            return 9.9
        return self.required_ratio / self.available_ratio

    @property
    def wind_along_kmh(self) -> float | None:
        return None if self.wind is None else self.wind.along_kmh

    @property
    def wind_credit_kmh(self) -> float:
        return 0.0 if self.wind is None else self.wind.credit_kmh


def calm_glide(wing: float, level: str, landing_name: str | None = None, pair: bool = False) -> GlideCheck:
    """Top landing (posé au décollage) : pas de plané, finesse de calcul en air calme pour mémoire."""
    k = rules.GLIDE_K_ASSOCIATED_PAIR if pair else rules.GLIDE_K[level]
    return GlideCheck(0.0, wing * k, True, True, landing_name, calm_ratio=wing * k, level=level)


@dataclass
class Route:
    kind: str  # plouf | local_thermal | ridge | out_and_return | triangle | fai_triangle
    coords: list[Coord]
    waypoints: list[Waypoint]
    distance_km: float
    max_altitude_m: float
    glide: GlideCheck
    decision_points: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    first_leg_bearing: float | None = None
    xc_subtype: str | None = None  # out_and_return | triangle | fai_triangle
    used_landings: list[Site] = field(default_factory=list)  # cross : atterros qui couvrent la route (cône)
    glide_dist_km: float | None = None  # plané déco → atterro allongé par un contournement de zone interdite
    avoided_zones: list[str] = field(default_factory=list)  # zones interdites contournées (briefing)
    glide_path: list[tuple[float, float]] = field(default_factory=list)  # points du contournement (lat, lon)
    glide_zones: list[str] = field(default_factory=list)  # zones contournées par le plané déco → atterro
    zpa_bearing: float | None = None  # relèvement atterro → zone de perte d'altitude (plouf)


# ---------------------------------------------------------------------------------------------
# Finesse
# ---------------------------------------------------------------------------------------------
def finesse_sol(
    wing: float, level: str, wind_speed: float, wind_dir: float, track: float, pair: bool = False
) -> float:
    """Finesse de calcul sol par un vent UNIFORME sur le cap `track` (§14 : polaire, travers payé, vent arrière crédité
    à la part de base du niveau et plafonné, face comptée en entier, accélérateur du niveau). `pair` : plané direct
    déco → atterro officiel associé par la source (k = GLIDE_K_ASSOCIATED_PAIR, décision expert 7.13) ; sinon k du
    niveau (§11). Les planés du plan utilisent le vent rencontré (`glide_to`)."""
    k = rules.GLIDE_K_ASSOCIATED_PAIR if pair else rules.GLIDE_K[level]
    return uniform_finesse(wing, level, k, wind_speed, wind_dir, track)


def arrival_margin(level: str, drop_m: float) -> float:
    return min(rules.LANDING_ARRIVAL_MARGIN_M[level], rules.LANDING_ARRIVAL_MARGIN_MAX_FRACTION * max(0.0, drop_m))


def landing_kind_of(site: Site) -> str:
    """Catégorie d'atterro (contrat `LandingKind`) : déduite de `official` si la source ne la donne pas."""
    return site.landing_kind or ("official" if site.official else "community")


def kind_glide_params(kind: str, level: str, drop_m: float) -> tuple[float, float]:
    """(marge d'arrivée m, facteur de finesse) : atterro officiel = marge du §2.3 bornée à 25 % du dénivelé ;
    communautaire / champ = hauteur d'arrivée mini et facteur f du CDC §12.7 (niveau élève : valeurs brevet)."""
    if kind == "official":
        return arrival_margin(level, drop_m), 1.0
    g = rules.UNOFFICIAL_GLIDE
    lv = level if level in g["arrival_height_min_m"][kind] else "intermediate"
    return float(g["arrival_height_min_m"][kind][lv]), float(g["available_factor"][kind])


def _glide_wind(
    ctx: DataContext,
    src,
    lat: float,
    lon: float,
    alt: float,
    landing: Site,
    level: str,
    wing: float,
    k: float,
    factor: float,
    za: float,
    path: list[tuple[float, float]] | None,
    t: datetime | None,
    t_arrival: datetime | None,
) -> tuple[list[tuple[float, float]], GlideWind]:
    pts = [(lat, lon), *(path or []), (landing.lat, landing.lon)]
    legs = legs_of(pts)
    t0 = t if t is not None else getattr(src, "start", None)
    ta = t_arrival
    if ta is None and t0 is not None:
        ta = t0 + timedelta(minutes=plouf_minutes(alt - landing.elevation_m))
    col = src.column(landing, t0, ta, alt)
    credit = src.credit(landing, t0, ta, (lat, lon))
    return pts, compute_glide(legs, alt, za, col, credit, level, wing, k, factor)


def glide_to(
    ctx: DataContext,
    lat: float,
    lon: float,
    alt: float,
    landing: Site,
    level: str,
    wing: float,
    wind,
    drop_ref: float | None = None,
    kind: str | None = None,
    pair: bool = False,
    path: list[tuple[float, float]] | None = None,
    t: datetime | None = None,
    t_arrival: datetime | None = None,
    detour_zones: list[str] | None = None,
) -> GlideCheck:
    """Plané vers un atterro (§14) : `wind` = champ de vent du vol (`GlideField`, vent rencontré) ou (vitesse,
    direction) uniforme ; `path` = points intermédiaires du chemin (contournement), `t` = heure de départ du point,
    `t_arrival` = heure d'arrivée (défaut : t + durée d'un plouf de ce dénivelé). Atterro non officiel (§12.7) :
    hauteur d'arrivée mini du kind au lieu de la marge standard, et finesse × f (0,90 communautaire, 0,80 champ).
    `kind="official"` force les règles d'un atterro officiel (portée « géométrique » d'un candidat). `pair` : plané
    direct déco → atterro officiel associé par la source ; k = GLIDE_K_ASSOCIATED_PAIR seulement si le relief est
    vérifié (`pair_k_allowed`)."""
    src = as_source(wind)
    k_kind = kind or landing_kind_of(landing)
    margin, factor = kind_glide_params(
        k_kind, level, drop_ref if drop_ref is not None else alt - landing.elevation_m
    )
    za = landing.elevation_m + margin
    height = alt - za
    use_pair = pair and k_kind == "official" and pair_k_allowed(ctx)
    k = rules.GLIDE_K_ASSOCIATED_PAIR if use_pair else rules.GLIDE_K[level]
    pts, gw = _glide_wind(ctx, src, lat, lon, alt, landing, level, wing, k, factor, za, path, t, t_arrival)
    dist_km = sum(d for d, _ in legs_of(pts))
    available = gw.available
    required = dist_km * 1000.0 / height if height > 1 else 99.0
    terrain_ok = terrain_clear(ctx, pts, alt, gw.leg_ratios)
    drop = alt - landing.elevation_m
    expected = drop - gw.expected_loss_m if gw.expected_loss_m != math.inf else -drop
    return GlideCheck(
        required_ratio=required,
        available_ratio=available,
        margin_ok=required <= available and terrain_ok and gw.penetration_ok,
        terrain_ok=terrain_ok,
        landing_name=landing.name,
        calm_ratio=gw.calm,
        wind=gw,
        expected_arrival_m=max(-drop, expected),
        dist_km=dist_km,
        level=level,
        detour_zones=detour_zones,
    )


def pair_k_allowed(ctx: DataContext) -> bool:
    """k « paire associée » (7.13) : relief vérifié sur MNT réel (live) ; en démo / scénario de test, les données
    de la fixture sont réputées exactes (couple déco / atterro de référence)."""
    return (ctx.terrain is not None and ctx.terrain_is_real) or ctx.mock or ctx.exact_inputs


def is_source_pair(takeoff: Site, landing: Site) -> bool:
    """L'atterro est-il associé au déco PAR LA SOURCE (FFVL, PGE, fixture) et non déduit par proximité ?"""
    return (
        landing.id in takeoff.associated_landing_ids
        and landing.id not in takeoff.deduced_landing_ids
        and landing_kind_of(landing) == "official"
    )


def terrain_clear(ctx: DataContext, pts: list[tuple[float, float]], alt: float, finesses: list[float]) -> bool:
    """La ligne de plané (pente 1/finesse de chaque branche, le long du chemin réel) reste-t-elle ≥ 50 m au-dessus du
    terrain ? MNT réel seulement ; on ignore les 500 premiers mètres et les 600 derniers (pente du déco, approche)."""
    if ctx.terrain is None or not ctx.terrain_is_real or not finesses or min(finesses) <= 0:
        return True
    legs = [(a, b, haversine_km(a[0], a[1], b[0], b[1])) for a, b in pairwise(pts)]
    legs = [x for x in legs if x[2] > 1e-4]
    total = sum(x[2] for x in legs)
    if total < 1.0 or len(legs) != len(finesses):
        return True
    s0, z0 = 0.0, alt
    for (a, b, dist), fin in zip(legs, finesses, strict=True):
        brg = bearing_deg(a[0], a[1], b[0], b[1])
        n = max(1, int(dist / 0.25))
        for i in range(1, n + 1):
            d = dist * i / n
            s = s0 + d
            if s < 0.5 or total - s < 0.6:
                continue
            la, lo = destination(a[0], a[1], brg, d)
            terrain = ctx.terrain_at(la, lo)
            if terrain is None:
                continue
            if z0 - d * 1000.0 / fin < terrain + rules.TERRAIN_CLEARANCE_M:
                return False
        s0 += dist
        z0 -= dist * 1000.0 / fin
    return True


def best_landing_glide(
    ctx: DataContext,
    lat: float,
    lon: float,
    alt: float,
    landings: list[Site],
    level: str,
    wing: float,
    wind,
    t: datetime | None = None,
) -> tuple[GlideCheck | None, float]:
    """Meilleur atterro joignable depuis un point (vent rencontré vers chaque atterro, §14) ; renvoie (glide,
    altitude de sécurité)."""
    src = as_source(wind)
    best_ldg: Site | None = None
    best_alt = 1e9
    k = rules.GLIDE_K[level]
    for ldg in landings:
        margin = arrival_margin(level, alt - ldg.elevation_m)
        pts, gw = _glide_wind(ctx, src, lat, lon, alt, ldg, level, wing, k, 1.0, ldg.elevation_m + margin, None, t,
                              None)  # fmt: skip
        if gw.available <= 0 or not gw.penetration_ok:
            continue
        dist_m = sum(d for d, _ in legs_of(pts)) * 1000.0
        alt_sec = ldg.elevation_m + margin + dist_m / gw.available
        if alt_sec < best_alt:
            best_alt = alt_sec
            best_ldg = ldg
    if best_ldg is None:
        return None, best_alt
    return glide_to(ctx, lat, lon, alt, best_ldg, level, wing, src, t=t), best_alt


def transition_finesse(
    src, lat1: float, lon1: float, lat2: float, lon2: float, z_hi: float, z_lo: float, landing: Site, level: str,
    wing: float, t: datetime | None,
) -> float:
    """Finesse de calcul sol d'une transition en altitude (point A → point B, tranche [z_lo ; z_hi]), vent rencontré
    de la colonne de l'atterro de repli (§14.1)."""
    src = as_source(src)
    legs = legs_of([(lat1, lon1), (lat2, lon2)])
    if not legs:
        return wing * rules.GLIDE_K[level]
    col = src.column(landing, t, None, z_hi)
    credit = src.credit(landing, t, None, (lat1, lon1))
    return compute_glide(legs, z_hi, z_lo, col, credit, level, wing, rules.GLIDE_K[level]).available


def projector_for(ctx: DataContext, site: Site) -> Projector:
    """Projection locale centrée sur un décollage, partagée (les caches de contournement sont indexés par elle)."""
    key = ("projector", site.id, round(site.lat, 5), round(site.lon, 5))
    proj = ctx.station_cache.get(key)
    if proj is None:
        proj = Projector(site.lat, site.lon)
        ctx.station_cache[key] = proj
    return proj


def path_for(
    ctx: DataContext, proj: Projector | None, lat: float, lon: float, landing: Site
) -> tuple[list[tuple[float, float]], list[str]]:
    """Chemin d'un plané qui évite les zones où le vol libre est interdit : (points intermédiaires, zones)."""
    if proj is None:
        return [], []
    d = detour(ctx, proj, (lat, lon), (landing.lat, landing.lon))
    if d is None or not d[0]:
        return [], []
    return list(d[0]), list(d[2])


# ---------------------------------------------------------------------------------------------
# Outils
# ---------------------------------------------------------------------------------------------
def path_length_km(coords: list[Coord]) -> float:
    return sum(
        haversine_km(a[1], a[0], b[1], b[0]) for a, b in pairwise(coords)
    )


def face_is_sunny(faces: list[str], t: datetime, lat: float, lon: float) -> bool:
    """Face au soleil (I17) : soleil > 5° et azimut à moins de 100° de l'orientation de la face."""
    if sun_elevation_deg(t, lat, lon) <= 5.0:
        return False
    if not faces:
        return True
    az = sun_azimuth_deg(t, lat, lon)
    # une face orientée X « regarde » vers X ; le vent favorable vient aussi de X
    return any(angle_diff(az, sector_to_deg(f)) <= 100.0 for f in faces)


def face_toward(faces: list[str], direction: float) -> float:
    if not faces:
        return 90.0
    return min(angle_diff(direction, sector_to_deg(f)) for f in faces)


def site_axis(site: Site) -> float:
    """Orientation moyenne du déco (direction vers laquelle il fait face)."""
    if not site.orientations:
        return 0.0
    xs = sum(math.sin(math.radians(sector_to_deg(o))) for o in site.orientations)
    ys = sum(math.cos(math.radians(sector_to_deg(o))) for o in site.orientations)
    return (math.degrees(math.atan2(xs, ys)) + 360.0) % 360.0


def _wp(
    name: str, lat: float, lon: float, alt: float, typ: str, radius: float | None, eta: float | None, note=None
) -> Waypoint:
    return Waypoint(
        name=name,
        lat=round(lat, 6),
        lon=round(lon, 6),
        altitude_m=round(alt),
        type=typ,
        radius_m=radius,
        eta_min=None if eta is None else round(eta, 1),
        note=note,
    )


def alternates_waypoints(alternates: list[Site], eta: float | None = None) -> list[Waypoint]:
    return [
        _wp(a.name, a.lat, a.lon, a.elevation_m, "alternate_landing", rules.GOAL_RADIUS_M, None, "Atterrissage de "
                                                                                                 "secours")
        for a in alternates
    ]


# ---------------------------------------------------------------------------------------------
# Contournement des zones où le vol libre est interdit (revue 7.4)
# ---------------------------------------------------------------------------------------------
DETOUR_CLEARANCE_KM = 0.15  # marge latérale autour d'une zone interdite
DETOUR_SIMPLIFY_KM = 0.05


def _obstacles(ctx: DataContext, proj: Projector):
    """(union des zones interdites élargies de la marge, union « intérieure » pour les tests de croisement, noms)."""
    from shapely.ops import unary_union

    from app.engine.airspace import prohibited_areas

    key = ("detour-obstacles", id(proj))
    hit = ctx.station_cache.get(key)
    if hit is not None:
        return hit
    areas = prohibited_areas(ctx)
    if not areas:
        res = (None, None, [])
    else:
        geoms = [proj.geom(a.geometry).buffer(DETOUR_CLEARANCE_KM).simplify(DETOUR_SIMPLIFY_KM) for a in areas]
        union = unary_union(geoms)
        res = (union, union.buffer(-0.005), [a.name for a in areas])
    ctx.station_cache[key] = res
    return res


def detour(ctx: DataContext, proj: Projector, a: tuple[float, float], b: tuple[float, float]):
    """Chemin le plus court de a à b (lat, lon) qui évite les zones interdites (graphe de visibilité sur les sommets
    des zones élargies) : (points intermédiaires (lat, lon), longueur km, zones contournées) ; None si impossible."""
    from shapely.geometry import LineString, MultiPolygon

    union, inner, _ = _obstacles(ctx, proj)
    pa, pb = proj.proj.to_xy(*a), proj.proj.to_xy(*b)
    direct = math.dist(pa, pb)
    if union is None or not LineString([pa, pb]).intersects(inner):
        return [], direct, []
    key = ("detour", id(proj), round(pa[0], 3), round(pa[1], 3), round(pb[0], 3), round(pb[1], 3))
    hit = ctx.station_cache.get(key)
    if hit is not None:
        return hit
    polys = list(union.geoms) if isinstance(union, MultiPolygon) else [union]
    nodes = [pa, pb] + [c for poly in polys for c in list(poly.exterior.coords)[:-1]]
    n = len(nodes)
    dist = [math.inf] * n
    prev = [-1] * n
    dist[0] = 0.0
    done = [False] * n
    for _ in range(n):
        u = min((i for i in range(n) if not done[i]), key=lambda i: dist[i], default=None)
        if u is None or dist[u] == math.inf or u == 1:
            break
        done[u] = True
        for v in range(n):
            if done[v] or v == u:
                continue
            d = dist[u] + math.dist(nodes[u], nodes[v])
            if d >= dist[v]:
                continue
            if LineString([nodes[u], nodes[v]]).intersects(inner):
                continue
            dist[v], prev[v] = d, u
    if dist[1] == math.inf:
        res = None
    else:
        path, i = [], prev[1]
        while i > 0:
            path.append(nodes[i])
            i = prev[i]
        pts = [proj.proj.to_latlon(x, y) for x, y in reversed(path)]
        res = (pts, dist[1], _crossed_names(ctx, proj, pa, pb))
    ctx.station_cache[key] = res
    return res


def _crossed_names(ctx: DataContext, proj: Projector, pa, pb) -> list[str]:
    from shapely.geometry import LineString

    from app.engine.airspace import prohibited_areas

    line = LineString([pa, pb])
    return [a.name for a in prohibited_areas(ctx) if proj.geom(a.geometry).buffer(DETOUR_CLEARANCE_KM).intersects(line)]


def inside_prohibited(ctx: DataContext, proj: Projector, lat: float, lon: float) -> bool:
    from shapely.geometry import Point

    union, _, _ = _obstacles(ctx, proj)
    return union is not None and union.contains(Point(*proj.proj.to_xy(lat, lon)))


def apply_detours(ctx: DataContext, proj: Projector, route: Route, takeoff: Site, landing: Site) -> Route:
    """Insère dans la route les points de contournement des zones interdites (segment par segment) et donne au plané
    déco → atterro son chemin réel (branches du contournement, §14.1). Un segment impossible à dévier reste tel quel
    (le constat le rejette)."""
    union, _, _ = _obstacles(ctx, proj)
    if union is None:
        return route
    if landing.id != takeoff.id:
        g = detour(ctx, proj, (takeoff.lat, takeoff.lon), (landing.lat, landing.lon))
        if g is not None and g[0]:
            route.glide_dist_km = g[1]
            route.glide_path = list(g[0])
            route.glide_zones = list(g[2])
    coords: list[Coord] = [route.coords[0]]
    zones: list[str] = []
    for a, b in pairwise(route.coords):
        d = detour(ctx, proj, (a[1], a[0]), (b[1], b[0]))
        if d is not None and d[0]:
            seg = math.dist(proj.proj.to_xy(a[1], a[0]), proj.proj.to_xy(b[1], b[0]))
            for k, (la, lo) in enumerate(d[0]):
                f = (k + 1) / (len(d[0]) + 1)
                coords.append((lo, la, a[2] + f * (b[2] - a[2]) if seg > 0 else a[2]))
            zones += d[2]
        coords.append(b)
    if len(coords) == len(route.coords):
        return route
    route.coords = coords
    route.distance_km = path_length_km(coords)
    route.avoided_zones = list(dict.fromkeys(zones + route.avoided_zones))
    return route


def lose_height_point(
    ctx: DataContext, proj: Projector | None, landing: Site, arrival_from: float, landing_wind: tuple[float, float]
) -> tuple[float, float, float]:
    """Zone de perte d'altitude (§14.4, corrige le §5.1) : au vent de l'atterro, décalée du côté d'où arrive le
    pilote (± 45°), en travers (± 90°) si ce secteur est interdit ; jamais sous le vent. Vent < 5 km/h : côté
    d'arrivée. Renvoie (lat, lon, relèvement atterro → ZPA)."""
    z = rules.LOSE_HEIGHT_ZONE
    lo_km, hi_km = z["distance_m"][0] / 1000.0, z["distance_m"][1] / 1000.0
    dists = [rules.PLOUF_LOSE_HEIGHT_POINT_KM, lo_km, hi_km]
    brgs = zpa_bearings(landing_wind[0], landing_wind[1], arrival_from)
    for brg in brgs:
        for d in dists:
            la, lo = destination(landing.lat, landing.lon, brg, d)
            if proj is None or not inside_prohibited(ctx, proj, la, lo):
                return la, lo, brg
    la, lo = destination(landing.lat, landing.lon, brgs[0], dists[0])
    return la, lo, brgs[0]


# ---------------------------------------------------------------------------------------------
# Plouf / descente
# ---------------------------------------------------------------------------------------------
def build_plouf(
    ctx: DataContext,
    takeoff: Site,
    landing: Site,
    alternates: list[Site],
    level: str,
    wing: float,
    glide_wind,
    landing_wind: tuple[float, float],
    duration_min: float,
    top_landing: bool = False,
    proj: Projector | None = None,
    t_start: datetime | None = None,
) -> Route:
    """Plouf déco → atterro. `glide_wind` : champ de vent du vol (§14) ; `landing_wind` : vent retenu à l'atterro à
    l'heure d'arrivée (place la zone de perte d'altitude AU VENT de l'atterro, §14.4)."""
    arrival_from = bearing_deg(landing.lat, landing.lon, takeoff.lat, takeoff.lon)
    lla, llo, lose_brg = lose_height_point(ctx, proj, landing, arrival_from, landing_wind)
    lose_alt = landing.elevation_m + max(rules.PLOUF_LOSE_HEIGHT_MIN_AGL_M, 250.0)
    coords: list[Coord] = [
        (takeoff.lon, takeoff.lat, takeoff.elevation_m),
        (llo, lla, lose_alt),
        (landing.lon, landing.lat, landing.elevation_m),
    ]
    if top_landing:
        coords = [(takeoff.lon, takeoff.lat, takeoff.elevation_m), (landing.lon, landing.lat, landing.elevation_m)]
    dist = path_length_km(coords)
    glide = (
        calm_glide(wing, level, landing.name)
        if top_landing
        else glide_to(ctx, takeoff.lat, takeoff.lon, takeoff.elevation_m, landing, level, wing, glide_wind,
                      pair=is_source_pair(takeoff, landing), t=t_start)
    )  # fmt: skip
    wps = [
        _wp(takeoff.name, takeoff.lat, takeoff.lon, takeoff.elevation_m, "takeoff", rules.TAKEOFF_RADIUS_M, 0.0),
    ]
    if not top_landing:
        min_agl = rules.LOSE_HEIGHT_ZONE["min_agl_m"]
        if landing_wind[0] >= rules.LOSE_HEIGHT_ZONE["calm_kmh"]:
            note = (f"Au vent de l'atterro ({au(dir_label(lose_brg))} de {landing.name}), décalée sur le côté, "
                    f"≥ {min_agl} m sol : perds l'altitude en 8 face au vent, jamais derrière l'atterro, puis PTU")
        else:
            note = f"Côté d'arrivée ({au(dir_label(lose_brg))} de {landing.name}), ≥ {min_agl} m sol, puis PTU"
        wps.append(
            _wp(
                "Zone de perte d'altitude",
                lla,
                llo,
                lose_alt,
                "turnpoint",
                rules.TURNPOINT_RADIUS_M,
                max(0.0, duration_min - 4.0),
                note,
            )
        )  # fmt: skip
    wps.append(
        _wp(landing.name, landing.lat, landing.lon, landing.elevation_m, "landing", rules.GOAL_RADIUS_M, duration_min)
    )
    wps += alternates_waypoints(alternates)
    route = Route("plouf", coords, wps, dist, takeoff.elevation_m, glide)
    route.zpa_bearing = None if top_landing else lose_brg
    return route


# ---------------------------------------------------------------------------------------------
# Vol local thermique
# ---------------------------------------------------------------------------------------------
def _local_trigger_candidates(
    ctx: DataContext, takeoff: Site, t: datetime, usable: float
) -> list[ReliefPoint]:
    out: list[ReliefPoint] = []
    for p in ctx.relief:
        if p.valley:
            continue
        d = haversine_km(takeoff.lat, takeoff.lon, p.lat, p.lon)
        if not (0.8 <= d <= rules.LOCAL_LOOP_KM[1] / 2):
            continue
        if p.elevation_m > usable - 150:
            continue
        out.append(p)
    # points heuristiques sur l'axe de la crête (perpendiculaire à l'orientation du déco)
    if ctx.terrain is not None:
        axis = site_axis(takeoff)
        for side in (-90.0, 90.0):
            for dist in (1.5, 2.5):
                la, lo = destination(takeoff.lat, takeoff.lon, (axis + side) % 360, dist)
                # léger décalage vers l'arrière (relief) pour viser l'éperon plutôt que la pente basse
                la, lo = destination(la, lo, (axis + 180.0) % 360, 0.3)
                elev = ctx.terrain_at(la, lo)
                if elev is None or elev < takeoff.elevation_m - 250 or elev > usable - 150:
                    continue
                out.append(
                    ReliefPoint(
                        name=f"Crête {dir_label((axis + side) % 360)} du déco ({dist:.1f} km)",
                        lat=la,
                        lon=lo,
                        elevation_m=elev,
                        faces=list(takeoff.orientations),
                    )
                )
    return out


def build_local_thermal(
    ctx: DataContext,
    proj: Projector,
    takeoff: Site,
    landing: Site,
    alternates: list[Site],
    level: str,
    wing: float,
    glide_wind,
    layer_wind: tuple[float, float],
    t_start: datetime,
    duration_min: float,
    usable: float,
    max_alt: float,
    vario: float = 1.0,
) -> Route:
    """Vol local thermique : déclencheurs au soleil, dans le cône (r ≤ 0,80) ; planés au vent rencontré (§14) à
    l'heure de passage."""
    cands = _local_trigger_candidates(ctx, takeoff, t_start + timedelta(minutes=duration_min / 3), usable)
    landings = [landing, *alternates]
    scored: list[tuple[float, ReliefPoint]] = []
    for p in cands:
        eta_t = t_start + timedelta(minutes=10)
        if not face_is_sunny(p.faces, eta_t, p.lat, p.lon):
            continue
        work_alt = min(max_alt, max(takeoff.elevation_m, p.elevation_m + 150.0))
        g, _ = best_landing_glide(ctx, p.lat, p.lon, work_alt, landings, level, wing, glide_wind, t=quarter(eta_t))
        if g is None or not g.margin_ok or g.ratio > rules.LOCAL_TRIGGER_MAX_GLIDE_RATIO:
            continue  # lot 6.6 : un vol local reste confortablement dans le cône (r ≤ 0,80)
        coords = [(takeoff.lon, takeoff.lat, max_alt), (p.lon, p.lat, max_alt)]
        if route_conflicts(ctx, proj, coords, landing.elevation_m, max_alt):
            continue
        if route_sensitive_conflict(ctx, proj, coords):
            continue
        windward = 1.0 - face_toward(p.faces, layer_wind[1]) / 180.0 if layer_wind[0] >= 8 else 0.5
        s = p.elevation_m / 100.0 + 8.0 * windward - 2.0 * haversine_km(takeoff.lat, takeoff.lon, p.lat, p.lon)
        scored.append((s, p))
    scored.sort(key=lambda x: -x[0])
    chosen = [p for _, p in scored[:2]]
    # ordre : on visite d'abord le point le plus proche
    chosen.sort(key=lambda p: haversine_km(takeoff.lat, takeoff.lon, p.lat, p.lon))
    coords: list[Coord] = [(takeoff.lon, takeoff.lat, takeoff.elevation_m)]
    wps = [_wp(takeoff.name, takeoff.lat, takeoff.lon, takeoff.elevation_m, "takeoff", rules.TAKEOFF_RADIUS_M, 0.0)]
    # revue 7.21 : ETA = transition au vent nul (vitesse bras hauts) + montée jusqu'à l'altitude du point au vario
    eta, prev_alt, prev_lat, prev_lon = 0.0, takeoff.elevation_m, takeoff.lat, takeoff.lon
    v_air = rules.trim_speed_kmh(wing)
    etas: dict[str, datetime] = {}
    for p in chosen:
        alt = min(max_alt, max(p.elevation_m + 300.0, takeoff.elevation_m + 200.0))
        coords.append((p.lon, p.lat, alt))
        eta += haversine_km(prev_lat, prev_lon, p.lat, p.lon) / v_air * 60.0
        eta += max(0.0, alt - prev_alt) / max(vario, 0.3) / 60.0
        etas[p.name] = quarter(t_start + timedelta(minutes=eta))
        prev_alt, prev_lat, prev_lon = alt, p.lat, p.lon
        wps.append(
            _wp(
                p.name,
                p.lat,
                p.lon,
                alt,
                "thermal_trigger",
                rules.THERMAL_TRIGGER_RADIUS_M,
                eta,
                "Déclencheur probable (face ensoleillée" + (", au vent" if layer_wind[0] >= 8 else "") + ")",
            )
        )
    if not chosen:
        # pas de déclencheur identifié : boucle au-dessus du déco
        coords.append((takeoff.lon, takeoff.lat, min(max_alt, takeoff.elevation_m + 300)))
    coords.append((landing.lon, landing.lat, landing.elevation_m))
    wps.append(
        _wp(landing.name, landing.lat, landing.lon, landing.elevation_m, "landing", rules.GOAL_RADIUS_M, duration_min)
    )
    wps += alternates_waypoints(alternates)
    glide = glide_to(ctx, takeoff.lat, takeoff.lon, takeoff.elevation_m, landing, level, wing, glide_wind,
                     pair=is_source_pair(takeoff, landing), t=t_start)
    # pire point de la boucle (déclencheurs à l'altitude de travail, à leur heure de passage)
    for p in chosen:
        work_alt = min(max_alt, max(takeoff.elevation_m, p.elevation_m + 150.0))
        g, _ = best_landing_glide(ctx, p.lat, p.lon, work_alt, landings, level, wing, glide_wind, t=etas[p.name])
        if g is not None and g.ratio > glide.ratio:
            glide = g
    route = Route("local_thermal", coords, wps, path_length_km(coords), max_alt, glide)
    # revue 7.8 : altitude de sécurité par segment (§5.4, §7.1-7) : alt_sécurité(p) = min sur les atterros de
    # (alt + marge + dist / finesse sol) ; pour rejoindre B depuis A, il faut alt_sécurité(B) + dist(A, B) / finesse
    prev_name, prev_lat, prev_lon = "au déco", takeoff.lat, takeoff.lon
    for p in chosen:
        g, alt_sec = best_landing_glide(ctx, p.lat, p.lon, max_alt, landings, level, wing, glide_wind, t=etas[p.name])
        if g is None:
            continue
        back = g.landing_name or landing.name
        back_site = next((x for x in landings if x.name == back), landing)
        sec = max(alt_sec, p.elevation_m + rules.LOCAL_TRIGGER_MIN_HEIGHT_M)  # jamais sous le relief + 150 m
        # transition A → B au vent rencontré dans la tranche [sec ; sec + 300 m] (§14.1)
        fs = transition_finesse(glide_wind, prev_lat, prev_lon, p.lat, p.lon, sec + 300.0, sec, back_site, level, wing,
                                etas[p.name])  # fmt: skip
        need = sec + haversine_km(prev_lat, prev_lon, p.lat, p.lon) * 1000.0 / max(fs, 1.0)
        need_r, sec_r = math.ceil(need / 50.0) * 50, math.ceil(sec / 50.0) * 50
        if need_r <= takeoff.elevation_m and prev_name == "au déco":
            first = f"{p.name} est accessible directement depuis le déco"
        else:
            first = (f"Pour aller à {p.name}, sois au-dessus de {need_r:.0f} m {prev_name} ; en dessous, retour vers "
                     f"{back}")  # fmt: skip
        route.decision_points.append(f"{first}. À {p.name}, sous {sec_r:.0f} m, rentre vers {back}.")
        prev_name, prev_lat, prev_lon = f"à {p.name}", p.lat, p.lon
    return route


# ---------------------------------------------------------------------------------------------
# Soaring dynamique
# ---------------------------------------------------------------------------------------------
def build_ridge(
    ctx: DataContext,
    takeoff: Site,
    landing: Site,
    alternates: list[Site],
    level: str,
    wing: float,
    glide_wind,
    wind_dir: float,
    duration_min: float,
    top_landing: bool,
) -> Route:
    axis = site_axis(takeoff)
    half = rules.RIDGE_BEAT_HALF_LENGTH_KM
    # on vole devant la crête, côté au vent (100 m vers le vent)
    fla, flo = destination(takeoff.lat, takeoff.lon, wind_dir, 0.1)
    a_lat, a_lon = destination(fla, flo, (axis + 90.0) % 360, half)
    b_lat, b_lon = destination(fla, flo, (axis - 90.0) % 360, half)
    alt = takeoff.elevation_m + rules.RIDGE_SOARING_HEIGHT_M
    coords: list[Coord] = [
        (takeoff.lon, takeoff.lat, takeoff.elevation_m),
        (a_lon, a_lat, alt),
        (b_lon, b_lat, alt),
        (a_lon, a_lat, alt),
        (landing.lon, landing.lat, landing.elevation_m),
    ]
    wps = [
        _wp(takeoff.name, takeoff.lat, takeoff.lon, takeoff.elevation_m, "takeoff", rules.TAKEOFF_RADIUS_M, 0.0),
        _wp("Extrémité de crête A", a_lat, a_lon, alt, "turnpoint", rules.TURNPOINT_RADIUS_M, None,
            "Demi-tour face à la pente, virage côté vallée"),
        _wp("Extrémité de crête B", b_lat, b_lon, alt, "turnpoint", rules.TURNPOINT_RADIUS_M, None,
            "Demi-tour face à la pente, virage côté vallée"),
        _wp(landing.name, landing.lat, landing.lon, landing.elevation_m, "landing", rules.GOAL_RADIUS_M, duration_min,
            "Top landing" if top_landing else None),
    ]  # fmt: skip
    wps += alternates_waypoints(alternates)
    if top_landing:
        glide = calm_glide(wing, level, landing.name)
    else:
        glide = glide_to(ctx, takeoff.lat, takeoff.lon, takeoff.elevation_m, landing, level, wing, glide_wind,
                         pair=is_source_pair(takeoff, landing))
    route = Route("ridge", coords, wps, path_length_km(coords), alt, glide)
    if top_landing:
        route.notes.append(
            "Atterrissage au sommet ; en cas de baisse du vent, posez-vous en bas de la pente côté au vent."
        )
    return route


# ---------------------------------------------------------------------------------------------
# Cross-country
# ---------------------------------------------------------------------------------------------
@dataclass(slots=True)
class XcPlan:
    route: Route
    duration_min: float
    v_eff_kmh: float
    v_xc_kmh: float
    limited: bool = False  # distance réduite par le cône de finesse / les espaces à éviter
    target_km: float = 0.0


def _xc_candidates(
    ctx: DataContext,
    takeoff: Site,
    radius_km: float,
    wind_dir: float,
    min_elev: float,
    landings: list[Site] | None = None,
) -> list[ReliefPoint]:
    out: list[ReliefPoint] = []
    for p in ctx.relief:
        if p.valley or p.elevation_m < min_elev:
            continue
        d = haversine_km(takeoff.lat, takeoff.lon, p.lat, p.lon)
        if 2.0 <= d <= radius_km:
            out.append(p)
    if ctx.terrain is not None:
        for brg in range(0, 360, 20):
            for frac in (0.25, 0.4, 0.55, 0.7, 0.85, 1.0):
                d = radius_km * frac
                if d < 3.0:
                    continue
                la, lo = destination(takeoff.lat, takeoff.lon, float(brg), d)
                elev = ctx.terrain_at(la, lo)
                if elev is None or elev < min_elev:
                    continue
                # face principale du relief : direction de la pente descendante (aspect)
                out.append(
                    ReliefPoint(
                        name=_relief_name(ctx, la, lo, f"Relief à {d:.0f} km au {dir_label(brg)}"), lat=la, lon=lo,
                        elevation_m=elev, faces=[],
                    )
                )  # fmt: skip
        # reliefs dans le cône des atterros de secours : permet des circuits longs qui restent couverts
        for ldg in landings or []:
            if haversine_km(takeoff.lat, takeoff.lon, ldg.lat, ldg.lon) > radius_km + 10:
                continue
            for brg in range(0, 360, 30):
                for d in (4.0, 8.0, 12.0):
                    la, lo = destination(ldg.lat, ldg.lon, float(brg), d)
                    if haversine_km(takeoff.lat, takeoff.lon, la, lo) > radius_km:
                        continue
                    elev = ctx.terrain_at(la, lo)
                    if elev is None or elev < min_elev:
                        continue
                    dd = haversine_km(takeoff.lat, takeoff.lon, la, lo)
                    bb = bearing_deg(takeoff.lat, takeoff.lon, la, lo)
                    out.append(
                        ReliefPoint(name=_relief_name(ctx, la, lo, f"Relief à {dd:.0f} km au {dir_label(bb)} (secteur "
                                                                   f"{ldg.name})"),
                                    lat=la, lon=lo, elevation_m=elev, faces=[])
                    )  # fmt: skip
    return out


def _relief_name(ctx: DataContext, lat: float, lon: float, default: str) -> str:
    """Revue 7.11 : nom du sommet connu (couche relief) le plus proche à moins de 2 km, sinon `default`."""
    best: tuple[float, str] | None = None
    for p in ctx.relief:
        if p.valley:
            continue
        d = haversine_km(lat, lon, p.lat, p.lon)
        if d <= rules.XC_RELIEF_NAME_RADIUS_KM and (best is None or d < best[0]):
            best = (d, p.name)
    if best is None:
        return default
    return best[1] if best[0] <= 0.5 else f"Secteur {best[1]}"


def build_cross(
    ctx: DataContext,
    proj: Projector,
    takeoff: Site,
    landing: Site,
    landings_pool: list[Site],
    level: str,
    wing: float,
    layer_wind: tuple[float, float],
    t_start: datetime,
    budget_min: float,
    usable: float,
    max_alt: float,
    vario: float,
    glide_wind=None,
) -> tuple[XcPlan | None, str | None]:
    """Construit le meilleur circuit fermé ; renvoie (plan, raison si impossible). `layer_wind` = vent moyen de la
    couche (forme du circuit, vitesse effective) ; `glide_wind` = champ de vent du vol pour les planés du cône (§14 :
    vent rencontré à l'heure de passage ; défaut : vent de la couche, uniforme)."""
    v_xc = rules.xc_speed_kmh(vario, level, wing)
    if v_xc <= 0:
        return None, "[WEAK_THERMALS] Thermiques trop faibles pour un cross à ce niveau"
    w_speed, w_dir = layer_wind
    shapes: list[str] = []
    if level in ("advanced", "expert") and w_speed <= rules.XC_FAI_MAX_WIND_KMH:
        shapes += ["fai_triangle", "triangle"]
    shapes.append("out_and_return")
    if level in ("advanced", "expert") and "triangle" not in shapes:
        shapes.append("triangle")

    t_climb = max(rules.XC_MIN_INITIAL_CLIMB_MIN, (usable - takeoff.elevation_m) / max(vario, 0.3) / 60.0)
    t_legs = budget_min - t_climb - rules.XC_FINAL_GLIDE_MIN
    if t_legs < 30:
        return None, "Fenêtre thermique trop courte pour un cross"
    max_dist = float(rules.XC_MAX_DISTANCE_KM[level])
    if max_dist <= 0:
        return None, "[SITE_LEVEL] Pas de cross à ce niveau"

    upwind = w_dir  # direction d'où vient le vent : premier segment face au vent
    best: tuple[float, XcPlan] | None = None
    reasons: list[str] = []
    min_elev = max(700.0, takeoff.elevation_m - 400.0)
    for shape in shapes:
        if shape == "out_and_return":
            v_eff = v_xc - w_speed**2 / v_xc
        else:
            w = w_speed * rules.XC_TRIANGLE_WIND_FACTOR
            v_eff = v_xc - w**2 / v_xc
        if v_eff < rules.XC_MIN_EFFECTIVE_SPEED_KMH:
            reasons.append(f"Vent trop fort pour un {shape} (vitesse effective {v_eff:.0f} km/h)")
            continue
        d_target = min(max_dist, rules.XC_WINDOW_USAGE * v_eff * t_legs / 60.0)
        if d_target < 8.0:
            continue
        radius = d_target / 2.0 + 3.0 if shape == "out_and_return" else d_target / 2.5 + 3.0
        pool = _xc_candidates(ctx, takeoff, radius, upwind, min_elev, landings_pool)
        for scale in (1.0, 0.9, 0.8, 0.7, 0.6, 0.45, 0.33):
            d = d_target * scale
            if d < 8.0:
                break
            plan = _search_shape(
                ctx, proj, takeoff, landing, landings_pool, level, wing, layer_wind, shape, d, upwind,
                usable, max_alt, pool, v_eff, t_climb, t_start, glide_wind,
            )  # fmt: skip
            if plan is None:
                continue
            plan.limited = scale < 1.0
            plan.target_km = d_target
            # objectif : distance la plus proche de la cible, préférence aux formes « nobles »
            bonus = {"fai_triangle": 1.08, "triangle": 1.03, "out_and_return": 1.0}[shape]
            key = plan.route.distance_km * bonus
            if best is None or key > best[0]:
                best = (key, plan)
            break
    if best is None:
        why = "; ".join(reasons) if reasons else (
            "aucun circuit ne garde un atterrissage identifié dans le cône de finesse (ou évite les espaces "
            "aériens / zones protégées)"
        )
        return None, f"[GLIDE_MARGIN] Cross non proposé : {why}"
    plan = best[1]
    plan.v_xc_kmh = v_xc
    return plan, None


def _search_shape(
    ctx: DataContext,
    proj: Projector,
    takeoff: Site,
    landing: Site,
    landings_pool: list[Site],
    level: str,
    wing: float,
    layer_wind: tuple[float, float],
    shape: str,
    d: float,
    upwind: float,
    usable: float,
    max_alt: float,
    pool: list[ReliefPoint],
    v_eff: float,
    t_climb: float,
    t_start: datetime,
    glide_wind=None,
) -> XcPlan | None:
    radius = d / 2.0 + 3.0 if shape == "out_and_return" else d / 2.5 + 3.0
    cands = [p for p in pool if haversine_km(takeoff.lat, takeoff.lon, p.lat, p.lon) <= radius]
    if not cands:
        return None
    w_speed = layer_wind[0]
    routes: list[tuple[float, list[ReliefPoint]]] = []

    def leg_ok(p: ReliefPoint) -> float:
        brg = bearing_deg(takeoff.lat, takeoff.lon, p.lat, p.lon)
        return angle_diff(brg, upwind)

    if shape == "out_and_return":
        for p in cands:
            dist = haversine_km(takeoff.lat, takeoff.lon, p.lat, p.lon) + haversine_km(
                p.lat, p.lon, landing.lat, landing.lon
            )
            if not (0.75 * d <= dist <= 1.15 * d):
                continue
            dev = leg_ok(p)
            if w_speed >= 10 and dev > 60:
                continue
            score = -abs(dist - d) / d * 10 - dev / 30.0 + p.elevation_m / 1000.0
            routes.append((score, [p]))
    else:
        firsts = sorted(cands, key=lambda p: leg_ok(p))[:60]
        seconds = cands if len(cands) <= 150 else sorted(cands, key=lambda p: -p.elevation_m)[:150]
        for i, p1 in enumerate(firsts):
            dev = leg_ok(p1)
            if w_speed >= 10 and dev > 60:
                continue
            for p2 in seconds:
                if p2 is p1:
                    continue
                l1 = haversine_km(takeoff.lat, takeoff.lon, p1.lat, p1.lon)
                l2 = haversine_km(p1.lat, p1.lon, p2.lat, p2.lon)
                l3 = haversine_km(p2.lat, p2.lon, takeoff.lat, takeoff.lon)
                per = l1 + l2 + l3
                if not (0.75 * d <= per <= 1.15 * d):
                    continue
                shortest = min(l1, l2, l3) / per
                if shape == "fai_triangle" and shortest < rules.XC_FAI_MIN_LEG_RATIO:
                    continue
                if shape == "triangle" and shortest < 0.15:
                    continue
                score = -abs(per - d) / d * 10 - dev / 30.0 + (p1.elevation_m + p2.elevation_m) / 2000.0
                routes.append((score, [p1, p2]))
            if len(routes) > 3000 and i > 30:
                break
    routes.sort(key=lambda r: -r[0])
    landings = [landing, *[x for x in landings_pool if x.id != landing.id]]
    best: XcPlan | None = None
    passing = 0
    for _, tps in routes[:120]:
        if passing >= 6:
            break
        coords: list[Coord] = [(takeoff.lon, takeoff.lat, takeoff.elevation_m)]
        for p in tps:
            coords.append((p.lon, p.lat, max_alt))
        coords.append((landing.lon, landing.lat, landing.elevation_m))
        flight_coords = [(c[0], c[1], max_alt) for c in coords[:-1]] + [coords[-1]]
        if route_conflicts(ctx, proj, flight_coords, landing.elevation_m, max_alt):
            continue
        if route_sensitive_conflict(ctx, proj, flight_coords[:-1]):
            continue
        cone = _cone_check(ctx, coords, landings, level, wing, glide_wind if glide_wind is not None else layer_wind,
                           usable, lambda km: t_start + timedelta(minutes=t_climb + km / v_eff * 60.0))  # fmt: skip
        if cone is None:
            continue
        glide, decisions, used_landings = cone
        dist = path_length_km(coords)
        duration = t_climb + dist / v_eff * 60.0 + rules.XC_FINAL_GLIDE_MIN
        wps = [_wp(takeoff.name, takeoff.lat, takeoff.lon, takeoff.elevation_m, "takeoff", rules.TAKEOFF_RADIUS_M, 0.0)]
        cum = 0.0
        prev = coords[0]
        for p, c in zip(tps, coords[1:-1], strict=False):
            cum += haversine_km(prev[1], prev[0], c[1], c[0])
            prev = c
            eta = t_climb + cum / v_eff * 60.0
            wps.append(_wp(p.name, p.lat, p.lon, max_alt, "turnpoint", rules.TURNPOINT_RADIUS_M, eta))
        wps.append(
            _wp(landing.name, landing.lat, landing.lon, landing.elevation_m, "landing", rules.GOAL_RADIUS_M, duration)
        )
        alts = [x for x in used_landings if x.id != landing.id]
        wps += alternates_waypoints(alts)
        route = Route(
            "xc",
            coords,
            wps,
            dist,
            max_alt,
            glide,
            decision_points=decisions,
            first_leg_bearing=bearing_deg(takeoff.lat, takeoff.lon, tps[0].lat, tps[0].lon),
            xc_subtype=shape,
            used_landings=alts,
        )
        passing += 1
        # parmi les circuits valides, on garde le plus long (sans dépasser la cible de plus de 15 %)
        if best is None or dist > best.route.distance_km:
            best = XcPlan(route, duration, v_eff, 0.0)
    return best


def _cone_check(
    ctx: DataContext,
    coords: list[Coord],
    landings: list[Site],
    level: str,
    wing: float,
    wind,
    usable: float,
    eta=None,
) -> tuple[GlideCheck, list[str], list[Site]] | None:
    """Vérifie tous les 500 m qu'un atterro identifié reste dans le cône ; renvoie le pire glide. `eta(km)` = heure de
    passage au km `km` de la route (planés au vent rencontré à cette heure, §14.1)."""
    limit = usable - rules.SAFETY_ALT_BELOW_CEILING_M
    # lot 6.11 : on contrôle depuis l'altitude de point bas (plafond utile − 300 m) avec r ≤ 0,90
    # (pas de GLIDE_MARGIN caution) ; le glide publié = pire cas à cette altitude.
    worst: GlideCheck | None = None
    decisions: list[str] = []
    used: dict[str, Site] = {}
    cum = 0.0
    for idx, (a, b) in enumerate(zip(coords[:-1], [*coords[1:-1], coords[-1]], strict=False)):
        seg = haversine_km(a[1], a[0], b[1], b[0])
        n = max(1, int(seg / rules.GLIDE_CHECK_STEP_KM))
        seg_worst_alt = 0.0
        seg_landing = None
        for i in range(n + 1):
            f = i / n
            lat = a[1] + f * (b[1] - a[1])
            lon = a[0] + f * (b[0] - a[0])
            t = quarter(eta(cum + f * seg)) if eta is not None else None
            g, alt_sec = best_landing_glide(ctx, lat, lon, limit, landings, level, wing, wind, t=t)
            if g is None or alt_sec > limit or g.ratio > rules.GLIDE_CAUTION_RATIO:
                return None
            if alt_sec > seg_worst_alt:
                seg_worst_alt = alt_sec
                seg_landing = g.landing_name
            if worst is None or g.ratio > worst.ratio:
                worst = g
            for ldg in landings:
                if ldg.name == g.landing_name:
                    used[ldg.id] = ldg
        cum += seg
        if idx < len(coords) - 2 and seg_landing:
            decisions.append(
                f"Segment {idx + 1} : sous {round(seg_worst_alt, -2):.0f} m, rentrer vers {seg_landing}"
            )
    if worst is None:
        return None
    return worst, decisions, list(used.values())
