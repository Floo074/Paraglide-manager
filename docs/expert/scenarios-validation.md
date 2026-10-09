# Scénarios de validation métier — Paraglide Manager

> Rédigé par l'expert pilote (référent métier). Ces scénarios **font foi** pour le verdict, le type de vol, la durée et les risques.
> À transformer en `backend/tests/test_expert_scenarios.py` (un test paramétré par scénario + les invariants globaux du §3). Source machine-readable : `scenarios-validation.yaml` : 32 cas actifs (`scenarios`) et 5 cas de phase 2, S28 à S32 (`scenarios_phase2`, CDC §12), à charger dès que le moteur les gère.
> Codes `Risk` : catalogue du §1. Seuils : `cahier-des-charges-pilote.md` §2, §3, §11 et §12 (balises d'atterro, horizon 15 min, décollage libre, atterros non officiels).

---

## 1. Conventions

### 1.1 Codes `Risk` (exacts)

`RAIN, THUNDERSTORM, OVERDEVELOPMENT, SITE_LEVEL, FOEHN, REGIONAL_WIND, LOW_CLOUD_BASE, STRONG_WIND_ALOFT, LEE_SIDE, TAKEOFF_WIND, TAKEOFF_GUSTS, CROSSWIND, TAILWIND, LANDING_WIND, VALLEY_BREEZE, GLIDE_MARGIN, SUNSET, AIRSPACE, AIRSPACE_ACTIVATION, ALTITUDE_LIMIT, SENSITIVE_AREA, NATIONAL_PARK, SITE_CLOSED, SITE_RESTRICTED, WIND_GRADIENT, WIND_SHEAR, STRONG_THERMALS, WEAK_THERMALS, INVERSION, VENTURI, ROTOR, FRONT, FREEZING, WIND_INCREASING, BEACON_MISMATCH, STALE_BEACONS, LOW_CONFIDENCE, MOCK_DATA, ACCESS_TIME`

Phase 2 (CDC §12) : `NO_LANDING_BEACON, WIND_SHIFT, FREE_TAKEOFF, UNOFFICIAL_LANDING, DETECTED_FIELD`. `NO_LANDING_BEACON` est la seule caution **non bloquante** de la liste.

Niveaux : `danger` ⇒ no-go ; `caution` ⇒ marginal ou point de vigilance ; `info` ⇒ rappel.

### 1.2 Format des entrées

- **Heures** : heure légale Europe/Paris (CEST = UTC+2 jusqu'au 25/10/2026, CET = UTC+1 ensuite) ; l'UTC est donné entre parenthèses.
- **Vents** : `[vitesse km/h, direction ° d'où vient le vent]`.
- `weather.takeoff` = vent **à l'altitude du déco** (déjà interpolé). Le test peut le construire en mettant ce vent dans le niveau du profil correspondant à l'altitude du déco.
- `weather.crest` = vent à `alt_déco + 300 m` (sert à la règle du dévent `LEE_SIDE`).
- `weather.landing` = vent **modèle 10 m** à l'atterro, **avant** le facteur de brise × 1,3 (le moteur doit l'appliquer lui-même entre 13 h et 17 h).
- Conditions constantes sur ±3 h autour de l'heure cible, sauf indication dans `timeline` (heure légale → valeurs qui changent).
- `models` (facultatif) : vent au déco par modèle, pour tester la dispersion et la confiance.
- `beacons` (facultatif) : mesures de balises proches (âge en minutes).
  - Phase 2 : `trend` (= `Beacon.trend` du contrat : `window_min`, `speed_change_kmh`, `direction_change_deg`, `gust_max_kmh`, `samples`).
  - `elevation_m: null` signifie altitude inconnue. Si `dem_elevation_m` est absent, le MNT est considéré comme indisponible au point de la balise.
  - Le rattachement au déco ou à l'atterro se fait par distance, altitude et nom (CDC §12.1) : le scénario ne le donne pas.
- Phase 2, décollage libre :
  - `mode: custom_takeoff` et `custom_takeoff` (`name`, `lat`, `lon`, `elevation_m`, `orientations`, `slope_pct`, `aspect_deg`) remplacent `takeoff`. `slope_pct` et `aspect_deg` sont des valeurs MNT imposées.
  - `landing_candidates` remplace `landing` / `alternate_landings`. Chaque entrée porte `landing_kind` (`official` / `community` / `field`), `size_m`, `slope_pct`, `surface`, `community_usage`, `access` et `clearances_m` : distances aux lignes, aux arbres et bâtiments, à l'eau et aux routes.
  - `filters.landing_policy` fixe les catégories d'atterros admises.
- Les données injectées par scénario sont traitées comme **source exacte** : confiance = confiance de base de l'horizon (CDC §8.2) × dispersion. Elles ne sont **pas** plafonnées comme le mode mock.

### 1.3 Sites de référence (paramètres à injecter tels quels ; coordonnées approximatives)

| Clé | Déco | Alt. déco | Orientations | Difficulté site | Atterro principal | Alt. atterro | Distance / cap déco→atterro | Types |
|---|---|---|---|---|---|---|---|---|
| `forclaz` | Col de la Forclaz (Montmin), 45.812 N 6.245 E | 1250 | W, WNW, NW | beginner | Doussard, 45.786 N 6.222 E | 450 | 3,5 km / 215° | local, cross_country |
| `planfait` | Planfait (Talloires), 45.853 N 6.235 E | 1180 | WSW, W, SW | intermediate | Talloires, 45.845 N 6.212 E | 450 | 2,0 km / 245° | local |
| `planpraz` | Planpraz (Chamonix), 45.937 N 6.858 E | 2000 | SE, SSE, S, SSW, SW | intermediate | Bois du Bouchet, 45.932 N 6.882 E | 1030 | 2,0 km / 107° | local, cross_country |
| `st_hilaire` | Saint-Hilaire du Touvet (déco Sud), 45.305 N 5.888 E | 980 | E, ESE, SE | beginner | Lumbin, 45.300 N 5.910 E | 240 | 1,8 km / 110° | local, cross_country |
| `chalvet` | Chalvet (Saint-André-les-Alpes), 43.975 N 6.488 E | 1550 | S, SSW, SW, WSW, W | intermediate | Saint-André, 43.966 N 6.505 E | 900 | 1,7 km / 125° | local, cross_country |
| `pyla` | Dune du Pyla, 44.589 N 1.213 W | 100 | W, WNW | beginner | Top landing / plage | 100 / 5 | 0,3 km / 270° | ridge_soaring |
| `deco_technique` | Site fictif, 45.500 N 6.500 E | 1600 | S | advanced | Atterro fictif | 700 | 3,0 km / 180° | local |
| `rando` (décollage libre) | Alpage rando fictif, 45.700 N 6.400 E, pente 40 % face SE | 1500 | ESE, SE, SSE | — (vaut intermediate) | Pré communautaire, 1,6 km / 135° (alt. 800) ; pré de fauche détecté, 1,8 km / 150° (alt. 820) ; officiel à 15 km (hors de portée) | — | — | local |

Finesse par défaut : 8,5 (EN-B), sauf mention.

---

## 2. Scénarios

> Lecture : **verdict attendu** = `flyability` du meilleur plan pour ce site. Si le scénario dit « rejeté », le site doit figurer dans `rejected` avec la raison indiquée, sans aucun plan go ou marginal pour ce site.
> Fourchettes de durée = `est_duration_min`.

| ID | Site / quand | Situation | Niveau / filtres | Verdict attendu | Type | Durée | Risques obligatoires | Interdits |
|---|---|---|---|---|---|---|---|---|
| S01 | forclaz, 15/07/2026 14:00 | Belle journée thermique (vario 1,8), brise du lac | intermediate, allowed, 60-120, local | **go** | local | 60-120 | VALLEY_BREEZE (info) | RAIN, THUNDERSTORM, LEE_SIDE, TAILWIND ; cross > 25 km |
| S02 | forclaz, 15/07/2026 19:30 | Fin d'après-midi calme, après la convection | beginner, avoid, 10-45 | **go** | local (`thermal_usage` none/optional) | 11-20 | — | STRONG_THERMALS, cross_country ; atterrissage après le coucher du soleil |
| S03 | forclaz, 15/07/2026 14:00 | Comme S01 (vario 2,2) | beginner, allowed, 15-45 | **rejeté** (thermiques trop forts, difficulté du plan = intermediate) | — | — | STRONG_THERMALS (danger) | aucun plan go pour beginner sur ce site à 14 h |
| S04 | forclaz, 08/10/2026 13:00 | Faux calme : déco 3 km/h, crête ESE 20 km/h | expert, allowed, 30-120 | **no_go** (tous niveaux) | — | — | LEE_SIDE (danger) | go, marginal |
| S05 | planpraz, 20/07/2026 12:00 | Cross, plafond 3900 (> FL115), CAPE 400 / LI −1 | advanced, required, 120-300, finesse 9,0 | **marginal** | cross_country (ou local) | 120-200 | OVERDEVELOPMENT (caution), ALTITUDE_LIMIT | RAIN ; `max_altitude_m` > 3405 ; atterrissage après 15:00 |
| S06 | planpraz, 21/07/2026 13:00 | Orages : CAPE 1200 / LI −4, averses à 16:00 | expert, allowed, 30-240 | **no_go** | — | — | THUNDERSTORM (danger) | go, marginal |
| S07 | st_hilaire, 16/05/2026 11:00 | Thermique moyen, brise pas encore établie | intermediate, allowed, 30-90 | **go** | local | 30-90 | — | LANDING_WIND (danger), THUNDERSTORM, LEE_SIDE |
| S08 | st_hilaire, 16/05/2026 15:30 | Brise du Grésivaudan établie à l'arrivée (10 m : 18 g21 → ×1,3 ≈ 23 g27) | intermediate, allowed, 30-60 | **rejeté** (atterro : 23 > 20) | — | — | LANDING_WIND (danger) | go |
| S08b | idem S08 | idem | advanced, allowed, 30-60 | **marginal** (23 = 94 % de 25 ; rafales 27 = 91 % de 30) | local | 30-60 | VALLEY_BREEZE (caution) | — |
| S09 | chalvet, 13/06/2026 11:30 | Grand cross, NW faible | expert, required, 240-480, cross_country, finesse 9,8 | **go** | cross_country | 240-420 | — | RAIN, THUNDERSTORM, LEE_SIDE ; `max_altitude_m` > 3200 |
| S10 | chalvet, 10/04/2026 12:00 | Mistral : NW 52 km/h à 3000 m, N 30 à la crête | expert, allowed, 30-240 | **no_go** | — | — | STRONG_WIND_ALOFT (danger) | go, marginal |
| S11 | planpraz, 12/10/2026 13:00 | Foehn de S : 700 hPa SSW 55 km/h, déco 20 g38 | expert, allowed, 30-240 | **no_go** | — | — | FOEHN (danger), STRONG_WIND_ALOFT (danger), TAKEOFF_GUSTS (danger) | go, marginal |
| S12 | forclaz, 05/09/2026 14:00 | Pluie 0,5 mm/h, base 1400 | advanced, allowed, 30-120 | **no_go** | — | — | RAIN (danger), LOW_CLOUD_BASE (danger) | go, marginal |
| S13 | forclaz, 05/09/2026 17:00 | Sec à l'heure cible, mais 2,5 mm dans les 3 h précédentes | intermediate, allowed, 30-90 | **no_go** | — | — | RAIN (danger) | go |
| S14 | forclaz, 12/12/2026 13:00 | Mer de nuages : déco au soleil, atterro dans le stratus (T−Td 0,5 °C, couverture basse 100 %) | advanced, allowed, 15-60 | **no_go** | — | — | LOW_CLOUD_BASE (danger) | go, marginal |
| S15 | pyla, 10/08/2026 16:00 | Soaring : WNW 16 g19, top landing | intermediate, avoid, 30-90 | **go** | ridge_soaring | 30-90 | — | cross_country, STRONG_THERMALS, GLIDE_MARGIN |
| S16 | pyla, 11/08/2026 16:00 | Soaring fort : W 26 g30 | intermediate, avoid, 30-90 | **rejeté** (vent > 22, difficulté = advanced) | — | — | TAKEOFF_WIND (danger) | go |
| S16b | idem S16 | idem | expert, avoid, 30-90 | **marginal** (26 = 87 % de 30) | ridge_soaring | 30-90 | TAKEOFF_WIND (caution) | — |
| S17 | planfait, 20/09/2026 13:00 | Travers : NNW 12 km/h (écart 56°) | intermediate, allowed, 30-90 | **rejeté** (> 45°) | — | — | CROSSWIND (danger) | go |
| S17b | idem S17 | idem | advanced, allowed, 30-90 | **marginal** (56° = 93 % de 60°) | local | 30-90 | CROSSWIND (caution) | — |
| S18 | forclaz, 20/09/2026 11:00 | Vent arrière E 6 km/h, crête E 8 | advanced, allowed, 30-90 | **rejeté** (arrière 6 > 5) | — | — | TAILWIND (danger) | go |
| S18b | idem S18 | idem | expert, allowed, 30-90 | **marginal** (tout vent arrière ≥ 5 km/h ⇒ au mieux marginal) | local | 15-90 | TAILWIND (caution) | go |
| S19 | forclaz, 08/10/2026 18:45 | Fin de journée, coucher ≈ 19:05 | intermediate, allowed, 30-90 | **marginal** | local (plouf) | 10-20 | SUNSET (caution) | durée > 20 ; atterrissage après le coucher |
| S20 | forclaz, horizon 30m, réf. 08/10/2026 13:00 | Modèle W 10 km/h, balise du déco N 25 g38 il y a 5 min | advanced, allowed, 30-90 | **no_go** | — | — | TAKEOFF_GUSTS (danger), BEACON_MISMATCH | go, marginal |
| S21 | st_hilaire, horizon 48h, réf. 08/10/2026 11:00 | Modèles en désaccord : SE 10 / 22 / 15 km/h | intermediate, allowed, 30-90 | **marginal** (confiance < 0,5) | local | 30-90 | LOW_CONFIDENCE (caution) | go |
| S22 | chalvet, 25/07/2026 09:30 | Matin calme, orages l'après-midi (CAPE 900 / LI −2 dès 16 h, averses 17 h) | intermediate, allowed, 30-180 | **marginal** | local | 30-90 | OVERDEVELOPMENT (caution) | cross_country ; atterrissage après 15:00 ; durée > 90 |
| S23 | deco_technique, 16/05/2026 11:00 | Conditions parfaites | intermediate, allowed, 30-90 | **rejeté** (site advanced > intermediate) | — | — | SITE_LEVEL | go, marginal |
| S24 | st_hilaire, 16/07/2026 08:30 | Matin calme avant les thermiques : plouf | beginner, avoid, 10-45 | **go** | local (plouf, `thermal_usage` none) | 10-20 | — | cross_country, STRONG_THERMALS ; durée > 25 |
| S25 | forclaz, 14/07/2026 11:30 | Cross expert, CTR classe D fictive au nord du lac | expert, required, 120-300, cross | **go** | cross_country | 120-300 | — | route qui coupe une classe A/C/D/P |
| S26 | planpraz, 14/07/2026 12:00 | Zone de quiétude aigle royal active autour du déco | intermediate, allowed, 30-90 | **marginal** | local | 30-90 | SENSITIVE_AREA (caution) | — |
| S26b | idem S26, 05/10/2026 | Zone hors période | intermediate, allowed, 30-90 | **go** | local | 30-90 | — | SENSITIVE_AREA |
| S27 | deco_technique dans un cœur de parc national | Déco interdit | expert, allowed, 30-90 | **no_go** | — | — | NATIONAL_PARK (danger) | go, marginal |

**Phase 2 (CDC §12, bloc `scenarios_phase2`)**

| ID | Site / quand | Situation | Niveau / filtres | Verdict attendu | Type | Durée | Risques et contrôles obligatoires | Interdits |
|---|---|---|---|---|---|---|---|---|
| S28 | forclaz, horizon 15m, réf. 10/10/2026 13:45 | Modèle calme à l'atterro (4 km/h, × 1,3 = 5). Balise « Doussard atterro » à 12 g17 et +10 km/h en 1 h. Vers 14 h 25 à l'arrivée : ≈ 19 g24 extrapolés (≈ 75 % / 80 % des seuils advanced) | advanced, allowed, 15-45, local | **marginal** (tendance > 5 km/h/h, valeur extrapolée ≥ 50 % du seuil) | local | 15-45 | WIND_INCREASING (caution) ; balise d'atterro représentative | NO_LANDING_BEACON, WIND_SHIFT, TAKEOFF_GUSTS, TAILWIND ; go |
| S29 | forclaz, horizon 15m, réf. 10/10/2026 13:45 | Aucune balise à l'atterro, balise du déco cohérente ; atterro 6 km/h × 1,3 = 7,8 | intermediate, allowed, 15-45, local | **go** (l'absence de balise n'est jamais un no-go à elle seule) | local | 15-45 | NO_LANDING_BEACON (caution non bloquante) ; confiance ≤ 0,915 (0,92 × 1,1 × 0,9) ; aucune balise d'atterro représentative | WIND_INCREASING, LANDING_WIND, BEACON_MISMATCH |
| S30 | forclaz, horizon 30m, réf. 10/10/2026 13:30 | Balise « Pioupiou Doussard atterro » à 0,36 km, sans altitude et sans MNT ; cohérente avec le modèle | intermediate, allowed, 15-45, local | **go** | local | 15-45 | Balise d'atterro représentative (bonus de nom), poids ≤ 0,35 (× 0,5), commentaire « altitude inconnue » | NO_LANDING_BEACON, BEACON_MISMATCH, WIND_INCREASING |
| S31 | rando (décollage libre), 20/09/2026 10:30 | SE 8 km/h de face. Seul un champ détecté est à portée (officiel à 15 km) | beginner, avoid, 10-30, `include_fields` | **rejeté** : aucun plan | — | — | FREE_TAKEOFF (danger), DETECTED_FIELD (danger) ; raison « décollage libre » | tout plan go ou marginal |
| S32 | rando (décollage libre), 20/09/2026 10:30 | Idem, avec un pré communautaire à 1,6 km (finesse requise ≈ 2,8 pour ≈ 4,3 de finesse de calcul) | advanced, avoid, 10-30, `include_community` | **go** | local | 10-30 | FREE_TAKEOFF (info), UNOFFICIAL_LANDING (info) ; atterro principal `community` ; warning « Non officiel » | DETECTED_FIELD, GLIDE_MARGIN, TAILWIND, CROSSWIND, TAKEOFF_WIND ; atterro `field` |

---

## 3. Invariants globaux (à vérifier sur TOUS les plans de TOUS les scénarios et des appels `/api/plans` de démo)

| # | Invariant |
|---|---|
| I1 | Un plan qui porte un Risk `danger` n'est jamais `go` ni `marginal` : il est `no_go` ou rejeté. |
| I2 | Un plan `marginal` porte au moins un Risk `caution` qui l'explique. |
| I3 | `filters.difficulty = beginner` ⇒ aucun `cross_country`, `est_duration_min ≤ 45`, `thermals.peak_strength_ms` pendant le créneau ≤ 1,5 (sinon le plan est rejeté). |
| I4 | `plan.difficulty ≤ filters.difficulty` et `plan.difficulty ≥ takeoff.difficulty` (un site sans difficulté renseignée compte comme intermediate). |
| I5 | Heure d'atterrissage estimée (`window.start + est_duration_min`) ≤ coucher du soleil ; atterrissage entre coucher − 30 min et coucher ⇒ `SUNSET` caution et au mieux marginal. |
| I6 | `max_altitude_m ≤ min(plafond utile + 100, 3405)` (FL115 − 100 m, QNH 1013). |
| I7 | `glide.margin_ok = true` et `glide.available_ratio ≤ wing_glide_ratio × 0,75 × (V_air + W)/V_air` (c'est la finesse de calcul sol, pas la finesse polaire). Exception : soaring avec top landing (`required_ratio = 0`). |
| I8 | Aucun `AirspaceWarning` avec `intersects_route = true` et une classe parmi A, C, D, P (ni R/ZRT dont l'activité est connue). |
| I9 | Au plus 2 plans par décollage dans `plans`. |
| I10 | `est_duration_min` dans [`duration_min_minutes`, `duration_max_minutes`], **ou** `summary` explique pourquoi la durée est plus courte (créneau, coucher, surdéveloppement). Jamais plus long que le maximum demandé. |
| I11 | Un plan sans thermiques (`thermal_usage = none`) dure au plus `(alt_déco − alt_atterro) / 1,0 m/s / 60 + 5` min (aucun « plouf de 2 h »), sauf `ridge_soaring`. |
| I12 | `briefing[0]` contient le verdict (« GO », « MARGINAL » ou « NO-GO ») et le niveau requis. Le briefing contient le créneau (« entre hh:mm et hh:mm »), l'atterro principal, « 112 » et « 143,9875 » (ou « 143.9875 »). |
| I13 | `checklist` contient au moins : parachute de secours, sellette/mousquetons, casque, radio, espace aérien/NOTAM, météo/balises. |
| I14 | `confidence ≤` confiance de base de l'horizon × 1,1 (plafond 0,95) (30m 0,90 · 1h 0,85 · 2h 0,80 · 8h 0,70 · 12h 0,65 · 24h 0,55 · 48h 0,40). Un `go` exige `confidence ≥ 0,75 × base`. |
| I15 | Pour `cross_country` : le premier segment part face au vent moyen de la couche de vol, à ± 60° près, si ce vent est ≥ 10 km/h ; distance ≤ `xc_max_distance_km[niveau]`. |
| I16 | Tout plan dont la route touche une zone sensible active, ou un cœur de parc national sous 1000 m sol, porte le Risk `SENSITIVE_AREA` (ou `NATIONAL_PARK`). |
| I17 | Pas de waypoint `thermal_trigger` sur une face à l'ombre à l'ETA (soleil sous 5° ou azimut à plus de 100° de l'orientation de la face) ni sur un lac. |
| I18 | (Phase 2) `filters.difficulty = beginner` ⇒ aucun plan en `mode = custom_takeoff`, et aucun atterro principal ni de secours de kind `community` ou `field`. |
| I19 | (Phase 2) Tout atterro `community` ou `field` d'un plan (principal ou secours) porte dans `warnings` un texte qui contient « Non officiel ». Un `field` n'est jamais l'atterro principal d'un niveau intermediate. |
| I20 | (Phase 2) Horizons 15m, 30m, 1h : `window.start` est dans les bornes du CDC §12.5 et au moins 10 min après `reference_time` ; `briefing[1]` donne la lecture des balises, ou dit qu'il n'y a pas de balise à l'atterro. |
| I21 | (Phase 2) Une `StationReading` avec `representative = false` a un poids nul dans la correction. `weight ≤ beacon_weight_by_minutes(Δt)` (CDC §12.1). |

---

## 4. Bloc machine-readable

Le fichier **`docs/expert/scenarios-validation.yaml`** fait foi. Il est au format `app.engine.scenario.run_scenario(spec)` du backend : heures en UTC, sites et météos factorisés par ancres YAML. Il contient 37 cas :
- 32 dans `scenarios` ;
- 5 dans `scenarios_phase2` (S28-S32), séparés pour que la suite de tests actuelle reste verte. Le backend les charge avec `scenarios + scenarios_phase2` dès qu'il gère les clés d'entrée et d'attente décrites en tête du YAML.

Le tableau du §2 est la lecture humaine du YAML. Le tableau du §2 en est la lecture humaine.
Les valeurs du YAML ont été ajustées pour éviter toute égalité avec un seuil (rafales, vario, brise). Voir les notes du §5.

## 5. Notes pour l'implémentation des tests

1. **Une rafale proche d'un seuil** : « au-delà du seuil » veut dire **strictement supérieur** ⇒ no-go. Une valeur égale au seuil donne un sous-score de 0 ⇒ marginal au mieux. Les scénarios évitent les égalités exactes.
2. **Vent arrière** : tout vent arrière ≥ 5 km/h rend le plan **au mieux marginal**, même s'il reste sous le seuil du niveau (S18b).
3. **Vent nul** (< 5 km/h) : pas de jugement de direction, mais la règle `LEE_SIDE` sur `crest` s'applique toujours (S04).
4. **Fenêtre orage** : CAPE et LI évalués sur `[déco, atterrissage + 2 h]` (S06 : averses à 16 h → no-go pour un déco à 13 h ; S22 : déco à 9 h 30 → marginal).
5. **Brise d'atterro** : facteur × 1,3 entre 13 h et 17 h légales, appliqué à l'heure d'arrivée (S08 : 15 h 30 + ~45 min → dans la plage).
6. **Rejet par niveau** : la raison doit dire pour quel niveau le plan serait valable (« conditions trop fortes pour ton niveau — OK pour brevet confirmé »).
7. **Ridge soaring** : contrôle du vent en altitude remplacé par les seuils de soaring jusqu'à déco + 300 m ; en top landing, pas de contrôle de finesse.
8. **Facteur de rafale** : non bloquant (caution seulement, si moyenne ≥ 15 km/h).
9. **Rotation du vent** : mesurée entre déco + 300 m et le plafond utile, jamais depuis la brise de pente du déco.
10. **Créneau** : `window.start ∈ [cible − 30 min, cible + 3 h]`. On ne déplace pas un vol de 14 h vers le matin ou le soir (S03).
11. Les tests doivent viser le **moteur** (point d'entrée de l'évaluation d'un site), pas l'API HTTP, pour rester rapides et déterministes. Ajouter un test API de fumée sur S01.
12. **Balise d'atterro (S28, S30)** : le poids se calcule sur Δt jusqu'à l'**heure d'arrivée** (créneau + durée), pas sur l'horizon. La tendance s'extrapole sur `min(Δt, 60)` min, plafonnée à + 15 km/h et jamais à la baisse. S28 n'est pas un no-go pour un advanced, car la valeur extrapolée reste sous 25 / 30 ; c'est la tendance seule qui le rend marginal.
13. **Pas de balise d'atterro (S29)** : `NO_LANDING_BEACON` est une caution **non bloquante** pendant les heures de brise. Elle avance la bande marginale de l'atterro à 72 % et multiplie la confiance par 0,9, mais ne touche jamais au seuil de no-go.
14. **Altitude inconnue (S30)** : le chargeur doit simuler un MNT indisponible (pas de `dem_elevation_m`). Avec un MNT disponible, le facteur serait 0,8 au lieu de 0,5 et le poids dépasserait 0,35.
15. **Décollage libre (S31, S32)** : la difficulté du site vaut intermediate. Pour un beginner, toutes les raisons de rejet sont listées (`FREE_TAKEOFF` **et** `DETECTED_FIELD`), pas seulement la première.
16. **Atterros non officiels** : `landing_policy` filtre d'abord, le niveau ensuite (CDC §12.7). En S32 le champ est exclu par la politique `include_community` : il n'apparaît dans aucun plan.
