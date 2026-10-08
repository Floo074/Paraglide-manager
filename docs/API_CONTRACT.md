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
  landing_kind: LandingKind | null; // pour un atterrissage
}

interface Beacon {                   // balise météo temps réel
  id: string; name: string;
  lat: number; lon: number; elevation_m: number | null;
  observed_at: string;
  wind_speed_kmh: number | null;
  wind_gust_kmh: number | null;
  wind_direction_deg: number | null;
  temperature_c: number | null;
  source: BeaconSource;
  stale: boolean;                    // mesure > 30 min
  trend: {                           // tendance sur l'historique récent (null si indisponible)
    window_min: number;              // ex. 60
    speed_change_kmh: number;        // vent moyen actuel − vent moyen au début de la fenêtre
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
  kind: LandingKind;
  score: number;                     // 0..100
  required_glide_ratio: number;      // finesse sol nécessaire depuis le déco (vent compris)
  available_glide_ratio: number;     // finesse de calcul retenue (prudente)
  arrival_height_m: number;          // hauteur estimée à l'arrivée au-dessus de l'atterro
  size_m: { length: number; width: number } | null;
  slope_pct: number | null;
  surface: string | null;            // "prairie", "pré fauché", "plage"…
  obstacles: string[];               // "ligne électrique à 80 m", "forêt en bout de champ"…
  wind_at_arrival: { speed_kmh: number; direction_deg: number; gust_kmh: number } | null;
  community_usage: "frequent" | "occasional" | "unknown";
  access: string | null;             // route / parking / navette
  warnings: string[];                // ex. "Non officiel : autorisation du propriétaire à vérifier"
  reasons: string[];                 // pourquoi ce classement
}

interface ScoreItem { criterion: string; score: number; weight: number; comment: string } // score 0..100

interface FlightPlan {
  id: string;
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
                                     // du verdict : fin des thermiques / surdév − 1 h…, coucher du soleil)
  sun?: { sunrise: string | null; sunset: string | null };          // (optionnel) lever/coucher au déco, ISO UTC
  takeoff: Site;
  landing: Site;
  alternate_landings: Site[];
  landing_analysis: LandingCandidate[]; // atterros candidats évalués, triés (le 1er = landing)
  waypoints: Waypoint[];
  route: { type: "LineString"; coordinates: [number, number, number][] }; // GeoJSON [lon, lat, alt]
  distance_km: number;
  est_duration_min: number;
  max_altitude_m: number;
  glide: { required_ratio: number; available_ratio: number; margin_ok: boolean };
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

### `GET /api/health`
`{ "status": "ok", "data_mode": DataMode, "version": string }`

### `GET /api/sources`
État de chaque fournisseur de données.
`{ "sources": { name: string; kind: "forecast"|"sites"|"beacons"|"airspaces"|"elevation"|"sensitive_areas"; mode: "live"|"mock"|"disabled"; healthy: boolean; requires_api_key: boolean; api_key_configured: boolean; message: string | null; url: string | null }[] }`

### `GET /api/sites?bbox=min_lon,min_lat,max_lon,max_lat`
`{ "sites": Site[] }` — fusion dédoublonnée FFVL + ParaglidingEarth + SpotAir (dédoublonnage < 300 m et nom proche).

### `GET /api/beacons?bbox=min_lon,min_lat,max_lon,max_lat`
`{ "beacons": Beacon[] }`

### `GET /api/airspaces?bbox=min_lon,min_lat,max_lon,max_lat`
GeoJSON `FeatureCollection` ; `properties`: `{ name, airspace_class, type, floor_m, ceiling_m, floor_reference }`.
`floor_m` / `ceiling_m` toujours en m AMSL (FL convertis en atmosphère standard ×30,48 m) ; `floor_reference` :
`"AMSL"` ou `"GND"` (plancher publié par rapport au sol, converti en AMSL avec l'altitude du terrain au centre de la
zone quand elle est connue). `airspace_class` : A…G, `R`, `Q` (dangereuse), `P`, `SIV`, `UNCLASSIFIED`.

### `GET /api/sensitive-areas?bbox=min_lon,min_lat,max_lon,max_lat&time=ISO` (`time` optionnel, défaut maintenant : sert à `active_now`)
Zones sensibles pour la faune (Biodiv'Sports, pratique « aérien / vol libre ») + cœurs de parcs nationaux.
GeoJSON `FeatureCollection` ; `properties` :
`{ id, name, species: string | null, kind: "species" | "regulatory" | "national_park_core", period_months: number[] /* 1..12, mois de sensibilité */, active_now: boolean, recommendation: string /* consigne en français */, min_height_agl_m: number | null /* hauteur de survol recommandée */, source: "biodivsports" | "fixture", url: string | null }`.
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
  mode?: "classic" | "custom_takeoff"; // défaut "classic" = déco ET atterro officiels
  custom_takeoff?: {                 // requis si mode = "custom_takeoff" (ex. vol rando)
    lat: number; lon: number;
    elevation_m?: number;            // sinon altitude terrain (MNT)
    orientations?: string[];         // sinon déduites de la pente (exposition MNT)
    name?: string;
  };
}
```
Réponse :
```ts
interface PlanResponse {
  request_id: string;
  generated_at: string;
  target_time: string;               // reference_time + horizon, arrondi au pas de prévision
  horizon: Horizon;
  zone: Zone;
  data_mode: DataMode;
  plans: FlightPlan[];               // triés par score décroissant
  rejected: { site: Site; reasons: string[] }[];
  warnings: string[];
}
```
Erreurs : `422` si requête invalide (zone > 150 km de rayon / bbox > 3° de côté, durée min > max…).

### `POST /api/landings/analyze`
Analyse des atterrissages possibles depuis un point de décollage libre (clic sur la carte).
Requête : `{ takeoff: { lat, lon, elevation_m?, orientations? }, horizon: Horizon, reference_time?: string, wing_glide_ratio?: number, difficulty: Difficulty, landing_policy: "official_only" | "include_community" | "include_fields" }`
Réponse : `{ takeoff: Site /* source "user" */, target_time: string, glide_cone: GeoJSON Polygon /* zone atteignable avec marge, vent compris */, candidates: LandingCandidate[], warnings: string[] }`

### `GET /api/plans/{id}` → `FlightPlan` (cache mémoire, TTL 6h ; 404 sinon)
### `GET /api/plans/{id}/gpx` → `application/gpx+xml` (GPX 1.1 : `wpt` déco/balises/atterros, `rte` route, `metadata` avec briefing résumé)
### `GET /api/plans/{id}/xctsk` → `application/json` (format tâche XCTrack v1 : déco en `TAKEOFF`, balises, atterro = dernière balise, typée `ESS` et décrite par l'objet `goal` — XCTrack n'a pas de type de balise « GOAL »)
