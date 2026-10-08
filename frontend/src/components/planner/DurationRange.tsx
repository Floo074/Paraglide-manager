import { formatDuration } from "../../utils/format";
import { DURATION_BOUNDS, DURATION_PRESETS } from "./criteria";

/** Double curseur min/max de durée de vol + raccourcis. */
export function DurationRange({ min, max, onChange }: { min: number; max: number; onChange: (min: number, max: number) => void }) {
  const { min: lo, max: hi, step } = DURATION_BOUNDS;
  const pct = (v: number) => ((v - lo) / (hi - lo)) * 100;
  const active = DURATION_PRESETS.find((p) => p.min === min && p.max === max)?.id;
  return (
    <div className="duration">
      <div className="duration__value num" aria-live="polite">
        {formatDuration(min)} – {formatDuration(max)}
      </div>
      <div className="dual-range">
        <div className="dual-range__track" />
        <div className="dual-range__fill" style={{ left: `${pct(min)}%`, right: `${100 - pct(max)}%` }} />
        <input
          type="range"
          min={lo}
          max={hi}
          step={step}
          value={min}
          aria-label="Durée minimale"
          aria-valuetext={formatDuration(min)}
          onChange={(e) => onChange(Math.min(Number(e.target.value), max - step), max)}
        />
        <input
          type="range"
          min={lo}
          max={hi}
          step={step}
          value={max}
          aria-label="Durée maximale"
          aria-valuetext={formatDuration(max)}
          onChange={(e) => onChange(min, Math.max(Number(e.target.value), min + step))}
        />
      </div>
      <div className="chips chips--compact" role="group" aria-label="Durées types">
        {DURATION_PRESETS.map((p) => (
          <button key={p.id} type="button" className={`chip${active === p.id ? " chip--on" : ""}`} onClick={() => onChange(p.min, p.max)} aria-pressed={active === p.id}>
            <span className="chip__label">{p.label}</span>
            <span className="chip__sub">{formatDuration(p.min)}–{formatDuration(p.max)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
