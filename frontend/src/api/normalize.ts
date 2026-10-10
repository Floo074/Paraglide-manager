/**
 * Normalisation défensive des réponses : un backend encore en retard sur le contrat peut omettre
 * les champs récents (station_readings, landing_analysis, Beacon.trend, Site.official, glide.wind_*…). On les
 * complète avec des valeurs neutres pour que l'interface ne casse pas ; aucune valeur inventée
 * (nombre absent du plané → NaN, que l'affichage traite comme « non communiqué », cf. utils/glide.known).
 */
import type { Beacon, FlightPlan, FlightPlanGlide, LandingAnalyzeResponse, LandingCandidate, PlanResponse, Site, StationReading } from "./types";

type Loose<T> = Partial<T> & Record<string, unknown>;

export function normalizeSite(s: Site): Site {
  const raw = s as Loose<Site>;
  const official = typeof raw.official === "boolean" ? raw.official : raw.source !== "user" && raw.source !== "osm";
  const landing_kind =
    raw.landing_kind !== undefined ? (raw.landing_kind ?? null) : s.kind === "takeoff" ? null : official ? "official" : raw.source === "osm" ? "field" : "community";
  return { ...s, official, landing_kind };
}

export function normalizeBeacon(b: Beacon): Beacon {
  return (b as Loose<Beacon>).trend === undefined ? { ...b, trend: null } : b;
}

function normalizeReading(r: StationReading): StationReading {
  return { ...r, beacon: normalizeBeacon(r.beacon) };
}

function normalizeCandidate(c: LandingCandidate): LandingCandidate {
  // `use` absent (cache d'une version antérieure) : choix prudent, un non officiel n'est retenu qu'en secours.
  const use = (c as Loose<LandingCandidate>).use ?? (c.kind === "official" ? "main" : "alternate");
  const wind = (c as Loose<LandingCandidate>).wind_along_track_kmh;
  return {
    ...c,
    use,
    wind_along_track_kmh: typeof wind === "number" && Number.isFinite(wind) ? wind : null,
    site: normalizeSite(c.site),
    obstacles: c.obstacles ?? [],
    warnings: c.warnings ?? [],
    reasons: c.reasons ?? [],
  };
}

const num = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) ? v : Number.NaN);

/** FlightPlan.glide : champs du §14 absents (backend antérieur, cache) → NaN / null / "" (rien d'inventé). */
export function normalizeGlide(g: FlightPlanGlide): FlightPlanGlide {
  const raw = (g ?? {}) as Loose<FlightPlanGlide>;
  const expected = raw.expected_arrival_height_m;
  return {
    required_ratio: num(raw.required_ratio),
    available_ratio: num(raw.available_ratio),
    margin_ok: raw.margin_ok === true,
    calm_available_ratio: num(raw.calm_available_ratio),
    wind_along_track_kmh: num(raw.wind_along_track_kmh),
    wind_credit_kmh: num(raw.wind_credit_kmh),
    expected_arrival_height_m: typeof expected === "number" && Number.isFinite(expected) ? expected : null,
    comment: typeof raw.comment === "string" ? raw.comment : "",
  };
}

export function normalizePlan(p: FlightPlan): FlightPlan {
  const raw = p as Loose<FlightPlan>;
  return {
    ...p,
    takeoff: normalizeSite(p.takeoff),
    landing: normalizeSite(p.landing),
    alternate_landings: (p.alternate_landings ?? []).map(normalizeSite),
    landing_analysis: Array.isArray(raw.landing_analysis) ? p.landing_analysis.map(normalizeCandidate) : [],
    glide: normalizeGlide(p.glide),
    beacons_nearby: (p.beacons_nearby ?? []).map(normalizeBeacon),
    station_readings: Array.isArray(raw.station_readings) ? p.station_readings.map(normalizeReading) : [],
  };
}

export function normalizePlanResponse(r: PlanResponse): PlanResponse {
  return { ...r, plans: r.plans.map(normalizePlan), rejected: r.rejected.map((x) => ({ ...x, site: normalizeSite(x.site) })) };
}

export function normalizeLandingAnalysis(r: LandingAnalyzeResponse): LandingAnalyzeResponse {
  return { ...r, takeoff: normalizeSite(r.takeoff), candidates: (r.candidates ?? []).map(normalizeCandidate), warnings: r.warnings ?? [] };
}
