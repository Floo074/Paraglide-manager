import type {
  CustomTakeoff,
  Difficulty,
  FlightType,
  Horizon,
  LandingAnalyzeRequest,
  LandingPolicy,
  PlanMode,
  PlanRequest,
  ThermalPreference,
  Zone,
} from "../../api/types";
import { DIFFICULTY_ORDER } from "../../config/labels";
import { isHorizon } from "../../utils/horizon";
import { COMPASS_16 } from "../../utils/units";

export interface Criteria {
  horizon: Horizon;
  durationMin: number;
  durationMax: number;
  difficulty: Difficulty;
  thermals: ThermalPreference;
  flightTypes: FlightType[];
  glide: number;
  /** Heure de référence (ISO) ; null = maintenant. */
  referenceTime: string | null;
  /** classic = déco ET atterro officiels ; custom_takeoff = décollage libre posé sur la carte. */
  mode: PlanMode;
  /** Atterros acceptés en décollage libre (en mode classique : toujours officiels). */
  landingPolicy: LandingPolicy;
}

/** Décollage libre posé sur la carte (altitude / orientations facultatives : sinon déduites du relief). */
export interface FreeTakeoff {
  lat: number;
  lon: number;
  elevation: number | null;
  orientations: string[];
  name: string;
}

export const DEFAULT_CRITERIA: Criteria = {
  horizon: "2h",
  durationMin: 30,
  durationMax: 120,
  difficulty: "intermediate",
  thermals: "allowed",
  flightTypes: ["local", "ridge_soaring", "cross_country"],
  glide: 8.5,
  referenceTime: null,
  mode: "classic",
  landingPolicy: "official_only",
};

export const LANDING_POLICIES: LandingPolicy[] = ["official_only", "include_community", "include_fields"];
export const PLAN_MODES: PlanMode[] = ["classic", "custom_takeoff"];

/** Rayon de la zone envoyée au serveur en décollage libre (centrée sur le point choisi). */
export const CUSTOM_ZONE_RADIUS_KM = 15;

export const DURATION_BOUNDS = { min: 10, max: 480, step: 5 };

export const DURATION_PRESETS: { id: string; label: string; min: number; max: number }[] = [
  { id: "plouf", label: "Plouf", min: 10, max: 30 },
  { id: "1h", label: "1 h", min: 45, max: 75 },
  { id: "2-3h", label: "2-3 h", min: 120, max: 180 },
  { id: "cross", label: "Cross", min: 180, max: 420 },
];

/** Critères mémorisés valides (les champs ajoutés depuis, `mode` et `landingPolicy`, sont facultatifs). */
export function isCriteria(v: unknown): v is Criteria {
  if (!v || typeof v !== "object") return false;
  const c = v as Partial<Criteria>;
  return (
    isHorizon(c.horizon) &&
    typeof c.durationMin === "number" &&
    typeof c.durationMax === "number" &&
    DIFFICULTY_ORDER.includes(c.difficulty as Difficulty) &&
    ["required", "allowed", "avoid"].includes(c.thermals as string) &&
    Array.isArray(c.flightTypes) &&
    typeof c.glide === "number" &&
    (c.mode === undefined || PLAN_MODES.includes(c.mode)) &&
    (c.landingPolicy === undefined || LANDING_POLICIES.includes(c.landingPolicy))
  );
}

/** Complète des critères mémorisés par une version antérieure. */
export function withCriteriaDefaults(c: Criteria): Criteria {
  return { ...DEFAULT_CRITERIA, ...c, mode: c.mode ?? "classic", landingPolicy: c.landingPolicy ?? "official_only" };
}

export function isFreeTakeoff(v: unknown): v is FreeTakeoff | null {
  if (v === null) return true;
  if (!v || typeof v !== "object") return false;
  const t = v as Partial<FreeTakeoff>;
  return (
    typeof t.lat === "number" &&
    typeof t.lon === "number" &&
    Number.isFinite(t.lat) &&
    Number.isFinite(t.lon) &&
    (t.elevation === null || typeof t.elevation === "number") &&
    Array.isArray(t.orientations) &&
    typeof t.name === "string"
  );
}

const round = (v: number, digits: number) => Math.round(v * 10 ** digits) / 10 ** digits;

/** Décollage libre → `custom_takeoff` du contrat (champs facultatifs omis s'ils sont vides). */
export function toCustomTakeoff(t: FreeTakeoff): CustomTakeoff {
  const orientations = COMPASS_16.filter((p) => t.orientations.includes(p));
  const name = t.name.trim();
  return {
    lat: round(t.lat, 5),
    lon: round(t.lon, 5),
    ...(t.elevation !== null && Number.isFinite(t.elevation) ? { elevation_m: Math.round(t.elevation) } : {}),
    ...(orientations.length ? { orientations: [...orientations] } : {}),
    ...(name ? { name } : {}),
  };
}

/** Zone envoyée en décollage libre : cercle centré sur le point choisi. */
export function customTakeoffZone(t: FreeTakeoff): Zone {
  return { type: "circle", center: { lat: round(t.lat, 5), lon: round(t.lon, 5) }, radius_km: CUSTOM_ZONE_RADIUS_KM };
}

/** Pourquoi la recherche est impossible (null si elle peut partir). */
export function planRequestError(c: Criteria, takeoff: FreeTakeoff | null): string | null {
  if (c.mode === "custom_takeoff" && !takeoff) return "Pose d'abord le point de décollage sur la carte.";
  return null;
}

/**
 * Requête POST /api/plans. En mode classique : `mode: "classic"`, atterros officiels uniquement.
 * En décollage libre : `mode: "custom_takeoff"`, `custom_takeoff`, `filters.landing_policy`, et une
 * zone centrée sur le point (la zone dessinée ne sert pas). Sans point posé, repli sur le mode classique.
 */
export function buildPlanRequest(zone: Zone, c: Criteria, takeoff: FreeTakeoff | null = null): PlanRequest {
  const free = c.mode === "custom_takeoff" && takeoff !== null;
  return {
    zone: free ? customTakeoffZone(takeoff) : zone,
    horizon: c.horizon,
    ...(c.referenceTime ? { reference_time: new Date(c.referenceTime).toISOString() } : {}),
    filters: {
      duration_min_minutes: Math.min(c.durationMin, c.durationMax),
      duration_max_minutes: Math.max(c.durationMin, c.durationMax),
      difficulty: c.difficulty,
      thermals: c.thermals,
      flight_types: c.flightTypes.length ? c.flightTypes : undefined,
      max_results: 5,
      wing_glide_ratio: round(c.glide, 1),
      landing_policy: free ? c.landingPolicy : "official_only",
    },
    mode: free ? "custom_takeoff" : "classic",
    ...(free ? { custom_takeoff: toCustomTakeoff(takeoff) } : {}),
  };
}

/** Requête POST /api/landings/analyze depuis un décollage libre. */
export function buildLandingAnalyzeRequest(c: Criteria, t: FreeTakeoff): LandingAnalyzeRequest {
  const { lat, lon, elevation_m, orientations } = toCustomTakeoff(t);
  return {
    takeoff: { lat, lon, ...(elevation_m !== undefined ? { elevation_m } : {}), ...(orientations ? { orientations } : {}) },
    horizon: c.horizon,
    ...(c.referenceTime ? { reference_time: new Date(c.referenceTime).toISOString() } : {}),
    wing_glide_ratio: round(c.glide, 1),
    difficulty: c.difficulty,
    landing_policy: c.landingPolicy,
  };
}
