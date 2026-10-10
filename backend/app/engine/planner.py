"""Moteur de plans de vol : pour chaque décollage de la zone, évalue les variantes de vol (plouf,
local thermique, soaring, cross) sur les créneaux autour de l'heure cible, applique les filtres durs
(§3 no-go, §2 seuils par niveau), calcule score / verdict / difficulté, puis classe les plans.

Point d'entrée : `evaluate_sites(ctx, filters) -> (plans, rejected, warnings)` (synchrone, sans réseau).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import pairwise

from app.engine import free_takeoff, rules
from app.engine.airspace import (
    AirspaceResult,
    Projector,
    evaluate_airspaces,
    evaluate_sensitive_route,
    evaluate_sensitive_sites,
)
from app.engine.briefing import briefing, checklist, duration_label, summary, title
from app.engine.conditions import (
    LandingWind,
    TakeoffWind,
    dir_label,
    fmt_hm,
    landing_wind,
    lee_angle,
    solar_hour,
    sun_times,
    takeoff_wind,
)
from app.engine.context import DataContext, PointTimeline
from app.engine.findings import Finding, max_level, smallest_passing_level
from app.engine.glidewind import (
    GlideField,
    au,
    glide_comment,
    high_arrival_detail,
    high_arrival_levels,
    plouf_minutes,
    quarter,
    wind_phrase,
)
from app.engine.landings import (
    LandingEval,
    LandingSelection,
    big_valley,
    candidates_for_plan,
    evaluate_spot,
    landing_kind_findings,
    select_landings,
    spot_for,
)
from app.engine.routing import (
    GlideCheck,
    projector_for,
    Route,
    alternates_waypoints,
    apply_detours,
    build_cross,
    build_local_thermal,
    build_plouf,
    build_ridge,
    calm_glide,
    glide_to,
    is_source_pair,
    landing_kind_of,
    path_for,
)
from app.engine.scoring import (
    CRITERION_LABEL_FR,
    CRITERION_RISK_CODE,
    aggregate_score,
    compute_confidence,
    confidence_factors,
    duration_subscore,
    glide_subscore,
    linear,
    thermal_match_subscore,
    verdict,
)
from app.engine.stations import (
    StationNowcast,
    duration_fr,
    landing_band_start,
    landing_confidence_factor,
    nearest_unattached,
    no_landing_beacon_finding,
    reading_comment,
    station_nowcast,
    trend_findings,
)
from app.engine.terrain import TakeoffTerrain
from app.geo import angle_diff, haversine_km
from app.meteo.snapshot import iso, snapshot_from_analysis, sounding_from_analysis
from app.meteo.thermals import ConvectionWindow, HourAnalysis, convection_window
from app.models import (
    HORIZON_MINUTES,
    AirspaceWarning,
    Beacon,
    FlightPlan,
    Glide,
    NowcastCorrection,
    PlanFilters,
    PlanLinks,
    PlanWeather,
    RejectedSite,
    Risk,
    RouteGeometry,
    Site,
    StationReading,
    SunTimes,
    ThermalAnalysis,
    TimeWindow,
)

LEVELS = rules.LEVELS
VARIANT_TYPE = {
    "plouf": "local",
    "restitution": "local",
    "local_thermal": "local",
    "ridge": "ridge_soaring",
    "xc": "cross_country",
}
# ALTITUDE_LIMIT n'est plus non bloquant par code (revue 7.15) : le plafond abaissé par un espace aérien ou le FL115
# reste non bloquant (blocks_go=False), le décollage au-dessus du FL115 est une caution bloquante
NON_BLOCKING_CAUTIONS = {
    "MOCK_DATA", "ACCESS_TIME", *rules.NON_BLOCKING_CAUTIONS_ADD, *rules.NON_BLOCKING_CAUTIONS_ADD_REV5,
}  # fmt: skip
ALL_CODES_ORDER = ["danger", "caution", "info"]


@dataclass
class Candidate:
    variant: str
    takeoff: Site
    landing: Site
    alternates: list[Site]
    start: datetime
    duration_min: float
    route: Route
    findings: list[Finding]
    takeoff_wind: TakeoffWind
    landing_wind: LandingWind
    convection: ConvectionWindow
    vario: float
    usable: float
    max_alt: float
    thermal_usage: str
    horizon: str
    level: str
    mock: bool
    sunrise: datetime | None
    sunset: datetime | None
    latest_landing: datetime
    landing_cap_reason: str | None
    duration_note: str | None
    airspace: AirspaceResult | None
    conf_raw: float = 0.0
    confidence: float = 0.0
    difficulty: str = "beginner"
    flyability: str = "no_go"
    score: float = 0.0
    raw_score: float = 0.0
    score_items: list = field(default_factory=list)
    risks: list[Risk] = field(default_factory=list)
    reject_reasons: list[str] = field(default_factory=list)
    window_start: datetime | None = None
    window_end: datetime | None = None
    airspaces: list[AirspaceWarning] = field(default_factory=list)
    glide_wind: object = (0.0, 0.0)  # vent sur les planés (§14) : GlideField du vol
    wing: float = 8.5
    ref_glide: GlideCheck | None = None  # plané direct déco → atterro principal au niveau du pilote (§14.4, 7.13)
    high_arrival_m: float | None = None  # hauteur d'arrivée attendue si HIGH_ARRIVAL (§14.4)
    free_terrain: TakeoffTerrain | None = None  # décollage libre (§12.6)
    landing_sel: LandingSelection | None = None  # candidats évalués (décollage libre)
    policy: str = "official_only"
    landing_warnings: list[str] = field(default_factory=list)  # avertissements de l'atterro (briefing)
    alt_evals: list[LandingEval] | None = None  # secours retenus, évalués depuis le point de route qui les rejoint
    zone_notes: list[str] = field(default_factory=list)  # zones interdites près de l'atterro (briefing Atterrissage)
    day_ceiling: float | None = None  # plafond utile max de la journée (aérologie du jour, revue 7.21)
    window_end_reason: str | None = None  # cause qui ferme le créneau (revue 7.7)

    @property
    def flight_type(self) -> str:
        return VARIANT_TYPE[self.variant]

    @property
    def landing_time(self) -> datetime:
        return self.start + timedelta(minutes=self.duration_min)

    def window_start_eta(self, eta_min: float | None) -> datetime:
        return self.start + timedelta(minutes=eta_min or 0)


# =============================================================================================
# Utilitaires
# =============================================================================================
def _round_time(t: datetime) -> datetime:
    return t.replace(minute=0, second=0, microsecond=0) + (timedelta(hours=1) if t.minute >= 30 else timedelta())


def _site_level(site: Site) -> str:
    return site.difficulty or rules.UNKNOWN_SITE_DIFFICULTY


def _codes_prefix(code: str, text: str) -> str:
    return f"[{code}] {text}"


def _usable_capped(a: HourAnalysis) -> float:
    return min(a.usable_ceiling_m, rules.FL115_M_STANDARD - rules.CEILING_MARGIN_BELOW_AIRSPACE_M)


def _in_region(lat: float, lon: float, region: str) -> bool:
    min_lat, min_lon, max_lat, max_lon = rules.REGIONS[region]
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


def _in_sector(direction: float, sector: tuple[float, float]) -> bool:
    lo, hi = sector
    d = direction % 360
    return lo <= d <= hi if lo <= hi else (d >= lo or d <= hi)


# =============================================================================================
# Constats météo (communs à toutes les variantes)
# =============================================================================================
def takeoff_wind_findings(tw: TakeoffWind, site: Site, ridge: bool, solar_h: float) -> list[Finding]:
    f: list[Finding] = []
    v, g = tw.speed_kmh, tw.gust_kmh
    spread = max(0.0, g - v)
    wind_lim = rules.RIDGE["max_kmh"] if ridge else rules.TAKEOFF_WIND_MAX_KMH
    gust_lim = rules.RIDGE_GUST_MAX_KMH if ridge else rules.TAKEOFF_GUST_MAX_KMH
    spread_lim = (
        {lv: min(rules.GUST_SPREAD_MAX_KMH[lv], rules.RIDGE_GUST_SPREAD_MAX_KMH) for lv in LEVELS}
        if ridge
        else rules.GUST_SPREAD_MAX_KMH
    )
    wdesc = f"{dir_label(tw.direction_deg)} {v:.0f} km/h, rafales {g:.0f} km/h"
    f.append(
        Finding(
            "TAKEOFF_WIND",
            "Vent moyen au déco" + (" (soaring)" if ridge else ""),
            f"Vent au déco {wdesc}.",
            criterion="takeoff_wind",
            value=v,
            limits=dict(wind_lim),
        )
    )
    f.append(
        Finding("TAKEOFF_GUSTS", "Rafales au déco", f"Rafales {g:.0f} km/h au déco.", criterion="takeoff_wind",
                value=g, limits=dict(gust_lim))
    )  # fmt: skip
    f.append(
        Finding("TAKEOFF_GUSTS", "Écart rafales / vent moyen", f"Écart rafale − moyenne de {spread:.0f} km/h (air "
                                                               f"turbulent).",
                criterion="takeoff_wind", value=spread, limits=dict(spread_lim))
    )  # fmt: skip
    if v >= rules.GUST_FACTOR_MIN_MEAN_KMH:
        f.append(
            Finding("TAKEOFF_GUSTS", "Vent rafaleux", f"Facteur de rafale {g / v:.2f} (rafale / moyenne).",
                    value=g / v, limits=dict(rules.GUST_FACTOR_MAX), soft=True, blocks_go=False)
        )  # fmt: skip
    # absolus §3 #9
    if (
        v > rules.NOGO["takeoff_wind_abs_kmh"]
        or g > rules.NOGO["takeoff_gust_abs_kmh"]
        or spread > rules.GUST_SPREAD_ABS_MAX_KMH
    ):
        code = "TAKEOFF_WIND" if v > rules.NOGO["takeoff_wind_abs_kmh"] else "TAKEOFF_GUSTS"
        f.append(
            Finding(
                code,
                "Vent au déco hors limites (tous niveaux)",
                f"Vent au déco {wdesc} : hors limites.",
                absolute_nogo=True,
            )
        )
    ang = tw.angle
    if not ang.calm:
        if ang.category == "cross":
            f.append(
                Finding("CROSSWIND", "Vent de travers au déco",
                        f"Vent {ang.ecart_deg:.0f}° hors de l'axe du déco (orientations "
                        f"{', '.join(site.orientations)}).",
                        criterion="takeoff_wind", value=ang.ecart_deg,
                        limits=dict(rules.RIDGE["max_angle_deg"] if ridge else rules.CROSSWIND_ANGLE_MAX_DEG))
            )  # fmt: skip
            f.append(
                Finding(
                    "CROSSWIND",
                    "Composante de travers",
                    f"Composante de travers {ang.cross_component_kmh:.0f} km/h.",
                    criterion="takeoff_wind",
                    value=ang.cross_component_kmh,
                    limits=dict(rules.CROSSWIND_COMPONENT_MAX_KMH),
                )
            )
        elif ang.category == "tail":
            if ridge:
                f.append(
                    Finding(
                        "TAILWIND",
                        "Vent arrière : pas de soaring possible",
                        "Vent arrière sur la pente.",
                        feasibility=True,
                        value=0.0,
                        limits={lv: 1.0 for lv in LEVELS},
                        kind="min",
                    )
                )
            f.append(
                Finding("TAILWIND", "Vent arrière au déco",
                        f"Vent arrière de {ang.tail_component_kmh:.0f} km/h ({dir_label(tw.direction_deg)}) au déco.",
                        criterion="takeoff_wind", value=ang.tail_component_kmh,
                        limits={lv: float(x) for lv, x in rules.TAILWIND_MAX_KMH.items()}, band=False)
            )  # fmt: skip
            f.append(
                Finding("TAILWIND", "Vent arrière au déco", f"Vent arrière de {ang.tail_component_kmh:.0f} km/h : "
                                                            f"décollage délicat.",
                        caution=True)
            )  # fmt: skip
            f.append(
                Finding(
                    "CROSSWIND",
                    "Composante de travers",
                    f"Composante de travers {ang.cross_component_kmh:.0f} km/h.",
                    criterion="takeoff_wind",
                    value=ang.cross_component_kmh,
                    limits=dict(rules.CROSSWIND_COMPONENT_MAX_KMH),
                )
            )
    # dévent / faux calme (§3 #8)
    lee = lee_angle(tw.crest_direction_deg, site.orientations)
    crest = f"vent de {tw.crest_speed_kmh:.0f} km/h du {dir_label(tw.crest_direction_deg)} au niveau des crêtes"
    if lee > rules.LEE_ANGLE_DEG and tw.crest_speed_kmh >= rules.NOGO["lee_wind_at_crest_kmh"]:
        f.append(Finding("LEE_SIDE", "Dévent : déco sous le vent",
                         f"Dévent : {crest}, opposé à l'axe du déco — rotors et faux calme, même si le vent au déco "
                         f"semble favorable.",
                         absolute_nogo=True))  # fmt: skip
    elif lee > rules.LEE_ANGLE_DEG and tw.crest_speed_kmh >= rules.LEE_WIND_CAUTION_KMH:
        f.append(Finding("LEE_SIDE", "Vent météo opposé au déco", f"Dévent possible : {crest}.", caution=True))
    elif 60.0 < lee <= rules.LEE_ANGLE_DEG and tw.crest_speed_kmh >= rules.SYNOPTIC_CROSSWIND_CAUTION_KMH:
        f.append(Finding("CROSSWIND", "Vent météo de travers", f"Vent météo de travers : {crest}.", caution=True))
    # déco E passé à l'ombre (§4.3 bascule)
    if site.orientations and all(o in ("NE", "ENE", "E", "ESE") for o in site.orientations):
        syn_e = (
            tw.crest_speed_kmh >= rules.EAST_FACE_SYNOPTIC_EXEMPT_KMH and angle_diff(tw.crest_direction_deg, 90) <= 45
        )
        if solar_h > rules.EAST_FACE_SHADE_SOLAR_H and not syn_e:
            f.append(Finding("LEE_SIDE", "Déco passé à l'ombre",
                             "Déco orienté est passé à l'ombre après 12h30 solaire : brise descendante, vent arrière "
                             "probable.",
                             absolute_nogo=True))  # fmt: skip
    return f


def aloft_findings(
    a: HourAnalysis, site: Site, top: float, ridge: bool, usable: float, thermal_flight: bool
) -> list[Finding]:
    out: list[Finding] = []
    alt = site.elevation_m
    zs = [alt + i * 100.0 for i in range(int(max(0.0, top - alt) / 100.0) + 1)]
    if not zs:
        zs = [alt]
    speeds = [(z, *a.profile.wind(z)) for z in zs]
    vmax_z, vmax, _ = max(speeds, key=lambda x: x[1])
    ratios: dict[str, float] = {}
    for lv in LEVELS:
        if ridge:
            lim = float(rules.RIDGE["max_kmh"][lv])
            rs = [v / lim for z, v, _ in speeds if z <= alt + rules.CREST_CHECK_ABOVE_TAKEOFF_M]
        else:
            rs = [v / rules.interp_aloft_threshold(z, lv) for z, v, _ in speeds]
        ratios[lv] = max(rs) if rs else 0.0
    out.append(
        Finding("STRONG_WIND_ALOFT",  # revue 7.18 : vent en altitude, même en soaring (pas le vent du déco)
                "Vent devant la crête" if ridge else "Vent en altitude",
                f"Vent jusqu'à {vmax:.0f} km/h vers {vmax_z:.0f} m sur la tranche volée.",
                criterion="wind_aloft", ratios=ratios)
    )  # fmt: skip
    if vmax >= rules.NOGO["wind_any_level_kmh"]:
        out.append(Finding("STRONG_WIND_ALOFT", "Vent fort en altitude", f"{vmax:.0f} km/h vers {vmax_z:.0f} m : "
                                                                         f"no-go.", absolute_nogo=True))
    elif vmax >= rules.WIND_ANY_LEVEL_CAUTION_KMH:
        out.append(
            Finding(
                "STRONG_WIND_ALOFT", "Vent soutenu en altitude", f"{vmax:.0f} km/h vers {vmax_z:.0f} m.", caution=True
            )
        )
    v3000 = a.profile.wind(3000.0)[0]
    if alt >= rules.MOUNTAIN_MIN_TAKEOFF_M and v3000 >= rules.NOGO["wind_3000m_mountain_kmh"]:
        out.append(
            Finding(
                "STRONG_WIND_ALOFT",
                "Vent très fort à 3000 m",
                f"{v3000:.0f} km/h à 3000 m : la turbulence descend sur les reliefs.",
                absolute_nogo=True,
            )
        )
    # gradient déco → déco + 1000 m (sur la tranche atteinte)
    z_top = min(alt + 1000.0, max(top, alt + 300.0))
    v0 = a.profile.wind(alt)[0]
    v1 = a.profile.wind(z_top)[0]
    out.append(
        Finding("WIND_GRADIENT", "Gradient de vent", f"Le vent passe de {v0:.0f} à {v1:.0f} km/h entre {alt:.0f} et "
                                                     f"{z_top:.0f} m.",
                criterion="wind_aloft", value=abs(v1 - v0), limits=dict(rules.GRADIENT_MAX_KMH_PER_1000M))
    )  # fmt: skip
    # cisaillement local (Δ vitesse sur 300 m)
    shear = 0.0
    for z, v, _ in speeds:
        if z + 300 <= top:
            shear = max(shear, abs(a.profile.wind(z + 300)[0] - v))
    if shear > 0:
        out.append(
            Finding("WIND_SHEAR", "Cisaillement", f"Variation de {shear:.0f} km/h sur 300 m dans la tranche volée.",
                    criterion="wind_aloft", value=shear, limits=dict(rules.SHEAR_MAX_KMH_PER_300M))
        )  # fmt: skip
    # rotation déco + 300 m → plafond utile (lot 2.3)
    if thermal_flight and usable > alt + 400:
        va, da = a.profile.wind(alt + rules.CREST_CHECK_ABOVE_TAKEOFF_M)
        vb, db = a.profile.wind(usable)
        if va >= rules.VEER_MIN_WIND_KMH and vb >= rules.VEER_MIN_WIND_KMH:
            veer = angle_diff(da, db)
            out.append(
                Finding("WIND_SHEAR", "Rotation du vent avec l'altitude",
                        f"Le vent tourne de {veer:.0f}° entre {alt + 300:.0f} m et {usable:.0f} m.",
                        criterion="wind_aloft", value=veer, limits=dict(rules.VEER_MAX_DEG))
            )  # fmt: skip
    # foehn (§3 #4)
    v7, d7 = a.profile.wind(3000.0)
    for region, sector in rules.FOEHN_SECTORS_DEG.items():
        if _in_region(site.lat, site.lon, region) and _in_sector(d7, sector):
            dry = (a.rh700_pct is not None and a.rh700_pct < rules.FOEHN_DRY_RH_PCT) or (
                a.temperature_c - a.dew_point_c > 12
            )
            if v7 >= rules.NOGO["foehn_700hpa_kmh"]:
                out.append(Finding("FOEHN", "Foehn", f"Flux de {dir_label(d7)} {v7:.0f} km/h à 700 hPa en travers de "
                                                     f"la crête principale : foehn, rotors et rafales en vallée.",
                                   absolute_nogo=True))  # fmt: skip
            elif v7 >= rules.FOEHN_CAUTION_700HPA_KMH and dry:
                out.append(Finding("FOEHN", "Tendance foehn", f"Flux de {dir_label(d7)} {v7:.0f} km/h à 700 hPa, air "
                                                              f"sec : tendance foehn.",
                                   caution=True))  # fmt: skip
    return out


def landing_findings(lw: LandingWind, landing: Site, end: datetime, band_start: float | None = None) -> list[Finding]:
    """Vent à l'atterro à l'heure d'arrivée (vent retenu : brise, balises de l'atterro, tendance extrapolée).
    `band_start` : début de la bande marginale (72 % sans balise représentative à l'atterro, §12.3)."""
    out: list[Finding] = []
    lw_lim = rules.LANDING_WIND_MAX_KMH
    lg_lim = rules.LANDING_GUST_MAX_KMH
    breeze = lw.breeze_factor > 1.0
    breeze_txt = f" (brise de vallée ×{lw.breeze_factor:.2f} incluse)" if breeze else ""
    nc = lw.nowcast
    src = ""
    if nc is not None and nc.has_representative:
        pl = "s" if len(nc.representative) > 1 else ""
        src = f" ; balise{pl} de l'atterro prise{pl} en compte (poids {nc.weight * 100:.0f} %)"
        if nc.trend is not None and nc.trend.v_ext is not None:
            src += f", tendance extrapolée ({nc.trend.v_ext:.0f} km/h, raf. {nc.trend.g_ext:.0f})"
    out.append(
        Finding("LANDING_WIND", "Vent à l'atterrissage",
                f"Vent à {landing.name} vers {fmt_hm(end)} : {dir_label(lw.direction_deg)} {lw.speed_kmh:.0f} "
                f"km/h{breeze_txt}{src}.",
                criterion="landing", value=lw.speed_kmh, limits=dict(lw_lim), band=not breeze, band_start=band_start)
    )  # fmt: skip
    out.append(
        Finding("LANDING_WIND", "Rafales à l'atterrissage", f"Rafales {lw.gust_kmh:.0f} km/h à "
                                                            f"{landing.name}{breeze_txt}.",
                criterion="landing", value=lw.gust_kmh, limits=dict(lg_lim), band=not breeze, band_start=band_start)
    )  # fmt: skip
    if lw.speed_kmh > rules.LANDING_WIND_ABS_MAX_KMH or lw.gust_kmh > rules.LANDING_GUST_ABS_MAX_KMH:
        out.append(
            Finding(
                "LANDING_WIND",
                "Vent à l'atterrissage hors limites",
                f"{lw.speed_kmh:.0f} km/h, rafales {lw.gust_kmh:.0f} à {landing.name} : no-go.",
                absolute_nogo=True,
            )
        )
    if breeze:
        # VALLEY_BREEZE : info sous 80 % du seuil, caution entre 80 et 100 % (le no-go reste LANDING_WIND)
        ratios = {lv: min(1.0, max(lw.speed_kmh / lw_lim[lv], lw.gust_kmh / lg_lim[lv])) for lv in LEVELS}
        if abs(lw.speed_kmh - lw.model_speed_kmh) >= 1.0 or abs(lw.gust_kmh - lw.model_gust_kmh) >= 1.0:
            txt = (f"modèle × {lw.breeze_factor:.2f} = {lw.model_speed_kmh:.0f} km/h (rafales "
                   f"{lw.model_gust_kmh:.0f}), "
                   f"vent retenu avec la balise de l'atterro : {lw.speed_kmh:.0f} km/h, rafales {lw.gust_kmh:.0f}")
        else:
            txt = f"{lw.speed_kmh:.0f} km/h, rafales {lw.gust_kmh:.0f} (×{lw.breeze_factor:.2f} sur le modèle)"
        out.append(
            Finding("VALLEY_BREEZE", "Brise de vallée à l'atterrissage",
                    f"Brise de vallée attendue à {landing.name} vers {fmt_hm(end)} : {txt}. Approche face à la brise.",
                    ratios=ratios, info=True, band=True, band_start=band_start)
        )  # fmt: skip
    return out


def regional_wind_findings(site: Site, landing_hour: HourAnalysis) -> list[Finding]:
    out: list[Finding] = []
    v, d = landing_hour.wind_speed_kmh, landing_hour.wind_direction_deg
    for region, sector, name in (
        ("bise", rules.BISE_SECTOR_DEG, "Bise"),
        ("mistral", rules.MISTRAL_SECTOR_DEG, "Mistral"),
    ):
        if _in_region(site.lat, site.lon, region) and _in_sector(d, sector):
            if v >= rules.NOGO["regional_wind_ground_kmh"]:
                out.append(Finding("REGIONAL_WIND", f"{name} forte", f"{name} {v:.0f} km/h en vallée : no-go dans la "
                                                                     f"zone d'influence.",
                                   absolute_nogo=True))  # fmt: skip
            elif v >= rules.REGIONAL_WIND_CAUTION_KMH:
                out.append(
                    Finding("REGIONAL_WIND", f"{name} sensible", f"{name} {v:.0f} km/h en vallée.", caution=True)
                )
    return out


def landing_nowcast_findings(ctx: DataContext, lw: LandingWind, landing: Site, end: datetime) -> list[Finding]:
    """Balises de l'atterro à l'heure d'arrivée (§12.1-12.4) : tendance, désaccord, absence de balise."""
    out: list[Finding] = []
    nc = lw.nowcast
    out += trend_findings(nc, ctx.horizon, lw.speed_kmh)
    if nc is not None and nc.has_representative and nc.mismatch:
        out.append(Finding("BEACON_MISMATCH", "Balises en désaccord avec la prévision",
                           "À l'atterro, la balise contredit le modèle : " + " ; ".join(nc.details[:2])
                           + f". Vent retenu à l'arrivée : {lw.speed_kmh:.0f} km/h (modèle seul : "
                             f"{lw.model_speed_kmh:.0f}).",
                           caution=True))  # fmt: skip
    nb = no_landing_beacon_finding(ctx, nc, landing, end, lw.model_speed_kmh)
    if nb is not None:
        out.append(nb)
    return out


def cloud_precip_findings(
    tl: PointTimeline, ltl: PointTimeline, site: Site, landing: Site, start: datetime, end: datetime
) -> list[Finding]:
    out: list[Finding] = []
    a = tl.at(start)
    alt = site.elevation_m
    # pluie ±1 h au déco + à l'atterro à l'arrivée. Convention Open-Meteo (revue, m) : la valeur horodatée H est le
    # cumul de l'heure PRÉCÉDENTE (H − 1 → H) ; [déco − 1 h, déco + 1 h] = valeurs horodatées déco et déco + 1 h
    win = tl.between(start, start + timedelta(hours=1))
    pmax = max([h.precipitation_mm_h for h in win] + [ltl.at(end).precipitation_mm_h])
    if pmax >= rules.NOGO["precip_mm_h"]:
        out.append(
            Finding("RAIN", "Pluie", f"Précipitations prévues ({pmax:.1f} mm/h) sur le créneau.", absolute_nogo=True)
        )
    elif pmax >= rules.PRECIP_CAUTION_MM_H:
        out.append(
            Finding("RAIN", "Averses possibles", f"Faibles précipitations possibles ({pmax:.2f} mm/h).", caution=True)
        )
    # 3 h avant le déco = valeurs horodatées déco − 2 h, déco − 1 h et déco (cumuls de l'heure précédente)
    prev = [h for h in tl.hours if start - timedelta(hours=2) <= h.time <= start]
    prev_sum = sum(h.precipitation_mm_h for h in prev)
    if prev_sum >= rules.NOGO["precip_prev_3h_mm"]:
        out.append(Finding("RAIN", "Pluie dans les 3 h précédentes",
                           f"{prev_sum:.1f} mm de pluie dans les 3 h avant le déco : aile mouillée (risque de "
                           f"parachutale), sol froid.",
                           absolute_nogo=True))  # fmt: skip
    # base des nuages / brouillard au déco
    base = a.cloud_base_m
    if base is not None and base < alt + rules.NOGO["cloud_base_min_above_takeoff_m"]:
        out.append(Finding("LOW_CLOUD_BASE", "Base des nuages au déco", f"Base des cumulus vers {base:.0f} m : déco "
                                                                        f"dans ou sous le nuage.",
                           absolute_nogo=True))  # fmt: skip
    elif base is not None and base < alt + rules.CLOUD_BASE_CAUTION_ABOVE_TAKEOFF_M:
        out.append(Finding("LOW_CLOUD_BASE", "Base basse", f"Base des cumulus vers {base:.0f} m : peu de marge "
                                                           f"au-dessus du déco.",
                           caution=True))  # fmt: skip
    if (
        a.cloud_cover_low_pct >= rules.LOW_CLOUD_NOGO_PCT
        and (base is None or base < alt + rules.LOW_CLOUD_NOGO_ABOVE_TAKEOFF_M)
        and a.temperature_c - a.dew_point_c < 4
    ):
        out.append(Finding("LOW_CLOUD_BASE", "Nuages bas", f"Couverture nuageuse basse {a.cloud_cover_low_pct:.0f} % "
                                                           f"au niveau du déco.",
                           absolute_nogo=True))  # fmt: skip
    if a.temperature_c - a.dew_point_c < rules.SPREAD_T_TD_NOGO_C:
        out.append(Finding("LOW_CLOUD_BASE", "Brouillard au déco", f"T − Td = {a.temperature_c - a.dew_point_c:.1f} °C "
                                                                   f"au déco : brouillard / nuage.",
                           absolute_nogo=True))  # fmt: skip
    la = ltl.at(end)
    if (
        la.temperature_c - la.dew_point_c < rules.SPREAD_T_TD_NOGO_C
        and la.cloud_cover_low_pct >= rules.LOW_CLOUD_NOGO_PCT
    ):
        out.append(Finding("LOW_CLOUD_BASE", "Stratus / brouillard sur l'atterro",
                           f"Atterro {landing.name} dans le stratus (T − Td = {la.temperature_c - la.dew_point_c:.1f} "
                           f"°C, nuages bas {la.cloud_cover_low_pct:.0f} %).",
                           absolute_nogo=True))  # fmt: skip
    # front (§3 #13, revue 7.17) : pression réduite au niveau de la mer en baisse ≥ 3 hPa en 3 h, sur [déco − 3 h,
    # atterrissage]
    drop, at = pressure_drop(tl, start - timedelta(hours=3), end)
    if drop is not None and drop >= rules.NOGO["pressure_drop_hpa_3h"]:
        out.append(Finding("FRONT", "Pression en baisse rapide",
                           f"La pression baisse de {drop:.1f} hPa en 3 h vers {fmt_hm(at)} : arrivée d'une "
                           f"perturbation (dégradation rapide, vent qui forcit).", absolute_nogo=True))  # fmt: skip
    if a.cloud_cover_midhigh_pct >= rules.MIDHIGH_CLOUD_CAUTION_PCT and a.cloud_cover_pct >= 80:
        out.append(Finding("FRONT", "Voile nuageux épais", "Couverture moyenne/haute ≥ 80 % : thermiques coupés, "
                                                           "dégradation possible.",
                           caution=True))  # fmt: skip
    return out


def rotor_finding(ctx: DataContext, point: Site, what: str, crest: tuple[float, float]) -> Finding | None:
    """§4.5 (revue 7.17) : `point` (atterro) dans la zone de rotor d'un relief au vent : vent à la crête ≥ 15 km/h,
    relief de hauteur h au-dessus du point à moins de 5 h (15-25 km/h) ou 10 h (> 25 km/h) en amont. MNT réel
    seulement (sinon la règle est listée « non vérifiée »)."""
    from app.geo import destination

    v, d = crest
    if v < rules.ROTOR_MIN_CREST_WIND_KMH or ctx.terrain is None or not ctx.terrain_is_real:
        return None
    factor = rules.ROTOR_LEE_FACTOR["strong" if v > rules.ROTOR_STRONG_WIND_KMH else "moderate"]
    n = int(rules.ROTOR_SEARCH_KM / rules.ROTOR_STEP_KM)
    for i in range(1, n + 1):
        x = i * rules.ROTOR_STEP_KM
        la, lo = destination(point.lat, point.lon, d, x)
        z = ctx.terrain_at(la, lo)
        if z is None:
            continue
        h = z - point.elevation_m
        if h >= rules.ROTOR_MIN_RELIEF_M and x * 1000.0 <= factor * h:
            km = f"{x:.1f}".replace(".", ",")
            return Finding("ROTOR", "Rotor sous le vent",
                           f"{what} {point.name} sous le vent d'un relief de {h:.0f} m à {km} km au {dir_label(d)} "
                           f"(vent de {v:.0f} km/h à la crête) : zone de rotor ({factor} × la hauteur du relief).",
                           absolute_nogo=True)  # fmt: skip
    return None


def route_relief_max(ctx: DataContext, route: Route) -> float | None:
    """Relief le plus haut sous la route (MNT réel, tous les 500 m) ; None sans MNT réel."""
    if ctx.terrain is None or not ctx.terrain_is_real:
        return None
    best: float | None = None
    for a, b in pairwise(route.coords):
        seg = haversine_km(a[1], a[0], b[1], b[0])
        n = max(1, int(seg / rules.GLIDE_CHECK_STEP_KM))
        for i in range(n + 1):
            f = i / n
            z = ctx.terrain_at(a[1] + f * (b[1] - a[1]), a[0] + f * (b[0] - a[0]))
            if z is not None and (best is None or z > best):
                best = z
    return best


def pressure_drop(tl: PointTimeline, t0: datetime, t1: datetime) -> tuple[float | None, datetime | None]:
    """Plus forte baisse de pression (hPa) sur 3 h dont le début tombe dans [t0, t1] ; (None, None) sans donnée."""
    by_t = {h.time: h.pressure_msl_hpa for h in tl.hours if h.pressure_msl_hpa is not None}
    best: tuple[float, datetime] | None = None
    for t, p in by_t.items():
        if not (t0 <= t <= t1):
            continue
        p3 = by_t.get(t + timedelta(hours=3))
        if p3 is None:
            continue
        if best is None or p - p3 > best[0]:
            best = (p - p3, t + timedelta(hours=3))
    return (None, None) if best is None else best


def convective_findings(
    tl: PointTimeline, cw: ConvectionWindow, start: datetime, end: datetime, level_variant: str
) -> tuple[list[Finding], float]:
    """(constats, sous-score convective_stability)."""
    out: list[Finding] = []
    sub = 100.0
    storm_hours = tl.between(start, end + timedelta(hours=rules.THUNDERSTORM_CHECK_AFTER_LANDING_H))
    cs = rules.NOGO["cape_storm"]
    for h in storm_hours:
        li = h.lifted_index if h.lifted_index is not None else 5.0
        if (h.cape_j_kg >= cs["cape"] and li <= cs["li"]) or h.cape_j_kg >= rules.NOGO["cape_absolute"]:
            out.append(Finding("THUNDERSTORM", "Risque d'orage",
                               f"CAPE {h.cape_j_kg:.0f} J/kg et LI {li:.0f} vers {fmt_hm(h.time)} : risque d'orage "
                               f"pendant ou juste après le vol.",
                               absolute_nogo=True))  # fmt: skip
            sub = 0.0
            break
    else:
        for h in storm_hours:
            li = h.lifted_index if h.lifted_index is not None else 5.0
            if h.cape_j_kg >= rules.CAPE_CAUTION["cape"] and li <= rules.CAPE_CAUTION["li"]:
                out.append(Finding("THUNDERSTORM", "Instabilité modérée", f"CAPE {h.cape_j_kg:.0f} J/kg, LI {li:.0f} : "
                                                                          f"averses possibles en fin de créneau.",
                                   caution=True))  # fmt: skip
                sub = min(sub, 40.0)
                break
    conv_hours = tl.between(start, end + timedelta(hours=rules.CONVECTIVE_PRECIP_CHECK_AFTER_LANDING_H))
    for h in conv_hours:
        if (
            h.time > end
            and h.precipitation_mm_h >= rules.NOGO["precip_mm_h"]
            and h.cape_j_kg >= rules.CAPE_CAUTION["cape"]
        ):
            out.append(Finding("THUNDERSTORM", "Averses orageuses après le vol",
                               f"Précipitations convectives ({h.precipitation_mm_h:.1f} mm/h) vers {fmt_hm(h.time)}, "
                               f"moins de 2 h après l'atterrissage.",
                               absolute_nogo=True))  # fmt: skip
            sub = 0.0
            break
    # surdéveloppement (§4.6 + lot 2.6)
    od = cw.overdevelopment_time
    if cw.overdevelopment_risk == "high":
        if od is not None and end > od:
            out.append(
                Finding(
                    "OVERDEVELOPMENT",
                    "Vol après l'heure de surdéveloppement",
                    f"Surdéveloppement attendu vers {fmt_hm(od)} : le vol se termine trop tard.",
                    absolute_nogo=True,
                )
            )
            sub = 0.0
        elif od is not None and end > od - timedelta(hours=rules.OVERDEV_MODERATE_END_BEFORE_H):
            # jamais moins strict que « moderate » (revue 7.2) : posé au plus tard 1 h avant le surdéveloppement
            out.append(
                Finding(
                    "OVERDEVELOPMENT",
                    "Plus de créneau avant le surdéveloppement",
                    f"Surdéveloppement attendu vers {fmt_hm(od)} : plus de créneau (il fallait être posé avant "
                    f"{fmt_hm(od - timedelta(hours=rules.OVERDEV_MODERATE_END_BEFORE_H))}).",
                    absolute_nogo=True,
                )
            )
            sub = 0.0
        else:
            out.append(Finding("OVERDEVELOPMENT", "Journée à surdéveloppement",
                               f"Risque de surdéveloppement élevé{(' vers ' + fmt_hm(od)) if od else ''} : vols du "
                               f"matin courts uniquement.",
                               caution=True))  # fmt: skip
            sub = min(sub, 35.0)
    elif cw.overdevelopment_risk == "moderate":
        limit = od - timedelta(hours=rules.OVERDEV_MODERATE_END_BEFORE_H) if od is not None else None
        if od is not None and limit is not None and (od <= start or end > limit):
            # revue 7.2 : vol à l'heure du surdéveloppement, après, ou posé moins d'1 h avant : plus de créneau
            out.append(
                Finding(
                    "OVERDEVELOPMENT",
                    "Plus de créneau avant le surdéveloppement",
                    f"Surdéveloppement possible vers {fmt_hm(od)} : plus de créneau (il fallait être posé avant "
                    f"{fmt_hm(limit)}).",
                    absolute_nogo=True,
                )
            )
            sub = 0.0
        elif od is not None and start <= od <= end + timedelta(hours=rules.OVERDEV_MODERATE_WINDOW_AFTER_LANDING_H):
            out.append(
                Finding(
                    "OVERDEVELOPMENT",
                    "Surdéveloppement possible",
                    f"Surdéveloppement possible vers {fmt_hm(od)} : être posé au plus tard 1 h avant.",
                    caution=True,
                )
            )
            sub = min(sub, 50.0)
        else:
            sub = min(sub, 75.0)
    else:
        a = tl.at(start)
        sub = min(sub, linear(a.cape_j_kg, 100, 100, rules.CAPE_CAUTION["cape"], 70))
    return out, sub


# =============================================================================================
# Évaluation d'une variante à un instant de décollage
# =============================================================================================
@dataclass
class TakeoffData:
    site: Site
    tl: PointTimeline
    landing: Site
    ltl: PointTimeline
    alternates: list[Site]
    landings_pool: list[Site]
    big_valley: bool
    top_landing: bool
    cw: ConvectionWindow
    sunrise: datetime | None
    sunset: datetime | None
    site_findings: list[Finding]
    free: TakeoffTerrain | None = None
    sel: LandingSelection | None = None
    day_ceiling: float | None = None  # plafond utile max de la journée (fenêtre de convection), revue 7.21


def _landing_caps(td: TakeoffData, start: datetime, thermal: bool) -> tuple[datetime, str]:
    caps: list[tuple[datetime, str]] = []
    if td.sunset:
        caps.append((td.sunset, "coucher du soleil"))
    if thermal:
        if td.cw.end is not None:
            caps.append(
                (td.cw.end + timedelta(minutes=rules.XC_LANDING_AFTER_CONVECTION_END_MIN), "fin des thermiques")
            )
        if td.sunset:
            caps.append((td.sunset - timedelta(minutes=rules.LANDING_BEFORE_SUNSET_MIN), "30 min avant le coucher du "
                                                                                         "soleil"))
    od = td.cw.overdevelopment_time
    if od is not None and td.cw.overdevelopment_risk != "low":
        caps.append((od - timedelta(hours=rules.OVERDEV_MODERATE_END_BEFORE_H), "surdéveloppement attendu 1 h plus "
                                                                                "tard"))
    a = td.tl.at(start)
    li = a.lifted_index if a.lifted_index is not None else 5.0
    if (
        thermal
        and a.cape_j_kg >= rules.CAPE_CAUTION["cape"]
        and li <= rules.CAPE_CAUTION["li"]
        and td.cw.overdevelopment_risk == "low"
    ):
        # repli : fin de créneau avancée à 14h solaire
        dh = rules.CAPE_CAUTION_WINDOW_END_SOLAR_H - solar_hour(start, td.site.lon)
        caps.append((start + timedelta(hours=dh), "instabilité : fin avancée à 14h solaire"))
    if not caps:
        return start + timedelta(hours=12), "fin de journée"
    return min(caps, key=lambda c: c[0])


def evaluate_variant(
    ctx: DataContext,
    td: TakeoffData,
    variant: str,
    start: datetime,
    filters: PlanFilters,
    proj: Projector,
    usable_cap: float | None = None,
) -> Candidate | str:
    """Renvoie un Candidate (évalué pour tous les niveaux) ou une raison d'infaisabilité « [CODE] … ».
    `usable_cap` : plafond imposé par un espace aérien au-dessus de la route (second passage, route reconstruite
    sous ce plafond)."""
    site, landing = td.site, td.landing
    level = filters.difficulty
    wing = filters.wing_glide_ratio
    tw = takeoff_wind(ctx, site, td.tl, start)
    a = tw.hour
    alt = site.elevation_m
    usable = _usable_capped(a)
    if usable_cap is not None:
        usable = min(usable, usable_cap)
    vario = a.thermal_strength_ms
    sh = solar_hour(start, site.lon)
    # jour aéronautique
    if td.sunrise and start < td.sunrise:
        return _codes_prefix("SUNSET", f"Décollage avant le lever du soleil ({fmt_hm(td.sunrise)}).")
    if td.sunset and start >= td.sunset:
        return _codes_prefix("SUNSET", f"Décollage après le coucher du soleil ({fmt_hm(td.sunset)}) : le vol libre se "
                                       f"pratique de jour.")
    thermal_variant = variant in ("local_thermal", "xc")
    cap, cap_reason = _landing_caps(td, start, thermal_variant)
    avail_min = (cap - start).total_seconds() / 60.0
    drop = alt - landing.elevation_m
    plouf_min = max(0.0, drop) / (rules.SINK_RATE_MS["calm"] * 60.0) + rules.PLOUF_EXTRA_MIN
    # §14 : vent RENCONTRÉ sur chaque plané (vent retenu au déco à l'heure de départ, vent retenu à l'atterro à l'heure
    # d'arrivée, profil du déco au-dessus de son altitude), crédit du vent arrière selon la fiabilité
    field = GlideField(ctx, site, td.tl, start, tw=tw, main_landing=landing, main_ltl=td.ltl,
                       main_big_valley=td.big_valley)  # fmt: skip
    duration_note: str | None = None
    feas: list[Finding] = []
    max_alt = alt
    route: Route
    thermal_usage = "none"

    if variant in ("plouf", "restitution"):
        if td.top_landing and not td.landings_pool:
            return "Pas d'atterrissage en contrebas pour un plouf"
        dur = plouf_min
        if variant == "restitution":
            if not td.sunset or not (
                td.sunset - timedelta(hours=rules.RESTITUTION_BEFORE_SUNSET_H) <= start < td.sunset
            ):
                return "Hors créneau de restitution"
            if not any(o in rules.RESTITUTION_FACES for o in site.orientations):
                return "Face non orientée pour la restitution"
            dur = max(0.0, drop) / (rules.SINK_RATE_MS["evening"] * 60.0) * rules.RESTITUTION_DURATION_FACTOR / 1.0
            # vol du soir : posé avant le coucher ; entre coucher − 30 min et coucher, SUNSET caution (§3 #11)
            dur = min(dur, (td.sunset - start).total_seconds() / 60.0 - 5)
            thermal_usage = "optional"
        if dur > filters.duration_max_minutes + 0.5:
            return _codes_prefix("WEAK_THERMALS", f"La descente seule dure ~{dur:.0f} min, plus que la durée max "
                                                  f"demandée.")
        if dur < filters.duration_min_minutes:
            # revue 7.7 : la durée d'un plouf vient du dénivelé (pas du coucher du soleil)
            why = f"dénivelé de {max(0.0, drop):.0f} m" + (", pas de thermique exploitable" if vario <
                                                            rules.THERMAL_USABLE_MIN_MS else "")  # fmt: skip
            duration_note = (f"Seul un plouf d'environ {dur:.0f} min est possible ({why}) : plus court que les "
                             f"{filters.duration_min_minutes:.0f} min demandées.")  # fmt: skip
        lw_arr = field.landing_wind(landing, start + timedelta(minutes=dur))  # ZPA au vent de l'atterro (§14.4)
        route = build_plouf(ctx, site, landing, td.alternates, level, wing, field,
                            (lw_arr.speed_kmh, lw_arr.direction_deg), dur, proj=proj, t_start=start)  # fmt: skip
        if variant == "restitution":
            route.kind = "plouf"
    elif variant == "ridge":
        ang = tw.angle
        if ang.category == "tail" or ang.calm:
            return _codes_prefix("WEAK_THERMALS", "Pas de vent de face suffisant pour le soaring.")
        # persistance du vent de soaring
        persist = 0.0
        t = start
        while t < cap and persist < 600:
            twx = takeoff_wind(ctx, site, td.tl, t)
            if (
                not (rules.RIDGE_MIN_KMH_BY_LEVEL[level] <= twx.speed_kmh <= rules.RIDGE["max_kmh"][level] * 1.05)
                or twx.angle.category == "tail"
            ):
                break
            persist += 60.0
            t += timedelta(hours=1)
        persist = max(persist, 30.0 if rules.RIDGE_MIN_KMH_BY_LEVEL[level] <= tw.speed_kmh else 0.0)
        dur = min(filters.duration_max_minutes, persist, rules.RIDGE_MAX_DURATION_MIN[level], avail_min)
        feas.append(Finding("WEAK_THERMALS", "Vent de soaring", f"Vent de face {tw.speed_kmh:.0f} km/h pour tenir en "
                                                                f"dynamique.",
                            value=tw.speed_kmh, limits={lv: float(rules.RIDGE_MIN_KMH_BY_LEVEL[lv]) for lv in LEVELS},
                            kind="min", feasibility=True, band=False, blocks_go=False))  # fmt: skip
        if dur < 15:
            return _codes_prefix("WEAK_THERMALS", "Vent de soaring trop peu durable.")
        if dur < filters.duration_min_minutes:
            duration_note = f"Le vent de soaring ne tient que ~{dur:.0f} min : plus court que demandé."
        route = build_ridge(
            ctx, site, landing, td.alternates, level, wing, field, tw.direction_deg, dur, td.top_landing
        )
        max_alt = route.max_altitude_m
    elif variant == "local_thermal":
        if vario < rules.THERMAL_USABLE_MIN_MS:
            return _codes_prefix("WEAK_THERMALS", f"Thermiques non exploitables à {fmt_hm(start)} ({vario:.1f} m/s).")
        if usable <= alt:  # revue 7.15 : message clair (pas de « plafond utile −188 m »)
            return _codes_prefix("ALTITUDE_LIMIT", f"Plafond limité par le FL115 (≈ {usable:.0f} m avec la marge) sous "
                                                   f"l'altitude du déco ({alt:.0f} m) : pas de vol thermique.")
        feas.append(
            Finding(
                "WEAK_THERMALS",
                "Plafond utile",
                f"Plafond utile {usable:.0f} m ({usable - alt:.0f} m au-dessus du déco).",
                value=usable - alt,
                limits={lv: float(x) for lv, x in rules.LOCAL_CEILING_MIN_ABOVE_TAKEOFF_M.items()},
                kind="min",
                feasibility=True,
                band=False,
                blocks_go=False,
            )
        )
        if level == "beginner" and td.cw.start is not None and start > td.cw.start + timedelta(
            hours=rules.BEGINNER_THERMAL_OFFPEAK_AFTER_START_H
        ):  # §2.1 / lot 1.12 / revue 7.10 : élève en thermique hors pic seulement
            lim = td.cw.start + timedelta(hours=rules.BEGINNER_THERMAL_OFFPEAK_AFTER_START_H)
            return _codes_prefix("STRONG_THERMALS", f"Élève : en thermique, décollage avant {fmt_hm(lim)} (début des "
                                                    f"thermiques + 1 h, hors pic) ou en restitution du soir.")
        # durée : la plus petite des limites, avec sa cause (revue 7.7)
        limits = [(filters.duration_max_minutes, "durée max demandée"), (avail_min, cap_reason)]
        if level == "beginner":  # avant la durée max du niveau : même valeur, cause plus parlante
            limits.append((rules.LOCAL_THERMAL_BEGINNER_MAX_MIN, "limite élève 45 min"))
        limits.append((float(rules.MAX_DURATION_MIN[level]), "durée max de ton niveau"))
        if td.cw.overdevelopment_risk == "high":
            limits.append((rules.OVERDEV_HIGH_MAX_DURATION_MIN, "journée à surdéveloppement : 1h30 au plus"))
        realism_cap = None
        for vmax, cap_min in rules.LOCAL_THERMAL_DURATION_CAPS:
            if vario < vmax:
                realism_cap = cap_min
                break
        if usable - alt < rules.LOCAL_THERMAL_LOW_CEILING_M:
            realism_cap = min(realism_cap or 1e9, rules.LOCAL_THERMAL_LOW_CEILING_MAX_MIN)
        if realism_cap is not None:
            limits.append((realism_cap, f"thermiques {vario:.1f} m/s, plafond utile {usable - alt:.0f} m au-dessus "
                                        f"du déco"))  # fmt: skip
        max_d, dur_reason = min(limits, key=lambda x: x[0])
        if max_d < plouf_min + 10:
            return _codes_prefix("WEAK_THERMALS", f"Fenêtre thermique trop courte après {fmt_hm(start)} "
                                                  f"({dur_reason}).")
        dur = max_d
        if dur < filters.duration_min_minutes:
            duration_note = f"Vol limité à ~{dur:.0f} min ({dur_reason}) : plus court que demandé."
        max_alt = usable
        thermal_usage = "essential" if dur > plouf_min * 1.5 else "optional"
        layer = a.profile.mean_wind(alt, max(alt + 200, usable))
        route = build_local_thermal(
            ctx, proj, site, landing, td.alternates, level, wing, field, layer, start, dur, usable, max_alt,
            vario=vario,
        )
    elif variant == "xc":
        if vario < rules.THERMAL_USABLE_MIN_MS:
            return _codes_prefix("WEAK_THERMALS", f"Thermiques insuffisants pour un cross à {fmt_hm(start)}.")
        xc_vario = rules.XC_MIN_VARIO_MS[level]
        if xc_vario is not None and vario < xc_vario:
            v_txt, req_txt = f"{vario:.1f}".replace(".", ","), f"{xc_vario:.1f}".replace(".", ",")
            return _codes_prefix("WEAK_THERMALS", f"Thermiques trop faibles pour un cross ({v_txt} m/s ; {req_txt} "
                                                  f"requis).")
        xc_min = rules.XC_CEILING_MIN_ABOVE_TAKEOFF_M
        feas.append(
            Finding(
                "WEAK_THERMALS",
                "Plafond pour le cross",
                f"Plafond utile {usable - alt:.0f} m au-dessus du déco.",
                value=usable - alt,
                limits={lv: (None if x is None else float(x)) for lv, x in xc_min.items()},
                kind="min",
                feasibility=True,
                band=False,
                blocks_go=False,
            )
        )
        if usable <= alt:
            return _codes_prefix("ALTITUDE_LIMIT", f"Plafond limité par le FL115 (≈ {usable:.0f} m avec la marge) sous "
                                                   f"l'altitude du déco ({alt:.0f} m) : pas de vol thermique.")
        if xc_min[level] is None or usable - alt < xc_min[level]:
            return _codes_prefix("WEAK_THERMALS", f"Plafond utile trop bas pour un cross ({usable - alt:.0f} m "
                                                  f"au-dessus du déco).")
        budget = min(filters.duration_max_minutes, avail_min, float(rules.MAX_DURATION_MIN[level]))
        if td.cw.overdevelopment_risk == "high":
            if level != "expert":
                return _codes_prefix("OVERDEVELOPMENT", "Journée à surdéveloppement : pas de cross (sauf expert, "
                                                        "retour avant 13h solaire).")
            back = start + timedelta(hours=rules.OVERDEV_HIGH_EXPERT_RETURN_SOLAR_H - sh)
            budget = min(budget, (back - start).total_seconds() / 60.0, rules.OVERDEV_HIGH_MAX_DURATION_MIN)
        if budget < rules.XC_MIN_DURATION_MIN:
            return _codes_prefix("WEAK_THERMALS", f"Fenêtre trop courte pour un cross ({budget:.0f} min, "
                                                  f"{cap_reason}).")
        layer = a.profile.mean_wind(alt, usable)
        xc, why = build_cross(
            ctx, proj, site, landing, td.landings_pool, level, wing, layer, start, budget, usable, usable, vario,
            glide_wind=field,
        )
        if xc is None:
            return why or "Cross impossible"
        route = xc.route
        relief = route_relief_max(ctx, route)
        need = rules.XC_CEILING_MIN_ABOVE_RELIEF_M[level]
        if relief is not None and need is not None and usable < relief + need:  # §2.1 (revue 7.17)
            return _codes_prefix("WEAK_THERMALS", f"Plafond utile {usable:.0f} m : moins de {need} m au-dessus du "
                                                  f"relief le plus haut de la route du cross ({relief:.0f} m).")
        dur = xc.duration_min
        max_alt = usable
        thermal_usage = "essential"
        if xc.limited:
            duration_note = (
                f"Distance limitée par la couverture des atterrissages identifiés (cône de finesse) : "
                f"{route.distance_km:.0f} km au lieu de ~{xc.target_km:.0f} km possibles en {duration_label(budget)}."
            )
        elif dur < filters.duration_min_minutes:
            duration_note = f"Cross réaliste de ~{duration_label(dur)} : plus court que demandé."
    else:  # pragma: no cover
        return "variante inconnue"

    # revue 7.4 : la route contourne les zones où le vol libre est interdit (plané allongé d'autant)
    route = apply_detours(ctx, proj, route, site, landing)
    end = start + timedelta(minutes=dur)
    lw = field.landing_wind(landing, end)  # = landing_wind(td.ltl, end, td.big_valley, ctx, landing), mis en cache
    findings: list[Finding] = list(td.site_findings) + feas
    ridge = variant == "ridge"
    findings += takeoff_wind_findings(tw, site, ridge, sh)
    if free_takeoff.is_free_takeoff(site):  # §12.6 : seuils propres au décollage libre
        findings += free_takeoff.wind_findings(tw, td.free, site)
    # nowcasting (§12) : tendance des balises du déco (début du créneau)
    findings += trend_findings(tw.nowcast, ctx.horizon, tw.speed_kmh, ridge)
    top = (max_alt + rules.ALOFT_CHECK_ABOVE_CEILING_M) if thermal_variant else alt + rules.CREST_CHECK_ABOVE_TAKEOFF_M
    findings += aloft_findings(a, site, top, ridge, usable, thermal_variant)
    findings += regional_wind_findings(site, td.ltl.at(start))
    findings += cloud_precip_findings(td.tl, td.ltl, site, landing, start, end)
    conv_f, conv_sub = convective_findings(td.tl, td.cw, start, end, variant)
    findings += conv_f
    # thermiques pendant le vol (seuil par niveau, s'applique à tous les vols : on est dans l'air)
    flight_hours = td.tl.between(start, end)
    vario_max = max(h.thermal_strength_ms for h in flight_hours)
    findings.append(
        Finding("STRONG_THERMALS", "Thermiques forts", f"Vario moyen jusqu'à {vario_max:.1f} m/s pendant le vol.",
                criterion=None, value=vario_max, limits={lv: float(x) for lv, x in rules.THERMAL_MAX_MS.items()})
    )  # fmt: skip
    if filters.thermals == "avoid" and vario_max > rules.AVOID_THERMAL_MAX_MS:
        return _codes_prefix("STRONG_THERMALS", f"Thermiques {vario_max:.1f} m/s pendant le créneau : incompatible "
                                                f"avec « sans thermiques ».")
    if filters.thermals == "required" and thermal_usage == "none":
        return _codes_prefix("WEAK_THERMALS", "Vol sans thermique alors que tu veux des thermiques.")
    if filters.thermals == "required" and vario < 1.0:
        findings.append(
            Finding("WEAK_THERMALS", "Thermiques faibles", "Thermiques faibles, vol local court probable.", info=True)
        )
    # froid / gel
    if thermal_variant and a.freezing_level_m is not None and a.freezing_level_m < max_alt:
        t_ceiling = a.profile.temperature(max_alt)
        findings.append(Finding("FREEZING", "Isotherme 0 °C sous le plafond",
                                f"Isotherme 0 °C vers {a.freezing_level_m:.0f} m, {t_ceiling:.0f} °C au plafond : "
                                f"onglée, givre sur les instruments.",
                                caution=True))  # fmt: skip
        findings.append(
            Finding(
                "FREEZING",
                "Froid au plafond",
                f"{t_ceiling:.0f} °C au plafond.",
                value=-t_ceiling,
                limits={
                    "beginner": -rules.COLD_AT_CEILING_BEGINNER_C,
                    "intermediate": 99.0,
                    "advanced": 99.0,
                    "expert": 99.0,
                },
                band=False,
            )
        )
    inv = _inversion(a, alt)
    if inv is not None:
        findings.append(Finding("INVERSION", "Inversion", f"Inversion vers {inv:.0f} m : thermiques bloqués en "
                                                          f"dessous, turbulence au passage.",
                                info=True))  # fmt: skip
    # atterrissage à l'heure d'arrivée (en top landing : même vent que le déco, déjà contrôlé — lot 6.8)
    top_ldg = ridge and td.top_landing
    if not top_ldg:
        findings += landing_findings(lw, landing, end, landing_band_start(ctx, lw.nowcast))
        findings += landing_nowcast_findings(ctx, lw, landing, end)
        rot = rotor_finding(ctx, landing, "Atterro", (tw.crest_speed_kmh, tw.crest_direction_deg))
        if rot is not None:
            findings.append(rot)
    # finesse (par niveau) : vent rencontré, crédit et accélérateur du niveau (§14)
    glide_ratios: dict[str, float] = {}
    glide_by_level: dict[str, GlideCheck] = {}
    ref_by_level: dict[str, GlideCheck] = {}
    for lv in LEVELS:
        g, ref = _route_glide(ctx, td, route, lv, wing, field, start, dur, variant)
        glide_by_level[lv] = g
        ref_by_level[lv] = ref
        glide_ratios[lv] = g.ratio if not (top_ldg or (variant == "plouf" and td.top_landing)) else 0.0
    high_m: float | None = None
    if not top_ldg:
        g = glide_by_level[level]
        findings.append(Finding("GLIDE_MARGIN", "Marge de finesse", glide_margin_text(g, landing.name, level),
                                criterion="landing", ratios=glide_ratios, band_start=rules.GLIDE_CAUTION_RATIO,
                                curve=glide_subscore, level_titles={"danger": "Hors de portée"}))  # fmt: skip
        # §14.4 : arrivée haute avec du vent arrière, sur le plané direct déco → atterro principal (jamais bloquant)
        ref = ref_by_level[level]
        h = rules.HIGH_ARRIVAL
        if (ref.wind is not None and ref.expected_arrival_m is not None and ref.wind.along_kmh >= h["min_tail_kmh"]
                and ref.expected_arrival_m >= h["info_m"]):  # fmt: skip
            high_m = ref.expected_arrival_m
            side = dir_label(route.zpa_bearing) if route.zpa_bearing is not None else None
            zones = [z[0] for z in _landing_zones(ctx, proj, landing, route)]
            findings.append(Finding("HIGH_ARRIVAL", "Arrivée haute",
                                    high_arrival_detail(landing.name, high_m, ref, level, lw.direction_deg,
                                                        lw.speed_kmh, side, zones),
                                    level_risk=high_arrival_levels(high_m), blocks_go=False))  # fmt: skip
    # coucher du soleil
    if td.sunset:
        if end > td.sunset:
            findings.append(Finding("SUNSET", "Atterrissage après le coucher du soleil", f"Atterrissage estimé "
                f"{fmt_hm(end)}, coucher {fmt_hm(td.sunset)}.",
                                    absolute_nogo=True))  # fmt: skip
        elif end > td.sunset - timedelta(minutes=rules.LANDING_BEFORE_SUNSET_MIN):
            findings.append(Finding("SUNSET", "Atterrissage proche du coucher du soleil",
                                    f"Atterrissage estimé {fmt_hm(end)}, coucher du soleil {fmt_hm(td.sunset)} : pas "
                                    f"de marge.",
                                    caution=True))  # fmt: skip
    # espaces aériens + zones sensibles (route 3D)
    min_alt = min(landing.elevation_m, alt)
    flight_coords = route.coords
    asp = evaluate_airspaces(ctx, proj, flight_coords, min_alt, max_alt)
    if thermal_variant and usable_cap is None and asp.altitude_cap_m is not None and asp.altitude_cap_m < max_alt:
        # revue (TMA) : on reconstruit le vol thermique sous le plancher de l'espace (plafond − 100 m)
        return evaluate_variant(ctx, td, variant, start, filters, proj, usable_cap=asp.altitude_cap_m)
    if usable_cap is not None:
        findings.append(Finding("ALTITUDE_LIMIT", "Plafond limité par un espace aérien",
                                f"Altitude max limitée à {usable_cap:.0f} m (plancher d'un espace aérien interdit "
                                f"au-dessus de la route − 100 m) : rester dessous.", caution=True,
                                blocks_go=False))  # fmt: skip
    if asp.altitude_cap_m is not None and asp.altitude_cap_m < max_alt:
        max_alt = max(alt, asp.altitude_cap_m)
        findings.append(
            Finding(
                "ALTITUDE_LIMIT",
                "Plafond limité par un espace aérien",
                f"Altitude max limitée à {max_alt:.0f} m (plancher d'un espace aérien − 100 m).",
                caution=True,
                blocks_go=False,
            )
        )
        asp = evaluate_airspaces(ctx, proj, flight_coords, min_alt, max_alt)
    findings += asp.findings
    if thermal_variant and a.usable_ceiling_m > rules.FL115_M_STANDARD - rules.CEILING_MARGIN_BELOW_AIRSPACE_M:
        findings.append(Finding("ALTITUDE_LIMIT", "Plafond au-dessus du FL115",
                                f"Plafond utile ~{a.usable_ceiling_m:.0f} m : rester sous le FL115 (≈ "
                                f"{rules.FL115_M_STANDARD:.0f} m QNH 1013), altitude retenue {max_alt:.0f} m.",
                                caution=True, blocks_go=False))  # fmt: skip
    findings += evaluate_sensitive_route(
        ctx,
        proj,
        [(c[0], c[1], max_alt if i not in (0, len(flight_coords) - 1) else c[2]) for i, c in enumerate(flight_coords)],
        site,
        landing,
    )

    cand = Candidate(
        variant=variant,
        takeoff=site,
        landing=landing,
        alternates=td.alternates,
        start=start,
        duration_min=round(dur, 1),
        route=route,
        findings=findings,
        takeoff_wind=tw,
        landing_wind=lw,
        convection=td.cw,
        vario=vario,
        usable=usable,
        max_alt=max_alt,
        thermal_usage=thermal_usage,
        horizon=ctx.horizon,
        level=level,
        mock=ctx.mock,
        sunrise=td.sunrise,
        sunset=td.sunset,
        latest_landing=cap,
        landing_cap_reason=cap_reason,
        duration_note=duration_note,
        airspace=asp,
    )
    cand.airspaces = asp.warnings
    cand.glide_wind = field
    cand.ref_glide = ref_by_level[level] if not top_ldg else None
    cand.high_arrival_m = high_m
    cand.wing = wing
    cand.free_terrain = td.free
    cand.landing_sel = td.sel
    cand.policy = filters.landing_policy
    cand.score_items = [conv_sub]  # temporaire : sous-score convectif transmis à finalize()
    cand.zone_notes = _landing_zone_notes(ctx, proj, landing, route)
    cand.day_ceiling = td.day_ceiling
    route.glide = glide_by_level[level] if not top_ldg else route.glide
    return cand


LANDING_ZONE_NOTE_KM = 1.5


def _landing_zones(ctx: DataContext, proj: Projector, landing: Site, route: Route) -> list[tuple[str, float, bool]]:
    """Zones où le vol libre est interdit près de l'atterro (≤ 1,5 km) ou contournées par la route :
    (nom, distance à l'atterro en km, contournée)."""
    from app.engine.airspace import prohibited_areas

    out: list[tuple[str, float, bool]] = []
    p = proj.point(landing.lat, landing.lon)
    for a in prohibited_areas(ctx):
        d = proj.geom(a.geometry).distance(p)
        if d <= LANDING_ZONE_NOTE_KM or a.name in route.avoided_zones:
            out.append((a.name, d, a.name in route.avoided_zones))
    return out


def _landing_zone_notes(ctx: DataContext, proj: Projector, landing: Site, route: Route) -> list[str]:
    """Revue 7.4 : zone où le vol libre est interdit près de l'atterro ou contournée par la route → consigne du
    briefing (« PTU et approche hors de la zone « Réserve naturelle du Bout du Lac » »)."""
    return [f"PTU et approche hors de la zone « {name} » (vol libre interdit, à {d * 1000:.0f} m de l'atterro)"
            + (" : la route la contourne" if avoided else "")
            for name, d, avoided in _landing_zones(ctx, proj, landing, route)]  # fmt: skip


def glide_margin_text(g: GlideCheck, landing_name: str, level: str) -> str:
    """Détail du constat GLIDE_MARGIN (§14.7) : finesses requise / disponible, vent rencontré sur le plané (dans le dos,
    de face, de travers ; accélérateur), pénétration insuffisante, relief."""
    req, avail = f"{g.required_ratio:.1f}".replace(".", ","), f"{g.available_ratio:.1f}".replace(".", ",")
    txt = f"Finesse requise {req} vers {g.landing_name or landing_name} pour {avail} disponible"
    w = g.wind
    if w is not None:
        txt += f" ({f'{g.calm_ratio:.1f}'.replace('.', ',')} sans vent) : {wind_phrase(g, level)}"
        if not w.penetration_ok:
            txt += (f" ; pénétration insuffisante (vitesse sol {max(0.0, w.min_ground_kmh):.0f} km/h, minimum "
                    f"{w.penetration_min_kmh:.0f} à ton niveau)")  # fmt: skip
    if not g.terrain_ok:
        txt += " ; le relief coupe la ligne de plané"
    return txt + "."


def _direct_glide(
    ctx: DataContext, td: TakeoffData, route: Route, level: str, wing: float, field: GlideField, t0: datetime,
    ta: datetime,
) -> GlideCheck:
    """Plané direct déco → atterro principal (§14.1) : branches réelles (contournement des zones interdites), vent
    rencontré à l'heure de départ t0 / d'arrivée ta."""
    return glide_to(ctx, td.site.lat, td.site.lon, td.site.elevation_m, td.landing, level, wing, field,
                    pair=is_source_pair(td.site, td.landing), path=route.glide_path, t=t0, t_arrival=ta,
                    detour_zones=route.glide_zones or None)  # fmt: skip


def _route_glide(
    ctx: DataContext, td: TakeoffData, route: Route, level: str, wing: float, field: GlideField, start: datetime,
    dur: float, variant: str,
) -> tuple[GlideCheck, GlideCheck]:
    """(pire cas publié, plané direct de référence). Pire cas (lot 6.11) : (a) déco → atterro principal à l'altitude
    du déco (au départ ; pour un vol qui dure, aussi en fin de vol avec la brise de l'heure d'arrivée) ; (b) chaque
    point de route à son altitude de point bas → meilleur atterro identifié, à son heure de passage (§14.1)."""
    if td.landing.id == td.site.id:
        g = calm_glide(wing, level, td.landing.name)
        return g, g
    plouf = plouf_minutes(td.site.elevation_m - td.landing.elevation_m)
    end = start + timedelta(minutes=dur)
    single = variant == "plouf"
    g = _direct_glide(ctx, td, route, level, wing, field, start, end if single else start + timedelta(minutes=plouf))
    if not single and dur > plouf + 1.0:
        g_end = _direct_glide(ctx, td, route, level, wing, field, quarter(end - timedelta(minutes=plouf)), end)
        if g_end.ratio > g.ratio:
            g = g_end
    ref = g
    if route.kind == "xc":
        if route.glide.ratio > g.ratio:
            g = route.glide
        return g, ref
    if route.kind == "local_thermal":
        for w in route.waypoints:
            if w.type != "thermal_trigger":
                continue
            t = quarter(start + timedelta(minutes=w.eta_min or 0.0))
            best = None
            for ldg in [td.landing, *td.alternates]:
                gg = glide_to(ctx, w.lat, w.lon, max(td.site.elevation_m, w.altitude_m - 150.0), ldg, level, wing,
                              field, t=t)  # fmt: skip
                if best is None or gg.ratio < best.ratio:
                    best = gg
            if best is not None and best.ratio > g.ratio:
                g = best
    return g, ref


def _inversion(a: HourAnalysis, alt: float) -> float | None:
    pts = [p for p in a.profile.points if alt + 100 <= p.z <= 3500]
    for p, q in pairwise(pts):
        if q.t > p.t + 0.5:
            return p.z
    return None


# =============================================================================================
# Finalisation : niveau, score, verdict, risques
# =============================================================================================
def finalize(ctx: DataContext, cand: Candidate, filters: PlanFilters) -> Candidate:
    level = filters.difficulty
    findings = cand.findings
    # confiance
    t = cand.start
    tl = ctx.timelines[cand.takeoff.id]
    model_winds = (
        tl.model_winds.get(min(tl.model_winds, key=lambda x: abs((x - t).total_seconds()))) if tl.model_winds else []
    )
    nc = cand.takeoff_wind.nowcast
    rep_to = nc is not None and nc.has_representative
    coherent = None if not rep_to else (True if nc.coherent else (False if nc.mismatch else None))
    disp, beacon, sig_v, sig_d = confidence_factors(model_winds or [], coherent)
    single_model = tl.mode == "live" and bool(tl.model_winds) and not ctx.exact_inputs and len(model_winds or []) < 2
    if single_model:  # revue (m) : en bout d'échéance, un seul modèle couvre l'heure → pas de contrôle croisé
        disp *= rules.SINGLE_MODEL_CONFIDENCE_FACTOR
    top_ldg = cand.landing.id == cand.takeoff.id
    f_ldg = 1.0 if top_ldg else landing_confidence_factor(ctx, cand.landing_wind.nowcast)
    conf_raw = compute_confidence(ctx.horizon, disp, beacon, f_ldg)
    cand.conf_raw = conf_raw
    cand.confidence = min(conf_raw, rules.MOCK_CONFIDENCE_CAP) if ctx.mock else conf_raw
    base = rules.HORIZON_BASE_CONFIDENCE[ctx.horizon]
    if conf_raw < rules.VERDICT["go_min_confidence_ratio"] * base:
        why = (
            f"dispersion des modèles (σ vent {sig_v:.0f} km/h" + (f", σ direction {sig_d:.0f}°" if sig_d else "") + ")"
        )
        if beacon < 1:
            why += ", balises en désaccord"
        if f_ldg < 1:
            why += ", balise de l'atterro absente ou en désaccord"
        if single_model:
            why += ", un seul modèle disponible à cette heure"
        findings.append(
            Finding(
                "LOW_CONFIDENCE", "Prévision incertaine", f"Confiance {conf_raw * 100:.0f} % : {why}.", caution=True
            )
        )
    if rep_to and nc.mismatch:
        findings.append(Finding("BEACON_MISMATCH", "Balises en désaccord avec la prévision",
                                "Au déco, les balises contredisent le modèle : " + " ; ".join(nc.details[:2])
                                + ". On suit la balise pour les 2 prochaines heures.", caution=True))  # fmt: skip
    if ctx.horizon in rules.NOWCAST_HORIZONS:
        stale = _stale_attached(ctx, cand)
        if stale:
            findings.append(
                Finding(
                    "STALE_BEACONS",
                    "Balises anciennes",
                    "Mesure de plus de 30 min ignorée : " + ", ".join(stale[:3]) + ".",
                    info=True,
                )
            )
    # une source no-go (lot 4.3)
    sp = tl.spreads.get(min(tl.spreads, key=lambda x: abs((x - t).total_seconds()))) if tl.spreads else None
    if sp is not None and sp.n_models >= 2:
        a = cand.takeoff_wind.hour
        scale = cand.takeoff_wind.model_speed_kmh / a.wind_speed_kmh if a.wind_speed_kmh > 1 else 1.0
        msgs = []
        if sp.gust_max_kmh * scale > rules.TAKEOFF_GUST_MAX_KMH[level]:
            msgs.append(("TAKEOFF_GUSTS", f"au moins un modèle prévoit {sp.gust_max_kmh * scale:.0f} km/h de rafales "
                                          f"au déco"))
        if sp.precip_max_mm_h >= rules.NOGO["precip_mm_h"]:
            msgs.append(("RAIN", f"au moins un modèle prévoit {sp.precip_max_mm_h:.1f} mm/h de pluie"))
        if sp.cape_max_j_kg >= rules.NOGO["cape_storm"]["cape"] and (
            sp.li_min is None or sp.li_min <= rules.NOGO["cape_storm"]["li"]
        ):
            msgs.append(("THUNDERSTORM", f"au moins un modèle prévoit une CAPE de {sp.cape_max_j_kg:.0f} J/kg"))
        for code, m in msgs:
            findings.append(Finding(code, "Un modèle prévoit un no-go", m[0].upper() + m[1:] + ".", caution=True,
                                    blocks_go=conf_raw < rules.SINGLE_SOURCE_NOGO_CONFIDENCE))  # fmt: skip
    unchecked = rules.UNCHECKED_RULES_TEXT
    if ctx.terrain is None or not ctx.terrain_is_real:
        unchecked += " ; sans MNT réel : rotor sous le vent (§4.5) et relief de la route d'un cross (§2.1)"
    if not any(h.pressure_msl_hpa is not None for h in tl.hours):
        unchecked += " ; tendance de pression (§3 #13, donnée absente)"
    findings.append(Finding("UNCHECKED", "Règles non vérifiées par l'outil", unchecked + ".", info=True,
                            blocks_go=False))  # fmt: skip
    if ctx.airspace_unverified:
        findings.append(Finding("AIRSPACE", "Espaces aériens non vérifiés",
                                "Espaces aériens non vérifiés par l'outil (OpenAIP indisponible) : CTR, TMA et zones R "
                                "à contrôler sur la carte aéronautique avant de voler.", caution=True))  # fmt: skip
    if ctx.mock:
        findings.append(Finding("MOCK_DATA", "Données synthétiques", "Plan calculé sur des données SYNTHÉTIQUES (démo "
                                                                     "hors-ligne) : ne pas utiliser pour voler.",
                                caution=True, blocks_go=False))  # fmt: skip
    if ctx.horizon in ("15m", "30m", "1h") and cand.takeoff.access:
        findings.append(Finding("ACCESS_TIME", "Temps d'accès au déco", f"Vérifie que tu peux être au déco à temps : "
                                                                        f"{cand.takeoff.access}",
                                info=True, blocks_go=False))  # fmt: skip

    # difficulté du plan
    passing = smallest_passing_level(findings)
    type_min = rules.FLIGHT_TYPE_MIN_LEVEL[cand.flight_type]
    if cand.route.xc_subtype == "fai_triangle":
        type_min = max_level(type_min, rules.FLIGHT_TYPE_MIN_LEVEL["fai_triangle"])
    site_lvl = _site_level(cand.takeoff)
    absolute = [f for f in findings if f.absolute_nogo]
    reasons: list[str] = []
    if absolute:
        for f in absolute:
            reasons.append(_codes_prefix(f.code, f.detail))
    elif passing is None:
        for f in findings:
            if f.fails(level) and not f.feasibility:
                reasons.append(_codes_prefix(f.code, f.detail + " Hors limites pour tous les niveaux."))
    else:
        diff = max_level(site_lvl, passing, type_min)
        cand.difficulty = diff
        if rules.level_index(diff) > rules.level_index(level):
            fails = [f for f in findings if f.fails(level) and not f.feasibility]
            label = rules.LEVEL_LABEL_FR[diff]
            if fails:
                for f in fails:
                    reasons.append(_codes_prefix(f.code, f"{f.detail} Conditions trop fortes pour ton niveau (OK pour "
                                                         f"{label})."))
            elif rules.level_index(site_lvl) > rules.level_index(level):
                reasons.append(_codes_prefix("SITE_LEVEL", f"Site de niveau {label} : au-dessus de ton niveau."))
            else:
                reasons.append(_codes_prefix("SITE_LEVEL", f"Ce type de vol demande le niveau {label}."))
    # faisabilité au niveau du pilote
    for f in findings:
        if f.feasibility and f.fails(level):
            reasons.append(_codes_prefix(f.code, f"{f.detail} Insuffisant pour ce type de vol à ton niveau."))
    if reasons:
        cand.risks = _risks(findings, level)
        context = [
            _codes_prefix(r.code, r.detail)
            for r in cand.risks
            if r.level == "caution" and r.code not in NON_BLOCKING_CAUTIONS
        ]
        cand.reject_reasons = list(dict.fromkeys(reasons + context))
        cand.flyability = "no_go"
        return cand

    # score
    conv_sub = cand.score_items[0] if cand.score_items else 100.0
    sr, risks, v = _score_at(ctx, cand, filters, findings, level, conf_raw, conv_sub, site_lvl)
    if v == "no_go":
        weak = sr.weakest_safety
        what = CRITERION_LABEL_FR[weak].lower()
        g = cand.route.glide
        if weak == "landing" and g.required_ratio > 0:  # revue 7.18 : les chiffres de finesse
            what += f" (finesse requise {g.required_ratio:.1f} pour {g.available_ratio:.1f} disponible)"
        cand.reject_reasons = [
            _codes_prefix(CRITERION_RISK_CODE[weak], f"Score global insuffisant ({sr.score:.0f}/100) : point faible = "
                                                     f"{what}.")
        ]  # fmt: skip
        cand.flyability = "no_go"
        cand.risks = risks
        return cand
    if v == "marginal" and not any(r.level == "caution" and r.code not in NON_BLOCKING_CAUTIONS for r in risks):
        weak = min(rules.WEIGHTS, key=lambda c: sr.subscores.get(c, 100.0))
        risks.append(Risk(code=CRITERION_RISK_CODE[weak], level="caution", title=f"{CRITERION_LABEL_FR[weak]} limite",
                          detail=f"Critère « {CRITERION_LABEL_FR[weak]} » à {sr.subscores[weak]:.0f}/100 : conditions "
                                 f"moyennes."))  # fmt: skip
    # revue 7.10 : difficulté = plus petit niveau dont le VERDICT n'est pas no_go (score compris)
    lo = rules.level_index(cand.difficulty)
    for lv in LEVELS[lo : rules.level_index(level)]:
        if _score_at(ctx, cand, filters, findings, lv, conf_raw, conv_sub, site_lvl)[2] != "no_go":
            break
        cand.difficulty = LEVELS[min(rules.level_index(lv) + 1, rules.level_index(level))]
    cand.flyability = v
    cand.score = sr.score
    cand.raw_score = sr.raw_score
    cand.score_items = sr.items
    cand.risks = risks
    return cand


def _score_at(
    ctx: DataContext, cand: Candidate, filters: PlanFilters, findings: list[Finding], level: str, conf_raw: float,
    conv_sub: float, site_lvl: str,
):
    """(score, risques, verdict) du candidat jugé au niveau `level` (seuils, sous-scores et confiance)."""
    th_s, th_c = thermal_match_subscore(filters.thermals, cand.vario, cand.thermal_usage != "none", level)
    if (
        filters.thermals == "required"
        and cand.variant == "xc"
        and cand.vario > rules.THERMAL_MAX_MS[level] * rules.MARGINAL_BAND
    ):
        th_c += " (zone de vigilance de ton niveau)"
    du_s, du_c = duration_subscore(cand.duration_min, filters.duration_min_minutes, filters.duration_max_minutes)
    conf_s = linear(conf_raw, 0.3, 0.0, 0.9, 100.0)
    site_s = 100.0 if cand.takeoff.status == "open" else 60.0
    if rules.level_index(site_lvl) == rules.level_index(level):
        site_s = min(site_s, 85.0)
    asp_s = 100.0
    if cand.airspace and any(
        f.code in ("AIRSPACE", "AIRSPACE_ACTIVATION") and (f.caution or f.absolute_nogo) for f in cand.airspace.findings
    ):
        asp_s = 40.0
    extra: dict[str, tuple[float, str]] = {
        "thermal_match": (th_s, th_c),
        "duration_match": (du_s, du_c),
        "convective_stability": (conv_sub, "stabilité de la masse d'air / surdéveloppement"),
        "data_confidence": (conf_s, f"confiance {conf_raw * 100:.0f} %"),
        "site_fit": (site_s, "site adapté" if site_s >= 85 else "site au niveau limite ou soumis à consignes"),
        "airspace": (asp_s, "aucun espace aérien gênant" if asp_s == 100 else "espace aérien proche ou à vérifier"),
    }
    if cand.takeoff_wind.angle.calm:
        extra["takeoff_wind"] = (rules.CALM_TAKEOFF_SUBSCORE, "vent nul au déco : décollage plus technique")
    g = cand.route.glide
    if g.required_ratio > 0 and level == cand.level:  # autres niveaux : constat GLIDE_MARGIN (finesse du niveau)
        extra["landing"] = (glide_subscore(g.ratio), f"finesse requise {g.required_ratio:.1f} / "
                                                     f"{g.available_ratio:.1f}")
    sr = aggregate_score(level, findings, extra)
    risks = _risks(findings, level)
    blocking = any(
        r.level == "caution" and r.code not in NON_BLOCKING_CAUTIONS and _blocks(findings, r, level) for r in risks
    )
    return sr, risks, verdict(sr, risks, blocking, conf_raw, ctx.horizon)


def _stale_attached(ctx: DataContext, cand: Candidate) -> list[str]:
    """Balises rattachables au déco ou à l'atterro mais périmées (§12.1) : « nom (muette depuis N min) »."""
    out: list[str] = []
    for nc in (cand.takeoff_wind.nowcast, cand.landing_wind.nowcast):
        if nc is None:
            continue
        for a in nc.attachments:
            if a.stale:
                what = (
                    f"muette depuis {duration_fr(a.age_min)}"
                    if a.beacon.wind_speed_kmh is not None
                    else "aucune mesure"
                )
                txt = f"{a.beacon.name} ({what})"
                if txt not in out:
                    out.append(txt)
    return out


def _only_strong_thermals(cand: Candidate) -> bool:
    codes = {r.split("]")[0].strip("[") for r in cand.reject_reasons}
    return codes == {"STRONG_THERMALS"} or (
        codes <= {"STRONG_THERMALS", "LANDING_WIND", "VALLEY_BREEZE"} and "STRONG_THERMALS" in codes
    )


def _blocks(findings: list[Finding], risk: Risk, level: str) -> bool:
    return any(f.code == risk.code and f.risk_level(level) == "caution" and f.blocks_go for f in findings)


def _risks(findings: list[Finding], level: str) -> list[Risk]:
    """Un seul Risk par code (lot 6.8) : niveau le plus grave, titre du constat le plus grave, détails concaténés."""
    by_code: dict[str, list[Risk]] = {}
    for f in findings:
        r = f.to_risk(level)
        if r is None:
            continue
        by_code.setdefault(r.code, []).append(r)
    out: list[Risk] = []
    for code, rs in by_code.items():
        rs.sort(key=lambda r: ALL_CODES_ORDER.index(r.level))
        details = list(dict.fromkeys(r.detail for r in rs))
        out.append(Risk(code=code, level=rs[0].level, title=rs[0].title, detail=" ".join(details)))
    out.sort(key=lambda r: ALL_CODES_ORDER.index(r.level))
    return out


# =============================================================================================
# Orchestration par décollage
# =============================================================================================
def _landing_setup(ctx: DataContext, site: Site) -> tuple[Site | None, list[Site], list[Site]]:
    """Mode classique : atterro principal = premier atterro associé OFFICIEL ; secours et réserve (cross) = atterros
    officiels plus bas à moins de 40 km (les atterros communautaires et les champs relèvent du décollage libre)."""
    assoc = [ctx.landings[i] for i in site.associated_landing_ids
             if i in ctx.landings and landing_kind_of(ctx.landings[i]) == "official"]  # fmt: skip
    meta = ctx.site_meta.get(site.id)
    if not assoc and meta and meta.top_landing:
        assoc = [site]
    if not assoc:
        return None, [], []
    main = assoc[0]
    alternates = [x for x in assoc[1:] if x.id != main.id]
    pool = list(assoc)
    for ldg in ctx.landings.values():
        if ldg.id in {x.id for x in pool} or landing_kind_of(ldg) != "official":
            continue
        d = haversine_km(site.lat, site.lon, ldg.lat, ldg.lon)
        if d <= 40.0 and ldg.elevation_m < site.elevation_m:
            pool.append(ldg)
            if d <= rules.ALTERNATE_LANDING_SEARCH_KM and len(alternates) < 3 and ldg.id != main.id:
                alternates.append(ldg)
    return main, alternates, pool


def _big_valley(ctx: DataContext, landing: Site) -> bool:
    return big_valley(ctx, landing)


MAIN_SECTORS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def resolve_orientations(ctx: DataContext, site: Site) -> tuple[Site | None, list[Finding], str | None]:
    """Orientation utilisée pour juger le vent (revue 7.3). Une orientation « tous secteurs » (≥ 6 secteurs principaux
    sur 8, ou signalée incertaine par la source) n'en est pas une : elle est remplacée par l'exposition MNT ± 22,5°
    avec une caution « vérifie sur place » ; sans MNT, le site n'est pas proposé. Sinon, les secteurs à plus de 90° de
    l'exposition MNT (quand elle est connue) sont écartés. Renvoie (site, constats, raison de rejet)."""
    if free_takeoff.is_free_takeoff(site) or not site.orientations:
        return site, [], None
    from app.engine.terrain import dem_aspect, filter_by_aspect, orientations_from_aspect

    meta = ctx.site_meta.get(site.id)
    aspect = meta.dem_aspect_deg if meta else None  # exposition sur le MNT réel (DataService.sites)
    main = [o for o in MAIN_SECTORS if o in site.orientations]
    uncertain = bool(meta and meta.orientation_uncertain) or len(main) >= rules.ORIENTATION_UNCERTAIN_MIN_SECTORS
    if uncertain and aspect is None and ctx.mock and ctx.terrain is not None:  # démo : MNT de démonstration
        aspect = dem_aspect(ctx.terrain, site.lat, site.lon)
    if not uncertain:
        if aspect is None:
            return site, [], None
        kept = filter_by_aspect(site.orientations, aspect)
        if kept == site.orientations:
            return site, [], None
        if kept:
            return site.model_copy(update={"orientations": kept}), [], None
        uncertain = True  # aucun secteur cohérent avec le relief
    why = (meta.orientation_note if meta and meta.orientation_note
           else f"{len(main)} secteurs sur 8 donnés par la source")  # fmt: skip
    if aspect is None:
        return None, [], _codes_prefix(
            "TAKEOFF_WIND",
            f"Orientation du déco incertaine ({why}) et MNT indisponible : site non proposé (impossible de juger le "
            f"vent arrière ou le dévent ; vérifie l'orientation sur place).",
        )
    ori = orientations_from_aspect(aspect)
    f = Finding("TAKEOFF_WIND", "Orientation du déco incertaine",
                f"Orientation du déco incertaine ({why}) : orientation déduite du relief (MNT, pente orientée "
                f"{dir_label(aspect)}) = {', '.join(ori)} ; vérifie sur place.", caution=True)  # fmt: skip
    return site.model_copy(update={"orientations": ori}), [f], None


def _site_findings(ctx: DataContext, site: Site, landing: Site, proj: Projector) -> list[Finding]:
    out: list[Finding] = []
    if site.status == "closed":
        out.append(
            Finding(
                "SITE_CLOSED",
                "Site fermé",
                site.restrictions or "Site signalé fermé par la source.",
                absolute_nogo=True,
            )
        )
    elif site.status == "restricted":
        out.append(Finding("SITE_RESTRICTED", "Site soumis à restrictions", site.restrictions or "Site à accès "
            "restreint : se renseigner.",
                           caution=True))  # fmt: skip
    out += evaluate_sensitive_sites(ctx, proj, site, landing)
    fl115 = rules.FL115_M_STANDARD - rules.CEILING_MARGIN_BELOW_AIRSPACE_M
    if site.elevation_m > fl115:  # revue 7.15 (CDC §7.4) : haute montagne, au-dessus du plafond réglementaire
        out.append(Finding("ALTITUDE_LIMIT", "Décollage au-dessus du FL115",
                           f"Décollage à {site.elevation_m:.0f} m, au-dessus du plafond réglementaire FL115 (≈ "
                           f"{rules.FL115_M_STANDARD:.0f} m) : haute montagne, réglementation locale (Mont-Blanc, R30) "
                           f"à vérifier ; réservé aux pilotes experts.",
                           level_risk={"beginner": "danger", "intermediate": "danger", "advanced": "danger",
                                       "expert": "caution"}))  # fmt: skip
    return out


def start_bounds(ctx: DataContext) -> tuple[datetime, datetime]:
    """Bornes de window.start : [cible − 30 min, cible + 3 h] (§9.4) ; horizons ≤ 1 h : bornes du §12.5 et au
    moins 10 min après reference_time (le pilote est déjà au déco ou en train d'y monter)."""
    t0 = ctx.target_time
    nb = rules.NOWCAST_WINDOW_START_MIN.get(ctx.horizon)
    if nb is None:
        return t0 - timedelta(minutes=rules.WINDOW_START_BEFORE_TARGET_MIN), t0 + timedelta(
            hours=rules.WINDOW_START_AFTER_TARGET_H
        )
    lead = ctx.reference_time + timedelta(minutes=rules.NOWCAST_MIN_LEAD_MIN)
    if lead.second or lead.microsecond:  # minute entière suivante (heure de décollage lisible)
        lead = lead.replace(second=0, microsecond=0) + timedelta(minutes=1)
    lo = max(t0 + timedelta(minutes=nb[0]), lead)
    return lo, max(lo, t0 + timedelta(minutes=nb[1]))


def candidate_starts(ctx: DataContext, td: TakeoffData, variant: str, level: str) -> list[datetime]:
    t0 = ctx.target_time
    lo, hi = start_bounds(ctx)
    if ctx.horizon in rules.NOWCAST_WINDOW_START_MIN:
        t0 = min(max(t0, lo), hi)
        base = [t0, lo]
        k = 1
        while t0 + timedelta(minutes=15 * k) <= hi:
            base.append(t0 + timedelta(minutes=15 * k))
            k += 1
    else:
        base = [t0, t0 - timedelta(minutes=rules.WINDOW_START_BEFORE_TARGET_MIN)]
        base += [t0 + timedelta(hours=h) for h in range(1, int(rules.WINDOW_START_AFTER_TARGET_H) + 1)]
    extra: list[datetime] = []
    cw = td.cw
    if variant in ("local_thermal", "xc") and cw.start is not None:
        extra.append(cw.start)
        extra.append(cw.start + timedelta(minutes=30))
    if level == "beginner" and cw.start is not None:
        extra.append(cw.start + timedelta(minutes=30))
    starts = [b for b in base if lo <= b <= hi] + [e for e in extra if lo <= e <= hi]
    uniq: list[datetime] = []
    for s in starts:
        if all(abs((s - u).total_seconds()) > 60 for u in uniq):
            uniq.append(s)
    # ordre : l'heure cible d'abord, puis par proximité
    uniq.sort(key=lambda s: (s != t0, abs((s - t0).total_seconds())))
    return uniq


def variants_for(site: Site, filters: PlanFilters, top_landing: bool) -> list[str]:
    site_types = set(site.flight_types or ["local", "cross_country"])
    req = set(filters.flight_types or ["local", "ridge_soaring", "cross_country"])
    allowed = site_types & req
    out: list[str] = []
    if "local" in allowed:
        if filters.thermals != "required":
            out += ["plouf", "restitution"]
        if filters.thermals != "avoid":
            out.append("local_thermal")
    if "ridge_soaring" in allowed and filters.thermals != "required":
        out.append("ridge")
    if "cross_country" in allowed and filters.thermals != "avoid" and filters.difficulty != "beginner":
        out.append("xc")
    return out


def evaluate_takeoff(
    ctx: DataContext, site: Site, filters: PlanFilters
) -> tuple[list[Candidate], list[str]]:
    level = filters.difficulty
    free = free_takeoff.is_free_takeoff(site)
    sel: LandingSelection | None = None
    if free:
        # décollage libre (§12.6) : jamais pour un élève ; atterros candidats évalués dans le cône (§12.7)
        sel = select_landings(ctx, site, level, filters.wing_glide_ratio, filters.landing_policy)
        if level not in rules.FREE_TAKEOFF["allowed_levels"]:
            return [], [_codes_prefix("FREE_TAKEOFF", rules.FREE_TAKEOFF["refusal_beginner"]), *sel.reasons]
    site_r, orient_findings, orient_reject = resolve_orientations(ctx, site)
    if site_r is None:
        return [], [orient_reject] if orient_reject else []
    site = site_r
    if not site.orientations:
        why = ("précise l'orientation de la pente (MNT indisponible)" if free
               else "site visible sur la carte seulement")  # fmt: skip
        return [], [_codes_prefix("TAKEOFF_WIND", f"Orientation du déco inconnue : impossible de juger le vent "
                                                  f"({why}).")]  # fmt: skip
    if sel is not None:
        if sel.main is None:
            return [], sel.reasons
        landing = sel.main.spot.site
        alternates = [e.spot.site for e in sel.alternates]
        pool = [e.spot.site for e in sel.evals if e.policy_ok and e.use != "never" and not e.failures]
    else:
        landing, alternates, pool = _landing_setup(ctx, site)
    if landing is None:
        unofficial = [ctx.landings[i] for i in site.associated_landing_ids
                      if i in ctx.landings and landing_kind_of(ctx.landings[i]) != "official"]  # fmt: skip
        if unofficial:
            return [], [_codes_prefix("UNOFFICIAL_LANDING", f"Seul atterro associé : « {unofficial[0].name} », non "
                                      "officiel : non proposé en mode classique (étudie-le en mode décollage libre "
                                      "avec les atterros communautaires).")]  # fmt: skip
        return [], [_codes_prefix("GLIDE_MARGIN", "Aucun atterrissage identifié associé à ce déco.")]
    tl = ctx.timelines.get(site.id)
    ltl = ctx.timelines.get(landing.id) or tl
    if tl is None:
        return [], ["Prévision météo indisponible pour ce site."]
    meta = ctx.site_meta.get(landing.id)
    top_landing = (landing.elevation_m >= site.elevation_m - rules.TOP_LANDING_MAX_DROP_M) or bool(
        meta and meta.top_landing
    )
    proj = Projector(site.lat, site.lon)
    rise, sset = sun_times(ctx.target_time, site.lat, site.lon)
    day_hours = [h for h in tl.hours if abs((h.time - ctx.target_time).total_seconds()) <= 16 * 3600]
    cw = convection_window(sorted(day_hours, key=lambda h: h.time), rise, sset)
    conv = [h for h in day_hours if cw.start is not None and cw.end is not None and cw.start <= h.time <= cw.end]
    day_ceiling = max((_usable_capped(h) for h in conv), default=None)
    td = TakeoffData(
        site=site,
        tl=tl,
        landing=landing,
        ltl=ltl,
        alternates=alternates if not top_landing else [x for x in pool if x.id != landing.id][:2],
        landings_pool=pool,
        big_valley=_big_valley(ctx, landing),
        top_landing=top_landing,
        cw=cw,
        sunrise=rise,
        sunset=sset,
        site_findings=[*orient_findings, *_site_findings(ctx, site, landing, proj)],
        free=ctx.free_terrain.get(site.id) if free else None,
        sel=sel,
        day_ceiling=day_ceiling,
    )
    if free and sel is not None and sel.main is not None:
        td.site_findings = [*free_takeoff.site_findings(site, td.free), *td.site_findings,
                            *landing_kind_findings(ctx, sel.main, sel.alternates)]  # fmt: skip
    if top_landing:
        # le plouf / local nécessitent un atterro en contrebas : on prend le premier atterro de secours
        lower = [x for x in pool if x.elevation_m < site.elevation_m - rules.TOP_LANDING_MAX_DROP_M]
        td.landings_pool = lower
    accepted: list[Candidate] = []
    reasons_first: list[str] = []
    target_nogo = False
    for variant in variants_for(site, filters, top_landing):
        vt = td
        lo_b, hi_b = start_bounds(ctx)
        if variant == "restitution" and (target_nogo or not (
            sset and sset - timedelta(hours=rules.RESTITUTION_BEFORE_SUNSET_H) <= hi_b and lo_b < sset
        )):  # fmt: skip
            # revue 7.20 : restitution proposée dès que son créneau recoupe [cible − 30 min, cible + 3 h] ; mais un
            # no-go absolu à l'heure cible reste un no-go (lot 2.9 : pluie, orage… ne se rattrapent pas le soir)
            continue
        site_meta = ctx.site_meta.get(site.id)
        if variant == "ridge" and not top_landing and (site.kind == "both" or (site_meta and site_meta.top_landing)):
            # lot 3.2 : le déco sert de top landing, l'atterro en contrebas devient le secours
            vt = TakeoffData(**{**td.__dict__, "landing": site, "ltl": tl, "alternates": [landing, *alternates][:2],
                                "top_landing": True, "big_valley": False})  # fmt: skip
        elif variant != "ridge" and top_landing:
            lower = td.landings_pool
            if not lower:
                continue
            vt = TakeoffData(
                **{
                    **td.__dict__,
                    "landing": lower[0],
                    "ltl": ctx.timelines.get(lower[0].id) or tl,
                    "alternates": lower[1:3],
                    "top_landing": False,
                    "big_valley": _big_valley(ctx, lower[0]),
                }
            )
        first_reasons: list[str] | None = None
        for start in candidate_starts(ctx, vt, variant, level):
            res = evaluate_variant(ctx, vt, variant, start, filters, proj)
            if isinstance(res, str):
                # variante infaisable à cet instant (ex. convection pas commencée) : on essaie le créneau suivant
                if first_reasons is None and start == ctx.target_time:
                    first_reasons = [res]
                continue
            cand = finalize(ctx, res, filters)
            if cand.flyability == "no_go":
                if first_reasons is None and start == ctx.target_time:
                    first_reasons = cand.reject_reasons
                    target_nogo = target_nogo or any(f.absolute_nogo for f in cand.findings)
                # un no-go météo à l'heure cible reste un no-go (lot 2.9) ; seule exception : la règle
                # « élève hors pic thermique » (1.12) autorise un autre créneau dans [cible − 30 min, cible + 3 h]
                if level == "beginner" and _only_strong_thermals(cand):
                    continue
                break
            _compute_window(ctx, vt, cand, filters)
            _difficulty_floor(vt, cand)
            _apply_alternates(ctx, vt, cand)
            accepted.append(cand)
            break
        if not any(c.variant == variant for c in accepted) and first_reasons:
            reasons_first += first_reasons
    # lot 6.3 : le plouf n'est « seul possible » que si aucune variante thermique n'est faisable
    if any(c.thermal_usage != "none" and c.variant in ("local_thermal", "xc") for c in accepted):
        for c in accepted:
            if c.variant == "plouf":
                c.duration_note = (
                    f"Variante sans thermique : plouf direct de ~{c.duration_min:.0f} min (plan B si ça ne monte pas)."
                )
    return accepted, dedupe_reasons(reasons_first)


def _reason_severity(r: str) -> int:
    low = r.lower()
    if "hors limites" in low or "no-go" in low or "interdit" in low:
        return 2
    return 1 if "trop fortes pour ton niveau" in low else 0


def dedupe_reasons(reasons: list[str]) -> list[str]:
    """Revue 7.18 : une raison par code (la plus grave ; à gravité égale, la première, celle de l'heure cible) ; les
    raisons sans code restent toutes."""
    out: list[str] = []
    by_code: dict[str, int] = {}
    for r in dict.fromkeys(reasons):
        code = r[1 : r.index("]")] if r.startswith("[") and "]" in r else None
        if code is None:
            out.append(r)
            continue
        if code not in by_code:
            by_code[code] = len(out)
            out.append(r)
        elif _reason_severity(r) > _reason_severity(out[by_code[code]]):
            out[by_code[code]] = r
    return out


MAX_ALTERNATES = 3
MAX_ALTERNATES_XC = 5
XC_ALTERNATE_SAMPLE_KM = 2.0


Origin = tuple[float, float, float, str] | None


def _alternate_origins(td: TakeoffData, cand: Candidate) -> list[tuple[Origin, datetime]]:
    """Points d'où un secours peut être rejoint (7.1), avec l'heure de passage (vent rencontré, §14.1) : le déco
    (None) pour un plouf ou du soaring ; en local, chaque déclencheur à son altitude de point bas (déclencheur − 150 m) ;
    en cross, la route tous les 2 km à l'altitude de sécurité (plafond utile − 300 m, comme le contrôle du cône)."""
    out: list[tuple[Origin, datetime]] = [(None, cand.start)]
    route = cand.route
    if cand.variant == "local_thermal":
        for w in route.waypoints:
            if w.type == "thermal_trigger":
                out.append(((w.lat, w.lon, max(td.site.elevation_m, w.altitude_m - 150.0), w.name),
                            quarter(cand.start + timedelta(minutes=w.eta_min or 0.0))))  # fmt: skip
    elif cand.variant == "xc":
        low = cand.usable - rules.SAFETY_ALT_BELOW_CEILING_M
        total = max(route.distance_km, 0.1)
        cum = 0.0
        for a, b in pairwise(route.coords[:-1]):
            seg = haversine_km(a[1], a[0], b[1], b[0])
            n = max(1, int(seg / XC_ALTERNATE_SAMPLE_KM))
            for i in range(1, n + 1):
                f = i / n
                km = cum + f * seg
                t = quarter(cand.start + timedelta(minutes=cand.duration_min * km / total))
                out.append(((a[1] + f * (b[1] - a[1]), a[0] + f * (b[0] - a[0]), low, f"la route (km {km:.0f})"), t))
            cum += seg
    return out


def _apply_alternates(ctx: DataContext, td: TakeoffData, cand: Candidate) -> None:
    """Secours publiés (revue 7.1, 7.12) : seulement les atterros atteignables avec la marge (r ≤ 1, relief dégagé)
    depuis le déco (plouf, soaring) ou depuis au moins un point de la route à son altitude de sécurité (local, cross),
    et dont le vent d'arrivée reste dans les seuils du niveau. Les autres sortent des `alternate_landings`, des
    waypoints, du briefing et de `landing_analysis`. Le plané retenu (vent rencontré, §14) est celui que publie
    `landing_analysis` : même calcul partout."""
    level = cand.level
    takeoff, landing = cand.takeoff, cand.landing
    pool = cand.route.used_landings if cand.variant == "xc" else cand.alternates
    if cand.variant == "xc":
        pool = [*pool, *[x for x in cand.alternates if x.id not in {p.id for p in pool}]]
    origins = _alternate_origins(td, cand)
    proj = projector_for(ctx, takeoff)
    evals: list[tuple[float, LandingEval]] = []
    seen: set[str] = set()
    for s in pool:
        if s.id in (landing.id, takeoff.id) or s.id in seen:
            continue
        seen.add(s.id)
        best: tuple[float, Origin, datetime, GlideCheck, list[tuple[float, float]]] | None = None
        for o, t in origins:
            lat, lon, alt = (takeoff.lat, takeoff.lon, takeoff.elevation_m) if o is None else o[:3]
            path = path_for(ctx, proj, lat, lon, s)[0] if o is None else []
            g = glide_to(ctx, lat, lon, alt, s, level, cand.wing, cand.glide_wind, path=path, t=t)
            if g.margin_ok and (best is None or g.ratio < best[0]):
                best = (g.ratio, o, t, g, path)
        if best is None:
            continue  # hors de portée de partout : jamais publié comme secours
        ev = evaluate_spot(ctx, takeoff, spot_for(ctx, s), level, cand.wing, cand.glide_wind, cand.landing_time,
                           cand.policy, origin=best[1], t_origin=best[2], path=best[4], glide=best[3])  # fmt: skip
        if ev.usable:
            evals.append((best[0], ev))
    evals.sort(key=lambda x: (x[0], -x[1].score))
    keep = [e for _, e in evals][: MAX_ALTERNATES_XC if cand.variant == "xc" else MAX_ALTERNATES]
    cand.alt_evals = keep
    cand.alternates = [e.spot.site for e in keep]
    cand.route.waypoints = [w for w in cand.route.waypoints if w.type != "alternate_landing"]
    cand.route.waypoints += alternates_waypoints(cand.alternates)


def _window_check(
    ctx: DataContext, td: TakeoffData, cand: Candidate, t: datetime, level: str
) -> tuple[float, str | None]:
    """(ratio max vent/seuil au déco à t et à l'atterro à t + durée, cause du no-go à t ou None). Revue 7.6 : en plus
    du vent et de la pluie, les constats bloquants horaires (vent arrière, déco E passé à l'ombre, dévent, vent hors
    limites, orage / surdéveloppement) ferment le créneau."""
    ridge = cand.variant == "ridge"
    tw = takeoff_wind(ctx, td.site, td.tl, t)
    wl = rules.RIDGE["max_kmh"][level] if ridge else rules.TAKEOFF_WIND_MAX_KMH[level]
    gl = rules.RIDGE_GUST_MAX_KMH[level] if ridge else rules.TAKEOFF_GUST_MAX_KMH[level]
    tail_max = rules.TAILWIND_MAX_KMH[level]
    if free_takeoff.is_free_takeoff(td.site):  # §12.6 : seuils du décollage libre
        fwl, fgl, tail_max = free_takeoff.wind_limits(level)
        wl, gl = min(wl, fwl), min(gl, fgl)
    r = max(tw.speed_kmh / wl, tw.gust_kmh / gl)
    why: str | None = "vent ou rafales au-delà du seuil de ton niveau au déco" if r > 1.0 else None
    end = t + timedelta(minutes=cand.duration_min)
    if not (ridge and td.top_landing):
        lw = landing_wind(td.ltl, end, td.big_valley, ctx, td.landing)
        rl = max(lw.speed_kmh / rules.LANDING_WIND_MAX_KMH[level], lw.gust_kmh / rules.LANDING_GUST_MAX_KMH[level])
        if rl > 1.0 and why is None:
            why = "vent trop fort à l'atterro à l'arrivée"
        r = max(r, rl)
    if why is None and not (ridge and td.top_landing) and td.landing.id != td.site.id:
        # §14 : plané direct déco → atterro principal au vent rencontré à t (vent de face qui forcit, brise qui tourne)
        field = GlideField(ctx, td.site, td.tl, t, tw=tw, main_landing=td.landing, main_ltl=td.ltl,
                           main_big_valley=td.big_valley)  # fmt: skip
        plouf = plouf_minutes(td.site.elevation_m - td.landing.elevation_m)
        g = _direct_glide(ctx, td, cand.route, level, cand.wing, field, t,
                          end if cand.variant == "plouf" else t + timedelta(minutes=plouf))  # fmt: skip
        if g.ratio > 1.0:
            w = g.wind
            face = " (vent de face)" if w is not None and w.along_kmh <= -5 else ""
            why = f"plané vers {td.landing.name} impossible{face}"
    if why is None and td.tl.at(t).precipitation_mm_h >= rules.NOGO["precip_mm_h"]:
        why = "pluie"
    if why is None and tw.angle.category == "tail" and tw.speed_kmh > tail_max:
        why = "vent arrière au déco"
    if why is None:
        hourly = takeoff_wind_findings(tw, td.site, ridge, solar_hour(t, td.site.lon))
        hourly += convective_findings(td.tl, td.cw, t, end, cand.variant)[0]
        nogo = next((f for f in hourly if f.absolute_nogo), None)
        if nogo is not None:
            why = nogo.title[0].lower() + nogo.title[1:]
    return r, why


def _compute_window(ctx: DataContext, td: TakeoffData, cand: Candidate, filters: PlanFilters) -> None:
    """Fin du créneau (lot 6.7, revue 7.5-7.7) : on coupe avant le premier pas qui ferait passer le plan en no-go
    (vent / rafales au déco, vent à l'atterro à l'arrivée, pluie, constats bloquants horaires) et au plus tard à
    coucher − 30 min − durée, cible + 3 h (validité du nowcasting aux horizons ≤ 1 h), convection + 1 h pour un élève
    en thermique. Le vent qui entre dans la bande 80-100 % : le créneau GO s'arrête au pas précédent (info) ; si c'est
    dans les 30 premières minutes, caution WIND_INCREASING et verdict au mieux MARGINAL. La cause qui ferme le créneau
    est gardée (`window_end_reason`) pour expliquer l'heure « être posé avant »."""
    level = filters.difficulty
    start = cand.start
    dur = timedelta(minutes=cand.duration_min)
    caps: list[tuple[datetime, str]] = [(cand.latest_landing - dur, cand.landing_cap_reason or "fin de la fenêtre")]
    step = timedelta(minutes=30)
    if ctx.horizon in rules.NOWCAST_WINDOW_START_MIN:
        # horizons ≤ 1 h (§12.5) : créneau borné par la validité du nowcasting, pas de 15 min
        caps.append((start_bounds(ctx)[1], "fin de validité de la lecture des balises"))
        step = timedelta(minutes=15)
    else:
        caps.append((ctx.target_time + timedelta(hours=rules.WINDOW_START_AFTER_TARGET_H), "heure cible + 3 h"))
    if cand.sunset:
        caps.append((cand.sunset - timedelta(minutes=rules.LANDING_BEFORE_SUNSET_MIN) - dur,
                     "posé 30 min avant le coucher du soleil"))  # fmt: skip
    if level == "beginner" and cand.variant == "local_thermal" and td.cw.start is not None:
        caps.append((td.cw.start + timedelta(hours=rules.BEGINNER_THERMAL_OFFPEAK_AFTER_START_H),
                     "élève : décollage avant le début des thermiques + 1 h (hors pic)"))  # fmt: skip
    hard_end, hard_reason = min(caps, key=lambda c: c[0])
    r0, _ = _window_check(ctx, td, cand, start, level)
    end = start
    reason = hard_reason
    t = start + step
    increasing_at: datetime | None = None
    while t <= hard_end:
        r, why = _window_check(ctx, td, cand, t, level)
        if why is not None:
            reason = f"{why} à partir de {fmt_hm(t)}"
            break
        if increasing_at is None and r0 < rules.MARGINAL_BAND <= r:
            increasing_at = t
            break
        end = t
        t += step
    cand.window_start = start
    we = end if end > start else start + timedelta(minutes=15)
    if increasing_at is not None and increasing_at - start > timedelta(minutes=30):
        we = min(we, increasing_at - step)
        reason = f"le vent forcit à partir de {fmt_hm(increasing_at)}"
        cand.risks.append(Risk(code="WIND_INCREASING", level="info", title="Fin du créneau GO",
                               detail=f"Fin du créneau à {fmt_hm(max(start, we))} : le vent forcit ensuite (proche des "
                                      f"limites de ton niveau à partir de {fmt_hm(increasing_at)})."))  # fmt: skip
        _merge_risk_code(cand, "WIND_INCREASING")
    elif increasing_at is not None:
        detail = (f"Le vent forcit dès {fmt_hm(increasing_at)}, juste après le début du créneau (proche des limites "
                  f"de ton niveau) : décoller tout de suite ou renoncer.")  # fmt: skip
        reason = f"le vent forcit à partir de {fmt_hm(increasing_at)}"
        cand.risks.append(Risk(code="WIND_INCREASING", level="caution", title="Le vent forcit", detail=detail))
        _merge_risk_code(cand, "WIND_INCREASING")
        if cand.flyability == "go":  # caution bloquante (§9.4) : verdict recalculé
            cand.flyability = "marginal"
    # revue 7.2 : window.end + durée ≤ latest_landing (jamais un créneau qui finit après l'heure limite)
    cand.window_end = max(start, min(we, hard_end if hard_end >= start else start))
    cand.window_end_reason = reason


def _difficulty_floor(td: TakeoffData, cand: Candidate) -> None:
    """Revue 7.10 : un vol de plus de 45 min, ou un créneau thermique qui déborde le début des thermiques + 1 h (règle
    « hors pic » de l'élève, §2.1), n'est pas un vol d'élève : difficulté au moins « brevet de pilote »."""
    long_flight = cand.duration_min > rules.MAX_DURATION_MIN["beginner"] + 0.5
    peak = (
        cand.variant in ("local_thermal", "xc")
        and td.cw.start is not None
        and cand.window_end is not None
        and cand.window_end > td.cw.start + timedelta(hours=rules.BEGINNER_THERMAL_OFFPEAK_AFTER_START_H)
    )
    if (long_flight or peak) and cand.difficulty == "beginner":
        cand.difficulty = "intermediate"


def _merge_risk_code(cand: Candidate, code: str) -> None:
    """Un seul Risk par code (lot 6.8) : niveau le plus grave, détails concaténés."""
    same = [r for r in cand.risks if r.code == code]
    if len(same) < 2:
        return
    same.sort(key=lambda r: ALL_CODES_ORDER.index(r.level))
    keep = same[0]
    keep.detail = " ".join(dict.fromkeys(r.detail for r in same))
    cand.risks = [r for r in cand.risks if r.code != code or r is keep]


# =============================================================================================
# Construction des FlightPlan et classement
# =============================================================================================
def _plan_id(ctx: DataContext, cand: Candidate) -> str:
    raw = (f"{ctx.request_key}|{cand.takeoff.id}|{cand.variant}|{cand.start.isoformat()}|"
           f"{ctx.reference_time.isoformat()}|{cand.level}")  # fmt: skip
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _window_end(ctx: DataContext, td_tl: PointTimeline, cand: Candidate) -> datetime:
    latest_start = cand.latest_landing - timedelta(minutes=cand.duration_min)
    end = max(cand.start + timedelta(minutes=15), min(latest_start, cand.start + timedelta(hours=3)))
    if cand.variant in ("plouf", "restitution") and cand.sunset:
        end = min(end, cand.sunset - timedelta(minutes=cand.duration_min))
    return max(end, cand.start)


ROUND_QUARTER_FROM_MIN = 12 * 60  # revue 7.19 : pas de fausse précision dès 12 h d'horizon (CDC §1.1, §10 #21)
QUARTER = timedelta(minutes=15)


def _floor_q(t: datetime) -> datetime:
    t = t.replace(second=0, microsecond=0)
    return t - timedelta(minutes=t.minute % 15)


def _round_quarter(cand: Candidate, by_window: datetime) -> None:
    """« Être posé avant » au quart d'heure : arrondi vers le haut quand c'est la fin du créneau + la durée qui borne
    (sans jamais dépasser le plafond horaire), vers le bas sinon ; le créneau est raccourci d'autant si besoin."""
    cap = cand.latest_landing
    t = cand.latest_landing
    dur = timedelta(minutes=cand.duration_min)
    if t == by_window or _floor_q(t) < cand.start + dur:
        up = _floor_q(t) + (QUARTER if t != _floor_q(t) else timedelta())
        t = up if up <= cap or _floor_q(t) < cand.start + dur else _floor_q(t)
    else:
        t = _floor_q(t)
    if cand.window_end is not None and cand.window_end + dur > t:
        cand.window_end = max(cand.start, (t - dur).replace(second=0, microsecond=0))
    cand.latest_landing = max(t, cand.start + dur)


def _correction(nc: StationNowcast | None, dv: float, d: float, md: float) -> NowcastCorrection | None:
    """Correction effectivement appliquée au vent modèle (fusion balise + tendance), au déco ou à l'atterro."""
    if nc is None or not nc.has_representative:
        return None
    return NowcastCorrection(
        beacon_ids=nc.beacon_ids,
        wind_speed_bias_kmh=round(dv, 1),
        wind_direction_bias_deg=round((d - md + 180.0) % 360.0 - 180.0, 0),
    )


MAX_READINGS_PER_SITE = 3


def _readings_for(ctx: DataContext, nc: StationNowcast | None, site: Site, role: str) -> list[StationReading]:
    """Balises rattachées (représentatives d'abord) ; sans balise représentative, la plus proche quand même, avec la
    raison dans `comment` (§12.3)."""
    out: list[StationReading] = []
    atts = list(nc.attachments) if nc is not None else []
    if not any(a.representative for a in atts):
        near = nearest_unattached(ctx, site, role, {a.beacon.id for a in atts})
        if near is not None and (
            not atts
            or near.distance_km < min(a.distance_km for a in atts)
            or (not near.stale and all(a.stale for a in atts))
        ):
            atts.append(near)
        atts.sort(key=lambda a: (a.stale, a.distance_km))  # balises qui transmettent d'abord, muettes ensuite
    for a in atts[:MAX_READINGS_PER_SITE]:
        w = round(nc.weight_of(a), 2) if nc is not None else 0.0
        dz = a.alt_diff_m
        out.append(StationReading(
            site_role=role, site_id=site.id, beacon=a.beacon, distance_km=round(a.distance_km, 2),
            altitude_diff_m=round(dz) if dz is not None else 0.0, representative=a.representative and w > 0,
            weight=round(w, 2), comment=reading_comment(a, w),
        ))  # fmt: skip
    return out


def station_readings(ctx: DataContext, cand: Candidate) -> list[StationReading]:
    """StationReading du déco (début du créneau), de l'atterro et des atterros de secours (heure d'arrivée).
    Horizons de nowcasting seulement (≤ 2 h) : au-delà, les balises ne corrigent pas la prévision (§8.2)."""
    from app.engine.stations import nowcast_active

    if not ctx.beacons or not nowcast_active(ctx):
        return []
    out: list[StationReading] = []
    tl = ctx.timelines[cand.takeoff.id]
    out += _readings_for(ctx, cand.takeoff_wind.nowcast, cand.takeoff, "takeoff")
    arrival = cand.landing_time
    if cand.landing.id != cand.takeoff.id:
        out += _readings_for(ctx, cand.landing_wind.nowcast, cand.landing, "landing")
    seen = {r.beacon.id for r in out}
    for alt in cand.alternates[:3]:
        if alt.id == cand.takeoff.id:
            continue
        atl = ctx.timelines.get(alt.id) or ctx.timelines.get(cand.landing.id) or tl
        nc_a = station_nowcast(ctx, alt, "alternate_landing", atl, arrival, _big_valley(ctx, alt))
        for r in _readings_for(ctx, nc_a, alt, "alternate_landing"):
            if r.beacon.id not in seen or r.representative:
                out.append(r)
                seen.add(r.beacon.id)
    return out


def _models(h: HourAnalysis, tl: PointTimeline) -> str:
    """Modèles réellement présents à cette heure (revue, m) ; à défaut, l'étiquette de la série."""
    return "+".join(h.models) if h.models else tl.model_label


def to_flight_plan(ctx: DataContext, cand: Candidate, rank: int, sources) -> FlightPlan:
    tl = ctx.timelines[cand.takeoff.id]
    ltl = ctx.timelines.get(cand.landing.id) or tl
    tw = cand.takeoff_wind
    nc_to = _correction(tw.nowcast, tw.speed_kmh - tw.model_speed_kmh, tw.direction_deg, tw.model_direction_deg)
    snap_to = snapshot_from_analysis(tw.hour, _models(tw.hour, tl), (tw.speed_kmh, tw.direction_deg, tw.gust_kmh),
                                     nc_to)  # fmt: skip
    lw = cand.landing_wind
    nc_ldg = _correction(lw.nowcast, lw.speed_kmh - lw.model_speed_kmh, lw.direction_deg, lw.model_direction_deg)
    snap_ldg = snapshot_from_analysis(lw.hour, _models(lw.hour, ltl), (lw.speed_kmh, lw.direction_deg, lw.gust_kmh),
                                      nc_ldg)  # fmt: skip
    timeline = []
    for h in tl.hours:
        if abs((h.time - cand.start).total_seconds()) <= 3 * 3600 + 1:
            twx = takeoff_wind(ctx, cand.takeoff, tl, h.time)
            timeline.append(snapshot_from_analysis(h, _models(h, tl), (twx.speed_kmh, twx.direction_deg, twx.gust_kmh)))
    cw = cand.convection
    od = cw.overdevelopment_risk
    day_ceiling = cand.day_ceiling if cand.day_ceiling is not None else cand.usable
    th_comment = (
        f"Pic des thermiques {cw.peak_strength_ms:.1f} m/s, plafond utile de la journée {day_ceiling:.0f} m"
        + (f", cumulus base {tw.hour.cloud_base_m:.0f} m" if tw.hour.cloud_base_m else ", thermiques bleus")
        + f", surdéveloppement {dict(low='faible', moderate='modéré', high='élevé')[od]}."
    )
    thermals = ThermalAnalysis(
        convection_start=iso(cw.start) if cw.start else None,
        convection_end=iso(cw.end) if cw.end else None,
        peak_time=iso(cw.peak) if cw.peak else None,
        peak_strength_ms=round(cw.peak_strength_ms, 1),
        # revue 7.21 : aérologie de la JOURNÉE (identique pour tous les plans du site), bornée par le plafond du plan
        # (espace aérien, FL115) pour un vol thermique
        ceiling_m=round(min(day_ceiling, cand.max_alt) if cand.thermal_usage != "none" else day_ceiling),
        cumulus=tw.hour.cumulus,
        overdevelopment_risk=od,
        comment=th_comment,
    )
    beacons_nearby: list[Beacon] = [
        b
        for b in ctx.beacons
        if haversine_km(b.lat, b.lon, cand.takeoff.lat, cand.takeoff.lon) <= rules.BEACON_SEARCH_RADIUS_KM
    ][:10]
    plan_id = _plan_id(ctx, cand)
    if cand.window_start is None:
        cand.window_start = cand.start
        cand.window_end = _window_end(ctx, tl, cand)
    # dernier atterrissage pour ce verdict = min(fin du créneau + durée, plafond horaire, coucher du soleil)
    by_window = cand.window_end + timedelta(minutes=cand.duration_min)
    latest = min(cand.latest_landing, by_window)
    if cand.sunset:
        latest = min(latest, cand.sunset)
    if by_window < cand.latest_landing - timedelta(minutes=1) and latest == by_window:
        # revue 7.7 : c'est la fin du créneau + la durée du vol qui borne l'heure, avec la cause qui a fermé le créneau
        why = f" ; {cand.window_end_reason}" if cand.window_end_reason else ""
        cand.landing_cap_reason = f"fin du créneau à {fmt_hm(cand.window_end)} + {duration_label(cand.duration_min)} " \
                                  f"de vol{why}"
    # revue 7.2 : jamais au-dessus du plafond horaire (surdéveloppement, coucher…) ; les constats rejettent un vol
    # qui finirait après ce plafond
    cand.latest_landing = latest
    if HORIZON_MINUTES.get(ctx.horizon, 0) >= ROUND_QUARTER_FROM_MIN:
        _round_quarter(cand, by_window)
    analysis = candidates_for_plan(
        ctx, cand.takeoff, cand.landing, cand.alternates, cand.level, cand.wing, cand.glide_wind, cand.landing_time,
        cand.policy, cand.landing_wind, extra=cand.landing_sel.evals if cand.landing_sel is not None else None,
        alt_evals=cand.alt_evals, main_classic=True, pair=is_source_pair(cand.takeoff, cand.landing),
        t_origin=cand.start, main_path=cand.route.glide_path, main_glide=cand.ref_glide,
    )  # fmt: skip
    cand.landing_warnings = analysis[0].warnings if analysis and analysis[0].site.id == cand.landing.id else []
    return FlightPlan(
        id=plan_id,
        rank=rank,
        score=cand.score,
        flyability=cand.flyability,
        difficulty=cand.difficulty,
        flight_type=cand.flight_type,
        thermal_usage=cand.thermal_usage,
        title=title(cand),
        summary=summary(cand),
        target_time=iso(ctx.target_time),
        window=TimeWindow(
            start=iso(cand.window_start), end=iso(cand.window_end), latest_landing=iso(cand.latest_landing)
        ),
        sun=SunTimes(
            sunrise=iso(cand.sunrise) if cand.sunrise else None, sunset=iso(cand.sunset) if cand.sunset else None
        ),
        takeoff=cand.takeoff,
        landing=cand.landing,
        alternate_landings=cand.alternates,
        landing_analysis=analysis,
        waypoints=cand.route.waypoints,
        route=RouteGeometry(coordinates=[(round(c[0], 6), round(c[1], 6), round(c[2])) for c in cand.route.coords]),
        distance_km=round(cand.route.distance_km, 1),
        est_duration_min=round(cand.duration_min),
        max_altitude_m=round(cand.max_alt),
        glide=plan_glide(cand),
        weather=PlanWeather(takeoff=snap_to, landing=snap_ldg, timeline=timeline),
        thermals=thermals,
        sounding=sounding_from_analysis(tw.hour),
        beacons_nearby=beacons_nearby,
        station_readings=station_readings(ctx, cand),
        airspaces=cand.airspaces,
        risks=cand.risks,
        briefing=briefing(cand),
        checklist=checklist(cand),
        score_breakdown=cand.score_items,
        confidence=round(cand.confidence, 2),
        sources=sources,
        links=PlanLinks(gpx=f"/api/plans/{plan_id}/gpx", xctsk=f"/api/plans/{plan_id}/xctsk"),
    )


def plan_glide(cand: Candidate) -> Glide:
    """FlightPlan.glide (§14.7) : le pire plané du lot 6.11, tous les champs décrivent CE plané."""
    g = cand.route.glide
    w = g.wind
    return Glide(
        required_ratio=round(g.required_ratio, 2),
        available_ratio=round(g.available_ratio, 2),
        margin_ok=bool(g.margin_ok),
        calm_available_ratio=round(g.calm_ratio, 2),
        wind_along_track_kmh=0.0 if w is None else round(w.along_kmh, 1),
        wind_credit_kmh=0.0 if w is None else round(w.credit_kmh, 1),
        expected_arrival_height_m=None if w is None or g.expected_arrival_m is None else round(g.expected_arrival_m),
        comment=glide_comment(g, g.landing_name or cand.landing.name, cand.level, cand.wing, g.detour_zones,
                              cand.high_arrival_m),  # fmt: skip
    )


def _main_axis_sector(site: Site) -> int:
    from app.engine.routing import site_axis

    return int(((site_axis(site) + 22.5) % 360) // 45)


def evaluate_sites(
    ctx: DataContext, filters: PlanFilters, sources=None
) -> tuple[list[FlightPlan], list[RejectedSite], list[str], list[Candidate]]:
    all_cands: list[Candidate] = []
    rejected: list[RejectedSite] = []
    for site in ctx.takeoffs:
        cands, reasons = evaluate_takeoff(ctx, site, filters)
        if cands:
            cands.sort(key=lambda c: _rank_key(c, filters))
            # au plus 2 plans par déco, de types différents si possible
            kept: list[Candidate] = []
            for c in cands:
                if len(kept) >= rules.MAX_PLANS_PER_TAKEOFF:
                    break
                if any(k.flight_type == c.flight_type and k.thermal_usage == c.thermal_usage for k in kept):
                    continue
                kept.append(c)
            all_cands += kept
        else:
            rejected.append(RejectedSite(site=site, reasons=reasons or ["Aucun vol possible dans le créneau demandé."]))
    all_cands.sort(key=lambda c: _rank_key(c, filters))
    n = filters.max_results
    selected = all_cands[:n]
    # diversité d'orientation : au moins un plan d'une autre orientation si disponible
    if len(selected) >= 2:
        sectors = {_main_axis_sector(c.takeoff) for c in selected}
        if len(sectors) == 1:
            other = next((c for c in all_cands[n:] if _main_axis_sector(c.takeoff) not in sectors), None)
            if other is not None:
                selected[-1] = other
    plans = [to_flight_plan(ctx, c, i + 1, sources or []) for i, c in enumerate(selected)]
    warnings = list(ctx.warnings)
    if ctx.mock:
        demo = ["météo simulée"]
        if ctx.takeoffs and all(s.source == "fixture" for s in ctx.takeoffs):
            demo.append("sites de démonstration")
        if all(b.source == "fixture" for b in ctx.beacons):
            demo.append("balises de démonstration")
        warnings.append(
            f"Mode démo : données SYNTHÉTIQUES ({', '.join(demo)}). "
            "Confiance affichée plafonnée à 30 % — ne pas utiliser pour décider d'un vol."
        )
    if not plans:
        warnings.append("Aucun plan volable dans la zone pour ces critères : voir les raisons de rejet par site.")
    return plans, rejected, warnings, selected


def _rank_key(c: Candidate, filters: PlanFilters) -> tuple:
    """Tri (lot 6.2) : verdict, durée dans la plage demandée, score plafonné, score non plafonné."""
    in_range = filters.duration_min_minutes <= c.duration_min <= filters.duration_max_minutes
    return (-_verdict_rank(c.flyability), not in_range, -c.score, -c.raw_score)


def _verdict_rank(v: str) -> int:
    return {"go": 2, "marginal": 1, "no_go": 0}[v]


