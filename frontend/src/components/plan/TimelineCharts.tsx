import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Difficulty, FlightPlan } from "../../api/types";
import { takeoffLimits } from "../../config/thresholds";
import { formatNumber, formatTime } from "../../utils/format";

interface Row {
  t: number;
  wind: number;
  gust: number;
  vario: number;
  ceiling: number;
  base: number | null;
  rain: number;
}

const AXIS = { fontSize: 11, fill: "var(--text-muted)" };
const tickTime = (v: number) => formatTime(new Date(v));

function ChartTooltip({ active, payload, label, unit }: { active?: boolean; payload?: { name: string; value: number | null; color: string }[]; label?: number; unit: string }) {
  if (!active || !payload?.length || label === undefined) return null;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__t">{formatTime(new Date(label))}</div>
      {payload.map((p) =>
        p.value === null ? null : (
          <div key={p.name} className="chart-tooltip__row">
            <i style={{ background: p.color }} />
            {p.name} <strong className="num">{formatNumber(p.value, unit === "m/s" || unit === "mm/h" ? 1 : 0)}</strong> {unit}
          </div>
        ),
      )}
    </div>
  );
}

/**
 * Évolution détaillée au déco sur la fenêtre ±3 h : petits multiples alignés (un axe par graphique),
 * créneau de décollage surligné, heure cible marquée.
 */
export function TimelineCharts({ plan, level }: { plan: FlightPlan; level: Difficulty }) {
  const rows: Row[] = plan.weather.timeline.map((w) => ({
    t: new Date(w.time).getTime(),
    wind: w.wind_10m.speed_kmh,
    gust: w.wind_10m.gust_kmh,
    vario: w.thermal_strength_ms,
    ceiling: w.thermal_ceiling_m,
    base: w.cloud_base_m,
    rain: w.precipitation_mm_h,
  }));
  if (rows.length < 2) return <p className="muted small">Pas de chronologie disponible.</p>;
  const ws = new Date(plan.window.start).getTime();
  const we = new Date(plan.window.end).getTime();
  const target = new Date(plan.target_time).getTime();
  const domain: [number, number] = [rows[0]!.t, rows[rows.length - 1]!.t];
  const lim = takeoffLimits(level, plan.flight_type);
  const common = {
    data: rows,
    margin: { top: 6, right: 12, bottom: 0, left: 0 },
    syncId: "timeline",
  };
  const xAxis = <XAxis dataKey="t" type="number" domain={domain} scale="time" tickFormatter={tickTime} tick={AXIS} stroke="var(--border)" ticks={rows.map((r) => r.t)} />;
  const grid = <CartesianGrid stroke="var(--chart-grid)" vertical={false} />;
  const windowArea = <ReferenceArea x1={Math.max(ws, domain[0])} x2={Math.min(we, domain[1])} fill="var(--accent)" fillOpacity={0.1} ifOverflow="hidden" />;
  const targetLine = <ReferenceLine x={target} stroke="var(--text-muted)" strokeDasharray="3 3" />;
  const hasRain = rows.some((r) => r.rain > 0);
  const maxWind = Math.max(...rows.map((r) => r.gust), lim.wind + 5);

  return (
    <div className="timeline-charts">
      <div className="mini-chart">
        <div className="mini-chart__head">
          <span className="mini-chart__title">Vent au déco (km/h)</span>
          <span className="chart-legend">
            <span>
              <i className="sw sw--line" style={{ background: "var(--series-1)" }} /> moyen
            </span>
            <span>
              <i className="sw sw--line" style={{ background: "var(--series-2)" }} /> rafales
            </span>
            <span>
              <i className="sw sw--dash" style={{ borderColor: "var(--nogo)" }} /> max niveau ({lim.wind})
            </span>
          </span>
        </div>
        <ResponsiveContainer width="100%" height={130}>
          <LineChart {...common}>
            {grid}
            {windowArea}
            {xAxis}
            <YAxis tick={AXIS} stroke="var(--border)" width={34} domain={[0, Math.ceil(maxWind / 5) * 5]} allowDecimals={false} />
            <ReferenceLine y={lim.wind} stroke="var(--nogo)" strokeDasharray="5 4" />
            {targetLine}
            <Tooltip content={<ChartTooltip unit="km/h" />} />
            <Line type="monotone" dataKey="wind" name="Moyen" stroke="var(--series-1)" strokeWidth={2} dot={{ r: 2.5 }} isAnimationActive={false} />
            <Line type="monotone" dataKey="gust" name="Rafales" stroke="var(--series-2)" strokeWidth={2} dot={{ r: 2.5 }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="mini-chart">
        <div className="mini-chart__head">
          <span className="mini-chart__title">Plafond et base des nuages (m)</span>
          <span className="chart-legend">
            <span>
              <i className="sw sw--line" style={{ background: "var(--series-1)" }} /> plafond thermique
            </span>
            <span>
              <i className="sw sw--dash" style={{ borderColor: "var(--series-3)" }} /> base cumulus
            </span>
          </span>
        </div>
        <ResponsiveContainer width="100%" height={130}>
          <LineChart {...common}>
            {grid}
            {windowArea}
            {xAxis}
            <YAxis tick={AXIS} stroke="var(--border)" width={42} domain={["dataMin - 200", "dataMax + 200"]} tickFormatter={(v: number) => formatNumber(Math.round(v / 100) * 100)} />
            <ReferenceLine y={plan.takeoff.elevation_m} stroke="var(--text-faint)" strokeDasharray="6 4" label={{ value: "déco", position: "insideBottomLeft", fontSize: 10, fill: "var(--text-muted)" }} />
            {targetLine}
            <Tooltip content={<ChartTooltip unit="m" />} />
            <Line type="monotone" dataKey="ceiling" name="Plafond" stroke="var(--series-1)" strokeWidth={2} dot={{ r: 2.5 }} isAnimationActive={false} />
            <Line type="monotone" dataKey="base" name="Base" stroke="var(--series-3)" strokeWidth={2} strokeDasharray="6 3" dot={{ r: 2.5 }} connectNulls={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="mini-chart">
        <div className="mini-chart__head">
          <span className="mini-chart__title">Vario moyen estimé (m/s)</span>
        </div>
        <ResponsiveContainer width="100%" height={100}>
          <BarChart {...common} barCategoryGap={6}>
            {grid}
            {windowArea}
            {xAxis}
            <YAxis tick={AXIS} stroke="var(--border)" width={34} allowDecimals />
            {targetLine}
            <Tooltip content={<ChartTooltip unit="m/s" />} cursor={{ fill: "var(--bg-hover)" }} />
            <Bar dataKey="vario" name="Vario" fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={22} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="mini-chart">
        <div className="mini-chart__head">
          <span className="mini-chart__title">Pluie (mm/h)</span>
          {!hasRain ? <span className="faint small">aucune pluie prévue</span> : null}
        </div>
        <ResponsiveContainer width="100%" height={hasRain ? 90 : 56}>
          <BarChart {...common} barCategoryGap={6}>
            {grid}
            {windowArea}
            {xAxis}
            <YAxis tick={AXIS} stroke="var(--border)" width={34} domain={[0, (max: number) => Math.max(1, Math.ceil(max))]} />
            {targetLine}
            <Tooltip content={<ChartTooltip unit="mm/h" />} cursor={{ fill: "var(--bg-hover)" }} />
            <Bar dataKey="rain" name="Pluie" fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={22} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="tiny faint">Zone bleutée : créneau de décollage · pointillé vertical : heure cible.</p>
    </div>
  );
}
