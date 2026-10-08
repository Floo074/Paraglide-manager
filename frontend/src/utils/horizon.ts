import type { Horizon } from "../api/types";

export interface HorizonOption {
  value: Horizon;
  label: string;
  minutes: number;
}

export const HORIZONS: HorizonOption[] = [
  { value: "30m", label: "30 min", minutes: 30 },
  { value: "1h", label: "1 h", minutes: 60 },
  { value: "2h", label: "2 h", minutes: 120 },
  { value: "8h", label: "8 h", minutes: 480 },
  { value: "12h", label: "12 h", minutes: 720 },
  { value: "24h", label: "24 h", minutes: 1440 },
  { value: "48h", label: "48 h", minutes: 2880 },
];

export function isHorizon(value: unknown): value is Horizon {
  return typeof value === "string" && HORIZONS.some((h) => h.value === value);
}

export function horizonToMinutes(h: Horizon): number {
  const found = HORIZONS.find((o) => o.value === h);
  if (!found) throw new Error(`Horizon inconnu : ${h}`);
  return found.minutes;
}

/**
 * Heure cible = heure de référence + horizon, arrondie au pas de prévision (1 h par défaut,
 * arrondi au plus proche, comme le backend). stepMinutes = 0 désactive l'arrondi.
 */
export function targetTimeFromHorizon(reference: Date, horizon: Horizon, stepMinutes = 60): Date {
  const raw = reference.getTime() + horizonToMinutes(horizon) * 60_000;
  if (stepMinutes <= 0) return new Date(raw);
  const step = stepMinutes * 60_000;
  return new Date(Math.round(raw / step) * step);
}

/** Pour un nowcasting (balises), le backend corrige les prévisions jusqu'à 2 h. */
export function isNowcastHorizon(h: Horizon): boolean {
  return horizonToMinutes(h) <= 120;
}
