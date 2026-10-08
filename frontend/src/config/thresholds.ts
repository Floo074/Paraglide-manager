/**
 * Seuils de vent par niveau (cahier des charges pilote §2.1 / §2.2), utilisés pour colorer
 * balises et vents : vert < 80 % du seuil, orange 80-100 %, rouge au-delà.
 */
import type { Difficulty, FlightType } from "../api/types";
import { windColor } from "../utils/colors";

type PerLevel = Record<Difficulty, number>;

export const TAKEOFF_WIND_MAX: PerLevel = { beginner: 15, intermediate: 20, advanced: 25, expert: 30 };
export const TAKEOFF_GUST_MAX: PerLevel = { beginner: 20, intermediate: 25, advanced: 30, expert: 35 };
export const LANDING_WIND_MAX: PerLevel = { beginner: 15, intermediate: 20, advanced: 25, expert: 28 };
export const LANDING_GUST_MAX: PerLevel = { beginner: 20, intermediate: 25, advanced: 30, expert: 35 };
/** Soaring dynamique (§2.2) : s'applique au déco ET à l'atterro d'un plan ridge_soaring. */
export const RIDGE_WIND_MAX: PerLevel = { beginner: 20, intermediate: 22, advanced: 27, expert: 30 };
export const RIDGE_GUST_MAX: PerLevel = { beginner: 22, intermediate: 26, advanced: 32, expert: 35 };
export const WIND_ALOFT_MAX: Record<1500 | 2000 | 3000, PerLevel> = {
  1500: { beginner: 15, intermediate: 20, advanced: 25, expert: 30 },
  2000: { beginner: 20, intermediate: 25, advanced: 30, expert: 35 },
  3000: { beginner: 25, intermediate: 30, advanced: 35, expert: 40 },
};

export interface WindLimits {
  wind: number;
  gust: number | null;
}

export function takeoffLimits(level: Difficulty, flightType?: FlightType): WindLimits {
  if (flightType === "ridge_soaring") return { wind: RIDGE_WIND_MAX[level], gust: RIDGE_GUST_MAX[level] };
  return { wind: TAKEOFF_WIND_MAX[level], gust: TAKEOFF_GUST_MAX[level] };
}

export function landingLimits(level: Difficulty, flightType?: FlightType): WindLimits {
  if (flightType === "ridge_soaring") return { wind: RIDGE_WIND_MAX[level], gust: RIDGE_GUST_MAX[level] };
  return { wind: LANDING_WIND_MAX[level], gust: LANDING_GUST_MAX[level] };
}

/** Seuil de vent en altitude (niveau de pression le plus proche parmi 1500/2000/3000), null en dessous de 1250 m. */
export function aloftLimit(level: Difficulty, altitudeM: number): number | null {
  if (altitudeM < 1250) return null;
  const key = altitudeM < 1750 ? 1500 : altitudeM < 2500 ? 2000 : 3000;
  return WIND_ALOFT_MAX[key][level];
}

export type WindVerdict = "ok" | "near" | "over";

export function ratioVerdict(value: number | null, max: number | null): WindVerdict | null {
  if (value === null || max === null || !(max > 0)) return null;
  const r = value / max;
  return r > 1 ? "over" : r > 0.8 ? "near" : "ok";
}

export function windVerdict(speed: number | null, gust: number | null, limits: WindLimits): WindVerdict | null {
  const a = ratioVerdict(speed, limits.wind);
  const b = ratioVerdict(gust, limits.gust);
  const order: (WindVerdict | null)[] = ["over", "near", "ok"];
  for (const v of order) if (a === v || b === v) return v;
  return null;
}

export const VERDICT_COLOR: Record<WindVerdict, string> = { ok: "#22c55e", near: "#f59e0b", over: "#ef4444" };
export const VERDICT_CLASS: Record<WindVerdict, string> = { ok: "wv--ok", near: "wv--near", over: "wv--over" };

/** Couleur d'une balise : relative au niveau du pilote si connu (seuils déco), sinon échelle absolue. */
export function beaconColor(speed: number | null, gust: number | null, level: Difficulty | null): string {
  if (speed === null) return "#94a3b8";
  if (!level) return windColor(speed);
  return VERDICT_COLOR[windVerdict(speed, gust, takeoffLimits(level))!];
}
