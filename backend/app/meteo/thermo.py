"""Thermodynamique de l'atmosphère (formules classiques, unités SI sauf mention)."""

from __future__ import annotations

import math

G = 9.80665  # m/s²
RD = 287.04  # J/(kg·K) constante des gaz air sec
CP = 1004.6  # J/(kg·K)
LV = 2.501e6  # J/kg chaleur latente de vaporisation
EPS = 0.622
KAPPA = RD / CP  # ≈ 0.2857
T0K = 273.15
DRY_LAPSE_K_PER_M = G / CP  # ≈ 0.00976 K/m (adiabatique sèche)
ESPY_M_PER_K = 125.0  # base des cumulus ≈ 125 m par °C d'écart T−Td


def sat_vapor_pressure_hpa(t_c: float) -> float:
    """Pression de vapeur saturante (Bolton 1980), hPa."""
    return 6.112 * math.exp(17.67 * t_c / (t_c + 243.5))


def dew_point_from_rh(t_c: float, rh_pct: float) -> float:
    """Point de rosée (°C) depuis T (°C) et humidité relative (%)."""
    rh = min(100.0, max(1.0, rh_pct))
    e = rh / 100.0 * sat_vapor_pressure_hpa(t_c)
    ln = math.log(e / 6.112)
    return 243.5 * ln / (17.67 - ln)


def rh_from_dew_point(t_c: float, td_c: float) -> float:
    return 100.0 * min(1.0, sat_vapor_pressure_hpa(td_c) / sat_vapor_pressure_hpa(t_c))


def mixing_ratio(td_c: float, p_hpa: float) -> float:
    """Rapport de mélange (kg/kg) à partir du point de rosée."""
    e = sat_vapor_pressure_hpa(td_c)
    return EPS * e / max(p_hpa - e, 1.0)


def dew_point_from_mixing_ratio(r: float, p_hpa: float) -> float:
    e = r * p_hpa / (EPS + r)
    ln = math.log(max(e, 1e-6) / 6.112)
    return 243.5 * ln / (17.67 - ln)


def potential_temperature_k(t_c: float, p_hpa: float) -> float:
    return (t_c + T0K) * (1000.0 / p_hpa) ** KAPPA


def std_pressure_hpa(z_m: float) -> float:
    """Pression de l'atmosphère standard OACI à l'altitude z."""
    return 1013.25 * (1.0 - 2.25577e-5 * z_m) ** 5.25588


def std_altitude_m(p_hpa: float) -> float:
    return (1.0 - (p_hpa / 1013.25) ** (1.0 / 5.25588)) / 2.25577e-5


def air_density(z_m: float, t_c: float | None = None) -> float:
    p = std_pressure_hpa(z_m) * 100.0
    t_k = (t_c + T0K) if t_c is not None else 288.15 - 0.0065 * z_m
    return p / (RD * t_k)


def moist_lapse_rate_k_per_m(t_c: float, p_hpa: float) -> float:
    """Gradient adiabatique saturé (pseudo-adiabatique), K/m."""
    t_k = t_c + T0K
    rs = mixing_ratio(t_c, p_hpa)
    num = 1.0 + LV * rs / (RD * t_k)
    den = CP + LV * LV * rs * EPS / (RD * t_k * t_k)
    return G * num / den


def espy_cloud_base_agl(t_c: float, td_c: float) -> float:
    """Hauteur de condensation (m sol) par la formule d'Espy : 125 m × (T − Td)."""
    return max(0.0, ESPY_M_PER_K * (t_c - td_c))


def lcl(t_c: float, td_c: float, z_m: float, p_hpa: float | None = None) -> tuple[float, float]:
    """Niveau de condensation d'une particule (altitude AMSL, température à ce niveau).

    Itération : la particule suit l'adiabatique sèche, son rapport de mélange est conservé.
    """
    p0 = p_hpa if p_hpa is not None else std_pressure_hpa(z_m)
    r = mixing_ratio(td_c, p0)
    z = z_m
    t = t_c
    for _ in range(600):
        p = std_pressure_hpa(z) * (p0 / std_pressure_hpa(z_m))
        td = dew_point_from_mixing_ratio(r, p)
        if t <= td:
            return z, t
        z += 10.0
        t -= DRY_LAPSE_K_PER_M * 10.0
    return z, t


def parcel_temperature_profile(
    t_start_c: float,
    td_start_c: float,
    z_start_m: float,
    heights_m: list[float],
    p_ratio: float = 1.0,
) -> tuple[list[float], float]:
    """Température d'une particule soulevée (sèche puis saturée) aux altitudes demandées.

    Renvoie (températures, altitude du LCL).
    """
    z_lcl, t_lcl = lcl(t_start_c, td_start_c, z_start_m)
    out: list[float] = []
    # pré-calcul d'une table saturée au-dessus du LCL par pas de 25 m
    step = 25.0
    table_z = [z_lcl]
    table_t = [t_lcl]
    zmax = max(heights_m) if heights_m else z_lcl
    z, t = z_lcl, t_lcl
    while z < zmax + step:
        p = std_pressure_hpa(z) * p_ratio
        t -= moist_lapse_rate_k_per_m(t, p) * step
        z += step
        table_z.append(z)
        table_t.append(t)
    for h in heights_m:
        if h <= z_lcl:
            out.append(t_start_c - DRY_LAPSE_K_PER_M * (h - z_start_m))
        else:
            i = min(int((h - z_lcl) / step), len(table_z) - 2)
            f = (h - table_z[i]) / step
            out.append(table_t[i] + f * (table_t[i + 1] - table_t[i]))
    return out, z_lcl
