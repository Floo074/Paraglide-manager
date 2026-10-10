/** Lecture des balises : âge, tendance, rattachement aux sites du plan (affichage). */
import type { Beacon, BeaconTrend, StationReading, StationRole } from "../api/types";
import { formatDuration, formatNumber } from "./format";

/** Au-delà de cet âge, une mesure n'est plus utilisable pour décider (CDC §8 : `stale` > 30 min). */
export const BEACON_MAX_AGE_MIN = 30;

/**
 * Seuils de tendance sur 1 h, IDENTIQUES au backend (CDC §12.2, `trend_1h`, `rules.TREND_1H`) :
 * hausse > 5 km/h/h (prudence) et > 20 km/h/h (danger) ; rotation ≥ 60° si le vent fait au moins
 * 8 km/h ; bascule ≥ 120° (danger) si le vent fait au moins 10 km/h.
 */
export const TREND_THRESHOLDS = {
  windIncrease: { caution: 5, danger: 20 },
  rotation: { caution: 60, minWind: 8 },
  reversal: { deg: 120, minWind: 10 },
} as const;

/** Âge de la mesure en minutes (arrondi, jamais négatif). */
export function beaconAgeMinutes(observedAt: string | Date, now: Date): number {
  const t = typeof observedAt === "string" ? new Date(observedAt) : observedAt;
  return Math.max(0, Math.round((now.getTime() - t.getTime()) / 60_000));
}

/** Mesure trop ancienne : marquée `stale` par le serveur ou plus de 30 min au moment de l'affichage. */
export function isBeaconOutdated(b: Pick<Beacon, "observed_at" | "stale">, now: Date): boolean {
  return b.stale || beaconAgeMinutes(b.observed_at, now) > BEACON_MAX_AGE_MIN;
}

/** Fenêtre de tendance lisible : 60 → "1 h", 30 → "30 min", 90 → "1 h 30". */
export function formatTrendWindow(minutes: number): string {
  return formatDuration(minutes);
}

/** Flèche de tendance du vent moyen : ↗ forcit, ↘ mollit, → stable (|Δ| < 2 km/h). */
export function trendArrow(t: Pick<BeaconTrend, "speed_change_kmh">): "↗" | "↘" | "→" {
  if (t.speed_change_kmh >= 2) return "↗";
  if (t.speed_change_kmh <= -2) return "↘";
  return "→";
}

/** "+8 km/h en 1 h", "−3 km/h en 30 min", "stable en 1 h". */
export function formatSpeedTrend(t: Pick<BeaconTrend, "speed_change_kmh" | "window_min">): string {
  const d = Math.round(t.speed_change_kmh);
  const win = formatTrendWindow(t.window_min);
  if (d === 0) return `stable en ${win}`;
  return `${d > 0 ? "+" : "−"}${formatNumber(Math.abs(d))}\u00a0km/h en ${win}`;
}

/** "rotation +40° (horaire)" / "rotation −35° (anti-horaire)" ; null si rotation < 15°. */
export function formatRotation(t: Pick<BeaconTrend, "direction_change_deg">, minDeg = 15): string | null {
  const d = Math.round(t.direction_change_deg);
  if (Math.abs(d) < minDeg) return null;
  return `rotation ${d > 0 ? "+" : "−"}${Math.abs(d)}° (${d > 0 ? "horaire" : "anti-horaire"})`;
}

/** Tendance complète en une ligne : "↗ +8 km/h en 1 h · rotation +40° (horaire)". */
export function formatTrend(t: BeaconTrend): string {
  const rot = formatRotation(t);
  return `${trendArrow(t)} ${formatSpeedTrend(t)}${rot ? ` · ${rot}` : ""}`;
}

/**
 * Niveau d'alerte de la tendance, aligné sur le backend (CDC §12.2) : vent qui forcit de plus de
 * 5 km/h/h (prudence) ou de plus de 20 km/h/h (danger) ; rotation ≥ 60° (prudence) si le vent fait
 * au moins 8 km/h ; bascule ≥ 120° (danger) si le vent fait au moins 10 km/h. Hausse ramenée à 1 h
 * (r = speed_change × 60 / window) ; la rotation est celle de la fenêtre, comme côté serveur.
 */
export function trendLevel(t: BeaconTrend, currentSpeedKmh: number | null): "danger" | "caution" | null {
  const perHour = t.window_min > 0 ? 60 / t.window_min : 1;
  const inc = t.speed_change_kmh * perHour;
  const rot = Math.abs(t.direction_change_deg);
  const v = currentSpeedKmh ?? 0;
  const T = TREND_THRESHOLDS;
  if (inc > T.windIncrease.danger || (v >= T.reversal.minWind && rot >= T.reversal.deg)) return "danger";
  if (inc > T.windIncrease.caution || (v >= T.rotation.minWind && rot >= T.rotation.caution)) return "caution";
  return null;
}

export const STATION_ROLE_LABEL: Record<StationRole, string> = {
  takeoff: "Déco",
  landing: "Atterro",
  alternate_landing: "Atterro de secours",
};

/** Regroupe les balises rattachées par rôle, représentatives d'abord puis par poids décroissant. */
export function readingsByRole(readings: StationReading[]): Record<StationRole, StationReading[]> {
  const out: Record<StationRole, StationReading[]> = { takeoff: [], landing: [], alternate_landing: [] };
  for (const r of readings) out[r.site_role]?.push(r);
  for (const k of Object.keys(out) as StationRole[]) {
    out[k].sort((a, b) => Number(b.representative) - Number(a.representative) || b.weight - a.weight || a.distance_km - b.distance_km);
  }
  return out;
}

/** Vrai si au moins une balise Pioupiou / OpenWindMap est affichée (attribution obligatoire). */
export function hasPioupiou(beacons: Pick<Beacon, "source">[]): boolean {
  return beacons.some((b) => b.source === "pioupiou");
}

export const PIOUPIOU_ATTRIBUTION =
  'Balises &copy; <a href="https://www.openwindmap.org" target="_blank" rel="noreferrer">contributeurs OpenWindMap / Pioupiou</a>';
export const PIOUPIOU_ATTRIBUTION_TEXT = "© contributeurs OpenWindMap / Pioupiou";

export const NO_LANDING_BEACON_TEXT = "Pas de balise représentative à l'atterro — vérifiez la manche à air sur place";
export const NO_TAKEOFF_BEACON_TEXT = "Pas de balise représentative au déco — observez la manche à air et les autres voiles avant de gonfler";
