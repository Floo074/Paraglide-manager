/**
 * Cache des derniers résultats : évite de recalculer en revenant de la fiche d'un plan,
 * et permet d'ouvrir un plan sans requête supplémentaire.
 */
import type { FlightPlan, PlanRequest, PlanResponse } from "./types";

const KEY = "pm.lastResults.v1";
const plans = new Map<string, FlightPlan>();

export interface CachedResults {
  request: PlanRequest;
  response: PlanResponse;
}

export function rememberResults(request: PlanRequest, response: PlanResponse): void {
  response.plans.forEach((p) => plans.set(p.id, p));
  try {
    sessionStorage.setItem(KEY, JSON.stringify({ request, response } satisfies CachedResults));
  } catch {
    /* quota : ignoré */
  }
}

export function lastResults(): CachedResults | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CachedResults;
    parsed.response.plans.forEach((p) => plans.set(p.id, p));
    return parsed;
  } catch {
    return null;
  }
}

export function cachedPlan(id: string): FlightPlan | null {
  if (!plans.has(id)) lastResults();
  return plans.get(id) ?? null;
}

export function rememberPlan(plan: FlightPlan): void {
  plans.set(plan.id, plan);
}
