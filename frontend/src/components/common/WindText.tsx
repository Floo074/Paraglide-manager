import { ArrowUp } from "lucide-react";
import { VERDICT_CLASS, windVerdict, type WindLimits } from "../../config/thresholds";
import { degToCardinalFr, normalizeDeg } from "../../utils/units";

/**
 * Vent lisible : flèche (pointe vers où va le vent) + "ONO 12 km/h, raf. 18".
 * Coloré selon les seuils (vert < 80 %, orange 80-100 %, rouge au-delà) si `limits` est fourni.
 */
export function WindText({
  speed,
  gust,
  dir,
  limits,
  compact = false,
}: {
  speed: number | null;
  gust?: number | null;
  dir: number | null;
  limits?: WindLimits | null;
  compact?: boolean;
}) {
  if (speed === null) return <span className="muted">vent inconnu</span>;
  const v = limits ? windVerdict(speed, gust ?? null, limits) : null;
  const card = dir !== null ? degToCardinalFr(dir) : "variable";
  return (
    <span className={`wind-text ${v ? VERDICT_CLASS[v] : ""}`} title={dir !== null ? `Vent de ${card} (${Math.round(dir)}°) — la flèche indique où va le vent` : undefined}>
      {dir !== null ? <ArrowUp size={compact ? 13 : 15} aria-hidden style={{ transform: `rotate(${normalizeDeg(dir + 180)}deg)` }} className="wind-text__arrow" /> : null}
      <span className="wind-text__dir">{card}</span>
      <span className="num">
        {" "}
        {Math.round(speed)}
        {gust !== null && gust !== undefined && gust > speed ? <span className="wind-text__gust">/{Math.round(gust)}</span> : null} km/h
      </span>
    </span>
  );
}
