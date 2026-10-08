"""TOUS les seuils métier de Paraglide Manager, en un seul endroit.

Source : docs/expert/cahier-des-charges-pilote.md (§2 seuils par niveau, §3 no-go, §4 aérologie,
§5 routage, §6 durées, §8 pondération balises/confiance, §9 score/verdict, §11 valeurs proposées).
Les valeurs sont des défauts réglables par le pilote expert : ne JAMAIS dupliquer un seuil ailleurs.

Unités : km/h, m AMSL (sauf mention _agl), m/s, degrés « d'où vient le vent », minutes.
Ce module ne doit importer que la bibliothèque standard (il est importé partout).
"""

from __future__ import annotations

from typing import Final

LEVELS: Final = ("beginner", "intermediate", "advanced", "expert")
LEVEL_LABEL_FR: Final = {
    "beginner": "élève / brevet initial",
    "intermediate": "brevet de pilote",
    "advanced": "brevet de pilote confirmé",
    "expert": "pilote cross / compétiteur",
}


def by_level(beginner, intermediate, advanced, expert) -> dict:
    return {"beginner": beginner, "intermediate": intermediate, "advanced": advanced, "expert": expert}


# ---------------------------------------------------------------------------------------------
# §0 / §2.1 — Vent au décollage
# ---------------------------------------------------------------------------------------------
CALM_WIND_KMH: Final = 5.0  # vent moyen < 5 km/h : direction non significative (ni travers ni arrière)
SECTOR_HALF_WIDTH_DEG: Final = 11.25  # demi-largeur d'un secteur de la rose 16 points
TAKEOFF_WIND_MAX_KMH: Final = by_level(15, 20, 25, 30)
TAKEOFF_WIND_IDEAL_KMH: Final = (5.0, 15.0)  # plage « 100 » du sous-score takeoff_wind (§9.2)
TAKEOFF_GUST_MAX_KMH: Final = by_level(20, 25, 30, 35)
GUST_SPREAD_MAX_KMH: Final = by_level(8, 10, 12, 15)  # écart rafale − moyenne
GUST_FACTOR_MAX: Final = by_level(1.4, 1.5, 1.6, 1.7)  # rafale / moyenne, si moyenne ≥ 10 km/h
GUST_FACTOR_MIN_MEAN_KMH: Final = 10.0
CROSSWIND_ANGLE_MAX_DEG: Final = by_level(30, 45, 60, 75)  # écart angulaire au secteur le plus proche
CROSSWIND_COMPONENT_MAX_KMH: Final = by_level(6, 10, 13, 16)  # v·sin(écart)
TAILWIND_MAX_KMH: Final = by_level(0, 0, 5, 8)  # vent arrière toléré (déco pentu) ; 0 = interdit hors vent nul
TAILWIND_ANGLE_DEG: Final = 90.0  # écart > 90° = vent arrière
# Vent au déco = moyenne vectorielle entre le vent 10 m du modèle (relief lissé) et le vent « air libre »
# interpolé dans les niveaux de pression à l'altitude réelle du déco (piège §10.1).
TAKEOFF_FREE_AIR_WEIGHT: Final = 0.5
GUST_FACTOR_FREE_AIR: Final = 1.35  # facteur de rafale appliqué au vent air libre si le modèle n'en donne pas

# ---------------------------------------------------------------------------------------------
# §2.1 — Vent en altitude, gradient, cisaillement
# ---------------------------------------------------------------------------------------------
WIND_ALOFT_MAX_KMH: Final = {  # altitude AMSL → seuil par niveau (interpolé entre paliers)
    1500: by_level(15, 20, 25, 30),
    2000: by_level(20, 25, 30, 35),
    3000: by_level(25, 30, 35, 40),
}
GRADIENT_MAX_KMH_PER_1000M: Final = by_level(10, 15, 20, 25)  # Δ vitesse déco → déco + 1000 m
VEER_MAX_DEG: Final = by_level(45, 60, 90, 120)  # rotation déco → plafond (si vents ≥ 10 km/h)
VEER_MIN_WIND_KMH: Final = 10.0
SHEAR_MAX_KMH_PER_300M: Final = by_level(8, 12, 15, 20)
ALOFT_CHECK_ABOVE_CEILING_M: Final = 300.0  # niveaux atteints = déco → plafond utile + 300 m
CREST_CHECK_ABOVE_TAKEOFF_M: Final = 300.0  # « niveau des crêtes » pour le dévent / faux calme

# ---------------------------------------------------------------------------------------------
# §2.1 — Atterrissage
# ---------------------------------------------------------------------------------------------
LANDING_WIND_MAX_KMH: Final = by_level(15, 20, 25, 28)
LANDING_GUST_MAX_KMH: Final = by_level(20, 25, 30, 35)
LANDING_ARRIVAL_MARGIN_M: Final = by_level(200, 150, 120, 100)  # hauteur d'entrée dans l'approche
# Brise de vallée (§4.3) : ×1,3 sur le vent 10 m entre 13h et 17h légale dans les grandes vallées
VALLEY_BREEZE_AFTERNOON_FACTOR: Final = 1.3
VALLEY_BREEZE_HOURS_LEGAL: Final = (13, 17)
BIG_VALLEY_MAX_FLOOR_M: Final = 800.0  # atterro < 800 m …
BIG_VALLEY_MIN_RELIEF_M: Final = 2000.0  # … entouré de relief > 2000 m …
BIG_VALLEY_RADIUS_KM: Final = 10.0  # … dans un rayon de 10 km

# ---------------------------------------------------------------------------------------------
# §2.1 / §4.8 — Thermiques et plafond
# ---------------------------------------------------------------------------------------------
THERMAL_MAX_MS: Final = by_level(1.5, 2.5, 3.5, 5.0)  # vario moyen max (au-delà : niveau supérieur)
THERMAL_USABLE_MIN_MS: Final = 0.8  # < 0,8 m/s : non exploitable (plouf)
THERMAL_QUALITY_MS: Final = ((0.8, "faible"), (1.5, "bon"), (2.5, "fort"), (3.5, "très fort / turbulent"))
LOCAL_CEILING_MIN_ABOVE_TAKEOFF_M: Final = by_level(700, 600, 400, 300)
XC_CEILING_MIN_ABOVE_TAKEOFF_M: Final = by_level(None, 1200, 1000, 800)
XC_CEILING_MIN_ABOVE_RELIEF_M: Final = by_level(None, 500, 400, 300)
TRANSITION_ARRIVAL_ABOVE_TERRAIN_M: Final = by_level(None, 500, 400, 300)
CLOUD_CLEARANCE_VERTICAL_M: Final = 300.0  # plafond utile = base des cumulus − 300 m (VMC)
AVOID_THERMAL_MAX_MS: Final = 1.5  # préférence "avoid" : exclure si vario prévu > 1,5 m/s pendant le vol
REQUIRED_THERMAL_MIN_MS: Final = 0.8  # préférence "required" : exclure en dessous

# ---------------------------------------------------------------------------------------------
# Paramètres aérologiques des calculs (app/meteo) — §0, §4.1, §4.7
# ---------------------------------------------------------------------------------------------
THERMAL_TRIGGER_EXCESS_C: Final = 1.0  # surchauffe de la particule : T_max_sol + 1 °C (§4.7)
TRIGGER_EXCESS_FULL_SUN_W_M2: Final = 150.0  # surchauffe pleine dès 150 W/m² (0 la nuit)
WSTAR_TO_VARIO_SINK_MS: Final = 1.0  # vario ≈ max(0, W* − 1,0) (§0)
SENSIBLE_HEAT_ALBEDO: Final = 0.15
SENSIBLE_HEAT_FRACTION_RANGE: Final = (0.15, 0.45)  # fraction du rayonnement net en chaleur sensible
CONVECTION_START_MIN_BLH_AGL_M: Final = 500.0  # §4.1 : début = BLH ≥ 500 m ET W* ≥ 1,2
CONVECTION_START_MIN_WSTAR_MS: Final = 1.2
CONVECTION_END_MIN_WSTAR_MS: Final = 1.0  # fin = dernière heure W* ≥ 1,0
STRONG_WIND_THERMAL_BREAK_KMH: Final = 20.0  # au-delà, les thermiques sont hachés (réduction du vario)
MODEL_BLH_WEIGHT: Final = 0.35  # croisement plafond particule / hauteur de couche limite du modèle
# Décalage du début des thermiques selon l'orientation de la face (h, relatif à une face S) — §4.2
FACE_THERMAL_OFFSET_H: Final = {
    "E": -1.5, "ESE": -1.1, "SE": -0.75, "SSE": -0.4, "S": 0.0, "SSW": 0.5, "SW": 1.0,
    "WSW": 1.5, "W": 2.0, "WNW": 2.5, "NW": 3.0, "NNW": 3.0, "N": 3.0, "NNE": 3.0, "NE": 3.0, "ENE": 3.0,
}  # fmt: skip
EAST_FACE_SHADE_SOLAR_H: Final = 12.5  # déco E interdit après 12h30 solaire (bascule de brise)…
EAST_FACE_SYNOPTIC_EXEMPT_KMH: Final = 10.0  # … sauf vent météo d'E ≥ 10 km/h
RESTITUTION_BEFORE_SUNSET_H: Final = 1.5  # restitution du soir : coucher − 1h30 → coucher (faces W/SW)
RESTITUTION_FACES: Final = ("SW", "WSW", "W", "WNW", "SSW")

# ---------------------------------------------------------------------------------------------
# §3 — No-go absolus (tous niveaux)
# ---------------------------------------------------------------------------------------------
NOGO_PRECIP_MM_H: Final = 0.2  # sur le créneau ±1 h au déco ou sur la route
CAUTION_PRECIP_MM_H: Final = 0.05
NOGO_PRECIP_PREV_3H_MM: Final = 1.0  # aile mouillée / sol froid
NOGO_CAPE_STORM: Final = (800.0, -2.0)  # CAPE ≥ 800 ET LI ≤ −2
NOGO_CAPE_ABSOLUTE: Final = 1500.0
CAUTION_CAPE: Final = (300.0, 0.0)  # CAPE 300-800 ET LI ≤ 0 → fin de créneau avancée à 14h solaire
CAUTION_CAPE_WINDOW_END_SOLAR_H: Final = 14.0
NOGO_CLOUD_BASE_MIN_ABOVE_TAKEOFF_M: Final = 200.0
CAUTION_CLOUD_BASE_ABOVE_TAKEOFF_M: Final = 500.0
NOGO_LOW_CLOUD_COVER_PCT: Final = 80.0  # nuages bas ≥ 80 % avec base < déco + 300
NOGO_SPREAD_T_TD_C: Final = 1.5  # T − Td < 1,5 °C au déco (brouillard / nuage au déco)
NOGO_WIND_ANY_LEVEL_KMH: Final = 45.0  # à un niveau atteint par le vol
CAUTION_WIND_ANY_LEVEL_KMH: Final = 35.0
NOGO_WIND_3000M_MOUNTAIN_KMH: Final = 50.0  # même si le plafond est plus bas (turbulence descend)
MOUNTAIN_MIN_TAKEOFF_M: Final = 800.0  # déco considéré « en montagne » au-dessus de cette altitude
NOGO_FOEHN_700HPA_KMH: Final = 40.0
CAUTION_FOEHN_700HPA_KMH: Final = 25.0
FOEHN_DRY_RH_PCT: Final = 40.0
# Secteurs de foehn (d'où vient le vent à 700 hPa) par région
FOEHN_SECTORS_DEG: Final = {
    "alpes_nord": (150.0, 250.0),  # foehn de S-SW
    "alpes_sud": (300.0, 360.0),  # foehn de N-NW (Briançonnais, Ubaye…)
}
NOGO_REGIONAL_WIND_GROUND_KMH: Final = 30.0  # bise / mistral au sol
CAUTION_REGIONAL_WIND_GROUND_KMH: Final = 20.0
NOGO_LEE_WIND_AT_CREST_KMH: Final = 15.0  # vent opposé (> 120° de l'axe du déco) au niveau des crêtes
CAUTION_LEE_WIND_AT_CREST_KMH: Final = 10.0
LEE_ANGLE_DEG: Final = 120.0
CAUTION_SYNOPTIC_CROSSWIND_KMH: Final = 20.0
NOGO_TAKEOFF_WIND_ABS_KMH: Final = 30.0
NOGO_TAKEOFF_GUST_ABS_KMH: Final = 35.0
NOGO_GUST_SPREAD_ABS_KMH: Final = 15.0
NOGO_LANDING_WIND_ABS_KMH: Final = 28.0
NOGO_LANDING_GUST_ABS_KMH: Final = 35.0
LANDING_BEFORE_SUNSET_CAUTION_MIN: Final = 30.0  # atterrissage < 30 min avant coucher → caution
COLD_AT_CEILING_BEGINNER_C: Final = -10.0
CAUTION_MID_HIGH_CLOUD_PCT: Final = 80.0  # voile épais : thermiques coupés

# ---------------------------------------------------------------------------------------------
# §4.6 — Surdéveloppement
# ---------------------------------------------------------------------------------------------
OVERDEV_LOW_CAPE: Final = 300.0
OVERDEV_LOW_LI: Final = 2.0
OVERDEV_HIGH: Final = (800.0, 0.0)  # CAPE > 800 ET LI < 0
OVERDEV_MODERATE_RH700_PCT: Final = 70.0
OVERDEV_BASE_BELOW_DRY_TOP_M: Final = 1000.0  # base < plafond sec − 1000 m dès midi → high
OVERDEV_DELAY_AFTER_FIRST_CU_H: Final = 3.5  # surdév ≈ premier cumulus + 3 à 4 h
OVERDEV_MODERATE_END_BEFORE_H: Final = 1.0  # moderate → fin du créneau = surdév − 1 h
OVERDEV_HIGH_MAX_DURATION_MIN: Final = 90.0
OVERDEV_HIGH_EXPERT_RETURN_SOLAR_H: Final = 13.0

# ---------------------------------------------------------------------------------------------
# §2.2 — Soaring dynamique
# ---------------------------------------------------------------------------------------------
RIDGE_MIN_KMH: Final = by_level(15, 15, 15, 13)
RIDGE_MAX_KMH: Final = by_level(20, 22, 27, 30)
RIDGE_MAX_ANGLE_DEG: Final = by_level(20, 30, 40, 45)
RIDGE_GUST_MAX_KMH: Final = by_level(22, 26, 32, 35)
RIDGE_GUST_SPREAD_MAX_KMH: Final = 8.0  # vent régulier
RIDGE_MAX_DURATION_MIN: Final = by_level(30, 90, 90, 90)
RIDGE_BEAT_HALF_LENGTH_KM: Final = 0.6  # demi-longueur de la portion soarable par défaut
RIDGE_SOARING_HEIGHT_M: Final = 120.0  # gain typique au-dessus du déco en dynamique

# ---------------------------------------------------------------------------------------------
# §2.3 / §5 — Finesse, routage
# ---------------------------------------------------------------------------------------------
AIR_SPEED_TRIM_KMH: Final = 37.0
AIR_SPEED_TRIM_HIGH_PERF_KMH: Final = 39.0  # EN-C/D (finesse ≥ 9,5)
HIGH_PERF_GLIDE_RATIO: Final = 9.5
GLIDE_K: Final = by_level(0.50, 0.60, 0.65, 0.70)  # finesse de calcul = polaire × k
GLIDE_LEE_PENALTY: Final = 0.9  # −10 % sous le vent d'un relief / vallée en brise descendante
TERRAIN_CLEARANCE_M: Final = 50.0  # dégagement mini de la ligne de plané au-dessus du terrain
GLIDE_CHECK_STEP_KM: Final = 0.5  # vérification « atterro dans le cône » tous les 500 m
SAFETY_ALT_BELOW_CEILING_M: Final = 300.0  # alt_sécurité(p) ≤ plafond utile − 300 m
XC_MAX_DISTANCE_KM: Final = by_level(0, 25, 80, 250)
MAX_DURATION_MIN: Final = by_level(45, 120, 300, 540)
XC_MIN_DURATION_MIN: Final = 60.0  # en dessous, un cross n'a pas de sens
XC_SPEED_KMH_BY_VARIO: Final = {  # vario moyen (m/s) → vitesse de croisière (km/h), aile EN-B
    "intermediate": {1: 8, 2: 14, 3: 19},
    "advanced": {1: 10, 2: 17, 3: 23, 4: 27},
    "expert": {1: 12, 2: 20, 3: 27, 4: 32, 5: 36},
}
XC_SPEED_HIGH_PERF_FACTOR: Final = 1.15
XC_MIN_EFFECTIVE_SPEED_KMH: Final = 8.0
XC_TRIANGLE_WIND_FACTOR: Final = 0.7  # W × 0,7 pour un triangle
XC_DOWNWIND_FACTOR: Final = 0.8  # V_eff = V_xc + 0,8 × W en distance libre
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
TURNPOINT_RADIUS_M: Final = 400.0
GOAL_RADIUS_M: Final = 300.0
TAKEOFF_RADIUS_M: Final = 400.0
LOCAL_LOOP_KM: Final = (3.0, 10.0)  # boucle de vol local thermique
PLOUF_LOSE_HEIGHT_POINT_KM: Final = 0.4  # zone de perte d'altitude à 300-500 m de l'atterro
ALTERNATE_LANDING_SEARCH_KM: Final = 15.0
ASSOCIATED_LANDING_MAX_KM: Final = 8.0  # association heuristique déco ↔ atterro (sources sans lien)
ASSOCIATED_LANDING_MIN_DROP_M: Final = 150.0

# ---------------------------------------------------------------------------------------------
# §6 — Durées
# ---------------------------------------------------------------------------------------------
SINK_RATE_MS: Final = {"calm": 1.2, "evening": 1.0, "sinking_air": 1.5}
PLOUF_EXTRA_MIN: Final = 3.0
RESTITUTION_DURATION_FACTOR: Final = 1.75  # plouf en restitution × 1,5 à 2
LOCAL_THERMAL_BEGINNER_MAX_MIN: Final = 45.0
LANDING_BEFORE_SUNSET_MIN: Final = 30.0  # finir ≥ 30 min avant le coucher (créneau recommandé)

# ---------------------------------------------------------------------------------------------
# §7.4 — Espaces aériens et zones sensibles
# ---------------------------------------------------------------------------------------------
FL115_M_STANDARD: Final = 3505.0  # plafond légal général en France
CEILING_MARGIN_BELOW_AIRSPACE_M: Final = 100.0
AIRSPACE_CAUTION_LATERAL_KM: Final = 1.0
AIRSPACE_CAUTION_VERTICAL_M: Final = 100.0
AIRSPACE_REPORT_RADIUS_KM: Final = 10.0  # espaces listés dans le plan s'ils sont à moins de 10 km
AIRSPACE_FORBIDDEN_CLASSES: Final = ("A", "B", "C", "D", "P", "CTR")  # interdits sans clairance
AIRSPACE_CAUTION_CLASSES: Final = ("R", "Q", "ZRT", "TRA", "TSA", "RMZ", "TMZ", "W", "GP")
PARK_MIN_HEIGHT_AGL_M: Final = 1000.0  # cœurs de parcs nationaux : survol < 1000 m/sol interdit

# ---------------------------------------------------------------------------------------------
# §8.2 — Balises, nowcasting, confiance
# ---------------------------------------------------------------------------------------------
HORIZON_BEACON_WEIGHT: Final = {"30m": 0.7, "1h": 0.5, "2h": 0.3, "8h": 0.1, "12h": 0.0, "24h": 0.0, "48h": 0.0}
HORIZON_BASE_CONFIDENCE: Final = {
    "30m": 0.90, "1h": 0.85, "2h": 0.80, "8h": 0.70, "12h": 0.65, "24h": 0.55, "48h": 0.40,
}  # fmt: skip
NOWCAST_MAX_HORIZON_MIN: Final = 120  # correction par balises uniquement pour les horizons ≤ 2 h
BEACON_MAX_DISTANCE_KM: Final = 5.0  # balise « du site »
BEACON_SEARCH_RADIUS_KM: Final = 15.0  # balises affichées / utilisables avec poids réduit
BEACON_MAX_ALT_DIFF_M: Final = 300.0  # au-delà : poids divisé par 2
BEACON_STALE_MIN: Final = 30.0
BEACON_CONTRADICTION_KMH: Final = 10.0  # règle d'or : > 10 km/h ou > 45° → on suit la balise
BEACON_CONTRADICTION_DEG: Final = 45.0
BEACON_COHERENT_KMH: Final = 5.0
BEACON_COHERENT_DEG: Final = 30.0
NOWCAST_MAX_SPEED_BIAS_KMH: Final = 25.0
NOWCAST_MAX_DIR_BIAS_DEG: Final = 90.0
DISPERSION_SPEED_SIGMA_KMH: Final = (3.0, 10.0)  # σ ≤ 3 → ×1 ; σ = 10 → ×0,6
DISPERSION_SPEED_FACTOR_AT_MAX: Final = 0.6
DISPERSION_DIR_SIGMA_DEG: Final = 45.0  # σ direction > 45° → ×0,7
DISPERSION_DIR_FACTOR: Final = 0.7
BEACON_COHERENT_FACTOR: Final = 1.1
BEACON_CONTRADICTORY_FACTOR: Final = 0.8
CONFIDENCE_MAX: Final = 0.95
MOCK_CONFIDENCE_CAP: Final = 0.3  # données synthétiques : confiance plafonnée (→ jamais « go »)
SINGLE_SOURCE_NOGO_CONFIDENCE: Final = 0.6  # une source no-go + confiance < 0,6 → marginal au mieux

# ---------------------------------------------------------------------------------------------
# §9 — Score et verdict
# ---------------------------------------------------------------------------------------------
MARGINAL_BAND: Final = 0.8  # zone « marginal » = 80-100 % du seuil
SCORE_WEIGHTS: Final = {
    "takeoff_wind": 25,
    "wind_aloft": 15,
    "landing": 15,
    "thermal_match": 15,
    "duration_match": 10,
    "convective_stability": 10,
    "data_confidence": 5,
    "site_fit": 5,
    # Ajout backend (non listé au §9.2) : proximité des espaces aériens. Normalisé avec les autres.
    "airspace": 5,
}
SAFETY_CRITERIA: Final = ("takeoff_wind", "wind_aloft", "landing", "convective_stability", "airspace")
SAFETY_CAP_OFFSET: Final = 40.0  # score ≤ 40 + min(sous-scores de sécurité)
CALM_TAKEOFF_SUBSCORE: Final = 80.0
ALLOWED_NO_THERMAL_SUBSCORE: Final = 70.0
GO_MIN_SCORE: Final = 65.0
GO_MIN_SAFETY_SUBSCORE: Final = 50.0
GO_MIN_CONFIDENCE: Final = 0.5
NOGO_MAX_SCORE: Final = 45.0
MAX_PLANS_PER_TAKEOFF: Final = 2
UNKNOWN_SITE_DIFFICULTY: Final = "intermediate"  # site sans difficulté renseignée (ex. ParaglidingEarth)

# ---------------------------------------------------------------------------------------------
# Régions (heuristiques simples, bbox lat/lon) pour foehn et vents régionaux
# ---------------------------------------------------------------------------------------------
REGIONS: Final = {
    # (min_lat, min_lon, max_lat, max_lon)
    "alpes_nord": (45.0, 5.5, 46.6, 7.9),
    "alpes_sud": (43.6, 5.5, 45.0, 7.8),
    "bise": (45.6, 5.7, 46.6, 7.0),  # bassin genevois, Annecy, Chablais : bise de NE
    "mistral": (43.2, 4.2, 45.0, 5.9),  # vallée du Rhône, Provence occidentale
}
BISE_SECTOR_DEG: Final = (10.0, 80.0)
MISTRAL_SECTOR_DEG: Final = (320.0, 30.0)

# ---------------------------------------------------------------------------------------------
# Radio / urgence (§7.5)
# ---------------------------------------------------------------------------------------------
RADIO_FREQ_MHZ: Final = "143,9875"
EMERGENCY_NUMBER: Final = "112"


def level_index(level: str) -> int:
    return LEVELS.index(level)


def interp_aloft_threshold(altitude_m: float, level: str) -> float:
    """Seuil de vent en altitude (§2.1) interpolé linéairement entre les paliers 1500/2000/3000 m."""
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
    """Vitesse de croisière (§5.5) interpolée dans la table, 0 si le niveau ne fait pas de cross."""
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
