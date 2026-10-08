# Scénarios de validation métier — Paraglide Manager

> Rédigé par l'expert pilote (référent métier). Ces scénarios **font foi** pour le verdict, le type de vol, la durée et les risques.
> À transformer en `backend/tests/test_expert_scenarios.py` (un test paramétré par scénario + les invariants globaux du §3).
> Codes `Risk` : catalogue du §1. Seuils : `cahier-des-charges-pilote.md` §2, §3 et §11.

---

## 1. Conventions

### 1.1 Codes `Risk` (exacts)

`RAIN, THUNDERSTORM, OVERDEVELOPMENT, FOEHN, REGIONAL_WIND, LOW_CLOUD_BASE, STRONG_WIND_ALOFT, LEE_SIDE, TAKEOFF_WIND, TAKEOFF_GUSTS, CROSSWIND, TAILWIND, LANDING_WIND, VALLEY_BREEZE, GLIDE_MARGIN, SUNSET, AIRSPACE, AIRSPACE_ACTIVATION, ALTITUDE_LIMIT, SENSITIVE_AREA, NATIONAL_PARK, SITE_CLOSED, SITE_RESTRICTED, WIND_GRADIENT, WIND_SHEAR, STRONG_THERMALS, WEAK_THERMALS, INVERSION, VENTURI, ROTOR, FRONT, FREEZING, WIND_INCREASING, BEACON_MISMATCH, STALE_BEACONS, LOW_CONFIDENCE, MOCK_DATA, ACCESS_TIME`

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

Finesse par défaut : 8,5 (EN-B), sauf mention.

---

## 2. Scénarios

> Lecture : **verdict attendu** = `flyability` du meilleur plan pour ce site. Si le scénario dit « rejeté », le site doit figurer dans `rejected` avec la raison indiquée, sans aucun plan go ou marginal pour ce site.
> Fourchettes de durée = `est_duration_min`.

| ID | Site / quand | Situation | Niveau / filtres | Verdict attendu | Type | Durée | Risques obligatoires | Interdits |
|---|---|---|---|---|---|---|---|---|
| S01 | forclaz, 15/07/2026 14:00 | Belle journée thermique, brise du lac | intermediate, allowed, 60-120 | **go** | local | 60-120 | VALLEY_BREEZE (info/caution) | RAIN, THUNDERSTORM, LEE_SIDE, TAILWIND ; cross > 25 km |
| S02 | forclaz, 15/07/2026 19:30 | Restitution du soir | beginner, avoid, 15-45 | **go** | local (`thermal_usage` none/optional) | 15-35 | SUNSET (info) | STRONG_THERMALS, cross_country ; atterrissage après le coucher du soleil |
| S03 | forclaz, 15/07/2026 14:00 | Comme S01 (vario 2,2) | beginner, allowed, 15-45 | **rejeté** (thermiques trop forts, difficulté du plan = intermediate) | — | — | STRONG_THERMALS (danger) | aucun plan go pour beginner sur ce site à 14 h |
| S04 | forclaz, 08/10/2026 13:00 | Faux calme : déco 3 km/h, crête ESE 20 km/h | expert, allowed, 30-120 | **no_go** (tous niveaux) | — | — | LEE_SIDE (danger) | go, marginal |
| S05 | planpraz, 20/07/2026 12:00 | Cross, plafond 3900 (> FL115), CAPE 400 / LI −1 | advanced, required, 120-300, finesse 9,0 | **marginal** | cross_country (ou local) | 120-200 | OVERDEVELOPMENT (caution), ALTITUDE_LIMIT | RAIN ; `max_altitude_m` > 3405 ; atterrissage après 15:00 |
| S06 | planpraz, 21/07/2026 13:00 | Orages : CAPE 1200 / LI −4, averses à 16:00 | expert, allowed, 30-240 | **no_go** | — | — | THUNDERSTORM (danger) | go, marginal |
| S07 | st_hilaire, 16/05/2026 11:00 | Thermique moyen, brise pas encore établie | intermediate, allowed, 30-90 | **go** | local | 30-90 | — | LANDING_WIND (danger), THUNDERSTORM, LEE_SIDE |
| S08 | st_hilaire, 16/05/2026 15:30 | Brise du Grésivaudan établie à l'arrivée (10 m : 17 g24 → ×1,3 ≈ 22) | intermediate, allowed, 30-90 | **rejeté** (atterro : 22 > 20) | — | — | LANDING_WIND ou VALLEY_BREEZE (danger) | go |
| S08b | idem S08 | idem | advanced, allowed, 30-90 | **marginal** (22 = 88 % de 25) | local | 30-90 | VALLEY_BREEZE (caution) | — |
| S09 | chalvet, 13/06/2026 11:30 | Grand cross, NW faible | expert, required, 240-480, cross_country, finesse 9,8 | **go** | cross_country | 240-420 | — | RAIN, THUNDERSTORM, LEE_SIDE ; `max_altitude_m` > 3200 |
| S10 | chalvet, 10/04/2026 12:00 | Mistral : NW 45 km/h à 3000 m, N 30 à la crête | expert, allowed, 30-240 | **no_go** | — | — | STRONG_WIND_ALOFT (danger), LEE_SIDE (danger) | go, marginal |
| S11 | planpraz, 12/10/2026 13:00 | Foehn de S : 700 hPa SSW 55 km/h, déco 20 g38 | expert, allowed, 30-240 | **no_go** | — | — | FOEHN (danger), STRONG_WIND_ALOFT (danger), TAKEOFF_GUSTS (danger) | go, marginal |
| S12 | forclaz, 05/09/2026 14:00 | Pluie 0,5 mm/h, base 1400 | advanced, allowed, 30-120 | **no_go** | — | — | RAIN (danger), LOW_CLOUD_BASE (danger) | go, marginal |
| S13 | forclaz, 05/09/2026 17:00 | Sec à l'heure cible, mais 2,5 mm dans les 3 h précédentes | intermediate, allowed, 30-90 | **no_go** | — | — | RAIN (danger) | go |
| S14 | forclaz, 12/12/2026 13:00 | Mer de nuages : déco au soleil, atterro dans le stratus (T−Td 0,5 °C, couverture basse 100 %) | advanced, allowed, 15-60 | **no_go** | — | — | LOW_CLOUD_BASE (danger) | go, marginal |
| S15 | pyla, 10/08/2026 16:00 | Soaring : WNW 16 g19 | intermediate, avoid, 30-90 | **go** | ridge_soaring | 30-90 | — | cross_country, STRONG_THERMALS |
| S16 | pyla, 11/08/2026 16:00 | Soaring fort : W 26 g30 | intermediate, avoid, 30-90 | **rejeté** (vent > 22, difficulté = advanced) | — | — | TAKEOFF_WIND (danger) | go |
| S16b | idem S16 | idem | expert, avoid, 30-90 | **marginal** (26 = 87 % de 30) | ridge_soaring | 30-90 | TAKEOFF_WIND (caution) | — |
| S17 | planfait, 20/09/2026 13:00 | Travers : NNW 12 km/h (écart 56°) | intermediate, allowed, 30-90 | **rejeté** (> 45°) | — | — | CROSSWIND (danger) | go |
| S17b | idem S17 | idem | advanced, allowed, 30-90 | **marginal** (56° = 93 % de 60°) | local | 30-90 | CROSSWIND (caution) | — |
| S18 | forclaz, 20/09/2026 11:00 | Vent arrière E 6 km/h, crête E 8 | advanced, allowed, 30-90 | **rejeté** (arrière 6 > 5) | — | — | TAILWIND (danger) | go |
| S18b | idem S18 | idem | expert, allowed, 30-90 | **marginal** (tout vent arrière ≥ 5 km/h ⇒ au mieux marginal) | local | 15-90 | TAILWIND (caution) | go |
| S19 | forclaz, 08/10/2026 18:45 | Fin de journée, coucher ≈ 19:05 | intermediate, allowed, 30-90 | **marginal** | local (plouf) | 10-20 | SUNSET (caution) | durée > 20 ; atterrissage après le coucher |
| S20 | forclaz, horizon 30m, réf. 08/10/2026 13:00 | Modèle W 10 km/h, balise du déco N 25 g38 il y a 5 min | advanced, allowed, 30-90 | **no_go** | — | — | TAKEOFF_GUSTS (danger), BEACON_MISMATCH | go, marginal |
| S21 | st_hilaire, horizon 48h, réf. 08/10/2026 11:00 | Modèles en désaccord : SE 10 / 22 / 15 km/h | intermediate, allowed, 30-90 | **marginal** (confiance < 0,5) | local | 30-90 | LOW_CONFIDENCE (caution) | go |
| S22 | chalvet, 25/07/2026 09:30 | Matin calme, orages l'après-midi (CAPE 1200 / LI −4 à 15 h) | intermediate, allowed, 30-180 | **marginal** | local | 30-90 | OVERDEVELOPMENT (caution) | cross_country ; atterrissage après 12:30 ; durée > 90 |
| S23 | deco_technique, 16/05/2026 11:00 | Conditions parfaites | intermediate, allowed, 30-90 | **rejeté** (site advanced > intermediate) | — | — | — | go, marginal |
| S24 | st_hilaire, 16/07/2026 08:30 | Matin calme avant les thermiques : plouf | beginner, avoid, 10-45 | **go** | local (plouf, `thermal_usage` none) | 10-20 | — | cross_country, STRONG_THERMALS ; durée > 25 |

---

## 3. Invariants globaux (à vérifier sur TOUS les plans de TOUS les scénarios et des appels `/api/plans` de démo)

| # | Invariant |
|---|---|
| I1 | Un plan qui porte un Risk `danger` n'est jamais `go` ni `marginal` : il est `no_go` ou rejeté. |
| I2 | Un plan `marginal` porte au moins un Risk `caution` qui l'explique. |
| I3 | `filters.difficulty = beginner` ⇒ aucun `cross_country`, `est_duration_min ≤ 45`, `thermals.peak_strength_ms` pendant le créneau ≤ 1,5 (sinon le plan est rejeté). |
| I4 | `plan.difficulty ≤ filters.difficulty` et `plan.difficulty ≥ takeoff.difficulty` (un site sans difficulté renseignée compte comme intermediate). |
| I5 | Heure d'atterrissage estimée (`window.start + est_duration_min`) ≤ coucher du soleil ; `window.end ≤ coucher − 30 min`. |
| I6 | `max_altitude_m ≤ min(plafond utile + 100, 3405)` (FL115 − 100 m, QNH 1013). |
| I7 | `glide.margin_ok = true` et `glide.available_ratio ≤ wing_glide_ratio × 0,70` (c'est la finesse de calcul, pas la finesse polaire). |
| I8 | Aucun `AirspaceWarning` avec `intersects_route = true` et une classe parmi A, C, D, P (ni R/ZRT dont l'activité est connue). |
| I9 | Au plus 2 plans par décollage dans `plans`. |
| I10 | `est_duration_min` dans [`duration_min_minutes`, `duration_max_minutes`], **ou** `summary` explique pourquoi la durée est plus courte (créneau, coucher, surdéveloppement). Jamais plus long que le maximum demandé. |
| I11 | Un plan sans thermiques (`thermal_usage = none`) dure au plus `(alt_déco − alt_atterro) / 1,0 m/s / 60 + 5` min (aucun « plouf de 2 h »), sauf `ridge_soaring`. |
| I12 | `briefing[0]` contient le verdict (« GO », « MARGINAL » ou « NO-GO ») et le niveau requis. Le briefing contient le créneau (« entre hh:mm et hh:mm »), l'atterro principal, « 112 » et « 143.9875 ». |
| I13 | `checklist` contient au moins : parachute de secours, sellette/mousquetons, casque, radio, espace aérien/NOTAM, météo/balises. |
| I14 | `confidence ≤` confiance de base de l'horizon (30m 0,90 · 1h 0,85 · 2h 0,80 · 8h 0,70 · 12h 0,65 · 24h 0,55 · 48h 0,40). |
| I15 | Pour `cross_country` : le premier segment part face au vent moyen de la couche de vol, à ± 60° près, si ce vent est ≥ 10 km/h ; distance ≤ `xc_max_distance_km[niveau]`. |
| I16 | Tout plan dont la route touche une zone sensible active, ou un cœur de parc national sous 1000 m sol, porte le Risk `SENSITIVE_AREA` (ou `NATIONAL_PARK`). |
| I17 | Pas de waypoint `thermal_trigger` sur une face à l'ombre à l'ETA (soleil sous 5° ou azimut à plus de 100° de l'orientation de la face) ni sur un lac. |

---

## 4. Bloc machine-readable (YAML)

```yaml
defaults:
  wing_glide_ratio: 8.5
  max_results: 5

scenarios:
  - id: S01
    site: forclaz
    local_time: "2026-07-15T14:00"   # 12:00Z
    horizon: "24h"
    filters: {difficulty: intermediate, thermals: allowed, duration_min_minutes: 60, duration_max_minutes: 120}
    weather:
      takeoff: {wind: [12, 290], gust: 18}
      crest: [10, 280]
      aloft: {1500: [12, 270], 2000: [15, 270], 3000: [20, 250]}
      landing: {wind: [12, 0], gust: 18}        # brise du lac (N) ; ×1,3 → 15,6
      cape: 150
      li: 3
      precip_mm_h: 0
      precip_prev_3h_mm: 0
      thermal_ceiling_m: 2800
      cloud_base_m: 3000
      thermal_strength_ms: 2.2
      convection: ["11:00", "18:30"]
      overdevelopment: low
      cloud_cover_low_pct: 20
    expected:
      flyability: go
      flight_type: local
      duration: [60, 120]
      plan_difficulty: intermediate
      risks_required: [VALLEY_BREEZE]
      risks_forbidden: [RAIN, THUNDERSTORM, LEE_SIDE, TAILWIND]

  - id: S02
    site: forclaz
    local_time: "2026-07-15T19:30"   # 17:30Z ; coucher ≈ 21:15
    horizon: "8h"
    filters: {difficulty: beginner, thermals: avoid, duration_min_minutes: 15, duration_max_minutes: 45}
    weather:
      takeoff: {wind: [8, 290], gust: 11}
      crest: [6, 280]
      aloft: {1500: [8, 270], 2000: [10, 270], 3000: [15, 260]}
      landing: {wind: [6, 0], gust: 9}
      cape: 50
      li: 4
      precip_mm_h: 0
      thermal_ceiling_m: 1700
      cloud_base_m: null
      thermal_strength_ms: 0.6            # restitution
      convection: ["11:00", "18:30"]
      overdevelopment: low
    expected:
      flyability: go
      flight_type: local
      thermal_usage_in: [none, optional]
      duration: [15, 35]
      plan_difficulty: beginner
      risks_forbidden: [STRONG_THERMALS, LEE_SIDE]
      flight_types_forbidden: [cross_country]

  - id: S03
    site: forclaz
    local_time: "2026-07-15T14:00"
    horizon: "24h"
    filters: {difficulty: beginner, thermals: allowed, duration_min_minutes: 15, duration_max_minutes: 45}
    weather: {same_as: S01}
    expected:
      rejected: true
      reasons_contain_codes: [STRONG_THERMALS]
      no_plan_with_flyability: [go, marginal]

  - id: S04
    site: forclaz
    local_time: "2026-10-08T13:00"   # 11:00Z
    horizon: "12h"
    filters: {difficulty: expert, thermals: allowed, duration_min_minutes: 30, duration_max_minutes: 120}
    weather:
      takeoff: {wind: [3, 200], gust: 8}
      crest: [20, 112]                     # ESE, à 158° de l'axe W
      aloft: {1500: [22, 110], 2000: [25, 110], 3000: [25, 120]}
      landing: {wind: [8, 90], gust: 14}
      cape: 50
      li: 5
      precip_mm_h: 0
      thermal_ceiling_m: 2000
      cloud_base_m: null
      thermal_strength_ms: 1.2
      convection: ["12:00", "16:30"]
      overdevelopment: low
    expected:
      flyability: no_go
      risks_required: [LEE_SIDE]
      no_plan_with_flyability: [go, marginal]
      applies_to_all_levels: true

  - id: S05
    site: planpraz
    local_time: "2026-07-20T12:00"   # 10:00Z
    horizon: "24h"
    filters: {difficulty: advanced, thermals: required, duration_min_minutes: 120, duration_max_minutes: 300, wing_glide_ratio: 9.0}
    weather:
      takeoff: {wind: [10, 180], gust: 16}
      crest: [10, 220]
      aloft: {1500: [10, 225], 2000: [15, 225], 3000: [22, 270], 4000: [28, 270]}
      landing: {wind: [10, 45], gust: 16}     # brise de l'Arve, vers l'amont
      cape: 400
      li: -1
      precip_mm_h: 0
      thermal_ceiling_m: 3900
      cloud_base_m: 4100
      thermal_strength_ms: 3.0
      convection: ["11:00", "18:30"]
      overdevelopment: moderate
      overdevelopment_time: "16:00"
    expected:
      flyability: marginal
      flight_type_in: [cross_country, local]
      duration: [120, 200]
      landing_before_local: "15:00"         # surdév − 1 h
      max_altitude_m_max: 3405
      risks_required: [OVERDEVELOPMENT, ALTITUDE_LIMIT]
      risks_forbidden: [RAIN]

  - id: S06
    site: planpraz
    local_time: "2026-07-21T13:00"
    horizon: "24h"
    filters: {difficulty: expert, thermals: allowed, duration_min_minutes: 30, duration_max_minutes: 240}
    weather:
      takeoff: {wind: [8, 200], gust: 15}
      crest: [8, 220]
      aloft: {1500: [10, 220], 2000: [12, 220], 3000: [18, 230]}
      landing: {wind: [10, 45], gust: 18}
      cape: 1200
      li: -4
      precip_mm_h: 0
      thermal_ceiling_m: 3800
      cloud_base_m: 2900
      thermal_strength_ms: 3.5
      convection: ["10:30", "18:00"]
      overdevelopment: high
      overdevelopment_time: "14:00"
      timeline: {"16:00": {precip_mm_h: 1.5, cape: 1500, li: -5}}
    expected:
      flyability: no_go
      risks_required: [THUNDERSTORM]
      no_plan_with_flyability: [go, marginal]

  - id: S07
    site: st_hilaire
    local_time: "2026-05-16T11:00"   # 09:00Z
    horizon: "24h"
    filters: {difficulty: intermediate, thermals: allowed, duration_min_minutes: 30, duration_max_minutes: 90}
    weather:
      takeoff: {wind: [8, 135], gust: 14}
      crest: [10, 140]
      aloft: {1500: [15, 180], 2000: [18, 225], 3000: [25, 225]}
      landing: {wind: [10, 45], gust: 15}     # avant 13 h : pas de facteur brise
      cape: 100
      li: 4
      precip_mm_h: 0
      thermal_ceiling_m: 2400
      cloud_base_m: 2600
      thermal_strength_ms: 2.0
      convection: ["10:30", "18:00"]
      overdevelopment: low
    expected:
      flyability: go
      flight_type: local
      duration: [30, 90]
      plan_difficulty: intermediate
      risks_forbidden: [LANDING_WIND, THUNDERSTORM, LEE_SIDE]

  - id: S08
    site: st_hilaire
    local_time: "2026-05-16T15:30"
    horizon: "24h"
    filters: {difficulty: intermediate, thermals: allowed, duration_min_minutes: 30, duration_max_minutes: 90}
    weather:
      takeoff: {wind: [12, 135], gust: 18}
      crest: [12, 150]
      aloft: {1500: [15, 180], 2000: [18, 225], 3000: [25, 225]}
      landing: {wind: [17, 45], gust: 24}     # ×1,3 → 22 km/h (rafales 31)
      cape: 100
      li: 4
      precip_mm_h: 0
      thermal_ceiling_m: 2500
      cloud_base_m: 2700
      thermal_strength_ms: 2.0
      convection: ["10:30", "18:00"]
      overdevelopment: low
    expected:
      rejected: true
      reasons_contain_codes_any: [LANDING_WIND, VALLEY_BREEZE]
      no_plan_with_flyability: [go]

  - id: S08b
    same_as: S08
    filters: {difficulty: advanced, thermals: allowed, duration_min_minutes: 30, duration_max_minutes: 90}
    expected:
      flyability: marginal
      flight_type: local
      risks_required_any: [VALLEY_BREEZE, LANDING_WIND]

  - id: S09
    site: chalvet
    local_time: "2026-06-13T11:30"   # 09:30Z
    horizon: "48h"
    filters: {difficulty: expert, thermals: required, duration_min_minutes: 240, duration_max_minutes: 480, flight_types: [cross_country], wing_glide_ratio: 9.8}
    weather:
      takeoff: {wind: [10, 180], gust: 16}
      crest: [8, 200]
      aloft: {1500: [10, 315], 2000: [15, 315], 3000: [20, 315]}
      landing: {wind: [8, 160], gust: 14}
      cape: 200
      li: 2
      precip_mm_h: 0
      thermal_ceiling_m: 3300
      cloud_base_m: 3500
      thermal_strength_ms: 3.5
      convection: ["10:30", "19:00"]
      overdevelopment: low
    expected:
      flyability: go
      flight_type: cross_country
      duration: [240, 420]
      distance_km: [60, 220]
      max_altitude_m_max: 3200            # plafond utile = min(3300, 3500 − 300)
      first_leg_upwind_of_deg: 315        # ± 60°
      risks_forbidden: [RAIN, THUNDERSTORM, LEE_SIDE]
    note: "La confiance à 48 h (base 0,40) ferait tomber le verdict à marginal : pour ce test, horizon = 24h si la règle confiance < 0,5 ⇒ marginal est appliquée. Le backend choisit l'une des deux variantes et le documente."

  - id: S10
    site: chalvet
    local_time: "2026-04-10T12:00"
    horizon: "24h"
    filters: {difficulty: expert, thermals: allowed, duration_min_minutes: 30, duration_max_minutes: 240}
    weather:
      takeoff: {wind: [15, 330], gust: 30}
      crest: [30, 0]
      aloft: {1500: [30, 330], 2000: [38, 320], 3000: [45, 315]}
      landing: {wind: [20, 330], gust: 35}
      cape: 50
      li: 6
      precip_mm_h: 0
      thermal_ceiling_m: 2600
      cloud_base_m: null
      thermal_strength_ms: 2.5
      convection: ["11:00", "17:00"]
      overdevelopment: low
    expected:
      flyability: no_go
      risks_required: [STRONG_WIND_ALOFT, LEE_SIDE]
      no_plan_with_flyability: [go, marginal]

  - id: S11
    site: planpraz
    local_time: "2026-10-12T13:00"
    horizon: "24h"
    filters: {difficulty: expert, thermals: allowed, duration_min_minutes: 30, duration_max_minutes: 240}
    weather:
      takeoff: {wind: [20, 190], gust: 38}
      crest: [30, 200]
      aloft: {1500: [25, 190], 2000: [40, 200], 3000: [55, 205]}
      landing: {wind: [18, 200], gust: 35}
      cape: 0
      li: 8
      precip_mm_h: 0
      thermal_ceiling_m: 2600
      cloud_base_m: null
      thermal_strength_ms: 1.5
      convection: ["12:00", "16:00"]
      overdevelopment: low
      foehn_dp_hpa: 6                      # Turin − Genève
      rh_700_lee_pct: 30
    expected:
      flyability: no_go
      risks_required: [FOEHN, STRONG_WIND_ALOFT, TAKEOFF_GUSTS]
      no_plan_with_flyability: [go, marginal]

  - id: S12
    site: forclaz
    local_time: "2026-09-05T14:00"
    horizon: "12h"
    filters: {difficulty: advanced, thermals: allowed, duration_min_minutes: 30, duration_max_minutes: 120}
    weather:
      takeoff: {wind: [8, 270], gust: 14}
      crest: [10, 260]
      aloft: {1500: [12, 250], 2000: [15, 250], 3000: [20, 240]}
      landing: {wind: [8, 0], gust: 12}
      cape: 100
      li: 3
      precip_mm_h: 0.5
      thermal_ceiling_m: 1600
      cloud_base_m: 1400
      thermal_strength_ms: 0.5
      convection: ["12:00", "16:00"]
      overdevelopment: low
      cloud_cover_low_pct: 90
    expected:
      flyability: no_go
      risks_required: [RAIN, LOW_CLOUD_BASE]
      no_plan_with_flyability: [go, marginal]

  - id: S13
    site: forclaz
    local_time: "2026-09-05T17:00"
    horizon: "12h"
    filters: {difficulty: intermediate, thermals: allowed, duration_min_minutes: 30, duration_max_minutes: 90}
    weather:
      takeoff: {wind: [8, 280], gust: 12}
      crest: [8, 270]
      aloft: {1500: [10, 260], 2000: [12, 260], 3000: [18, 250]}
      landing: {wind: [6, 0], gust: 10}
      cape: 50
      li: 4
      precip_mm_h: 0
      precip_prev_3h_mm: 2.5
      thermal_ceiling_m: 2000
      cloud_base_m: 2200
      thermal_strength_ms: 1.0
      convection: ["12:00", "18:00"]
      overdevelopment: low
    expected:
      flyability: no_go
      risks_required: [RAIN]
      no_plan_with_flyability: [go]

  - id: S14
    site: forclaz
    local_time: "2026-12-12T13:00"   # 12:00Z (CET)
    horizon: "24h"
    filters: {difficulty: advanced, thermals: allowed, duration_min_minutes: 15, duration_max_minutes: 60}
    weather:
      takeoff: {wind: [5, 270], gust: 8, t_minus_td_c: 8}
      crest: [5, 260]
      aloft: {1500: [8, 260], 2000: [10, 260], 3000: [15, 270]}
      landing: {wind: [2, 0], gust: 4, t_minus_td_c: 0.5, cloud_cover_low_pct: 100}
      cape: 0
      li: 10
      precip_mm_h: 0
      thermal_ceiling_m: 1300
      cloud_base_m: null
      thermal_strength_ms: 0.3
      convection: null
      overdevelopment: low
    expected:
      flyability: no_go
      risks_required: [LOW_CLOUD_BASE]
      no_plan_with_flyability: [go, marginal]

  - id: S15
    site: pyla
    local_time: "2026-08-10T16:00"
    horizon: "24h"
    filters: {difficulty: intermediate, thermals: avoid, duration_min_minutes: 30, duration_max_minutes: 90}
    weather:
      takeoff: {wind: [16, 290], gust: 19}
      crest: [17, 290]
      aloft: {1500: [20, 290], 2000: [22, 290], 3000: [25, 280]}
      landing: {wind: [16, 290], gust: 19}
      cape: 0
      li: 8
      precip_mm_h: 0
      thermal_ceiling_m: 600
      cloud_base_m: null
      thermal_strength_ms: 0.3
      convection: null
      overdevelopment: low
    expected:
      flyability: go
      flight_type: ridge_soaring
      duration: [30, 90]
      thermal_usage_in: [none]
      risks_forbidden: [STRONG_THERMALS]
      flight_types_forbidden: [cross_country]

  - id: S16
    site: pyla
    local_time: "2026-08-11T16:00"
    horizon: "24h"
    filters: {difficulty: intermediate, thermals: avoid, duration_min_minutes: 30, duration_max_minutes: 90}
    weather:
      takeoff: {wind: [26, 270], gust: 30}
      crest: [27, 270]
      aloft: {1500: [30, 270], 2000: [32, 270], 3000: [35, 270]}
      landing: {wind: [26, 270], gust: 30}
      cape: 0
      li: 8
      precip_mm_h: 0
      thermal_ceiling_m: 600
      cloud_base_m: null
      thermal_strength_ms: 0.3
      convection: null
      overdevelopment: low
    expected:
      rejected: true
      reasons_contain_codes: [TAKEOFF_WIND]
      no_plan_with_flyability: [go, marginal]

  - id: S16b
    same_as: S16
    filters: {difficulty: expert, thermals: avoid, duration_min_minutes: 30, duration_max_minutes: 90}
    expected:
      flyability: marginal
      flight_type: ridge_soaring
      plan_difficulty_in: [advanced, expert]
      risks_required: [TAKEOFF_WIND]

  - id: S17
    site: planfait
    local_time: "2026-09-20T13:00"
    horizon: "12h"
    filters: {difficulty: intermediate, thermals: allowed, duration_min_minutes: 30, duration_max_minutes: 90}
    weather:
      takeoff: {wind: [12, 337.5], gust: 16}   # NNW, écart au secteur W = 67,5 − 11,25 = 56°
      crest: [12, 340]
      aloft: {1500: [12, 340], 2000: [15, 340], 3000: [18, 330]}
      landing: {wind: [8, 0], gust: 12}
      cape: 50
      li: 4
      precip_mm_h: 0
      thermal_ceiling_m: 2200
      cloud_base_m: 2500
      thermal_strength_ms: 1.5
      convection: ["12:00", "17:00"]
      overdevelopment: low
    expected:
      rejected: true
      reasons_contain_codes: [CROSSWIND]
      no_plan_with_flyability: [go]

  - id: S17b
    same_as: S17
    filters: {difficulty: advanced, thermals: allowed, duration_min_minutes: 30, duration_max_minutes: 90}
    expected:
      flyability: marginal
      flight_type: local
      risks_required: [CROSSWIND]

  - id: S18
    site: forclaz
    local_time: "2026-09-20T11:00"
    horizon: "12h"
    filters: {difficulty: advanced, thermals: allowed, duration_min_minutes: 30, duration_max_minutes: 90}
    weather:
      takeoff: {wind: [6, 90], gust: 9}
      crest: [8, 90]                       # < 10 km/h : pas de LEE_SIDE
      aloft: {1500: [8, 90], 2000: [10, 90], 3000: [12, 80]}
      landing: {wind: [5, 45], gust: 8}
      cape: 50
      li: 4
      precip_mm_h: 0
      thermal_ceiling_m: 2200
      cloud_base_m: 2500
      thermal_strength_ms: 1.5
      convection: ["11:30", "17:00"]
      overdevelopment: low
    expected:
      rejected: true
      reasons_contain_codes: [TAILWIND]
      no_plan_with_flyability: [go]

  - id: S18b
    same_as: S18
    filters: {difficulty: expert, thermals: allowed, duration_min_minutes: 15, duration_max_minutes: 90}
    expected:
      flyability: marginal
      risks_required: [TAILWIND]
      risks_forbidden: [LEE_SIDE]

  - id: S19
    site: forclaz
    local_time: "2026-10-08T18:45"   # 16:45Z ; coucher ≈ 19:05 CEST
    horizon: "2h"
    filters: {difficulty: intermediate, thermals: allowed, duration_min_minutes: 30, duration_max_minutes: 90}
    weather:
      takeoff: {wind: [6, 290], gust: 9}
      crest: [6, 280]
      aloft: {1500: [8, 270], 2000: [10, 270], 3000: [15, 260]}
      landing: {wind: [4, 0], gust: 6}
      cape: 0
      li: 6
      precip_mm_h: 0
      thermal_ceiling_m: 1500
      cloud_base_m: null
      thermal_strength_ms: 0.3
      convection: ["12:00", "16:30"]
      overdevelopment: low
    expected:
      flyability: marginal
      flight_type: local
      duration: [10, 20]
      landing_before_sunset: true
      risks_required: [SUNSET]
      summary_mentions_shorter_duration: true

  - id: S20
    site: forclaz
    reference_local_time: "2026-10-08T13:00"
    horizon: "30m"
    filters: {difficulty: advanced, thermals: allowed, duration_min_minutes: 30, duration_max_minutes: 90}
    weather:
      takeoff: {wind: [10, 270], gust: 16}
      crest: [12, 270]
      aloft: {1500: [12, 270], 2000: [15, 270], 3000: [20, 260]}
      landing: {wind: [6, 0], gust: 10}
      cape: 50
      li: 4
      precip_mm_h: 0
      thermal_ceiling_m: 2000
      cloud_base_m: 2300
      thermal_strength_ms: 1.5
      convection: ["12:00", "16:30"]
      overdevelopment: low
    beacons:
      - {distance_km: 0.3, delta_alt_m: 0, age_min: 5, wind: [25, 0], gust: 38}
    expected:
      flyability: no_go
      risks_required: [TAKEOFF_GUSTS, BEACON_MISMATCH]
      no_plan_with_flyability: [go, marginal]
    note: "À 30 min et 1 h : rafale retenue = max(rafale balise sur 10 min, rafale fusionnée). Une rafale mesurée tient pour les 30 prochaines minutes."

  - id: S21
    site: st_hilaire
    reference_local_time: "2026-10-08T11:00"
    horizon: "48h"
    filters: {difficulty: intermediate, thermals: allowed, duration_min_minutes: 30, duration_max_minutes: 90}
    weather:
      takeoff: {wind: [15, 135], gust: 20}
      crest: [15, 140]
      aloft: {1500: [15, 160], 2000: [18, 180], 3000: [22, 200]}
      landing: {wind: [8, 45], gust: 12}
      cape: 50
      li: 4
      precip_mm_h: 0
      thermal_ceiling_m: 2000
      cloud_base_m: 2300
      thermal_strength_ms: 1.5
      convection: ["12:00", "16:30"]
      overdevelopment: low
    models:
      arome_france_hd: {takeoff_wind: [10, 135]}
      icon_d2: {takeoff_wind: [22, 150]}
      ecmwf_ifs025: {takeoff_wind: [15, 135]}
    expected:
      flyability: marginal
      confidence_max: 0.40
      risks_required: [LOW_CONFIDENCE]
      no_plan_with_flyability: [go]

  - id: S22
    site: chalvet
    local_time: "2026-07-25T09:30"   # 07:30Z
    horizon: "24h"
    filters: {difficulty: intermediate, thermals: allowed, duration_min_minutes: 30, duration_max_minutes: 180}
    weather:
      takeoff: {wind: [6, 180], gust: 10}
      crest: [6, 200]
      aloft: {1500: [8, 220], 2000: [10, 220], 3000: [12, 230]}
      landing: {wind: [5, 160], gust: 8}
      cape: 150
      li: 1
      precip_mm_h: 0
      thermal_ceiling_m: 2600
      cloud_base_m: 2800
      thermal_strength_ms: 1.8
      convection: ["10:00", "18:00"]
      overdevelopment: high
      overdevelopment_time: "13:30"
      timeline:
        "13:00": {cape: 900, li: -2}
        "15:00": {cape: 1200, li: -4, precip_mm_h: 2.0}
    expected:
      flyability: marginal
      flight_type: local
      duration: [30, 90]
      landing_before_local: "12:30"
      risks_required: [OVERDEVELOPMENT]
      flight_types_forbidden: [cross_country]
    note: "Les règles orage/CAPE s'évaluent sur [déco, atterrissage + 2 h], PAS sur toute la journée : un vol du matin reste possible un jour d'orages l'après-midi."

  - id: S23
    site: deco_technique
    local_time: "2026-05-16T11:00"
    horizon: "24h"
    filters: {difficulty: intermediate, thermals: allowed, duration_min_minutes: 30, duration_max_minutes: 90}
    weather: {same_as: S07}
    expected:
      rejected: true
      no_plan_with_flyability: [go, marginal]
      reason_mentions: "niveau du site"

  - id: S24
    site: st_hilaire
    local_time: "2026-07-16T08:30"   # 06:30Z
    horizon: "12h"
    filters: {difficulty: beginner, thermals: avoid, duration_min_minutes: 10, duration_max_minutes: 45}
    weather:
      takeoff: {wind: [2, 135], gust: 5}
      crest: [5, 160]
      aloft: {1500: [6, 200], 2000: [8, 220], 3000: [12, 240]}
      landing: {wind: [4, 225], gust: 6}   # brise descendante résiduelle
      cape: 50
      li: 4
      precip_mm_h: 0
      thermal_ceiling_m: 1200
      cloud_base_m: null
      thermal_strength_ms: 0.4
      convection: ["10:30", "18:30"]
      overdevelopment: low
    expected:
      flyability: go
      flight_type: local
      thermal_usage_in: [none]
      duration: [10, 20]                   # (980 − 240) / 1,2 / 60 + 3 ≈ 13 min
      plan_difficulty: beginner
      risks_forbidden: [STRONG_THERMALS, LEE_SIDE, TAILWIND]
      flight_types_forbidden: [cross_country]
```

---

## 5. Notes pour l'implémentation des tests

1. **Une rafale proche d'un seuil** : « au-delà du seuil » veut dire **strictement supérieur** ⇒ no-go. Une valeur égale au seuil donne un sous-score de 0 ⇒ marginal au mieux. Les scénarios évitent les égalités exactes.
2. **Vent arrière** : tout vent arrière ≥ 5 km/h rend le plan **au mieux marginal**, même s'il reste sous le seuil du niveau (S18b).
3. **Vent nul** (< 5 km/h) : pas de jugement de direction, mais la règle `LEE_SIDE` sur `crest` s'applique toujours (S04).
4. **Fenêtre orage** : CAPE et LI évalués sur `[déco, atterrissage + 2 h]` (S06 : averses à 16 h → no-go pour un déco à 13 h ; S22 : déco à 9 h 30 → marginal).
5. **Brise d'atterro** : facteur × 1,3 entre 13 h et 17 h légales, appliqué à l'heure d'arrivée (S08 : 15 h 30 + ~45 min → dans la plage).
6. **Rejet par niveau** : la raison doit dire pour quel niveau le plan serait valable (« conditions trop fortes pour ton niveau — OK pour brevet confirmé »).
7. Les tests doivent viser le **moteur** (point d'entrée de l'évaluation d'un site), pas l'API HTTP, pour rester rapides et déterministes. Ajouter un test API de fumée sur S01.
