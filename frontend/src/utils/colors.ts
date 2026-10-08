/** Échelles de couleurs (vent, altitude, couches météo). */

export type Rgb = [number, number, number];
export interface ColorStop {
  value: number;
  color: Rgb;
}

const hex = (c: Rgb) => "#" + c.map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");

export function hexToRgb(h: string): Rgb {
  const s = h.replace("#", "");
  return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16)];
}

/** Interpolation linéaire dans une échelle de couleurs (valeurs croissantes). */
export function interpolateStops(stops: ColorStop[], value: number): string {
  if (stops.length === 0) return "#888888";
  if (value <= stops[0]!.value) return hex(stops[0]!.color);
  const last = stops[stops.length - 1]!;
  if (value >= last.value) return hex(last.color);
  for (let i = 1; i < stops.length; i++) {
    const a = stops[i - 1]!;
    const b = stops[i]!;
    if (value <= b.value) {
      const t = (value - a.value) / (b.value - a.value || 1);
      return hex([0, 1, 2].map((k) => a.color[k]! + (b.color[k]! - a.color[k]!) * t) as Rgb);
    }
  }
  return hex(last.color);
}

const s = (value: number, color: string): ColorStop => ({ value, color: hexToRgb(color) });

/**
 * Vent (km/h), lecture parapente : calme → bleu, 5-15 idéal → vert,
 * 20 → jaune, 25-30 → orange/rouge, ≥ 40 → violet (hors domaine de vol).
 */
export const WIND_STOPS: ColorStop[] = [
  s(0, "#60a5fa"),
  s(6, "#34d399"),
  s(15, "#22c55e"),
  s(20, "#eab308"),
  s(26, "#f97316"),
  s(32, "#ef4444"),
  s(42, "#a855f7"),
];
export const windColor = (kmh: number) => interpolateStops(WIND_STOPS, kmh);

/** Catégorie textuelle du vent pour un pilote. */
export function windCategory(kmh: number): "calme" | "faible" | "modéré" | "fort" | "très fort" {
  if (kmh < 6) return "calme";
  if (kmh < 15) return "faible";
  if (kmh < 25) return "modéré";
  if (kmh < 35) return "fort";
  return "très fort";
}

/** Altitude de la trace : bleu (bas) → vert → jaune → rouge (haut), façon "turbo". */
export const ALTITUDE_STOPS: ColorStop[] = [
  s(0, "#3b4cc0"),
  s(0.25, "#2aa7de"),
  s(0.5, "#3fd27f"),
  s(0.75, "#f4c430"),
  s(1, "#e8443a"),
];
export function altitudeColor(alt: number, min: number, max: number): string {
  const t = max > min ? (alt - min) / (max - min) : 0.5;
  return interpolateStops(ALTITUDE_STOPS, t);
}

export const THERMAL_STOPS: ColorStop[] = [s(0, "#1e3a8a"), s(0.8, "#0ea5e9"), s(1.5, "#22c55e"), s(2.2, "#eab308"), s(3, "#f97316"), s(4, "#dc2626")];
export const HEIGHT_STOPS: ColorStop[] = [s(500, "#7c3aed"), s(1200, "#2563eb"), s(1800, "#06b6d4"), s(2400, "#22c55e"), s(3000, "#eab308"), s(3800, "#f97316")];
export const CAPE_STOPS: ColorStop[] = [s(0, "#94a3b8"), s(200, "#a3e635"), s(600, "#eab308"), s(1200, "#f97316"), s(2000, "#dc2626"), s(3000, "#a21caf")];
export const PRECIP_STOPS: ColorStop[] = [s(0, "#cbd5e1"), s(0.2, "#93c5fd"), s(1, "#3b82f6"), s(3, "#1d4ed8"), s(8, "#7c3aed"), s(15, "#c026d3")];

/** Hauteur utile (m/sol) : rouge = on ne tient pas, vert/bleu = marge confortable. */
export const USEFUL_HEIGHT_STOPS: ColorStop[] = [s(0, "#b91c1c"), s(300, "#f97316"), s(600, "#eab308"), s(1000, "#22c55e"), s(1500, "#06b6d4"), s(2200, "#2563eb")];

/** Couleur d'une jauge de score 0..100. */
export function scoreColor(score: number): string {
  return interpolateStops([s(0, "#dc2626"), s(40, "#f97316"), s(60, "#eab308"), s(75, "#84cc16"), s(100, "#16a34a")], score);
}
