/** Conversions d'unités et de directions (rose des vents 16 points). */

export const COMPASS_16 = [
  "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
] as const;
export type Compass16 = (typeof COMPASS_16)[number];

/** Libellés français (O = Ouest). */
const COMPASS_FR: Record<Compass16, string> = {
  N: "N", NNE: "NNE", NE: "NE", ENE: "ENE", E: "E", ESE: "ESE", SE: "SE", SSE: "SSE",
  S: "S", SSW: "SSO", SW: "SO", WSW: "OSO", W: "O", WNW: "ONO", NW: "NO", NNW: "NNO",
};

/** Ramène un angle dans [0, 360). */
export function normalizeDeg(deg: number): number {
  const d = deg % 360;
  return d < 0 ? d + 360 : d;
}

/** Écart angulaire absolu entre deux directions, dans [0, 180]. */
export function angleDiff(a: number, b: number): number {
  const d = Math.abs(normalizeDeg(a) - normalizeDeg(b));
  return d > 180 ? 360 - d : d;
}

/** Direction en degrés → point cardinal (16 points, notation internationale du contrat). */
export function degToCompass(deg: number): Compass16 {
  const idx = Math.round(normalizeDeg(deg) / 22.5) % 16;
  return COMPASS_16[idx]!;
}

/** Direction en degrés → libellé français ("ONO", "SO"…). */
export function degToCardinalFr(deg: number): string {
  return COMPASS_FR[degToCompass(deg)];
}

/** Point cardinal (16 points, "N".."NNW") → degrés, ou null si inconnu. */
export function compassToDeg(point: string): number | null {
  const idx = COMPASS_16.indexOf(point.toUpperCase() as Compass16);
  return idx < 0 ? null : idx * 22.5;
}

/** Libellé français d'un point cardinal du contrat ("WNW" → "ONO"). */
export function compassFr(point: string): string {
  return COMPASS_FR[point.toUpperCase() as Compass16] ?? point;
}

export const kmhToMs = (kmh: number): number => kmh / 3.6;
export const msToKmh = (ms: number): number => ms * 3.6;
export const kmhToKt = (kmh: number): number => kmh / 1.852;
export const ktToKmh = (kt: number): number => kt * 1.852;
export const mToFt = (m: number): number => m * 3.28084;

/** Pression standard (atmosphère type OACI) à une altitude donnée, en hPa. */
export function standardPressureHpa(altitudeM: number): number {
  return 1013.25 * Math.pow(1 - 2.25577e-5 * altitudeM, 5.25588);
}

/**
 * Finesse sol effective avec un vent de face/arrière (composante positive = vent de face).
 * airspeedKmh : vitesse air à finesse max (≈ 36-38 km/h pour une aile loisir).
 */
export function groundGlideRatio(glideRatio: number, headwindKmh: number, airspeedKmh = 37): number {
  const ground = airspeedKmh - headwindKmh;
  if (ground <= 0) return 0;
  return (glideRatio * ground) / airspeedKmh;
}
