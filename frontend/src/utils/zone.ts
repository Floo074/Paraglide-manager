import type { BBoxZone, Zone } from "../api/types";
import { KM_PER_DEG_LAT, haversineKm, kmPerDegLon, type Pt } from "./geo";

/** Limites imposées par le contrat (POST /api/plans → 422 au-delà). */
export const MAX_RADIUS_KM = 150;
export const MAX_BBOX_SIDE_DEG = 3;
export const MIN_RADIUS_KM = 2;

const round = (v: number, digits = 4) => Number(v.toFixed(digits));

/**
 * Sérialisation compacte et lisible pour l'URL / localStorage :
 *  - cercle : "c:45.8125,6.2475,25"   (lat, lon, rayon km)
 *  - bbox   : "b:45.7,6.1,45.95,6.4"  (min_lat, min_lon, max_lat, max_lon)
 */
export function serializeZone(zone: Zone): string {
  if (zone.type === "circle") {
    return `c:${round(zone.center.lat)},${round(zone.center.lon)},${round(zone.radius_km, 1)}`;
  }
  return `b:${round(zone.min_lat)},${round(zone.min_lon)},${round(zone.max_lat)},${round(zone.max_lon)}`;
}

/** Inverse de serializeZone. Renvoie null si la chaîne est invalide. */
export function parseZone(raw: string | null | undefined): Zone | null {
  if (!raw) return null;
  const m = /^([cb]):(.+)$/.exec(raw.trim());
  if (!m) return null;
  const nums = m[2]!.split(",").map((s) => Number(s));
  if (nums.some((n) => !Number.isFinite(n))) return null;
  if (m[1] === "c") {
    if (nums.length !== 3) return null;
    const [lat, lon, r] = nums as [number, number, number];
    if (Math.abs(lat) > 90 || Math.abs(lon) > 180 || r <= 0) return null;
    return { type: "circle", center: { lat, lon }, radius_km: r };
  }
  if (nums.length !== 4) return null;
  const [a, b, c, d] = nums as [number, number, number, number];
  const z = bboxFromCorners({ lat: a, lon: b }, { lat: c, lon: d });
  if (Math.abs(z.min_lat) > 90 || Math.abs(z.max_lat) > 90 || Math.abs(z.min_lon) > 180 || Math.abs(z.max_lon) > 180) return null;
  return z;
}

/** Rectangle normalisé à partir de deux coins quelconques. */
export function bboxFromCorners(a: Pt, b: Pt): BBoxZone {
  return {
    type: "bbox",
    min_lat: Math.min(a.lat, b.lat),
    min_lon: Math.min(a.lon, b.lon),
    max_lat: Math.max(a.lat, b.lat),
    max_lon: Math.max(a.lon, b.lon),
  };
}

/** Rectangle englobant d'une zone (cercle → carré circonscrit). */
export function zoneToBBox(zone: Zone): BBoxZone {
  if (zone.type === "bbox") return zone;
  const dLat = zone.radius_km / KM_PER_DEG_LAT;
  const dLon = zone.radius_km / Math.max(1e-6, kmPerDegLon(zone.center.lat));
  return {
    type: "bbox",
    min_lat: zone.center.lat - dLat,
    min_lon: zone.center.lon - dLon,
    max_lat: zone.center.lat + dLat,
    max_lon: zone.center.lon + dLon,
  };
}

/** Agrandit un rectangle d'un facteur (1.2 = +20 %). */
export function padBBox(b: BBoxZone, factor: number): BBoxZone {
  const dLat = ((b.max_lat - b.min_lat) * (factor - 1)) / 2;
  const dLon = ((b.max_lon - b.min_lon) * (factor - 1)) / 2;
  return { type: "bbox", min_lat: b.min_lat - dLat, min_lon: b.min_lon - dLon, max_lat: b.max_lat + dLat, max_lon: b.max_lon + dLon };
}

/** Paramètre `bbox` des endpoints GET : "min_lon,min_lat,max_lon,max_lat". */
export function bboxParam(b: BBoxZone): string {
  return [b.min_lon, b.min_lat, b.max_lon, b.max_lat].map((v) => round(v, 5)).join(",");
}

export function zoneCenter(zone: Zone): Pt {
  if (zone.type === "circle") return zone.center;
  return { lat: (zone.min_lat + zone.max_lat) / 2, lon: (zone.min_lon + zone.max_lon) / 2 };
}

/** Le point est-il dans la zone ? */
export function zoneContains(zone: Zone, p: Pt): boolean {
  if (zone.type === "circle") return haversineKm(zone.center, p) <= zone.radius_km;
  return p.lat >= zone.min_lat && p.lat <= zone.max_lat && p.lon >= zone.min_lon && p.lon <= zone.max_lon;
}

/** Dimensions approximatives d'une zone en km (largeur × hauteur). */
export function zoneSizeKm(zone: Zone): { width: number; height: number } {
  if (zone.type === "circle") return { width: zone.radius_km * 2, height: zone.radius_km * 2 };
  const midLat = (zone.min_lat + zone.max_lat) / 2;
  return {
    width: (zone.max_lon - zone.min_lon) * kmPerDegLon(midLat),
    height: (zone.max_lat - zone.min_lat) * KM_PER_DEG_LAT,
  };
}

/** Validation côté client (mêmes règles que le backend). Renvoie un message ou null. */
export function validateZone(zone: Zone): string | null {
  if (zone.type === "circle") {
    if (!(zone.radius_km > 0)) return "Le rayon doit être positif.";
    if (zone.radius_km > MAX_RADIUS_KM) return `Rayon trop grand (max ${MAX_RADIUS_KM} km).`;
    return null;
  }
  if (zone.max_lat <= zone.min_lat || zone.max_lon <= zone.min_lon) return "Rectangle vide.";
  if (zone.max_lat - zone.min_lat > MAX_BBOX_SIDE_DEG || zone.max_lon - zone.min_lon > MAX_BBOX_SIDE_DEG) {
    return `Rectangle trop grand (max ${MAX_BBOX_SIDE_DEG}° de côté).`;
  }
  return null;
}

/** Description courte : "cercle 25 km" / "rectangle 32 × 20 km". */
export function describeZone(zone: Zone): string {
  if (zone.type === "circle") return `cercle de ${Math.round(zone.radius_km)} km`;
  const { width, height } = zoneSizeKm(zone);
  return `rectangle ${Math.round(width)} × ${Math.round(height)} km`;
}
