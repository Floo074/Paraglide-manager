/**
 * Moteur de plans de vol de DÉMONSTRATION (mode sans backend).
 *
 * Reprend dans les grandes lignes la logique du cahier des charges pilote (filtre no-go puis score
 * non compensatoire, seuils par niveau, briefing dans l'ordre moniteur) sur la météo synthétique.
 * Il sert à rendre l'interface utilisable hors-ligne : ce n'est PAS le moteur de référence.
 */
import type {
  AirspaceWarning,
  Beacon,
  Difficulty,
  FlightPlan,
  FlightType,
  CustomTakeoff,
  Horizon,
  LandingCandidate,
  LandingPolicy,
  PlanFilters,
  PlanRequest,
  PlanResponse,
  Risk,
  ScoreItem,
  Site,
  ThermalAnalysis,
  Waypoint,
  WeatherSnapshot,
} from "../api/types";
import { ApiError } from "../api/errors";
import { DIFFICULTY_ORDER, difficultyLabel } from "../config/labels";
import { bearingDeg, destinationPoint, distancePointToSegmentKm, haversineKm, pointInRing, type Pt } from "../utils/geo";
import { horizonToMinutes, isHorizon, targetTimeFromHorizon } from "../utils/horizon";
import { formatDuration, formatTime, formatNumber } from "../utils/format";
import { sunTimes } from "../utils/sun";
import { COMPASS_16, angleDiff, compassToDeg, compassFr, degToCardinalFr, groundGlideRatio, normalizeDeg } from "../utils/units";
import { formatSpeedTrend } from "../utils/beacons";
import { validateZone, zoneContains } from "../utils/zone";
import { MOCK_AIRSPACES } from "./airspaces";
import { mockBeacons } from "./beacons";
import { RULES, arrivalMargin, thresholdSubscore } from "./rules";
import { FREE_TAKEOFF_CHECKS, UNOFFICIAL_WARNING, canBeMain, evaluateLanding, searchLandings, sortCandidates, userTakeoffSite, type LandingContext } from "./landings";
import { mockSensitiveAreas } from "./sensitiveAreas";
import { nowcastFrom, stationReadings } from "./stations";
import { CROSS_TURNPOINTS, MOCK_SITES, MOCK_SITES_BY_ID, THERMAL_TRIGGERS } from "./sites";
import { facingOf, hash01, scenarioFor, soundingAt, terrainAt, weatherAt } from "./weather";

// ───────────────────────────── outils ─────────────────────────────

const LEVELS = DIFFICULTY_ORDER;
const lvl = (d: Difficulty) => LEVELS.indexOf(d);
const maxLevel = (...ds: Difficulty[]) => LEVELS[Math.max(...ds.map(lvl))]!;
const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));
const MIN = 60_000;
const fmtAlt = (m: number) => `${formatNumber(Math.round(m / 10) * 10)} m`;
const fmtT = (d: Date) => formatTime(d, "Europe/Paris");

interface Finding {
  code: string;
  text: string;
}

const MOCK_SOURCE = (now: Date) => [
  { name: "Prévisions synthétiques (démonstration)", url: null, fetched_at: now.toISOString(), mode: "mock" as const },
  { name: "Sites de démonstration (fixtures)", url: null, fetched_at: now.toISOString(), mode: "mock" as const },
  { name: "Balises de démonstration", url: null, fetched_at: now.toISOString(), mode: "mock" as const },
  { name: "Espaces aériens et zones sensibles (démonstration)", url: null, fetched_at: now.toISOString(), mode: "mock" as const },
];

/** Écart angulaire au secteur favorable le plus proche (− demi-secteur 11,25°, borné à 0). */
export function sectorOffset(windDir: number, orientations: string[]): number {
  const degs = orientations.map(compassToDeg).filter((d): d is number => d !== null);
  if (degs.length === 0) return 0;
  return Math.max(0, Math.min(...degs.map((d) => angleDiff(windDir, d))) - 11.25);
}

function aloftAt(wx: WeatherSnapshot, altitude: number): { speed: number; dir: number } | null {
  const levels = wx.winds_aloft;
  if (levels.length === 0) return null;
  let best = levels[0]!;
  for (const l of levels) if (Math.abs(l.altitude_m - altitude) < Math.abs(best.altitude_m - altitude)) best = l;
  return { speed: best.speed_kmh, dir: best.direction_deg };
}

export function usefulCeiling(wx: WeatherSnapshot): number {
  return Math.min(wx.thermal_ceiling_m, wx.cloud_base_m !== null ? wx.cloud_base_m - 300 : Infinity, RULES.fl115m - 100);
}

function overdevelopmentRisk(wx: WeatherSnapshot): ThermalAnalysis["overdevelopment_risk"] {
  const li = wx.lifted_index ?? 3;
  if (wx.cape_j_kg > 800 && li < 0) return "high";
  if (wx.cape_j_kg >= 300) return "moderate";
  return "low";
}

// ───────────────────────────── conditions ─────────────────────────────

interface Conditions {
  wx: WeatherSnapshot;
  landingWx: WeatherSnapshot;
  speed: number;
  gust: number;
  dir: number;
  offset: number;
  calm: boolean;
  crossComponent: number;
  ceiling: number;
  aloftReached: { alt: 1500 | 2000 | 3000; speed: number }[];
  wind3000: number;
  maxAloft: number;
  lee: { speed: number; dir: number; opposite: boolean };
  precipMax: number;
  overdev: ThermalAnalysis["overdevelopment_risk"];
  thermals: ThermalAnalysis;
  sunset: Date | null;
}

function computeConditions(site: Site, landing: Site, time: Date, durationMin: number): Conditions {
  const facing = facingOf(site.orientations);
  const wx = weatherAt(site.lat, site.lon, site.elevation_m, time, { facingDeg: facing, key: site.id });
  // arrivée = début du créneau (cible − 30 min) + durée de vol
  const arrival = new Date(Math.round((time.getTime() - 30 * MIN) / (15 * MIN)) * 15 * MIN + durationMin * MIN);
  const landingWx = weatherAt(landing.lat, landing.lon, landing.elevation_m, arrival, { isLanding: true, key: landing.id });
  const speed = wx.wind_10m.speed_kmh;
  const dir = wx.wind_10m.direction_deg;
  const offset = sectorOffset(dir, site.orientations);
  const ceiling = usefulCeiling(wx);
  const reachedTop = Math.max(ceiling, site.elevation_m) + 300;
  const aloftReached = ([1500, 2000, 3000] as const)
    .filter((a) => a <= reachedTop && a >= site.elevation_m - 200)
    .map((a) => ({ alt: a, speed: aloftAt(wx, a)?.speed ?? 0 }));
  const crest = aloftAt(wx, site.elevation_m + 300) ?? { speed: 0, dir: 0 };
  const axis = facing ?? dir;
  const precipMax = Math.max(
    ...[-60, 0, 60, durationMin].map(
      (m) => weatherAt(site.lat, site.lon, site.elevation_m, new Date(time.getTime() + m * MIN), { key: site.id }).precipitation_mm_h,
    ),
  );
  return {
    wx,
    landingWx,
    speed,
    gust: wx.wind_10m.gust_kmh,
    dir,
    offset,
    calm: speed < RULES.calmWind,
    crossComponent: speed * Math.sin((Math.min(90, offset) * Math.PI) / 180),
    ceiling,
    aloftReached,
    wind3000: aloftAt(wx, 3000)?.speed ?? 0,
    maxAloft: Math.max(0, ...aloftReached.map((a) => a.speed)),
    lee: { speed: crest.speed, dir: crest.dir, opposite: angleDiff(crest.dir, axis) > 120 },
    precipMax,
    overdev: overdevelopmentRisk(wx),
    thermals: thermalAnalysis(site, time),
    sunset: sunTimes(site.lat, site.lon, time)?.sunset ?? null,
  };
}

function thermalAnalysis(site: Site, time: Date): ThermalAnalysis {
  const facing = facingOf(site.orientations);
  const day = new Date(time);
  day.setUTCHours(4, 0, 0, 0);
  let start: Date | null = null;
  let end: Date | null = null;
  let peak: Date | null = null;
  let peakStrength = 0;
  let maxCape = 0;
  for (let h = 0; h <= 16; h++) {
    const t = new Date(day.getTime() + h * 3_600_000);
    const wx = weatherAt(site.lat, site.lon, site.elevation_m, t, { facingDeg: facing, key: site.id });
    maxCape = Math.max(maxCape, wx.cape_j_kg);
    if (wx.wstar_ms >= 1.2 && wx.boundary_layer_height_agl_m >= 500) start ??= t;
    if (wx.wstar_ms >= 1.0) end = t;
    if (wx.thermal_strength_ms > peakStrength) {
      peakStrength = wx.thermal_strength_ms;
      peak = t;
    }
  }
  const cur = weatherAt(site.lat, site.lon, site.elevation_m, time, { facingDeg: facing, key: site.id });
  const risk = maxCape > 800 ? "high" : maxCape >= 300 ? "moderate" : "low";
  const cumulus = cur.cloud_base_m !== null;
  const parts: string[] = [];
  if (!start) parts.push("Pas de convection exploitable sur la journée.");
  else {
    parts.push(
      `Convection de ${fmtT(start)} à ${end ? fmtT(end) : "?"} (heure légale), pic vers ${peak ? fmtT(peak) : "?"} avec ≈ ${formatNumber(peakStrength, 1, 1)} m/s.`,
    );
    parts.push(cumulus ? `Cumulus, base ≈ ${fmtAlt(cur.cloud_base_m!)}.` : "Thermiques bleus (pas de cumulus).");
  }
  if (risk === "high") parts.push("Surdéveloppement probable l'après-midi : vols du matin uniquement.");
  else if (risk === "moderate") parts.push("Surdéveloppement possible : surveiller l'évolution des cumulus.");
  return {
    convection_start: start?.toISOString() ?? null,
    convection_end: end?.toISOString() ?? null,
    peak_time: peak?.toISOString() ?? null,
    peak_strength_ms: Math.round(peakStrength * 10) / 10,
    ceiling_m: Math.round(usefulCeiling(cur) / 10) * 10, // plafond UTILE (≤ base − 300 m)
    cumulus,
    overdevelopment_risk: risk,
    comment: parts.join(" "),
  };
}

/** Vérifie les seuils absolus (§3) et ceux d'un niveau (§2). */
function checkLevel(level: Difficulty, site: Site, c: Conditions, landingTime: Date): { nogo: Finding[]; marginal: Finding[] } {
  const nogo: Finding[] = [];
  const marginal: Finding[] = [];
  const band = (value: number, max: number, code: string, text: string) => {
    if (value > max) nogo.push({ code, text });
    else if (value > 0.8 * max) marginal.push({ code, text: `${text} (proche de la limite)` });
  };
  const cardinal = degToCardinalFr(c.dir);
  // §3 absolus
  if (site.status === "closed") nogo.push({ code: "SITE_CLOSED", text: "Site fermé" });
  if (c.precipMax >= RULES.nogo.precipMmH) nogo.push({ code: "RAIN", text: `Pluie prévue (${formatNumber(c.precipMax, 1)} mm/h) sur le créneau` });
  const li = c.wx.lifted_index ?? 3;
  if (c.wx.cape_j_kg >= RULES.nogo.capeAbsolute || (c.wx.cape_j_kg >= RULES.nogo.capeStorm.cape && li <= RULES.nogo.capeStorm.li))
    nogo.push({ code: "THUNDERSTORM", text: `Risque orageux (CAPE ${formatNumber(c.wx.cape_j_kg)} J/kg, LI ${formatNumber(li, 1)})` });
  else if (c.overdev === "high") nogo.push({ code: "OVERDEVELOPMENT", text: "Surdéveloppement probable pendant le vol" });
  if (c.wx.cloud_base_m !== null && c.wx.cloud_base_m < site.elevation_m + RULES.nogo.cloudBaseMinAboveTakeoff)
    nogo.push({ code: "LOW_CLOUD_BASE", text: `Base des nuages (${fmtAlt(c.wx.cloud_base_m)}) trop proche du déco` });
  if (c.maxAloft >= RULES.nogo.windAnyLevel || c.wind3000 >= 50)
    nogo.push({ code: "STRONG_WIND_ALOFT", text: `Vent fort en altitude (${Math.round(Math.max(c.maxAloft, c.wind3000))} km/h)` });
  if (c.lee.opposite && c.lee.speed >= RULES.nogo.leeWindAtCrest)
    nogo.push({ code: "LEE_SIDE", text: `Dévent : vent de ${degToCardinalFr(c.lee.dir)} ${Math.round(c.lee.speed)} km/h au niveau de la crête, déco sous le vent` });
  else if (c.lee.opposite && c.lee.speed >= 10)
    marginal.push({ code: "LEE_SIDE", text: `Vent météo opposé au déco (${degToCardinalFr(c.lee.dir)} ${Math.round(c.lee.speed)} km/h à la crête)` });
  if (c.sunset && landingTime.getTime() > c.sunset.getTime())
    nogo.push({ code: "SUNSET", text: `Atterrissage après le coucher du soleil (${fmtT(c.sunset)}) : vol de nuit interdit` });
  else if (c.sunset && landingTime.getTime() > c.sunset.getTime() - 30 * MIN)
    marginal.push({ code: "SUNSET", text: `Atterrissage moins de 30 min avant le coucher du soleil (${fmtT(c.sunset)})` });

  // §2 par niveau
  band(c.speed, RULES.takeoffWindMax[level], "TAKEOFF_WIND", `Vent au déco ${Math.round(c.speed)} km/h (max ${RULES.takeoffWindMax[level]} pour ce niveau)`);
  band(c.gust, RULES.takeoffGustMax[level], "TAKEOFF_GUSTS", `Rafales au déco ${Math.round(c.gust)} km/h (max ${RULES.takeoffGustMax[level]})`);
  band(c.gust - c.speed, RULES.gustSpreadMax[level], "TAKEOFF_GUSTS", `Écart rafales/moyenne ${Math.round(c.gust - c.speed)} km/h`);
  if (!c.calm) {
    if (c.offset > 90) {
      band(c.speed, RULES.tailwindMax[level] || 0.001, "TAILWIND", `Vent arrière au déco (${cardinal} ${Math.round(c.speed)} km/h)`);
    } else if (c.offset > 0) {
      if (c.offset > RULES.crosswindAngleMax[level] || c.crossComponent > RULES.crosswindComponentMax[level])
        nogo.push({ code: "CROSSWIND", text: `Vent de travers au déco (${cardinal}, écart ${Math.round(c.offset)}°)` });
      else if (c.offset > 0.8 * RULES.crosswindAngleMax[level])
        marginal.push({ code: "CROSSWIND", text: `Vent légèrement de travers (${cardinal}, écart ${Math.round(c.offset)}°)` });
    }
  }
  for (const a of c.aloftReached) {
    band(a.speed, RULES.windAloftMax[a.alt][level], "STRONG_WIND_ALOFT", `Vent ${Math.round(a.speed)} km/h à ${fmtAlt(a.alt)}`);
  }
  band(c.landingWx.wind_10m.speed_kmh, RULES.landingWindMax[level], "LANDING_WIND", `Vent à l'atterro ${Math.round(c.landingWx.wind_10m.speed_kmh)} km/h à l'arrivée`);
  return { nogo, marginal };
}

// ───────────────────────────── route ─────────────────────────────

interface P3 extends Pt {
  alt: number;
}

const CAPPING_CLASSES = new Set(["A", "C", "D", "P", "R"]);

function altitudeCap(p: Pt, ceiling: number): number {
  let cap = Math.min(ceiling, RULES.fl115m - 100);
  for (const f of MOCK_AIRSPACES) {
    if (!CAPPING_CLASSES.has(f.properties.airspace_class) || f.properties.floor_m <= 0) continue;
    const ring = f.geometry.type === "Polygon" ? f.geometry.coordinates[0]! : f.geometry.coordinates[0]![0]!;
    if (pointInRing(p, ring)) cap = Math.min(cap, f.properties.floor_m - 100);
  }
  return cap;
}

class RouteBuilder {
  readonly pts: P3[] = [];
  constructor(start: P3, private readonly ceiling: number, private readonly climbMinAgl = 400) {
    this.pts.push({ ...start });
  }
  get last(): P3 {
    return this.pts[this.pts.length - 1]!;
  }
  climb(to: number): this {
    const p = this.last;
    const target = Math.min(to, altitudeCap(p, this.ceiling));
    if (target > p.alt + 20) this.pts.push({ lat: p.lat, lon: p.lon, alt: Math.round(target) });
    return this;
  }
  /** Transition en plané (finesse `ratio`) avec reprises thermiques si on passe trop bas. */
  glideTo(target: Pt, ratio: number, opts: { endAlt?: number; climbTo?: number } = {}): this {
    const start = this.last;
    const dist = haversineKm(start, target);
    const steps = Math.max(1, Math.ceil(dist / 0.6));
    for (let i = 1; i <= steps; i++) {
      const t = i / steps;
      const p = { lat: start.lat + (target.lat - start.lat) * t, lon: start.lon + (target.lon - start.lon) * t };
      const prev = this.last;
      let alt: number;
      if (opts.endAlt !== undefined) alt = start.alt + (opts.endAlt - start.alt) * t;
      else alt = prev.alt - (haversineKm(prev, p) * 1000) / ratio;
      alt = Math.min(alt, altitudeCap(p, this.ceiling));
      this.pts.push({ ...p, alt: Math.round(alt) });
      if (opts.endAlt === undefined && opts.climbTo !== undefined && i < steps && alt < terrainAt(p.lat, p.lon) + this.climbMinAgl) {
        this.climb(opts.climbTo);
      }
    }
    return this;
  }
  coordinates(): [number, number, number][] {
    return this.pts.map((p) => [Number(p.lon.toFixed(5)), Number(p.lat.toFixed(5)), Math.round(p.alt)]);
  }
  lengthKm(): number {
    let d = 0;
    for (let i = 1; i < this.pts.length; i++) d += haversineKm(this.pts[i - 1]!, this.pts[i]!);
    return d;
  }
}

/** Zone de perte d'altitude (PTU) côté sous le vent de l'atterro. */
function approachPoint(landing: Site, landingWindDir: number): Pt {
  return destinationPoint(landing, normalizeDeg(landingWindDir + 180), 0.45);
}

// ───────────────────────────── construction des vols ─────────────────────────────

type Variant = "plouf" | "thermal" | "soaring" | "cross";

interface Candidate {
  variant: Variant;
  type: FlightType;
  thermal_usage: FlightPlan["thermal_usage"];
  natural: [number, number];
  minLevel: Difficulty;
  extraMarginal: Finding[];
}

interface BuildCtx {
  site: Site;
  landing: Site;
  target: Date;
  filters: Required<Pick<PlanFilters, "duration_min_minutes" | "duration_max_minutes" | "difficulty" | "thermals">> & {
    wing_glide_ratio: number;
  };
  horizon: Horizon;
  now: Date;
  /** Décollage libre : point demandé, politique d'atterrissage et atterros trouvés (le 1er = principal). */
  custom?: { takeoff: CustomTakeoff; policy: LandingPolicy; candidates: LandingCandidate[] };
}

function ploufMinutes(site: Site, landing: Site, time: Date, sunset: Date | null): number {
  const base = (site.elevation_m - landing.elevation_m) / (RULES.sinkRateMs * 60) + 3;
  const restitution = sunset && time.getTime() > sunset.getTime() - 90 * MIN && time.getTime() < sunset.getTime();
  return Math.round(base * (restitution ? 1.6 : 1));
}

function candidatesFor(ctx: BuildCtx, c: Conditions, level: Difficulty): { list: Candidate[]; notes: Finding[] } {
  const { site, landing, target, filters } = ctx;
  const list: Candidate[] = [];
  const notes: Finding[] = [];
  const wanted = new Set<FlightType>(site.flight_types);
  const strength = c.wx.thermal_strength_ms;
  const above = c.ceiling - site.elevation_m;
  const convEnd = c.thermals.convection_end ? new Date(c.thermals.convection_end) : null;
  const sunsetLimit = c.sunset ? (c.sunset.getTime() - 30 * MIN - target.getTime()) / MIN : 600;
  const plouf = ploufMinutes(site, landing, target, c.sunset);
  const cap = (m: number) => Math.max(0, Math.min(m, RULES.maxDurationMin[level], sunsetLimit));

  if (wanted.has("local") || site.flight_types.length === 0) {
    const thermalOk = strength >= 0.8 && above >= RULES.localCeilingMinAboveTakeoff[level] && filters.thermals !== "avoid";
    if (thermalOk) {
      const remaining = convEnd ? (convEnd.getTime() - target.getTime()) / MIN + plouf : plouf;
      const hi = cap(Math.max(plouf, remaining));
      list.push({
        variant: "thermal",
        type: "local",
        thermal_usage: strength >= 1.5 ? "essential" : "optional",
        natural: [Math.min(30, hi), hi],
        minLevel: strength > RULES.thermalMax.beginner ? "intermediate" : "beginner",
        extraMarginal: [],
      });
    } else if (filters.thermals === "required") {
      notes.push({ code: "WEAK_THERMALS", text: `Thermiques insuffisants pour un vol local (vario ${formatNumber(strength, 1, 1)} m/s, plafond utile ${fmtAlt(c.ceiling)})` });
    }
    if (filters.thermals !== "required") {
      const marg: Finding[] = [];
      if (filters.thermals === "avoid" && strength > 1.5)
        marg.push({ code: "STRONG_THERMALS", text: "Air thermique actif à cette heure : préférer le matin ou la restitution du soir" });
      list.push({ variant: "plouf", type: "local", thermal_usage: "none", natural: [plouf, plouf + 5], minLevel: "beginner", extraMarginal: marg });
    }
  }
  if (wanted.has("ridge_soaring")) {
    const facingComp = c.speed * Math.cos((Math.min(90, c.offset) * Math.PI) / 180);
    if (facingComp >= RULES.ridge.minKmh && facingComp <= RULES.ridge.maxKmh[level] && c.offset <= RULES.ridge.maxAngle[level] && c.gust - c.speed <= 8) {
      list.push({
        variant: "soaring",
        type: "ridge_soaring",
        thermal_usage: strength >= 1 && filters.thermals !== "avoid" ? "optional" : "none",
        natural: [20, cap(level === "beginner" ? 30 : 90)],
        minLevel: "beginner",
        extraMarginal: [],
      });
    } else {
      notes.push({ code: "TAKEOFF_WIND", text: `Soaring impossible : vent de face ${Math.round(facingComp)} km/h (il faut ${RULES.ridge.minKmh}-${RULES.ridge.maxKmh[level]} km/h bien dans l'axe)` });
    }
  }
  if (wanted.has("cross_country") && filters.thermals !== "avoid") {
    if (level === "beginner") notes.push({ code: "", text: "Cross non proposé au niveau débutant" });
    else if (strength < 1.5 || above < RULES.xcCeilingMinAboveTakeoff[level])
      notes.push({ code: "WEAK_THERMALS", text: `Conditions trop faibles pour un cross (vario ${formatNumber(strength, 1, 1)} m/s, plafond utile ${fmtAlt(c.ceiling)})` });
    else {
      const remaining = convEnd ? (convEnd.getTime() - target.getTime()) / MIN + 30 : 0;
      const hi = cap(remaining);
      if (hi >= 90) list.push({ variant: "cross", type: "cross_country", thermal_usage: "essential", natural: [90, hi], minLevel: "intermediate", extraMarginal: [] });
      else notes.push({ code: "", text: "Fenêtre thermique restante trop courte pour un cross" });
    }
  }
  return { list, notes };
}

function xcSpeed(level: Difficulty, vario: number): number {
  const key = level === "beginner" ? "intermediate" : level;
  const table = RULES.xcSpeedByVario[key];
  const v = clamp(vario, 1, table.length - 1);
  const i = Math.floor(v);
  const frac = v - i;
  const a = table[i]!;
  const b = table[Math.min(table.length - 1, i + 1)]!;
  return a + (b - a) * frac;
}

interface BuiltRoute {
  builder: RouteBuilder;
  waypoints: Waypoint[];
  decision: string[];
  lastBeforeFinal: P3;
  distanceKm: number;
}

function buildRoute(variant: Variant, ctx: BuildCtx, c: Conditions, durationMin: number, level: Difficulty): BuiltRoute {
  const { site, landing } = ctx;
  const glide = ctx.filters.wing_glide_ratio;
  const facing = facingOf(site.orientations) ?? 270;
  const ceiling = c.ceiling;
  const start: P3 = { lat: site.lat, lon: site.lon, alt: site.elevation_m };
  const rb = new RouteBuilder(start, ceiling);
  const wps: Waypoint[] = [
    { name: `Déco ${site.name}`, lat: site.lat, lon: site.lon, altitude_m: site.elevation_m, type: "takeoff", radius_m: 400, eta_min: 0, note: `Orientations ${site.orientations.map(compassFr).join(", ")}` },
  ];
  const decision: string[] = [];
  const ptu = approachPoint(landing, c.landingWx.wind_10m.direction_deg);
  const landingAlt = landing.elevation_m;
  const margin = arrivalMargin(level, site.elevation_m - landing.elevation_m);

  if (variant === "plouf") {
    rb.glideTo(ptu, glide, { endAlt: landingAlt + 250 });
    rb.glideTo(landing, glide, { endAlt: landingAlt });
    wps.push({ name: "Zone de perte d'altitude", lat: ptu.lat, lon: ptu.lon, altitude_m: landingAlt + 250, type: "turnpoint", radius_m: 300, eta_min: Math.round(durationMin * 0.7), note: "PTU côté sous le vent de l'atterrissage" });
    return { builder: rb, waypoints: wps, decision, lastBeforeFinal: start, distanceKm: rb.lengthKm() };
  }

  if (variant === "soaring") {
    const front = destinationPoint(site, facing, 0.15);
    const a = destinationPoint(front, normalizeDeg(facing + 90), 0.8);
    const b = destinationPoint(front, normalizeDeg(facing - 90), 0.8);
    const alt = site.elevation_m + 120;
    rb.glideTo(a, glide, { endAlt: alt }).glideTo(b, glide, { endAlt: alt + 30 }).glideTo(a, glide, { endAlt: alt }).glideTo(b, glide, { endAlt: alt + 30 });
    const last = rb.last;
    rb.glideTo(ptu, glide, { endAlt: landingAlt + 250 }).glideTo(landing, glide, { endAlt: landingAlt });
    wps.push(
      { name: `Bout de pente ${degToCardinalFr(normalizeDeg(facing + 90))}`, lat: a.lat, lon: a.lon, altitude_m: alt, type: "turnpoint", radius_m: 200, eta_min: 3, note: "Demi-tour face à la pente, virage côté vallée" },
      { name: `Bout de pente ${degToCardinalFr(normalizeDeg(facing - 90))}`, lat: b.lat, lon: b.lon, altitude_m: alt + 30, type: "turnpoint", radius_m: 200, eta_min: 6, note: "Priorité au pilote qui a la pente à sa droite" },
      { name: "Zone de perte d'altitude", lat: ptu.lat, lon: ptu.lon, altitude_m: landingAlt + 250, type: "turnpoint", radius_m: 300, eta_min: Math.round(durationMin - 5), note: null },
    );
    decision.push(`Si le vent de face passe sous ${RULES.ridge.minKmh} km/h ou que tu descends sous le déco : quitter la pente vers l'atterro.`);
    return { builder: rb, waypoints: wps, decision, lastBeforeFinal: last, distanceKm: rb.lengthKm() };
  }

  if (variant === "thermal") {
    const named = THERMAL_TRIGGERS[site.id];
    const t1: Pt & { name: string } = named ?? { ...destinationPoint(destinationPoint(site, normalizeDeg(facing + 180), 0.3), normalizeDeg(facing + 90), 1.1), name: "Éperon au soleil" };
    const t2 = { ...destinationPoint(site, normalizeDeg(facing - 90), 2.2), name: "Rupture de pente" };
    const top1 = Math.min(ceiling - 100, site.elevation_m + 900);
    const top2 = Math.min(ceiling - 200, site.elevation_m + 700);
    // premier thermique devant le déco : on ne part vers les déclencheurs qu'avec de la hauteur
    rb.climb(Math.min(top1, site.elevation_m + 300));
    rb.glideTo(t1, glide).climb(top1);
    const a1 = rb.last.alt;
    rb.glideTo(t2, glide * 0.8).climb(top2);
    const last = rb.last;
    rb.glideTo(ptu, glide, { endAlt: landingAlt + 250 }).glideTo(landing, glide, { endAlt: landingAlt });
    wps.push(
      { name: t1.name, lat: t1.lat, lon: t1.lon, altitude_m: Math.round(a1), type: "thermal_trigger", radius_m: 400, eta_min: 5, note: `Enrouler jusqu'à ≈ ${fmtAlt(a1)}` },
      { name: t2.name, lat: t2.lat, lon: t2.lon, altitude_m: Math.round(last.alt), type: "thermal_trigger", radius_m: 400, eta_min: Math.round(durationMin * 0.45), note: "Déclencheur secondaire sur face au soleil" },
      { name: "Zone de perte d'altitude", lat: ptu.lat, lon: ptu.lon, altitude_m: landingAlt + 250, type: "turnpoint", radius_m: 300, eta_min: Math.round(durationMin - 6), note: null },
    );
    return { builder: rb, waypoints: wps, decision, lastBeforeFinal: last, distanceKm: rb.lengthKm() };
  }

  // cross : triangle, premier côté face au vent (ou balises remarquables)
  const vario = c.wx.thermal_strength_ms;
  const aloft = aloftAt(c.wx, Math.min(c.ceiling, 2500)) ?? { speed: 10, dir: c.dir };
  const vxc = xcSpeed(level, vario) * (glide >= 9.5 ? 1.15 : 1);
  const w = aloft.speed * 0.7;
  const veff = Math.max(8, vxc - (w * w) / vxc);
  const climb0 = Math.max(10, (c.ceiling - site.elevation_m) / Math.max(0.5, vario) / 60);
  const targetDist = Math.min(RULES.xcMaxDistanceKm[level], (veff * Math.max(20, durationMin - climb0 - 10)) / 60);
  const fixed = CROSS_TURNPOINTS[site.id];
  let tps: (Pt & { name: string; altitude_m?: number })[];
  if (fixed && fixed.length >= 2) {
    const total = haversineKm(site, fixed[0]!) + haversineKm(fixed[0]!, fixed[1]!) + haversineKm(fixed[1]!, landing);
    tps = total <= targetDist * 1.35 && total >= targetDist * 0.5 ? fixed : [];
  } else tps = [];
  if (tps.length === 0) {
    const leg = Math.max(3, targetDist / 3);
    const p1 = destinationPoint(site, aloft.dir, leg);
    const p2 = destinationPoint(p1, normalizeDeg(aloft.dir + 120), leg);
    tps = [
      { ...p1, name: `Balise ${degToCardinalFr(aloft.dir)}` },
      { ...p2, name: `Balise ${degToCardinalFr(bearingDeg(site, p2))}` },
    ];
  }
  const ratio = glide * 0.7;
  const top = c.ceiling - 50;
  rb.climb(top);
  let cum = climb0;
  let prev: Pt = site;
  for (const tp of tps) {
    rb.glideTo(tp, ratio, { climbTo: top });
    cum += (haversineKm(prev, tp) / veff) * 60;
    prev = tp;
    const here = rb.last.alt;
    rb.climb(top);
    const finesseSol = groundGlideRatio(glide * RULES.glideK[level], 0);
    const altSec = landingAlt + margin + (haversineKm(tp, landing) * 1000) / Math.max(1, finesseSol);
    wps.push({
      name: tp.name,
      lat: tp.lat,
      lon: tp.lon,
      altitude_m: Math.round(Math.max(here, rb.last.alt)),
      type: "turnpoint",
      radius_m: 400,
      eta_min: Math.round(cum),
      note: `Altitude de sécurité ≈ ${fmtAlt(altSec)} (retour ${landing.name})`,
    });
    decision.push(`Sous ${fmtAlt(altSec)} à ${tp.name} : retour direct vers ${landing.name}.`);
  }
  const last = rb.last;
  rb.glideTo(ptu, ratio, { climbTo: top });
  rb.glideTo(landing, glide, { endAlt: landingAlt });
  return { builder: rb, waypoints: wps, decision, lastBeforeFinal: last, distanceKm: rb.lengthKm() };
}

// ───────────────────────────── évaluation complète ─────────────────────────────

function nearbyLandings(route: P3[], main: Site): Site[] {
  return MOCK_SITES.filter((s) => s.kind !== "takeoff" && s.id !== main.id)
    .map((s) => ({ s, d: Math.min(...route.map((p) => haversineKm(p, s))) }))
    .filter((x) => x.d <= 10)
    .sort((a, b) => a.d - b.d)
    .slice(0, 3)
    .map((x) => x.s);
}

function airspaceWarnings(route: P3[]): AirspaceWarning[] {
  const out: AirspaceWarning[] = [];
  for (const f of MOCK_AIRSPACES) {
    const ring = f.geometry.type === "Polygon" ? f.geometry.coordinates[0]! : f.geometry.coordinates[0]![0]!;
    let minD = Infinity;
    let intersects = false;
    let inside2d = false;
    for (const p of route) {
      if (pointInRing(p, ring)) {
        inside2d = true;
        minD = 0;
        if (p.alt >= f.properties.floor_m && p.alt <= f.properties.ceiling_m) intersects = true;
      } else {
        for (let i = 1; i < ring.length; i++) {
          const a = { lon: ring[i - 1]![0]!, lat: ring[i - 1]![1]! };
          const b = { lon: ring[i]![0]!, lat: ring[i]![1]! };
          minD = Math.min(minD, distancePointToSegmentKm(p, a, b));
        }
      }
    }
    if (minD <= 8 || inside2d) {
      out.push({ ...f.properties, min_distance_km: Math.round(minD * 10) / 10, intersects_route: intersects });
    }
  }
  return out.sort((a, b) => a.min_distance_km - b.min_distance_km);
}

function sensitiveRisks(route: P3[], at: Date): Risk[] {
  const risks: Risk[] = [];
  for (const f of mockSensitiveAreas(at)) {
    if (!f.properties.active_now) continue;
    const ring = f.geometry.type === "Polygon" ? f.geometry.coordinates[0]! : f.geometry.coordinates[0]![0]!;
    const minH = f.properties.min_height_agl_m ?? 0;
    const insideLow = route.some((p) => pointInRing(p, ring) && p.alt - terrainAt(p.lat, p.lon) < minH);
    const inside = insideLow || route.some((p) => pointInRing(p, ring));
    let minD = Infinity;
    for (const p of route)
      for (let i = 1; i < ring.length; i++)
        minD = Math.min(minD, distancePointToSegmentKm(p, { lon: ring[i - 1]![0]!, lat: ring[i - 1]![1]! }, { lon: ring[i]![0]!, lat: ring[i]![1]! }));
    if (!inside && minD > 0.3) continue;
    const park = f.properties.kind === "national_park_core";
    risks.push({
      code: park ? "NATIONAL_PARK" : "SENSITIVE_AREA",
      level: insideLow ? (park ? "danger" : "caution") : "info",
      title: insideLow
        ? `Zone sensible traversée trop bas : ${f.properties.name}`
        : inside
          ? `Survol de zone sensible : ${f.properties.name} (rester à plus de ${minH} m/sol)`
          : `Zone sensible à ${Math.round(minD * 1000)} m : ${f.properties.name}`,
      detail: `${f.properties.species ? f.properties.species + " — " : ""}${f.properties.recommendation}`,
    });
  }
  return risks;
}

function nearbyBeacons(site: Site, now: Date): Beacon[] {
  return mockBeacons(now)
    .map((b) => ({ b, d: haversineKm(b, site) }))
    .filter((x) => x.d <= 15)
    .sort((a, b) => a.d - b.d)
    .map((x) => x.b);
}

function roundTo(date: Date, minutes: number): Date {
  const step = minutes * MIN;
  return new Date(Math.round(date.getTime() / step) * step);
}

const VARIANT_TITLE: Record<Variant, string> = {
  plouf: "plouf",
  thermal: "local thermique",
  soaring: "soaring",
  cross: "cross",
};

function confidenceFor(horizon: Horizon, wx: WeatherSnapshot): number {
  let c = RULES.horizonBaseConfidence[horizon];
  if (wx.cape_j_kg > 500) c *= 0.85;
  return Math.round(c * 100) / 100;
}

function scoreItems(ctx: BuildCtx, c: Conditions, _cand: Candidate, est: number, glideReq: number, glideAvail: number, confidence: number, level: Difficulty): ScoreItem[] {
  const strength = c.wx.thermal_strength_ms;
  const takeoffScore = c.calm
    ? 80
    : Math.min(
        thresholdSubscore(c.speed, RULES.takeoffWindMax[level]) + (c.speed >= 5 && c.speed <= 15 ? 15 : 0),
        thresholdSubscore(c.gust - c.speed, RULES.gustSpreadMax[level]),
        thresholdSubscore(c.offset, RULES.crosswindAngleMax[level]),
        100,
      );
  const aloftScore = Math.min(100, ...c.aloftReached.map((a) => thresholdSubscore(a.speed, RULES.windAloftMax[a.alt][level])));
  const glideRatio = glideAvail > 0 ? glideReq / glideAvail : 2;
  const glideScore = glideRatio <= 0.7 ? 100 : glideRatio >= 1 ? 0 : 100 - ((glideRatio - 0.7) / 0.3) * 100;
  const landingScore = Math.min(thresholdSubscore(c.landingWx.wind_10m.speed_kmh, RULES.landingWindMax[level]), glideScore);
  let thermalScore: number;
  if (ctx.filters.thermals === "required") thermalScore = strength < 0.8 ? 0 : strength <= RULES.thermalMax[level] - 0.5 ? clamp(50 + (strength - 0.8) * 70, 50, 100) : 60;
  else if (ctx.filters.thermals === "avoid") thermalScore = strength > 1.5 ? 25 : 100 - strength * 30;
  else thermalScore = strength < 0.8 ? 70 : strength > 0.8 * RULES.thermalMax[level] ? 55 : 85;
  const { duration_min_minutes: mn, duration_max_minutes: mx } = ctx.filters;
  const gap = est < mn ? (mn - est) / mn : est > mx ? (est - mx) / mx : 0;
  const durationScore = clamp(100 - gap * 200, 0, 100);
  const convective = clamp(100 - c.wx.cape_j_kg / 8 - (c.overdev === "moderate" ? 25 : c.overdev === "high" ? 60 : 0), 0, 100);
  const confScore = clamp(((confidence - 0.3) / 0.6) * 100, 0, 100);
  const siteScore = ctx.site.status === "restricted" ? 60 : 100;
  const W = RULES.weights;
  const item = (criterion: keyof typeof W, score: number, comment: string): ScoreItem => ({ criterion, score: Math.round(score), weight: W[criterion], comment });
  return [
    item("takeoff_wind", takeoffScore, c.calm ? "Vent nul : décollage plus technique" : `${degToCardinalFr(c.dir)} ${Math.round(c.speed)} km/h, rafales ${Math.round(c.gust)}, écart au secteur ${Math.round(c.offset)}°`),
    item("wind_aloft", aloftScore, c.aloftReached.length ? c.aloftReached.map((a) => `${a.speed} km/h à ${a.alt} m`).join(", ") : "Niveaux d'altitude non atteints"),
    item("landing", landingScore, `Vent ${Math.round(c.landingWx.wind_10m.speed_kmh)} km/h à l'arrivée ; finesse requise ${formatNumber(glideReq, 1)} / ${formatNumber(glideAvail, 1)}`),
    item("thermal_match", thermalScore, `Vario ≈ ${formatNumber(strength, 1, 1)} m/s, plafond utile ${fmtAlt(c.ceiling)}`),
    item("duration_match", durationScore, gap === 0 ? "Durée dans la plage demandée" : `Durée réaliste ${formatDuration(est)} (demandé ${formatDuration(mn)} – ${formatDuration(mx)})`),
    item("convective_stability", convective, `CAPE ${c.wx.cape_j_kg} J/kg, surdéveloppement ${c.overdev === "low" ? "faible" : c.overdev === "moderate" ? "modéré" : "élevé"}`),
    item("data_confidence", confScore, "Prévisions synthétiques (démonstration)"),
    item("site_fit", siteScore, ctx.site.status === "restricted" ? "Site avec restrictions" : `Site adapté (${difficultyLabel(ctx.site.difficulty)})`),
  ];
}

const SAFETY = new Set(["takeoff_wind", "wind_aloft", "landing", "convective_stability"]);
/** Risques « prudence » qui n'empêchent pas un GO (CDC §12.2 : NO_LANDING_BEACON blocks_go: false). */
const NON_BLOCKING = new Set(["MOCK_DATA", "NO_LANDING_BEACON"]);

function verdict(items: ScoreItem[], confidence: number, horizon: Horizon, risks: Risk[]): { score: number; flyability: FlightPlan["flyability"] } {
  const total = items.reduce((s, i) => s + i.score * i.weight, 0) / items.reduce((s, i) => s + i.weight, 0);
  const minSafety = Math.min(...items.filter((i) => SAFETY.has(i.criterion)).map((i) => i.score));
  const score = Math.round(Math.min(total, 40 + minSafety));
  const V = RULES.verdict;
  if (risks.some((r) => r.level === "danger") || score < V.nogoMaxScore) return { score, flyability: "no_go" };
  const confOk = confidence >= V.goMinConfidenceRatio * RULES.horizonBaseConfidence[horizon];
  if (score >= V.goMinScore && minSafety >= V.goMinSafety && confOk && !risks.some((r) => r.level === "caution" && !NON_BLOCKING.has(r.code)))
    return { score, flyability: "go" };
  return { score, flyability: "marginal" };
}

// ───────────────────────────── identifiants partageables ─────────────────────────────

const VARIANT_CODE: Record<Variant, string> = { plouf: "plouf", thermal: "loc", soaring: "soar", cross: "xc" };
const CODE_VARIANT: Record<string, Variant> = { plouf: "plouf", loc: "thermal", soar: "soaring", xc: "cross" };

interface PlanKey {
  siteId: string;
  variant: Variant;
  target: Date;
  horizon: Horizon;
  filters: BuildCtx["filters"];
  rank: number;
  /** Décollage libre : le point (sans le nom) et la politique d'atterrissage sont dans l'identifiant. */
  custom?: { takeoff: CustomTakeoff; policy: LandingPolicy };
}

const POLICY_CODE: Record<LandingPolicy, string> = { official_only: "o", include_community: "c", include_fields: "f" };
const CODE_POLICY: Record<string, LandingPolicy> = { o: "official_only", c: "include_community", f: "include_fields" };

/** Jeton de site : "forclaz" (fixture) ou "u45.81234~6.24567~1250~0c00~c" (décollage libre). */
function siteToken(k: PlanKey): string {
  if (!k.custom) return k.siteId.replace(/^fixture:/, "");
  const t = k.custom.takeoff;
  let mask = 0;
  for (const o of t.orientations ?? []) {
    const i = COMPASS_16.indexOf(o.toUpperCase() as (typeof COMPASS_16)[number]);
    if (i >= 0) mask |= 1 << i;
  }
  const elev = t.elevation_m !== undefined ? String(Math.round(t.elevation_m)) : "";
  return `u${t.lat.toFixed(5)}~${t.lon.toFixed(5)}~${elev}~${mask ? mask.toString(16) : ""}~${POLICY_CODE[k.custom.policy]}`;
}

function parseUserToken(token: string): PlanKey["custom"] | null {
  const m = /^u(-?\d+(?:\.\d+)?)~(-?\d+(?:\.\d+)?)~(\d*)~([0-9a-f]*)~([ocf])$/.exec(token);
  if (!m) return null;
  const mask = m[4] ? parseInt(m[4], 16) : 0;
  const orientations = COMPASS_16.filter((_, i) => mask & (1 << i));
  return {
    takeoff: {
      lat: Number(m[1]),
      lon: Number(m[2]),
      ...(m[3] ? { elevation_m: Number(m[3]) } : {}),
      ...(orientations.length ? { orientations: [...orientations] } : {}),
    },
    policy: CODE_POLICY[m[5]!]!,
  };
}

export function encodePlanId(k: PlanKey): string {
  const t = k.target.toISOString().replace(/[-:]/g, "").slice(0, 13);
  return [
    "demo",
    siteToken(k),
    VARIANT_CODE[k.variant],
    t,
    k.horizon,
    k.filters.difficulty,
    k.filters.thermals,
    k.filters.duration_min_minutes,
    k.filters.duration_max_minutes,
    Math.round(k.filters.wing_glide_ratio * 10),
    k.rank,
  ].join("_");
}

export function decodePlanId(id: string): PlanKey | null {
  const p = id.split("_");
  if (p.length !== 11 || p[0] !== "demo") return null;
  const [, site, v, t, horizon, diff, th, mn, mx, g, rank] = p as [string, string, string, string, string, string, string, string, string, string, string];
  const variant = CODE_VARIANT[v];
  const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})$/.exec(t);
  if (!variant || !m || !isHorizon(horizon) || !LEVELS.includes(diff as Difficulty) || !["required", "allowed", "avoid"].includes(th)) return null;
  const custom = site.startsWith("u") ? parseUserToken(site) : undefined;
  if (custom === null) return null;
  return {
    siteId: custom ? `user:${custom.takeoff.lat.toFixed(5)},${custom.takeoff.lon.toFixed(5)}` : `fixture:${site}`,
    custom,
    variant,
    target: new Date(Date.UTC(+m[1]!, +m[2]! - 1, +m[3]!, +m[4]!, +m[5]!)),
    horizon,
    filters: {
      difficulty: diff as Difficulty,
      thermals: th as PlanFilters["thermals"],
      duration_min_minutes: Number(mn),
      duration_max_minutes: Number(mx),
      wing_glide_ratio: Number(g) / 10,
    },
    rank: Number(rank) || 1,
  };
}

// ───────────────────────────── atterros évalués ─────────────────────────────

function landingCtx(ctx: BuildCtx, arrivalAfterMin?: number): LandingContext {
  return { takeoff: ctx.site, level: ctx.filters.difficulty, glide: ctx.filters.wing_glide_ratio, time: ctx.target, arrivalAfterMin };
}

/** landing_analysis : l'atterro principal en premier, puis les autres candidats évalués (triés). */
function landingAnalysisFor(ctx: BuildCtx, landing: Site, alternates: Site[], est: number): LandingCandidate[] {
  const lc = landingCtx(ctx, est);
  if (ctx.custom) {
    const main = ctx.custom.candidates.find((c) => c.site.id === landing.id) ?? evaluateLanding(landing, lc).candidate;
    return [main, ...ctx.custom.candidates.filter((c) => c.site.id !== landing.id)];
  }
  const main = evaluateLanding(landing, lc).candidate;
  const others = sortCandidates(alternates.map((a) => evaluateLanding(a, lc).candidate), ctx.filters.difficulty);
  return [main, ...others];
}

// ───────────────────────────── assemblage d'un plan ─────────────────────────────

function buildPlan(ctx: BuildCtx, cand: Candidate, c: Conditions, planLevel: Difficulty, rank: number): FlightPlan {
  const { site, landing, target, filters, horizon, now } = ctx;
  const level = filters.difficulty;
  const [lo, hi] = cand.natural;
  const { duration_min_minutes: mn, duration_max_minutes: mx } = filters;
  const est = Math.round(clamp((Math.max(lo, mn) + Math.min(hi, mx)) / 2, lo, hi));
  const route = buildRoute(cand.variant, ctx, c, est, level);
  const pts = route.builder.pts;
  const landingWind = c.landingWx.wind_10m;
  const finesseAir = filters.wing_glide_ratio * RULES.glideK[level];
  const alternates = ctx.custom ? ctx.custom.candidates.slice(1, 4).map((c) => c.site) : nearbyLandings(pts, landing);
  // Finesse requise = PIRE cas (CDC, règle backend) : (a) déco → atterro principal à l'altitude du déco,
  // (b) chaque point de route à son altitude prévue → atterro identifié le plus proche.
  const legRatio = (from: P3, to: Site) => {
    const margin = arrivalMargin(level, site.elevation_m - to.elevation_m);
    const h = from.alt - (to.elevation_m + margin);
    const d = haversineKm(from, to) * 1000;
    const bearing = bearingDeg(from, to);
    // composante du vent sur la tranche, positive = vent arrière (CDC §2.3)
    const tail = -landingWind.speed_kmh * Math.cos(((bearing - landingWind.direction_deg) * Math.PI) / 180);
    const avail = Math.max(0, (finesseAir * (RULES.airSpeedKmh + tail)) / RULES.airSpeedKmh);
    return { req: h > 0 ? d / h : 99, avail };
  };
  let worst = legRatio({ lat: site.lat, lon: site.lon, alt: site.elevation_m }, landing);
  let allOk = worst.req <= worst.avail;
  for (const p of pts) {
    // CDC §5.4 : il suffit qu'UN atterro identifié soit dans le cône → meilleur atterro pour ce point
    if (haversineKm(p, landing) < 0.6) continue; // approche finale : PTU et dernier virage
    const options = [landing, ...alternates].filter((l) => haversineKm(p, l) >= 0.3).map((l) => legRatio(p, l));
    if (options.length === 0) continue;
    const r = options.reduce((best, o) => (o.req / Math.max(0.1, o.avail) < best.req / Math.max(0.1, best.avail) ? o : best));
    if (r.req > r.avail) allOk = false;
    if (r.req > worst.req) worst = r;
  }
  const required = worst.req;
  const available = worst.avail;
  const glide = { required_ratio: Math.round(required * 10) / 10, available_ratio: Math.round(available * 10) / 10, margin_ok: allOk };

  // créneau
  const roundMin = horizonToMinutes(horizon) >= 1440 ? 60 : 15;
  const start = roundTo(new Date(target.getTime() - 30 * MIN), roundMin);
  const limits = [target.getTime() + 90 * MIN];
  if (c.sunset) limits.push(c.sunset.getTime() - 30 * MIN - est * MIN);
  if (cand.thermal_usage !== "none" && c.thermals.convection_end) limits.push(new Date(c.thermals.convection_end).getTime() + 30 * MIN - est * MIN);
  let end = roundTo(new Date(Math.min(...limits)), roundMin);
  if (end.getTime() < start.getTime() + 15 * MIN) end = new Date(start.getTime() + 15 * MIN);
  // règle expert : posé avant = min(fin du créneau + durée, coucher du soleil)
  const landBefore = new Date(Math.min(end.getTime() + est * MIN, c.sunset ? c.sunset.getTime() : Infinity));

  // balises rattachées (déco à l'heure cible, atterros à l'heure d'arrivée)
  const horizonMin = horizonToMinutes(horizon);
  const beacons = nearbyBeacons(site, now);
  const minutesToTarget = (target.getTime() - now.getTime()) / MIN;
  const readings = stationReadings(
    [
      { role: "takeoff", site, forecast: c.wx, minutesAhead: minutesToTarget },
      { role: "landing", site: landing, forecast: c.landingWx, minutesAhead: minutesToTarget + est },
      ...alternates.map((a) => ({ role: "alternate_landing" as const, site: a, forecast: c.landingWx, minutesAhead: minutesToTarget + est })),
    ],
    [...beacons, ...mockBeacons(now).filter((b) => !beacons.some((x) => x.id === b.id) && [landing, ...alternates].some((l) => haversineKm(b, l) <= 5))],
    now,
  );
  const repTakeoff = readings.filter((r) => r.site_role === "takeoff" && r.representative);
  const repLanding = readings.filter((r) => r.site_role === "landing" && r.representative);

  // risques
  const checks = checkLevel(level, site, c, new Date(target.getTime() + est * MIN));
  const risks: Risk[] = [];
  risks.push({ code: "MOCK_DATA", level: "caution", title: "Démo hors-ligne : données synthétiques", detail: "Plan calculé sur une météo synthétique et des sites approximatifs : NE PAS utiliser pour voler." });
  for (const m of [...checks.marginal, ...cand.extraMarginal]) risks.push({ code: m.code, level: "caution", title: m.text, detail: "Dans la zone 80-100 % du seuil de ton niveau : rester vigilant, prévoir un plan B." });
  const airspaces = airspaceWarnings(pts);
  for (const a of airspaces) {
    if (a.intersects_route) risks.push({ code: "AIRSPACE", level: "danger", title: `Route dans ${a.name}`, detail: `Classe ${a.airspace_class}, ${fmtAlt(a.floor_m)} – ${fmtAlt(a.ceiling_m)} : pénétration interdite sans clairance.` });
    else if (a.min_distance_km === 0 && a.floor_m > 0) risks.push({ code: "ALTITUDE_LIMIT", level: "caution", title: `Plancher ${a.name} : ${fmtAlt(a.floor_m)}`, detail: `La route passe sous cet espace : rester sous ${fmtAlt(a.floor_m - 100)} dans ce secteur (plafond thermique prévu ${fmtAlt(c.wx.thermal_ceiling_m)}).` });
    else if (a.min_distance_km < 1) risks.push({ code: "AIRSPACE", level: "caution", title: `${a.name} à ${formatNumber(a.min_distance_km, 1)} km`, detail: `Classe ${a.airspace_class}, plancher ${fmtAlt(a.floor_m)} : garder 1 km de marge latérale.` });
  }
  risks.push(...sensitiveRisks(pts, target));
  if (!glide.margin_ok) risks.push({ code: "GLIDE_MARGIN", level: "danger", title: "Marge de finesse insuffisante", detail: `Finesse requise ${formatNumber(glide.required_ratio, 1)} pour ${formatNumber(glide.available_ratio, 1)} disponible vers ${landing.name}.` });
  const valleyBreeze = landingWind.speed_kmh >= 12 && new Date(target.getTime() + est * MIN).getUTCHours() >= 11;
  if (valleyBreeze) risks.push({ code: "VALLEY_BREEZE", level: "info", title: `Brise à l'atterro : ${degToCardinalFr(landingWind.direction_deg)} ${landingWind.speed_kmh} km/h`, detail: "Brise de vallée/lac établie l'après-midi : approche face au vent, arriver haut." });
  if (c.wx.thermal_strength_ms > 2 && cand.thermal_usage !== "none") risks.push({ code: "STRONG_THERMALS", level: "info", title: "Thermiques soutenus", detail: `Vario ≈ ${formatNumber(c.wx.thermal_strength_ms, 1, 1)} m/s (pics ≈ ${formatNumber(c.wx.thermal_strength_ms * 2, 0)} m/s) : air turbulent près du relief.` });
  if (c.thermals.overdevelopment_risk !== "low") risks.push({ code: "OVERDEVELOPMENT", level: c.thermals.overdevelopment_risk === "high" ? "caution" : "info", title: `Surdéveloppement ${c.thermals.overdevelopment_risk === "high" ? "probable" : "possible"} dans la journée`, detail: "Surveiller les cumulus qui gonflent ; être posé avant les premières averses." });
  if (site.restrictions) risks.push({ code: site.status === "restricted" ? "SITE_RESTRICTED" : "SITE_RESTRICTED", level: site.status === "restricted" ? "caution" : "info", title: "Consignes du site", detail: site.restrictions });
  if (horizonMin <= 120) risks.push({ code: "STALE_BEACONS", level: "info", title: "Vérifier les balises au déco", detail: "Moyenne et rafales sur 10 min, comparer déco et atterro avant de décoller." });
  if (horizonMin <= 120 && repLanding.length === 0) {
    const legalHour = Number(new Intl.DateTimeFormat("fr-FR", { hour: "numeric", hour12: false, timeZone: "Europe/Paris" }).format(new Date(target.getTime() + est * MIN)));
    risks.push({
      code: "NO_LANDING_BEACON",
      level: legalHour >= 12 && legalHour < 18 ? "caution" : "info",
      title: "Pas de balise représentative à l'atterro",
      detail: "Vent d'atterro estimé par le modèle (brise comprise) : regarde la manche à air et les drapeaux en vol, ou demande le vent par radio à un pilote posé.",
    });
  }
  for (const r of [...repTakeoff, ...repLanding]) {
    const t = r.beacon.trend;
    if (!t || horizonMin > 120) continue;
    const inc = (t.speed_change_kmh * 60) / Math.max(1, t.window_min);
    if (inc >= 6) {
      const where = r.site_role === "takeoff" ? "au déco" : "à l'atterro";
      risks.push({
        code: "WIND_INCREASING",
        level: inc >= 10 ? "danger" : "caution",
        title: `Vent qui forcit ${where} : ${formatSpeedTrend(t)}`,
        detail: `${r.beacon.name} : la moyenne sur 10 min augmente ; ${r.site_role === "takeoff" ? "décoller tôt ou attendre l'accalmie" : "la brise forcit, arriver haut et prévoir une approche face au vent"}.`,
      });
    }
  }
  if (site.source === "user") {
    risks.push({
      code: "FREE_TAKEOFF",
      level: level === "beginner" ? "danger" : level === "intermediate" ? "caution" : "info",
      title: "Décollage libre (hors site officiel)",
      detail: `Contrôles obligatoires : ${FREE_TAKEOFF_CHECKS.join(" ")}`,
    });
  }
  const landingKind = landing.landing_kind ?? (landing.official ? "official" : "community");
  if (landingKind !== "official") {
    risks.push({
      code: landingKind === "field" ? "DETECTED_FIELD" : "UNOFFICIAL_LANDING",
      level: landingKind === "field" ? "danger" : level === "intermediate" ? "caution" : "info",
      title: landingKind === "field" ? `Atterro principal = champ détecté : ${landing.name}` : `Atterro non officiel : ${landing.name}`,
      detail: UNOFFICIAL_WARNING[landingKind],
    });
  }
  const fieldAlt = alternates.filter((a) => a.landing_kind === "field");
  if (fieldAlt.length) {
    risks.push({ code: "DETECTED_FIELD", level: "caution", title: `Secours sur champ détecté : ${fieldAlt.map((a) => a.name).join(", ")}`, detail: UNOFFICIAL_WARNING.field });
  }
  const order = { danger: 0, caution: 1, info: 2 } as const;
  risks.sort((a, b) => order[a.level] - order[b.level]);

  const confidence = confidenceFor(horizon, c.wx);
  const items = scoreItems(ctx, c, cand, est, glide.required_ratio, glide.available_ratio, confidence, level);
  const { score, flyability } = verdict(items, confidence, horizon, risks);

  // météo
  const timeline: WeatherSnapshot[] = [];
  for (let h = -3; h <= 3; h++) {
    const t = new Date(roundTo(target, 60).getTime() + h * 3_600_000);
    timeline.push(weatherAt(site.lat, site.lon, site.elevation_m, t, { facingDeg: facingOf(site.orientations), key: site.id }));
  }
  const takeoffWx = { ...c.wx };
  const landingWxOut = { ...c.landingWx };
  if (horizonMin <= 120) {
    takeoffWx.nowcast_correction = nowcastFrom(repTakeoff, c.wx);
    landingWxOut.nowcast_correction = nowcastFrom(repLanding, c.landingWx);
  }

  const durationTxt = formatDuration(est);
  const title = `${site.name} → ${landing.name} · ${VARIANT_TITLE[cand.variant]} ${durationTxt}`;
  const flyTxt = flyability === "go" ? "GO" : flyability === "marginal" ? "LIMITE" : "NO-GO";
  const sc = scenarioFor(target);
  const aloft = (a: number) => aloftAt(c.wx, a);
  const fmtAloft = (a: number) => {
    const w = aloft(a);
    return w ? `${w.speed} km/h de ${degToCardinalFr(w.dir)} à ${fmtAlt(a)}` : null;
  };
  const conv = c.thermals;
  const technique = c.speed >= 12 ? "face voile conseillé (vent ≥ 12 km/h)" : "dos voile possible (vent faible)";
  const summary =
    cand.variant === "cross"
      ? `Triangle de ${Math.round(route.distanceKm)} km en ${durationTxt} sous un plafond utile de ${fmtAlt(c.ceiling)} ; premier côté face au vent.`
      : cand.variant === "soaring"
        ? `Soaring dans un vent de ${Math.round(c.speed)} km/h bien établi, ${durationTxt} environ puis atterrissage à ${landing.name}.`
        : cand.variant === "thermal"
          ? `Vol local en thermique (≈ ${formatNumber(c.wx.thermal_strength_ms, 1, 1)} m/s) autour du déco, ${durationTxt}, en restant dans le cône de finesse de ${landing.name}.`
          : `Plouf de ${durationTxt} en air ${c.wx.thermal_strength_ms > 1 ? "thermique" : "calme"} jusqu'à ${landing.name}.`;

  const beaconLine = (role: "takeoff" | "landing") => {
    const r = (role === "takeoff" ? repTakeoff : repLanding)[0];
    if (!r) return null;
    const b = r.beacon;
    const speed = b.wind_speed_kmh;
    if (speed === null) return null;
    const dir = b.wind_direction_deg !== null ? `${degToCardinalFr(b.wind_direction_deg)} ` : "";
    const trend = b.trend ? `, tendance ${formatSpeedTrend(b.trend)}` : "";
    return `${role === "takeoff" ? "déco" : "atterro"} ${dir}${Math.round(speed)} km/h${b.wind_gust_kmh !== null ? ` (raf. ${Math.round(b.wind_gust_kmh)})` : ""}${trend}`;
  };
  const beaconBullet = (() => {
    if (horizonMin > 60) return null;
    const parts = [beaconLine("takeoff"), beaconLine("landing")].filter(Boolean);
    const ages = [...repTakeoff, ...repLanding].map((r) => Math.round((now.getTime() - new Date(r.beacon.observed_at).getTime()) / MIN));
    const head = parts.length ? `Balises (il y a ${Math.min(...ages)} min) : ${parts.join(" ; ")}.` : "Balises : aucune balise représentative au déco ni à l'atterro.";
    return repLanding.length ? head : `${head} Pas de balise à l'atterro : regarde la manche à air et les drapeaux en vol, ou demande le vent par radio à un pilote posé.`;
  })();
  const freeTakeoffText = site.source === "user" ? ` Décollage libre : ${FREE_TAKEOFF_CHECKS.join(" ")}` : "";
  const landingWarnText = landingKind !== "official" ? ` ${UNOFFICIAL_WARNING[landingKind]}` : "";

  const briefing = [
    ...(beaconBullet ? [beaconBullet] : []),
    `⚠ DÉMONSTRATION — ${flyTxt} pour ${difficultyLabel(planLevel).toLowerCase()} (difficulté estimée), confiance ${Math.round(confidence * 100)} %. Données synthétiques : ne pas utiliser pour voler.`,
    `Créneau : décoller entre ${fmtT(start)} et ${fmtT(end)}, être posé avant ${fmtT(landBefore)}${c.sunset ? ` (coucher du soleil ${fmtT(c.sunset)})` : ""}.`,
    `Situation : ${sc.label.toLowerCase()}.`,
    `Vent au déco : ${degToCardinalFr(c.dir)} ${Math.round(c.speed)} km/h (rafales ${Math.round(c.gust)}) ; ${[fmtAloft(1500), fmtAloft(2000), fmtAloft(3000)].filter(Boolean).join(", ")} ; à l'atterro ${degToCardinalFr(landingWind.direction_deg)} ${landingWind.speed_kmh} km/h à l'arrivée.`,
    conv.convection_start
      ? `Aérologie : thermiques de ${fmtT(new Date(conv.convection_start))} à ${conv.convection_end ? fmtT(new Date(conv.convection_end)) : "?"}, pic vers ${conv.peak_time ? fmtT(new Date(conv.peak_time)) : "?"} (≈ ${formatNumber(conv.peak_strength_ms, 1, 1)} m/s) ; plafond utile ${fmtAlt(c.ceiling)}${c.wx.cloud_base_m ? `, base des cumulus ${fmtAlt(c.wx.cloud_base_m)}` : ", thermiques bleus"} ; surdéveloppement ${c.overdev === "low" ? "peu probable" : c.overdev === "moderate" ? "possible" : "probable"}.`
      : "Aérologie : pas de convection exploitable, air calme.",
    `Décollage : orientations ${site.orientations.map(compassFr).join(", ")} ; ${technique}.${site.restrictions && site.source !== "user" ? ` Consignes : ${site.restrictions}` : ""}${freeTakeoffText}`,
    `Itinéraire : ${route.waypoints.filter((w) => w.type !== "takeoff").map((w) => w.name).join(" → ")} → ${landing.name} (${formatNumber(route.distanceKm, 1)} km).${route.decision.length ? " Points de décision : " + route.decision.join(" ") : ""}`,
    `Atterrissage : ${landing.name} (${fmtAlt(landing.elevation_m)}), approche face au ${degToCardinalFr(landingWind.direction_deg)}, PTU côté sous le vent ; finesse requise ${formatNumber(glide.required_ratio, 1)} pour ${formatNumber(glide.available_ratio, 1)} de finesse de calcul.${landingWarnText}`,
    airspaces.length
      ? `Espaces aériens : ${airspaces.map((a) => `${a.name} (${a.airspace_class}, plancher ${fmtAlt(a.floor_m)}, à ${formatNumber(a.min_distance_km, 1)} km)`).join(" ; ")}. Vérifier NOTAM / SUP AIP.`
      : "Espaces aériens : rien à moins de 8 km de la route (vérifier NOTAM / SUP AIP).",
    `Logistique : fréquence vol libre 143,9875 MHz, urgence 112 ; prévoir 15 à 30 min de préparation au déco.`,
  ];

  const checklist = [
    "Météo revue il y a moins d'1 h (balises déco + atterro), plan B connu",
    "Espaces aériens et NOTAM / activations (R, ZRT, AZBA) vérifiés pour le jour",
    "Parachute de secours : poignée accessible et verrouillée, aiguilles en place, repliage < 12 mois",
    "Sellette : cuissardes, ventrale réglée, mousquetons verrouillés, accélérateur connecté et libre",
    "Casque jugulaire fermée, gants, lunettes, vêtements adaptés au plafond",
    "Voile : visite prévol, suspentes démêlées, élévateurs non vrillés, freins libres",
    "Instruments chargés, tâche XCTrack / GPX chargée, live tracking activé, téléphone chargé",
    "Radio allumée sur 143,9875 MHz, test de réception",
    "Eau, nourriture, kit de secours / couverture de survie",
    "Plan de vol communiqué à un proche ou au chauffeur (site, route, heure de retour)",
    "Contrôle final au déco : attaches, casque, suspentes, voile, vent et espace devant libres",
  ];

  const id = encodePlanId({
    siteId: site.id,
    variant: cand.variant,
    target,
    horizon,
    filters,
    rank,
    custom: ctx.custom ? { takeoff: ctx.custom.takeoff, policy: ctx.custom.policy } : undefined,
  });
  for (const a of alternates) {
    route.waypoints.push({ name: a.name, lat: a.lat, lon: a.lon, altitude_m: a.elevation_m, type: "alternate_landing", radius_m: 200, eta_min: null, note: "Atterrissage de secours identifié" });
  }
  route.waypoints.splice(route.waypoints.length - alternates.length, 0, {
    name: landing.name,
    lat: landing.lat,
    lon: landing.lon,
    altitude_m: landing.elevation_m,
    type: "landing",
    radius_m: 300,
    eta_min: est,
    note: `Approche face au ${degToCardinalFr(landingWind.direction_deg)}`,
  });

  return {
    id,
    rank,
    score,
    flyability,
    difficulty: planLevel,
    flight_type: cand.type,
    thermal_usage: cand.thermal_usage,
    title,
    summary,
    target_time: target.toISOString(),
    window: { start: start.toISOString(), end: end.toISOString(), latest_landing: landBefore.toISOString() },
    sun: (() => {
      const st = sunTimes(site.lat, site.lon, target);
      return { sunrise: st?.sunrise.toISOString() ?? null, sunset: st?.sunset.toISOString() ?? null };
    })(),
    takeoff: site,
    landing,
    alternate_landings: alternates,
    landing_analysis: landingAnalysisFor(ctx, landing, alternates, est),
    waypoints: route.waypoints,
    route: { type: "LineString", coordinates: route.builder.coordinates() },
    distance_km: Math.round(route.distanceKm * 10) / 10,
    est_duration_min: est,
    max_altitude_m: Math.round(Math.max(...pts.map((p) => p.alt))),
    glide,
    weather: { takeoff: takeoffWx, landing: landingWxOut, timeline },
    thermals: c.thermals,
    sounding: soundingAt(site.lat, site.lon, target),
    beacons_nearby: beacons,
    station_readings: readings,
    airspaces,
    risks,
    briefing,
    checklist,
    score_breakdown: items,
    confidence,
    sources: MOCK_SOURCE(now),
    links: { gpx: `/api/plans/${id}/gpx`, xctsk: `/api/plans/${id}/xctsk` },
  };
}

// ───────────────────────────── points d'entrée ─────────────────────────────

const TYPE_MIN_LEVEL: Record<Variant, Difficulty> = { plouf: "beginner", thermal: "beginner", soaring: "beginner", cross: "intermediate" };

function planLevelFor(site: Site, cand: Candidate, c: Conditions, ctx: BuildCtx, est: number): Difficulty | null {
  const floor = maxLevel(site.difficulty ?? "intermediate", TYPE_MIN_LEVEL[cand.variant], cand.minLevel);
  for (const L of LEVELS.slice(lvl(floor))) {
    if (checkLevel(L, site, c, new Date(ctx.target.getTime() + est * MIN)).nogo.length === 0) {
      if (cand.thermal_usage !== "none" && c.wx.thermal_strength_ms > RULES.thermalMax[L]) continue;
      return L;
    }
  }
  return null;
}

function normalizeFilters(f: PlanFilters): BuildCtx["filters"] {
  return {
    duration_min_minutes: f.duration_min_minutes,
    duration_max_minutes: f.duration_max_minutes,
    difficulty: f.difficulty,
    thermals: f.thermals,
    wing_glide_ratio: f.wing_glide_ratio ?? 8.5,
  };
}

const formatReason = (f: Finding) => (f.code ? `[${f.code}] ${f.text}` : f.text);

/** Décollage libre : refus au niveau élève, recherche des atterros, atterro principal compatible avec le niveau. */
function customLandings(
  site: Site,
  takeoff: CustomTakeoff,
  policy: LandingPolicy,
  filters: BuildCtx["filters"],
  target: Date,
): { reason: string } | { custom: NonNullable<BuildCtx["custom"]>; warnings: string[] } {
  if (filters.difficulty === "beginner") return { reason: "[FREE_TAKEOFF] Décollage libre jamais proposé au niveau élève : choisis un site officiel encadré." };
  const search = searchLandings({ takeoff: site, level: filters.difficulty, glide: filters.wing_glide_ratio, time: target }, policy);
  const main = search.candidates.find((c) => canBeMain(c.kind, filters.difficulty));
  if (!main) {
    return {
      reason: search.candidates.length
        ? "[GLIDE_MARGIN] Aucun atterro principal utilisable à ton niveau dans le cône de finesse (seulement des secours non officiels)"
        : "[GLIDE_MARGIN] Aucun atterrissage atteignable avec la marge de sécurité depuis ce point",
    };
  }
  return {
    custom: { takeoff, policy, candidates: [main, ...search.candidates.filter((c) => c !== main)] },
    warnings: search.warnings,
  };
}

/** Simulation de POST /api/plans. */
export function mockPlans(req: PlanRequest, now: Date = new Date()): PlanResponse {
  const zoneError = validateZone(req.zone);
  if (zoneError) throw new ApiError(422, zoneError, [{ loc: ["body", "zone"], msg: `Value error, ${zoneError}` }]);
  if (req.filters.duration_min_minutes > req.filters.duration_max_minutes)
    throw new ApiError(422, "La durée minimale dépasse la durée maximale.", [{ loc: ["body", "filters"], msg: "Value error, La durée minimale dépasse la durée maximale." }]);
  const reference = req.reference_time ? new Date(req.reference_time) : now;
  const target = targetTimeFromHorizon(reference, req.horizon);
  const filters = normalizeFilters(req.filters);
  const types = new Set<FlightType>(req.filters.flight_types?.length ? req.filters.flight_types : ["local", "ridge_soaring", "cross_country"]);
  const maxResults = clamp(req.filters.max_results ?? 5, 1, 20);

  const customMode = req.mode === "custom_takeoff";
  const ct = req.custom_takeoff;
  if (customMode && (!ct || !Number.isFinite(ct.lat) || !Number.isFinite(ct.lon)))
    throw new ApiError(422, "Point de décollage requis en mode décollage libre.", [{ loc: ["body", "custom_takeoff"], msg: "Value error, custom_takeoff requis si mode = custom_takeoff" }]);
  const policy: LandingPolicy = customMode ? (req.filters.landing_policy ?? "official_only") : "official_only";
  const takeoffs = customMode
    ? [userTakeoffSite(ct!)]
    : MOCK_SITES.filter((s) => (s.kind === "takeoff" || s.kind === "both") && zoneContains(req.zone, s));
  const warnings: string[] = [
    "Démo hors-ligne : données synthétiques (météo, sites, balises, espaces aériens approximatifs). Ne pas utiliser pour voler.",
  ];
  if (customMode) warnings.push("Décollage libre : contrôles obligatoires sur place (autorisation, reconnaissance à pied, manche à air, atterro repéré).");
  if (horizonToMinutes(req.horizon) >= 1440) warnings.push("Horizon long : tendance seulement, créneaux arrondis à l'heure. À reconfirmer la veille et le matin.");
  if (takeoffs.length === 0 && !customMode)
    warnings.push("Aucun décollage de démonstration dans cette zone. Essayez Annecy, Chamonix, Saint-Hilaire, Saint-André, la Dune du Pilat, le Puy de Dôme ou Millau.");

  const candidates: { plan: FlightPlan; siteId: string }[] = [];
  const rejected: PlanResponse["rejected"] = [];

  for (const site of takeoffs) {
    let landing: Site | undefined;
    let custom: BuildCtx["custom"];
    if (site.source === "user") {
      const found = customLandings(site, ct!, policy, filters, target);
      if ("reason" in found) {
        rejected.push({ site, reasons: [found.reason] });
        continue;
      }
      custom = found.custom;
      landing = custom.candidates[0]!.site;
      for (const w of found.warnings) if (!warnings.includes(w)) warnings.push(w);
    } else {
      landing = site.associated_landing_ids.map((id) => MOCK_SITES_BY_ID[id]).find((s): s is Site => !!s);
    }
    if (!landing) {
      rejected.push({ site, reasons: [site.status === "closed" ? "[SITE_CLOSED] Site fermé" : "Aucun atterrissage officiel associé connu"] });
      continue;
    }
    const ctx: BuildCtx = { site, landing, target, filters, horizon: req.horizon, now, custom };
    const c0 = computeConditions(site, landing, target, 30);
    const base = checkLevel(filters.difficulty, site, c0, new Date(target.getTime() + 30 * MIN));
    const absolute = base.nogo.filter((f) => ["SITE_CLOSED", "RAIN", "THUNDERSTORM", "OVERDEVELOPMENT", "LOW_CLOUD_BASE", "LEE_SIDE", "SUNSET"].includes(f.code));
    if (absolute.length) {
      rejected.push({ site, reasons: absolute.map(formatReason) });
      continue;
    }
    const { list, notes } = candidatesFor(ctx, c0, filters.difficulty);
    const reasons: Finding[] = [...notes];
    const accepted: { cand: Candidate; level: Difficulty; est: number; c: Conditions }[] = [];
    for (const cand of list) {
      if (!types.has(cand.type)) continue;
      const { duration_min_minutes: mn, duration_max_minutes: mx } = filters;
      const [lo, hi] = cand.natural;
      const est = Math.round(clamp((Math.max(lo, mn) + Math.min(hi, mx)) / 2, lo, hi));
      const gap = est < mn ? (mn - est) / mn : est > mx ? (est - mx) / mx : 0;
      if (gap > 0.5) {
        reasons.push({ code: "", text: `${VARIANT_TITLE[cand.variant][0]!.toUpperCase()}${VARIANT_TITLE[cand.variant].slice(1)} possible seulement ${formatDuration(lo)}${hi > lo + 5 ? ` – ${formatDuration(hi)}` : ""} : hors de la durée souhaitée` });
        continue;
      }
      const c = computeConditions(site, landing, target, est);
      const level = planLevelFor(site, cand, c, ctx, est);
      if (!level) {
        reasons.push(...checkLevel("expert", site, c, new Date(target.getTime() + est * MIN)).nogo);
        continue;
      }
      if (lvl(level) > lvl(filters.difficulty)) {
        const own = checkLevel(filters.difficulty, site, c, new Date(target.getTime() + est * MIN)).nogo;
        reasons.push(...own);
        reasons.push({ code: "", text: `${VARIANT_TITLE[cand.variant]} : conditions trop fortes pour ton niveau, OK pour ${difficultyLabel(level).toLowerCase()}` });
        continue;
      }
      accepted.push({ cand, level, est, c });
    }
    if (accepted.length === 0) {
      const uniq = Array.from(new Set(reasons.map(formatReason)));
      rejected.push({ site, reasons: uniq.length ? uniq : ["Aucun type de vol compatible avec les critères"] });
      continue;
    }
    for (const a of accepted) candidates.push({ plan: buildPlan(ctx, a.cand, a.c, a.level, 0), siteId: site.id });
  }

  // tri + diversité : au plus 2 plans par déco
  candidates.sort((a, b) => b.plan.score - a.plan.score);
  const perSite = new Map<string, number>();
  const plans: FlightPlan[] = [];
  for (const cand of candidates) {
    const n = perSite.get(cand.siteId) ?? 0;
    if (n >= 2) continue;
    perSite.set(cand.siteId, n + 1);
    plans.push(cand.plan);
    if (plans.length >= maxResults) break;
  }
  const ranked = plans.map((p, i) => withRank(p, i + 1));
  if (ranked.length === 0 && takeoffs.length > 0) warnings.push("Aucun vol ne passe les filtres de sécurité pour ces critères : voir les sites écartés.");
  if (ranked.length > 0 && ranked.every((p) => p.flyability !== "go")) warnings.push("Aucun plan franchement volable : conditions limites, sois prêt à renoncer.");

  return {
    request_id: `demo-${Math.floor(hash01(now.getTime()) * 1e8).toString(36)}`,
    generated_at: now.toISOString(),
    target_time: target.toISOString(),
    horizon: req.horizon,
    zone: req.zone,
    data_mode: "mock",
    plans: ranked,
    rejected,
    warnings,
  };
}

function withRank(plan: FlightPlan, rank: number): FlightPlan {
  const key = decodePlanId(plan.id);
  const id = key ? encodePlanId({ ...key, rank }) : plan.id;
  return { ...plan, rank, id, links: { gpx: `/api/plans/${id}/gpx`, xctsk: `/api/plans/${id}/xctsk` } };
}

/** Simulation de GET /api/plans/{id} : le plan de démo est recalculé depuis son identifiant. */
export function mockPlanById(id: string, now: Date = new Date()): FlightPlan {
  const key = decodePlanId(id);
  const site = key?.custom ? userTakeoffSite(key.custom.takeoff) : key ? MOCK_SITES_BY_ID[key.siteId] : undefined;
  let landing: Site | undefined;
  let custom: BuildCtx["custom"];
  if (key?.custom && site) {
    const found = customLandings(site, key.custom.takeoff, key.custom.policy, key.filters, key.target);
    if ("custom" in found) {
      custom = found.custom;
      landing = custom.candidates[0]!.site;
    }
  } else landing = site?.associated_landing_ids.map((x) => MOCK_SITES_BY_ID[x]).find((s): s is Site => !!s);
  if (!key || !site || !landing) throw new ApiError(404, "Plan de vol introuvable (expiré ou identifiant invalide).");
  const ctx: BuildCtx = { site, landing, target: key.target, filters: key.filters, horizon: key.horizon, now, custom };
  const c0 = computeConditions(site, landing, key.target, 30);
  const { list } = candidatesFor(ctx, c0, key.filters.difficulty);
  const cand =
    list.find((x) => x.variant === key.variant) ??
    ({ variant: key.variant, type: key.variant === "cross" ? "cross_country" : key.variant === "soaring" ? "ridge_soaring" : "local", thermal_usage: key.variant === "plouf" ? "none" : "optional", natural: [20, 90], minLevel: "beginner", extraMarginal: [] } satisfies Candidate);
  const [lo, hi] = cand.natural;
  const est = Math.round(clamp((Math.max(lo, key.filters.duration_min_minutes) + Math.min(hi, key.filters.duration_max_minutes)) / 2, lo, hi));
  const c = computeConditions(site, landing, key.target, est);
  const level = planLevelFor(site, cand, c, ctx, est) ?? "expert";
  const plan = buildPlan(ctx, cand, c, level, key.rank);
  return { ...plan, id, rank: key.rank, links: { gpx: `/api/plans/${id}/gpx`, xctsk: `/api/plans/${id}/xctsk` } };
}

