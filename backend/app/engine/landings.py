"""Atterros candidats (CDC §12.7) : catégories official / community / field, usage permis par niveau, critères
minimaux des atterros non officiels, marges de finesse renforcées, score pondéré, avertissements obligatoires,
raisons du classement, choix de l'atterro principal et des secours pour un décollage libre, rejet expliqué.

Fonctions synchrones et sans réseau : les données (terrains, obstacles, vent) arrivent par le `DataContext`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.engine import rules
from app.engine.conditions import LandingWind, dir_label, landing_wind
from app.engine.context import DataContext
from app.engine.findings import Finding
from app.engine.glidewind import GlideField, big_valley, plouf_minutes, timeline_for, uniform_finesse
from app.engine.routing import (
    GlideCheck,
    calm_glide,
    finesse_sol,
    glide_to,
    kind_glide_params,
    landing_kind_of,
    path_for,
    projector_for,
)
from app.engine.scoring import glide_subscore, linear
from app.engine.stations import site_attachments
from app.geo import angle_diff, bearing_deg, destination, haversine_km
from app.models import ArrivalWind, LandingCandidate, Site, SizeM

LEVELS = rules.LEVELS
UNOFFICIAL_LEVELS = ("intermediate", "advanced", "expert")
KIND_LABEL = {"official": "atterro officiel", "community": "atterro communautaire", "field": "champ détecté"}
CLEARANCES = (  # (clé, clé du minimum dans UNOFFICIAL_LANDING_MIN, libellé)
    ("power_line", "power_line_clearance_m", "ligne électrique"),
    ("trees_buildings", "tree_building_clearance_m", "arbres / bâtiments"),
    ("water", "water_clearance_m", "eau"),
    ("road", "road_clearance_m", "route"),
)
POLICY_LABEL = {
    "official_only": "atterros officiels seulement",
    "include_community": "officiels et communautaires",
    "include_fields": "officiels, communautaires et champs",
}
USE_ORDER = {"main": 0, "main_marginal": 1, "alternate": 2, "never": 3}


# =============================================================================================
# Données d'un terrain candidat
# =============================================================================================
@dataclass(slots=True)
class ApproachObstacle:
    """Obstacle dans l'axe d'approche (au-delà d'un bout du terrain)."""

    bearing_deg: float  # cap depuis le centre du terrain vers l'obstacle
    height_m: float
    distance_m: float  # distance au bord du terrain
    label: str  # « forêt », « bâtiment », « ligne électrique »


@dataclass(slots=True)
class LandingSpot:
    """Atterro candidat : le `Site` publié + ce qu'on sait du terrain (CDC §12.7)."""

    site: Site
    kind: str  # official | community | field
    size: tuple[float, float] | None = None  # (longueur, largeur) en m
    axis_deg: float | None = None  # orientation du grand axe (0..180)
    slope_pct: float | None = None
    surface: str | None = None
    community_usage: str = "unknown"  # frequent | occasional | unknown
    access: str | None = None
    road_m: float | None = None  # distance du bord du terrain à la route la plus proche
    # distance (m) du bord du terrain à l'obstacle le plus proche, par type ; None = rien dans le rayon de recherche ;
    # clé absente = non cartographié (distance inconnue)
    clearances: dict[str, float | None] = field(default_factory=dict)
    clearance_bearings: dict[str, float] = field(default_factory=dict)  # cap centre → obstacle (texte)
    approach: list[ApproachObstacle] = field(default_factory=list)
    demo: bool = False  # terrain de démonstration (fictif)


def spot_for(ctx: DataContext, site: Site) -> LandingSpot:
    spot = ctx.landing_spots.get(site.id)
    if spot is not None:
        return spot
    kind = landing_kind_of(site)
    usage = rules.PGE_COMMUNITY_USAGE if kind == "community" and site.source == "paraglidingearth" else "unknown"
    return LandingSpot(site=site, kind=kind, community_usage=usage, access=site.access)


def kind_use(kind: str, level: str, usage: str) -> str:
    """main | main_marginal | alternate | never (table « niveaux autorisés » du §12.7)."""
    u = rules.LANDING_KIND_USE[kind][level]
    if u == "main_if_frequent":
        return "main" if usage == "frequent" else "alternate"
    return u


def effective_policy(policy: str, level: str) -> str:
    return rules.BEGINNER_LANDING_POLICY if level == "beginner" else policy


def _lvl(level: str) -> str:
    return level if level in UNOFFICIAL_LEVELS else "intermediate"


# =============================================================================================
# Critères minimaux (atterros non officiels)
# =============================================================================================
def fr_num(x: float, nd: int = 1) -> str:
    """Nombre au format français (virgule décimale)."""
    return f"{x:.{nd}f}".replace(".", ",")


def _compass_fr(deg: float) -> str:
    return {
        "N": "nord", "NNE": "nord-nord-est", "NE": "nord-est", "ENE": "est-nord-est", "E": "est",
        "ESE": "est-sud-est", "SE": "sud-est", "SSE": "sud-sud-est", "S": "sud", "SSO": "sud-sud-ouest",
        "SO": "sud-ouest", "OSO": "ouest-sud-ouest", "O": "ouest", "ONO": "ouest-nord-ouest", "NO": "nord-ouest",
        "NNO": "nord-nord-ouest",
    }[dir_label(deg)]  # fmt: skip


def _min_clearance(key: str, min_key: str, lv: str) -> float:
    v = rules.UNOFFICIAL_LANDING_MIN[min_key]
    return float(v[lv] if isinstance(v, dict) else v)


def approach_penalty(spot: LandingSpot, lw: LandingWind | None) -> tuple[float, str | None]:
    """(longueur perdue en m, échec « finale ») : obstacles dans l'axe d'approche (on se pose face au vent, l'approche
    se fait côté sous le vent). Longueur utile = longueur − (5 × hauteur − distance au bord) ; un obstacle de plus de
    10 m à moins de 150 m dans l'axe de finale exclut le terrain. Vent faible : on retient le meilleur bout."""
    m = rules.UNOFFICIAL_LANDING_MIN
    if not spot.approach:
        return 0.0, None
    if lw is not None and lw.speed_kmh >= rules.CALM_WIND_KMH:
        sides = [(lw.direction_deg + 180.0) % 360.0]
    elif spot.axis_deg is not None:
        sides = [spot.axis_deg % 360.0, (spot.axis_deg + 180.0) % 360.0]
    else:
        sides = [float(b) for b in range(0, 360, 45)]
    best: tuple[float, str | None] | None = None
    for side in sides:
        lost, fail = 0.0, None
        for ob in spot.approach:
            if angle_diff(ob.bearing_deg, side) > 45.0 or ob.distance_m >= m["approach_free_m"]:
                continue
            if ob.height_m > 10.0:
                fail = (
                    f"{ob.label} de {ob.height_m:.0f} m à {ob.distance_m:.0f} m dans l'axe de finale "
                    f"(aucun obstacle de plus de 10 m sur {m['approach_free_m']} m)"
                )
            lost = max(lost, m["approach_obstacle_length_factor"] * ob.height_m - ob.distance_m)
        cand = (max(0.0, lost), fail)
        if best is None or (cand[1] is None, -cand[0]) > (best[1] is None, -best[0]):
            best = cand
    return best if best is not None else (0.0, None)


def criteria_failures(spot: LandingSpot, level: str, lw: LandingWind | None) -> tuple[list[str], list[str]]:
    """(critères non remplis, notes) pour un atterro communautaire ou un champ au niveau donné (§12.7). Donnée inconnue
    (taille, pente, obstacle non cartographié) : pas d'exclusion, mais une note (et un sous-score réduit)."""
    m = rules.UNOFFICIAL_LANDING_MIN
    lv = _lvl(level)
    fails: list[str] = []
    notes: list[str] = []
    lmin, wmin = m["length_m"][lv], m["width_m"][lv]
    lost, appr_fail = approach_penalty(spot, lw)
    if appr_fail:
        fails.append(appr_fail)
    if spot.size is not None:
        length, width = spot.size
        useful = length - lost
        if useful < lmin or width < wmin:
            ut = f", longueur utile {useful:.0f} m (obstacle en bout de finale)" if lost > 0 else ""
            fails.append(f"terrain de {length:.0f} × {width:.0f} m{ut} : minimum {lmin} × {wmin} m à ce niveau")
    else:
        notes.append(f"Taille non renseignée : vérifie en vol qu'il fait au moins {lmin} × {wmin} m.")
    if spot.slope_pct is not None:
        if spot.slope_pct > m["slope_pct_max"][lv]:
            fails.append(f"pente de {spot.slope_pct:.0f} % (maximum {m['slope_pct_max'][lv]} %)")
    else:
        notes.append("Pente non mesurée : à vérifier en vol (terrain plat, sans dévers).")
    for key, min_key, label in CLEARANCES:
        if key not in spot.clearances:
            continue
        d = spot.clearances[key]
        mn = _min_clearance(key, min_key, lv)
        if d is not None and d < mn:
            fails.append(f"{label} à {d:.0f} m (minimum {mn:.0f} m)")
    if spot.axis_deg is not None and lw is not None and lw.speed_kmh >= rules.CALM_WIND_KMH:
        ang = min(angle_diff(lw.direction_deg, spot.axis_deg), angle_diff(lw.direction_deg, spot.axis_deg + 180.0))
        if ang > m["long_axis_vs_wind_max_deg"]:
            fails.append(f"vent d'arrivée à {ang:.0f}° de l'axe du terrain (maximum {m['long_axis_vs_wind_max_deg']}°)")
    return fails, notes


# =============================================================================================
# Évaluation d'un candidat
# =============================================================================================
@dataclass
class LandingEval:
    spot: LandingSpot
    distance_km: float
    bearing_deg: float
    reachable: bool  # portée de plané avec les règles d'un atterro officiel, au niveau du pilote
    std_glide: GlideCheck
    glide: GlideCheck  # avec les marges du kind (hauteur d'arrivée mini, facteur f)
    arrival_height_m: float
    wind: LandingWind | None
    use: str
    policy_ok: bool
    failures: list[str] = field(default_factory=list)  # critères / exclusions (le candidat est écarté)
    failure_codes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    obstacles: list[str] = field(default_factory=list)
    subscores: dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    beacon: bool = False
    top_landing: bool = False
    wind_exceeded: bool = False  # vent ou rafales à l'arrivée au-dessus du seuil du niveau
    takeoff: Site | None = None
    wing: float = 8.5
    glide_source: object = (0.0, 0.0)  # vent sur le plané : GlideField (§14) ou (vitesse, direction) uniforme
    origin_name: str | None = None  # point de la route d'où le terrain est évalué (secours d'un local / cross)
    origin_alt_m: float = 0.0
    t_origin: datetime | None = None  # heure de départ du plané évalué
    path: list[tuple[float, float]] = field(default_factory=list)  # contournement d'une zone interdite (lat, lon)

    @property
    def kind(self) -> str:
        return self.spot.kind

    @property
    def usable(self) -> bool:
        return self.reachable and self.policy_ok and self.use != "never" and not self.failures

    @property
    def can_be_main(self) -> bool:
        return self.usable and self.use in ("main", "main_marginal")


def _sensitive_hit(ctx: DataContext, site: Site) -> tuple[str, str] | None:
    """(code, texte) si le terrain est dans un cœur de parc, une zone réglementée ou une zone de quiétude active."""
    if not ctx.sensitive_areas:
        return None
    from shapely.geometry import Point

    p = Point(site.lon, site.lat)
    month = ctx.target_time.month
    for area in ctx.sensitive_areas:
        try:
            inside = area.geometry.contains(p)
        except Exception:  # pragma: no cover - géométrie invalide
            continue
        if not inside:
            continue
        if area.kind == "national_park_core":
            return "NATIONAL_PARK", f"en cœur de parc national ({area.name})"
        if area.active_in_month(month):
            what = "zone réglementée" if area.kind == "regulatory" else "zone de quiétude faune active"
            return "SENSITIVE_AREA", f"dans une {what} ({area.name})"
    return None


def _road_m(spot: LandingSpot) -> float | None:
    if spot.road_m is not None:
        return spot.road_m
    if "road" in spot.clearances and spot.clearances["road"] is not None:
        return spot.clearances["road"]
    txt = (spot.access or "").lower()
    if not txt:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(km|m)\b", txt)
    if m:
        v = float(m.group(1).replace(",", "."))
        return v * 1000.0 if m.group(2) == "km" else v
    if any(w in txt for w in ("route", "parking", "chemin", "piste", "navette", "accès")):
        return rules.ACCESS_TEXT_ROAD_M
    return None


def compute_subscores(ev: LandingEval, level: str) -> dict[str, float]:
    spot = ev.spot
    lv = _lvl(level)
    m = rules.UNOFFICIAL_LANDING_MIN
    official = spot.kind == "official"
    s: dict[str, float] = {}
    s["glide_margin"] = 100.0 if ev.top_landing else glide_subscore(ev.glide.ratio)
    # obstacles (lignes, arbres, bâtiments, eau ; la route compte pour l'accès) : 100 si toutes les distances ≥ 2 × le
    # minimum, 0 si une distance est au minimum ; non cartographié : 50
    vals: list[float] = []
    for key, min_key, _ in CLEARANCES:
        if key == "road":
            continue
        if key not in spot.clearances:
            if not official:
                vals.append(float(m["unknown_clearance_subscore"]))
            continue
        d = spot.clearances[key]
        if d is None:
            vals.append(100.0)
            continue
        mn = _min_clearance(key, min_key, lv)
        vals.append(linear(d / mn, 1.0, 0.0, rules.OBSTACLE_SUBSCORE_FULL_AT, 100.0))
    s["obstacles"] = min(vals) if vals else 100.0
    # vent à l'arrivée : < 50 % du seuil et axe ≤ 15° → 100 ; au seuil ou axe à 45° → 0
    lw = ev.wind
    if lw is None:
        s["wind_at_arrival"] = rules.LANDING_WIND_UNKNOWN_SUBSCORE
    else:
        ratio = max(lw.speed_kmh / rules.LANDING_WIND_MAX_KMH[level], lw.gust_kmh / rules.LANDING_GUST_MAX_KMH[level])
        sw = linear(ratio, 0.5, 100.0, 1.0, 0.0)
        if spot.axis_deg is not None and lw.speed_kmh >= rules.CALM_WIND_KMH:
            ang = min(angle_diff(lw.direction_deg, spot.axis_deg), angle_diff(lw.direction_deg, spot.axis_deg + 180))
            sw = min(sw, linear(ang, 15.0, 100.0, float(m["long_axis_vs_wind_max_deg"]), 0.0))
        s["wind_at_arrival"] = sw
    # taille : 100 à 2 × les dimensions minimales, 0 au minimum
    if spot.size is not None:
        r = min(spot.size[0] / m["length_m"][lv], spot.size[1] / m["width_m"][lv])
        s["size"] = linear(r, 1.0, 0.0, rules.SIZE_SUBSCORE_FULL_AT, 100.0)
    else:
        s["size"] = 100.0 if official else rules.UNKNOWN_SIZE_SUBSCORE
    u = rules.COMMUNITY_USAGE_SUBSCORE
    if official:
        s["community_usage"] = float(u["official"])
    elif spot.kind == "field":
        s["community_usage"] = float(u["field"])
    else:
        s["community_usage"] = float(u.get(spot.community_usage, u["unknown"]))
    if spot.slope_pct is not None:
        s["slope"] = linear(spot.slope_pct, 3.0, 100.0, float(m["slope_pct_max"][lv]), 0.0)
    else:
        s["slope"] = 100.0 if official else rules.UNKNOWN_SLOPE_SUBSCORE
    road = _road_m(spot)
    if road is None:
        s["access"] = float(rules.ACCESS_UNKNOWN_SUBSCORE)
    else:
        (d0, s0), (d1, s1) = sorted(rules.ACCESS_SUBSCORE_BY_ROAD_M.items())
        s["access"] = s0 if road <= d0 else (linear(road, d0, s0, d1, s1) if road <= d1 else 0.0)
    s["beacon"] = 100.0 if ev.beacon else 0.0
    return s


def weighted_score(subscores: dict[str, float], kind: str) -> float:
    w = rules.LANDING_CANDIDATE_WEIGHTS
    total = sum(w[k] * subscores.get(k, 0.0) for k in w) / sum(w.values())
    return round(min(100.0, total + rules.LANDING_CATEGORY_BONUS[kind]), 1)


def capped_score(subscores: dict[str, float], kind: str) -> float:
    """Score pondéré plafonné à 40 + min(sous-scores finesse, vent d'arrivée) (non compensatoire, CDC §9.1) : un
    atterro hors de portée ou balayé par le vent ne peut pas être bien classé grâce à sa taille ou à son accès."""
    safety = min(subscores.get("glide_margin", 0.0), subscores.get("wind_at_arrival", 0.0))
    return round(min(weighted_score(subscores, kind), rules.SAFETY_CAP_OFFSET + safety), 1)


def _size_text(spot: LandingSpot) -> str:
    noun = spot.surface or ("terrain" if spot.kind != "field" else "champ")
    return f"{noun} de {spot.size[0]:.0f} × {spot.size[1]:.0f} m" if spot.size else f"{noun}, taille inconnue"


def _phrase(key: str, ev: LandingEval) -> str:
    spot, s = ev.spot, ev.subscores[key]
    if key == "glide_margin":
        if ev.top_landing:
            return "posé au décollage"
        g = ev.glide
        if not g.terrain_ok:
            return "le relief coupe la ligne de plané"
        if g.ratio > 1.0:
            return f"hors de portée (finesse requise {fr_num(g.required_ratio)} pour {fr_num(g.available_ratio)})"
        q = "confortable" if s >= 100 else ("correcte" if s >= 60 else "juste")
        txt = f"marge de finesse {q} ({fr_num(g.ratio, 2)})"
        if ev.origin_name:
            txt += f", depuis {ev.origin_name} à {ev.origin_alt_m:.0f} m"
        return txt
    if key == "obstacles":
        near = [o for o in ev.obstacles if "non cartographi" not in o]
        if s >= 100:
            return "aucun obstacle cartographié à proximité"
        if near:
            return near[0]
        return "obstacles non cartographiés"
    if key == "wind_at_arrival":
        lw = ev.wind
        if lw is None:
            return "vent d'arrivée inconnu"
        return f"vent d'arrivée {dir_label(lw.direction_deg)} {lw.speed_kmh:.0f} km/h" + (
            " (fort pour ton niveau)" if s < 40 else ""
        )
    if key == "size":
        return _size_text(spot)
    if key == "community_usage":
        return {
            "official": "atterro officiel",
            "field": "jamais repéré par des pilotes",
        }.get(spot.kind, {"frequent": "très utilisé par les pilotes", "occasional": "utilisé par les pilotes"}.get(
            spot.community_usage, "usage par les pilotes inconnu"))  # fmt: skip
    if key == "slope":
        return f"pente {spot.slope_pct:.0f} %" if spot.slope_pct is not None else "pente non mesurée"
    if key == "access":
        road = _road_m(spot)
        if road is None:
            return "accès inconnu"
        return f"route à {road:.0f} m" if road < 1000 else f"route à {road / 1000:.1f} km".replace(".", ",")
    return "balise à l'atterro" if ev.beacon else "pas de balise à l'atterro"


def reasons_for(ev: LandingEval) -> list[str]:
    """2 ou 3 sous-scores qui ont décidé : distance + marge de finesse, puis les plus marquants (bons ou mauvais)."""
    w = rules.LANDING_CANDIDATE_WEIGHTS
    spot = ev.spot
    head = f"{ev.distance_km:.1f} km".replace(".", ",") + f", {_phrase('glide_margin', ev)}"
    unknown_official = spot.kind == "official"  # atterro officiel sans fiche détaillée : pas de « taille inconnue »
    keys = [k for k in w if k != "glide_margin"
            and not (k == "obstacles" and unknown_official and not spot.clearances)
            and not (k == "size" and unknown_official and spot.size is None)
            and not (k == "slope" and unknown_official and spot.slope_pct is None)
            and not (k == "access" and _road_m(spot) is None)
            and not (k == "wind_at_arrival" and ev.wind is None)]  # fmt: skip
    others = sorted(keys, key=lambda k: -w[k] * abs(ev.subscores[k] - 50.0))
    return [head, *[_phrase(k, ev) for k in others[:2]]]


def _obstacle_texts(spot: LandingSpot, lv: str) -> tuple[list[str], list[str]]:
    """(obstacles publiés, avertissements « obstacle connu à moins de 2 fois la distance minimale »)."""
    obs: list[str] = []
    warn: list[str] = []
    noun = "du champ" if spot.kind == "field" else "du terrain"
    for key, min_key, label in CLEARANCES:
        if key not in spot.clearances:
            if key == "power_line" and spot.kind != "official":
                obs.append("lignes électriques non cartographiées")
            continue
        d = spot.clearances[key]
        if d is None:
            continue
        mn = _min_clearance(key, min_key, lv)
        brg = spot.clearance_bearings.get(key)
        where = ""
        if brg is not None:
            c = _compass_fr(brg)
            where = f" à l'{c}" if c[0] in "eo" else f" au {c}"
        obs.append(f"{label} à {d:.0f} m{where}")
        if d < rules.OBSTACLE_SUBSCORE_FULL_AT * mn and key != "road":
            warn.append(f"{label.capitalize()} à {d:.0f} m{where} {noun}.")
    for ob in spot.approach:
        side = _compass_fr(ob.bearing_deg)
        obs.append(f"{ob.label} ({ob.height_m:.0f} m) à {ob.distance_m:.0f} m dans l'axe, côté {side}")
    return obs, warn


def evaluate_spot(
    ctx: DataContext,
    takeoff: Site,
    spot: LandingSpot,
    level: str,
    wing: float,
    glide_wind,
    arrival: datetime,
    policy: str,
    lw: LandingWind | None = None,
    main_classic: bool = False,
    origin: tuple[float, float, float, str] | None = None,
    pair: bool = False,
    t_origin: datetime | None = None,
    path: list[tuple[float, float]] | None = None,
) -> LandingEval:
    """Évalue un atterro candidat depuis le déco (ou depuis `origin` = (lat, lon, altitude, nom) : point de la route
    d'où un secours est rejoint). `glide_wind` : champ de vent du vol (`GlideField`, vent rencontré §14) ou (vitesse,
    direction) uniforme ; `t_origin` : heure de départ du plané ; `path` : contournement d'une zone interdite.
    `main_classic` : atterro principal d'un plan classique — un vent d'arrivée au-dessus du seuil du niveau n'y est
    qu'un avertissement (le plan le juge, LANDING_WIND) ; partout ailleurs (secours, analyse d'un décollage libre)
    l'atterro est écarté (décision expert, REPRISE §8). `pair` : plané direct déco → atterro officiel associé par la
    source, relief vérifié (k = GLIDE_K_ASSOCIATED_PAIR)."""
    site = spot.site
    kind = spot.kind
    top = site.id == takeoff.id
    src = takeoff
    if origin is not None and not top:
        src = takeoff.model_copy(update={"lat": origin[0], "lon": origin[1], "elevation_m": float(origin[2])})
    dist = haversine_km(src.lat, src.lon, site.lat, site.lon)
    brg = bearing_deg(src.lat, src.lon, site.lat, site.lon)
    alt = src.elevation_m
    if top:
        std = glide = calm_glide(wing, level, site.name)
        arrival_h = 0.0
    else:
        std = glide_to(ctx, src.lat, src.lon, alt, site, level, wing, glide_wind, kind="official",
                       pair=pair and kind == "official", path=path, t=t_origin)  # fmt: skip
        glide = std if kind == "official" else glide_to(ctx, src.lat, src.lon, alt, site, level, wing,
                                                         glide_wind, kind=kind, path=path, t=t_origin)  # fmt: skip
        path_km = glide.dist_km or dist
        arrival_h = (alt - site.elevation_m) - (path_km * 1000.0 / glide.available_ratio if glide.available_ratio > 0
                                                else 1e9)  # fmt: skip
    if lw is None and not top:
        tl = timeline_for(ctx, site, ctx.timelines.get(takeoff.id))
        if tl is not None and tl.hours:
            lw = landing_wind(tl, arrival, big_valley(ctx, site), ctx, site)
    eff_policy = effective_policy(policy, level)
    ev = LandingEval(
        spot=spot, distance_km=dist, bearing_deg=brg, reachable=bool(std.margin_ok) or top, std_glide=std,
        glide=glide, arrival_height_m=arrival_h, wind=lw,
        use=kind_use(kind, level, spot.community_usage) if kind != "official" else "main",
        policy_ok=kind in rules.LANDING_POLICY_KINDS[eff_policy], top_landing=top, takeoff=src, wing=wing,
        glide_source=glide_wind, t_origin=t_origin, path=list(path or []),
    )  # fmt: skip
    if origin is not None and not top and src is not takeoff:
        ev.origin_name = origin[3]
        ev.origin_alt_m = float(origin[2])
    lv = _lvl(level)
    # exclusions et critères (§12.7) ; hors de portée = écarté, quel que soit le kind (CDC §10 #7)
    if not top and not std.terrain_ok:
        ev.failures.append("le relief coupe la ligne de plané")
        ev.failure_codes.append("GLIDE_MARGIN")
    elif not top and not std.margin_ok:
        ev.failures.append(f"hors de portée (finesse requise {fr_num(std.required_ratio)} pour "
                           f"{fr_num(std.available_ratio)} disponible)")  # fmt: skip
        ev.failure_codes.append("GLIDE_MARGIN")
    if lw is not None and (
        lw.speed_kmh > rules.LANDING_WIND_MAX_KMH[level] or lw.gust_kmh > rules.LANDING_GUST_MAX_KMH[level]
    ):
        ev.wind_exceeded = True
        if kind == "official" and main_classic:
            # atterro principal d'un plan classique : jugé par le plan (LANDING_WIND, niveau requis), pas exclu ici
            ev.warnings.append(f"Vent à l'arrivée {lw.speed_kmh:.0f} km/h, rafales {lw.gust_kmh:.0f} : au-dessus du "
                               f"seuil de ton niveau ({rules.LANDING_WIND_MAX_KMH[level]} / "
                               f"{rules.LANDING_GUST_MAX_KMH[level]}).")  # fmt: skip
        else:
            lim = f"{rules.LANDING_WIND_MAX_KMH[level]} / {rules.LANDING_GUST_MAX_KMH[level]}"
            ev.failures.append(f"vent d'arrivée {lw.speed_kmh:.0f} km/h, rafales {lw.gust_kmh:.0f} (seuils {lim})")
            ev.failure_codes.append("LANDING_WIND")
    hit = _sensitive_hit(ctx, site)
    if kind != "official":
        if hit is not None:
            ev.failures.append(hit[1])
            ev.failure_codes.append(hit[0])
        fails, notes = criteria_failures(spot, level, lw)
        if ev.reachable and not glide.margin_ok:
            margin, f = kind_glide_params(kind, level, alt - site.elevation_m)
            fails.append(f"marge de finesse insuffisante pour un {KIND_LABEL[kind]} (finesse requise "
                         f"{fr_num(glide.required_ratio)} pour {fr_num(glide.available_ratio)} = finesse de calcul × "
                         f"{fr_num(f, 2)}, arrivée à {margin:.0f} m sol au moins)")  # fmt: skip
        ev.failures += fails
        ev.failure_codes += ["DETECTED_FIELD" if kind == "field" else "UNOFFICIAL_LANDING"] * len(fails)
        ev.notes += notes
    elif hit is not None and not top:
        ev.warnings.append(f"Atterro {hit[1]} : vérifie la consigne du site et les limites de la zone.")
    # balise représentative près du terrain (tous horizons : utile au pilote avant de partir)
    if not top:
        tl = timeline_for(ctx, site, ctx.timelines.get(takeoff.id))
        if tl is not None and tl.hours and ctx.beacons:
            ev.beacon = any(a.representative for a in site_attachments(ctx, site, "landing", tl, big_valley(ctx, site)))
    obstacles, near_warn = _obstacle_texts(spot, lv)
    ev.obstacles = obstacles
    # avertissements obligatoires
    if spot.demo:
        ev.warnings.append("Terrain de DÉMONSTRATION (fictif, données hors-ligne) : ne pas l'utiliser pour voler.")
    if kind in ("community", "field"):
        ev.warnings.append(rules.UNOFFICIAL_WARNINGS[kind])
        if kind == "field" and ctx.target_time.month in rules.FIELD_CROP_SEASON_MONTHS:
            ev.warnings.append(rules.UNOFFICIAL_WARNINGS["field_season"])
        if "power_line" not in spot.clearances:
            ev.warnings.append(rules.UNOFFICIAL_WARNINGS["unknown_clearance"])
        ev.warnings += near_warn + ev.notes
    ev.subscores = compute_subscores(ev, level)
    ev.score = capped_score(ev.subscores, kind)
    ev.reasons = reasons_for(ev)
    return ev


def to_candidate(ev: LandingEval) -> LandingCandidate:
    spot = ev.spot
    lw = ev.wind
    reasons = list(ev.reasons)
    if ev.failures:
        reasons.append("Écarté : " + " ; ".join(ev.failures[:3]) + ".")
    return LandingCandidate(
        site=spot.site,
        kind=spot.kind,  # type: ignore[arg-type]
        use="alternate" if ev.use == "alternate" else "main",
        score=ev.score,
        required_glide_ratio=round(ev.glide.required_ratio, 2) if ev.glide.required_ratio < 99 else 99.0,
        available_glide_ratio=round(ev.glide.available_ratio, 2),
        wind_along_track_kmh=None if ev.glide.wind_along_kmh is None else round(ev.glide.wind_along_kmh, 1),
        arrival_height_m=round(ev.arrival_height_m),
        size_m=SizeM(length=round(spot.size[0]), width=round(spot.size[1])) if spot.size else None,
        slope_pct=None if spot.slope_pct is None else round(spot.slope_pct, 1),
        surface=spot.surface,
        obstacles=ev.obstacles,
        wind_at_arrival=None
        if lw is None
        else ArrivalWind(
            speed_kmh=round(lw.speed_kmh, 1),
            direction_deg=round(lw.direction_deg) % 360,
            gust_kmh=round(lw.gust_kmh, 1),
        ),
        community_usage=spot.community_usage if spot.community_usage in ("frequent", "occasional") else "unknown",
        access=spot.access,
        warnings=list(dict.fromkeys(ev.warnings)),
        reasons=reasons,
    )


# =============================================================================================
# Sélection (décollage libre) et rejet expliqué
# =============================================================================================
@dataclass
class LandingSelection:
    evals: list[LandingEval]  # tous les candidats évalués, triés (utilisables d'abord, puis score)
    main: LandingEval | None
    alternates: list[LandingEval]
    reasons: list[str]  # rejet expliqué quand aucun atterro principal n'est possible
    warnings: list[str]
    policy: str  # politique effective (élève : official_only)


def _rank(ev: LandingEval) -> tuple:
    """Utilisables d'abord, principaux possibles d'abord, vent d'arrivée dans les seuils d'abord, puis score."""
    return (not ev.usable, not ev.can_be_main, ev.wind_exceeded, -ev.score)


def glide_field_for(ctx: DataContext, takeoff: Site, t: datetime) -> GlideField | tuple[float, float]:
    """Vent sur les planés depuis un décollage à l'heure t (§14 : vent rencontré, brise de chaque atterro à l'heure
    d'arrivée) ; (0, 0) sans prévision au déco."""
    tl = ctx.timelines.get(takeoff.id)
    if tl is None or not tl.hours:
        return 0.0, 0.0
    return GlideField(ctx, takeoff, tl, t)


def select_landings(
    ctx: DataContext, takeoff: Site, level: str, wing: float, policy: str, start: datetime | None = None
) -> LandingSelection:
    """Évalue tous les atterros du contexte depuis `takeoff` (décollage libre) ; atterro principal = meilleur score
    parmi ceux qui peuvent l'être à ce niveau ; secours = suivants (≤ 3). Planés au vent rencontré (§14), en
    contournant les zones où le vol libre est interdit."""
    start = start or ctx.target_time
    eff = effective_policy(policy, level)
    warnings: list[str] = []
    if eff != policy:
        warnings.append(rules.UNOFFICIAL_WARNINGS["beginner_policy"])
    field = glide_field_for(ctx, takeoff, start)
    proj = projector_for(ctx, takeoff)
    evals: list[LandingEval] = []
    for site in ctx.landings.values():
        if site.id == takeoff.id or site.elevation_m >= takeoff.elevation_m - rules.TOP_LANDING_MAX_DROP_M:
            continue
        if site.elevation_m < 0:  # altitude inconnue (MNT indisponible) : jamais de portée « optimiste »
            continue
        spot = spot_for(ctx, site)
        arrival = start + timedelta(minutes=plouf_minutes(takeoff.elevation_m - site.elevation_m))
        path, _ = path_for(ctx, proj, takeoff.lat, takeoff.lon, site)
        evals.append(evaluate_spot(ctx, takeoff, spot, level, wing, field, arrival, policy, t_origin=start, path=path))
    evals.sort(key=_rank)
    mains = [e for e in evals if e.can_be_main]
    main = mains[0] if mains else None
    alternates = [e for e in evals if e.usable and e is not main][:3]
    reasons = [] if main is not None else explain_no_main(evals, level, policy)
    return LandingSelection(evals, main, alternates, reasons, warnings, eff)


def explain_no_main(evals: list[LandingEval], level: str, policy: str) -> list[str]:
    """Raison de rejet (§12.7) : nomme le meilleur candidat écarté et la cause."""
    reach = sorted((e for e in evals if e.reachable), key=lambda e: -e.score)
    if not reach:
        return ["[GLIDE_MARGIN] Aucun atterro à portée de plané avec la marge requise."]
    kinds = {e.kind for e in reach}
    if kinds == {"field"} and level in ("beginner", "intermediate"):
        return ["[DETECTED_FIELD] Seul un champ détecté (jamais repéré) est à portée de plané : jamais proposé à ce "
                "niveau."]  # fmt: skip
    if level == "beginner" and kinds <= {"community", "field"}:
        return ["[UNOFFICIAL_LANDING] Seul un atterro communautaire est à portée : non proposé à un élève."]
    best = reach[0]
    code = "DETECTED_FIELD" if best.kind == "field" else ("UNOFFICIAL_LANDING" if best.kind == "community"
                                                           else "GLIDE_MARGIN")  # fmt: skip
    name = f"« {best.spot.site.name} » ({KIND_LABEL[best.kind]})"
    if not best.policy_ok:
        return [f"[{code}] Seul atterro à portée : {name}, exclu par ta politique d'atterrissage "
                f"({POLICY_LABEL[effective_policy(policy, level)]}). Élargis-la pour l'étudier."]  # fmt: skip
    if best.failures:
        fcode = best.failure_codes[0] if best.failure_codes else code
        return [f"[{fcode}] Meilleur candidat écarté : {name} — {best.failures[0]}."]
    if best.use == "alternate":
        why = ("un champ détecté ne sert que de secours à ce niveau" if best.kind == "field"
               else "un atterro communautaire d'usage occasionnel ou inconnu ne sert que de secours au niveau brevet "
                    "de pilote")  # fmt: skip
        return [f"[{code}] Seul atterro à portée : {name} : {why}."]
    return [f"[{code}] Aucun atterro utilisable comme atterro principal à ce niveau ({name} écarté)."]


# =============================================================================================
# Constats du plan liés à l'atterro (catégorie, avertissements)
# =============================================================================================
def landing_kind_findings(ctx: DataContext, sel_main: LandingEval, alternates: list[LandingEval]) -> list[Finding]:
    """UNOFFICIAL_LANDING / DETECTED_FIELD (§12.8). Atterro principal : niveau de risque par niveau de pilote (danger
    là où ce kind ne peut pas être principal ou ne remplit pas les critères) ; secours : info."""
    out: list[Finding] = []
    main = sel_main
    if main.kind != "official":
        code = "DETECTED_FIELD" if main.kind == "field" else "UNOFFICIAL_LANDING"
        title = "Champ détecté, jamais repéré" if main.kind == "field" else "Atterro non officiel"
        lr: dict[str, str | None] = {}
        for lv in LEVELS:
            use = kind_use(main.kind, lv, main.spot.community_usage)
            ok_main = use in ("main", "main_marginal") and _criteria_ok_at(ctx, main, lv)
            if not ok_main:
                lr[lv] = "danger"
            elif main.kind == "field":
                lr[lv] = rules.RISK_LEVELS["DETECTED_FIELD"]["main"]
            else:
                lr[lv] = rules.RISK_LEVELS["UNOFFICIAL_LANDING"].get(lv, "danger")
        detail = f"{main.spot.site.name} ({KIND_LABEL[main.kind]}) : " + " ".join(dict.fromkeys(main.warnings))
        out.append(Finding(code, title, detail, level_risk=lr))
    for alt in alternates:
        if alt.kind == "official":
            continue
        code = "DETECTED_FIELD" if alt.kind == "field" else "UNOFFICIAL_LANDING"
        out.append(Finding(code, "Atterro de secours non officiel",
                           f"Secours {alt.spot.site.name} ({KIND_LABEL[alt.kind]}) : "
                           + rules.UNOFFICIAL_WARNINGS[alt.kind], info=True))  # fmt: skip
    return out


def _criteria_ok_at(ctx: DataContext, ev: LandingEval, level: str) -> bool:
    """Le terrain remplit-il les critères minimaux et la marge de finesse de son kind au niveau `level` ?"""
    if ev.kind == "official":
        return True
    if level == "beginner" or ev.takeoff is None:
        return False
    fails, _ = criteria_failures(ev.spot, level, ev.wind)
    if fails:
        return False
    t = ev.takeoff
    g = glide_to(ctx, t.lat, t.lon, t.elevation_m, ev.spot.site, level, ev.wing, ev.glide_source, kind=ev.kind,
                 path=ev.path, t=ev.t_origin)  # fmt: skip
    return bool(g.margin_ok)


def candidates_for_plan(
    ctx: DataContext,
    takeoff: Site,
    landing: Site,
    alternates: list[Site],
    level: str,
    wing: float,
    glide_wind,
    arrival: datetime,
    policy: str,
    lw_main: LandingWind | None,
    extra: list[LandingEval] | None = None,
    alt_evals: list[LandingEval] | None = None,
    main_classic: bool = True,
    pair: bool = False,
    t_origin: datetime | None = None,
    main_path: list[tuple[float, float]] | None = None,
) -> list[LandingCandidate]:
    """FlightPlan.landing_analysis : l'atterro du plan en premier (vent d'arrivée du plan, même plané que le plan :
    même heure de départ, même contournement), puis les secours retenus (évalués depuis le point de la route d'où ils
    sont rejoints, `alt_evals`) et les autres candidats utilisables, par score décroissant. Un terrain écarté (hors de
    portée, vent d'arrivée) n'est jamais publié comme secours."""
    main_ev = evaluate_spot(ctx, takeoff, spot_for(ctx, landing), level, wing, glide_wind, arrival, policy,
                            lw=lw_main if landing.id != takeoff.id else None, main_classic=main_classic,
                            pair=pair, t_origin=t_origin, path=main_path)  # fmt: skip
    others: list[LandingEval] = []
    seen = {landing.id}
    if alt_evals is not None:
        for e in alt_evals:
            if e.spot.site.id in seen:
                continue
            seen.add(e.spot.site.id)
            others.append(e)
    else:
        proj = projector_for(ctx, takeoff)
        for s in alternates:
            if s.id in seen:
                continue
            seen.add(s.id)
            path, _ = path_for(ctx, proj, takeoff.lat, takeoff.lon, s)
            ev = evaluate_spot(ctx, takeoff, spot_for(ctx, s), level, wing, glide_wind, arrival, policy,
                               t_origin=t_origin, path=path)  # fmt: skip
            if ev.usable:
                others.append(ev)
    for e in extra or []:
        if e.spot.site.id in seen or not e.usable:
            continue
        seen.add(e.spot.site.id)
        others.append(e)
    others.sort(key=lambda e: -e.score)
    return [to_candidate(e) for e in [main_ev, *others][: rules.LANDING_MAX_IN_ANALYSIS]]


def cone_finesse(level: str, wing: float, wind, t: datetime | None = None):
    """finesse(cap) pour le cône de finesse (§14.1) : finesse de calcul sol du niveau (k), vent moyen du profil du
    déco sur [alt_déco − 1000 m ; alt_déco], crédit du niveau sans bonus (champ de vent) ; vent uniforme sinon."""
    if isinstance(wind, GlideField):
        speed, direction = wind.cone_wind(t)
        credit = wind.cone_credit(t)
        k = rules.GLIDE_K[level]
        return lambda brg: uniform_finesse(wing, level, k, speed, direction, brg, credit)
    return lambda brg: finesse_sol(wing, level, wind[0], wind[1], brg)


def analyze_free_takeoff(
    ctx: DataContext, takeoff: Site, level: str, wing: float, policy: str
) -> tuple[list[LandingCandidate], dict, list[str]]:
    """POST /api/landings/analyze : candidats utilisables à ce niveau (principaux possibles d'abord, puis par score),
    cône de finesse (GeoJSON Polygon) et avertissements (refus élève, politique, meilleurs candidats écartés)."""
    from app.engine.terrain import cone_geojson, glide_cone

    sel = select_landings(ctx, takeoff, level, wing, policy)
    warnings: list[str] = []
    if level not in rules.FREE_TAKEOFF["allowed_levels"]:
        warnings.append(rules.FREE_TAKEOFF["refusal_beginner"])
    warnings += sel.warnings
    if sel.main is None:
        warnings += [r.split("] ", 1)[-1] for r in sel.reasons]
    usable = sorted((e for e in sel.evals if e.usable), key=lambda e: (not e.can_be_main, -e.score))
    for e in [e for e in sel.evals if e.reachable and not e.usable][:3]:
        why = e.failures[0] if e.failures else (
            "exclu par ta politique d'atterrissage" if not e.policy_ok else "jamais proposé à ce niveau"
        )  # fmt: skip
        warnings.append(f"« {e.spot.site.name} » ({KIND_LABEL[e.kind]}) écarté : {why}.")
    gw = glide_field_for(ctx, takeoff, ctx.target_time)
    floor = min((e.spot.site.elevation_m for e in sel.evals), default=takeoff.elevation_m - 1000.0)
    # relief : MNT réel seulement (contrat) — comme terrain_clear() pour les candidats ; le MNT de démonstration,
    # lisse, coupait le cône dès le pied du déco alors que les candidats restaient atteignables
    real_terrain = ctx.terrain is not None and ctx.terrain_is_real
    ring = glide_cone(
        takeoff.lat, takeoff.lon, takeoff.elevation_m, cone_finesse(level, wing, gw, ctx.target_time),
        ctx.terrain_at if real_terrain else None, float(rules.LANDING_ARRIVAL_MARGIN_M[level]), floor,
    )  # fmt: skip
    return [to_candidate(e) for e in usable[: rules.LANDING_MAX_IN_ANALYSIS]], cone_geojson(ring), warnings
