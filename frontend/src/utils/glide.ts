/**
 * Plané final : lecture pilote de FlightPlan.glide et de LandingCandidate.wind_along_track_kmh
 * (CDC pilote §14 : vent rencontré sur le plané, part du vent arrière comptée, hauteur d'arrivée).
 * Fonctions pures, sans React, testées dans src/test/glide.test.ts.
 */
import type { Difficulty, FlightPlanGlide } from "../api/types";
import { formatNumber } from "./format";

const MINUS = "−";
const NBSP = " ";

/** |w∥| sous ce seuil : vent faible sur le plané, aucun crédit de vent arrière (CDC §14.2, gabarits §14.7). */
export const GLIDE_WIND_WEAK_KMH = 5;
/** r = requise / disponible au-delà : marge faible (Risk GLIDE_MARGIN caution, CDC §2.3). */
export const GLIDE_R_CAUTION = 0.9;
/** Hauteur d'arrivée attendue à partir de laquelle l'arrivée est « haute » avec du vent arrière (HIGH_ARRIVAL info). */
export const HIGH_ARRIVAL_M = 300;
/** Seuil « prudence » de HIGH_ARRIVAL selon le niveau (CDC §14.4). */
export const HIGH_ARRIVAL_CAUTION_M: Record<Difficulty, number> = { beginner: 500, intermediate: 500, advanced: 700, expert: 700 };
/** Arrivée attendue sous cette hauteur : arrivée basse (marge d'arrivée du §2.3). */
export const LOW_ARRIVAL_M = 100;

/** Valeur numérique exploitable (un backend en retard sur le contrat peut omettre les champs récents). */
export function known(v: number | null | undefined): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

export type AlongWindKind = "tail" | "head" | "weak";

/** Vent arrière (≥ 5 km/h), de face (≤ −5 km/h) ou faible. */
export function alongWindKind(kmh: number): AlongWindKind {
  if (kmh >= GLIDE_WIND_WEAK_KMH) return "tail";
  if (kmh <= -GLIDE_WIND_WEAK_KMH) return "head";
  return "weak";
}

/** « +14 km/h » / « −12 km/h » / « 0 km/h » (signe typographique, + = arrière). */
export function formatSignedKmh(kmh: number): string {
  const r = Math.round(kmh);
  if (r === 0) return `0${NBSP}km/h`;
  return r > 0 ? `+${r}${NBSP}km/h` : `${MINUS}${-r}${NBSP}km/h`;
}

/** « +14 km/h dans le dos », « −12 km/h de face », « vent nul ». */
export function formatAlongWind(kmh: number): string {
  const r = Math.round(kmh);
  if (r === 0) return "vent nul";
  return r > 0 ? `${formatSignedKmh(r)} dans le dos` : `${formatSignedKmh(r)} de face`;
}

/** Vent sur le plané d'un candidat (null = non calculé par le serveur). */
export function formatCandidateWind(kmh: number | null | undefined): string {
  return known(kmh) ? formatAlongWind(kmh) : "inconnu";
}

/**
 * Part du vent retenue dans la finesse de calcul :
 * arrière crédité en partie (« 10 km/h comptés (71 %) »), face comptée en entier ou majorée par les rafales.
 */
export function formatWindCredit(along: number, credit: number): string {
  if (!known(along) || !known(credit)) return "";
  const kmh = (v: number) => `${formatNumber(v, 1)}${NBSP}km/h ${v >= 2 ? "comptés" : "compté"}`;
  if (along >= 0.5) {
    if (credit < 0.5) return along < GLIDE_WIND_WEAK_KMH ? "trop faible pour être compté" : "non compté par prudence";
    const pct = Math.round(Math.min(1, credit / along) * 100);
    return pct >= 99 ? "compté en entier" : `${kmh(credit)} (${pct}${NBSP}%)`;
  }
  if (along <= -0.5) {
    return -credit >= -along + 0.5 ? `${kmh(-credit)} avec les rafales` : "compté en entier";
  }
  return "";
}

export type GlideMarginLevel = "ok" | "low" | "over";

/** Marge de finesse : OK, faible (r > 0,90) ou hors de portée (r > 1 ou margin_ok faux). */
export function glideMarginLevel(g: Pick<FlightPlanGlide, "required_ratio" | "available_ratio" | "margin_ok">): GlideMarginLevel {
  if (!g.margin_ok) return "over";
  if (g.required_ratio <= 0) return "ok"; // top landing : pas de plané à vérifier
  if (!(g.available_ratio > 0)) return "over";
  const r = g.required_ratio / g.available_ratio;
  if (r > 1) return "over";
  return r > GLIDE_R_CAUTION ? "low" : "ok";
}

export const GLIDE_MARGIN_LABEL: Record<GlideMarginLevel, string> = { ok: "marge OK", low: "marge faible", over: "hors de portée" };

/** « marge 39 % » (part de finesse disponible non utilisée) ou « il manque 12 % ». */
export function formatGlideMarginPct(required: number, available: number): string {
  if (required <= 0) return "pas de plané à vérifier";
  if (!(available > 0)) return "plané impossible";
  const m = Math.round((1 - required / available) * 100);
  return m >= 0 ? `marge ${m}${NBSP}%` : `il manque ${-m}${NBSP}%`;
}

/** Effet du vent sur la finesse de calcul par rapport à l'air calme : « +32 % », « −35 % », « = ». */
export function formatWindGain(calm: number, available: number): string {
  if (!(calm > 0) || !known(available)) return "";
  const p = Math.round((available / calm - 1) * 100);
  if (p === 0) return "=";
  return p > 0 ? `+${p}${NBSP}%` : `${MINUS}${-p}${NBSP}%`;
}

/** Effet du vent en clair : « +21 % grâce au vent », « −35 % à cause du vent », « sans effet du vent ». */
export function formatWindEffect(calm: number, available: number): string {
  const gain = formatWindGain(calm, available);
  if (!gain) return "";
  if (gain === "=") return "sans effet du vent";
  return gain.startsWith("+") ? `${gain} grâce au vent` : `${gain} à cause du vent`;
}

/** La valeur en air calme mérite-t-elle d'être montrée (différente de la disponible) ? */
export function showCalmRatio(g: Pick<FlightPlanGlide, "calm_available_ratio" | "available_ratio">): boolean {
  return known(g.calm_available_ratio) && g.calm_available_ratio > 0 && Math.abs(g.calm_available_ratio - g.available_ratio) >= 0.05;
}

export type ArrivalLevel = "unknown" | "below" | "low" | "normal" | "high" | "very_high";

/**
 * Hauteur d'arrivée attendue : sous l'atterro, basse, normale, haute (vent arrière ≥ 5 km/h et ≥ 300 m) ou très haute
 * (seuil « prudence » du niveau : 500 m élève / brevet, 700 m au-delà).
 */
export function arrivalLevel(expected: number | null | undefined, along: number | null | undefined, level: Difficulty): ArrivalLevel {
  if (!known(expected)) return "unknown";
  if (expected < 0) return "below";
  if (expected < LOW_ARRIVAL_M) return "low";
  if (known(along) && along >= GLIDE_WIND_WEAK_KMH) {
    if (expected >= HIGH_ARRIVAL_CAUTION_M[level]) return "very_high";
    if (expected >= HIGH_ARRIVAL_M) return "high";
  }
  return "normal";
}

export const ARRIVAL_LABEL: Record<ArrivalLevel, string> = {
  unknown: "non estimée",
  below: "sous l'atterro",
  low: "arrivée basse",
  normal: "arrivée normale",
  high: "arrivée haute",
  very_high: "arrivée très haute",
};

/** « ≈ 370 m » (arrondi à 10 m : c'est une estimation) ; « −40 m » sous l'atterro ; « — » inconnue (top landing). */
export function formatArrivalHeight(m: number | null | undefined): string {
  if (!known(m)) return "—";
  const r = Math.round(m / 10) * 10;
  return r < 0 ? `${MINUS}${formatNumber(-r)}${NBSP}m` : `≈${NBSP}${formatNumber(r)}${NBSP}m`;
}

/** Couleur d'ensemble du bloc : rouge hors de portée, orange marge faible ou arrivée basse, bleu arrivée haute. */
export type GlideTone = "nogo" | "marginal" | "high" | "ok";

export function glideTone(margin: GlideMarginLevel, arrival: ArrivalLevel): GlideTone {
  if (margin === "over" || arrival === "below") return "nogo";
  if (margin === "low" || arrival === "low") return "marginal";
  if (arrival === "high" || arrival === "very_high") return "high";
  return "ok";
}

/** Texte court de l'indicateur de carte : « +14 km/h dans le dos · finesse 7,3 → 9,6 ». */
export function glideMapSummary(g: FlightPlanGlide): string {
  const parts: string[] = [];
  if (known(g.wind_along_track_kmh)) parts.push(`Vent sur le plané ${formatAlongWind(g.wind_along_track_kmh)}`);
  if (showCalmRatio(g)) parts.push(`finesse ${formatNumber(g.calm_available_ratio, 1)} → ${formatNumber(g.available_ratio, 1)}`);
  else parts.push(`finesse ${formatNumber(g.available_ratio, 1)}`);
  if (known(g.expected_arrival_height_m)) parts.push(`arrivée ${formatArrivalHeight(g.expected_arrival_height_m)}`);
  return parts.join(" · ");
}
