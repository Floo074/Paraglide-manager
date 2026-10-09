/**
 * Analyse des atterrissages de DÉMONSTRATION (POST /api/landings/analyze et FlightPlan.landing_analysis).
 *
 * Reprend les règles du cahier des charges pilote §12 (catégories officiel / communautaire / champ
 * détecté, niveaux autorisés, marges renforcées, critères minimaux, pondération du classement) sur
 * des atterros FICTIFS placés autour du lac d'Annecy. Ne pas utiliser pour voler.
 */
import type {
  CustomTakeoff,
  Difficulty,
  GeoJsonPolygon,
  LandingAnalyzeRequest,
  LandingAnalyzeResponse,
  LandingCandidate,
  LandingKind,
  LandingPolicy,
  Site,
} from "../api/types";
import { ApiError } from "../api/errors";
import { DIFFICULTY_ORDER } from "../config/labels";
import { bearingDeg, destinationPoint, haversineKm, type Pt } from "../utils/geo";
import { horizonToMinutes, isHorizon, targetTimeFromHorizon } from "../utils/horizon";
import { formatNumber } from "../utils/format";
import { compassFr, degToCardinalFr, degToCompass, normalizeDeg } from "../utils/units";
import { RULES, arrivalMargin } from "./rules";
import { MOCK_SITES } from "./sites";
import { slopeAspect, terrainAt, valleyFloor, weatherAt } from "./weather";

// ───────────────────────────── données fictives ─────────────────────────────

interface LandingDetails {
  size_m: { length: number; width: number } | null;
  slope_pct: number | null;
  surface: string | null;
  obstacles: string[];
  community_usage: LandingCandidate["community_usage"];
  access: string | null;
}

const NO_DETAILS: LandingDetails = { size_m: null, slope_pct: null, surface: null, obstacles: [], community_usage: "unknown", access: null };

/** Caractéristiques des atterros officiels de démonstration (approximatives). */
const OFFICIAL_DETAILS: Record<string, Partial<LandingDetails>> = {
  "fixture:doussard": { size_m: { length: 300, width: 120 }, slope_pct: 1, surface: "prairie entretenue", obstacles: ["camping et réserve du Bout du Lac à ne pas survoler"], access: "Parking de l'atterrissage, navette en saison" },
  "fixture:talloires": { size_m: { length: 160, width: 50 }, slope_pct: 2, surface: "pelouse en bord de lac", obstacles: ["lac en bout de terrain", "arbres côté route"], access: "Parking de la plage" },
  "fixture:montmin-atterro": { size_m: { length: 150, width: 60 }, slope_pct: 6, surface: "prairie d'altitude", obstacles: ["clôtures de pâturage"], access: "Route du col de la Forclaz" },
  "fixture:st-jorioz": { size_m: { length: 200, width: 80 }, slope_pct: 1, surface: "prairie", access: "Parking de la base nautique" },
  "fixture:gruffy": { size_m: { length: 180, width: 70 }, slope_pct: 3, surface: "prairie", obstacles: ["ligne électrique balisée au sud"] },
  "fixture:bois-du-bouchet": { size_m: { length: 250, width: 100 }, slope_pct: 1, surface: "pelouse", obstacles: ["forêt en bordure"], access: "Parking du Bouchet" },
  "fixture:lumbin": { size_m: { length: 300, width: 120 }, slope_pct: 1, surface: "prairie", obstacles: ["ligne électrique balisée"], access: "Parking de l'atterrissage" },
};

type FixtureInput = Pick<Site, "id" | "name" | "lat" | "lon" | "elevation_m" | "description"> & { source: Site["source"]; kind: Exclude<LandingKind, "official">; details: LandingDetails };

function landingSite(f: FixtureInput): Site {
  return {
    id: f.id,
    name: f.name,
    kind: "landing",
    lat: f.lat,
    lon: f.lon,
    elevation_m: f.elevation_m,
    orientations: [],
    difficulty: null,
    flight_types: [],
    description: f.description,
    access: f.details.access,
    restrictions: null,
    status: "unknown",
    source: f.source,
    url: null,
    associated_landing_ids: [],
    official: false,
    landing_kind: f.kind,
  };
}

/** Atterros « communautaires » (non validés FFVL) et champs détectés : FICTIFS. */
const UNOFFICIAL: FixtureInput[] = [
  {
    id: "pge:demo-lathuile", name: "Lathuile, pré des pilotes (communautaire)", lat: 45.7905, lon: 6.2045, elevation_m: 452, source: "paraglidingearth", kind: "community",
    description: "Pré utilisé par les pilotes locaux quand Doussard est encombré (données de démonstration).",
    details: { size_m: { length: 180, width: 60 }, slope_pct: 2, surface: "prairie", obstacles: ["haie en bordure nord"], community_usage: "occasional", access: "Route du Bout du Lac, parking du stade" },
  },
  {
    id: "pge:demo-giez", name: "Giez, champ des pilotes (communautaire)", lat: 45.751, lon: 6.244, elevation_m: 470, source: "paraglidingearth", kind: "community",
    description: "Grand pré plat signalé par la communauté (données de démonstration).",
    details: { size_m: { length: 200, width: 70 }, slope_pct: 1, surface: "prairie", obstacles: [], community_usage: "frequent", access: "Chemin agricole depuis Giez" },
  },
  {
    id: "pge:demo-menthon", name: "Menthon, pré du bord du lac (communautaire)", lat: 45.861, lon: 6.198, elevation_m: 452, source: "paraglidingearth", kind: "community",
    description: "Pré en bord de lac, petit : arriver haut (données de démonstration).",
    details: { size_m: { length: 140, width: 45 }, slope_pct: 4, surface: "pré fauché", obstacles: ["ligne électrique basse à 120 m à l'est", "rangée d'arbres côté route"], community_usage: "occasional", access: "Parking de la plage de Menthon" },
  },
  {
    id: "pge:demo-forclaz-alpage", name: "Alpage sous la Forclaz (communautaire)", lat: 45.808, lon: 6.262, elevation_m: 1180, source: "paraglidingearth", kind: "community",
    description: "Alpage utilisé pour les vols rando côté Montmin (données de démonstration).",
    details: { size_m: { length: 120, width: 40 }, slope_pct: 9, surface: "alpage", obstacles: ["clôtures de pâturage", "bétail possible"], community_usage: "frequent", access: "Route du col de la Forclaz" },
  },
  {
    id: "osm:demo-verthier", name: "Champ détecté — Verthier", lat: 45.775, lon: 6.235, elevation_m: 455, source: "osm", kind: "field",
    description: "Prairie détectée automatiquement (OSM landuse=meadow + relief), jamais vérifiée.",
    details: { size_m: { length: 230, width: 90 }, slope_pct: 2, surface: "prairie", obstacles: ["ligne électrique à 90 m", "fossé de drainage probable"], community_usage: "unknown", access: "Route communale à 200 m" },
  },
  {
    id: "osm:demo-vesonne", name: "Champ détecté — Vesonne", lat: 45.763, lon: 6.27, elevation_m: 500, source: "osm", kind: "field",
    description: "Parcelle agricole détectée automatiquement, jamais vérifiée.",
    details: { size_m: { length: 260, width: 110 }, slope_pct: 3, surface: "culture (maïs possible en été)", obstacles: ["route départementale le long du champ"], community_usage: "unknown", access: "Bord de la RD 1508" },
  },
  {
    id: "osm:demo-entrevernes", name: "Champ détecté — Entrevernes", lat: 45.776, lon: 6.188, elevation_m: 760, source: "osm", kind: "field",
    description: "Pré en pente douce détecté automatiquement, jamais vérifié.",
    details: { size_m: { length: 150, width: 50 }, slope_pct: 7, surface: "pré", obstacles: ["forêt en bout de champ"], community_usage: "unknown", access: null },
  },
  {
    id: "osm:demo-angon", name: "Champ détecté — Angon", lat: 45.828, lon: 6.224, elevation_m: 520, source: "osm", kind: "field",
    description: "Pâture détectée automatiquement, jamais vérifiée.",
    details: { size_m: { length: 110, width: 40 }, slope_pct: 11, surface: "pâture", obstacles: ["bâtiments agricoles à 40 m", "ligne électrique à 60 m"], community_usage: "unknown", access: "Hameau d'Angon" },
  },
];

const UNOFFICIAL_SITES: { site: Site; details: LandingDetails }[] = UNOFFICIAL.map((f) => ({ site: landingSite(f), details: f.details }));

// ───────────────────────────── règles (CDC §12.2) ─────────────────────────────

const lvl = (d: Difficulty) => DIFFICULTY_ORDER.indexOf(d);
const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));

export const KIND_LEVELS: Record<LandingKind, Difficulty[]> = {
  official: ["beginner", "intermediate", "advanced", "expert"],
  community: ["intermediate", "advanced", "expert"],
  field: ["advanced", "expert"],
};
/** Peut servir d'atterro PRINCIPAL (sinon : secours uniquement). */
export function canBeMain(kind: LandingKind, level: Difficulty): boolean {
  if (kind === "official") return true;
  if (kind === "community") return lvl(level) >= lvl("advanced");
  return false;
}
const POLICY_KINDS: Record<LandingPolicy, LandingKind[]> = {
  official_only: ["official"],
  include_community: ["official", "community"],
  include_fields: ["official", "community", "field"],
};
const AVAILABLE_FACTOR: Record<LandingKind, number> = { official: 1, community: 0.85, field: 0.75 };
const ARRIVAL_MIN: Record<Exclude<LandingKind, "official">, Partial<Record<Difficulty, number>>> = {
  community: { intermediate: 150, advanced: 120, expert: 100 },
  field: { advanced: 150, expert: 120 },
};
const UNOFFICIAL_MIN = {
  length: { beginner: 150, intermediate: 120, advanced: 100, expert: 80 } as Record<Difficulty, number>,
  width: { beginner: 50, intermediate: 40, advanced: 30, expert: 25 } as Record<Difficulty, number>,
  slope: { beginner: 6, intermediate: 8, advanced: 10, expert: 12 } as Record<Difficulty, number>,
};
const WEIGHTS = { glide_margin: 30, obstacle_clearance: 20, size_margin: 15, source_reliability: 10, slope: 10, axis_vs_wind: 10, road_access: 5 };
const RELIABILITY: Record<LandingKind, number> = { official: 100, community: 60, field: 30 };

export const UNOFFICIAL_WARNING: Record<Exclude<LandingKind, "official">, string> = {
  community:
    "Atterrissage communautaire non validé par la FFVL : vérifie l'état du terrain (cultures, bétail, clôtures, lignes) et l'accord du propriétaire ; repère-le en vol avant de t'engager.",
  field:
    "Champ détecté automatiquement par cartographie, SANS vérification humaine : à utiliser uniquement en secours, après reconnaissance en vol (lignes électriques invisibles sur la carte, clôtures, cultures hautes, pente).",
};

// ───────────────────────────── calculs ─────────────────────────────

export interface LandingContext {
  takeoff: Pt & { elevation_m: number };
  level: Difficulty;
  glide: number;
  /** Heure de décollage (cible). */
  time: Date;
  /** Durée de vol supposée avant l'arrivée (min) pour le vent à l'atterro. */
  arrivalAfterMin?: number;
}

/** Vent de transition (niveau d'altitude le plus proche du milieu du plané). */
function glideWind(ctx: LandingContext, landingElev: number): { speed: number; dir: number } {
  const wx = weatherAt(ctx.takeoff.lat, ctx.takeoff.lon, ctx.takeoff.elevation_m, ctx.time, { key: `glide:${ctx.takeoff.lat.toFixed(3)},${ctx.takeoff.lon.toFixed(3)}` });
  const mid = (ctx.takeoff.elevation_m + landingElev) / 2;
  let best: { speed: number; dir: number } = { speed: wx.wind_10m.speed_kmh, dir: wx.wind_10m.direction_deg };
  let bestD = Infinity;
  for (const l of wx.winds_aloft) {
    const d = Math.abs(l.altitude_m - mid);
    if (d < bestD && d < 600) {
      bestD = d;
      best = { speed: l.speed_kmh, dir: l.direction_deg };
    }
  }
  return best;
}

/** Finesse sol avec le vent sur la trajectoire de cap `bearing` (vent arrière > 0). */
function groundRatio(airRatio: number, wind: { speed: number; dir: number }, bearing: number): number {
  const tail = wind.speed * Math.cos(((bearing - (wind.dir + 180)) * Math.PI) / 180);
  return Math.max(0, (airRatio * (RULES.airSpeedKmh + tail)) / RULES.airSpeedKmh);
}

function detailsFor(site: Site): LandingDetails {
  const extra = UNOFFICIAL_SITES.find((u) => u.site.id === site.id)?.details;
  if (extra) return extra;
  return { ...NO_DETAILS, community_usage: "frequent", access: site.access, ...OFFICIAL_DETAILS[site.id] };
}

export function kindOf(site: Site): LandingKind {
  return site.landing_kind ?? (site.official ? "official" : "community");
}

/** Hauteur d'arrivée minimale (m au-dessus de l'atterro) selon la catégorie et le niveau. */
function arrivalMin(kind: LandingKind, level: Difficulty, drop: number): number {
  if (kind === "official") return arrivalMargin(level, drop);
  return ARRIVAL_MIN[kind][level] ?? 150;
}

/** Évalue un atterro (toujours un résultat, même hors de portée : `reachable` l'indique). */
export function evaluateLanding(site: Site, ctx: LandingContext): { candidate: LandingCandidate; reachable: boolean } {
  const kind = kindOf(site);
  const det = detailsFor(site);
  const d = haversineKm(ctx.takeoff, site);
  const bearing = bearingDeg(ctx.takeoff, site);
  const wind = glideWind(ctx, site.elevation_m);
  const airRatio = ctx.glide * RULES.glideK[ctx.level];
  const drop = ctx.takeoff.elevation_m - site.elevation_m;
  const margin = arrivalMin(kind, ctx.level, drop);
  const available = groundRatio(airRatio, wind, bearing) * AVAILABLE_FACTOR[kind];
  const usable = drop - margin;
  const required = usable > 0 ? (d * 1000) / usable : 99;
  const arrival = available > 0 ? drop - (d * 1000) / available : -drop;
  const reachable = required <= available && arrival >= margin - 1;
  const arrivalTime = new Date(ctx.time.getTime() + (ctx.arrivalAfterMin ?? Math.max(5, Math.round((d / 30) * 60))) * 60_000);
  const w = weatherAt(site.lat, site.lon, site.elevation_m, arrivalTime, { isLanding: true, key: site.id }).wind_10m;

  // score (CDC §12.2 landing_candidate_weights, somme 100)
  const marginRatio = available > 0 ? 1 - required / available : -1;
  const sGlide = clamp(marginRatio / 0.4, 0, 1) * WEIGHTS.glide_margin;
  const sObst = Math.max(0, WEIGHTS.obstacle_clearance - 6 * det.obstacles.length);
  const minLen = UNOFFICIAL_MIN.length[ctx.level];
  const minWid = UNOFFICIAL_MIN.width[ctx.level];
  const sSize = det.size_m
    ? clamp(Math.min(det.size_m.length / (minLen * 1.8), det.size_m.width / (minWid * 1.8)), 0, 1) * WEIGHTS.size_margin
    : kind === "official" ? 11 : 5;
  const sRel = (RELIABILITY[kind] / 100) * WEIGHTS.source_reliability;
  const sSlope = det.slope_pct === null ? 6 : clamp(1 - det.slope_pct / (UNOFFICIAL_MIN.slope[ctx.level] * 1.5), 0, 1) * WEIGHTS.slope;
  const sWind = clamp(1 - Math.max(0, w.speed_kmh - 8) / 20, 0, 1) * WEIGHTS.axis_vs_wind;
  const sAccess = det.access ? WEIGHTS.road_access : 0;
  const score = Math.round(sGlide + sObst + sSize + sRel + sSlope + sWind + sAccess);

  const warnings: string[] = [];
  if (kind !== "official") warnings.push(UNOFFICIAL_WARNING[kind]);
  if (kind === "field" && [5, 6, 7, 8, 9].includes(arrivalTime.getUTCMonth() + 1)) warnings.push("Saison des cultures hautes : le champ peut être impraticable.");
  if (!canBeMain(kind, ctx.level)) warnings.push("Atterrissage de secours uniquement à ton niveau (pas d'atterro principal).");
  if (!reachable) warnings.push(`Hors du cône de finesse avec marge : finesse requise ${formatNumber(required, 1)} pour ${formatNumber(available, 1)} disponible.`);
  if (det.obstacles.some((o) => /ligne/i.test(o))) warnings.push("Ligne électrique signalée à proximité : la repérer en vol avant la finale.");
  if (w.gust_kmh - w.speed_kmh >= 10) warnings.push(`Rafales à l'arrivée (${w.gust_kmh} km/h).`);

  const reasons: string[] = [];
  reasons.push(
    marginRatio >= 0.3
      ? `Marge de finesse confortable (requise ${formatNumber(required, 1)} / disponible ${formatNumber(available, 1)})`
      : marginRatio >= 0
        ? `Marge de finesse juste (requise ${formatNumber(required, 1)} / disponible ${formatNumber(available, 1)})`
        : `Marge de finesse insuffisante (requise ${formatNumber(required, 1)} / disponible ${formatNumber(available, 1)})`,
  );
  reasons.push(kind === "official" ? "Atterrissage officiel référencé" : kind === "community" ? "Utilisé par la communauté, non validé FFVL" : "Champ candidat détecté, jamais repéré");
  if (det.size_m) reasons.push(`Terrain de ${det.size_m.length} × ${det.size_m.width} m${det.slope_pct !== null ? `, pente ${formatNumber(det.slope_pct)} %` : ""}`);
  reasons.push(det.obstacles.length ? `${det.obstacles.length} obstacle${det.obstacles.length > 1 ? "s" : ""} signalé${det.obstacles.length > 1 ? "s" : ""}` : "Aucun obstacle signalé");
  reasons.push(`Vent à l'arrivée ${degToCardinalFr(w.direction_deg)} ${w.speed_kmh} km/h${w.speed_kmh > 15 ? " : approche à soigner" : ""}`);
  if (det.access) reasons.push("Accès routier proche");

  return {
    reachable,
    candidate: {
      site: { ...site, landing_kind: kind },
      kind,
      score,
      required_glide_ratio: Math.round(Math.min(99, required) * 10) / 10,
      available_glide_ratio: Math.round(available * 10) / 10,
      arrival_height_m: Math.round(arrival),
      size_m: det.size_m,
      slope_pct: det.slope_pct,
      surface: det.surface,
      obstacles: det.obstacles,
      wind_at_arrival: { speed_kmh: w.speed_kmh, direction_deg: w.direction_deg, gust_kmh: w.gust_kmh },
      community_usage: det.community_usage,
      access: det.access,
      warnings,
      reasons,
    },
  };
}

/** Respect des critères minimaux (non officiels uniquement, CDC §12.2 unofficial_landing_min). */
function meetsMinimum(site: Site, level: Difficulty): boolean {
  const kind = kindOf(site);
  if (kind === "official") return true;
  const det = detailsFor(site);
  if (det.size_m && (det.size_m.length < UNOFFICIAL_MIN.length[level] || det.size_m.width < UNOFFICIAL_MIN.width[level])) return false;
  if (det.slope_pct !== null && det.slope_pct > UNOFFICIAL_MIN.slope[level]) return false;
  return true;
}

/** Cône de finesse (zone atteignable avec la marge officielle, vent compris) au-dessus du fond de vallée. */
export function glideCone(ctx: LandingContext): GeoJsonPolygon {
  const floor = valleyFloor(ctx.takeoff.lat, ctx.takeoff.lon);
  const h = Math.max(0, ctx.takeoff.elevation_m - floor - arrivalMargin(ctx.level, ctx.takeoff.elevation_m - floor));
  const wind = glideWind(ctx, floor);
  const air = ctx.glide * RULES.glideK[ctx.level];
  const ring: [number, number][] = [];
  for (let b = 0; b < 360; b += 10) {
    const r = clamp((h * groundRatio(air, wind, b)) / 1000, 0.3, 30);
    const p = destinationPoint(ctx.takeoff, b, r);
    ring.push([Number(p.lon.toFixed(5)), Number(p.lat.toFixed(5))]);
  }
  ring.push(ring[0]!);
  return { type: "Polygon", coordinates: [ring] };
}

const kindRank = (c: LandingCandidate, level: Difficulty) => (canBeMain(c.kind, level) ? 0 : 1);

/** Trie : atterros pouvant servir d'atterro principal d'abord, puis par score décroissant. */
export function sortCandidates(list: LandingCandidate[], level: Difficulty): LandingCandidate[] {
  return [...list].sort((a, b) => kindRank(a, level) - kindRank(b, level) || b.score - a.score);
}

export interface LandingSearch {
  candidates: LandingCandidate[];
  warnings: string[];
}

/** Recherche des atterros atteignables (officiels → communautaires → champs selon la politique et le niveau). */
export function searchLandings(ctx: LandingContext, policy: LandingPolicy, max = 12): LandingSearch {
  const warnings: string[] = [];
  const allowed = POLICY_KINDS[policy].filter((k) => KIND_LEVELS[k].includes(ctx.level));
  const refused = POLICY_KINDS[policy].filter((k) => !allowed.includes(k));
  if (refused.includes("community")) warnings.push("Atterros communautaires non proposés au niveau élève : uniquement des atterrissages officiels.");
  if (refused.includes("field")) warnings.push("Champs détectés réservés aux pilotes confirmés (et uniquement en secours) : non proposés à ton niveau.");
  const pool: Site[] = [
    ...MOCK_SITES.filter((s) => s.kind !== "takeoff"),
    ...UNOFFICIAL_SITES.map((u) => u.site),
  ].filter((s) => allowed.includes(kindOf(s)) && haversineKm(ctx.takeoff, s) <= 30 && s.elevation_m < ctx.takeoff.elevation_m - 50);
  let belowMin = 0;
  const found: LandingCandidate[] = [];
  for (const s of pool) {
    if (!meetsMinimum(s, ctx.level)) {
      belowMin++;
      continue;
    }
    const { candidate, reachable } = evaluateLanding(s, ctx);
    if (reachable) found.push(candidate);
  }
  if (belowMin) warnings.push(`${belowMin} terrain${belowMin > 1 ? "s" : ""} non officiel${belowMin > 1 ? "s" : ""} écarté${belowMin > 1 ? "s" : ""} : taille ou pente hors des critères minimaux de ton niveau.`);
  const candidates = sortCandidates(found, ctx.level).slice(0, max);
  if (candidates.length === 0) warnings.push("Aucun atterrissage atteignable avec la marge de sécurité depuis ce point.");
  else if (!canBeMain(candidates[0]!.kind, ctx.level)) warnings.push("Aucun atterrissage utilisable comme atterro principal à ton niveau : secours seulement.");
  if (candidates.some((c) => c.kind !== "official")) warnings.push("Atterrissages non officiels : repérage et autorisation du propriétaire à vérifier.");
  return { candidates, warnings };
}

// ───────────────────────────── décollage libre ─────────────────────────────

/** Orientations déduites de la pente (exposition du relief simulé) : 3 secteurs autour de l'exposition. */
export function inferOrientations(lat: number, lon: number): string[] {
  const { aspect } = slopeAspect(lat, lon);
  return Array.from(new Set([degToCompass(normalizeDeg(aspect - 22.5)), degToCompass(aspect), degToCompass(normalizeDeg(aspect + 22.5))]));
}

export const FREE_TAKEOFF_CHECKS = [
  "Autorisation du propriétaire / de la commune ; pas de décollage en cœur de parc, réserve ou arrêté de biotope.",
  "Reconnaissance à pied : rochers, souches, clôtures, câbles, randonneurs, pistes de ski, remontées mécaniques.",
  "Manche à air ou repère de vent improvisé ; pas de vent arrière ni de rotor.",
  "Espace aérien et zones sensibles vérifiés ; prévenir quelqu'un du point de décollage exact (accès secours).",
  "Atterrissage repéré à vue et dans le cône de finesse avant de gonfler.",
];

/** Site « user » construit depuis un décollage libre (altitude et orientations déduites si absentes). */
export function userTakeoffSite(t: CustomTakeoff): Site {
  const elevation = t.elevation_m ?? Math.round(terrainAt(t.lat, t.lon));
  const orientations = t.orientations?.length ? t.orientations : inferOrientations(t.lat, t.lon);
  return {
    id: `user:${t.lat.toFixed(5)},${t.lon.toFixed(5)}`,
    name: t.name?.trim() || "Décollage libre",
    kind: "takeoff",
    lat: t.lat,
    lon: t.lon,
    elevation_m: elevation,
    orientations,
    difficulty: "intermediate",
    flight_types: ["local"],
    description: `Point choisi sur la carte (hors site officiel)${t.elevation_m === undefined ? ", altitude déduite du relief" : ""}${t.orientations?.length ? "" : ", orientation déduite de la pente"}.`,
    access: null,
    restrictions: "Décollage hors site officiel : autorisation du propriétaire, reconnaissance à pied et contrôles obligatoires.",
    status: "unknown",
    source: "user",
    url: null,
    associated_landing_ids: [],
    official: false,
    landing_kind: null,
  };
}

/** Simulation de POST /api/landings/analyze. */
export function mockAnalyzeLandings(req: LandingAnalyzeRequest, now: Date = new Date()): LandingAnalyzeResponse {
  const t = req?.takeoff;
  if (!t || !Number.isFinite(t.lat) || !Number.isFinite(t.lon) || Math.abs(t.lat) > 90 || Math.abs(t.lon) > 180)
    throw new ApiError(422, "Point de décollage invalide.", [{ loc: ["body", "takeoff"], msg: "Value error, Point de décollage invalide." }]);
  if (!isHorizon(req.horizon)) throw new ApiError(422, "Horizon invalide.", [{ loc: ["body", "horizon"], msg: "Value error, Horizon invalide." }]);
  if (!DIFFICULTY_ORDER.includes(req.difficulty)) throw new ApiError(422, "Niveau invalide.", [{ loc: ["body", "difficulty"], msg: "Value error, Niveau invalide." }]);
  if (t.elevation_m !== undefined && (t.elevation_m < -50 || t.elevation_m > 5000))
    throw new ApiError(422, "Altitude du décollage hors limites (0 à 5 000 m).", [{ loc: ["body", "takeoff", "elevation_m"], msg: "Value error, Altitude hors limites." }]);
  const site = userTakeoffSite(t);
  const reference = req.reference_time ? new Date(req.reference_time) : now;
  const target = targetTimeFromHorizon(reference, req.horizon);
  const ctx: LandingContext = { takeoff: site, level: req.difficulty, glide: req.wing_glide_ratio ?? 8.5, time: target };
  const { candidates, warnings } = searchLandings(ctx, req.landing_policy ?? "official_only");
  const head = ["Démo hors-ligne : relief, atterros et vent simulés (atterros non officiels FICTIFS). Ne pas utiliser pour voler."];
  if (req.difficulty === "beginner") head.push("Décollage libre jamais proposé au niveau élève : vole sur un site officiel encadré.");
  if (t.elevation_m === undefined) head.push(`Altitude déduite du relief : ${formatNumber(site.elevation_m)} m (indique-la si tu la connais).`);
  if (!t.orientations?.length) head.push(`Orientation déduite de la pente : ${site.orientations.map(compassFr).join(", ")}.`);
  if (horizonToMinutes(req.horizon) >= 1440) head.push("Horizon long : vent à l'arrivée indicatif seulement.");
  return { takeoff: site, target_time: target.toISOString(), glide_cone: glideCone(ctx), candidates, warnings: [...head, ...warnings] };
}
