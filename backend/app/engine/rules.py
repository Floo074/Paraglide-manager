"""TOUS les seuils métier de Paraglide Manager, en un seul endroit.

Source : docs/expert/cahier-des-charges-pilote.md — §2 seuils par niveau, §3 no-go, §4 aérologie,
§5 routage, §6 durées, §8 balises/confiance, §9 score/verdict. La partie 1 reprend À L'IDENTIQUE le
bloc YAML du §11 (mêmes clés, en MAJUSCULES, mêmes valeurs). La partie 2 regroupe les compléments
nécessaires au backend (tous issus du cahier des charges ou explicitement signalés « backend »).

Unités : km/h, m AMSL (sauf mention _agl), m/s, degrés « d'où vient le vent », minutes.
Ce module n'importe que la bibliothèque standard (il est importé partout, y compris par app/meteo).
"""

from __future__ import annotations

from typing import Final


def by_level(beginner, intermediate, advanced, expert) -> dict:
    return {"beginner": beginner, "intermediate": intermediate, "advanced": advanced, "expert": expert}


# =============================================================================================
# PARTIE 1 — Bloc YAML du §11 (copie fidèle)
# =============================================================================================
LEVELS: Final = ("beginner", "intermediate", "advanced", "expert")
TAKEOFF_WIND_MAX_KMH: Final = by_level(15, 20, 25, 30)
TAKEOFF_GUST_MAX_KMH: Final = by_level(20, 25, 30, 35)
GUST_SPREAD_MAX_KMH: Final = by_level(8, 10, 12, 15)
GUST_FACTOR_MAX: Final = by_level(1.4, 1.5, 1.6, 1.7)
CROSSWIND_ANGLE_MAX_DEG: Final = by_level(30, 45, 60, 75)
CROSSWIND_COMPONENT_MAX_KMH: Final = by_level(6, 10, 13, 16)
TAILWIND_MAX_KMH: Final = by_level(0, 0, 5, 8)
CALM_WIND_KMH: Final = 5.0
WIND_ALOFT_MAX_KMH: Final = {
    1500: by_level(15, 20, 25, 30),
    2000: by_level(20, 25, 30, 35),
    3000: by_level(25, 30, 35, 40),
}
LANDING_WIND_MAX_KMH: Final = by_level(15, 20, 25, 28)
LANDING_GUST_MAX_KMH: Final = by_level(20, 25, 30, 35)
THERMAL_MAX_MS: Final = by_level(1.5, 2.5, 3.5, 5.0)
GRADIENT_MAX_KMH_PER_1000M: Final = by_level(10, 15, 20, 25)
VEER_MAX_DEG: Final = by_level(45, 60, 90, 120)
SHEAR_MAX_KMH_PER_300M: Final = by_level(8, 12, 15, 20)
LOCAL_CEILING_MIN_ABOVE_TAKEOFF_M: Final = by_level(700, 600, 400, 300)
XC_CEILING_MIN_ABOVE_TAKEOFF_M: Final = by_level(None, 1200, 1000, 800)
XC_CEILING_MIN_ABOVE_RELIEF_M: Final = by_level(None, 500, 400, 300)
GLIDE_K: Final = by_level(0.65, 0.70, 0.72, 0.75)  # révision 2 (lot expert 2.1)
LANDING_ARRIVAL_MARGIN_M: Final = by_level(100, 100, 100, 80)  # révision 2 (lot expert 2.1)
XC_MAX_DISTANCE_KM: Final = by_level(0, 25, 80, 250)
MAX_DURATION_MIN: Final = by_level(45, 120, 300, 540)
TRANSITION_ARRIVAL_ABOVE_TERRAIN_M: Final = {"intermediate": 500, "advanced": 400, "expert": 300}
RIDGE: Final = {
    "min_kmh": 15,
    "max_kmh": by_level(20, 22, 27, 30),
    "max_angle_deg": by_level(20, 30, 40, 45),
}
AIR_SPEED_TRIM_KMH: Final = 37.0
SINK_RATE_MS: Final = {"calm": 1.2, "evening": 1.0, "sinking_air": 1.5}
NOGO: Final = {
    "precip_mm_h": 0.2,
    "precip_prev_3h_mm": 1.0,
    "cape_storm": {"cape": 800, "li": -2},
    "cape_absolute": 1500,
    "cloud_base_min_above_takeoff_m": 200,
    "wind_any_level_kmh": 45,
    "wind_3000m_mountain_kmh": 50,
    "foehn_700hpa_kmh": 40,
    "foehn_dp_hpa": 4,
    "regional_wind_ground_kmh": 30,
    "lee_wind_at_crest_kmh": 15,  # vent opposé (> 120° de l'axe du déco)
    "takeoff_wind_abs_kmh": 30,
    "takeoff_gust_abs_kmh": 35,
    "landing_before_sunset_min": 0,  # caution si < 30
    "pressure_drop_hpa_3h": 3,
}
CLOUD_CLEARANCE_VERTICAL_M: Final = 300.0
FL115_M_STANDARD: Final = 3505.0
VENTURI_FACTOR_COL: Final = 1.5
ROTOR_LEE_FACTOR: Final = {"moderate": 5, "strong": 10}  # × hauteur du relief
VALLEY_BREEZE_AFTERNOON_FACTOR: Final = 1.3
MARGINAL_BAND: Final = 0.8  # 80-100 % du seuil
VERDICT: Final = {
    "go_min_score": 65,
    # validé expert : 40 = valeur de la courbe à 80 % du seuil,
    # cohérent avec la bande marginale 80-100 % (50 rendait marginal un critère à 75-80 %).
    "go_min_safety_subscore": 40,
    # révision 2 (lot 2.11) : go si confiance ≥ 0,75 × HORIZON_BASE_CONFIDENCE[horizon]
    "go_min_confidence_ratio": 0.75,
    "nogo_max_score": 45,
}
WEIGHTS: Final = {
    "takeoff_wind": 25,
    "wind_aloft": 15,
    "landing": 15,
    "thermal_match": 15,
    "duration_match": 10,
    "convective_stability": 10,
    "data_confidence": 5,
    "site_fit": 5,
}
HORIZON_BEACON_WEIGHT: Final = {"30m": 0.7, "1h": 0.5, "2h": 0.3, "8h": 0.1, "12h": 0.0, "24h": 0.0, "48h": 0.0}
HORIZON_BASE_CONFIDENCE: Final = {
    "30m": 0.9, "1h": 0.85, "2h": 0.8, "8h": 0.7, "12h": 0.65, "24h": 0.55, "48h": 0.4,
}  # fmt: skip
XC_SPEED_KMH_BY_VARIO: Final = {  # vario m/s -> km/h (aile EN-B ; ×1.15 si finesse ≥ 9.5)
    "intermediate": {1: 8, 2: 14, 3: 19},
    "advanced": {1: 10, 2: 17, 3: 23, 4: 27},
    "expert": {1: 12, 2: 20, 3: 27, 4: 32, 5: 36},
}
TURNPOINT_RADIUS_M: Final = 400.0
GOAL_RADIUS_M: Final = 300.0


# =============================================================================================
# PARTIE 2 — Compléments backend (issus du cahier des charges, section citée)
# =============================================================================================
LEVEL_LABEL_FR: Final = {
    "beginner": "élève / brevet initial",
    "intermediate": "brevet de pilote",
    "advanced": "brevet de pilote confirmé",
    "expert": "pilote cross / compétiteur",
}

# --- §0 / §2.1 vent au déco ---------------------------------------------------------------------
SECTOR_HALF_WIDTH_DEG: Final = 11.25  # écart = angle au centre du secteur − 11,25°, borné à 0
TAILWIND_ANGLE_DEG: Final = 90.0  # écart > 90° = vent arrière
GUST_FACTOR_MIN_MEAN_KMH: Final = 15.0  # lot 2.2 : facteur de rafale = simple caution, si moyenne ≥ 15 km/h
TAKEOFF_WIND_IDEAL_KMH: Final = (5.0, 15.0)  # plage « 100 » du sous-score takeoff_wind (§9.2)
GUST_SPREAD_IDEAL_KMH: Final = 5.0
TAKEOFF_GUST_EXTRA_MAX_KMH: Final = 25.0  # rafale au déco bornée à vent_déco + 25 (lot expert 1.4)
GUST_FACTOR_DEFAULT: Final = 1.35  # facteur de rafale si le modèle ne fournit pas de rafales
SMOOTHED_TERRAIN_RADIUS_KM: Final = 2.5  # sol « lissé » du modèle ≈ moyenne MNT sur ce rayon (piège §10.1)
CREST_CHECK_ABOVE_TAKEOFF_M: Final = 300.0  # niveau des crêtes pour le dévent (§3 #8)
LEE_ANGLE_DEG: Final = 120.0
LEE_WIND_CAUTION_KMH: Final = 10.0
SYNOPTIC_CROSSWIND_CAUTION_KMH: Final = 20.0
GUST_SPREAD_ABS_MAX_KMH: Final = 15.0  # §3 #9

# --- §2.1 vent en altitude ---------------------------------------------------------------------
ALOFT_CHECK_ABOVE_CEILING_M: Final = 300.0  # niveaux atteints = déco → plafond utile + 300 m
WIND_ANY_LEVEL_CAUTION_KMH: Final = 35.0  # §3 #7 marginal 35-45
VEER_MIN_WIND_KMH: Final = 10.0
MOUNTAIN_MIN_TAKEOFF_M: Final = 800.0  # déco « en montagne » (no-go 50 km/h à 3000 m)

# --- §2.1 / §4.3 atterrissage et brises ------------------------------------------------------
LANDING_WIND_ABS_MAX_KMH: Final = 28.0  # §3 #10
LANDING_GUST_ABS_MAX_KMH: Final = 35.0
LANDING_BREEZE_CAUTION_FRACTION: Final = 0.8  # brise > seuil du niveau − 20 % → caution
VALLEY_BREEZE_HOURS_LEGAL: Final = (13, 17)
VALLEY_BREEZE_RAMP_FACTOR: Final = 1.15  # lot 5.2 : rampe ×1,15 entre 12-13 h et 17-18 h légales
VALLEY_BREEZE_RAMP_HOURS_LEGAL: Final = ((12, 13), (17, 18))
BIG_VALLEY_MAX_FLOOR_M: Final = 800.0
BIG_VALLEY_MIN_RELIEF_M: Final = 2000.0
BIG_VALLEY_RADIUS_KM: Final = 10.0
BIG_VALLEY_FALLBACK_TAKEOFF_M: Final = 1500.0  # repli sans MNT : déco > 1500 m …
BIG_VALLEY_FALLBACK_RADIUS_KM: Final = 15.0  # … à moins de 15 km

# --- §2.1 / §4 thermiques ----------------------------------------------------------------------
THERMAL_USABLE_MIN_MS: Final = 0.8  # < 0,8 m/s : non exploitable (§4.8)
THERMAL_QUALITY_MS: Final = ((0.8, "faible"), (1.5, "bon"), (2.5, "fort"), (3.5, "très fort / turbulent"))
THERMAL_IDEAL_MIN_MS: Final = 1.5  # §9.3 required : score max si vario dans [1,5 ; seuil − 0,5]
AVOID_THERMAL_MAX_MS: Final = 1.5  # §9.3 avoid : exclure si vario > 1,5 pendant le vol
REQUIRED_THERMAL_MIN_MS: Final = 0.8  # §9.3 required : exclure si vario < 0,8
BEGINNER_THERMAL_OFFPEAK_AFTER_START_H: Final = 1.0  # §2.1 beginner : avant convection + 1 h
LOCAL_THERMAL_BEGINNER_MAX_MIN: Final = 45.0
COLD_AT_CEILING_BEGINNER_C: Final = -10.0  # §3 #14
MIDHIGH_CLOUD_CAUTION_PCT: Final = 80.0  # §3 #13 voile épais
LOW_CLOUD_NOGO_PCT: Final = 80.0  # §3 #6 nuages bas ≥ 80 % avec base < déco + 300
LOW_CLOUD_NOGO_ABOVE_TAKEOFF_M: Final = 300.0
CLOUD_BASE_CAUTION_ABOVE_TAKEOFF_M: Final = 500.0
SPREAD_T_TD_NOGO_C: Final = 1.5
PRECIP_CAUTION_MM_H: Final = 0.05
CAPE_CAUTION: Final = {"cape": 300, "li": 0}  # §3 #2 marginal
CAPE_CAUTION_WINDOW_END_SOLAR_H: Final = 14.0
FOEHN_CAUTION_700HPA_KMH: Final = 25.0
FOEHN_DRY_RH_PCT: Final = 40.0
FOEHN_SECTORS_DEG: Final = {"alpes_nord": (180.0, 247.5), "alpes_sud": (292.5, 360.0)}  # S-SW / N-NW
REGIONAL_WIND_CAUTION_KMH: Final = 20.0

# Paramètres des calculs aérologiques (app/meteo)
THERMAL_TRIGGER_EXCESS_C: Final = 1.0  # §4.7 : T_max_sol + 1 °C
TRIGGER_EXCESS_FULL_SUN_W_M2: Final = 150.0  # surchauffe nulle la nuit, pleine dès 150 W/m²
WSTAR_TO_VARIO_SINK_MS: Final = 1.0  # §0 : vario ≈ max(0, W* − 1,0)
SENSIBLE_HEAT_ALBEDO: Final = 0.15
SENSIBLE_HEAT_FRACTION_RANGE: Final = (0.15, 0.50)
CONVECTION_START_MIN_BLH_AGL_M: Final = 500.0  # §4.1
CONVECTION_START_MIN_WSTAR_MS: Final = 1.2
CONVECTION_END_MIN_WSTAR_MS: Final = 1.0
STRONG_WIND_THERMAL_BREAK_KMH: Final = 20.0
MODEL_BLH_WEIGHT: Final = 0.35
FACE_THERMAL_OFFSET_H: Final = {  # §4.2, relatif à une face S
    "E": -1.5, "ESE": -1.1, "SE": -0.75, "SSE": -0.4, "S": 0.0, "SSW": 0.5, "SW": 1.0,
    "WSW": 1.5, "W": 2.0, "WNW": 2.5, "NW": 3.0, "NNW": 3.0, "N": 3.0, "NNE": 3.0, "NE": 3.0, "ENE": 3.0,
}  # fmt: skip
EAST_FACE_SECTORS: Final = ("ENE", "E", "ESE")
EAST_FACE_SHADE_SOLAR_H: Final = 12.5  # §4.3 bascule : déco E interdit après 12h30 solaire…
EAST_FACE_SYNOPTIC_EXEMPT_KMH: Final = 10.0  # … sauf vent météo d'E ≥ 10 km/h
RESTITUTION_BEFORE_SUNSET_H: Final = 1.5  # §4.4
RESTITUTION_FACES: Final = ("SSW", "SW", "WSW", "W", "WNW")
RESTITUTION_VARIO_MS: Final = 0.6

# --- §4.6 surdéveloppement ---------------------------------------------------------------------
OVERDEV_LOW_CAPE: Final = 300.0
OVERDEV_LOW_LI: Final = 2.0
OVERDEV_HIGH: Final = {"cape": 800, "li": 0}
OVERDEV_MODERATE_RH700_PCT: Final = 70.0
OVERDEV_BASE_BELOW_DRY_TOP_M: Final = 1000.0
OVERDEV_DELAY_AFTER_FIRST_CU_H: Final = 3.5
OVERDEV_MODERATE_END_BEFORE_H: Final = 1.0
OVERDEV_HIGH_MAX_DURATION_MIN: Final = 90.0
OVERDEV_HIGH_EXPERT_RETURN_SOLAR_H: Final = 13.0

# --- §2.2 soaring --------------------------------------------------------------------------------
RIDGE_MIN_KMH_BY_LEVEL: Final = by_level(15, 15, 15, 13)  # tableau §2.2 (expert tient dès 13 km/h)
RIDGE_GUST_MAX_KMH: Final = by_level(22, 26, 32, 35)
RIDGE_GUST_SPREAD_MAX_KMH: Final = 8.0  # §5.3 vent régulier
RIDGE_MAX_DURATION_MIN: Final = by_level(30, 90, 90, 90)  # §6
RIDGE_BEAT_HALF_LENGTH_KM: Final = 0.6
RIDGE_SOARING_HEIGHT_M: Final = 120.0

# --- §2.3 / §5 finesse et routage --------------------------------------------------------------
AIR_SPEED_TRIM_HIGH_PERF_KMH: Final = 39.0
HIGH_PERF_GLIDE_RATIO: Final = 9.5
LANDING_ARRIVAL_MARGIN_MAX_FRACTION: Final = 0.25  # lot 2.1 : marge eff. = min(marge, 0,25 × dénivelé)
GLIDE_RATIO_SUBSCORE: Final = ((0.75, 100.0), (0.90, 60.0), (0.95, 40.0), (1.0, 0.0))  # r = required/available
GLIDE_CAUTION_RATIO: Final = 0.90  # GLIDE_MARGIN caution au-delà ; danger (no-go) si r > 1
TOP_LANDING_MAX_DROP_M: Final = 50.0  # lot 2.4c : atterro ≥ alt déco − 50 m = top landing
GLIDE_LEE_PENALTY: Final = 0.9
TERRAIN_CLEARANCE_M: Final = 50.0
GLIDE_CHECK_STEP_KM: Final = 0.5
SAFETY_ALT_BELOW_CEILING_M: Final = 300.0
XC_WINDOW_USAGE: Final = 0.85  # backend : objectif de distance = 85 % de la fenêtre (marge, médiane ≠ record)
XC_MIN_DURATION_MIN: Final = 60.0  # backend : en dessous, un cross n'a pas de sens
XC_SPEED_HIGH_PERF_FACTOR: Final = 1.15
XC_MIN_EFFECTIVE_SPEED_KMH: Final = 8.0
XC_TRIANGLE_WIND_FACTOR: Final = 0.7
XC_DOWNWIND_FACTOR: Final = 0.8
XC_FAI_MAX_WIND_KMH: Final = 20.0
XC_FAI_MIN_LEG_RATIO: Final = 0.28
XC_FREE_DISTANCE_WIND_KMH: Final = (15.0, 30.0)
XC_FINAL_GLIDE_MIN: Final = 10.0
XC_MIN_INITIAL_CLIMB_MIN: Final = 10.0
XC_LANDING_AFTER_CONVECTION_END_MIN: Final = 30.0
FLIGHT_TYPE_MIN_LEVEL: Final = {
    "local": "beginner",
    "ridge_soaring": "beginner",
    "cross_country": "intermediate",
    "fai_triangle": "advanced",
    "free_distance": "expert",
}
TAKEOFF_RADIUS_M: Final = 400.0
THERMAL_TRIGGER_RADIUS_M: Final = 400.0
LOCAL_LOOP_KM: Final = (3.0, 10.0)
PLOUF_LOSE_HEIGHT_POINT_KM: Final = 0.4
PLOUF_LOSE_HEIGHT_MIN_AGL_M: Final = 200.0
ALTERNATE_LANDING_SEARCH_KM: Final = 15.0
ASSOCIATED_LANDING_MAX_KM: Final = 8.0  # backend : association déco ↔ atterro si la source ne la donne pas
ASSOCIATED_LANDING_MIN_DROP_M: Final = 150.0

# --- Lot expert 2 : fenêtres temporelles des no-go convectifs, créneau, coucher ---------------
THUNDERSTORM_CHECK_AFTER_LANDING_H: Final = 1.0  # CAPE/LI évalués sur [déco, atterrissage + 1 h]
CONVECTIVE_PRECIP_CHECK_AFTER_LANDING_H: Final = 2.0  # précipitations sur [déco, atterrissage + 2 h]
OVERDEV_MODERATE_WINDOW_AFTER_LANDING_H: Final = 2.0  # moderate → marginal si surdév ∈ [déco, atterro + 2 h]
WINDOW_START_BEFORE_TARGET_MIN: Final = 30.0  # créneau : début ∈ [cible − 30 min, cible + 3 h]
WINDOW_START_AFTER_TARGET_H: Final = 3.0
SUNSET_NOGO_AFTER: Final = True  # atterrissage après le coucher → no-go ; < 30 min avant → caution
BEACON_GUST_HORIZONS: Final = ("30m", "1h")  # rafale retenue = max(rafale balise 10 min, rafale fusionnée)

# --- §6 durées -----------------------------------------------------------------------------------
PLOUF_EXTRA_MIN: Final = 3.0
RESTITUTION_DURATION_FACTOR: Final = 1.75  # × 1,5 à 2
LANDING_BEFORE_SUNSET_MIN: Final = 30.0  # caution si atterrissage < 30 min avant coucher

# --- §7.4 espaces aériens et zones sensibles ----------------------------------------------------
CEILING_MARGIN_BELOW_AIRSPACE_M: Final = 100.0
AIRSPACE_CAUTION_LATERAL_KM: Final = 1.0
AIRSPACE_CAUTION_VERTICAL_M: Final = 100.0
AIRSPACE_REPORT_RADIUS_KM: Final = 10.0
AIRSPACE_FORBIDDEN_CLASSES: Final = ("A", "B", "C", "D")  # lot 2.15 : interdits sans clairance (par CLASSE)
AIRSPACE_FORBIDDEN_TYPES: Final = ("P", "PROHIBITED")  # zones interdites quel que soit la classe
AIRSPACE_INFO_TYPES: Final = ("SIV", "FIS", "FIR", "UIR", "ACC")  # information seulement
AIRSPACE_ACTIVATION_TYPES: Final = ("R", "ZRT", "D", "Q", "TRA", "TSA", "RESTRICTED", "DANGER")
PARK_MIN_HEIGHT_AGL_M: Final = 1000.0  # cœurs de parcs nationaux
SENSITIVE_AREA_DEFAULT_HEIGHT_AGL_M: Final = 300.0  # zone faune sans hauteur renseignée

# --- §8.2 balises, nowcasting, confiance ---------------------------------------------------------
NOWCAST_MAX_HORIZON_MIN: Final = 120
BEACON_MAX_DISTANCE_KM: Final = 5.0
BEACON_SEARCH_RADIUS_KM: Final = 15.0
BEACON_MAX_ALT_DIFF_M: Final = 300.0
BEACON_STALE_MIN: Final = 30.0
BEACON_CONTRADICTION_KMH: Final = 10.0
BEACON_CONTRADICTION_DEG: Final = 45.0
BEACON_COHERENT_KMH: Final = 5.0
BEACON_COHERENT_DEG: Final = 30.0
NOWCAST_MAX_SPEED_BIAS_KMH: Final = 25.0
NOWCAST_MAX_DIR_BIAS_DEG: Final = 90.0
DISPERSION_SPEED_SIGMA_KMH: Final = (3.0, 10.0)
DISPERSION_SPEED_FACTOR_AT_MAX: Final = 0.6
DISPERSION_DIR_SIGMA_DEG: Final = 45.0
DISPERSION_DIR_FACTOR: Final = 0.7
BEACON_COHERENT_FACTOR: Final = 1.1
BEACON_CONTRADICTORY_FACTOR: Final = 0.8
CONFIDENCE_MAX: Final = 0.95
MOCK_CONFIDENCE_CAP: Final = 0.3  # lot 2.12 : confiance AFFICHÉE plafonnée en mock ; verdict sur la valeur brute
SINGLE_SOURCE_NOGO_CONFIDENCE: Final = 0.6

# --- §9 score -----------------------------------------------------------------------------------
SAFETY_CRITERIA: Final = ("takeoff_wind", "wind_aloft", "landing", "convective_stability")
SAFETY_CAP_OFFSET: Final = 40.0  # score ≤ 40 + min(sous-scores sécurité)
CALM_TAKEOFF_SUBSCORE: Final = 80.0
ALLOWED_NO_THERMAL_SUBSCORE: Final = 70.0
MAX_PLANS_PER_TAKEOFF: Final = 2
UNKNOWN_SITE_DIFFICULTY: Final = "intermediate"  # §8.1

# --- Régions (heuristiques bbox : min_lat, min_lon, max_lat, max_lon) ---------------------------
REGIONS: Final = {
    "alpes_nord": (45.0, 5.5, 46.6, 7.9),
    "alpes_sud": (43.6, 5.5, 45.0, 7.8),
    "bise": (45.6, 5.7, 46.6, 7.0),  # bassin genevois / Annecy / Chablais
    "mistral": (43.2, 4.2, 45.0, 5.9),  # vallée du Rhône / Provence occidentale
}
BISE_SECTOR_DEG: Final = (10.0, 80.0)
MISTRAL_SECTOR_DEG: Final = (320.0, 30.0)

# --- §7.5 radio / urgence -----------------------------------------------------------------------
RADIO_FREQ_MHZ: Final = "143,9875"
EMERGENCY_NUMBER: Final = "112"


# =============================================================================================
# Fonctions utilitaires (aucune logique métier cachée : uniquement des lectures de tables)
# =============================================================================================
def level_index(level: str) -> int:
    return LEVELS.index(level)


def interp_aloft_threshold(altitude_m: float, level: str) -> float:
    """Seuil de vent en altitude (§2.1) interpolé entre paliers ; sous 1500 m : palier 1500."""
    keys = sorted(WIND_ALOFT_MAX_KMH)
    if altitude_m <= keys[0]:
        return float(WIND_ALOFT_MAX_KMH[keys[0]][level])
    if altitude_m >= keys[-1]:
        return float(WIND_ALOFT_MAX_KMH[keys[-1]][level])
    for a, b in zip(keys, keys[1:], strict=False):
        if a <= altitude_m <= b:
            va, vb = WIND_ALOFT_MAX_KMH[a][level], WIND_ALOFT_MAX_KMH[b][level]
            return float(va + (vb - va) * (altitude_m - a) / (b - a))
    return float(WIND_ALOFT_MAX_KMH[keys[-1]][level])


def xc_speed_kmh(vario_ms: float, level: str, glide_ratio: float) -> float:
    """Vitesse de croisière §5.5 interpolée ; 0 si le niveau ne fait pas de cross ou vario hors table."""
    table = XC_SPEED_KMH_BY_VARIO.get(level)
    if not table or vario_ms <= 0:
        return 0.0
    keys = sorted(table)
    v = min(vario_ms, float(keys[-1]))
    if v <= keys[0]:
        speed = table[keys[0]] * v / keys[0]
    else:
        speed = float(table[keys[-1]])
        for a, b in zip(keys, keys[1:], strict=False):
            if a <= v <= b:
                speed = table[a] + (table[b] - table[a]) * (v - a) / (b - a)
                break
    if glide_ratio >= HIGH_PERF_GLIDE_RATIO:
        speed *= XC_SPEED_HIGH_PERF_FACTOR
    return speed


def trim_speed_kmh(glide_ratio: float) -> float:
    return AIR_SPEED_TRIM_HIGH_PERF_KMH if glide_ratio >= HIGH_PERF_GLIDE_RATIO else AIR_SPEED_TRIM_KMH
