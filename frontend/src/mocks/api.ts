/**
 * Routeur de l'API simulée : mêmes chemins et mêmes formes de réponse que le backend
 * (docs/API_CONTRACT.md), calculés dans le navigateur.
 */
import { ApiError } from "../api/errors";
import type {
  AirspaceFeature,
  BBoxZone,
  ForecastPointResponse,
  GridLayer,
  HealthResponse,
  PlanRequest,
  SensitiveAreaFeature,
} from "../api/types";
import { buildGpx, buildXctsk } from "../utils/exports";
import { mockAirspaceCollection } from "./airspaces";
import { mockBeacons } from "./beacons";
import { mockPlanById, mockPlans } from "./planner";
import { mockSensitiveAreaCollection } from "./sensitiveAreas";
import { MOCK_SITES } from "./sites";
import { mockSources } from "./sources";
import { facingOf, gridAt, soundingAt, terrainAt, weatherAt } from "./weather";

const GRID_LAYERS: GridLayer[] = ["wind", "thermal", "cloudbase", "ceiling", "cape", "precipitation"];

function parseBbox(raw: string | null): BBoxZone {
  const parts = (raw ?? "").split(",").map(Number);
  if (parts.length !== 4 || parts.some((n) => !Number.isFinite(n))) {
    throw new ApiError(422, "Paramètre bbox invalide (attendu : min_lon,min_lat,max_lon,max_lat).", "Paramètre bbox invalide");
  }
  const [min_lon, min_lat, max_lon, max_lat] = parts as [number, number, number, number];
  return { type: "bbox", min_lat, min_lon, max_lat, max_lon };
}

function parseTime(raw: string | null): Date {
  if (!raw) return new Date();
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) throw new ApiError(422, "Paramètre time invalide (ISO 8601 attendu).", "Paramètre time invalide");
  return d;
}

const inBox = (b: BBoxZone, p: { lat: number; lon: number }) =>
  p.lat >= b.min_lat && p.lat <= b.max_lat && p.lon >= b.min_lon && p.lon <= b.max_lon;

function featureTouches(b: BBoxZone, f: AirspaceFeature | SensitiveAreaFeature): boolean {
  const rings = f.geometry.type === "Polygon" ? [f.geometry.coordinates[0]!] : f.geometry.coordinates.map((p) => p[0]!);
  let minLon = Infinity, minLat = Infinity, maxLon = -Infinity, maxLat = -Infinity;
  for (const r of rings)
    for (const c of r) {
      minLon = Math.min(minLon, c[0]!);
      maxLon = Math.max(maxLon, c[0]!);
      minLat = Math.min(minLat, c[1]!);
      maxLat = Math.max(maxLat, c[1]!);
    }
  return !(maxLon < b.min_lon || minLon > b.max_lon || maxLat < b.min_lat || minLat > b.max_lat);
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Réponse simulée pour `METHOD /api{path}`. Les exports renvoient du texte. */
export async function mockRequest(method: string, path: string, query: URLSearchParams, body?: unknown): Promise<unknown> {
  const route = path.replace(/\/+$/, "");
  await sleep(route === "/plans" ? 650 : 120 + Math.random() * 180);

  if (method === "GET" && route === "/health") {
    return { status: "ok", data_mode: "mock", version: "démo-frontend" } satisfies HealthResponse;
  }
  if (method === "GET" && route === "/sources") return mockSources();
  if (method === "GET" && route === "/sites") {
    const b = parseBbox(query.get("bbox"));
    return { sites: MOCK_SITES.filter((s) => inBox(b, s)) };
  }
  if (method === "GET" && route === "/beacons") {
    const b = parseBbox(query.get("bbox"));
    return { beacons: mockBeacons().filter((s) => inBox(b, s)) };
  }
  if (method === "GET" && route === "/airspaces") {
    const b = parseBbox(query.get("bbox"));
    const fc = mockAirspaceCollection();
    return { ...fc, features: fc.features.filter((f) => featureTouches(b, f)) };
  }
  if (method === "GET" && route === "/sensitive-areas") {
    const b = parseBbox(query.get("bbox"));
    const fc = mockSensitiveAreaCollection(parseTime(query.get("time")));
    return { ...fc, features: fc.features.filter((f) => featureTouches(b, f)) };
  }
  if (method === "GET" && route === "/forecast/point") {
    const lat = Number(query.get("lat"));
    const lon = Number(query.get("lon"));
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) throw new ApiError(422, "Paramètres lat/lon invalides.", "lat/lon invalides");
    const time = parseTime(query.get("time"));
    const elevation = terrainAt(lat, lon);
    const nearest = MOCK_SITES.find((s) => Math.abs(s.lat - lat) < 0.002 && Math.abs(s.lon - lon) < 0.002);
    const opts = { facingDeg: nearest ? facingOf(nearest.orientations) : null, key: `${lat},${lon}` };
    const day = new Date(time);
    day.setUTCHours(4, 0, 0, 0);
    const timeline = Array.from({ length: 16 }, (_, h) => weatherAt(lat, lon, elevation, new Date(day.getTime() + h * 3_600_000), opts));
    return { snapshot: weatherAt(lat, lon, elevation, time, opts), sounding: soundingAt(lat, lon, time), timeline } satisfies ForecastPointResponse;
  }
  if (method === "GET" && route === "/forecast/grid") {
    const b = parseBbox(query.get("bbox"));
    const layer = (query.get("layer") ?? "wind") as GridLayer;
    if (!GRID_LAYERS.includes(layer)) throw new ApiError(422, `Couche inconnue : ${layer}`, `Couche inconnue : ${layer}`);
    const alt = query.get("altitude_m");
    return gridAt(b, parseTime(query.get("time")), layer, layer === "wind" ? Number(alt ?? 10) : null);
  }
  if (method === "POST" && route === "/plans") return mockPlans(body as PlanRequest);

  const planMatch = /^\/plans\/([^/]+)(\/(gpx|xctsk))?$/.exec(route);
  if (method === "GET" && planMatch) {
    const plan = mockPlanById(decodeURIComponent(planMatch[1]!));
    if (planMatch[3] === "gpx") return buildGpx(plan);
    if (planMatch[3] === "xctsk") return buildXctsk(plan);
    return plan;
  }
  throw new ApiError(404, `Endpoint de démonstration inconnu : ${method} ${route}`);
}
