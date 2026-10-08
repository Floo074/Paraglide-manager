"""Calculs aérologiques : plafond thermique, base des cumulus, W* de Deardorff, vario, CAPE/LI,
fenêtre de convection et risque de surdéveloppement.

Formules (cf. backend/README.md) :
- Plafond (méthode de la particule) : on part de T_sol + surchauffe (≈ 1 °C au soleil), on suit
  l'adiabatique sèche (9,8 °C/km) jusqu'à l'intersection avec le profil. Croisé avec la hauteur de
  couche limite du modèle si disponible (moyenne pondérée).
- Base des cumulus (Espy) : z_sol + 125 m × (T − Td). Thermiques « bleus » si base > plafond sec.
- Plafond « thermique » = min(plafond sec, base) ; plafond utile = min(plafond, base − 300 m).
- W* = (g/θ · H/(ρ·cp) · zi)^(1/3), H = flux de chaleur sensible ≈ fraction du rayonnement solaire
  absorbé (fraction décroissante avec l'humidité du sol/de l'air).
- Vario moyen ≈ max(0, W* − 1,0 m/s) (taux de chute de l'aile en spirale), réduit par vent fort.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from app.engine import rules
from app.meteo.profile import VerticalProfile
from app.meteo.thermo import (
    CP,
    DRY_LAPSE_K_PER_M,
    ESPY_M_PER_K,
    G,
    T0K,
    air_density,
    moist_lapse_rate_k_per_m,
    rh_from_dew_point,
    std_pressure_hpa,
)
from app.meteo.types import HourData


@dataclass(slots=True)
class ParcelResult:
    cape: float
    cin: float
    lifted_index: float | None
    lcl_m: float
    lfc_m: float | None
    el_m: float | None  # niveau d'équilibre (≈ sommet des nuages convectifs)


@dataclass(slots=True)
class HourAnalysis:
    """Analyse aérologique d'une heure en un point (valeurs agrégées multi-modèles)."""

    time: datetime
    lat: float
    lon: float
    ground_m: float
    profile: VerticalProfile
    temperature_c: float
    dew_point_c: float
    wind_speed_kmh: float
    wind_direction_deg: float
    wind_gust_kmh: float
    cloud_cover_pct: float
    cloud_cover_low_pct: float
    cloud_cover_midhigh_pct: float
    precipitation_mm_h: float
    cape_j_kg: float
    lifted_index: float | None
    cin_j_kg: float | None
    freezing_level_m: float | None
    shortwave_w_m2: float
    blh_agl_m: float
    dry_top_m: float
    lcl_m: float
    thermal_ceiling_m: float
    cloud_base_m: float | None
    cumulus: bool
    usable_ceiling_m: float
    wstar_ms: float
    thermal_strength_ms: float
    rh700_pct: float | None
    el_m: float | None
    models: list[str] = field(default_factory=list)


def trigger_excess_c(shortwave_w_m2: float) -> float:
    """Surchauffe de la particule au déclenchement (°C), nulle sans soleil."""
    f = max(0.0, min(1.0, shortwave_w_m2 / rules.TRIGGER_EXCESS_FULL_SUN_W_M2))
    return rules.THERMAL_TRIGGER_EXCESS_C * f


def dry_thermal_top(profile: VerticalProfile, t_start_c: float, ground_m: float, max_agl: float = 5500) -> float:
    """Altitude où la particule (adiabatique sèche) rejoint la température de l'environnement."""
    step = 20.0
    z = ground_m
    prev_excess = t_start_c - profile.temperature(ground_m)
    if prev_excess <= 0:
        return ground_m
    while z < ground_m + max_agl:
        z_next = z + step
        tp = t_start_c - DRY_LAPSE_K_PER_M * (z_next - ground_m)
        excess = tp - profile.temperature(z_next)
        if excess <= 0:
            # interpolation linéaire du point de croisement
            return z + step * prev_excess / (prev_excess - excess)
        prev_excess = excess
        z = z_next
    return z


def cloud_base_espy(t_c: float, td_c: float, ground_m: float) -> float:
    return ground_m + ESPY_M_PER_K * max(0.0, t_c - td_c)


def sensible_heat_flux(shortwave_w_m2: float, rh_pct: float, recent_rain: bool = False) -> float:
    """Flux de chaleur sensible H (W/m²) estimé depuis le rayonnement solaire incident."""
    lo, hi = rules.SENSIBLE_HEAT_FRACTION_RANGE
    frac = max(lo, min(hi, 0.55 - 0.004 * rh_pct))
    if recent_rain:
        frac = lo
    return max(0.0, shortwave_w_m2 * (1.0 - rules.SENSIBLE_HEAT_ALBEDO) * frac)


def deardorff_wstar(h_w_m2: float, zi_m: float, theta_k: float, z_m: float) -> float:
    """Vitesse convective de Deardorff w* = (g/θ · H/(ρ cp) · zi)^(1/3)."""
    if h_w_m2 <= 0 or zi_m <= 0:
        return 0.0
    rho = air_density(z_m)
    return (G / theta_k * h_w_m2 / (rho * CP) * zi_m) ** (1.0 / 3.0)


def thermal_strength_from_wstar(wstar: float, mean_bl_wind_kmh: float = 0.0) -> float:
    """Vario moyen estimé (m/s) : W* − taux de chute en spirale, réduit si le vent hache les thermiques."""
    vario = max(0.0, wstar - rules.WSTAR_TO_VARIO_SINK_MS)
    excess = max(0.0, mean_bl_wind_kmh - rules.STRONG_WIND_THERMAL_BREAK_KMH)
    factor = 1.0 - min(0.5, excess / 60.0)
    return vario * factor


def parcel_analysis(profile: VerticalProfile, t_c: float, td_c: float, ground_m: float) -> ParcelResult:
    """CAPE / CIN / LI d'une particule de surface (sèche jusqu'au LCL puis pseudo-adiabatique)."""
    z_lcl = ground_m + ESPY_M_PER_K * max(0.0, t_c - td_c)
    step = 50.0
    z = ground_m
    tp = t_c
    cape = 0.0
    cin = 0.0
    lfc = None
    el = None
    li = None
    p_ratio = profile.pressure(ground_m) / std_pressure_hpa(ground_m)
    z500 = None
    for pt in profile.points:
        if abs(pt.p - 500.0) < 1.0:
            z500 = pt.z
    if z500 is None:
        z500 = 5570.0
    top = max(z500 + 200.0, min(14000.0, profile.top_m + 4000.0))
    above_lfc = False
    while z < top:
        z_next = z + step
        if z_next <= z_lcl:
            tp_next = tp - DRY_LAPSE_K_PER_M * step
        else:
            p = std_pressure_hpa(z) * p_ratio
            tp_next = tp - moist_lapse_rate_k_per_m(tp, p) * step
        te = profile.temperature(z_next)
        buoy = G * (tp_next - te) / (te + T0K)
        if buoy > 0:
            cape += buoy * step
            if not above_lfc:
                lfc = z_next
                above_lfc = True
        else:
            if above_lfc:
                el = z_next
                above_lfc = False
                # au-dessus de l'EL, on arrête de chercher une seconde couche instable
                if z_next > z500:
                    tp = tp_next
                    z = z_next
                    break
            elif cape == 0.0:
                cin += buoy * step
        if li is None and z_next >= z500:
            li = te - tp_next
        tp = tp_next
        z = z_next
    if li is None:
        li = profile.temperature(z500) - tp
    if above_lfc:
        el = z
    return ParcelResult(cape=cape, cin=cin, lifted_index=li, lcl_m=z_lcl, lfc_m=lfc, el_m=el)


def analyze_hour(
    hour: HourData,
    ground_m: float,
    lat: float,
    lon: float,
    models: list[str] | None = None,
    wind_ground_m: float | None = None,
) -> HourAnalysis:
    """Calculs aérologiques complets pour une heure (données déjà agrégées).

    `wind_ground_m` : altitude du sol lissé du modèle (le vent 10 m y est placé, cf. profile.py).
    """
    profile = VerticalProfile.from_hour(hour, ground_m, wind_ground_m)
    t2 = hour.temperature_2m if hour.temperature_2m is not None else profile.temperature(ground_m)
    td2 = hour.dew_point_2m if hour.dew_point_2m is not None else t2 - 8.0
    td2 = min(td2, t2)
    sw = max(0.0, hour.shortwave_radiation or 0.0)
    precip = max(0.0, hour.precipitation or 0.0)
    cc = hour.cloud_cover if hour.cloud_cover is not None else 0.0
    cc_low = hour.cloud_cover_low if hour.cloud_cover_low is not None else 0.0
    cc_mid = hour.cloud_cover_mid or 0.0
    cc_high = hour.cloud_cover_high or 0.0
    cc_midhigh = max(cc_mid, cc_high)

    excess = trigger_excess_c(sw)
    t_start = t2 + excess
    dry_top = dry_thermal_top(profile, t_start, ground_m)
    # croisement avec la couche limite du modèle (le jour seulement)
    if hour.boundary_layer_height is not None and sw > 50 and hour.boundary_layer_height > 0:
        model_top = ground_m + min(4500.0, hour.boundary_layer_height)
        w = rules.MODEL_BLH_WEIGHT
        dry_top = (1 - w) * dry_top + w * model_top if dry_top > ground_m + 50 else dry_top
    lcl_m = cloud_base_espy(t2, td2, ground_m)
    cumulus = lcl_m < dry_top and dry_top - ground_m > 300 and sw > 50
    thermal_ceiling = min(dry_top, lcl_m) if cumulus else dry_top
    cloud_base = lcl_m if cumulus else None
    usable = thermal_ceiling
    if cloud_base is not None:
        usable = min(usable, cloud_base - rules.CLOUD_CLEARANCE_VERTICAL_M)
    usable = max(ground_m, usable)

    zi = max(0.0, thermal_ceiling - ground_m)
    rh2 = rh_from_dew_point(t2, td2)
    h_flux = sensible_heat_flux(sw, rh2, recent_rain=precip >= 0.2)
    theta = (t2 + T0K) * (1000.0 / profile.pressure(ground_m)) ** 0.2857
    wstar = deardorff_wstar(h_flux, zi, theta, ground_m) if zi > 100 else 0.0
    bl_wind = profile.mean_wind(ground_m, max(ground_m + 200, thermal_ceiling))[0] if zi > 0 else 0.0
    strength = thermal_strength_from_wstar(wstar, bl_wind)
    if precip >= rules.NOGO["precip_mm_h"]:
        strength *= 0.3

    parcel = parcel_analysis(profile, t2 + excess, td2, ground_m)
    cape = hour.cape if hour.cape is not None else parcel.cape
    li = hour.lifted_index if hour.lifted_index is not None else parcel.lifted_index
    cin = hour.convective_inhibition if hour.convective_inhibition is not None else parcel.cin
    freezing = hour.freezing_level_height
    if freezing is None:
        freezing = profile.isotherm_height(0.0)
    blh = hour.boundary_layer_height if hour.boundary_layer_height is not None else zi

    rh700 = None
    for pt in profile.points:
        if abs(pt.p - 700.0) < 1.0:
            rh700 = rh_from_dew_point(pt.t, pt.td)

    return HourAnalysis(
        time=hour.time,
        lat=lat,
        lon=lon,
        ground_m=ground_m,
        profile=profile,
        temperature_c=t2,
        dew_point_c=td2,
        wind_speed_kmh=hour.wind_speed_10m or 0.0,
        wind_direction_deg=hour.wind_direction_10m or 0.0,
        wind_gust_kmh=hour.wind_gusts_10m
        if hour.wind_gusts_10m is not None
        else (hour.wind_speed_10m or 0.0) * rules.GUST_FACTOR_DEFAULT,
        cloud_cover_pct=cc,
        cloud_cover_low_pct=cc_low,
        cloud_cover_midhigh_pct=cc_midhigh,
        precipitation_mm_h=precip,
        cape_j_kg=max(0.0, cape),
        lifted_index=li,
        cin_j_kg=cin,
        freezing_level_m=freezing,
        shortwave_w_m2=sw,
        blh_agl_m=max(0.0, blh),
        dry_top_m=dry_top,
        lcl_m=lcl_m,
        thermal_ceiling_m=thermal_ceiling,
        cloud_base_m=cloud_base,
        cumulus=cumulus,
        usable_ceiling_m=usable,
        wstar_ms=wstar,
        thermal_strength_ms=strength,
        rh700_pct=rh700,
        el_m=parcel.el_m,
        models=list(models or []),
    )


# ---------------------------------------------------------------------------------------------
# Analyse sur la journée
# ---------------------------------------------------------------------------------------------


@dataclass(slots=True)
class ConvectionWindow:
    start: datetime | None
    end: datetime | None
    peak: datetime | None
    peak_strength_ms: float
    first_cumulus: datetime | None
    overdevelopment_risk: str  # low | moderate | high
    overdevelopment_time: datetime | None


def overdevelopment_level(a: HourAnalysis) -> str:
    """Risque de surdéveloppement d'une heure (§4.6 du cahier des charges)."""
    cape = a.cape_j_kg
    li = a.lifted_index if a.lifted_index is not None else 5.0
    hi_cape, hi_li = rules.OVERDEV_HIGH["cape"], rules.OVERDEV_HIGH["li"]
    if cape > hi_cape and li < hi_li:
        return "high"
    if (
        a.cumulus
        and a.cloud_base_m is not None
        and a.dry_top_m - a.cloud_base_m > rules.OVERDEV_BASE_BELOW_DRY_TOP_M
        and cape >= rules.OVERDEV_LOW_CAPE
    ):
        return "high"
    if cape < rules.OVERDEV_LOW_CAPE and not (
        a.cumulus and (a.rh700_pct or 0) > rules.OVERDEV_MODERATE_RH700_PCT
    ):
        return "low"
    if li > rules.OVERDEV_LOW_LI and not (a.cumulus and (a.rh700_pct or 0) > rules.OVERDEV_MODERATE_RH700_PCT):
        return "low"
    return "moderate"


def convection_window(hours: list[HourAnalysis]) -> ConvectionWindow:
    """Début / fin / pic de la convection (§4.1) et risque de surdéveloppement de la journée."""
    start = end = peak = first_cu = None
    peak_strength = 0.0
    for a in hours:
        if (
            start is None
            and a.blh_agl_m >= rules.CONVECTION_START_MIN_BLH_AGL_M
            and a.wstar_ms >= rules.CONVECTION_START_MIN_WSTAR_MS
        ):
            start = a.time
        if a.wstar_ms >= rules.CONVECTION_END_MIN_WSTAR_MS and start is not None:
            end = a.time
        if a.thermal_strength_ms > peak_strength:
            peak_strength = a.thermal_strength_ms
            peak = a.time
        if first_cu is None and a.cumulus:
            first_cu = a.time
    order = {"low": 0, "moderate": 1, "high": 2}
    risk = "low"
    for a in hours:
        lvl = overdevelopment_level(a)
        if order[lvl] > order[risk]:
            risk = lvl
    od_time = None
    if risk != "low":
        from datetime import timedelta

        if first_cu is not None:
            od_time = first_cu + timedelta(hours=rules.OVERDEV_DELAY_AFTER_FIRST_CU_H)
        else:
            # pas de cumulus détecté : première heure où le risque apparaît
            for a in hours:
                if overdevelopment_level(a) != "low":
                    od_time = a.time
                    break
    return ConvectionWindow(start, end, peak, peak_strength, first_cu, risk, od_time)


def thermal_quality_label(vario: float) -> str:
    label = "non exploitable"
    for threshold, name in rules.THERMAL_QUALITY_MS:
        if vario >= threshold:
            label = name
    return label


def round_to(value: float, step: float) -> float:
    return float(round(value / step) * step)


def is_finite(x: float | None) -> bool:
    return x is not None and not math.isnan(x) and not math.isinf(x)
