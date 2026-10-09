/**
 * Balises de démonstration : valeurs dérivées de la météo synthétique au moment présent.
 *
 * Les trois balises Pioupiou d'Annecy reprennent l'identifiant, le nom et la position RÉELS
 * (api.pioupiou.fr, octobre 2026) : seules les mesures sont simulées. Les autres balises sont
 * fictives (`fixture:`) ou placées approximativement.
 */
import type { Beacon, BeaconTrend } from "../api/types";
import { facingOf, hash01, weatherAt } from "./weather";

interface BeaconDef {
  id: string;
  name: string;
  lat: number;
  lon: number;
  elevation_m: number;
  source: Beacon["source"];
  facing?: string[];
  landing?: boolean;
  ageMin: number;
  /** false = pas d'historique exploitable (tendance null). */
  history?: boolean;
}

const DEFS: BeaconDef[] = [
  // ───────── Annecy (balises Pioupiou réelles : id, nom et position) ─────────
  { id: "pioupiou:1720", name: "Atterrissage de Doussard", lat: 45.781728, lon: 6.222627, elevation_m: 450, source: "pioupiou", landing: true, ageMin: 3 },
  { id: "pioupiou:1708", name: "Déco Anglettaz 1570m", lat: 45.960298, lon: 6.241037, elevation_m: 1570, source: "pioupiou", facing: ["SW", "W"], ageMin: 6 },
  { id: "pioupiou:1476", name: "Veyrier Club Nautique", lat: 45.887754, lon: 6.172054, elevation_m: 447, source: "pioupiou", landing: true, ageMin: 5 },
  // ───────── Annecy (fictives) ─────────
  { id: "fixture:b-forclaz", name: "Forclaz déco", lat: 45.8145, lon: 6.2475, elevation_m: 1250, source: "fixture", facing: ["W", "WNW"], ageMin: 4 },
  { id: "fixture:b-planfait", name: "Planfait", lat: 45.847, lon: 6.237, elevation_m: 1180, source: "pioupiou", facing: ["W", "NW"], ageMin: 9 },
  { id: "fixture:b-talloires", name: "Talloires plage", lat: 45.839, lon: 6.213, elevation_m: 450, source: "pioupiou", landing: true, ageMin: 74, history: false },
  { id: "fixture:b-semnoz", name: "Semnoz sommet", lat: 45.794, lon: 6.098, elevation_m: 1690, source: "pioupiou", ageMin: 6 },
  { id: "fixture:b-montmin", name: "Montmin", lat: 45.802, lon: 6.268, elevation_m: 1040, source: "pioupiou", landing: true, ageMin: 12 },
  // ───────── autres massifs (fictives) ─────────
  { id: "fixture:b-planpraz", name: "Planpraz", lat: 45.9305, lon: 6.851, elevation_m: 2000, source: "pioupiou", facing: ["S"], ageMin: 5 },
  { id: "fixture:b-chamonix", name: "Chamonix Bouchet", lat: 45.931, lon: 6.877, elevation_m: 1040, source: "pioupiou", landing: true, ageMin: 3 },
  { id: "fixture:b-sthilaire", name: "Saint-Hilaire déco", lat: 45.305, lon: 5.888, elevation_m: 985, source: "ffvl", facing: ["SE"], ageMin: 7 },
  { id: "fixture:b-lumbin", name: "Lumbin", lat: 45.304, lon: 5.911, elevation_m: 240, source: "pioupiou", landing: true, ageMin: 15 },
  { id: "fixture:b-chalvet", name: "Chalvet", lat: 43.976, lon: 6.489, elevation_m: 1600, source: "pioupiou", facing: ["S"], ageMin: 8 },
  { id: "fixture:b-pilat", name: "Dune du Pilat", lat: 44.5895, lon: -1.213, elevation_m: 100, source: "pioupiou", facing: ["W"], ageMin: 4 },
  { id: "fixture:b-pdd", name: "Puy de Dôme sommet", lat: 45.7725, lon: 2.964, elevation_m: 1465, source: "ffvl", ageMin: 11, history: false },
  { id: "fixture:b-millau", name: "Puncho d'Agast", lat: 44.093, lon: 3.103, elevation_m: 815, source: "pioupiou", facing: ["SW"], ageMin: 45 },
];

/**
 * Tendance simulée sur 60 min : la brise d'atterro forcit en début d'après-midi (+5 à +9 km/h),
 * sinon variations modérées. Plafonnée sous le seuil « danger » du CDC (+10 km/h/h).
 */
function mockTrend(d: BeaconDef, now: Date, speed: number, gust: number): BeaconTrend | null {
  if (d.history === false) return null;
  const n = hash01(d.id, "trend", now.getUTCHours(), now.getUTCDate());
  const m = hash01(d.id, "rot", now.getUTCHours());
  const utc = now.getUTCHours();
  const breeze = d.landing && utc >= 10 && utc <= 15;
  const raw = breeze ? 5 + n * 4 : (n - 0.4) * 12;
  const speed_change_kmh = Math.round(Math.max(-speed, Math.min(9, raw)));
  const direction_change_deg = speed < 3 ? 0 : Math.round((m - 0.5) * (breeze ? 30 : 70));
  return {
    window_min: 60,
    speed_change_kmh,
    direction_change_deg,
    gust_max_kmh: Math.max(gust, Math.round(gust + n * 6)),
    samples: d.source === "pioupiou" ? 15 : 6,
  };
}

export function mockBeacons(now: Date = new Date()): Beacon[] {
  return DEFS.map((d) => {
    const observed = new Date(now.getTime() - d.ageMin * 60_000);
    const wx = weatherAt(d.lat, d.lon, d.elevation_m, observed, {
      facingDeg: d.facing ? facingOf(d.facing) : null,
      isLanding: d.landing,
      key: d.id,
    });
    const n = hash01(d.id, now.getUTCHours());
    const speed = Math.max(0, Math.round(wx.wind_10m.speed_kmh * (0.85 + 0.3 * n)));
    const gust = Math.max(speed, Math.round(wx.wind_10m.gust_kmh * (0.9 + 0.2 * n)));
    return {
      id: d.id,
      name: d.name,
      lat: d.lat,
      lon: d.lon,
      elevation_m: d.elevation_m,
      observed_at: observed.toISOString(),
      wind_speed_kmh: speed,
      wind_gust_kmh: gust,
      wind_direction_deg: speed < 2 ? null : Math.round((wx.wind_10m.direction_deg + (n - 0.5) * 20 + 360) % 360),
      temperature_c: wx.temperature_c,
      source: d.source,
      stale: d.ageMin > 30,
      trend: mockTrend(d, now, speed, gust),
    };
  });
}
