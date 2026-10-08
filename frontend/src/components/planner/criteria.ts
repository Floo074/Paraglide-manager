import type { Difficulty, FlightType, Horizon, PlanRequest, ThermalPreference, Zone } from "../../api/types";
import { DIFFICULTY_ORDER } from "../../config/labels";
import { isHorizon } from "../../utils/horizon";

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
};

export const DURATION_BOUNDS = { min: 10, max: 480, step: 5 };

export const DURATION_PRESETS: { id: string; label: string; min: number; max: number }[] = [
  { id: "plouf", label: "Plouf", min: 10, max: 30 },
  { id: "1h", label: "1 h", min: 45, max: 75 },
  { id: "2-3h", label: "2-3 h", min: 120, max: 180 },
  { id: "cross", label: "Cross", min: 180, max: 420 },
];

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
    typeof c.glide === "number"
  );
}

export function buildPlanRequest(zone: Zone, c: Criteria): PlanRequest {
  return {
    zone,
    horizon: c.horizon,
    ...(c.referenceTime ? { reference_time: new Date(c.referenceTime).toISOString() } : {}),
    filters: {
      duration_min_minutes: Math.min(c.durationMin, c.durationMax),
      duration_max_minutes: Math.max(c.durationMin, c.durationMax),
      difficulty: c.difficulty,
      thermals: c.thermals,
      flight_types: c.flightTypes.length ? c.flightTypes : undefined,
      max_results: 5,
      wing_glide_ratio: Math.round(c.glide * 10) / 10,
    },
  };
}
