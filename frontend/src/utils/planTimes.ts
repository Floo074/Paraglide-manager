/**
 * Heures clés d'un plan en heure légale : créneau, "posé avant", coucher du soleil.
 * Règle (expert) : posé avant = min(window.end + durée, coucher) ; orange si > coucher − 30 min.
 * Si le backend fournit `window.latest_landing` / `sunset` (champs optionnels prévus), ils priment.
 */
import type { FlightPlan } from "../api/types";
import { sunTimes } from "./sun";

export interface PlanTimes {
  start: Date;
  end: Date;
  latestLanding: Date;
  sunset: Date | null;
  /** Atterrissage dans les 30 dernières minutes avant le coucher. */
  lateLanding: boolean;
}

/** Champs optionnels annoncés par le backend (window.latest_landing, sun.sunset ; repli : sunset à la racine). */
type Extended = FlightPlan & {
  sunset?: string | null;
  sun?: { sunrise?: string | null; sunset?: string | null } | null;
  window: FlightPlan["window"] & { latest_landing?: string | null };
};

export function planTimes(plan: FlightPlan): PlanTimes {
  const ext = plan as Extended;
  const start = new Date(plan.window.start);
  const end = new Date(plan.window.end);
  const sunsetIso = ext.sun?.sunset ?? ext.sunset ?? null;
  const sunset = sunsetIso ? new Date(sunsetIso) : (sunTimes(plan.takeoff.lat, plan.takeoff.lon, start)?.sunset ?? null);
  let latest = ext.window.latest_landing ? new Date(ext.window.latest_landing) : new Date(end.getTime() + plan.est_duration_min * 60_000);
  if (!ext.window.latest_landing && sunset && latest > sunset) latest = sunset;
  const lateLanding = sunset !== null && latest.getTime() > sunset.getTime() - 30 * 60_000;
  return { start, end, latestLanding: latest, sunset, lateLanding };
}
