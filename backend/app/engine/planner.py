"""Moteur de plans de vol : pour chaque décollage de la zone, évalue les variantes de vol (plouf,
local thermique, soaring, cross) sur les créneaux autour de l'heure cible, applique les filtres durs
(§3 no-go, §2 seuils par niveau), calcule score / verdict / difficulté, puis classe les plans.

Point d'entrée : `evaluate_sites(ctx, filters) -> (plans, rejected, warnings)` (synchrone, sans réseau).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.engine import rules
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
    vector_mean,
)
from app.engine.context import DataContext, PointTimeline
from app.engine.findings import Finding, max_level, smallest_passing_level
from app.engine.routing import (
    GlideCheck,
    Route,
    build_cross,
    build_local_thermal,
    build_plouf,
    build_ridge,
    glide_to,
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
from app.geo import angle_diff, haversine_km
from app.meteo.snapshot import iso, snapshot_from_analysis, sounding_from_analysis
from app.meteo.thermals import ConvectionWindow, HourAnalysis, convection_window
from app.models import (
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
    SunTimes,
    ThermalAnalysis,
    TimeWindow,
)

LEVELS = rules.LEVELS
VARIANT_TYPE = {"plouf": "local", "restitution": "local", "local_thermal": "local", "ridge": "ridge_soaring", "xc": "cross_country"}
NON_BLOCKING_CAUTIONS = {"MOCK_DATA", "ALTITUDE_LIMIT", "ACCESS_TIME"}
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
            f"Vent au déco {wdesc} (seuil de ton niveau appliqué).",
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
        Finding("TAKEOFF_GUSTS", "Écart rafales / vent moyen", f"Écart rafale − moyenne de {spread:.0f} km/h (air turbulent).",
                criterion="takeoff_wind", value=spread, limits=dict(spread_lim))
    )  # fmt: skip
    if v >= rules.GUST_FACTOR_MIN_MEAN_KMH:
        f.append(
            Finding("TAKEOFF_GUSTS", "Vent rafaleux", f"Facteur de rafale {g / v:.2f} (rafale / moyenne).",
                    value=g / v, limits=dict(rules.GUST_FACTOR_MAX), soft=True, blocks_go=False)
        )  # fmt: skip
    # absolus §3 #9
    if v > rules.NOGO["takeoff_wind_abs_kmh"] or g > rules.NOGO["takeoff_gust_abs_kmh"] or spread > rules.GUST_SPREAD_ABS_MAX_KMH:
        code = "TAKEOFF_WIND" if v > rules.NOGO["takeoff_wind_abs_kmh"] else "TAKEOFF_GUSTS"
        f.append(Finding(code, "Vent au déco hors limites (tous niveaux)", f"Vent au déco {wdesc} : hors limites.", absolute_nogo=True))
    ang = tw.angle
    if not ang.calm:
        if ang.category == "cross":
            f.append(
                Finding("CROSSWIND", "Vent de travers au déco",
                        f"Vent {ang.ecart_deg:.0f}° hors de l'axe du déco (orientations {', '.join(site.orientations)}).",
                        criterion="takeoff_wind", value=ang.ecart_deg,
                        limits=dict(rules.RIDGE["max_angle_deg"] if ridge else rules.CROSSWIND_ANGLE_MAX_DEG))
            )  # fmt: skip
            f.append(
                Finding("CROSSWIND", "Composante de travers", f"Composante de travers {ang.cross_component_kmh:.0f} km/h.",
                        criterion="takeoff_wind", value=ang.cross_component_kmh, limits=dict(rules.CROSSWIND_COMPONENT_MAX_KMH))
            )  # fmt: skip
        elif ang.category == "tail":
            if ridge:
                f.append(Finding("TAILWIND", "Vent arrière : pas de soaring possible", "Vent arrière sur la pente.", feasibility=True,
                                 value=0.0, limits={lv: 1.0 for lv in LEVELS}, kind="min"))  # fmt: skip
            f.append(
                Finding("TAILWIND", "Vent arrière au déco",
                        f"Vent arrière de {ang.tail_component_kmh:.0f} km/h ({dir_label(tw.direction_deg)}) au déco.",
                        criterion="takeoff_wind", value=ang.tail_component_kmh,
                        limits={lv: float(x) for lv, x in rules.TAILWIND_MAX_KMH.items()}, band=False)
            )  # fmt: skip
            f.append(
                Finding("TAILWIND", "Vent arrière au déco", f"Vent arrière de {ang.tail_component_kmh:.0f} km/h : décollage délicat.",
                        caution=True)
            )  # fmt: skip
            f.append(
                Finding("CROSSWIND", "Composante de travers", f"Composante de travers {ang.cross_component_kmh:.0f} km/h.",
                        criterion="takeoff_wind", value=ang.cross_component_kmh, limits=dict(rules.CROSSWIND_COMPONENT_MAX_KMH))
            )  # fmt: skip
    # dévent / faux calme (§3 #8)
    lee = lee_angle(tw.crest_direction_deg, site.orientations)
    crest = f"vent de {tw.crest_speed_kmh:.0f} km/h du {dir_label(tw.crest_direction_deg)} au niveau des crêtes"
    if lee > rules.LEE_ANGLE_DEG and tw.crest_speed_kmh >= rules.NOGO["lee_wind_at_crest_kmh"]:
        f.append(Finding("LEE_SIDE", "Dévent : déco sous le vent",
                         f"Dévent : {crest}, opposé à l'axe du déco — rotors et faux calme, même si le vent au déco semble favorable.",
                         absolute_nogo=True))  # fmt: skip
    elif lee > rules.LEE_ANGLE_DEG and tw.crest_speed_kmh >= rules.LEE_WIND_CAUTION_KMH:
        f.append(Finding("LEE_SIDE", "Vent météo opposé au déco", f"Dévent possible : {crest}.", caution=True))
    elif 60.0 < lee <= rules.LEE_ANGLE_DEG and tw.crest_speed_kmh >= rules.SYNOPTIC_CROSSWIND_CAUTION_KMH:
        f.append(Finding("CROSSWIND", "Vent météo de travers", f"Vent météo de travers : {crest}.", caution=True))
    # déco E passé à l'ombre (§4.3 bascule)
    if site.orientations and all(o in ("NE", "ENE", "E", "ESE") for o in site.orientations):
        syn_e = tw.crest_speed_kmh >= rules.EAST_FACE_SYNOPTIC_EXEMPT_KMH and angle_diff(tw.crest_direction_deg, 90) <= 45
        if solar_h > rules.EAST_FACE_SHADE_SOLAR_H and not syn_e:
            f.append(Finding("LEE_SIDE", "Déco passé à l'ombre",
                             "Déco orienté est passé à l'ombre après 12h30 solaire : brise descendante, vent arrière probable.",
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
        Finding("TAKEOFF_WIND" if ridge else "STRONG_WIND_ALOFT",
                "Vent devant la crête" if ridge else "Vent en altitude",
                f"Vent jusqu'à {vmax:.0f} km/h vers {vmax_z:.0f} m sur la tranche volée.",
                criterion="wind_aloft", ratios=ratios)
    )  # fmt: skip
    if vmax >= rules.NOGO["wind_any_level_kmh"]:
        out.append(Finding("STRONG_WIND_ALOFT", "Vent fort en altitude", f"{vmax:.0f} km/h vers {vmax_z:.0f} m : no-go.", absolute_nogo=True))
    elif vmax >= rules.WIND_ANY_LEVEL_CAUTION_KMH:
        out.append(Finding("STRONG_WIND_ALOFT", "Vent soutenu en altitude", f"{vmax:.0f} km/h vers {vmax_z:.0f} m.", caution=True))
    v3000 = a.profile.wind(3000.0)[0]
    if alt >= rules.MOUNTAIN_MIN_TAKEOFF_M and v3000 >= rules.NOGO["wind_3000m_mountain_kmh"]:
        out.append(Finding("STRONG_WIND_ALOFT", "Vent très fort à 3000 m",
                           f"{v3000:.0f} km/h à 3000 m : la turbulence descend sur les reliefs.", absolute_nogo=True))  # fmt: skip
    # gradient déco → déco + 1000 m (sur la tranche atteinte)
    z_top = min(alt + 1000.0, max(top, alt + 300.0))
    v0 = a.profile.wind(alt)[0]
    v1 = a.profile.wind(z_top)[0]
    out.append(
        Finding("WIND_GRADIENT", "Gradient de vent", f"Le vent passe de {v0:.0f} à {v1:.0f} km/h entre {alt:.0f} et {z_top:.0f} m.",
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
            dry = (a.rh700_pct is not None and a.rh700_pct < rules.FOEHN_DRY_RH_PCT) or (a.temperature_c - a.dew_point_c > 12)
            if v7 >= rules.NOGO["foehn_700hpa_kmh"]:
                out.append(Finding("FOEHN", "Foehn", f"Flux de {dir_label(d7)} {v7:.0f} km/h à 700 hPa en travers de la crête principale : foehn, rotors et rafales en vallée.",
                                   absolute_nogo=True))  # fmt: skip
            elif v7 >= rules.FOEHN_CAUTION_700HPA_KMH and dry:
                out.append(Finding("FOEHN", "Tendance foehn", f"Flux de {dir_label(d7)} {v7:.0f} km/h à 700 hPa, air sec : tendance foehn.",
                                   caution=True))  # fmt: skip
    return out


def landing_findings(lw: LandingWind, landing: Site, end: datetime) -> list[Finding]:
    out: list[Finding] = []
    lw_lim = rules.LANDING_WIND_MAX_KMH
    lg_lim = rules.LANDING_GUST_MAX_KMH
    breeze = lw.breeze_factor > 1.0
    breeze_txt = f" (brise de vallée ×{lw.breeze_factor:.2f} incluse)" if breeze else ""
    out.append(
        Finding("LANDING_WIND", "Vent à l'atterrissage",
                f"Vent à {landing.name} vers {fmt_hm(end)} : {dir_label(lw.direction_deg)} {lw.speed_kmh:.0f} km/h{breeze_txt}.",
                criterion="landing", value=lw.speed_kmh, limits=dict(lw_lim), band=not breeze)
    )  # fmt: skip
    out.append(
        Finding("LANDING_WIND", "Rafales à l'atterrissage", f"Rafales {lw.gust_kmh:.0f} km/h à {landing.name}{breeze_txt}.",
                criterion="landing", value=lw.gust_kmh, limits=dict(lg_lim), band=not breeze)
    )  # fmt: skip
    if lw.speed_kmh > rules.LANDING_WIND_ABS_MAX_KMH or lw.gust_kmh > rules.LANDING_GUST_ABS_MAX_KMH:
        out.append(Finding("LANDING_WIND", "Vent à l'atterrissage hors limites",
                           f"{lw.speed_kmh:.0f} km/h, rafales {lw.gust_kmh:.0f} à {landing.name} : no-go.", absolute_nogo=True))  # fmt: skip
    if breeze:
        # VALLEY_BREEZE : info sous 80 % du seuil, caution entre 80 et 100 % (le no-go reste LANDING_WIND)
        ratios = {lv: min(1.0, max(lw.speed_kmh / lw_lim[lv], lw.gust_kmh / lg_lim[lv])) for lv in LEVELS}
        out.append(
            Finding("VALLEY_BREEZE", "Brise de vallée à l'atterrissage",
                    f"Brise de vallée attendue à {landing.name} vers {fmt_hm(end)} : {lw.speed_kmh:.0f} km/h, rafales "
                    f"{lw.gust_kmh:.0f} (×{lw.breeze_factor:.2f} sur le modèle). Approche face à la brise.",
                    ratios=ratios, info=True, band=True)
        )  # fmt: skip
    return out


def regional_wind_findings(site: Site, landing_hour: HourAnalysis) -> list[Finding]:
    out: list[Finding] = []
    v, d = landing_hour.wind_speed_kmh, landing_hour.wind_direction_deg
    for region, sector, name in (("bise", rules.BISE_SECTOR_DEG, "Bise"), ("mistral", rules.MISTRAL_SECTOR_DEG, "Mistral")):
        if _in_region(site.lat, site.lon, region) and _in_sector(d, sector):
            if v >= rules.NOGO["regional_wind_ground_kmh"]:
                out.append(Finding("REGIONAL_WIND", f"{name} forte", f"{name} {v:.0f} km/h en vallée : no-go dans la zone d'influence.",
                                   absolute_nogo=True))  # fmt: skip
            elif v >= rules.REGIONAL_WIND_CAUTION_KMH:
                out.append(Finding("REGIONAL_WIND", f"{name} sensible", f"{name} {v:.0f} km/h en vallée.", caution=True))
    return out


def cloud_precip_findings(
    tl: PointTimeline, ltl: PointTimeline, site: Site, landing: Site, start: datetime, end: datetime
) -> list[Finding]:
    out: list[Finding] = []
    a = tl.at(start)
    alt = site.elevation_m
    # pluie ±1 h au déco + à l'atterro à l'arrivée
    win = tl.between(start - timedelta(hours=1), start + timedelta(hours=1))
    pmax = max([h.precipitation_mm_h for h in win] + [ltl.at(end).precipitation_mm_h])
    if pmax >= rules.NOGO["precip_mm_h"]:
        out.append(Finding("RAIN", "Pluie", f"Précipitations prévues ({pmax:.1f} mm/h) sur le créneau.", absolute_nogo=True))
    elif pmax >= rules.PRECIP_CAUTION_MM_H:
        out.append(Finding("RAIN", "Averses possibles", f"Faibles précipitations possibles ({pmax:.2f} mm/h).", caution=True))
    prev = [h for h in tl.hours if start - timedelta(hours=3) <= h.time < start]
    prev_sum = sum(h.precipitation_mm_h for h in prev)
    if prev_sum >= rules.NOGO["precip_prev_3h_mm"]:
        out.append(Finding("RAIN", "Pluie dans les 3 h précédentes",
                           f"{prev_sum:.1f} mm de pluie dans les 3 h avant le déco : aile mouillée (risque de parachutale), sol froid.",
                           absolute_nogo=True))  # fmt: skip
    # base des nuages / brouillard au déco
    base = a.cloud_base_m
    if base is not None and base < alt + rules.NOGO["cloud_base_min_above_takeoff_m"]:
        out.append(Finding("LOW_CLOUD_BASE", "Base des nuages au déco", f"Base des cumulus vers {base:.0f} m : déco dans ou sous le nuage.",
                           absolute_nogo=True))  # fmt: skip
    elif base is not None and base < alt + rules.CLOUD_BASE_CAUTION_ABOVE_TAKEOFF_M:
        out.append(Finding("LOW_CLOUD_BASE", "Base basse", f"Base des cumulus vers {base:.0f} m : peu de marge au-dessus du déco.",
                           caution=True))  # fmt: skip
    if a.cloud_cover_low_pct >= rules.LOW_CLOUD_NOGO_PCT and (base is None or base < alt + rules.LOW_CLOUD_NOGO_ABOVE_TAKEOFF_M) and a.temperature_c - a.dew_point_c < 4:
        out.append(Finding("LOW_CLOUD_BASE", "Nuages bas", f"Couverture nuageuse basse {a.cloud_cover_low_pct:.0f} % au niveau du déco.",
                           absolute_nogo=True))  # fmt: skip
    if a.temperature_c - a.dew_point_c < rules.SPREAD_T_TD_NOGO_C:
        out.append(Finding("LOW_CLOUD_BASE", "Brouillard au déco", f"T − Td = {a.temperature_c - a.dew_point_c:.1f} °C au déco : brouillard / nuage.",
                           absolute_nogo=True))  # fmt: skip
    la = ltl.at(end)
    if la.temperature_c - la.dew_point_c < rules.SPREAD_T_TD_NOGO_C and la.cloud_cover_low_pct >= rules.LOW_CLOUD_NOGO_PCT:
        out.append(Finding("LOW_CLOUD_BASE", "Stratus / brouillard sur l'atterro",
                           f"Atterro {landing.name} dans le stratus (T − Td = {la.temperature_c - la.dew_point_c:.1f} °C, nuages bas {la.cloud_cover_low_pct:.0f} %).",
                           absolute_nogo=True))  # fmt: skip
    if a.cloud_cover_midhigh_pct >= rules.MIDHIGH_CLOUD_CAUTION_PCT and a.cloud_cover_pct >= 80:
        out.append(Finding("FRONT", "Voile nuageux épais", "Couverture moyenne/haute ≥ 80 % : thermiques coupés, dégradation possible.",
                           caution=True))  # fmt: skip
    return out


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
                               f"CAPE {h.cape_j_kg:.0f} J/kg et LI {li:.0f} vers {fmt_hm(h.time)} : risque d'orage pendant ou juste après le vol.",
                               absolute_nogo=True))  # fmt: skip
            sub = 0.0
            break
    else:
        for h in storm_hours:
            li = h.lifted_index if h.lifted_index is not None else 5.0
            if h.cape_j_kg >= rules.CAPE_CAUTION["cape"] and li <= rules.CAPE_CAUTION["li"]:
                out.append(Finding("THUNDERSTORM", "Instabilité modérée", f"CAPE {h.cape_j_kg:.0f} J/kg, LI {li:.0f} : averses possibles en fin de créneau.",
                                   caution=True))  # fmt: skip
                sub = min(sub, 40.0)
                break
    conv_hours = tl.between(start, end + timedelta(hours=rules.CONVECTIVE_PRECIP_CHECK_AFTER_LANDING_H))
    for h in conv_hours:
        if h.time > end and h.precipitation_mm_h >= rules.NOGO["precip_mm_h"] and h.cape_j_kg >= rules.CAPE_CAUTION["cape"]:
            out.append(Finding("THUNDERSTORM", "Averses orageuses après le vol",
                               f"Précipitations convectives ({h.precipitation_mm_h:.1f} mm/h) vers {fmt_hm(h.time)}, moins de 2 h après l'atterrissage.",
                               absolute_nogo=True))  # fmt: skip
            sub = 0.0
            break
    # surdéveloppement (§4.6 + lot 2.6)
    od = cw.overdevelopment_time
    if cw.overdevelopment_risk == "high":
        if od is not None and end > od:
            out.append(Finding("OVERDEVELOPMENT", "Vol après l'heure de surdéveloppement",
                               f"Surdéveloppement attendu vers {fmt_hm(od)} : le vol se termine trop tard.", absolute_nogo=True))  # fmt: skip
            sub = 0.0
        else:
            out.append(Finding("OVERDEVELOPMENT", "Journée à surdéveloppement",
                               f"Risque de surdéveloppement élevé{(' vers ' + fmt_hm(od)) if od else ''} : vols du matin courts uniquement.",
                               caution=True))  # fmt: skip
            sub = min(sub, 35.0)
    elif cw.overdevelopment_risk == "moderate":
        if od is not None and start <= od <= end + timedelta(hours=rules.OVERDEV_MODERATE_WINDOW_AFTER_LANDING_H):
            out.append(Finding("OVERDEVELOPMENT", "Surdéveloppement possible",
                               f"Surdéveloppement possible vers {fmt_hm(od)} : être posé au plus tard 1 h avant.", caution=True))  # fmt: skip
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


def _landing_caps(td: TakeoffData, start: datetime, thermal: bool) -> tuple[datetime, str]:
    caps: list[tuple[datetime, str]] = []
    if td.sunset:
        caps.append((td.sunset, "coucher du soleil"))
    if thermal:
        if td.cw.end is not None:
            caps.append((td.cw.end + timedelta(minutes=rules.XC_LANDING_AFTER_CONVECTION_END_MIN), "fin des thermiques"))
        if td.sunset:
            caps.append((td.sunset - timedelta(minutes=rules.LANDING_BEFORE_SUNSET_MIN), "30 min avant le coucher du soleil"))
    od = td.cw.overdevelopment_time
    if od is not None and td.cw.overdevelopment_risk != "low":
        caps.append((od - timedelta(hours=rules.OVERDEV_MODERATE_END_BEFORE_H), "surdéveloppement attendu 1 h plus tard"))
    a = td.tl.at(start)
    li = a.lifted_index if a.lifted_index is not None else 5.0
    if thermal and a.cape_j_kg >= rules.CAPE_CAUTION["cape"] and li <= rules.CAPE_CAUTION["li"] and td.cw.overdevelopment_risk == "low":
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
) -> Candidate | str:
    """Renvoie un Candidate (évalué pour tous les niveaux) ou une raison d'infaisabilité « [CODE] … »."""
    site, landing = td.site, td.landing
    level = filters.difficulty
    wing = filters.wing_glide_ratio
    tw = takeoff_wind(ctx, site, td.tl, start)
    a = tw.hour
    alt = site.elevation_m
    usable = _usable_capped(a)
    vario = a.thermal_strength_ms
    sh = solar_hour(start, site.lon)
    # jour aéronautique
    if td.sunrise and start < td.sunrise:
        return _codes_prefix("SUNSET", f"Décollage avant le lever du soleil ({fmt_hm(td.sunrise)}).")
    if td.sunset and start >= td.sunset:
        return _codes_prefix("SUNSET", f"Décollage après le coucher du soleil ({fmt_hm(td.sunset)}) : le vol libre se pratique de jour.")
    thermal_variant = variant in ("local_thermal", "xc")
    cap, cap_reason = _landing_caps(td, start, thermal_variant)
    avail_min = (cap - start).total_seconds() / 60.0
    drop = alt - landing.elevation_m
    plouf_min = max(0.0, drop) / (rules.SINK_RATE_MS["calm"] * 60.0) + rules.PLOUF_EXTRA_MIN
    glide_wind = vector_mean([(tw.speed_kmh, tw.direction_deg), (td.ltl.at(start).wind_speed_kmh, td.ltl.at(start).wind_direction_deg)])
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
            if not td.sunset or not (td.sunset - timedelta(hours=rules.RESTITUTION_BEFORE_SUNSET_H) <= start < td.sunset):
                return "Hors créneau de restitution"
            if not any(o in rules.RESTITUTION_FACES for o in site.orientations):
                return "Face non orientée pour la restitution"
            dur = max(0.0, drop) / (rules.SINK_RATE_MS["evening"] * 60.0) * rules.RESTITUTION_DURATION_FACTOR / 1.0
            dur = min(dur, (td.sunset - start).total_seconds() / 60.0 - 5)
            thermal_usage = "optional"
        if dur > filters.duration_max_minutes + 0.5:
            return _codes_prefix("WEAK_THERMALS", f"La descente seule dure ~{dur:.0f} min, plus que la durée max demandée.")
        if dur < filters.duration_min_minutes:
            duration_note = (
                f"Seul un plouf d'environ {dur:.0f} min est possible"
                + (" avant le coucher du soleil" if td.sunset and (td.sunset - start) < timedelta(hours=2) else " (pas de thermique exploitable)")
                + f" : plus court que les {filters.duration_min_minutes:.0f} min demandées."
            )
        lw_hour = td.ltl.at(start + timedelta(minutes=dur))
        route = build_plouf(ctx, site, landing, td.alternates, level, wing, glide_wind,
                            (lw_hour.wind_speed_kmh, lw_hour.wind_direction_deg), dur)  # fmt: skip
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
            if not (rules.RIDGE_MIN_KMH_BY_LEVEL[level] <= twx.speed_kmh <= rules.RIDGE["max_kmh"][level] * 1.05) or twx.angle.category == "tail":
                break
            persist += 60.0
            t += timedelta(hours=1)
        persist = max(persist, 30.0 if rules.RIDGE_MIN_KMH_BY_LEVEL[level] <= tw.speed_kmh else 0.0)
        dur = min(filters.duration_max_minutes, persist, rules.RIDGE_MAX_DURATION_MIN[level], avail_min)
        feas.append(Finding("WEAK_THERMALS", "Vent de soaring", f"Vent de face {tw.speed_kmh:.0f} km/h pour tenir en dynamique.",
                            value=tw.speed_kmh, limits={lv: float(rules.RIDGE_MIN_KMH_BY_LEVEL[lv]) for lv in LEVELS},
                            kind="min", feasibility=True, band=False, blocks_go=False))  # fmt: skip
        if dur < 15:
            return _codes_prefix("WEAK_THERMALS", "Vent de soaring trop peu durable.")
        if dur < filters.duration_min_minutes:
            duration_note = f"Le vent de soaring ne tient que ~{dur:.0f} min : plus court que demandé."
        route = build_ridge(ctx, site, landing, td.alternates, level, wing, glide_wind, tw.direction_deg, dur, td.top_landing)
        max_alt = route.max_altitude_m
    elif variant == "local_thermal":
        if vario < rules.THERMAL_USABLE_MIN_MS:
            return _codes_prefix("WEAK_THERMALS", f"Thermiques non exploitables à {fmt_hm(start)} ({vario:.1f} m/s).")
        feas.append(Finding("WEAK_THERMALS", "Plafond utile", f"Plafond utile {usable:.0f} m ({usable - alt:.0f} m au-dessus du déco).",
                            value=usable - alt, limits={lv: float(x) for lv, x in rules.LOCAL_CEILING_MIN_ABOVE_TAKEOFF_M.items()},
                            kind="min", feasibility=True, band=False, blocks_go=False))  # fmt: skip
        max_d = min(filters.duration_max_minutes, avail_min, float(rules.MAX_DURATION_MIN[level]))
        if level == "beginner":
            max_d = min(max_d, rules.LOCAL_THERMAL_BEGINNER_MAX_MIN)
        if td.cw.overdevelopment_risk == "high":
            max_d = min(max_d, rules.OVERDEV_HIGH_MAX_DURATION_MIN)
        realism_cap = None
        for vmax, cap_min in rules.LOCAL_THERMAL_DURATION_CAPS:
            if vario < vmax:
                realism_cap = cap_min
                break
        if usable - alt < rules.LOCAL_THERMAL_LOW_CEILING_M:
            realism_cap = min(realism_cap or 1e9, rules.LOCAL_THERMAL_LOW_CEILING_MAX_MIN)
        if realism_cap is not None and realism_cap < max_d:
            max_d = realism_cap
            cap_reason = f"thermiques {vario:.1f} m/s, plafond utile {usable - alt:.0f} m au-dessus du déco"
        if max_d < plouf_min + 10:
            return _codes_prefix("WEAK_THERMALS", f"Fenêtre thermique trop courte après {fmt_hm(start)} ({cap_reason}).")
        dur = max_d
        if dur < filters.duration_min_minutes:
            duration_note = f"Vol limité à ~{dur:.0f} min ({cap_reason}) : plus court que demandé."
        max_alt = usable
        thermal_usage = "essential" if dur > plouf_min * 1.5 else "optional"
        layer = a.profile.mean_wind(alt, max(alt + 200, usable))
        route = build_local_thermal(ctx, proj, site, landing, td.alternates, level, wing, glide_wind, layer, start, dur, usable, max_alt)
    elif variant == "xc":
        if vario < rules.THERMAL_USABLE_MIN_MS:
            return _codes_prefix("WEAK_THERMALS", f"Thermiques insuffisants pour un cross à {fmt_hm(start)}.")
        xc_min = rules.XC_CEILING_MIN_ABOVE_TAKEOFF_M
        feas.append(Finding("WEAK_THERMALS", "Plafond pour le cross", f"Plafond utile {usable - alt:.0f} m au-dessus du déco.",
                            value=usable - alt, limits={lv: (None if x is None else float(x)) for lv, x in xc_min.items()},
                            kind="min", feasibility=True, band=False, blocks_go=False))  # fmt: skip
        if xc_min[level] is None or usable - alt < xc_min[level]:
            return _codes_prefix("WEAK_THERMALS", f"Plafond utile trop bas pour un cross ({usable - alt:.0f} m au-dessus du déco).")
        budget = min(filters.duration_max_minutes, avail_min, float(rules.MAX_DURATION_MIN[level]))
        if td.cw.overdevelopment_risk == "high":
            if level != "expert":
                return _codes_prefix("OVERDEVELOPMENT", "Journée à surdéveloppement : pas de cross (sauf expert, retour avant 13h solaire).")
            back = start + timedelta(hours=rules.OVERDEV_HIGH_EXPERT_RETURN_SOLAR_H - sh)
            budget = min(budget, (back - start).total_seconds() / 60.0, rules.OVERDEV_HIGH_MAX_DURATION_MIN)
        if budget < rules.XC_MIN_DURATION_MIN:
            return _codes_prefix("WEAK_THERMALS", f"Fenêtre trop courte pour un cross ({budget:.0f} min, {cap_reason}).")
        layer = a.profile.mean_wind(alt, usable)
        xc, why = build_cross(ctx, proj, site, landing, td.landings_pool, level, wing, layer, start, budget, usable, usable, vario)
        if xc is None:
            return why or "Cross impossible"
        route = xc.route
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

    end = start + timedelta(minutes=dur)
    lw = landing_wind(td.ltl, end, td.big_valley)
    findings: list[Finding] = list(td.site_findings) + feas
    ridge = variant == "ridge"
    findings += takeoff_wind_findings(tw, site, ridge, sh)
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
        return _codes_prefix("STRONG_THERMALS", f"Thermiques {vario_max:.1f} m/s pendant le créneau : incompatible avec « sans thermiques ».")
    if filters.thermals == "required" and thermal_usage == "none":
        return _codes_prefix("WEAK_THERMALS", "Vol sans thermique alors que tu veux des thermiques.")
    if filters.thermals == "required" and vario < 1.0:
        findings.append(Finding("WEAK_THERMALS", "Thermiques faibles", "Thermiques faibles, vol local court probable.", info=True))
    # froid / gel
    if thermal_variant and a.freezing_level_m is not None and a.freezing_level_m < max_alt:
        t_ceiling = a.profile.temperature(max_alt)
        findings.append(Finding("FREEZING", "Isotherme 0 °C sous le plafond",
                                f"Isotherme 0 °C vers {a.freezing_level_m:.0f} m, {t_ceiling:.0f} °C au plafond : onglée, givre sur les instruments.",
                                caution=True))  # fmt: skip
        findings.append(Finding("FREEZING", "Froid au plafond", f"{t_ceiling:.0f} °C au plafond.", value=-t_ceiling,
                                limits={"beginner": -rules.COLD_AT_CEILING_BEGINNER_C, "intermediate": 99.0, "advanced": 99.0, "expert": 99.0},
                                band=False))  # fmt: skip
    inv = _inversion(a, alt)
    if inv is not None:
        findings.append(Finding("INVERSION", "Inversion", f"Inversion vers {inv:.0f} m : thermiques bloqués en dessous, turbulence au passage.",
                                info=True))  # fmt: skip
    # atterrissage à l'heure d'arrivée (en top landing : même vent que le déco, déjà contrôlé — lot 6.8)
    top_ldg = ridge and td.top_landing
    if not top_ldg:
        findings += landing_findings(lw, landing, end)
    # finesse (par niveau)
    glide_ratios: dict[str, float] = {}
    glide_by_level: dict[str, GlideCheck] = {}
    for lv in LEVELS:
        g = _route_glide(ctx, td, route, lv, wing, glide_wind)
        glide_by_level[lv] = g
        glide_ratios[lv] = g.ratio if not (top_ldg or variant == "plouf" and td.top_landing) else 0.0
    if not top_ldg:
        g = glide_by_level[level]
        txt = (f"Finesse requise {g.required_ratio:.1f} vers {g.landing_name or landing.name} pour {g.available_ratio:.1f} disponible "
               f"(finesse de calcul sol, vent compris)") + ("" if g.terrain_ok else " ; le relief coupe la ligne de plané")
        findings.append(Finding("GLIDE_MARGIN", "Marge de finesse", txt + ".", criterion="landing", ratios=glide_ratios,
                                band_start=rules.GLIDE_CAUTION_RATIO, curve=glide_subscore))  # fmt: skip
    # coucher du soleil
    if td.sunset:
        if end > td.sunset:
            findings.append(Finding("SUNSET", "Atterrissage après le coucher du soleil", f"Atterrissage estimé {fmt_hm(end)}, coucher {fmt_hm(td.sunset)}.",
                                    absolute_nogo=True))  # fmt: skip
        elif end > td.sunset - timedelta(minutes=rules.LANDING_BEFORE_SUNSET_MIN):
            findings.append(Finding("SUNSET", "Atterrissage proche du coucher du soleil",
                                    f"Atterrissage estimé {fmt_hm(end)}, coucher du soleil {fmt_hm(td.sunset)} : pas de marge.",
                                    caution=True))  # fmt: skip
    # espaces aériens + zones sensibles (route 3D)
    min_alt = min(landing.elevation_m, alt)
    flight_coords = route.coords
    asp = evaluate_airspaces(ctx, proj, flight_coords, min_alt, max_alt)
    if asp.altitude_cap_m is not None and asp.altitude_cap_m < max_alt:
        max_alt = max(alt, asp.altitude_cap_m)
        findings.append(Finding("ALTITUDE_LIMIT", "Plafond limité par un espace aérien",
                                f"Altitude max limitée à {max_alt:.0f} m (plancher d'un espace aérien − 100 m).", caution=True, blocks_go=False))  # fmt: skip
        asp = evaluate_airspaces(ctx, proj, flight_coords, min_alt, max_alt)
    findings += asp.findings
    if thermal_variant and a.usable_ceiling_m > rules.FL115_M_STANDARD - rules.CEILING_MARGIN_BELOW_AIRSPACE_M:
        findings.append(Finding("ALTITUDE_LIMIT", "Plafond au-dessus du FL115",
                                f"Plafond utile ~{a.usable_ceiling_m:.0f} m : rester sous le FL115 (≈ {rules.FL115_M_STANDARD:.0f} m QNH 1013), altitude retenue {max_alt:.0f} m.",
                                caution=True, blocks_go=False))  # fmt: skip
    findings += evaluate_sensitive_route(ctx, proj, [(c[0], c[1], max_alt if i not in (0, len(flight_coords) - 1) else c[2]) for i, c in enumerate(flight_coords)], site, landing)

    cand = Candidate(
        variant=variant, takeoff=site, landing=landing, alternates=td.alternates, start=start, duration_min=round(dur, 1),
        route=route, findings=findings, takeoff_wind=tw, landing_wind=lw, convection=td.cw, vario=vario, usable=usable,
        max_alt=max_alt, thermal_usage=thermal_usage, horizon=ctx.horizon, level=level, mock=ctx.mock,
        sunrise=td.sunrise, sunset=td.sunset, latest_landing=cap, landing_cap_reason=cap_reason, duration_note=duration_note,
        airspace=asp,
    )  # fmt: skip
    cand.airspaces = asp.warnings
    cand.score_items = [conv_sub]  # temporaire : sous-score convectif transmis à finalize()
    route.glide = glide_by_level[level] if not top_ldg else route.glide
    return cand


def _route_glide(ctx: DataContext, td: TakeoffData, route: Route, level: str, wing: float, wind: tuple[float, float]) -> GlideCheck:
    """Pire cas (lot 6.11) : (a) déco → atterro principal à l'altitude du déco ; (b) chaque point de route à
    son altitude de point bas → meilleur atterro identifié."""
    g = glide_to(ctx, td.site.lat, td.site.lon, td.site.elevation_m, td.landing, level, wing, wind)
    if route.kind == "xc":
        if route.glide.ratio > g.ratio:
            g = route.glide
        return g
    if route.kind == "local_thermal":
        for w in route.waypoints:
            if w.type != "thermal_trigger":
                continue
            best = None
            for ldg in [td.landing, *td.alternates]:
                gg = glide_to(ctx, w.lat, w.lon, max(td.site.elevation_m, w.altitude_m - 150.0), ldg, level, wing, wind)
                if best is None or gg.ratio < best.ratio:
                    best = gg
            if best is not None and best.ratio > g.ratio:
                g = best
    return g


def _inversion(a: HourAnalysis, alt: float) -> float | None:
    pts = [p for p in a.profile.points if alt + 100 <= p.z <= 3500]
    for p, q in zip(pts, pts[1:], strict=False):
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
    model_winds = tl.model_winds.get(min(tl.model_winds, key=lambda x: abs((x - t).total_seconds()))) if tl.model_winds else []
    nc = cand.takeoff_wind.nowcast
    coherent = None if nc is None else (True if nc.coherent else (False if nc.mismatch else None))
    disp, beacon, sig_v, sig_d = confidence_factors(model_winds or [], coherent)
    conf_raw = compute_confidence(ctx.horizon, disp, beacon)
    cand.conf_raw = conf_raw
    cand.confidence = min(conf_raw, rules.MOCK_CONFIDENCE_CAP) if ctx.mock else conf_raw
    base = rules.HORIZON_BASE_CONFIDENCE[ctx.horizon]
    if conf_raw < rules.VERDICT["go_min_confidence_ratio"] * base:
        why = f"dispersion des modèles (σ vent {sig_v:.0f} km/h" + (f", σ direction {sig_d:.0f}°" if sig_d else "") + ")"
        if beacon < 1:
            why += ", balises en désaccord"
        findings.append(Finding("LOW_CONFIDENCE", "Prévision incertaine", f"Confiance {conf_raw * 100:.0f} % : {why}.", caution=True))
    if nc is not None and nc.mismatch:
        findings.append(Finding("BEACON_MISMATCH", "Balises en désaccord avec la prévision",
                                "Les balises contredisent le modèle : " + " ; ".join(nc.details[:2]) + ". On suit la balise pour les 2 prochaines heures.",
                                caution=True))  # fmt: skip
    stale = [b for b in ctx.beacons if b.stale and haversine_km(b.lat, b.lon, cand.takeoff.lat, cand.takeoff.lon) <= rules.BEACON_MAX_DISTANCE_KM]
    if stale and ctx.horizon in ("30m", "1h", "2h"):
        findings.append(Finding("STALE_BEACONS", "Balises anciennes", "Mesure > 30 min ignorée : " + ", ".join(b.name for b in stale[:3]) + ".", info=True))
    # une source no-go (lot 4.3)
    sp = tl.spreads.get(min(tl.spreads, key=lambda x: abs((x - t).total_seconds()))) if tl.spreads else None
    if sp is not None and sp.n_models >= 2:
        a = cand.takeoff_wind.hour
        scale = cand.takeoff_wind.model_speed_kmh / a.wind_speed_kmh if a.wind_speed_kmh > 1 else 1.0
        msgs = []
        if sp.gust_max_kmh * scale > rules.TAKEOFF_GUST_MAX_KMH[level]:
            msgs.append(("TAKEOFF_GUSTS", f"au moins un modèle prévoit {sp.gust_max_kmh * scale:.0f} km/h de rafales au déco"))
        if sp.precip_max_mm_h >= rules.NOGO["precip_mm_h"]:
            msgs.append(("RAIN", f"au moins un modèle prévoit {sp.precip_max_mm_h:.1f} mm/h de pluie"))
        if sp.cape_max_j_kg >= rules.NOGO["cape_storm"]["cape"] and (sp.li_min is None or sp.li_min <= rules.NOGO["cape_storm"]["li"]):
            msgs.append(("THUNDERSTORM", f"au moins un modèle prévoit une CAPE de {sp.cape_max_j_kg:.0f} J/kg"))
        for code, m in msgs:
            findings.append(Finding(code, "Un modèle prévoit un no-go", m[0].upper() + m[1:] + ".", caution=True,
                                    blocks_go=conf_raw < rules.SINGLE_SOURCE_NOGO_CONFIDENCE))  # fmt: skip
    if ctx.mock:
        findings.append(Finding("MOCK_DATA", "Données synthétiques", "Plan calculé sur des données SYNTHÉTIQUES (démo hors-ligne) : ne pas utiliser pour voler.",
                                caution=True, blocks_go=False))  # fmt: skip
    if ctx.horizon in ("30m", "1h") and cand.takeoff.access:
        findings.append(Finding("ACCESS_TIME", "Temps d'accès au déco", f"Vérifie que tu peux être au déco à temps : {cand.takeoff.access}",
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
                    reasons.append(_codes_prefix(f.code, f"{f.detail} Conditions trop fortes pour ton niveau (OK pour {label})."))
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
    vario_flight = cand.vario
    th_s, th_c = thermal_match_subscore(filters.thermals, vario_flight, cand.thermal_usage != "none", level)
    if filters.thermals == "required" and cand.variant == "xc" and cand.vario > rules.THERMAL_MAX_MS[level] * rules.MARGINAL_BAND:
        th_c += " (zone de vigilance de ton niveau)"
    du_s, du_c = duration_subscore(cand.duration_min, filters.duration_min_minutes, filters.duration_max_minutes)
    conf_s = linear(conf_raw, 0.3, 0.0, 0.9, 100.0)
    site_s = 100.0 if cand.takeoff.status == "open" else 60.0
    if rules.level_index(site_lvl) == rules.level_index(level):
        site_s = min(site_s, 85.0)
    asp_s = 100.0
    if cand.airspace and any(f.code in ("AIRSPACE", "AIRSPACE_ACTIVATION") and (f.caution or f.absolute_nogo) for f in cand.airspace.findings):
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
    if g.required_ratio > 0:
        extra["landing"] = (glide_subscore(g.ratio), f"finesse requise {g.required_ratio:.1f} / {g.available_ratio:.1f}")
    sr = aggregate_score(level, findings, extra)
    risks = _risks(findings, level)
    blocking = any(
        r.level == "caution" and r.code not in NON_BLOCKING_CAUTIONS and _blocks(findings, r, level) for r in risks
    )
    v = verdict(sr, risks, blocking, conf_raw, ctx.horizon)
    if v == "no_go":
        weak = sr.weakest_safety
        cand.reject_reasons = [
            _codes_prefix(CRITERION_RISK_CODE[weak],
                          f"Score global insuffisant ({sr.score:.0f}/100) : point faible = {CRITERION_LABEL_FR[weak].lower()}.")
        ]  # fmt: skip
        cand.flyability = "no_go"
        cand.risks = risks
        return cand
    if v == "marginal" and not any(r.level == "caution" and r.code != "MOCK_DATA" for r in risks):
        weak = min(rules.WEIGHTS, key=lambda c: sr.subscores.get(c, 100.0))
        risks.append(Risk(code=CRITERION_RISK_CODE[weak], level="caution", title=f"{CRITERION_LABEL_FR[weak]} limite",
                          detail=f"Critère « {CRITERION_LABEL_FR[weak]} » à {sr.subscores[weak]:.0f}/100 : conditions moyennes."))  # fmt: skip
    cand.flyability = v
    cand.score = sr.score
    cand.raw_score = sr.raw_score
    cand.score_items = sr.items
    cand.risks = risks
    return cand


def _only_strong_thermals(cand: Candidate) -> bool:
    codes = {r.split("]")[0].strip("[") for r in cand.reject_reasons}
    return codes == {"STRONG_THERMALS"} or codes <= {"STRONG_THERMALS", "LANDING_WIND", "VALLEY_BREEZE"} and "STRONG_THERMALS" in codes


def _blocks(findings: list[Finding], risk: Risk, level: str) -> bool:
    for f in findings:
        if f.code == risk.code and f.risk_level(level) == "caution":
            if f.blocks_go:
                return True
    return False


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
    assoc = [ctx.landings[i] for i in site.associated_landing_ids if i in ctx.landings]
    meta = ctx.site_meta.get(site.id)
    if not assoc and meta and meta.top_landing:
        assoc = [site]
    if not assoc:
        return None, [], []
    main = assoc[0]
    alternates = [x for x in assoc[1:] if x.id != main.id]
    pool = list(assoc)
    for ldg in ctx.landings.values():
        if ldg.id in {x.id for x in pool}:
            continue
        d = haversine_km(site.lat, site.lon, ldg.lat, ldg.lon)
        if d <= 40.0 and ldg.elevation_m < site.elevation_m:
            pool.append(ldg)
            if d <= rules.ALTERNATE_LANDING_SEARCH_KM and len(alternates) < 3 and ldg.id != main.id:
                alternates.append(ldg)
    return main, alternates, pool


def _big_valley(ctx: DataContext, landing: Site) -> bool:
    meta = ctx.site_meta.get(landing.id)
    if meta and meta.big_valley is not None:
        return meta.big_valley
    if landing.elevation_m >= rules.BIG_VALLEY_MAX_FLOOR_M:
        return False
    if ctx.terrain is not None:
        from app.geo import destination

        for brg in range(0, 360, 30):
            for r in (5.0, rules.BIG_VALLEY_RADIUS_KM):
                la, lo = destination(landing.lat, landing.lon, brg, r)
                e = ctx.terrain_at(la, lo)
                if e is not None and e >= rules.BIG_VALLEY_MIN_RELIEF_M:
                    return True
        return False
    return any(
        s.elevation_m > rules.BIG_VALLEY_FALLBACK_TAKEOFF_M
        and haversine_km(s.lat, s.lon, landing.lat, landing.lon) <= rules.BIG_VALLEY_FALLBACK_RADIUS_KM
        for s in ctx.takeoffs
    )


def _site_findings(ctx: DataContext, site: Site, landing: Site, proj: Projector) -> list[Finding]:
    out: list[Finding] = []
    if site.status == "closed":
        out.append(Finding("SITE_CLOSED", "Site fermé", site.restrictions or "Site signalé fermé par la source.", absolute_nogo=True))
    elif site.status == "restricted":
        out.append(Finding("SITE_RESTRICTED", "Site soumis à restrictions", site.restrictions or "Site à accès restreint : se renseigner.",
                           caution=True))  # fmt: skip
    out += evaluate_sensitive_sites(ctx, proj, site, landing)
    return out


def candidate_starts(ctx: DataContext, td: TakeoffData, variant: str, level: str) -> list[datetime]:
    t0 = ctx.target_time
    base = [t0, t0 - timedelta(minutes=rules.WINDOW_START_BEFORE_TARGET_MIN)]
    base += [t0 + timedelta(hours=h) for h in range(1, int(rules.WINDOW_START_AFTER_TARGET_H) + 1)]
    lo = t0 - timedelta(minutes=rules.WINDOW_START_BEFORE_TARGET_MIN)
    hi = t0 + timedelta(hours=rules.WINDOW_START_AFTER_TARGET_H)
    extra: list[datetime] = []
    cw = td.cw
    if variant in ("local_thermal", "xc") and cw.start is not None:
        extra.append(cw.start)
        extra.append(cw.start + timedelta(minutes=30))
    if level == "beginner" and cw.start is not None:
        extra.append(cw.start + timedelta(minutes=30))
    starts = base + [e for e in extra if lo <= e <= hi]
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
    if not site.orientations:
        return [], [_codes_prefix("TAKEOFF_WIND", "Orientation du déco inconnue : impossible de juger le vent (site visible sur la carte seulement).")]
    landing, alternates, pool = _landing_setup(ctx, site)
    if landing is None:
        return [], [_codes_prefix("GLIDE_MARGIN", "Aucun atterrissage identifié associé à ce déco.")]
    tl = ctx.timelines.get(site.id)
    ltl = ctx.timelines.get(landing.id) or tl
    if tl is None:
        return [], ["Prévision météo indisponible pour ce site."]
    meta = ctx.site_meta.get(landing.id)
    top_landing = (landing.elevation_m >= site.elevation_m - rules.TOP_LANDING_MAX_DROP_M) or bool(meta and meta.top_landing)
    proj = Projector(site.lat, site.lon)
    rise, sset = sun_times(ctx.target_time, site.lat, site.lon)
    day_hours = [h for h in tl.hours if abs((h.time - ctx.target_time).total_seconds()) <= 16 * 3600]
    cw = convection_window(sorted(day_hours, key=lambda h: h.time), rise, sset)
    td = TakeoffData(
        site=site, tl=tl, landing=landing, ltl=ltl, alternates=alternates if not top_landing else [x for x in pool if x.id != landing.id][:2],
        landings_pool=pool, big_valley=_big_valley(ctx, landing), top_landing=top_landing, cw=cw, sunrise=rise, sunset=sset,
        site_findings=_site_findings(ctx, site, landing, proj),
    )  # fmt: skip
    if top_landing:
        # le plouf / local nécessitent un atterro en contrebas : on prend le premier atterro de secours
        lower = [x for x in pool if x.elevation_m < site.elevation_m - rules.TOP_LANDING_MAX_DROP_M]
        td.landings_pool = lower
    accepted: list[Candidate] = []
    reasons_first: list[str] = []
    for variant in variants_for(site, filters, top_landing):
        vt = td
        if variant == "restitution" and not (
            sset and sset - timedelta(hours=rules.RESTITUTION_BEFORE_SUNSET_H) <= ctx.target_time < sset
        ):
            continue  # la restitution n'est proposée que si l'heure cible tombe dans son créneau
        site_meta = ctx.site_meta.get(site.id)
        if variant == "ridge" and not top_landing and (site.kind == "both" or (site_meta and site_meta.top_landing)):
            # lot 3.2 : le déco sert de top landing, l'atterro en contrebas devient le secours
            vt = TakeoffData(**{**td.__dict__, "landing": site, "ltl": tl, "alternates": [landing, *alternates][:2],
                                "top_landing": True, "big_valley": False})  # fmt: skip
        elif variant != "ridge" and top_landing:
            lower = td.landings_pool
            if not lower:
                continue
            vt = TakeoffData(**{**td.__dict__, "landing": lower[0], "ltl": ctx.timelines.get(lower[0].id) or tl,
                                "alternates": lower[1:3], "top_landing": False, "big_valley": _big_valley(ctx, lower[0])})  # fmt: skip
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
                # un no-go météo à l'heure cible reste un no-go (lot 2.9) ; seule exception : la règle
                # « élève hors pic thermique » (1.12) autorise un autre créneau dans [cible − 30 min, cible + 3 h]
                if level == "beginner" and _only_strong_thermals(cand):
                    continue
                break
            _compute_window(ctx, vt, cand, filters)
            accepted.append(cand)
            break
        if not any(c.variant == variant for c in accepted) and first_reasons:
            reasons_first += first_reasons
    # lot 6.3 : le plouf n'est « seul possible » que si aucune variante thermique n'est faisable
    if any(c.thermal_usage != "none" and c.variant in ("local_thermal", "xc") for c in accepted):
        for c in accepted:
            if c.variant == "plouf":
                c.duration_note = f"Variante sans thermique : plouf direct de ~{c.duration_min:.0f} min (plan B si ça ne monte pas)."
    return accepted, list(dict.fromkeys(reasons_first))


def _wind_ratio_at(ctx: DataContext, td: TakeoffData, cand: Candidate, t: datetime, level: str) -> tuple[float, bool]:
    """(ratio max vent/seuil au déco à t et à l'atterro à t + durée, no-go ?)."""
    ridge = cand.variant == "ridge"
    tw = takeoff_wind(ctx, td.site, td.tl, t)
    wl = rules.RIDGE["max_kmh"][level] if ridge else rules.TAKEOFF_WIND_MAX_KMH[level]
    gl = rules.RIDGE_GUST_MAX_KMH[level] if ridge else rules.TAKEOFF_GUST_MAX_KMH[level]
    r = max(tw.speed_kmh / wl, tw.gust_kmh / gl)
    if not (ridge and td.top_landing):
        lw = landing_wind(td.ltl, t + timedelta(minutes=cand.duration_min), td.big_valley)
        r = max(r, lw.speed_kmh / rules.LANDING_WIND_MAX_KMH[level], lw.gust_kmh / rules.LANDING_GUST_MAX_KMH[level])
    wet = td.tl.at(t).precipitation_mm_h >= rules.NOGO["precip_mm_h"]
    tail = tw.angle.category == "tail" and tw.speed_kmh > rules.TAILWIND_MAX_KMH[level]
    return r, (r > 1.0 or wet or tail)


def _compute_window(ctx: DataContext, td: TakeoffData, cand: Candidate, filters: PlanFilters) -> None:
    """Fin du créneau (lot 6.7) : on coupe avant la première heure qui ferait passer le plan en no-go
    (vent / rafales au déco, vent à l'atterro à l'arrivée, pluie) ; WIND_INCREASING si le vent entre
    dans la bande 80-100 % alors qu'il en était hors au départ."""
    level = filters.difficulty
    start = cand.start
    latest_start = cand.latest_landing - timedelta(minutes=cand.duration_min)
    hard_end = min(latest_start, start + timedelta(hours=rules.WINDOW_START_AFTER_TARGET_H))
    if cand.variant in ("plouf", "restitution") and cand.sunset:
        hard_end = min(hard_end, cand.sunset - timedelta(minutes=cand.duration_min))
    r0, _ = _wind_ratio_at(ctx, td, cand, start, level)
    end = start
    t = start + timedelta(minutes=30)
    increasing_at: datetime | None = None
    while t <= hard_end:
        r, nogo = _wind_ratio_at(ctx, td, cand, t, level)
        if nogo:
            break
        if increasing_at is None and r0 < rules.MARGINAL_BAND <= r:
            increasing_at = t
        end = t
        t += timedelta(minutes=30)
    cand.window_start = start
    cand.window_end = max(end, start + timedelta(minutes=15)) if end > start else start + timedelta(minutes=15)
    if increasing_at is not None:
        cand.risks.append(
            Risk(code="WIND_INCREASING", level="caution", title="Le vent forcit",
                 detail=f"Le vent forcit à partir de {fmt_hm(increasing_at)} (proche des limites de ton niveau) : décoller tôt dans le créneau.")
        )  # fmt: skip


# =============================================================================================
# Construction des FlightPlan et classement
# =============================================================================================
def _plan_id(ctx: DataContext, cand: Candidate) -> str:
    raw = f"{cand.takeoff.id}|{cand.variant}|{cand.start.isoformat()}|{ctx.reference_time.isoformat()}|{cand.level}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _window_end(ctx: DataContext, td_tl: PointTimeline, cand: Candidate) -> datetime:
    latest_start = cand.latest_landing - timedelta(minutes=cand.duration_min)
    end = max(cand.start + timedelta(minutes=15), min(latest_start, cand.start + timedelta(hours=3)))
    if cand.variant in ("plouf", "restitution") and cand.sunset:
        end = min(end, cand.sunset - timedelta(minutes=cand.duration_min))
    return max(end, cand.start)


def to_flight_plan(ctx: DataContext, cand: Candidate, rank: int, sources) -> FlightPlan:
    tl = ctx.timelines[cand.takeoff.id]
    ltl = ctx.timelines.get(cand.landing.id) or tl
    tw = cand.takeoff_wind
    nc = None
    if tw.nowcast is not None:
        nc = NowcastCorrection(
            beacon_ids=tw.nowcast.beacon_ids,
            wind_speed_bias_kmh=round(tw.nowcast.weight * tw.nowcast.speed_bias_kmh, 1),
            wind_direction_bias_deg=round(tw.nowcast.weight * tw.nowcast.dir_bias_deg, 0),
        )
    snap_to = snapshot_from_analysis(tw.hour, tl.model_label, (tw.speed_kmh, tw.direction_deg, tw.gust_kmh), nc)
    lw = cand.landing_wind
    snap_ldg = snapshot_from_analysis(lw.hour, ltl.model_label, (lw.speed_kmh, lw.direction_deg, lw.gust_kmh))
    timeline = []
    for h in tl.hours:
        if abs((h.time - cand.start).total_seconds()) <= 3 * 3600 + 1:
            twx = takeoff_wind(ctx, cand.takeoff, tl, h.time)
            timeline.append(snapshot_from_analysis(h, tl.model_label, (twx.speed_kmh, twx.direction_deg, twx.gust_kmh)))
    cw = cand.convection
    od = cw.overdevelopment_risk
    th_comment = (
        f"Thermiques {cand.vario:.1f} m/s, plafond utile {cand.usable:.0f} m"
        + (f", cumulus base {tw.hour.cloud_base_m:.0f} m" if tw.hour.cloud_base_m else ", thermiques bleus")
        + f", surdéveloppement {dict(low='faible', moderate='modéré', high='élevé')[od]}."
    )
    thermals = ThermalAnalysis(
        convection_start=iso(cw.start) if cw.start else None,
        convection_end=iso(cw.end) if cw.end else None,
        peak_time=iso(cw.peak) if cw.peak else None,
        peak_strength_ms=round(cw.peak_strength_ms, 1),
        ceiling_m=round(min(cand.usable, cand.max_alt if cand.thermal_usage != "none" else cand.usable)),
        cumulus=tw.hour.cumulus,
        overdevelopment_risk=od,
        comment=th_comment,
    )
    beacons_nearby: list[Beacon] = [
        b for b in ctx.beacons if haversine_km(b.lat, b.lon, cand.takeoff.lat, cand.takeoff.lon) <= rules.BEACON_SEARCH_RADIUS_KM
    ][:10]
    g = cand.route.glide
    plan_id = _plan_id(ctx, cand)
    if cand.window_start is None:
        cand.window_start = cand.start
        cand.window_end = _window_end(ctx, tl, cand)
    # dernier atterrissage pour ce verdict = min(fin du créneau + durée, plafond horaire, coucher du soleil)
    latest = min(cand.latest_landing, cand.window_end + timedelta(minutes=cand.duration_min))
    if cand.sunset:
        latest = min(latest, cand.sunset)
    cand.latest_landing = max(latest, cand.landing_time)
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
        window=TimeWindow(start=iso(cand.window_start), end=iso(cand.window_end), latest_landing=iso(cand.latest_landing)),
        sun=SunTimes(sunrise=iso(cand.sunrise) if cand.sunrise else None, sunset=iso(cand.sunset) if cand.sunset else None),
        takeoff=cand.takeoff,
        landing=cand.landing,
        alternate_landings=cand.alternates,
        waypoints=cand.route.waypoints,
        route=RouteGeometry(coordinates=[(round(c[0], 6), round(c[1], 6), round(c[2])) for c in cand.route.coords]),
        distance_km=round(cand.route.distance_km, 1),
        est_duration_min=round(cand.duration_min),
        max_altitude_m=round(cand.max_alt),
        glide=Glide(
            required_ratio=round(g.required_ratio, 2),
            available_ratio=round(g.available_ratio, 2),
            margin_ok=bool(g.margin_ok),
        ),
        weather=PlanWeather(takeoff=snap_to, landing=snap_ldg, timeline=timeline),
        thermals=thermals,
        sounding=sounding_from_analysis(tw.hour),
        beacons_nearby=beacons_nearby,
        airspaces=cand.airspaces,
        risks=cand.risks,
        briefing=briefing(cand),
        checklist=checklist(cand),
        score_breakdown=cand.score_items,
        confidence=round(cand.confidence, 2),
        sources=sources,
        links=PlanLinks(gpx=f"/api/plans/{plan_id}/gpx", xctsk=f"/api/plans/{plan_id}/xctsk"),
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
        warnings.append(
            "Mode démo : données SYNTHÉTIQUES (météo simulée, sites et balises de démonstration). "
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


