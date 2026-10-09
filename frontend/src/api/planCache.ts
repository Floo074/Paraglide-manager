/**
 * Cache des derniers résultats : évite de recalculer en revenant de la fiche d'un plan,
 * permet d'ouvrir un plan sans requête supplémentaire, et retient pour chaque plan la requête
 * qui l'a produit (bouton « Actualiser les balises ») et l'heure du calcul.
 */
import { normalizePlan, normalizePlanResponse } from "./normalize";
import type { FlightPlan, PlanRequest, PlanResponse } from "./types";

const KEY = "pm.lastResults.v1";
const META_KEY = "pm.planMeta.v1";
const MAX_META = 40;
const plans = new Map<string, FlightPlan>();

export interface CachedResults {
  request: PlanRequest;
  response: PlanResponse;
}

/** Requête d'origine et heure de calcul d'un plan. */
export interface PlanMeta {
  request: PlanRequest;
  generated_at: string;
}

function loadMeta(): Record<string, PlanMeta> {
  try {
    const raw = sessionStorage.getItem(META_KEY);
    return raw ? (JSON.parse(raw) as Record<string, PlanMeta>) : {};
  } catch {
    return {};
  }
}

function saveMeta(meta: Record<string, PlanMeta>): void {
  try {
    const entries = Object.entries(meta)
      .sort((a, b) => b[1].generated_at.localeCompare(a[1].generated_at))
      .slice(0, MAX_META);
    sessionStorage.setItem(META_KEY, JSON.stringify(Object.fromEntries(entries)));
  } catch {
    /* quota ou stockage indisponible : ignoré */
  }
}

export function rememberResults(request: PlanRequest, response: PlanResponse): void {
  response.plans.forEach((p) => plans.set(p.id, p));
  const meta = loadMeta();
  response.plans.forEach((p) => (meta[p.id] = { request, generated_at: response.generated_at }));
  saveMeta(meta);
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
    const stored = JSON.parse(raw) as CachedResults;
    // résultats mémorisés par une version antérieure : champs récents complétés
    const parsed: CachedResults = { request: stored.request, response: normalizePlanResponse(stored.response) };
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
  plans.set(plan.id, normalizePlan(plan));
}

/** Requête et heure de calcul d'un plan (null pour un plan ouvert depuis un lien partagé). */
export function planMeta(id: string): PlanMeta | null {
  return loadMeta()[id] ?? null;
}
