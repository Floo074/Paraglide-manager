/**
 * Heures clés d'un plan en heure légale : créneau, "posé avant", coucher du soleil.
 * Règle (expert) : posé avant = min(window.end + durée, coucher) ; orange si > coucher − 30 min.
 * Les champs optionnels du contrat `window.latest_landing` et `sun.sunset` priment ;
 * à défaut, calcul local (coucher NOAA au point du déco).
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

export function planTimes(plan: FlightPlan): PlanTimes {
  const start = new Date(plan.window.start);
  const end = new Date(plan.window.end);
  const sunsetIso = plan.sun?.sunset ?? null;
  const sunset = sunsetIso ? new Date(sunsetIso) : (sunTimes(plan.takeoff.lat, plan.takeoff.lon, start)?.sunset ?? null);
  let latest: Date;
  if (plan.window.latest_landing) latest = new Date(plan.window.latest_landing);
  else {
    latest = new Date(end.getTime() + plan.est_duration_min * 60_000);
    if (sunset && latest > sunset) latest = sunset;
  }
  const lateLanding = sunset !== null && latest.getTime() > sunset.getTime() - 30 * 60_000;
  return { start, end, latestLanding: latest, sunset, lateLanding };
}
