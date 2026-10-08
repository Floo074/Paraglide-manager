"""Construction des routes (plouf, local thermique, soaring, cross) et contrôles de finesse.

Formules (cahier des charges §2.3, §5) :
- finesse de calcul sol = finesse polaire × k(niveau) × (V_air + W_comp) / V_air, W_comp = composante
  du vent moyen projetée sur la route (positive = vent arrière) ;
- hauteur disponible = altitude du point − (altitude atterro + marge d'arrivée), marge bornée à 25 %
  du dénivelé ; required_ratio = distance / hauteur disponible ; margin_ok = required ≤ available ;
- cross : « toujours un atterro dans le cône » vérifié tous les 500 m :
  alt_sécurité(p) = min_a [alt_a + marge + dist(p, a) / finesse_sol(p→a)] ≤ plafond utile − 300 m.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.engine import rules
from app.engine.airspace import Projector, route_conflicts, route_sensitive_conflict
from app.engine.conditions import along_track_component, dir_label
from app.engine.context import DataContext, ReliefPoint
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

    @property
    def ratio(self) -> float:
        if self.available_ratio <= 0:
            return 9.9
        return self.required_ratio / self.available_ratio


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


# ---------------------------------------------------------------------------------------------
# Finesse
# ---------------------------------------------------------------------------------------------
def finesse_sol(wing: float, level: str, wind_speed: float, wind_dir: float, track: float) -> float:
    v_air = rules.trim_speed_kmh(wing)
    w = along_track_component(wind_speed, wind_dir, track)
    return max(0.0, wing * rules.GLIDE_K[level] * (v_air + w) / v_air)


def arrival_margin(level: str, drop_m: float) -> float:
    return min(rules.LANDING_ARRIVAL_MARGIN_M[level], rules.LANDING_ARRIVAL_MARGIN_MAX_FRACTION * max(0.0, drop_m))


def glide_to(
    ctx: DataContext,
    lat: float,
    lon: float,
    alt: float,
    landing: Site,
    level: str,
    wing: float,
    wind: tuple[float, float],
    drop_ref: float | None = None,
) -> GlideCheck:
    dist_m = haversine_km(lat, lon, landing.lat, landing.lon) * 1000.0
    track = bearing_deg(lat, lon, landing.lat, landing.lon)
    margin = arrival_margin(level, drop_ref if drop_ref is not None else alt - landing.elevation_m)
    height = alt - (landing.elevation_m + margin)
    available = finesse_sol(wing, level, wind[0], wind[1], track)
    required = dist_m / height if height > 1 else 99.0
    terrain_ok = terrain_clear(ctx, lat, lon, alt, landing, available)
    return GlideCheck(
        required_ratio=required,
        available_ratio=available,
        margin_ok=required <= available and terrain_ok,
        terrain_ok=terrain_ok,
        landing_name=landing.name,
    )


def terrain_clear(ctx: DataContext, lat: float, lon: float, alt: float, landing: Site, finesse: float) -> bool:
    """La ligne de plané (pente 1/finesse) reste-t-elle ≥ 50 m au-dessus du terrain ?"""
    if ctx.terrain is None or not ctx.terrain_is_real or finesse <= 0:
        return True
    dist = haversine_km(lat, lon, landing.lat, landing.lon)
    if dist < 1.0:
        return True
    brg = bearing_deg(lat, lon, landing.lat, landing.lon)
    n = max(2, int(dist / 0.25))
    for i in range(1, n):
        d = dist * i / n
        if d < 0.5 or dist - d < 0.6:
            continue
        la, lo = destination(lat, lon, brg, d)
        terrain = ctx.terrain_at(la, lo)
        if terrain is None:
            continue
        glide_alt = alt - d * 1000.0 / finesse
        if glide_alt < terrain + rules.TERRAIN_CLEARANCE_M:
            return False
    return True


def best_landing_glide(
    ctx: DataContext,
    lat: float,
    lon: float,
    alt: float,
    landings: list[Site],
    level: str,
    wing: float,
    wind: tuple[float, float],
) -> tuple[GlideCheck | None, float]:
    """Meilleur atterro joignable depuis un point ; renvoie (glide, altitude de sécurité)."""
    best_ldg: Site | None = None
    best_alt = 1e9
    for ldg in landings:
        dist_m = haversine_km(lat, lon, ldg.lat, ldg.lon) * 1000.0
        track = bearing_deg(lat, lon, ldg.lat, ldg.lon)
        fs = finesse_sol(wing, level, wind[0], wind[1], track)
        if fs <= 0:
            continue
        margin = arrival_margin(level, alt - ldg.elevation_m)
        alt_sec = ldg.elevation_m + margin + dist_m / fs
        if alt_sec < best_alt:
            best_alt = alt_sec
            best_ldg = ldg
    if best_ldg is None:
        return None, best_alt
    return glide_to(ctx, lat, lon, alt, best_ldg, level, wing, wind), best_alt


# ---------------------------------------------------------------------------------------------
# Outils
# ---------------------------------------------------------------------------------------------
def path_length_km(coords: list[Coord]) -> float:
    return sum(
        haversine_km(a[1], a[0], b[1], b[0]) for a, b in zip(coords, coords[1:], strict=False)
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
        _wp(a.name, a.lat, a.lon, a.elevation_m, "alternate_landing", rules.GOAL_RADIUS_M, None, "Atterrissage de secours")
        for a in alternates
    ]


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
    glide_wind: tuple[float, float],
    landing_wind: tuple[float, float],
    duration_min: float,
    top_landing: bool = False,
) -> Route:
    lw_speed, lw_dir = landing_wind
    if lw_speed >= rules.CALM_WIND_KMH:
        lose_brg = (lw_dir + 180.0) % 360.0  # côté sous le vent de l'atterro (PTU)
    else:
        lose_brg = bearing_deg(landing.lat, landing.lon, takeoff.lat, takeoff.lon)
    lla, llo = destination(landing.lat, landing.lon, lose_brg, rules.PLOUF_LOSE_HEIGHT_POINT_KM)
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
        GlideCheck(0.0, finesse_sol(wing, level, *glide_wind, 0.0), True)
        if top_landing
        else glide_to(ctx, takeoff.lat, takeoff.lon, takeoff.elevation_m, landing, level, wing, glide_wind)
    )
    wps = [
        _wp(takeoff.name, takeoff.lat, takeoff.lon, takeoff.elevation_m, "takeoff", rules.TAKEOFF_RADIUS_M, 0.0),
    ]
    if not top_landing:
        wps.append(
            _wp(
                "Zone de perte d'altitude",
                lla,
                llo,
                lose_alt,
                "turnpoint",
                rules.TURNPOINT_RADIUS_M,
                max(0.0, duration_min - 4.0),
                f"Côté sous le vent de l'atterro, ≥ {rules.PLOUF_LOSE_HEIGHT_MIN_AGL_M:.0f} m sol, puis PTU",
            )
        )
    wps.append(_wp(landing.name, landing.lat, landing.lon, landing.elevation_m, "landing", rules.GOAL_RADIUS_M, duration_min))
    wps += alternates_waypoints(alternates)
    return Route("plouf", coords, wps, dist, takeoff.elevation_m, glide)


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
    glide_wind: tuple[float, float],
    layer_wind: tuple[float, float],
    t_start: datetime,
    duration_min: float,
    usable: float,
    max_alt: float,
) -> Route:
    cands = _local_trigger_candidates(ctx, takeoff, t_start + timedelta(minutes=duration_min / 3), usable)
    landings = [landing, *alternates]
    scored: list[tuple[float, ReliefPoint]] = []
    for p in cands:
        eta_t = t_start + timedelta(minutes=10)
        if not face_is_sunny(p.faces, eta_t, p.lat, p.lon):
            continue
        work_alt = min(max_alt, max(takeoff.elevation_m, p.elevation_m + 150.0))
        g, _ = best_landing_glide(ctx, p.lat, p.lon, work_alt, landings, level, wing, glide_wind)
        if g is None or not g.margin_ok:
            continue
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
    n = len(chosen)
    for i, p in enumerate(chosen):
        alt = min(max_alt, max(p.elevation_m + 300.0, takeoff.elevation_m + 200.0))
        coords.append((p.lon, p.lat, alt))
        eta = duration_min * (i + 1) / (n + 2)
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
    wps.append(_wp(landing.name, landing.lat, landing.lon, landing.elevation_m, "landing", rules.GOAL_RADIUS_M, duration_min))
    wps += alternates_waypoints(alternates)
    glide = glide_to(ctx, takeoff.lat, takeoff.lon, takeoff.elevation_m, landing, level, wing, glide_wind)
    # pire point de la boucle (déclencheurs à l'altitude de travail)
    for p in chosen:
        work_alt = min(max_alt, max(takeoff.elevation_m, p.elevation_m + 150.0))
        g, _ = best_landing_glide(ctx, p.lat, p.lon, work_alt, landings, level, wing, glide_wind)
        if g is not None and g.ratio > glide.ratio:
            glide = g
    route = Route("local_thermal", coords, wps, path_length_km(coords), max_alt, glide)
    if chosen:
        route.decision_points.append(
            f"Rester dans le cône de finesse de {landing.name} : si le thermique ne monte pas au-dessus "
            f"de {takeoff.elevation_m:.0f} m, revenir vers l'atterro."
        )
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
    glide_wind: tuple[float, float],
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
        glide = GlideCheck(0.0, finesse_sol(wing, level, glide_wind[0], glide_wind[1], 0.0), True)
    else:
        glide = glide_to(ctx, takeoff.lat, takeoff.lon, takeoff.elevation_m, landing, level, wing, glide_wind)
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


def _xc_candidates(
    ctx: DataContext, takeoff: Site, radius_km: float, wind_dir: float, min_elev: float
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
                        name=f"Relief à {d:.0f} km au {dir_label(brg)}", lat=la, lon=lo, elevation_m=elev, faces=[]
                    )
                )
    return out


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
) -> tuple[XcPlan | None, str | None]:
    """Construit le meilleur circuit fermé ; renvoie (plan, raison si impossible)."""
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
        for scale in (1.0, 0.8, 0.6, 0.45, 0.33):
            d = d_target * scale
            if d < 8.0:
                break
            plan = _search_shape(
                ctx, proj, takeoff, landing, landings_pool, level, wing, layer_wind, shape, d, upwind,
                usable, max_alt, min_elev, v_eff, t_climb, t_start,
            )  # fmt: skip
            if plan is None:
                continue
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
    min_elev: float,
    v_eff: float,
    t_climb: float,
    t_start: datetime,
) -> XcPlan | None:
    radius = d / 2.0 + 3.0 if shape == "out_and_return" else d / 2.5 + 3.0
    cands = _xc_candidates(ctx, takeoff, radius, upwind, min_elev)
    if not cands:
        return None
    w_speed = layer_wind[0]
    routes: list[tuple[float, list[ReliefPoint]]] = []

    def leg_ok(p: ReliefPoint) -> float:
        brg = bearing_deg(takeoff.lat, takeoff.lon, p.lat, p.lon)
        return angle_diff(brg, upwind)

    if shape == "out_and_return":
        for p in cands:
            dist = haversine_km(takeoff.lat, takeoff.lon, p.lat, p.lon) + haversine_km(p.lat, p.lon, landing.lat, landing.lon)
            if not (0.75 * d <= dist <= 1.15 * d):
                continue
            dev = leg_ok(p)
            if w_speed >= 10 and dev > 60:
                continue
            score = -abs(dist - d) / d * 10 - dev / 30.0 + p.elevation_m / 1000.0
            routes.append((score, [p]))
    else:
        cands = sorted(cands, key=lambda p: leg_ok(p))[:60]
        for i, p1 in enumerate(cands):
            dev = leg_ok(p1)
            if w_speed >= 10 and dev > 60:
                continue
            for p2 in cands:
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
            if len(routes) > 400 and i > 20:
                break
    routes.sort(key=lambda r: -r[0])
    landings = [landing, *[x for x in landings_pool if x.id != landing.id]]
    for _, tps in routes[:40]:
        coords: list[Coord] = [(takeoff.lon, takeoff.lat, takeoff.elevation_m)]
        for p in tps:
            coords.append((p.lon, p.lat, max_alt))
        coords.append((landing.lon, landing.lat, landing.elevation_m))
        flight_coords = [(c[0], c[1], max_alt) for c in coords[:-1]] + [coords[-1]]
        if route_conflicts(ctx, proj, flight_coords, landing.elevation_m, max_alt):
            continue
        if route_sensitive_conflict(ctx, proj, flight_coords[:-1]):
            continue
        cone = _cone_check(ctx, coords, landings, level, wing, layer_wind, usable)
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
        wps.append(_wp(landing.name, landing.lat, landing.lon, landing.elevation_m, "landing", rules.GOAL_RADIUS_M, duration))
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
        )
        return XcPlan(route, duration, v_eff, 0.0)
    return None


def _cone_check(
    ctx: DataContext,
    coords: list[Coord],
    landings: list[Site],
    level: str,
    wing: float,
    wind: tuple[float, float],
    usable: float,
) -> tuple[GlideCheck, list[str], list[Site]] | None:
    """Vérifie tous les 500 m qu'un atterro identifié reste dans le cône ; renvoie le pire glide."""
    limit = usable - rules.SAFETY_ALT_BELOW_CEILING_M
    worst: GlideCheck | None = None
    decisions: list[str] = []
    used: dict[str, Site] = {}
    for idx, (a, b) in enumerate(zip(coords[:-1], coords[1:-1] + [coords[-1]], strict=False)):
        seg = haversine_km(a[1], a[0], b[1], b[0])
        n = max(1, int(seg / rules.GLIDE_CHECK_STEP_KM))
        seg_worst_alt = 0.0
        seg_landing = None
        for i in range(n + 1):
            f = i / n
            lat = a[1] + f * (b[1] - a[1])
            lon = a[0] + f * (b[0] - a[0])
            g, alt_sec = best_landing_glide(ctx, lat, lon, usable, landings, level, wing, wind)
            if g is None or alt_sec > limit:
                return None
            if alt_sec > seg_worst_alt:
                seg_worst_alt = alt_sec
                seg_landing = g.landing_name
            if worst is None or g.ratio > worst.ratio:
                worst = g
            for ldg in landings:
                if ldg.name == g.landing_name:
                    used[ldg.id] = ldg
        if idx < len(coords) - 2 and seg_landing:
            decisions.append(
                f"Segment {idx + 1} : sous {round(seg_worst_alt, -2):.0f} m, rentrer vers {seg_landing}"
            )
    if worst is None:
        return None
    return worst, decisions, list(used.values())
