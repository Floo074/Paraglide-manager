/**
 * Météo SYNTHÉTIQUE déterministe pour le mode démonstration.
 *
 * Trois scénarios selon le jour (aujourd'hui / demain / après-demain) :
 *  0. anticyclonique, brise de NO faible, cumulus plats → bonne journée thermique ;
 *  1. flux de nord modéré (bise faible) et brise de lac de N l'après-midi → vent arrière sur les planés vers le S
 *     (Forclaz → Doussard : arrivée haute), vent fort en altitude pour les élèves ;
 *  2. dégradation orageuse l'après-midi (CAPE élevée, pluie) → no-go l'après-midi.
 * Cycle diurnal basé sur la position réelle du soleil, brises de pente orientées selon le déco.
 * Les valeurs sont plausibles mais FICTIVES.
 */
import type {
  ForecastGridResponse,
  GridLayer,
  SoundingLevel,
  WeatherSnapshot,
  WindLevel,
} from "../api/types";
import { solarElevationDeg, solarHour, sunTimes } from "../utils/sun";
import { compassToDeg, normalizeDeg, standardPressureHpa } from "../utils/units";
import { haversineKm } from "../utils/geo";
import { MOCK_SITES, CROSS_TURNPOINTS } from "./sites";

interface Scenario {
  label: string;
  levels: { alt: number; speed: number; dir: number }[]; // alt relative : 0 = sol de vallée
  tMin: number;
  tMax: number;
  spreadMin: number;
  spreadMax: number;
  blhMax: number;
  thermalMax: number;
  capeMax: number;
  rainFromSolarHour: number | null;
  rainMmH: number;
  cloud: number;
  lowCloud: number;
  stableAloft: boolean;
}

export const SCENARIOS: Scenario[] = [
  {
    label: "Anticyclonique, brise de NO faible, cumulus plats",
    levels: [
      { alt: 0, speed: 6, dir: 330 },
      { alt: 1500, speed: 11, dir: 320 },
      { alt: 2500, speed: 17, dir: 310 },
      { alt: 3000, speed: 22, dir: 300 },
      { alt: 4000, speed: 30, dir: 290 },
    ],
    tMin: 7,
    tMax: 19,
    spreadMin: 4,
    spreadMax: 17,
    blhMax: 2000,
    thermalMax: 2.4,
    capeMax: 140,
    rainFromSolarHour: null,
    rainMmH: 0,
    cloud: 15,
    lowCloud: 5,
    stableAloft: true,
  },
  {
    label: "Flux de nord modéré (bise faible), brise de lac de N l'après-midi",
    levels: [
      // directions au-delà de 360° : interpolation sans passer par le S (normalisées ensuite)
      { alt: 0, speed: 16, dir: 365 },
      { alt: 1500, speed: 19, dir: 360 },
      { alt: 2500, speed: 25, dir: 352 },
      { alt: 3000, speed: 30, dir: 345 },
      { alt: 4000, speed: 38, dir: 335 },
    ],
    tMin: 6,
    tMax: 15,
    spreadMin: 4,
    spreadMax: 13,
    blhMax: 1500,
    thermalMax: 1.9,
    capeMax: 40,
    rainFromSolarHour: null,
    rainMmH: 0,
    cloud: 25,
    lowCloud: 10,
    stableAloft: true,
  },
  {
    label: "Dégradation orageuse l'après-midi",
    levels: [
      { alt: 0, speed: 7, dir: 205 },
      { alt: 1500, speed: 14, dir: 215 },
      { alt: 2500, speed: 19, dir: 222 },
      { alt: 3000, speed: 23, dir: 228 },
      { alt: 4000, speed: 30, dir: 235 },
    ],
    tMin: 11,
    tMax: 22,
    spreadMin: 3,
    spreadMax: 12,
    blhMax: 2000,
    thermalMax: 2.8,
    capeMax: 1500,
    rainFromSolarHour: 14.5,
    rainMmH: 2.4,
    cloud: 60,
    lowCloud: 25,
    stableAloft: false,
  },
];

/** Hachage déterministe → [0, 1). */
export function hash01(...parts: (string | number)[]): number {
  let h = 2166136261;
  const str = parts.join("|");
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 100000) / 100000;
}

const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));
const r1 = (v: number) => Math.round(v * 10) / 10;

let referenceNow: Date = new Date();
/** Permet aux tests de figer "aujourd'hui". */
export function setMockNow(d: Date): void {
  referenceNow = d;
}

export function scenarioIndexFor(time: Date): number {
  const d0 = new Date(referenceNow);
  d0.setHours(0, 0, 0, 0);
  return clamp(Math.floor((time.getTime() - d0.getTime()) / 86_400_000), 0, 2);
}

export function scenarioFor(time: Date): Scenario {
  return SCENARIOS[scenarioIndexFor(time)]!;
}

/** Altitude du fond de vallée de référence : atterrissage connu le plus bas à < 35 km. */
export function valleyFloor(lat: number, lon: number): number {
  let best: number | null = null;
  for (const s of MOCK_SITES) {
    if (s.kind === "takeoff") continue;
    if (haversineKm({ lat, lon }, s) > 35) continue;
    if (best === null || s.elevation_m < best) best = s.elevation_m;
  }
  return best ?? 400;
}

/** Relief fictif : bosses gaussiennes autour des décos et sommets connus. */
export function terrainAt(lat: number, lon: number): number {
  const floor = valleyFloor(lat, lon);
  let h = floor;
  const bumps: { lat: number; lon: number; alt: number }[] = [];
  for (const s of MOCK_SITES) if (s.kind !== "landing") bumps.push({ lat: s.lat, lon: s.lon, alt: s.elevation_m + 250 });
  for (const list of Object.values(CROSS_TURNPOINTS)) for (const t of list) bumps.push({ lat: t.lat, lon: t.lon, alt: t.altitude_m });
  for (const b of bumps) {
    const d = haversineKm({ lat, lon }, b);
    if (d > 12) continue;
    const v = floor + (b.alt - floor) * Math.exp(-(d * d) / (2 * 2.2 * 2.2));
    if (v > h) h = v;
  }
  h += 60 * Math.sin(lat * 90) * Math.cos(lon * 70);
  return Math.max(floor, h);
}

/** Orientation de la pente (direction vers laquelle elle fait face), via le gradient du relief. */
export function slopeAspect(lat: number, lon: number): { aspect: number; steep: number } {
  const e = 0.01;
  const dzdx = terrainAt(lat, lon + e) - terrainAt(lat, lon - e);
  const dzdy = terrainAt(lat + e, lon) - terrainAt(lat - e, lon);
  // la pente fait face à la descente : direction opposée au gradient
  const aspect = normalizeDeg((Math.atan2(-dzdx, -dzdy) * 180) / Math.PI);
  return { aspect, steep: Math.min(1, Math.hypot(dzdx, dzdy) / 300) };
}

/** Vent synoptique à une altitude AMSL (interpolation des niveaux du scénario). */
export function synopticWind(sc: Scenario, floor: number, altitude: number, noise = 0): { speed: number; dir: number } {
  const rel = Math.max(0, altitude - floor);
  const lv = sc.levels;
  let a = lv[0]!;
  let b = lv[lv.length - 1]!;
  for (let i = 1; i < lv.length; i++) {
    if (rel <= lv[i]!.alt) {
      a = lv[i - 1]!;
      b = lv[i]!;
      break;
    }
  }
  const t = rel >= b.alt ? 1 : clamp((rel - a.alt) / (b.alt - a.alt || 1), 0, 1);
  const speed = (a.speed + (b.speed - a.speed) * t) * (1 + (noise - 0.5) * 0.16);
  const dir = normalizeDeg(a.dir + (b.dir - a.dir) * t + (noise - 0.5) * 16);
  return { speed, dir };
}

/** Somme vectorielle de vents (directions de provenance). */
function addWinds(...winds: { speed: number; dir: number }[]): { speed: number; dir: number } {
  let u = 0;
  let v = 0;
  for (const w of winds) {
    const rad = ((w.dir + 180) * Math.PI) / 180; // vecteur "vers"
    u += w.speed * Math.sin(rad);
    v += w.speed * Math.cos(rad);
  }
  const speed = Math.hypot(u, v);
  const dir = normalizeDeg((Math.atan2(u, v) * 180) / Math.PI + 180);
  return { speed, dir };
}

/**
 * Facteur d'activité thermique 0..1 en heure solaire, selon la durée du jour :
 * début ≈ lever + 37 % du jour, fin ≈ coucher − 23 % du jour, pic aux 45 % de la fenêtre
 * (octobre en Alpes du Nord : ~10h30 → 15h00 solaire, soit 12h00 → 16h30 légale, cf. CDC §4.1).
 * L'amplitude suit la hauteur du soleil à midi (saison).
 */
export function thermalFactor(lat: number, lon: number, time: Date): number {
  const st = sunTimes(lat, lon, time);
  if (!st) return 0;
  const rise = solarHour(lon, st.sunrise);
  const set = solarHour(lon, st.sunset);
  const day = set - rise;
  const start = rise + 0.37 * day;
  const end = set - 0.23 * day;
  const peak = start + 0.45 * (end - start);
  const hs = solarHour(lon, time);
  if (hs <= start || hs >= end) return 0;
  const shape = hs < peak ? Math.sin((Math.PI / 2) * ((hs - start) / (peak - start))) : Math.cos((Math.PI / 2) * ((hs - peak) / (end - peak)));
  const noon = new Date(time.getTime() + (12 - hs) * 3_600_000);
  const amp = clamp(Math.sin((solarElevationDeg(lat, lon, noon) * Math.PI) / 180) / Math.sin((65 * Math.PI) / 180), 0.45, 1);
  return clamp(shape * (0.55 + 0.45 * amp), 0, 1);
}

function diurnal(hs: number): number {
  if (hs >= 5 && hs <= 15) return (1 - Math.cos((Math.PI * (hs - 5)) / 10)) / 2;
  const x = hs < 5 ? hs + 24 : hs;
  return (1 + Math.cos((Math.PI * (x - 15)) / 14)) / 2;
}

export interface WeatherOptions {
  /** Direction de la pente (le déco fait face à…), pour les brises. */
  facingDeg?: number | null;
  isLanding?: boolean;
  key?: string;
  floor?: number;
}

export const SYNTHETIC_MODEL = "synthetic";
const ALOFT_LEVELS = [1000, 1500, 2000, 2500, 3000, 4000];

/** Instantané météo synthétique en un point. */
export function weatherAt(lat: number, lon: number, elevation: number, time: Date, opts: WeatherOptions = {}): WeatherSnapshot {
  const sc = scenarioFor(time);
  const floor = opts.floor ?? valleyFloor(lat, lon);
  const hs = solarHour(lon, time);
  const g = thermalFactor(lat, lon, time);
  const sunElev = solarElevationDeg(lat, lon, time);
  const n = hash01(opts.key ?? `${lat.toFixed(3)},${lon.toFixed(3)}`, time.getUTCHours(), time.getUTCDate());
  const d = diurnal(hs);

  const tValley = sc.tMin + (sc.tMax - sc.tMin) * d;
  const spread = sc.spreadMin + (sc.spreadMax - sc.spreadMin) * d;
  const temperature = tValley - 0.0065 * (elevation - floor);
  const dewPoint = Math.min(temperature - 0.5, tValley - spread - 0.0018 * (elevation - floor));

  const ceilingDry = floor + 250 + sc.blhMax * g;
  const base = floor + 125 * spread;
  const cumulus = g > 0.25 && base < ceilingDry;
  const ceiling = Math.max(elevation + 50, cumulus ? base : ceilingDry);

  const cloud = clamp(sc.cloud + (cumulus ? 25 * g : 0) + (n - 0.5) * 10, 0, 100);
  const lowCloud = clamp(sc.lowCloud + (cumulus ? 12 * g : 0), 0, 100);
  const strength = g > 0.12 ? clamp((0.35 + sc.thermalMax * g) * (1 - cloud / 250) * (0.92 + 0.16 * n), 0, 5) : 0.1;

  // Vent au sol : synoptique réduit + brise de pente (anabatique le jour, catabatique la nuit)
  const syn = synopticWind(sc, floor, elevation, n);
  const winds: { speed: number; dir: number }[] = [{ speed: syn.speed * (opts.isLanding ? 0.55 : 0.65), dir: syn.dir }];
  if (opts.facingDeg !== undefined && opts.facingDeg !== null && !opts.isLanding) {
    if (sunElev > 0) winds.push({ speed: 6.5 * g + 1.5, dir: opts.facingDeg });
    else winds.push({ speed: 4, dir: normalizeDeg(opts.facingDeg + 180) });
  }
  if (opts.isLanding) winds.push({ speed: 7 * g, dir: sc.levels[0]!.dir });
  const w10 = addWinds(...winds);
  const stormy = sc.rainFromSolarHour !== null && hs >= sc.rainFromSolarHour - 1 && hs <= 20;
  const gust = w10.speed * (1.15 + 0.2 * g) + 2 + (stormy ? 16 : 0);

  const winds_aloft: WindLevel[] = ALOFT_LEVELS.filter((a) => a > floor + 50).map((alt) => {
    const w = synopticWind(sc, floor, alt, hash01(alt, n));
    return { altitude_m: alt, pressure_hpa: Math.round(standardPressureHpa(alt)), speed_kmh: Math.round(w.speed), direction_deg: Math.round(w.dir) };
  });

  const precip =
    sc.rainFromSolarHour !== null && hs >= sc.rainFromSolarHour && hs <= 21 ? r1(sc.rainMmH * (0.6 + 0.8 * n)) : 0;
  const cape = Math.round(sc.capeMax * Math.pow(Math.max(g, sc.capeMax > 500 && hs > 12 && hs < 19 ? 0.7 : 0), 0.8));

  return {
    time: time.toISOString(),
    model: SYNTHETIC_MODEL,
    lat,
    lon,
    elevation_m: Math.round(elevation),
    temperature_c: r1(temperature),
    dew_point_c: r1(dewPoint),
    wind_10m: { speed_kmh: Math.round(w10.speed), direction_deg: Math.round(w10.dir), gust_kmh: Math.round(gust) },
    winds_aloft,
    cloud_cover_pct: Math.round(cloud),
    cloud_cover_low_pct: Math.round(lowCloud),
    precipitation_mm_h: precip,
    cape_j_kg: cape,
    lifted_index: r1(3 - cape / 250),
    cin_j_kg: -Math.round(5 + 60 * (1 - g)),
    freezing_level_m: Math.round((floor + tValley / 0.0065) / 10) * 10,
    boundary_layer_height_agl_m: Math.round(Math.max(50, ceilingDry - elevation)),
    thermal_ceiling_m: Math.round(ceiling),
    cloud_base_m: cumulus ? Math.round(base) : null,
    thermal_strength_ms: r1(strength),
    wstar_ms: r1(strength * 1.25),
    shortwave_radiation_w_m2: Math.round(Math.max(0, 1000 * Math.sin((sunElev * Math.PI) / 180)) * (1 - (0.65 * cloud) / 100)),
    nowcast_correction: null,
  };
}

const SOUNDING_PRESSURES = [975, 950, 925, 900, 875, 850, 825, 800, 775, 750, 700, 650, 600, 550, 500];

function altitudeForPressure(p: number): number {
  return (1 - Math.pow(p / 1013.25, 1 / 5.25588)) / 2.25577e-5;
}

/** Sondage synthétique cohérent avec weatherAt (parcelle sèche ≈ plafond, inversion au sommet). */
export function soundingAt(lat: number, lon: number, time: Date): SoundingLevel[] {
  const sc = scenarioFor(time);
  const floor = valleyFloor(lat, lon);
  const hs = solarHour(lon, time);
  const g = thermalFactor(lat, lon, time);
  const d = diurnal(hs);
  const tValley = sc.tMin + (sc.tMax - sc.tMin) * d;
  const spread = sc.spreadMin + (sc.spreadMax - sc.spreadMin) * d;
  const ts = tValley + (g > 0.2 ? 1 : 0);
  const ceilDry = floor + 250 + sc.blhMax * g;
  const base = floor + 125 * spread;
  const cumulus = g > 0.25 && base < ceilDry;
  const parcel = (h: number) => ts - 0.0098 * (h - floor);

  const env = (h: number): number => {
    if (h <= ceilDry) {
      const x = (h - floor) / Math.max(1, ceilDry - floor);
      return parcel(h) - 0.9 * Math.sin(Math.PI * x);
    }
    const inv = sc.stableAloft ? 1.6 : 0.2;
    const lapse = sc.stableAloft ? 0.0056 : 0.0074;
    return parcel(ceilDry) + inv * Math.min(1, (h - ceilDry) / 250) - lapse * (h - ceilDry);
  };
  const dew = (h: number): number => {
    const t = env(h);
    let td: number;
    if (h <= ceilDry) td = tValley - spread - 0.0018 * (h - floor);
    else td = t - (cumulus ? 3 + 0.003 * (h - ceilDry) : 11 + 0.002 * (h - ceilDry));
    return Math.min(td, t - 0.3);
  };

  const alts = [floor, ...SOUNDING_PRESSURES.map(altitudeForPressure).filter((a) => a > floor + 60)];
  return alts.map((h) => {
    const w = synopticWind(sc, floor, h, hash01("snd", Math.round(h)));
    return {
      pressure_hpa: Math.round(standardPressureHpa(h)),
      altitude_m: Math.round(h),
      temperature_c: r1(env(h)),
      dew_point_c: r1(dew(h)),
      wind_speed_kmh: Math.round(w.speed),
      wind_direction_deg: Math.round(w.dir),
    };
  });
}

const LAYER_UNIT: Record<GridLayer, string> = {
  wind: "km/h",
  thermal: "m/s",
  cloudbase: "m",
  ceiling: "m",
  cape: "J/kg",
  precipitation: "mm/h",
  useful_height: "m",
};

/** Grille synthétique ≤ 16×16 points sur la bbox. */
export function gridAt(
  bbox: { min_lat: number; min_lon: number; max_lat: number; max_lon: number },
  time: Date,
  layer: GridLayer,
  altitude: number | null,
): ForecastGridResponse {
  const N = 16;
  const dLat = bbox.max_lat - bbox.min_lat;
  const dLon = bbox.max_lon - bbox.min_lon;
  const res = Math.max(dLat, dLon) / (N - 1);
  const nLat = Math.min(20, Math.max(2, Math.round(dLat / res) + 1));
  const nLon = Math.min(20, Math.max(2, Math.round(dLon / res) + 1));
  const points: ForecastGridResponse["points"] = [];
  const sc = scenarioFor(time);
  for (let i = 0; i < nLat; i++) {
    for (let j = 0; j < nLon; j++) {
      const lat = bbox.min_lat + (dLat * i) / Math.max(1, nLat - 1);
      const lon = bbox.min_lon + (dLon * j) / Math.max(1, nLon - 1);
      const terrain = terrainAt(lat, lon);
      const floor = valleyFloor(lat, lon);
      const n = hash01("grid", i, j, time.getUTCHours());
      const { aspect, steep } = slopeAspect(lat, lon);
      if (layer === "wind") {
        const alt = altitude ?? 10;
        if (alt === 10) {
          const wx = weatherAt(lat, lon, terrain, time, { facingDeg: steep > 0.15 ? aspect : null, key: `g${i}-${j}`, floor });
          points.push({ lat, lon, value: wx.wind_10m.speed_kmh, direction_deg: wx.wind_10m.direction_deg });
        } else {
          if (alt < terrain + 30) continue;
          const w = synopticWind(sc, floor, alt, n);
          // accélération sur les crêtes, abri sous le vent
          const ridge = 1 + 0.25 * Math.exp(-Math.abs(alt - terrain) / 400);
          points.push({ lat, lon, value: Math.round(w.speed * ridge), direction_deg: Math.round(w.dir) });
        }
        continue;
      }
      const wx = weatherAt(lat, lon, terrain, time, { key: `g${i}-${j}`, floor });
      // les pentes au soleil (orientées S à O l'après-midi) déclenchent mieux
      const sunSlope = 1 + 0.35 * steep * Math.cos(((aspect - 200) * Math.PI) / 180);
      const relief = 1 + Math.max(0, terrain - floor) / 3000;
      let value: number | null = null;
      if (layer === "thermal") value = r1(Math.max(0, wx.thermal_strength_ms * sunSlope * relief * (0.9 + 0.2 * n)));
      else if (layer === "ceiling") value = Math.round(wx.thermal_ceiling_m + 0.25 * Math.max(0, terrain - floor) + (n - 0.5) * 120);
      else if (layer === "cloudbase") value = wx.cloud_base_m === null ? null : Math.round(wx.cloud_base_m + (n - 0.5) * 100);
      else if (layer === "useful_height") {
        const ceil = wx.thermal_ceiling_m + 0.25 * Math.max(0, terrain - floor) + (n - 0.5) * 120;
        const useful = Math.min(ceil, wx.cloud_base_m !== null ? wx.cloud_base_m - 300 : Infinity);
        value = Math.max(0, Math.round(useful - terrain));
      }
      else if (layer === "cape") value = Math.round(wx.cape_j_kg * (0.75 + 0.5 * n) * relief);
      else if (layer === "precipitation") {
        const cell = 0.5 + 0.5 * Math.sin(lat * 60 + time.getUTCHours()) * Math.cos(lon * 45);
        value = r1(wx.precipitation_mm_h * cell * 1.6);
      }
      if (value !== null) points.push({ lat, lon, value, direction_deg: null });
    }
  }
  const values = points.map((p) => p.value);
  return {
    time: time.toISOString(),
    layer,
    altitude_m: layer === "wind" ? (altitude ?? 10) : null,
    unit: LAYER_UNIT[layer],
    resolution_deg: Number(res.toFixed(4)),
    points,
    legend: { min: values.length ? Math.min(...values) : 0, max: values.length ? Math.max(...values) : 0 },
  };
}

/** Direction moyenne vers laquelle fait face un déco (à partir de ses secteurs favorables). */
export function facingOf(orientations: string[]): number | null {
  const degs = orientations.map(compassToDeg).filter((d): d is number => d !== null);
  if (degs.length === 0) return null;
  let x = 0;
  let y = 0;
  for (const d of degs) {
    x += Math.sin((d * Math.PI) / 180);
    y += Math.cos((d * Math.PI) / 180);
  }
  return normalizeDeg((Math.atan2(x, y) * 180) / Math.PI);
}
