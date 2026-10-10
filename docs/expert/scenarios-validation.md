# Scénarios de validation métier — Paraglide Manager

> Rédigé par l'expert pilote (référent métier). Ces scénarios **font foi** pour le verdict, le type de vol, la durée et les risques.
> À transformer en `backend/tests/test_expert_scenarios.py` (un test paramétré par scénario + les invariants globaux du §3). Source machine-readable : `scenarios-validation.yaml` : 32 cas actifs (`scenarios`), 5 cas de phase 2, S28 à S32 (`scenarios_phase2`, CDC §12, chargés), et 10 cas de la révision 5, S33 à S41 (`scenarios_phase3`, CDC §14 : vent sur le plané), à charger avec l'implémentation du §14.
> Codes `Risk` : catalogue du §1. Seuils : `cahier-des-charges-pilote.md` §2, §3, §11 et §12 (balises d'atterro, horizon 15 min, décollage libre, atterros non officiels).

---

## 1. Conventions

### 1.1 Codes `Risk` (exacts)

`RAIN, THUNDERSTORM, OVERDEVELOPMENT, SITE_LEVEL, FOEHN, REGIONAL_WIND, LOW_CLOUD_BASE, STRONG_WIND_ALOFT, LEE_SIDE, TAKEOFF_WIND, TAKEOFF_GUSTS, CROSSWIND, TAILWIND, LANDING_WIND, VALLEY_BREEZE, GLIDE_MARGIN, SUNSET, AIRSPACE, AIRSPACE_ACTIVATION, ALTITUDE_LIMIT, SENSITIVE_AREA, NATIONAL_PARK, SITE_CLOSED, SITE_RESTRICTED, WIND_GRADIENT, WIND_SHEAR, STRONG_THERMALS, WEAK_THERMALS, INVERSION, VENTURI, ROTOR, FRONT, FREEZING, WIND_INCREASING, BEACON_MISMATCH, STALE_BEACONS, LOW_CONFIDENCE, MOCK_DATA, ACCESS_TIME`

Phase 2 (CDC §12) : `NO_LANDING_BEACON, WIND_SHIFT, FREE_TAKEOFF, UNOFFICIAL_LANDING, DETECTED_FIELD`. `NO_LANDING_BEACON` est la seule caution **non bloquante** de la liste.

Révision 5 (CDC §14) : `HIGH_ARRIVAL` (« Arrivée haute » : vent arrière sur le plané et hauteur d'arrivée attendue ≥ 300 m ; info, ou caution **non bloquante** au-delà de 500 m pour beginner et intermediate, 700 m pour advanced et expert). `GLIDE_MARGIN` garde son sens, calculé avec la finesse du §14 ; il passe aussi en danger en cas de pénétration insuffisante.

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

Révision 5 (S33-S41) : positions des fixtures / PGE (`app/fixtures/sites.json`), plus justes que les ancres ci-dessus.

| Clé | Déco | Alt. déco | Orientations | Difficulté site | Atterro | Alt. atterro | Distance / cap |
|---|---|---|---|---|---|---|---|
| `forclaz_pge` → `doussard_pge` | Col de la Forclaz, 45.815 N 6.2465 E | 1245 | W, WNW, NW | beginner | Doussard, 45.782 N 6.2224 E (big_valley) | 452 | 4,12 km / 207° ; 4,38 km avec le contournement de la réserve |
| `planfait_fix` → `perroix_fix` | Planfait, 45.857 N 6.2285 E | 1240 | SW, WSW, W | intermediate | Talloires – Perroix, 45.8455 N 6.2135 E (big_valley) | 450 | 1,73 km / 222° |
| `montmin_aulp` → `doussard_pge` | Montmin – Chalet de l'Aulp, 45.804 N 6.273 E | 1420 | S, SSW, SW | intermediate | Doussard | 452 | 4,62 km / 238° |
| `bout_du_lac` (zone) | Réserve naturelle nationale du Bout du Lac d'Annecy : vol libre interdit (`flight_prohibited`), enveloppe à 10 sommets du polygone Biodiv'Sports 1564, à ≈ 330 m au N de l'atterro | — | — | — | — | — | — |

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

**Révision 5 (CDC §14, vent sur le plané, bloc `scenarios_phase3`)**

Tous ces vols sont des ploufs (`thermals: avoid`, 10-20 min). Dans la colonne « Plané », les chiffres sont les valeurs de référence du §14 :
- requise / disponible, et r ;
- composante brute du vent (+ = dans le dos) et part retenue ;
- hauteur d'arrivée attendue.

Entre parenthèses : la valeur du moteur actuel (un seul vent, 100 % crédité, sans travers).

| ID | Site / quand | Situation | Niveau | Verdict attendu | Plané (référence §14) | Risques et contrôles obligatoires | Interdits |
|---|---|---|---|---|---|---|---|
| S33 | forclaz_pge → doussard_pge, 12/09/2026 14:00 (12h) | NNO 13 km/h au déco, brise du lac N 10 × 1,3 = 13 à Doussard, N 15-18 au-dessus de 1550 m (non rencontré) | intermediate | **go** | 5,94 / 8,26 (8,51), r 0,72 ; + 10,8 dans le dos, 8,6 retenus (0,60 + 0,20 brise établie) ; ≈ 370 m | HIGH_ARRIVAL (info) ; gain ≥ 1,15 sur l'air calme ; commentaire « dans le dos » + « arrivée haute » ; briefing « au vent de l'atterro » ; ZPA au vent | GLIDE_MARGIN, TAILWIND, LEE_SIDE |
| S34 | idem + réserve du Bout du Lac, 26/09/2026 14:00 (12h) | NNO 9, brise N 8 × 1,3 ; plané contourné par l'E et le S (4,38 km) | beginner | **go** (« passe aisément ») | 6,33 / 7,70 (8,07), r 0,82 ; + 7,7, 5,4 retenus (0,50 + 0,20) ; ≈ 310 m | commentaire « dans le dos » + « contourn » ; briefing « hors de la zone « Réserve naturelle nationale du Bout du Lac » ; ZPA au vent (à l'E ou à l'O de l'atterro) | GLIDE_MARGIN, SENSITIVE_AREA, TAILWIND |
| S35 | idem S34, calme strict | Vents de 3 à 4 km/h | beginner | **marginal** | 6,33 / 6,78 (7,00), r 0,93 ; aucun crédit (< 5 km/h) ; ≈ 240 m | GLIDE_MARGIN (caution) ; r dans [0,905 ; 0,99] | HIGH_ARRIVAL |
| S36 | forclaz_pge, 12/09/2026 14:00 (12h) | N fort : déco NNO 24 g30, Doussard 19 × 1,3 = 24,7, 26-32 en altitude | intermediate | **rejeté** par le déco et l'atterro, pas par le plané | 5,94 / 8,2 (crédit plafonné à 10 km/h) | TAKEOFF_WIND, LANDING_WIND (danger) ; raison « trop fortes pour ton niveau » | GLIDE_MARGIN dans les raisons de rejet |
| S36b | idem S36 | idem | expert | **marginal** (vent au déco) | 5,78 / 9,11 (9,99), r 0,63 ; + 20,3, 15 retenus (plafond expert) ; ≈ 430 m | TAKEOFF_WIND (caution), HIGH_ARRIVAL (info) | GLIDE_MARGIN, TAILWIND, LEE_SIDE |
| S37 | forclaz_pge, 19/09/2026 14:30 (12h) | Flux de S 16-22 km/h au-dessus de 1550 m seulement ; O 9 au déco, N 4 à Doussard | advanced | **go** | 5,94 / 6,93 (6,89), r 0,86 ; + 1,5 (le S d'altitude n'est pas rencontré) | composante dans [− 3 ; + 4] | GLIDE_MARGIN, HIGH_ARRIVAL |
| S38 | idem S37 + flux de S jusqu'à Doussard (16 × 1,3 = 21 g29) | Plané long (4,1 km) face au vent | advanced | **rejeté** | 5,94 / 4,1 (5,2), r 1,45 ; − 12,5 de face, − 14,9 comptés (rafales) ; 40 km/h, accélérateur compris | GLIDE_MARGIN (danger) ; raison « de face » | go, marginal |
| S39 | planfait_fix → perroix_fix, 19/09/2026 18:30 (12h) | SO 16-17 km/h de face, rafales 20-22 | advanced | **go** | 2,50 / 3,48 (3,77), r 0,72 ; − 16,6 de face, − 19,0 comptés ; demi-barreau 44 km/h (bras hauts : 3,31) | commentaire « de face » + « accélér » ; part retenue ≤ composante brute | GLIDE_MARGIN, HIGH_ARRIVAL, TAKEOFF_WIND |
| S40 | montmin_aulp → doussard_pge, 19/09/2026 18:30 (12h) | SSE 21 km/h de travers (cap 238°) | expert | **marginal** | 5,21 / 5,60 (6,80), r 0,93 ; 0 dans le dos, 21 de travers (crabe 35°) | GLIDE_MARGIN (caution) ; commentaire « de travers » | HIGH_ARRIVAL |
| S41 | idem S33, horizon 48h | Même météo, prévision à 48 h | intermediate | **go** | 5,94 / 7,86, r 0,76 ; 6,5 retenus (0,60 + 0,20 − 0,20) au lieu de 8,6 ; ≈ 370 m | HIGH_ARRIVAL ; part retenue dans [5,0 ; 7,4] (S33 : [7,5 ; 10]) | GLIDE_MARGIN |

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
| I22 | (Rév. 5) `glide.calm_available_ratio` = `wing × k × f` (± 0,01, même k et même f que `available_ratio`). `glide.available_ratio ≤ calm_available_ratio × (V_bras_hauts + plafond(niveau)) / V_bras_hauts + 0,01` : le vent arrière crédité ne dépasse jamais le plafond du niveau (8 / 10 / 12 / 15 km/h). |
| I23 | (Rév. 5) `glide.wind_credit_kmh ≤ glide.wind_along_track_kmh + 0,05` : le vent arrière n'est crédité qu'en partie, la face est comptée en entier ou majorée. Et `wind_credit_kmh ≤ plafond(niveau) + 0,05`. |
| I24 | (Rév. 5) `HIGH_ARRIVAL` n'est jamais `danger`. Sur un plouf (`thermal_usage = none`), il implique `wind_along_track_kmh ≥ 5` et `expected_arrival_height_m ≥ 300`. |
| I25 | (Rév. 5) `glide.comment` est non vide, en français. Il contient « dans le dos » si `wind_along_track_kmh ≥ 5`, et « de face » si `wind_along_track_kmh ≤ − 5`. `expected_arrival_height_m` est non null, sauf en top landing. |

---

## 4. Bloc machine-readable

Le fichier **`docs/expert/scenarios-validation.yaml`** fait foi. Il est au format `app.engine.scenario.run_scenario(spec)` du backend : heures en UTC, sites et météos factorisés par ancres YAML. Il contient 47 cas :
- 32 dans `scenarios` ;
- 5 dans `scenarios_phase2` (S28-S32), d'abord tenus à part, aujourd'hui chargés avec `scenarios` ;
- 10 dans `scenarios_phase3` (S33-S41, CDC §14), tenus à part pour que la suite actuelle reste verte : le moteur actuel les manque sur `HIGH_ARRIVAL` (S33, S36b, S41), le texte « de face » du rejet (S38) et le travers (S40 : go au lieu de marginal). Le backend les charge (`scenarios + scenarios_phase2 + scenarios_phase3`) **en même temps** qu'il implémente le §14 et les nouvelles clés d'attente décrites en tête du YAML.

Le tableau du §2 est la lecture humaine du YAML.
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
17. **Vent rencontré (S33, S37)** : seule compte la tranche [alt. atterro + marge ; alt. de départ]. Le vent au-dessus du déco ne compte pas pour un plouf. En S37, le flux de S de 1550 à 3000 m ne doit pas toucher la finesse (composante ≈ + 1,5 km/h). Un moteur qui le projette encore sur le plané échoue S37.
18. **Crédit du vent arrière (S33, S34, S36b, S41)** : la part retenue dépend du niveau (0,50 / 0,60 / 0,70 / 0,70), des bonus et malus et du plafond. Les plages de `glide_wind_credit` de S33 ([7,5 ; 10,05]) et de S41 ([5,0 ; 7,4]) ne se recouvrent pas : seul l'horizon les sépare (malus 48 h). La brise est « établie » à l'**heure d'arrivée** (13-17 h légales) : un créneau décalé hors de cette plage fait perdre le bonus. C'est pour cela que ces scénarios demandent 10-20 min (plouf à la cible, pas de vol de restitution le soir).
19. **Face et travers (S38, S39, S40)** : la face est majorée par les rafales (`g` ≤ 1,2), donc `wind_credit_kmh` < `wind_along_track_kmh`. L'accélérateur n'est compté qu'à partir du niveau intermediate. En S39, sans le demi-barreau, la finesse tomberait à 3,31 (r = 0,76) : le scénario reste go, mais le commentaire doit dire d'accélérer. En S40, le travers seul fait passer r de 0,77 à 0,93 (`GLIDE_MARGIN` caution).
20. **Contournement (S34, S35)** : `required_ratio` utilise la longueur réelle (4,38 km), et chaque branche a son cap. S35 (calme strict) est le verdict de contrôle : MARGINAL, confirmé par l'expert (CDC §14.6).
21. **Arrivée haute** : `HIGH_ARRIVAL` est **non bloquant**. Un plan go le reste avec `HIGH_ARRIVAL` (S33, S41). La ZPA est au vent de l'atterro, en travers au plus ; à Doussard par N, elle est à l'E ou à l'O, hors de la réserve (S33, S34 : `zpa_upwind_of_landing`).
22. **Anciens scénarios** : le calcul de référence du §14 sur les planés directs déco → atterro de S01-S30 ne fait franchir aucun seuil (r ≤ 0,78 partout). Les planés depuis un point de la route (S05, S09, S25) dépendent du vent en altitude. Si l'un d'eux change de verdict, le constructeur de route doit d'abord relever l'altitude de sécurité du point (§5.4). Si cela ne suffit pas, signaler le cas à l'expert ; ne pas modifier l'attente.
