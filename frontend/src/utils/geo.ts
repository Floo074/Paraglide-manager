/** Fonctions géographiques simples (sphère WGS84 approchée). */

export const EARTH_RADIUS_KM = 6371.0088;
const toRad = (d: number) => (d * Math.PI) / 180;
const toDeg = (r: number) => (r * 180) / Math.PI;

export interface Pt {
  lat: number;
  lon: number;
}

export function haversineKm(a: Pt, b: Pt): number {
  const dLat = toRad(b.lat - a.lat);
  const dLon = toRad(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Cap initial de a vers b, en degrés [0, 360). */
export function bearingDeg(a: Pt, b: Pt): number {
  const φ1 = toRad(a.lat);
  const φ2 = toRad(b.lat);
  const Δλ = toRad(b.lon - a.lon);
  const y = Math.sin(Δλ) * Math.cos(φ2);
  const x = Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ);
  return (toDeg(Math.atan2(y, x)) + 360) % 360;
}

/** Point à `distanceKm` de `origin` selon le cap `bearing` (degrés). */
export function destinationPoint(origin: Pt, bearing: number, distanceKm: number): Pt {
  const δ = distanceKm / EARTH_RADIUS_KM;
  const θ = toRad(bearing);
  const φ1 = toRad(origin.lat);
  const λ1 = toRad(origin.lon);
  const φ2 = Math.asin(Math.sin(φ1) * Math.cos(δ) + Math.cos(φ1) * Math.sin(δ) * Math.cos(θ));
  const λ2 = λ1 + Math.atan2(Math.sin(θ) * Math.sin(δ) * Math.cos(φ1), Math.cos(δ) - Math.sin(φ1) * Math.sin(φ2));
  return { lat: toDeg(φ2), lon: ((toDeg(λ2) + 540) % 360) - 180 };
}

/** Longueur d'une polyligne (km). */
export function pathLengthKm(points: Pt[]): number {
  let total = 0;
  for (let i = 1; i < points.length; i++) total += haversineKm(points[i - 1]!, points[i]!);
  return total;
}

/** Kilomètres par degré de longitude à une latitude donnée. */
export function kmPerDegLon(lat: number): number {
  return 111.32 * Math.cos(toRad(lat));
}
export const KM_PER_DEG_LAT = 110.574;

/** Distance (km) d'un point à un segment [a, b], en projection locale équirectangulaire. */
export function distancePointToSegmentKm(p: Pt, a: Pt, b: Pt): number {
  const kx = kmPerDegLon(p.lat);
  const ky = KM_PER_DEG_LAT;
  const ax = (a.lon - p.lon) * kx, ay = (a.lat - p.lat) * ky;
  const bx = (b.lon - p.lon) * kx, by = (b.lat - p.lat) * ky;
  const dx = bx - ax, dy = by - ay;
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len2));
  const cx = ax + t * dx, cy = ay + t * dy;
  return Math.sqrt(cx * cx + cy * cy);
}

/** Point dans polygone (ring [lon, lat][]), algorithme du lancer de rayon. */
export function pointInRing(p: Pt, ring: ReadonlyArray<ReadonlyArray<number>>): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i]![0]!, yi = ring[i]![1]!;
    const xj = ring[j]![0]!, yj = ring[j]![1]!;
    const intersect = yi > p.lat !== yj > p.lat && p.lon < ((xj - xi) * (p.lat - yi)) / (yj - yi) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

/** Interpolation linéaire entre deux points. */
export function lerpPt(a: Pt, b: Pt, t: number): Pt {
  return { lat: a.lat + (b.lat - a.lat) * t, lon: a.lon + (b.lon - a.lon) * t };
}
