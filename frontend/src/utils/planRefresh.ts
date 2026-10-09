/**
 * « Actualiser les balises » : relance POST /api/plans avec la même requête et retrouve,
 * dans la nouvelle réponse, le plan équivalent (même déco, même atterro, même type de vol).
 */
import type { Difficulty, FlightPlan, PlanRequest } from "../api/types";
import { isOnSiteHorizon, nearestHorizon } from "./horizon";

/**
 * Requête à relancer : celle d'origine si elle est connue, sinon une requête reconstituée depuis
 * le plan (lien partagé) : petite zone autour du déco, horizon le plus proche de l'heure cible.
 */
export function refreshRequestFor(plan: FlightPlan, original: PlanRequest | null, level: Difficulty, now: Date): { request: PlanRequest; rebuilt: boolean } {
  if (original) return { request: original, rebuilt: false };
  const minutes = (new Date(plan.target_time).getTime() - now.getTime()) / 60_000;
  const t = plan.takeoff;
  const free = t.source === "user";
  const request: PlanRequest = {
    zone: { type: "circle", center: { lat: t.lat, lon: t.lon }, radius_km: free ? 15 : 3 },
    horizon: nearestHorizon(minutes),
    filters: {
      duration_min_minutes: Math.max(10, Math.round(plan.est_duration_min * 0.6)),
      duration_max_minutes: Math.max(20, Math.round(plan.est_duration_min * 1.5)),
      difficulty: level,
      thermals: "allowed",
      flight_types: [plan.flight_type],
      max_results: 5,
      landing_policy: free ? "include_community" : "official_only",
    },
    mode: free ? "custom_takeoff" : "classic",
    ...(free ? { custom_takeoff: { lat: t.lat, lon: t.lon, elevation_m: t.elevation_m, orientations: t.orientations, name: t.name } } : {}),
  };
  return { request, rebuilt: true };
}

/** Plan équivalent dans une nouvelle liste (null si ce vol n'est plus proposé). */
export function findEquivalentPlan(old: FlightPlan, plans: FlightPlan[]): FlightPlan | null {
  const same = (p: FlightPlan) => p.takeoff.id === old.takeoff.id;
  return (
    plans.find((p) => same(p) && p.landing.id === old.landing.id && p.flight_type === old.flight_type && p.thermal_usage === old.thermal_usage) ??
    plans.find((p) => same(p) && p.landing.id === old.landing.id && p.flight_type === old.flight_type) ??
    plans.find((p) => same(p) && p.flight_type === old.flight_type) ??
    plans.find(same) ??
    null
  );
}

/**
 * Le bloc « Balises en direct » passe en tête si l'horizon est ≤ 1 h. Horizon de la requête
 * d'origine si connu, sinon délai entre le calcul et l'heure cible (≤ 75 min, arrondi compris).
 */
export function beaconsFirst(plan: FlightPlan, request: PlanRequest | null, generatedAt: string | null, now: Date): boolean {
  if (request) return isOnSiteHorizon(request.horizon);
  const from = generatedAt ? new Date(generatedAt) : now;
  return (new Date(plan.target_time).getTime() - from.getTime()) / 60_000 <= 75;
}

/** Heure de dernière mise à jour du plan : heure du calcul, sinon la plus récente des sources. */
export function planUpdatedAt(plan: FlightPlan, generatedAt: string | null): string | null {
  if (generatedAt) return generatedAt;
  const times = plan.sources.map((s) => s.fetched_at).filter(Boolean).sort();
  return times.length ? times[times.length - 1]! : null;
}

