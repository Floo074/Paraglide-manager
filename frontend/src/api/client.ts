/**
 * Client de l'API Paraglide Manager (docs/API_CONTRACT.md).
 *
 * - `VITE_USE_MOCKS=true` → toutes les requêtes sont servies par le moteur de démonstration.
 * - Sinon, appels réels sur `/api` ; si le backend ne répond pas (réseau, timeout, 502/503/504,
 *   réponse non JSON), bascule automatique en démonstration avec un bandeau, et nouvelles
 *   tentatives périodiques.
 */
import { ApiError, describeErrorDetail } from "./errors";
import type {
  AirspaceFeatureCollection,
  BBoxZone,
  BeaconsResponse,
  FlightPlan,
  ForecastGridResponse,
  ForecastPointResponse,
  GridLayer,
  HealthResponse,
  PlanRequest,
  PlanResponse,
  SensitiveAreaFeatureCollection,
  SitesResponse,
  SourcesResponse,
} from "./types";
import { bboxParam } from "../utils/zone";
import { buildGpx, buildXctsk } from "../utils/exports";

export const API_BASE = "/api";
export const FORCE_MOCKS = (import.meta.env.VITE_USE_MOCKS ?? "").toLowerCase() === "true";

/** live = backend joignable ; demo-forced = VITE_USE_MOCKS ; demo-fallback = backend injoignable. */
export type ApiMode = "unknown" | "live" | "demo-forced" | "demo-fallback";

let mode: ApiMode = FORCE_MOCKS ? "demo-forced" : "unknown";
let backendDataMode: HealthResponse["data_mode"] | null = null;
const listeners = new Set<() => void>();

function setMode(next: ApiMode): void {
  if (mode === next) return;
  mode = next;
  listeners.forEach((l) => l());
}

export function getApiMode(): ApiMode {
  return mode;
}

/** Mode de données annoncé par le backend (`/api/health`), null si inconnu. */
export function getBackendDataMode(): HealthResponse["data_mode"] | null {
  return backendDataMode;
}

export function subscribeApiMode(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export const isDemoMode = (): boolean => mode === "demo-forced" || mode === "demo-fallback";
export const isDemoPlanId = (id: string): boolean => id.startsWith("demo_");

class BackendUnavailable extends Error {}

interface RequestOptions {
  query?: Record<string, string | number | undefined | null>;
  body?: unknown;
  timeoutMs?: number;
  signal?: AbortSignal;
  /** "json" (défaut) ou "text" (exports). */
  as?: "json" | "text";
  /** Ne jamais basculer sur les mocks (vérification de santé). */
  noFallback?: boolean;
}

function buildQuery(query?: RequestOptions["query"]): URLSearchParams {
  const qs = new URLSearchParams();
  if (query) for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null) qs.set(k, String(v));
  return qs;
}

async function viaMocks<T>(method: string, path: string, qs: URLSearchParams, body: unknown, as: "json" | "text"): Promise<T> {
  const { mockRequest } = await import("../mocks/api");
  const data = await mockRequest(method, path, qs, body);
  if (as === "text" && typeof data !== "string") return JSON.stringify(data, null, 2) as T;
  return data as T;
}

async function liveRequest<T>(method: string, path: string, qs: URLSearchParams, opts: RequestOptions): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new DOMException("timeout", "TimeoutError")), opts.timeoutMs ?? 10_000);
  const onAbort = () => controller.abort(opts.signal?.reason);
  opts.signal?.addEventListener("abort", onAbort);
  let res: Response;
  try {
    const q = qs.toString();
    res = await fetch(`${API_BASE}${path}${q ? `?${q}` : ""}`, {
      method,
      headers: opts.body !== undefined ? { "Content-Type": "application/json", Accept: "application/json" } : { Accept: "application/json" },
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: controller.signal,
    });
  } catch (e) {
    if (opts.signal?.aborted) throw e;
    throw new BackendUnavailable(e instanceof Error ? e.message : "réseau");
  } finally {
    clearTimeout(timer);
    opts.signal?.removeEventListener("abort", onAbort);
  }
  const type = res.headers.get("content-type") ?? "";
  const isJson = type.includes("json");
  if ([502, 503, 504].includes(res.status) || (res.status >= 500 && !isJson)) throw new BackendUnavailable(`HTTP ${res.status}`);
  if (!res.ok) {
    let detail: unknown = null;
    if (isJson) detail = (await res.json().catch(() => null))?.detail ?? null;
    else if (res.status === 404 && type.includes("html")) throw new BackendUnavailable("pas d'API derrière /api");
    throw new ApiError(res.status, describeErrorDetail(detail) ?? `Erreur ${res.status}`, detail);
  }
  if ((opts.as ?? "json") === "text") return (await res.text()) as T;
  // un hébergement statique sans proxy renvoie index.html (200, text/html) pour /api/…
  if (!isJson) throw new BackendUnavailable("réponse non JSON");
  return (await res.json()) as T;
}

async function request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
  const qs = buildQuery(opts.query);
  const as = opts.as ?? "json";
  const demoId = /^\/plans\/demo_/.test(path);
  if (!opts.noFallback && (mode === "demo-forced" || mode === "demo-fallback" || demoId)) {
    return viaMocks<T>(method, path, qs, opts.body, as);
  }
  try {
    const data = await liveRequest<T>(method, path, qs, opts);
    if (mode !== "live") setMode("live");
    return data;
  } catch (e) {
    if (e instanceof BackendUnavailable && !opts.noFallback) {
      console.warn(`[api] backend indisponible (${e.message}) : bascule en données de démonstration`);
      setMode("demo-fallback");
      return viaMocks<T>(method, path, qs, opts.body, as);
    }
    if (e instanceof BackendUnavailable) throw new ApiError(0, "Backend injoignable");
    throw e;
  }
}

/** Vérifie la disponibilité du backend (au démarrage et pour quitter le mode démo). */
export async function checkBackend(timeoutMs = 3000): Promise<boolean> {
  if (FORCE_MOCKS) return false;
  try {
    const h = await request<HealthResponse>("GET", "/health", { timeoutMs, noFallback: true });
    backendDataMode = h.data_mode;
    setMode("live");
    return true;
  } catch {
    setMode("demo-fallback");
    return false;
  }
}

// ───────────────────────────── endpoints ─────────────────────────────

export const getHealth = () => request<HealthResponse>("GET", "/health");
export const getSources = (signal?: AbortSignal) => request<SourcesResponse>("GET", "/sources", { signal });
export const getSites = (bbox: BBoxZone, signal?: AbortSignal) =>
  request<SitesResponse>("GET", "/sites", { query: { bbox: bboxParam(bbox) }, signal });
export const getBeacons = (bbox: BBoxZone, signal?: AbortSignal) =>
  request<BeaconsResponse>("GET", "/beacons", { query: { bbox: bboxParam(bbox) }, signal });
export const getAirspaces = (bbox: BBoxZone, signal?: AbortSignal) =>
  request<AirspaceFeatureCollection>("GET", "/airspaces", { query: { bbox: bboxParam(bbox) }, signal });
/** `time` : paramètre optionnel accepté par le backend pour évaluer `active_now` (défaut : maintenant). */
export const getSensitiveAreas = (bbox: BBoxZone, time?: string, signal?: AbortSignal) =>
  request<SensitiveAreaFeatureCollection>("GET", "/sensitive-areas", { query: { bbox: bboxParam(bbox), time }, signal });
export const getForecastPoint = (lat: number, lon: number, time: string, signal?: AbortSignal) =>
  request<ForecastPointResponse>("GET", "/forecast/point", { query: { lat, lon, time }, signal, timeoutMs: 20_000 });
export const getForecastGrid = (
  bbox: BBoxZone,
  time: string,
  layer: GridLayer,
  altitude_m?: number,
  signal?: AbortSignal,
) =>
  request<ForecastGridResponse>("GET", "/forecast/grid", {
    query: { bbox: bboxParam(bbox), time, layer, altitude_m: layer === "wind" ? (altitude_m ?? 10) : undefined },
    signal,
    timeoutMs: 25_000,
  });
export const createPlans = (req: PlanRequest, signal?: AbortSignal) =>
  request<PlanResponse>("POST", "/plans", { body: req, signal, timeoutMs: 60_000 });
export const getPlan = (id: string, signal?: AbortSignal) =>
  request<FlightPlan>("GET", `/plans/${encodeURIComponent(id)}`, { signal, timeoutMs: 20_000 });

/** Contenu d'un export (GPX ou XCTrack) en texte, depuis le backend ou généré localement en démo. */
export async function getPlanExport(plan: FlightPlan, kind: "gpx" | "xctsk"): Promise<string> {
  if (isDemoMode() || isDemoPlanId(plan.id)) {
    return kind === "gpx" ? buildGpx(plan) : JSON.stringify(buildXctsk(plan), null, 2);
  }
  const path = (kind === "gpx" ? plan.links.gpx : plan.links.xctsk).replace(/^\/api/, "");
  return request<string>("GET", path, { as: "text", timeoutMs: 20_000 });
}
