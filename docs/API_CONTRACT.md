# Contrat d'API — Paraglide Manager

Source de vérité partagée entre le backend (`backend/`, FastAPI) et le frontend (`frontend/`, React).
Toute divergence doit être corrigée **ici d'abord**, puis dans le code.

- Base URL : `/api` (le frontend passe par le proxy Vite en dev : `/api` → `http://localhost:8000`).
- JSON en **snake_case**. Dates en ISO 8601 UTC (`2026-10-08T14:00:00Z`).
- Unités : altitudes en mètres **AMSL** (sauf mention `_agl`), vents en km/h, directions en degrés
  (d'où vient le vent, 0 = Nord), vitesses verticales en m/s, distances en km, durées en minutes.
- Langue des textes destinés au pilote (briefing, risques, titres) : **français**.

## Énumérations

```ts
type Horizon = "15m" | "30m" | "1h" | "2h" | "8h" | "12h" | "24h" | "48h";
type Difficulty = "beginner" | "intermediate" | "advanced" | "expert";
// beginner = élève / brevet initial, intermediate = brevet de pilote,
// advanced = brevet de pilote confirmé, expert = compétiteur / pilote cross aguerri
type ThermalPreference = "required" | "allowed" | "avoid";
type FlightType = "local" | "ridge_soaring" | "cross_country";
type Flyability = "go" | "marginal" | "no_go";
type RiskLevel = "info" | "caution" | "danger";
type SiteSource = "ffvl" | "paraglidingearth" | "spotair" | "osm" | "user" | "fixture";
type LandingKind = "official" | "community" | "field";
// official = atterro officiel / référencé ; community = utilisé par les pilotes (PGE non officiel, OSM free_flying…) ;
// field = champ candidat détecté (OSM + relief), jamais repéré : à vérifier sur place
type BeaconSource = "ffvl" | "pioupiou" | "fixture";
type DataMode = "live" | "mock" | "mixed";
```

## Objets communs

```ts
interface LatLon { lat: number; lon: number }

type Zone =
  | { type: "bbox"; min_lat: number; min_lon: number; max_lat: number; max_lon: number }
  | { type: "circle"; center: LatLon; radius_km: number };

interface Site {
  id: string;                       // préfixé par la source : "ffvl:1234", "pge:5678", "fixture:forclaz"
  name: string;
  kind: "takeoff" | "landing" | "both";
  lat: number; lon: number;
  elevation_m: number;
  orientations: string[];           // secteurs favorables, rose 16 points : ["N","NNE",...,"NNW"]
  difficulty: Difficulty | null;    // niveau minimum conseillé pour le site
  flight_types: FlightType[];
  description: string | null;
  access: string | null;
  restrictions: string | null;      // consignes du site, réglementation locale
  status: "open" | "restricted" | "closed" | "unknown";
  source: SiteSource;
  url: string | null;
  associated_landing_ids: string[]; // pour un décollage : atterrissages officiels associés
  official: boolean;                // site officiel / référencé (FFVL, PGE validé, fixture)
  landing_kind: LandingKind | null; // pour un atterrissage : toujours renseigné si kind = "landing" | "both"
                                    // (déduit de `official` si la source ne le donne pas) ; null pour un décollage
}
// Décollage libre : Site source "user", id "user:{lat},{lon}" (5 décimales), kind "takeoff", official false,
// difficulty null (= intermediate), flight_types ["local", "cross_country"], orientations = pilote ou exposition MNT ± 22,5°.

interface Beacon {                   // balise météo temps réel
  id: string; name: string;
  lat: number; lon: number; elevation_m: number | null;
  observed_at: string;
  wind_speed_kmh: number | null;
  wind_gust_kmh: number | null;
  wind_direction_deg: number | null;
  temperature_c: number | null;
  source: BeaconSource;
  stale: boolean;                    // mesure ANCIENNE (> 30 min) ou balise éteinte ; une mesure récente sans
                                     // donnée de vent garde stale = false et wind_speed_kmh = null (« mesure absente »)
  trend: {                           // tendance sur l'historique récent (null si indisponible ; GET /api/beacons la
                                     // calcule pour au plus 8 balises Pioupiou affichées, cache 2 min)
    window_min: number;              // ex. 60
    speed_change_kmh: number;        // pente de la régression linéaire sur tous les échantillons × window_min :
                                     // taux = speed_change_kmh × 60 / window_min (km/h/h)
    direction_change_deg: number;    // rotation signée (+ = horaire)
    gust_max_kmh: number | null;     // rafale max sur la fenêtre
    samples: number;
  } | null;
}

interface StationReading {           // balise rattachée à un site du plan (nowcasting)
  site_role: "takeoff" | "landing" | "alternate_landing";
  site_id: string;
  beacon: Beacon;
  distance_km: number;
  altitude_diff_m: number;           // balise − site
  representative: boolean;           // assez proche/fraîche/à la bonne altitude pour corriger la prévision
  weight: number;                    // poids appliqué dans la correction (0..1)
  comment: string;                   // ex. "Doussard : 12 km/h NNW, rafales 18, il y a 4 min — conforme à la prévision"
}

interface WindLevel { altitude_m: number; pressure_hpa: number | null; speed_kmh: number; direction_deg: number }

interface SoundingLevel {            // pour l'émagramme
  pressure_hpa: number; altitude_m: number;
  temperature_c: number; dew_point_c: number;
  wind_speed_kmh: number; wind_direction_deg: number;
}

interface WeatherSnapshot {
  time: string;
  model: string;                     // ex. "arome_france_hd", "icon_d2", "ecmwf_ifs025", "synthetic"
  lat: number; lon: number; elevation_m: number;
  temperature_c: number; dew_point_c: number;
  wind_10m: { speed_kmh: number; direction_deg: number; gust_kmh: number };
  winds_aloft: WindLevel[];          // triés par altitude croissante
  cloud_cover_pct: number; cloud_cover_low_pct: number;
  precipitation_mm_h: number;
  cape_j_kg: number; lifted_index: number | null; cin_j_kg: number | null;
  freezing_level_m: number | null;
  boundary_layer_height_agl_m: number;
  thermal_ceiling_m: number;         // plafond thermique AMSL (calculé)
  cloud_base_m: number | null;       // base des cumulus AMSL, null si thermiques purs (bleus)
  thermal_strength_ms: number;       // vario moyen estimé en thermique (m/s)
  wstar_ms: number;                  // vitesse convective de Deardorff
  shortwave_radiation_w_m2: number;
  nowcast_correction: {              // correction court terme par balises (horizons <= 2h), au déco ET à l'atterro
    beacon_ids: string[]; wind_speed_bias_kmh: number; wind_direction_bias_deg: number;
  } | null;
}
// Dans un FlightPlan, wind_10m = vent RETENU au site : au déco (weather.takeoff et weather.timeline[*]),
// vent interpolé à l'altitude réelle du déco, nowcast inclus, rafales mises à l'échelle ; à l'atterro
// (weather.landing), vent à l'heure d'arrivée, facteur de brise de vallée inclus. Le 10 m brut du modèle
// reste dans GET /api/forecast/point (usage carte).

interface ThermalAnalysis {
  convection_start: string | null;
  convection_end: string | null;
  peak_time: string | null;
  peak_strength_ms: number;
  ceiling_m: number;
  cumulus: boolean;
  overdevelopment_risk: "low" | "moderate" | "high";
  comment: string;
}

interface Risk { code: string; level: RiskLevel; title: string; detail: string }
// codes : catalogue du cahier des charges ; §12 ajoute NO_LANDING_BEACON, WIND_SHIFT, FREE_TAKEOFF (décollage libre :
// info / caution / danger selon le niveau), UNOFFICIAL_LANDING (atterro communautaire), DETECTED_FIELD (champ détecté).
// Revue finale (10/10/2026) : ROTOR (no-go, atterro sous le vent d'un relief, MNT réel), FRONT (aussi : pression en
// baisse ≥ 3 hPa en 3 h, no-go), ALTITUDE_LIMIT (aussi : décollage au-dessus du FL115, caution BLOQUANTE, réservé
// expert), AIRSPACE (aussi : « Espaces aériens non vérifiés », caution, quand OpenAIP manque en live),
// SENSITIVE_AREA (zone où le vol libre est interdit, ou survol réglementé sous sa hauteur : no-go), UNCHECKED (info :
// règles du CDC non vérifiées par l'outil, détail en texte).
// Raisons de rejet préfixées « [CODE] », une seule par code (la plus grave).

interface Waypoint {
  name: string; lat: number; lon: number; altitude_m: number;
  type: "takeoff" | "turnpoint" | "thermal_trigger" | "landing" | "alternate_landing";
  radius_m: number | null;           // rayon de validation (balise XCTrack)
  eta_min: number | null;            // minutes depuis le décollage
  note: string | null;
}

interface AirspaceWarning {
  name: string; airspace_class: string; type: string;
  floor_m: number; ceiling_m: number;
  min_distance_km: number;           // distance mini entre la route et l'espace
  intersects_route: boolean;
}

interface LandingCandidate {
  site: Site;                        // site.landing_kind renseigné ; source "osm" pour un champ détecté
                                     // ("fixture" pour un terrain de démonstration, nom suffixé « démo »)
  kind: LandingKind;
  use: "main" | "alternate";         // usage permis au niveau du pilote : principal possible / secours seulement
                                     // (ex. champ pour un brevet de pilote, communautaire peu fréquenté) (CDC §12.7)
  score: number;                     // 0..100
  required_glide_ratio: number;      // finesse sol nécessaire depuis le déco (vent compris), hauteur d'arrivée mini
                                     // du kind déduite (officiel : marge §2.3 ; communautaire / champ : 100-200 m)
  available_glide_ratio: number;     // finesse de calcul retenue (prudente), × 0,90 communautaire / × 0,80 champ
  arrival_height_m: number;          // hauteur estimée à l'arrivée au-dessus de l'atterro
  size_m: { length: number; width: number } | null;
  slope_pct: number | null;
  surface: string | null;            // "prairie", "pré fauché", "plage"…
  obstacles: string[];               // "ligne électrique à 80 m", "forêt en bout de champ"…
  wind_at_arrival: { speed_kmh: number; direction_deg: number; gust_kmh: number } | null;
  community_usage: "frequent" | "occasional" | "unknown";
  access: string | null;             // route / parking / navette
  warnings: string[];                // ex. "Non officiel : autorisation du propriétaire à vérifier" (toujours pour
                                     // community / field), saison des foins, obstacles proches, données manquantes
  reasons: string[];                 // pourquoi ce classement (2-3 sous-scores décisifs ; « Écarté : … » le cas échéant)
}

interface ScoreItem { criterion: string; score: number; weight: number; comment: string } // score 0..100

interface FlightPlan {
  id: string;                        // dépend de TOUTE la requête (zone, horizon, référence, mode, filtres) : un id ne
                                     // désigne jamais deux contenus différents (GET /api/plans/{id}, GPX, .xctsk)
  rank: number;
  score: number;                     // 0..100
  flyability: Flyability;
  difficulty: Difficulty;            // difficulté estimée de CE vol dans CES conditions
  flight_type: FlightType;
  thermal_usage: "none" | "optional" | "essential";
  title: string;                     // "Col de la Forclaz → Doussard · local thermique 1h30"
  summary: string;                   // 1-2 phrases
  target_time: string;
  window: { start: string; end: string; latest_landing?: string };   // créneau de décollage recommandé ;
                                     // latest_landing (optionnel) = min(window.end + est_duration_min, plafond horaire
                                     // du verdict : fin des thermiques / surdév − 1 h…, coucher du soleil) ; garanti :
                                     // window.end + est_duration_min ≤ latest_landing, jamais au-dessus du plafond
                                     // horaire ; au quart d'heure dès 12 h d'horizon. window.end peut valoir
                                     // window.start (« décoller à hh:mm, pas plus tard »)
  sun?: { sunrise: string | null; sunset: string | null };          // (optionnel) lever/coucher au déco, ISO UTC
  takeoff: Site;
  landing: Site;
  alternate_landings: Site[];        // secours ATTEIGNABLES avec la marge (r ≤ 1, relief dégagé) depuis le déco
                                     // (plouf, soaring) ou un point de la route à son altitude de sécurité (local,
                                     // cross), vent d'arrivée dans les seuils du niveau ; jamais un terrain hors de
                                     // portée (absent aussi des waypoints, du briefing et de landing_analysis)
  landing_analysis: LandingCandidate[]; // atterros évalués (≤ 8), le 1er = landing, puis secours et autres candidats
                                     // utilisables par score ; mode classique : officiels seulement
  waypoints: Waypoint[];
  route: { type: "LineString"; coordinates: [number, number, number][] }; // GeoJSON [lon, lat, alt]
  distance_km: number;
  est_duration_min: number;
  max_altitude_m: number;
  glide: { required_ratio: number; available_ratio: number; margin_ok: boolean }; // atterro non officiel :
                                     // available_ratio inclut le facteur f (0,90 / 0,80) et la hauteur d'arrivée mini
  weather: { takeoff: WeatherSnapshot; landing: WeatherSnapshot; timeline: WeatherSnapshot[] }; // timeline horaire au déco, fenêtre ±3h
  thermals: ThermalAnalysis;
  sounding: SoundingLevel[];
  beacons_nearby: Beacon[];
  station_readings: StationReading[]; // balises du déco, de l'atterro et des atterros de secours
  airspaces: AirspaceWarning[];
  risks: Risk[];
  briefing: string[];                // puces ordonnées, en français
  checklist: string[];
  score_breakdown: ScoreItem[];
  confidence: number;                // 0..1 (dispersion inter-modèles, horizon, fraîcheur balises)
  sources: { name: string; url: string | null; fetched_at: string; mode: "live" | "mock" }[];
  links: { gpx: string; xctsk: string };    // "/api/plans/{id}/gpx", "/api/plans/{id}/xctsk"
}
```

## Endpoints

Erreurs communes à toutes les routes : `422` requête invalide ; `503` JSON `{ "detail": string }` quand une source
indispensable est indisponible en `live` (réseau, quota HTTP 429 : le message dit quand la source sera réessayée).
Le front affiche ce `detail` au pilote et ne bascule PAS en démonstration sur un 503 JSON (seulement si le backend est
injoignable : réseau, 502/504, réponse non JSON). En `live`, `GET /api/sites` reste servi si seul le MNT manque
(altitudes de la source gardées, sites sans altitude écartés).

### `GET /api/health`
`{ "status": "ok", "data_mode": DataMode, "version": string }`

### `GET /api/sources`
État de chaque fournisseur de données.
`{ "sources": { name: string; kind: "forecast"|"sites"|"beacons"|"airspaces"|"elevation"|"sensitive_areas"; mode: "live"|"mock"|"disabled"; healthy: boolean; requires_api_key: boolean; api_key_configured: boolean; message: string | null; url: string | null }[] }`
(inclut « OpenStreetMap / Overpass (champs candidats, atterros vol libre, obstacles) », kind `sites`, `disabled` par
défaut ; une source suspendue après un HTTP 429 le dit dans `message`.)

### `GET /api/sites?bbox=min_lon,min_lat,max_lon,max_lat`
`{ "sites": Site[] }` — fusion dédoublonnée FFVL + ParaglidingEarth + SpotAir (dédoublonnage < 300 m et nom proche).

### `GET /api/beacons?bbox=min_lon,min_lat,max_lon,max_lat`
`{ "beacons": Beacon[] }`

### `GET /api/airspaces?bbox=min_lon,min_lat,max_lon,max_lat`
GeoJSON `FeatureCollection` ; `properties`: `{ name, airspace_class, type, floor_m, ceiling_m, floor_reference,
ceiling_reference, floor_height_m, ceiling_height_m }`.
`floor_m` / `ceiling_m` en m AMSL (FL convertis en atmosphère standard ×30,48 m) ; `floor_reference` /
`ceiling_reference` : `"AMSL"` ou `"GND"` (limite publiée par rapport au sol, ex. « 1000 ft ASFC », R30C, parcs
`LOW_OVERFLIGHT`) ; pour une limite `"GND"`, `floor_height_m` / `ceiling_height_m` donnent la HAUTEUR publiée et
`floor_m` / `ceiling_m` une valeur AMSL indicative (terrain réel au centre de la zone ; sans MNT réel, la hauteur
seule). Le moteur convertit les limites sol point par point le long de la route (MNT ; inconnu = chevauchement
supposé). `airspace_class` : A…G, `R`, `Q` (dangereuse), `P`, `SIV`, `UNCLASSIFIED`.
La collection porte aussi `unverified: boolean` et `warning: string | null` : hors `DATA_MODE=mock`, JAMAIS d'espaces
de démonstration ; OpenAIP indisponible (et pas de fichier OpenAir) → liste vide ou partielle, `unverified = true`, et
les plans portent un `Risk` AIRSPACE caution « Espaces aériens non vérifiés » + un avertissement. OpenAIP est chargé
par tuiles de 1° (cache 24 h), un appel au plus toutes les 5 min.

### `GET /api/sensitive-areas?bbox=min_lon,min_lat,max_lon,max_lat&time=ISO` (`time` optionnel, défaut maintenant : sert à `active_now`)
Zones sensibles pour la faune (Biodiv'Sports, pratique « aérien / vol libre ») + cœurs de parcs nationaux.
GeoJSON `FeatureCollection` ; `properties` :
`{ id, name, species: string | null, kind: "species" | "regulatory" | "national_park_core", period_months: number[] /* 1..12, mois de sensibilité */, active_now: boolean, recommendation: string /* consigne en français */, min_height_agl_m: number | null /* hauteur de survol recommandée */, source: "biodivsports" | "fixture", url: string | null, flight_prohibited: boolean /* parapente / sports aériens interdits dans la zone, à toute hauteur */ }`.
Une zone `flight_prohibited` traversée (à toute hauteur), ou une zone réglementée survolée sous sa hauteur, est un
no-go (`SENSITIVE_AREA` danger) ; le routeur contourne les zones interdites et le briefing Atterrissage le dit
(« PTU et approche hors de la zone … »).
Les zones actives au temps cible et touchées par la route produisent un `Risk` (code `SENSITIVE_AREA`) dans le plan de vol.

### `GET /api/forecast/point?lat=..&lon=..&time=ISO`
`{ "snapshot": WeatherSnapshot, "sounding": SoundingLevel[], "timeline": WeatherSnapshot[] }` (timeline horaire sur la journée).

### `GET /api/forecast/grid?bbox=min_lon,min_lat,max_lon,max_lat&time=ISO&layer=..&altitude_m=..`
- `layer` ∈ `wind | thermal | cloudbase | ceiling | cape | precipitation | useful_height`
  (`useful_height` = plafond utile − terrain, unit `"m_agl"` (m/sol) : « où peut-on tenir en l'air » ; `cloudbase` : points
  sans cumulus omis ; `legend` = min/max des valeurs présentes ; grille ≤ 20×20 en mock, ≤ 10×10 en live)
- `altitude_m` (pour `wind`) ∈ `10 | 1000 | 1500 | 2000 | 2500 | 3000 | 4000` (défaut 10)
- Grille ≤ 20×20 points.

```ts
{
  time: string; layer: string; altitude_m: number | null; unit: string;
  resolution_deg: number;
  points: { lat: number; lon: number; value: number; direction_deg: number | null }[];
  legend: { min: number; max: number };
}
```

### `POST /api/plans`
Requête :
```ts
interface PlanRequest {
  zone: Zone;
  horizon: Horizon;
  reference_time?: string;           // défaut : maintenant
  filters: {
    duration_min_minutes: number;    // ex. 15
    duration_max_minutes: number;    // ex. 120
    difficulty: Difficulty;          // niveau du pilote = difficulté max acceptée
    thermals: ThermalPreference;
    flight_types?: FlightType[];     // défaut : tous
    max_results?: number;            // défaut 5, max 20
    wing_glide_ratio?: number;       // finesse de l'aile, défaut 8.5
    landing_policy?: "official_only" | "include_community" | "include_fields"; // défaut "official_only"
  };
  mode?: "classic" | "custom_takeoff"; // défaut "classic" = déco ET atterro officiels : les décos non officiels de la
                                     // zone sont listés dans `rejected` (non évalués) ; landing_policy autre
                                     // qu'official_only y est ignorée (warning). custom_takeoff : `zone` est ignorée
                                     // pour les décollages (seul le point est évalué), atterros cherchés à ≤ 20 km
  custom_takeoff?: {                 // requis si mode = "custom_takeoff" (ex. vol rando)
    lat: number; lon: number;
    elevation_m?: number;            // sinon altitude terrain (MNT)
    orientations?: string[];         // sinon déduites de la pente (exposition MNT) ; rose 16 points (O/SO… acceptés)
    name?: string;
  };
}
// mode = "custom_takeoff" sans custom_takeoff → 422. Altitude absente et MNT indisponible → 422 (« indique elevation_m »).
// Élève (beginner) : aucun plan, rejet « [FREE_TAKEOFF] Décollage libre non proposé au niveau élève… » + raison atterro.
```
Réponse :
```ts
interface PlanResponse {
  request_id: string;
  generated_at: string;
  target_time: string;               // reference_time + horizon, arrondi au pas de prévision : 15 min pour 15m, 30m
                                     // et 1h, l'heure au-delà (demie vers le haut) ; c'est AUSSI l'heure évaluée par le
                                     // moteur et FlightPlan.target_time ; le front arrondit de la même façon
  horizon: Horizon;
  zone: Zone;
  data_mode: DataMode;
  plans: FlightPlan[];               // ordre de `rank` : verdict (go > marginal), durée dans la plage demandée, score
                                     // plafonné puis non plafonné (revue moniteur, lot 6.2) ; diversité CDC §9.4 (≤ 2 par
                                     // déco dans les 5 premiers) : un `marginal` mieux noté peut suivre un `go`
  rejected: { site: Site; reasons: string[] }[];
  warnings: string[];
}
```
Erreurs : `422` si requête invalide (zone > 150 km de rayon / bbox > 3° de côté, durée min > max…).

### `POST /api/landings/analyze`
Analyse des atterrissages possibles depuis un point de décollage libre (clic sur la carte).
Requête : `{ takeoff: { lat, lon, elevation_m?, orientations?, name? }, horizon: Horizon, reference_time?: string, wing_glide_ratio?: number /* défaut 8.5 */, difficulty: Difficulty, landing_policy?: "official_only" | "include_community" | "include_fields" /* défaut official_only */ }`
Réponse : `{ takeoff: Site /* source "user" */, target_time: string, glide_cone: GeoJSON Polygon /* zone atteignable avec marge, vent compris */, candidates: LandingCandidate[], warnings: string[] }`
- `candidates` : atterros **utilisables** à ce niveau (portée de plané, politique, usage par niveau, critères minimaux),
  principaux possibles d'abord puis par score (≤ 8). Les meilleurs candidats écartés et la cause sont dans `warnings`
  (ex. « « Pré X » (champ détecté) écarté : pente de 12 % (maximum 8 %) »), ainsi que le refus élève, la politique
  forcée (élève : officiels seulement) et la lecture du MNT au point (pente, exposition, profil de l'axe).
- `glide_cone` : anneau de 36 caps (fermé), finesse de calcul du niveau (k) vent compris, marge d'arrivée du niveau,
  raccourci là où le relief coupe la ligne de plané (MNT réel).
- Erreurs : `422` (requête invalide, altitude inconnue sans MNT), `503` (source indispensable indisponible en `live`).

### `GET /api/plans/{id}` → `FlightPlan` (cache mémoire, TTL 6h ; 404 sinon)
### `GET /api/plans/{id}/gpx` → `application/gpx+xml` (GPX 1.1 : `wpt` déco/balises/atterros, `rte` route, `metadata` avec briefing résumé)
### `GET /api/plans/{id}/xctsk` → `application/json` (format tâche XCTrack v1 : déco en `TAKEOFF`, balises, atterro = dernière balise, typée `ESS` et décrite par l'objet `goal` — XCTrack n'a pas de type de balise « GOAL »)
