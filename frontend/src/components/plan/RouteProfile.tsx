import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { FlightPlan } from "../../api/types";
import { formatNumber } from "../../utils/format";
import { haversineKm } from "../../utils/geo";

const AXIS = { fontSize: 11, fill: "var(--text-muted)" };

/** Profil d'altitude prévu le long de la route (distance cumulée). */
export function RouteProfile({ plan }: { plan: FlightPlan }) {
  let d = 0;
  const rows = plan.route.coordinates.map((c, i, arr) => {
    if (i > 0) d += haversineKm({ lat: arr[i - 1]![1], lon: arr[i - 1]![0] }, { lat: c[1], lon: c[0] });
    return { d: Math.round(d * 100) / 100, alt: c[2] };
  });
  if (rows.length < 2) return null;
  return (
    <figure className="mini-chart">
      <figcaption className="mini-chart__head">
        <span className="mini-chart__title">Profil d'altitude prévu (m)</span>
        <span className="faint small">plafond utile {formatNumber(plan.thermals.ceiling_m)} m</span>
      </figcaption>
      <ResponsiveContainer width="100%" height={120}>
        <AreaChart data={rows} margin={{ top: 6, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
          <XAxis dataKey="d" type="number" domain={[0, "dataMax"]} tick={AXIS} stroke="var(--border)" tickFormatter={(v: number) => `${formatNumber(v, 0)} km`} />
          <YAxis tick={AXIS} stroke="var(--border)" width={42} domain={[(min: number) => Math.floor((min - 100) / 100) * 100, (max: number) => Math.ceil((Math.max(max, plan.thermals.ceiling_m) + 100) / 100) * 100]} tickFormatter={(v: number) => formatNumber(v)} />
          <ReferenceLine y={plan.thermals.ceiling_m} stroke="var(--go)" strokeDasharray="5 4" />
          <ReferenceLine y={plan.landing.elevation_m} stroke="var(--text-faint)" strokeDasharray="3 3" />
          <Tooltip
            formatter={(v: number) => [`${formatNumber(v)} m`, "Altitude"]}
            labelFormatter={(l: number) => `${formatNumber(l, 1)} km`}
            contentStyle={{ background: "var(--bg-elev)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
          />
          <Area type="linear" dataKey="alt" stroke="var(--series-1)" strokeWidth={2} fill="var(--series-1)" fillOpacity={0.15} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </figure>
  );
}
