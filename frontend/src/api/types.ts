/**
 * Types de l'API Paraglide Manager.
 *
 * Transcription EXACTE de docs/API_CONTRACT.md (source de vérité).
 * Toute évolution du contrat doit d'abord être faite dans ce document, puis reportée ici.
 * JSON en snake_case, dates ISO 8601 UTC, altitudes en m AMSL (sauf `_agl`), vents en km/h,
 * directions en degrés (provenance, 0 = Nord), vitesses verticales en m/s, distances en km,
 * durées en minutes.
 */

// ───────────────────────────── Énumérations ─────────────────────────────

export type Horizon = "15m" | "30m" | "1h" | "2h" | "8h" | "12h" | "24h" | "48h";
export type Difficulty = "beginner" | "intermediate" | "advanced" | "expert";
// beginner = élève / brevet initial, intermediate = brevet de pilote,
// advanced = brevet de pilote confirmé, expert = compétiteur / pilote cross aguerri
export type ThermalPreference = "required" | "allowed" | "avoid";
export type FlightType = "local" | "ridge_soaring" | "cross_country";
export type Flyability = "go" | "marginal" | "no_go";
export type RiskLevel = "info" | "caution" | "danger";
export type SiteSource = "ffvl" | "paraglidingearth" | "spotair" | "osm" | "user" | "fixture";
export type LandingKind = "official" | "community" | "field";
// official = atterro officiel / référencé ; community = utilisé par les pilotes (PGE non officiel, OSM free_flying…) ;
// field = champ candidat détecté (OSM + relief), jamais repéré : à vérifier sur place
export type BeaconSource = "ffvl" | "pioupiou" | "fixture";
export type DataMode = "live" | "mock" | "mixed";

// ───────────────────────────── Objets communs ─────────────────────────────

export interface LatLon {
  lat: number;
  lon: number;
}

export type Zone =
  | { type: "bbox"; min_lat: number; min_lon: number; max_lat: number; max_lon: number }
  | { type: "circle"; center: LatLon; radius_km: number };

export type BBoxZone = Extract<Zone, { type: "bbox" }>;
export type CircleZone = Extract<Zone, { type: "circle" }>;

export interface Site {
  id: string; // préfixé par la source : "ffvl:1234", "pge:5678", "fixture:forclaz"
  name: string;
  kind: "takeoff" | "landing" | "both";
  lat: number;
  lon: number;
  elevation_m: number;
  orientations: string[]; // secteurs favorables, rose 16 points : ["N","NNE",...,"NNW"]
  difficulty: Difficulty | null; // niveau minimum conseillé pour le site
  flight_types: FlightType[];
  description: string | null;
  access: string | null;
  restrictions: string | null; // consignes du site, réglementation locale
  status: "open" | "restricted" | "closed" | "unknown";
  source: SiteSource;
  url: string | null;
  associated_landing_ids: string[]; // pour un décollage : atterrissages officiels associés
  official: boolean; // site officiel / référencé (FFVL, PGE validé, fixture)
  landing_kind: LandingKind | null; // pour un atterrissage
}

export interface Beacon {
  // balise météo temps réel
  id: string;
  name: string;
  lat: number;
  lon: number;
  elevation_m: number | null;
  observed_at: string;
  wind_speed_kmh: number | null;
  wind_gust_kmh: number | null;
  wind_direction_deg: number | null;
  temperature_c: number | null;
  source: BeaconSource;
  stale: boolean; // mesure > 30 min
  trend: BeaconTrend | null; // tendance sur l'historique récent (null si indisponible)
}

/** Beacon.trend (le contrat la décrit en ligne ; nommée ici pour la réutiliser). */
export interface BeaconTrend {
  window_min: number; // ex. 60
  speed_change_kmh: number; // vent moyen actuel − vent moyen au début de la fenêtre
  direction_change_deg: number; // rotation signée (+ = horaire)
  gust_max_kmh: number | null; // rafale max sur la fenêtre
  samples: number;
}

export type StationRole = "takeoff" | "landing" | "alternate_landing";

export interface StationReading {
  // balise rattachée à un site du plan (nowcasting)
  site_role: StationRole;
  site_id: string;
  beacon: Beacon;
  distance_km: number;
  altitude_diff_m: number; // balise − site
  representative: boolean; // assez proche/fraîche/à la bonne altitude pour corriger la prévision
  weight: number; // poids appliqué dans la correction (0..1)
  comment: string; // ex. "Doussard : 12 km/h NNW, rafales 18, il y a 4 min — conforme à la prévision"
}

export interface WindLevel {
  altitude_m: number;
  pressure_hpa: number | null;
  speed_kmh: number;
  direction_deg: number;
}

export interface SoundingLevel {
  // pour l'émagramme
  pressure_hpa: number;
  altitude_m: number;
  temperature_c: number;
  dew_point_c: number;
  wind_speed_kmh: number;
  wind_direction_deg: number;
}

export interface WeatherSnapshot {
  time: string;
  model: string; // ex. "arome_france_hd", "icon_d2", "ecmwf_ifs025", "synthetic"
  lat: number;
  lon: number;
  elevation_m: number;
  temperature_c: number;
  dew_point_c: number;
  wind_10m: { speed_kmh: number; direction_deg: number; gust_kmh: number };
  winds_aloft: WindLevel[]; // triés par altitude croissante
  cloud_cover_pct: number;
  cloud_cover_low_pct: number;
  precipitation_mm_h: number;
  cape_j_kg: number;
  lifted_index: number | null;
  cin_j_kg: number | null;
  freezing_level_m: number | null;
  boundary_layer_height_agl_m: number;
  thermal_ceiling_m: number; // plafond thermique AMSL (calculé)
  cloud_base_m: number | null; // base des cumulus AMSL, null si thermiques purs (bleus)
  thermal_strength_ms: number; // vario moyen estimé en thermique (m/s)
  wstar_ms: number; // vitesse convective de Deardorff
  shortwave_radiation_w_m2: number;
  nowcast_correction: {
    // correction court terme par balises (horizons <= 2h), au déco ET à l'atterro
    beacon_ids: string[];
    wind_speed_bias_kmh: number;
    wind_direction_bias_deg: number;
  } | null;
}
// Dans un FlightPlan, wind_10m = vent RETENU au site : au déco (weather.takeoff et weather.timeline[*]),
// vent interpolé à l'altitude réelle du déco, nowcast inclus, rafales mises à l'échelle ; à l'atterro
// (weather.landing), vent à l'heure d'arrivée, facteur de brise de vallée inclus. Le 10 m brut du modèle
// reste dans GET /api/forecast/point (usage carte).

export interface ThermalAnalysis {
  convection_start: string | null;
  convection_end: string | null;
  peak_time: string | null;
  peak_strength_ms: number;
  ceiling_m: number;
  cumulus: boolean;
  overdevelopment_risk: "low" | "moderate" | "high";
  comment: string;
}

export interface Risk {
  code: string;
  level: RiskLevel;
  title: string;
  detail: string;
}

export type WaypointType = "takeoff" | "turnpoint" | "thermal_trigger" | "landing" | "alternate_landing";

export interface Waypoint {
  name: string;
  lat: number;
  lon: number;
  altitude_m: number;
  type: WaypointType;
  radius_m: number | null; // rayon de validation (balise XCTrack)
  eta_min: number | null; // minutes depuis le décollage
  note: string | null;
}

export interface AirspaceWarning {
  name: string;
  airspace_class: string;
  type: string;
  floor_m: number;
  ceiling_m: number;
  min_distance_km: number; // distance mini entre la route et l'espace
  intersects_route: boolean;
}

export interface LandingCandidate {
  site: Site; // site.landing_kind renseigné ; source "osm" pour un champ détecté
  kind: LandingKind;
  use: LandingUse; // usage permis au niveau du pilote : principal possible / secours seulement (CDC §12.7)
  score: number; // 0..100
  required_glide_ratio: number; // finesse sol nécessaire depuis le déco (vent compris), hauteur d'arrivée mini
  // du kind déduite (officiel : marge §2.3 ; communautaire / champ : 100-200 m)
  available_glide_ratio: number; // finesse de calcul retenue (prudente), × 0,90 communautaire / × 0,80 champ
  arrival_height_m: number; // hauteur estimée à l'arrivée au-dessus de l'atterro
  size_m: { length: number; width: number } | null;
  slope_pct: number | null;
  surface: string | null; // "prairie", "pré fauché", "plage"…
  obstacles: string[]; // "ligne électrique à 80 m", "forêt en bout de champ"…
  wind_at_arrival: { speed_kmh: number; direction_deg: number; gust_kmh: number } | null;
  community_usage: "frequent" | "occasional" | "unknown";
  access: string | null; // route / parking / navette
  warnings: string[]; // ex. "Non officiel : autorisation du propriétaire à vérifier" (toujours pour community / field)
  reasons: string[]; // pourquoi ce classement (2-3 sous-scores décisifs ; « Écarté : … » le cas échéant)
}

/** LandingCandidate.use (le contrat le décrit en ligne). */
export type LandingUse = "main" | "alternate";

export interface ScoreItem {
  criterion: string;
  score: number; // 0..100
  weight: number;
  comment: string;
}

export interface PlanSource {
  name: string;
  url: string | null;
  fetched_at: string;
  mode: "live" | "mock";
}

export interface FlightPlan {
  id: string;
  rank: number;
  score: number; // 0..100
  flyability: Flyability;
  difficulty: Difficulty; // difficulté estimée de CE vol dans CES conditions
  flight_type: FlightType;
  thermal_usage: "none" | "optional" | "essential";
  title: string; // "Col de la Forclaz → Doussard · local thermique 1h30"
  summary: string; // 1-2 phrases
  target_time: string;
  window: { start: string; end: string; latest_landing?: string }; // créneau de décollage recommandé ;
  // latest_landing (optionnel) = min(window.end + est_duration_min, plafond horaire
  // du verdict : fin des thermiques / surdév − 1 h…, coucher du soleil)
  sun?: { sunrise: string | null; sunset: string | null }; // (optionnel) lever/coucher au déco, ISO UTC
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
  briefing: string[]; // puces ordonnées, en français
  checklist: string[];
  score_breakdown: ScoreItem[];
  confidence: number; // 0..1 (dispersion inter-modèles, horizon, fraîcheur balises)
  sources: PlanSource[];
  links: { gpx: string; xctsk: string }; // "/api/plans/{id}/gpx", "/api/plans/{id}/xctsk"
}

// ───────────────────────────── Endpoints ─────────────────────────────

/** GET /api/health */
export interface HealthResponse {
  status: "ok";
  data_mode: DataMode;
  version: string;
}

export type SourceKind = "forecast" | "sites" | "beacons" | "airspaces" | "elevation" | "sensitive_areas";

export interface SourceStatus {
  name: string;
  kind: SourceKind;
  mode: "live" | "mock" | "disabled";
  healthy: boolean;
  requires_api_key: boolean;
  api_key_configured: boolean;
  message: string | null;
  url: string | null;
}

/** GET /api/sources */
export interface SourcesResponse {
  sources: SourceStatus[];
}

/** GET /api/sites?bbox=min_lon,min_lat,max_lon,max_lat */
export interface SitesResponse {
  sites: Site[];
}

/** GET /api/beacons?bbox=min_lon,min_lat,max_lon,max_lat */
export interface BeaconsResponse {
  beacons: Beacon[];
}

/** GET /api/airspaces?bbox=… → GeoJSON FeatureCollection */
export interface AirspaceProperties {
  name: string;
  airspace_class: string; // A…G, R, Q (dangereuse), P, SIV, UNCLASSIFIED
  type: string;
  floor_m: number; // m AMSL (FL convertis en atmosphère standard ; limite sol convertie au centre de la zone)
  ceiling_m: number; // m AMSL (idem)
  floor_reference: "AMSL" | "GND"; // plancher publié par rapport au sol
  ceiling_reference: "AMSL" | "GND"; // plafond publié par rapport au sol (ex. « 1000 ft ASFC », R30C, parcs)
  floor_height_m: number | null; // hauteur publiée au-dessus du sol (référence GND), sinon null
  ceiling_height_m: number | null; // idem pour le plafond
}

export type GeoJsonPosition = [number, number] | [number, number, number];

export type AirspaceGeometry =
  | { type: "Polygon"; coordinates: GeoJsonPosition[][] }
  | { type: "MultiPolygon"; coordinates: GeoJsonPosition[][][] };

export interface AirspaceFeature {
  type: "Feature";
  id?: string | number;
  geometry: AirspaceGeometry;
  properties: AirspaceProperties;
}

export interface AirspaceFeatureCollection {
  type: "FeatureCollection";
  features: AirspaceFeature[];
  /** OpenAIP indisponible (hors démo, jamais d'espaces fictifs) : liste vide ou partielle, à vérifier */
  unverified?: boolean;
  warning?: string | null;
}

/** GET /api/sensitive-areas?bbox=… → GeoJSON FeatureCollection (Biodiv'Sports + cœurs de parcs nationaux) */
export interface SensitiveAreaProperties {
  id: string;
  name: string;
  species: string | null;
  kind: "species" | "regulatory" | "national_park_core";
  period_months: number[]; // 1..12, mois de sensibilité
  active_now: boolean;
  recommendation: string; // consigne en français
  min_height_agl_m: number | null; // hauteur de survol recommandée
  source: "biodivsports" | "fixture";
  url: string | null;
  /** parapente / sports aériens interdits dans la zone, à toute hauteur (no-go, la route la contourne) */
  flight_prohibited?: boolean;
}

export interface SensitiveAreaFeature {
  type: "Feature";
  id?: string | number;
  geometry: AirspaceGeometry;
  properties: SensitiveAreaProperties;
}

export interface SensitiveAreaFeatureCollection {
  type: "FeatureCollection";
  features: SensitiveAreaFeature[];
}

/** GET /api/forecast/point?lat=..&lon=..&time=ISO */
export interface ForecastPointResponse {
  snapshot: WeatherSnapshot;
  sounding: SoundingLevel[];
  timeline: WeatherSnapshot[]; // timeline horaire sur la journée
}

export type GridLayer = "wind" | "thermal" | "cloudbase" | "ceiling" | "cape" | "precipitation" | "useful_height";
export const WIND_GRID_ALTITUDES = [10, 1000, 1500, 2000, 2500, 3000, 4000] as const;
export type WindGridAltitude = (typeof WIND_GRID_ALTITUDES)[number];

export interface GridPoint {
  lat: number;
  lon: number;
  value: number;
  direction_deg: number | null;
}

/**
 * GET /api/forecast/grid?bbox=…&time=ISO&layer=..&altitude_m=..
 * useful_height = plafond utile − terrain (m/sol) ; cloudbase : points sans cumulus omis ;
 * legend = min/max des valeurs présentes ; grille ≤ 20×20 (mock), ≤ 10×10 (live).
 */
export interface ForecastGridResponse {
  time: string;
  layer: string;
  altitude_m: number | null;
  unit: string;
  resolution_deg: number;
  points: GridPoint[];
  legend: { min: number; max: number };
}

/** POST /api/plans */
export interface PlanFilters {
  duration_min_minutes: number; // ex. 15
  duration_max_minutes: number; // ex. 120
  difficulty: Difficulty; // niveau du pilote = difficulté max acceptée
  thermals: ThermalPreference;
  flight_types?: FlightType[]; // défaut : tous
  max_results?: number; // défaut 5, max 20
  wing_glide_ratio?: number; // finesse de l'aile, défaut 8.5
  landing_policy?: LandingPolicy; // défaut "official_only"
}

export type LandingPolicy = "official_only" | "include_community" | "include_fields";
export type PlanMode = "classic" | "custom_takeoff";

export interface CustomTakeoff {
  // requis si mode = "custom_takeoff" (ex. vol rando)
  lat: number;
  lon: number;
  elevation_m?: number; // sinon altitude terrain (MNT)
  orientations?: string[]; // sinon déduites de la pente (exposition MNT)
  name?: string;
}

export interface PlanRequest {
  zone: Zone;
  horizon: Horizon;
  reference_time?: string; // défaut : maintenant
  filters: PlanFilters;
  mode?: PlanMode; // défaut "classic" = déco ET atterro officiels
  custom_takeoff?: CustomTakeoff;
}

export interface RejectedSite {
  site: Site;
  reasons: string[];
}

export interface PlanResponse {
  request_id: string;
  generated_at: string;
  target_time: string; // reference_time + horizon, arrondi au pas de prévision
  horizon: Horizon;
  zone: Zone;
  data_mode: DataMode;
  plans: FlightPlan[]; // ordre de `rank` : verdict, durée dans la plage, score (lot 6.2) ; diversité CDC §9.4
  rejected: RejectedSite[];
  warnings: string[];
}

/** GeoJSON Polygon (cône de finesse). Positions [lon, lat] (ou [lon, lat, alt]). */
export interface GeoJsonPolygon {
  type: "Polygon";
  coordinates: GeoJsonPosition[][];
}

/** POST /api/landings/analyze — analyse des atterrissages depuis un décollage libre (clic sur la carte). */
export interface LandingAnalyzeRequest {
  takeoff: { lat: number; lon: number; elevation_m?: number; orientations?: string[]; name?: string };
  horizon: Horizon;
  reference_time?: string;
  wing_glide_ratio?: number; // défaut 8.5
  difficulty: Difficulty;
  landing_policy?: LandingPolicy; // défaut "official_only"
}

export interface LandingAnalyzeResponse {
  takeoff: Site; // source "user"
  target_time: string;
  glide_cone: GeoJsonPolygon; // zone atteignable avec marge, vent compris
  candidates: LandingCandidate[];
  warnings: string[];
}
