import { useMemo, useState } from "react";
import type { SoundingLevel } from "../../api/types";
import { formatNumber } from "../../utils/format";
import { degToCardinalFr } from "../../utils/units";
import { WindBarb } from "./WindBarb";

interface Props {
  sounding: SoundingLevel[];
  ceiling: number;
  cloudBase: number | null;
  takeoffAlt: number;
  surfaceTemp?: number;
}

const W = 560;
const H = 380;
const M = { top: 14, right: 64, bottom: 34, left: 52 };

/**
 * Émagramme simplifié : température et point de rosée en fonction de l'altitude (axes linéaires),
 * trajet de la particule (adiabatique sèche puis ≈ saturée), plafond utile, base des cumulus,
 * altitude du déco, isotherme 0 °C, barbules de vent.
 */
export function Emagram({ sounding, ceiling, cloudBase, takeoffAlt }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const levels = useMemo(() => [...sounding].sort((a, b) => a.altitude_m - b.altitude_m), [sounding]);
  if (levels.length < 2) return <p className="muted small">Sondage indisponible.</p>;
  const surface = levels[0]!;
  const top = Math.min(levels[levels.length - 1]!.altitude_m, Math.max(ceiling + 1500, 4000));
  const shown = levels.filter((l) => l.altitude_m <= top + 1);
  const yMin = Math.floor(surface.altitude_m / 500) * 500;
  const yMax = Math.ceil(top / 500) * 500;
  const temps = shown.flatMap((l) => [l.temperature_c, l.dew_point_c]);
  const tMin = Math.floor((Math.min(...temps) - 2) / 5) * 5;
  const tMax = Math.ceil((Math.max(...temps, surface.temperature_c + 2) + 2) / 5) * 5;
  const pw = W - M.left - M.right;
  const ph = H - M.top - M.bottom;
  const x = (t: number) => M.left + ((t - tMin) / (tMax - tMin)) * pw;
  const y = (a: number) => M.top + ph - ((a - yMin) / (yMax - yMin)) * ph;

  // particule : adiabatique sèche depuis T sol, puis ≈ 6 °C/km au-dessus de la base
  const t0 = surface.temperature_c;
  const lcl = cloudBase ?? ceiling;
  const parcel: [number, number][] = [];
  for (let a = surface.altitude_m; a <= Math.min(yMax, ceiling + 600); a += 50) {
    const t = a <= lcl ? t0 - 0.0098 * (a - surface.altitude_m) : t0 - 0.0098 * (lcl - surface.altitude_m) - 0.006 * (a - lcl);
    parcel.push([x(t), y(a)]);
  }
  const line = (pts: [number, number][]) => pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const tPath = line(shown.map((l) => [x(l.temperature_c), y(l.altitude_m)]));
  const tdPath = line(shown.map((l) => [x(l.dew_point_c), y(l.altitude_m)]));
  const yTicks: number[] = [];
  for (let a = yMin; a <= yMax; a += 500) yTicks.push(a);
  const xTicks: number[] = [];
  for (let t = tMin; t <= tMax; t += 5) xTicks.push(t);
  const hl = hover !== null ? shown[hover] : null;

  const onMove = (e: React.PointerEvent<SVGRectElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const py = ((e.clientY - rect.top) / rect.height) * ph;
    const alt = yMin + ((ph - py) / ph) * (yMax - yMin);
    let best = 0;
    shown.forEach((l, i) => {
      if (Math.abs(l.altitude_m - alt) < Math.abs(shown[best]!.altitude_m - alt)) best = i;
    });
    setHover(best);
  };

  return (
    <figure className="emagram">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Émagramme simplifié : température et point de rosée selon l'altitude">
        <rect x={M.left} y={M.top} width={pw} height={ph} fill="var(--bg-elev)" stroke="var(--border)" />
        {yTicks.map((a) => (
          <g key={a}>
            <line x1={M.left} x2={M.left + pw} y1={y(a)} y2={y(a)} stroke="var(--chart-grid)" />
            <text x={M.left - 6} y={y(a) + 4} textAnchor="end" className="chart-tick">
              {formatNumber(a)}
            </text>
          </g>
        ))}
        {xTicks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={M.top} y2={M.top + ph} stroke="var(--chart-grid)" />
            <text x={x(t)} y={M.top + ph + 16} textAnchor="middle" className="chart-tick">
              {t}
            </text>
          </g>
        ))}
        {tMin < 0 && tMax > 0 ? (
          <g>
            <line x1={x(0)} x2={x(0)} y1={M.top} y2={M.top + ph} stroke="var(--series-1)" strokeDasharray="2 3" />
            <text x={x(0) + 3} y={M.top + 11} className="chart-note">
              0 °C
            </text>
          </g>
        ) : null}
        {/* repères d'altitude */}
        <line x1={M.left} x2={M.left + pw} y1={y(takeoffAlt)} y2={y(takeoffAlt)} stroke="var(--text-faint)" strokeDasharray="6 4" />
        <text x={M.left + 4} y={y(takeoffAlt) - 4} className="chart-note">
          Déco {formatNumber(takeoffAlt)} m
        </text>
        <line x1={M.left} x2={M.left + pw} y1={y(ceiling)} y2={y(ceiling)} stroke="var(--go)" strokeWidth={2} />
        <text x={M.left + pw - 4} y={y(ceiling) - 4} textAnchor="end" className="chart-note chart-note--strong">
          Plafond utile {formatNumber(ceiling)} m
        </text>
        {cloudBase !== null ? (
          <g>
            <line x1={M.left} x2={M.left + pw} y1={y(cloudBase)} y2={y(cloudBase)} stroke="var(--text-muted)" strokeWidth={2} strokeDasharray="8 4" />
            <text x={M.left + pw - 4} y={y(cloudBase) - 4} textAnchor="end" className="chart-note">
              Base des cumulus {formatNumber(cloudBase)} m
            </text>
          </g>
        ) : null}
        <path d={line(parcel)} fill="none" stroke="var(--marginal)" strokeWidth={1.5} strokeDasharray="5 4" />
        <path d={tdPath} fill="none" stroke="var(--series-1)" strokeWidth={2} />
        <path d={tPath} fill="none" stroke="var(--series-temp)" strokeWidth={2} />
        {/* barbules (une sur deux si trop serrées) */}
        {shown
          .filter((l, i, arr) => i === 0 || y(arr[i - 1]!.altitude_m) - y(l.altitude_m) >= 16 || i % 2 === 0)
          .map((l, i) => (
            <WindBarb key={i} x={M.left + pw + 34} y={y(l.altitude_m)} speedKmh={l.wind_speed_kmh} dirDeg={l.wind_direction_deg} size={20} color="var(--text)" />
          ))}
        <text x={M.left + pw + 34} y={M.top + ph + 16} textAnchor="middle" className="chart-tick">
          vent
        </text>
        <text x={M.left + pw / 2} y={H - 4} textAnchor="middle" className="chart-axis">
          Température (°C)
        </text>
        <text x={12} y={M.top + ph / 2} textAnchor="middle" className="chart-axis" transform={`rotate(-90 12 ${M.top + ph / 2})`}>
          Altitude (m)
        </text>
        {hl ? (
          <g pointerEvents="none">
            <line x1={M.left} x2={M.left + pw} y1={y(hl.altitude_m)} y2={y(hl.altitude_m)} stroke="var(--text)" strokeOpacity={0.4} />
            <circle cx={x(hl.temperature_c)} cy={y(hl.altitude_m)} r={4} fill="var(--series-temp)" stroke="var(--bg-elev)" strokeWidth={2} />
            <circle cx={x(hl.dew_point_c)} cy={y(hl.altitude_m)} r={4} fill="var(--series-1)" stroke="var(--bg-elev)" strokeWidth={2} />
          </g>
        ) : null}
        <rect x={M.left} y={M.top} width={pw} height={ph} fill="transparent" onPointerMove={onMove} onPointerLeave={() => setHover(null)} />
      </svg>
      <figcaption className="chart-legend">
        <span>
          <i className="sw sw--line" style={{ background: "var(--series-temp)" }} /> Température
        </span>
        <span>
          <i className="sw sw--line" style={{ background: "var(--series-1)" }} /> Point de rosée
        </span>
        <span>
          <i className="sw sw--dash" style={{ borderColor: "var(--marginal)" }} /> Particule (thermique)
        </span>
        {hl ? (
          <span className="chart-readout num">
            {formatNumber(hl.altitude_m)} m · {hl.pressure_hpa} hPa · T {formatNumber(hl.temperature_c, 1)} °C · Td {formatNumber(hl.dew_point_c, 1)} °C · vent{" "}
            {degToCardinalFr(hl.wind_direction_deg)} {hl.wind_speed_kmh} km/h
          </span>
        ) : (
          <span className="faint">Survole le graphique pour lire un niveau.</span>
        )}
      </figcaption>
    </figure>
  );
}
