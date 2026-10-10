"""TOUS les seuils métier de Paraglide Manager, en un seul endroit.

Source : docs/expert/cahier-des-charges-pilote.md — §2 seuils par niveau, §3 no-go, §4 aérologie,
§5 routage, §6 durées, §8 balises/confiance, §9 score/verdict. La partie 1 reprend À L'IDENTIQUE le
bloc YAML du §11 (mêmes clés, en MAJUSCULES, mêmes valeurs). La partie 2 regroupe les compléments
nécessaires au backend (tous issus du cahier des charges ou explicitement signalés « backend »).

Unités : km/h, m AMSL (sauf mention _agl), m/s, degrés « d'où vient le vent », minutes.
Ce module n'importe que la bibliothèque standard (il est importé partout, y compris par app/meteo).
"""

from __future__ import annotations

from itertools import pairwise
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
# §12.9 (a) : valeurs complétées de l'horizon 15m (remplacent celles du §11)
HORIZON_BEACON_WEIGHT: Final = {
    "15m": 0.85,
    "30m": 0.7,
    "1h": 0.5,
    "2h": 0.3,
    "8h": 0.1,
    "12h": 0.0,
    "24h": 0.0,
    "48h": 0.0,
}
HORIZON_BASE_CONFIDENCE: Final = {
    "15m": 0.92, "30m": 0.9, "1h": 0.85, "2h": 0.8, "8h": 0.7, "12h": 0.65, "24h": 0.55, "48h": 0.4,
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
# revue 7.3 : orientation de déco « incertaine » dès 6 secteurs principaux sur 8 (source « tous secteurs ») ; elle est
# alors déduite de l'exposition MNT ± 22,5° ; un secteur à plus de 90° de l'exposition MNT est écarté
ORIENTATION_UNCERTAIN_MIN_SECTORS: Final = 6
ORIENTATION_MAX_FROM_DEM_ASPECT_DEG: Final = 90.0
ORIENTATION_DEM_STEP_M: Final = 150.0  # exposition MNT : 4 points à ± 150 m (N, S, E, O) du déco
ORIENTATION_DEM_MIN_SLOPE_PCT: Final = 10.0  # en dessous, l'exposition MNT n'est pas significative (replat, sommet)
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
# lot 6.9 : durée réaliste d'un local thermique (vario moyen m/s → durée max min ; plafond bas → 45 min)
LOCAL_THERMAL_DURATION_CAPS: Final = ((1.2, 60.0), (2.0, 120.0))
LOCAL_THERMAL_LOW_CEILING_M: Final = 400.0
LOCAL_THERMAL_LOW_CEILING_MAX_MIN: Final = 45.0
LOCAL_TRIGGER_MIN_HEIGHT_M: Final = 150.0  # revue 7.8 : altitude de sécurité d'un déclencheur ≥ relief + 150 m
LOCAL_TRIGGER_MAX_GLIDE_RATIO: Final = 0.80  # lot 6.6 : déclencheur gardé si r ≤ 0,80 vers un atterro
ALLOWED_GENTLE_THERMAL_FRACTION: Final = 0.6  # lot 6.4 : « allowed » → 100 jusqu'à 60 % du seuil
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
# décision expert (revue finale 7.13, CDC §2.3 rév. 4) : plané direct déco → atterro officiel ASSOCIÉ PAR LA SOURCE
# (FFVL, PGE, fixture ; jamais une association déduite par proximité), relief vérifié : k = 0,80 à tous les niveaux
GLIDE_K_ASSOCIATED_PAIR: Final = 0.80
TERRAIN_CLEARANCE_M: Final = 50.0
GLIDE_CHECK_STEP_KM: Final = 0.5
SAFETY_ALT_BELOW_CEILING_M: Final = 300.0
XC_WINDOW_USAGE: Final = 0.85  # backend : objectif de distance = 85 % de la fenêtre (marge, médiane ≠ record)
# revue 7.11 (§4.8) : 0,8-1,5 m/s = local doux ; un cross demande au moins 1,5 m/s (1,2 pour un expert)
XC_MIN_VARIO_MS: Final = by_level(None, 1.5, 1.5, 1.2)
XC_RELIEF_NAME_RADIUS_KM: Final = 2.0  # point tournant nommé d'après le sommet connu le plus proche
XC_MIN_DURATION_MIN: Final = 60.0
SINGLE_MODEL_CONFIDENCE_FACTOR: Final = 0.8  # revue (m) : moins de 2 modèles couvrent l'heure cible
# §4.5 rotor sous le vent (revue 7.17) : vent à la crête ≥ 15 km/h ; 5 × la hauteur du relief (15-25 km/h), 10 × au-delà
ROTOR_MIN_CREST_WIND_KMH: Final = 15.0
ROTOR_STRONG_WIND_KMH: Final = 25.0
ROTOR_MIN_RELIEF_M: Final = 150.0  # relief significatif au-dessus du point
ROTOR_SEARCH_KM: Final = 10.0
ROTOR_STEP_KM: Final = 0.25
UNCHECKED_RULES_TEXT: Final = (
    "Non vérifié par l'outil : venturi aux cols et brèches (§4.5), écart de pression entre versants du foehn (§3 #4), "
    "hauteur d'arrivée sur la face suivante d'un cross (§5.4), finesse −10 % sous le vent (§2.3)"
)  # backend : en dessous, un cross n'a pas de sens
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

# --- §12.6 / §12.7 compléments backend (décollage libre, atterros candidats, cône de finesse) ----------
FREE_TAKEOFF_DEM: Final = {"grid_n": 5, "grid_step_m": 100.0}  # grille MNT autour du point (1 appel Open-Meteo)
FREE_TAKEOFF_FLIGHT_TYPES: Final = ("local", "cross_country")  # pas de soaring (top landing) depuis un point libre
# revue : altitude saisie d'un décollage libre comparée au MNT (avertissement au-delà de 100 m ; au-delà de 300 m,
# altitude retenue pour le plané = min(saisie, MNT + 50 m))
CUSTOM_ELEVATION_WARN_DIFF_M: Final = 100.0
CUSTOM_ELEVATION_MAX_DIFF_M: Final = 300.0
CUSTOM_ELEVATION_CLIFF_M: Final = 50.0
GLIDE_CONE: Final = {"bearings": 36, "step_km": 0.25, "max_km": 40.0, "clearance_from_km": 0.5}
LANDING_SEARCH_RADIUS_KM: Final = 20.0  # atterros candidats cherchés autour d'un décollage libre
LANDING_MAX_CANDIDATES: Final = 40  # au plus 40 candidats évalués (les plus proches, dans la portée de plané)
LANDING_MAX_IN_ANALYSIS: Final = 8  # LandingCandidate publiés dans un plan / une analyse
LANDING_FORECAST_CLUSTERS: Final = 4  # points de prévision pour les atterros candidats (quota Open-Meteo)
LANDING_FORECAST_CLUSTER_KM: Final = 3.0  # candidats à moins de 3 km d'un point de prévision : même prévision
OBSTACLE_TYPICAL_HEIGHT_M: Final = {"forest": 20.0, "building": 8.0, "power_line": 15.0, "aerialway": 15.0}
OSM_OBSTACLE_SEARCH_M: Final = {"power_line": 300, "trees_buildings": 60, "water": 200, "road": 60}  # 2 × minima
FIELD_MIN_DETECT_M: Final = (100.0, 30.0)  # champ OSM retenu si ≥ 100 × 30 m (minimum du niveau expert)
PGE_COMMUNITY_USAGE: Final = "occasional"  # atterro non officiel documenté par les pilotes sur ParaglidingEarth
ACCESS_TEXT_ROAD_M: Final = 150.0  # accès décrit (« route », « parking ») sans distance chiffrée
UNKNOWN_SIZE_SUBSCORE: Final = 30.0  # taille d'un atterro communautaire non renseignée
UNKNOWN_SLOPE_SUBSCORE: Final = 50.0  # pente non mesurée (MNT indisponible)
LANDING_WIND_UNKNOWN_SUBSCORE: Final = 50.0

# --- §7.5 radio / urgence -----------------------------------------------------------------------
RADIO_FREQ_MHZ: Final = "143,9875"
EMERGENCY_NUMBER: Final = "112"


# =============================================================================================
# PARTIE 3 — Bloc YAML du §12.9 (copie fidèle : balises, 15 min, tendance, décollage libre,
# atterros non officiels). Mêmes clés en MAJUSCULES, mêmes valeurs.
# =============================================================================================
# --- (a) balises, horizon 15 min, tendance --------------------------------------------------------
HORIZON_MINUTES_ADD: Final = {"15m": 15}  # ajouté à HORIZON_MINUTES (models.py)
# HORIZON_BEACON_WEIGHT et HORIZON_BASE_CONFIDENCE : partie 1 (valeurs 15m incluses)
# Δt (min) depuis reference_time → poids nominal ; déco : début du créneau ; atterro : ARRIVÉE ; interpolation linéaire
BEACON_WEIGHT_BY_MINUTES: Final = {0: 0.90, 15: 0.85, 30: 0.70, 60: 0.50, 120: 0.30, 480: 0.10, 720: 0.0}
BEACON_GUST_HORIZONS: Final = ("15m", "30m", "1h")  # rafale retenue = max(rafale balise 10 min, rafale fusionnée)
NOWCAST_HORIZONS: Final = ("15m", "30m", "1h", "2h")  # horizons où NO_LANDING_BEACON / STALE_BEACONS existent
NOWCAST_WINDOW_START_MIN: Final = {
    "15m": (-10, 45),
    "30m": (-15, 60),
    "1h": (-30, 90),
}  # bornes de window.start / cible
NOWCAST_MIN_LEAD_MIN: Final = 10  # window.start ≥ reference_time + 10 min
BEACON_FRESHNESS_MIN: Final = {"full_weight": 10, "stale": 30, "factor_at_stale": 0.3}  # > 30 min : périmée (poids 0)
BEACON_REPRESENTATIVE_MIN_FACTOR: Final = 0.3  # f_distance × f_altitude × f_alt_inconnue × f_fraîcheur
BEACON_SUSPECT_MODEL_MIN_KMH: Final = 12  # balise à 0 (rafale 0 ou nulle) et modèle ≥ 12 → poids 0
BEACON_OUTLIER: Final = {"deviation_kmh": 10, "factor": 0.3}  # ≥ 2 balises représentatives : écart à la médiane > 10
TAKEOFF_BEACON_ATTACH: Final = {
    "distance_km": {"full": 1.0, "max": 5.0, "factor_at_max": 0.4},
    # 300-600 m : biais calculé au vent modèle à l'altitude de la balise (composante synoptique)
    "alt_diff_m": {"full": 100, "reduced": 300, "factor_at_reduced": 0.5, "synoptic_max": 600, "factor_synoptic": 0.3},
    "name_bonus": {"keywords": ("déco", "deco", "décollage", "decollage", "take off", "takeoff"), "site_name": True,
                   "full_distance_km": 2.0},
    "wrong_role": {"keywords": ("atterro", "attero", "atterrissage", "landing"), "max_alt_diff_m": 100},
}  # fmt: skip
LANDING_BEACON_ATTACH: Final = {
    "distance_km": {"full": 1.5, "max": 3.0, "factor_at_max": 0.5},
    "alt_diff_m": {"full": 50, "max": 150, "factor_at_max": 0.5},
    "name_bonus": {"keywords": ("atterro", "attero", "atterrissage", "landing", "posé"), "site_name": True,
                   "full_distance_km": 2.5, "max_distance_km": 4.0, "max_alt_diff_m": 200},
    "wrong_role": {"keywords": ("déco", "deco", "décollage", "sommet", "crête", "col", "top"), "max_alt_diff_m": 50},
    "same_valley_relief_margin_m": 100,  # aucun point MNT du segment au-dessus de max(alt balise, alt atterro) + 100 m
}  # fmt: skip
UNKNOWN_BEACON_ALTITUDE: Final = {
    "dem_factor": 0.8,  # altitude prise sur le MNT
    "no_dem_factor": 0.5,
    "no_dem_takeoff_max_distance_km": 2.0,
    "no_dem_landing": {"requires_name_bonus": True, "max_distance_km": 1.5},  # sinon non représentative
}
TREND_1H: Final = {
    "min_window_min": 45,
    "min_samples": 4,
    "wind_increase_kmh_per_h": {"caution": 5, "danger": 20},  # strictement supérieur ; r = speed_change × 60 / window
    "caution_min_ratio_to_threshold": 0.5,  # caution seulement si max(v_fusion, v_ext) ≥ 50 % du seuil, sinon info
    "rotation": {"caution_deg": 60, "min_wind_kmh": 8},
    "reversal": {
        "deg": 120,
        "min_wind_kmh": 10,
        "level": {"beginner": "danger", "intermediate": "danger", "advanced": "caution", "expert": "caution"},
    },
    "gust_max_over_threshold_kmh": {
        "caution": 0,
        "danger": 10,
    },  # gust_max_kmh > seuil rafale du niveau (+ 10 → danger)
    "extrapolate_horizons": ("15m", "30m", "1h"),
    "extrapolate_max_minutes": 60,
    "extrapolate_cap_kmh": 15,
    "extrapolate_down": False,
}
TREND_IMPACT: Final = {  # niveau du Risk par horizon ; horizon absent = ignoré
    "wind_increase": {"15m": "caution", "30m": "caution", "1h": "caution", "2h": "info"},
    "wind_increase_high": {"15m": "danger", "30m": "danger", "1h": "danger", "2h": "caution"},
    "rotation": {"15m": "caution", "30m": "caution", "1h": "info"},
    "reversal": {"15m": "by_level", "30m": "by_level", "1h": "caution", "2h": "info"},
    "gust_max": {"15m": "caution", "30m": "caution", "1h": "caution", "2h": "info"},
    "gust_max_high": {"15m": "danger", "30m": "danger", "1h": "caution", "2h": "info"},
}
NO_LANDING_BEACON: Final = {
    "level": {"15m": "caution", "30m": "caution", "1h": "caution", "2h": "info"},
    "caution_legal_hours": (12, 18),  # arrivée hors de cette plage → info
    "blocking": False,  # ajouté à NON_BLOCKING_CAUTIONS
    "landing_marginal_band_factor": {"15m": 0.9, "30m": 0.9, "1h": 0.9},  # bande marginale atterro dès 72 %
    "confidence_factor": {"15m": 0.9, "30m": 0.9, "1h": 0.9, "2h": 0.95},
}
LANDING_BEACON_CONFIDENCE_FACTOR: Final = {"coherent": 1.0, "contradictory": 0.85}
RISK_CODES_ADD: Final = ("NO_LANDING_BEACON", "WIND_SHIFT", "FREE_TAKEOFF", "UNOFFICIAL_LANDING", "DETECTED_FIELD")
NON_BLOCKING_CAUTIONS_ADD: Final = ("NO_LANDING_BEACON",)

# --- (b) décollage libre (mode custom_takeoff) -----------------------------------------------------
FREE_TAKEOFF: Final = {
    "allowed_levels": ("intermediate", "advanced", "expert"),  # jamais beginner
    "site_difficulty": "intermediate",  # plan.difficulty ≥ intermediate
    "risk_level": by_level("danger", "caution", "info", "info"),  # FREE_TAKEOFF
    "best_verdict": {"intermediate": "marginal", "advanced": "go", "expert": "go"},
    "wind_max_kmh": {"intermediate": 15, "advanced": 20, "expert": 25},
    "gust_max_kmh": {"intermediate": 20, "advanced": 25, "expert": 30},
    "gust_spread_max_kmh": {"intermediate": 8, "advanced": 10, "expert": 12},
    "wind_slope_angle_max_deg": {"intermediate": 20, "advanced": 30, "expert": 45},  # sans tolérance de secteur
    "tailwind_max_kmh": 3,  # vent arrière ≥ 3 km/h → TAILWIND danger
    "calm_kmh": 5,  # vent nul accepté seulement si pente ≥ min_without_headwind
    "slope_pct": {
        "min": 15,  # avec vent de face ≥ headwind_for_gentle_kmh
        "min_without_headwind": 25,
        "headwind_for_gentle_kmh": 10,
        "ideal": (30, 50),
        "max": {"intermediate": 60, "advanced": 70, "expert": 80},
    },
    "slope_sampling": {"downslope_m": 150, "step_m": 50},
    "axis_profile": {"distance_m": 300, "max_slope_line": 0.1667},  # aucun point MNT au-dessus de alt_déco − d/6
    "orientation_halfwidth_deg": 22.5,  # orientations déduites de l'exposition MNT
    "clear_area_m": {"length": 30, "width": 15},  # non vérifiable au MNT : contrôle obligatoire
    "refusal_beginner": "Décollage libre non proposé au niveau élève : uniquement sous la responsabilité d'un moniteur "
    "présent sur place.",
    "warning": "Décollage libre, hors site officiel : pente, obstacles et vent ne sont vérifiés par personne. "
               "Reconnais le "
    "terrain à pied, vérifie l'autorisation, et ne décolle qu'une fois tous les contrôles faits.",
    "mandatory_checks": (
        "Autorisation du propriétaire ou de la commune ; pas de décollage en cœur de parc national, réserve naturelle, "
        "arrêté de biotope ou zone Biodiv'Sports active.",
        "Reconnaissance à pied de l'aire et de l'axe : pierres, souches, clôtures, câbles, téléskis, lignes, "
        "randonneurs, "
        "bétail ; prévoir de quoi interrompre le décollage.",
        "Observer le vent 5 min (manche, rubalise, herbes) : de face et régulier, ni rotor, ni dévent, ni cycles "
        "thermiques "
        "trop forts.",
        "Atterro repéré à vue avant de gonfler, dans le cône de finesse, plus un atterro de secours.",
        "Espaces aériens, NOTAM et zones sensibles vérifiés ; prévenir un proche (point exact, heure, atterro prévu) ; "
        "radio 143,9875.",
        "Matériel (aile légère, secours, casque) et prévol complète après la marche (sueur, fatigue, hydratation).",
    ),
}

# --- (c) atterros non officiels --------------------------------------------------------------------
LANDING_POLICY_KINDS: Final = {
    "official_only": ("official",),
    "include_community": ("official", "community"),
    "include_fields": ("official", "community", "field"),
}
BEGINNER_LANDING_POLICY: Final = "official_only"  # forcé, avec warning « Élève : seuls les atterros officiels… »
LANDING_KIND_USE: Final = {  # main = principal possible ; alternate = secours seulement ; never
    "official": by_level("main", "main", "main", "main"),
    "community": by_level("never", "main_if_frequent", "main", "main"),  # sinon alternate
    "field": by_level("never", "alternate", "main_marginal", "main_marginal"),
}
UNOFFICIAL_LANDING_MIN: Final = {  # community et field ; un critère manquant → candidat exclu
    "length_m": {"intermediate": 150, "advanced": 120, "expert": 100},
    "width_m": {"intermediate": 50, "advanced": 40, "expert": 30},
    "slope_pct_max": {"intermediate": 8, "advanced": 10, "expert": 12},
    "power_line_clearance_m": {"intermediate": 150, "advanced": 100, "expert": 100},
    "tree_building_clearance_m": {"intermediate": 30, "advanced": 25, "expert": 20},
    "water_clearance_m": {"intermediate": 100, "advanced": 50, "expert": 50},
    "road_clearance_m": 30,
    "approach_free_m": 150,  # aucun obstacle > 10 m dans l'axe de finale
    "approach_obstacle_length_factor": 5,  # longueur utile = longueur − 5 × hauteur de l'obstacle en bout de finale
    "long_axis_vs_wind_max_deg": 45,
    "unknown_clearance_subscore": 50,  # obstacle non cartographié : pas d'exclusion, sous-score 50 + warning
}
UNOFFICIAL_GLIDE: Final = {
    "available_factor": {"community": 0.90, "field": 0.80},  # required ≤ available × facteur (en plus de glide_k)
    "arrival_height_min_m": {
        "community": {"intermediate": 150, "advanced": 120, "expert": 100},
        "field": {"intermediate": 200, "advanced": 150, "expert": 150},
    },
}
LANDING_CANDIDATE_WEIGHTS: Final = {
    "glide_margin": 25, "obstacles": 20, "wind_at_arrival": 15, "size": 10, "community_usage": 10, "slope": 8,
    "access": 7, "beacon": 5,
}  # fmt: skip
LANDING_CATEGORY_BONUS: Final = {"official": 15, "community": 5, "field": 0}
COMMUNITY_USAGE_SUBSCORE: Final = {"official": 100, "frequent": 80, "occasional": 50, "unknown": 20, "field": 0}
ACCESS_SUBSCORE_BY_ROAD_M: Final = {200: 100, 1000: 50}  # > 1000 m : 0 ; inconnu : 30
ACCESS_UNKNOWN_SUBSCORE: Final = 30
SIZE_SUBSCORE_FULL_AT: Final = 2.0  # × dimensions minimales
OBSTACLE_SUBSCORE_FULL_AT: Final = 2.0  # × distances minimales
FIELD_CROP_SEASON_MONTHS: Final = (5, 6, 7, 8, 9)
UNOFFICIAL_WARNINGS: Final = {
    "community": "Non officiel : repérage et autorisation du propriétaire à vérifier. Atterro utilisé par les pilotes, "
    "mais non validé par la FFVL : vérifie l'état du terrain (cultures, bétail, clôtures, lignes) et repère-le en vol "
    "avant de t'engager.",
    "field": "Champ détecté automatiquement, jamais repéré : à vérifier sur place. Non officiel : repérage et "
    "autorisation du propriétaire à vérifier. Les lignes électriques, les clôtures, les cultures hautes et la pente ne "
    "sont pas toutes visibles sur la carte : survole-le à 150 m au moins et garde une autre option.",
    "field_season": "Saison des cultures et des foins : on ne se pose pas dans un champ cultivé ou en herbe haute "
    "(dégâts, risque de culbute).",
    "unknown_clearance": "Lignes électriques non cartographiées : à repérer en vol.",
    "beginner_policy": "Élève : seuls les atterros officiels sont proposés.",
}
RISK_LEVELS: Final = {
    "UNOFFICIAL_LANDING": {"intermediate": "caution", "advanced": "info", "expert": "info",
                           "only_reachable_beginner": "danger"},  # atterro principal community
    "DETECTED_FIELD": {"main": "caution", "only_reachable_beginner_intermediate": "danger", "alternate_only": "info"},
    "FREE_TAKEOFF": by_level("danger", "caution", "info", "info"),
}  # fmt: skip


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
    for a, b in pairwise(keys):
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
        for a, b in pairwise(keys):
            if a <= v <= b:
                speed = table[a] + (table[b] - table[a]) * (v - a) / (b - a)
                break
    if glide_ratio >= HIGH_PERF_GLIDE_RATIO:
        speed *= XC_SPEED_HIGH_PERF_FACTOR
    return speed


def trim_speed_kmh(glide_ratio: float) -> float:
    return AIR_SPEED_TRIM_HIGH_PERF_KMH if glide_ratio >= HIGH_PERF_GLIDE_RATIO else AIR_SPEED_TRIM_KMH


def beacon_weight_by_minutes(dt_min: float) -> float:
    """Poids nominal d'une balise (§12.1) pour Δt minutes après reference_time, interpolé linéairement."""
    pts = sorted(BEACON_WEIGHT_BY_MINUTES.items())
    x = max(0.0, dt_min)
    if x >= pts[-1][0]:
        return float(pts[-1][1])
    for (x0, y0), (x1, y1) in pairwise(pts):
        if x0 <= x <= x1:
            return float(y0 + (y1 - y0) * (x - x0) / (x1 - x0))
    return float(pts[0][1])  # pragma: no cover
