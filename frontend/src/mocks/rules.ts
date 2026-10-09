/**
 * Seuils métier du moteur de DÉMONSTRATION, repris du cahier des charges pilote
 * (docs/expert/cahier-des-charges-pilote.md §11). Le vrai moteur est côté backend (rules.py).
 */
import type { Difficulty, Horizon } from "../api/types";

type PerLevel<T> = Record<Difficulty, T>;

export const RULES = {
  takeoffWindMax: { beginner: 15, intermediate: 20, advanced: 25, expert: 30 } as PerLevel<number>,
  takeoffGustMax: { beginner: 20, intermediate: 25, advanced: 30, expert: 35 } as PerLevel<number>,
  gustSpreadMax: { beginner: 8, intermediate: 10, advanced: 12, expert: 15 } as PerLevel<number>,
  crosswindAngleMax: { beginner: 30, intermediate: 45, advanced: 60, expert: 75 } as PerLevel<number>,
  crosswindComponentMax: { beginner: 6, intermediate: 10, advanced: 13, expert: 16 } as PerLevel<number>,
  tailwindMax: { beginner: 0, intermediate: 0, advanced: 5, expert: 8 } as PerLevel<number>,
  calmWind: 5,
  windAloftMax: {
    1500: { beginner: 15, intermediate: 20, advanced: 25, expert: 30 },
    2000: { beginner: 20, intermediate: 25, advanced: 30, expert: 35 },
    3000: { beginner: 25, intermediate: 30, advanced: 35, expert: 40 },
  } as Record<1500 | 2000 | 3000, PerLevel<number>>,
  landingWindMax: { beginner: 15, intermediate: 20, advanced: 25, expert: 28 } as PerLevel<number>,
  thermalMax: { beginner: 1.5, intermediate: 2.5, advanced: 3.5, expert: 5 } as PerLevel<number>,
  localCeilingMinAboveTakeoff: { beginner: 700, intermediate: 600, advanced: 400, expert: 300 } as PerLevel<number>,
  xcCeilingMinAboveTakeoff: { beginner: Infinity, intermediate: 1200, advanced: 1000, expert: 800 } as PerLevel<number>,
  glideK: { beginner: 0.65, intermediate: 0.7, advanced: 0.72, expert: 0.75 } as PerLevel<number>, // CDC rév. 2
  /** Marge d'arrivée (m), bornée à 25 % du dénivelé (CDC rév. 2). */
  arrivalMargin: { beginner: 100, intermediate: 100, advanced: 100, expert: 80 } as PerLevel<number>,
  xcMaxDistanceKm: { beginner: 0, intermediate: 25, advanced: 80, expert: 250 } as PerLevel<number>,
  maxDurationMin: { beginner: 45, intermediate: 120, advanced: 300, expert: 540 } as PerLevel<number>,
  ridge: {
    minKmh: 15,
    maxKmh: { beginner: 20, intermediate: 22, advanced: 27, expert: 30 } as PerLevel<number>,
    maxAngle: { beginner: 20, intermediate: 30, advanced: 40, expert: 45 } as PerLevel<number>,
  },
  airSpeedKmh: 37,
  sinkRateMs: 1.2,
  nogo: {
    precipMmH: 0.2,
    capeAbsolute: 1500,
    capeStorm: { cape: 800, li: -2 },
    cloudBaseMinAboveTakeoff: 200,
    windAnyLevel: 45,
    leeWindAtCrest: 15,
    takeoffWindAbs: 30,
    takeoffGustAbs: 35,
  },
  fl115m: 3505,
  xcSpeedByVario: {
    intermediate: [0, 8, 14, 19],
    advanced: [0, 10, 17, 23, 27],
    expert: [0, 12, 20, 27, 32, 36],
  } as Record<"intermediate" | "advanced" | "expert", number[]>,
  weights: {
    takeoff_wind: 25,
    wind_aloft: 15,
    landing: 15,
    thermal_match: 15,
    duration_match: 10,
    convective_stability: 10,
    data_confidence: 5,
    site_fit: 5,
  },
  /** go si confidence ≥ goMinConfidenceRatio × horizonBaseConfidence[horizon] (CDC rév. 2). */
  verdict: { goMinScore: 65, goMinSafety: 50, goMinConfidenceRatio: 0.75, nogoMaxScore: 45 },
  horizonBaseConfidence: { "15m": 0.92, "30m": 0.9, "1h": 0.85, "2h": 0.8, "8h": 0.7, "12h": 0.65, "24h": 0.55, "48h": 0.4 } as Record<Horizon, number>,
};

/** Marge d'arrivée effective : bornée à 25 % du dénivelé disponible. */
export function arrivalMargin(level: Difficulty, dropM: number): number {
  return Math.min(RULES.arrivalMargin[level], Math.max(0, 0.25 * dropM));
}

/** Sous-score : 100 jusqu'à 50 % du seuil, 40 à 80 %, 0 au seuil (interpolation linéaire). */
export function thresholdSubscore(value: number, threshold: number): number {
  if (!(threshold > 0) || !Number.isFinite(threshold)) return 100;
  const r = Math.max(0, value) / threshold;
  if (r <= 0.5) return 100;
  if (r <= 0.8) return 100 - ((r - 0.5) / 0.3) * 60;
  if (r <= 1) return 40 - ((r - 0.8) / 0.2) * 40;
  return 0;
}
