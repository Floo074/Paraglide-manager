import type { FlightPlan } from "../../api/types";
import { altitudeColor } from "../../utils/colors";
import { kmPerDegLon, KM_PER_DEG_LAT } from "../../utils/geo";

/** Croquis vectoriel de la route (sans fond de carte) pour la feuille de vol imprimée. */
export function RouteSketch({ plan }: { plan: FlightPlan }) {
  const W = 640;
  const H = 300;
  const pts = [
    ...plan.route.coordinates.map((c) => ({ lat: c[1], lon: c[0] })),
    ...plan.waypoints.map((w) => ({ lat: w.lat, lon: w.lon })),
  ];
  const lat0 = pts.reduce((s, p) => s + p.lat, 0) / pts.length;
  const kx = kmPerDegLon(lat0);
  const xs = pts.map((p) => p.lon * kx);
  const ys = pts.map((p) => p.lat * KM_PER_DEG_LAT);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const span = Math.max(maxX - minX, (maxY - minY) * (W / H), 1);
  const scale = (W - 40) / span;
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  const P = (lat: number, lon: number): [number, number] => [W / 2 + (lon * kx - cx) * scale, H / 2 - (lat * KM_PER_DEG_LAT - cy) * scale];
  const alts = plan.route.coordinates.map((c) => c[2]);
  const min = Math.min(...alts), max = Math.max(...alts);
  const kmBar = [1, 2, 5, 10, 20, 50].find((k) => k * scale > 60) ?? 50;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="route-sketch" role="img" aria-label="Croquis de la route">
      <rect width={W} height={H} fill="none" stroke="#999" />
      {plan.route.coordinates.slice(1).map((c, i) => {
        const a = plan.route.coordinates[i]!;
        const [x1, y1] = P(a[1], a[0]);
        const [x2, y2] = P(c[1], c[0]);
        return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke={altitudeColor((a[2] + c[2]) / 2, min, max)} strokeWidth={3} strokeLinecap="round" />;
      })}
      {plan.waypoints.map((w, i) => {
        const [x, y] = P(w.lat, w.lon);
        return (
          <g key={i}>
            <circle cx={x} cy={y} r={5} fill={w.type === "landing" ? "#1d4ed8" : w.type === "takeoff" ? "#15803d" : w.type === "alternate_landing" ? "#64748b" : "#7c3aed"} stroke="#fff" strokeWidth={1.5} />
            <text x={x + 7} y={y - 6} fontSize={11} fill="#111">
              {w.name}
            </text>
          </g>
        );
      })}
      <g transform={`translate(16 ${H - 16})`}>
        <line x1={0} x2={kmBar * scale} y1={0} y2={0} stroke="#111" strokeWidth={2} />
        <text x={0} y={-5} fontSize={10}>
          {kmBar} km
        </text>
      </g>
      <text x={W - 16} y={20} fontSize={12} textAnchor="end">
        N ↑
      </text>
    </svg>
  );
}
