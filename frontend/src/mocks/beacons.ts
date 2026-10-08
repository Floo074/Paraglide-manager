/** Balises de démonstration : valeurs dérivées de la météo synthétique au moment présent. */
import type { Beacon } from "../api/types";
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
}

const DEFS: BeaconDef[] = [
  { id: "fixture:b-forclaz", name: "Forclaz déco", lat: 45.8145, lon: 6.2475, elevation_m: 1250, source: "fixture", facing: ["W", "WNW"], ageMin: 4 },
  { id: "fixture:b-doussard", name: "Doussard atterro", lat: 45.787, lon: 6.2175, elevation_m: 460, source: "pioupiou", landing: true, ageMin: 2 },
  { id: "fixture:b-planfait", name: "Planfait", lat: 45.847, lon: 6.237, elevation_m: 1180, source: "pioupiou", facing: ["W", "NW"], ageMin: 9 },
  { id: "fixture:b-talloires", name: "Talloires plage", lat: 45.839, lon: 6.213, elevation_m: 450, source: "pioupiou", landing: true, ageMin: 74 },
  { id: "fixture:b-semnoz", name: "Semnoz sommet", lat: 45.794, lon: 6.098, elevation_m: 1690, source: "pioupiou", ageMin: 6 },
  { id: "fixture:b-montmin", name: "Montmin", lat: 45.802, lon: 6.268, elevation_m: 1040, source: "pioupiou", landing: true, ageMin: 12 },
  { id: "fixture:b-planpraz", name: "Planpraz", lat: 45.9305, lon: 6.851, elevation_m: 2000, source: "pioupiou", facing: ["S"], ageMin: 5 },
  { id: "fixture:b-chamonix", name: "Chamonix Bouchet", lat: 45.931, lon: 6.877, elevation_m: 1040, source: "pioupiou", landing: true, ageMin: 3 },
  { id: "fixture:b-sthilaire", name: "Saint-Hilaire déco", lat: 45.305, lon: 5.888, elevation_m: 985, source: "pioupiou", facing: ["SE"], ageMin: 7 },
  { id: "fixture:b-lumbin", name: "Lumbin", lat: 45.304, lon: 5.911, elevation_m: 240, source: "pioupiou", landing: true, ageMin: 15 },
  { id: "fixture:b-chalvet", name: "Chalvet", lat: 43.976, lon: 6.489, elevation_m: 1600, source: "pioupiou", facing: ["S"], ageMin: 8 },
  { id: "fixture:b-pilat", name: "Dune du Pilat", lat: 44.5895, lon: -1.213, elevation_m: 100, source: "pioupiou", facing: ["W"], ageMin: 4 },
  { id: "fixture:b-pdd", name: "Puy de Dôme sommet", lat: 45.7725, lon: 2.964, elevation_m: 1465, source: "pioupiou", ageMin: 11 },
  { id: "fixture:b-millau", name: "Puncho d'Agast", lat: 44.093, lon: 3.103, elevation_m: 815, source: "pioupiou", facing: ["SW"], ageMin: 45 },
];

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
    return {
      id: d.id,
      name: d.name,
      lat: d.lat,
      lon: d.lon,
      elevation_m: d.elevation_m,
      observed_at: observed.toISOString(),
      wind_speed_kmh: speed,
      wind_gust_kmh: Math.max(speed, Math.round(wx.wind_10m.gust_kmh * (0.9 + 0.2 * n))),
      wind_direction_deg: speed < 2 ? null : Math.round((wx.wind_10m.direction_deg + (n - 0.5) * 20 + 360) % 360),
      temperature_c: wx.temperature_c,
      source: d.source,
      stale: d.ageMin > 30,
    };
  });
}
