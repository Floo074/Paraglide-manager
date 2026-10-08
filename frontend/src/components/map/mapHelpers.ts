import type { LatLngExpression } from "leaflet";
import type { AirspaceGeometry } from "../../api/types";
import { mToFt } from "../../utils/units";

/** GeoJSON (lon, lat) → anneaux Leaflet (lat, lon). */
export function geometryToLatLngs(g: AirspaceGeometry): LatLngExpression[][][] {
  const polys = g.type === "Polygon" ? [g.coordinates] : g.coordinates;
  return polys.map((rings) => rings.map((ring) => ring.map((c) => [c[1]!, c[0]!] as [number, number])));
}

const MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];

/** "févr. → juil." ; toute l'année si 12 mois. */
export function formatMonths(months: number[]): string {
  if (months.length === 0 || months.length >= 12) return "toute l'année";
  const set = new Set(months);
  // trouve le début d'une séquence circulaire
  let start = months[0]!;
  for (const m of months) if (!set.has(((m + 10) % 12) + 1)) start = m;
  const seq: number[] = [];
  for (let i = 0, m = start; i < 12 && set.has(m); i++, m = (m % 12) + 1) seq.push(m);
  if (seq.length === months.length) return `${MONTHS[seq[0]! - 1]} → ${MONTHS[seq[seq.length - 1]! - 1]}`;
  return [...months].sort((a, b) => a - b).map((m) => MONTHS[m - 1]).join(", ");
}

const CLASS_COLOR: Record<string, string> = {
  A: "#dc2626",
  B: "#dc2626",
  C: "#9333ea",
  D: "#2563eb",
  E: "#16a34a",
  F: "#0d9488",
  G: "#64748b",
  P: "#b91c1c",
  R: "#ea580c",
};

export function airspaceColor(cls: string, type: string): string {
  const t = type.toUpperCase();
  if (t.includes("PROHIB") || t === "P") return CLASS_COLOR.P!;
  if (t.includes("RESTRICT") || t.includes("DANGER") || t.includes("ZRT")) return CLASS_COLOR.R!;
  return CLASS_COLOR[cls.toUpperCase()] ?? "#475569";
}

export const fl = (m: number) => `FL${String(Math.round(mToFt(m) / 100)).padStart(3, "0")}`;
export const ft = (m: number) => `${Math.round(mToFt(m) / 10) * 10} ft`;

