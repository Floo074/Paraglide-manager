"""Fournisseur météo SYNTHÉTIQUE déterministe (mode mock).

Aucun hasard non seedé : la sortie ne dépend que de (date/heure UTC, lat, lon, altitude, membre).
Chaque journée reçoit un « scénario » synoptique (belle journée thermique, bise, foehn, orages
d'après-midi, front pluvieux, inversion…) choisi par hachage de la date, et les champs sont construits
de façon physiquement cohérente :
- atmosphère libre : T850 climatologique (saison) + anomalie du scénario, gradient du scénario,
  inversion de subsidence éventuelle ;
- cycle diurne : rayonnement ciel clair (position du soleil) atténué par la nébulosité, échauffement
  du sol puis couche limite bien mélangée (adiabatique sèche) jusqu'à rejoindre l'atmosphère libre ;
  refroidissement nocturne (inversion au sol) ;
- humidité : rapport de mélange conservé dans la couche limite, air plus ou moins sec au-dessus ;
- vent : flux synoptique par niveau + brise de pente/vallée montante le jour (direction = pente du
  MNT synthétique), descendante la nuit ; rafales selon turbulence et convection ;
- CAPE / LI / CIN calculés par la méthode de la particule sur le profil produit (cohérence interne) ;
- précipitations selon le scénario (orages localisés l'après-midi, pluie frontale…).
Trois « membres » légèrement perturbés (perturbation croissante avec l'échéance) simulent la
dispersion multi-modèles.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta

from app.geo import wind_components, wind_from_components
from app.meteo.solar import clear_sky_ghi, cloud_attenuation, solar_local_hour, sun_elevation_deg, sunrise_sunset
from app.meteo.thermo import DRY_LAPSE_K_PER_M, ESPY_M_PER_K, RD, T0K, G, dew_point_from_mixing_ratio, mixing_ratio
from app.meteo.types import PRESSURE_LEVELS_HPA, HourData, LevelData
from app.providers.synthetic_terrain import smooth_noise, terrain_gradient


@dataclass(frozen=True, slots=True)
class Scenario:
    key: str
    label: str
    wind700: tuple[float, float]  # (km/h, direction d'où vient le vent)
    wind850: tuple[float, float]
    t850_anom: float  # °C par rapport à la climatologie
    lapse_k_per_km: float  # gradient de l'atmosphère libre (négatif)
    dd_base: float  # écart T−Td de l'air (°C) au matin, à l'altitude du sol
    dd_aloft: float  # écart T−Td au-dessus de la couche limite
    cloud_base_pct: float  # nébulosité moyenne/haute de fond
    cumulus_pct: float  # couverture cumuliforme maximale si cumulus
    mslp_hpa: float
    precip: str  # none | storms | front | showers
    gust_factor: float
    breeze: float  # intensité relative de la brise thermique
    inversion_m: float | None = None  # sommet d'inversion de subsidence (AMSL)
    inversion_k: float = 0.0


SCENARIOS: dict[str, Scenario] = {
    s.key: s
    for s in (
        Scenario("thermal_good", "Belle journée thermique, flux faible d'ouest", (14, 285), (8, 300), 1.0, -6.0,
                 6.0, 14.0, 5, 35, 1020, "none", 1.35, 1.0),
        Scenario("blue_thermal", "Anticyclone sec, thermiques bleus, flux faible de nord-est", (10, 40), (8, 50), 2.0,
                 -6.0, 11.0, 20.0, 0, 0, 1026, "none", 1.3, 1.0),
        Scenario("west_moderate", "Flux d'ouest modéré, cumulus, dynamique sur les faces ouest", (32, 265), (22, 270),
                 -1.0, -6.0, 5.0, 9.0, 15, 45, 1014, "none", 1.4, 0.7),
        Scenario("nw_post_front", "Traîne de nord-ouest, air froid instable, averses isolées", (28, 315), (20, 320),
                 -3.0, -6.6, 4.5, 6.0, 20, 55, 1012, "showers", 1.5, 0.8),
        Scenario("afternoon_storms", "Marais barométrique chaud et humide, orages l'après-midi", (12, 220), (6, 210),
                 3.0, -7.4, 2.5, 3.0, 20, 70, 1013, "storms", 1.4, 1.0),
        Scenario("rainy_front", "Passage frontal, ciel couvert et pluie", (42, 230), (28, 220), 0.0, -6.0, 0.8, 1.0,
                 95, 0, 1003, "front", 1.6, 0.2),
        Scenario("bise", "Bise de nord-est soutenue, air sec", (38, 40), (34, 45), -2.0, -6.2, 9.0, 14.0, 5, 10, 1028,
                 "none", 1.45, 0.4),
        Scenario("foehn_south", "Foehn de sud, vent fort en altitude, air sec et chaud", (62, 200), (38, 190), 5.0,
                 -6.0, 13.0, 18.0, 30, 0, 1006, "none", 1.8, 0.3),
        Scenario("stable_inversion", "Anticyclone stable, inversion de subsidence, thermiques faibles",
                 (6, 60), (5, 70), 3.5, -5.0, 6.0, 25.0, 10, 0, 1030, "none", 1.25, 0.6, 1700.0, 4.0),
    )
}  # fmt: skip

# Fréquence relative des scénarios dans le cycle automatique
_SCENARIO_WEIGHTS = (
    ("thermal_good", 4),
    ("blue_thermal", 2),
    ("west_moderate", 2),
    ("nw_post_front", 1),
    ("afternoon_storms", 2),
    ("rainy_front", 1),
    ("bise", 1),
    ("foehn_south", 1),
    ("stable_inversion", 2),
)
MEMBERS = ("synthetic", "synthetic-b", "synthetic-c")


def scenario_for_date(d: date, forced: str | None = None) -> Scenario:
    if forced:
        return SCENARIOS[forced]
    h = int(hashlib.sha256(f"paraglide-{d.isoformat()}".encode()).hexdigest()[:8], 16)
    total = sum(w for _, w in _SCENARIO_WEIGHTS)
    r = h % total
    for key, w in _SCENARIO_WEIGHTS:
        if r < w:
            return SCENARIOS[key]
        r -= w
    return SCENARIOS["thermal_good"]


def find_date_for_scenario(key: str, start: date, max_days: int = 400) -> date:
    """Première date ≥ start à laquelle le cycle automatique donne le scénario `key` (utile aux tests)."""
    for i in range(max_days):
        d = start + timedelta(days=i)
        if scenario_for_date(d).key == key:
            return d
    raise ValueError(f"scénario {key} introuvable")


def _t850_climatology(d: date) -> float:
    doy = d.timetuple().tm_yday
    return 6.0 + 7.0 * math.cos(2 * math.pi * (doy - 200) / 365.0)


def _diurnal_shape(solar_h: float, rise_h: float, set_h: float) -> float:
    """0 la nuit, 1 au maximum (≈ 14h solaire), forme asymétrique."""
    h0 = rise_h + 1.5
    h1 = set_h + 0.8
    if solar_h <= h0 or solar_h >= h1:
        return 0.0
    u = (solar_h - h0) / (h1 - h0)
    return math.sin(math.pi * u**1.25) ** 1.2


def _hash_unit(*parts: object) -> float:
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


class SyntheticWeather:
    """Génère des `HourData` synthétiques."""

    def __init__(self, forced_scenario: str | None = None) -> None:
        if forced_scenario and forced_scenario not in SCENARIOS:
            raise ValueError(f"scénario synthétique inconnu : {forced_scenario} (choix : {', '.join(SCENARIOS)})")
        self.forced = forced_scenario or None

    def scenario(self, t: datetime, lon: float) -> Scenario:
        local = t + timedelta(hours=lon / 15.0)
        return scenario_for_date(local.date(), self.forced)

    def hour(
        self,
        lat: float,
        lon: float,
        ground_m: float,
        t: datetime,
        member: int = 0,
        issued_at: datetime | None = None,
    ) -> HourData:
        if t.tzinfo is None:
            t = t.replace(tzinfo=UTC)
        sc = self.scenario(t, lon)
        local_date = (t + timedelta(hours=lon / 15.0)).date()
        lead_h = 0.0 if issued_at is None else max(0.0, (t - issued_at).total_seconds() / 3600.0)
        pert = (0.15 + lead_h / 48.0) * (0, 1, -1)[member % 3]
        mseed = _hash_unit("member", member, local_date) - 0.5 if member else 0.0

        n1 = smooth_noise(lat, lon, seed=11 + local_date.toordinal() % 97)
        n2 = smooth_noise(lat, lon, seed=23 + local_date.toordinal() % 89)
        n3 = smooth_noise(lat, lon, seed=37 + local_date.toordinal() % 83)
        n4 = smooth_noise(lat, lon, seed=41 + local_date.toordinal() % 79)

        # --- soleil -----------------------------------------------------------------------
        elev = sun_elevation_deg(t, lat, lon)
        solar_h = solar_local_hour(t, lon)
        rise, sset = sunrise_sunset(local_date, lat, lon)
        rise_h = solar_local_hour(rise, lon) if rise else 6.0
        set_h = solar_local_hour(sset, lon) if sset else 18.0
        shape = _diurnal_shape(solar_h, rise_h, set_h)
        noon_elev = 90.0 - abs(lat - 23.44 * math.sin(2 * math.pi * (local_date.timetuple().tm_yday - 81) / 365))
        season = max(0.25, min(1.0, math.sin(math.radians(max(5.0, noon_elev))) / math.sin(math.radians(67.0))))

        # --- atmosphère libre ---------------------------------------------------------------
        t850 = _t850_climatology(local_date) + sc.t850_anom + 1.2 * n1 + 0.6 * pert
        lapse = sc.lapse_k_per_km / 1000.0
        z850 = 1460.0 + (sc.mslp_hpa - 1013.0) * 8.0

        def t_free(z: float) -> float:
            tz = t850 + lapse * (z - z850)
            if sc.inversion_m is not None:
                inv_base = sc.inversion_m - 300.0
                if z > inv_base:
                    tz += sc.inversion_k * min(1.0, (z - inv_base) / 300.0)
            return tz

        # --- nébulosité de fond et précipitations ---------------------------------------------
        storm_cell = max(0.0, smooth_noise(lat, lon, seed=59 + local_date.toordinal() % 71) + 0.15)
        precip = 0.0
        cc_midhigh = max(0.0, min(100.0, sc.cloud_base_pct + 10 * n2))
        if sc.precip == "storms" and solar_h >= 13.5 and solar_h <= 20.5:
            ramp = min(1.0, (solar_h - 13.5) / 1.5) * (1.0 if solar_h < 19 else max(0.0, (20.5 - solar_h) / 1.5))
            precip = 4.0 * storm_cell * ramp
            cc_midhigh = min(100.0, cc_midhigh + 60 * ramp)
        elif sc.precip == "front":
            precip = max(0.3, 1.8 + 1.2 * n3)
            cc_midhigh = 100.0
        elif sc.precip == "showers" and 12.5 <= solar_h <= 18.5:
            precip = max(0.0, 1.5 * (n3 - 0.35))

        # --- échauffement diurne -------------------------------------------------------------
        cc_eff = cc_midhigh
        sw_clear = clear_sky_ghi(elev, ground_m)
        amp = max(3.5, 10.0 - 2.5 * ground_m / 1000.0) * season * (1.0 - 0.55 * cc_eff / 100.0)
        if sc.precip == "front":
            amp *= 0.35
        night = (4.5 + 0.8 * n2) * (1.0 - 0.7 * cc_eff / 100.0)
        dt_day = -night + (amp + night) * shape
        t_fa_g = t_free(ground_m)
        t2 = t_fa_g + dt_day + 0.5 * n4 + 0.4 * pert

        # humidité : rapport de mélange conservé dans la couche limite
        dd0 = max(0.6, sc.dd_base + 1.2 * n2 + 0.5 * pert)
        td_g = min(t2 - 0.4, t_fa_g - dd0 + (1.0 if sc.precip in ("front", "storms") else 0.0))
        if precip > 0.2:
            td_g = max(td_g, t2 - 1.2)

        # --- profil aux niveaux de pression --------------------------------------------------
        p_sl = sc.mslp_hpa
        levels: list[LevelData] = []
        z_prev, p_prev = 0.0, p_sl
        # sommet de la couche mélangée (adiabatique sèche partant de T2m)
        top = ground_m
        if dt_day > 0:
            z = ground_m
            while z < ground_m + 5000:
                z += 25.0
                if t2 - DRY_LAPSE_K_PER_M * (z - ground_m) <= t_free(z):
                    break
            top = z
        r_g = mixing_ratio(td_g, 1013.25 * (1 - 2.25577e-5 * ground_m) ** 5.25588)
        w700 = sc.wind700[0] * (1.0 + 0.15 * n3 + 0.08 * pert) * (1.0 + 0.05 * mseed)
        d700 = (sc.wind700[1] + 14.0 * n4 + 8.0 * pert) % 360
        w850 = sc.wind850[0] * (1.0 + 0.15 * n3 + 0.08 * pert)
        d850 = (sc.wind850[1] + 14.0 * n4 + 8.0 * pert) % 360

        def wind_at(z: float) -> tuple[float, float]:
            u7, v7 = wind_components(w700, d700)
            u8, v8 = wind_components(w850, d850)
            if z >= 3000.0:
                f = min(1.6, 1.0 + (z - 3000.0) / 5000.0)
                return wind_from_components(u7 * f, v7 * f)
            if z >= z850:
                f = (z - z850) / (3000.0 - z850)
                return wind_from_components(u8 + f * (u7 - u8), v8 + f * (v7 - v8))
            f = max(0.45, 1.0 - (z850 - z) / 2500.0)
            return wind_from_components(u8 * f, v8 * f)

        for p in PRESSURE_LEVELS_HPA:
            # épaisseur hypsométrique avec la température libre moyenne de la couche
            z_guess = z_prev + 8000.0 * math.log(p_prev / p)
            t_mean = t_free((z_prev + z_guess) / 2) + T0K
            z = z_prev + RD * t_mean / G * math.log(p_prev / p)
            z_prev, p_prev = z, p
            tz = t_free(z)
            if z > ground_m and dt_day > 0 and z < top:
                tz = max(tz, t2 - DRY_LAPSE_K_PER_M * (z - ground_m) - 0.2)
            elif z > ground_m and dt_day <= 0:
                tz = tz + dt_day * math.exp(-(z - ground_m) / 180.0)
            elif z <= ground_m:
                tz = t2 + 0.0065 * (ground_m - z)
            if ground_m < z < top:
                tdz = dew_point_from_mixing_ratio(r_g, p)
            else:
                dd_al = max(0.5, sc.dd_aloft + 3.0 * n1 + (2.0 if z > 4000 else 0.0))
                if sc.precip == "storms" and solar_h > 12:
                    dd_al = max(0.5, dd_al - 1.5)
                tdz = tz - dd_al
            tdz = min(tdz, tz)
            ws, wd = wind_at(z)
            levels.append(LevelData(float(p), round(z, 1), round(tz, 2), round(tdz, 2), round(ws, 1), round(wd, 1)))

        # --- vent 10 m : synoptique mélangé + brise de pente/vallée --------------------------
        syn_s, syn_d = wind_at(ground_m + 300.0)
        mix = (0.35 + 0.30 * shape) * (1.0 + min(0.4, ground_m / 4000.0))
        us, vs = wind_components(syn_s * mix, syn_d)
        gx, gy = terrain_gradient(lat, lon)
        slope = math.hypot(gx, gy)
        breeze_kmh = 0.0
        if slope > 15.0:
            downhill_from = (math.degrees(math.atan2(-gx, -gy)) + 360.0) % 360.0  # vent montant vient de l'aval
            uphill_from = (downhill_from + 180.0) % 360.0
            if shape > 0:
                breeze_kmh = sc.breeze * shape * (6.0 + 6.0 * min(1.0, slope / 300.0)) * (1 - 0.6 * cc_eff / 100)
                ub, vb = wind_components(breeze_kmh, downhill_from)
            else:
                breeze_kmh = 3.0 * min(1.0, slope / 200.0)
                ub, vb = wind_components(breeze_kmh, uphill_from)
            us += ub
            vs += vb
        w10, d10 = wind_from_components(us, vs)
        convective = 5.0 * shape * (1 - cc_eff / 100)
        gust = w10 * sc.gust_factor + convective + 2.0
        if sc.key == "foehn_south":
            gust = max(gust, w10 * 1.9 + 5)

        # --- nébulosité convective, rayonnement ------------------------------------------------
        lcl = ground_m + ESPY_M_PER_K * max(0.0, t2 - td_g)
        cumulus = shape > 0.15 and lcl < top
        cc_low = 0.0
        if cumulus:
            cc_low = sc.cumulus_pct * min(1.0, shape * 1.4) * (0.7 + 0.3 * (n2 + 1) / 2)
        if sc.precip == "front":
            cc_low = 90.0
        if sc.precip == "storms" and precip > 0.2:
            cc_low = max(cc_low, 75.0)
        cc_total = min(100.0, max(cc_midhigh, cc_low) + 0.4 * min(cc_midhigh, cc_low))
        sw = sw_clear * cloud_attenuation(cc_total)

        # --- grandeurs dérivées « modèle » ---------------------------------------------------
        freezing = None
        for lv_a, lv_b in zip(levels, levels[1:], strict=False):
            if lv_a.temperature_c > 0 >= lv_b.temperature_c:
                freezing = lv_a.height_m + lv_a.temperature_c / (lv_a.temperature_c - lv_b.temperature_c) * (
                    lv_b.height_m - lv_a.height_m
                )
                break
        blh = max(50.0, top - ground_m) if dt_day > 0 else 80.0 + 40.0 * (n1 + 1)

        return HourData(
            time=t,
            temperature_2m=round(t2, 2),
            dew_point_2m=round(td_g, 2),
            wind_speed_10m=round(w10, 1),
            wind_direction_10m=round(d10, 1),
            wind_gusts_10m=round(gust, 1),
            cloud_cover=round(cc_total, 1),
            cloud_cover_low=round(cc_low, 1),
            cloud_cover_mid=round(cc_midhigh * 0.6, 1),
            cloud_cover_high=round(cc_midhigh, 1),
            precipitation=round(max(0.0, precip), 2),
            cape=None,  # calculé par la méthode de la particule (app.meteo.thermals)
            lifted_index=None,
            convective_inhibition=None,
            freezing_level_height=round(freezing, 0) if freezing is not None else None,
            boundary_layer_height=round(blh, 0),
            shortwave_radiation=round(sw, 1),
            levels=levels,
        )


def scenario_member(sc: Scenario, **changes) -> Scenario:
    return replace(sc, **changes)
