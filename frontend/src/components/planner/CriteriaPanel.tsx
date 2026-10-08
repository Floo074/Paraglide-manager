import { Clock, Gauge, Plane, Sun, Target, Timer, Wind } from "lucide-react";
import type { Difficulty, FlightType, Horizon, ThermalPreference, Zone } from "../../api/types";
import { DIFFICULTIES, FLIGHT_TYPES, THERMAL_PREFS } from "../../config/labels";
import { HORIZONS, targetTimeFromHorizon } from "../../utils/horizon";
import { formatDayTime, formatTime } from "../../utils/format";
import { ChipGroup, ChipMulti } from "../ui/Chips";
import type { Criteria } from "./criteria";
import { DurationRange } from "./DurationRange";
import { ZoneSection } from "./ZoneSection";

function shortTarget(d: Date, now: Date): string {
  const label = formatDayTime(d, now);
  return label.replace("aujourd'hui ", "").replace("demain ", "dem. ");
}

/** Convertit une date en valeur pour <input type="datetime-local"> (heure locale du navigateur). */
function toLocalInput(iso: string | null): string {
  const d = iso ? new Date(iso) : new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function CriteriaPanel({
  criteria,
  setCriteria,
  zone,
  onZone,
  now,
}: {
  criteria: Criteria;
  setCriteria: (c: Criteria) => void;
  zone: Zone;
  onZone: (z: Zone) => void;
  now: Date;
}) {
  const set = <K extends keyof Criteria>(k: K, v: Criteria[K]) => setCriteria({ ...criteria, [k]: v });
  const ref = criteria.referenceTime ? new Date(criteria.referenceTime) : now;
  const target = targetTimeFromHorizon(ref, criteria.horizon);

  return (
    <div className="criteria">
      <ZoneSection zone={zone} onZone={onZone} />

      <section className="field" aria-labelledby="f-horizon">
        <h3 className="field__label" id="f-horizon">
          <Clock size={16} aria-hidden /> Quand ?
          <span className="field__aside">
            cible <strong>{formatDayTime(target, now)}</strong> <span className="faint">(heure locale)</span>
          </span>
        </h3>
        <ChipGroup<Horizon>
          label="Horizon"
          className="chips--horizon"
          value={criteria.horizon}
          onChange={(v) => set("horizon", v)}
          options={HORIZONS.map((h) => ({
            value: h.value,
            label: h.label,
            sub: shortTarget(targetTimeFromHorizon(ref, h.value), now),
          }))}
        />
        <details className="advanced">
          <summary>Heure de référence : {criteria.referenceTime ? formatDayTime(ref, now) : `maintenant (${formatTime(now)})`}</summary>
          <div className="row row--wrap">
            <label className="sr-only" htmlFor="ref-time">
              Heure de référence
            </label>
            <input
              id="ref-time"
              type="datetime-local"
              className="input"
              value={toLocalInput(criteria.referenceTime)}
              onChange={(e) => set("referenceTime", e.target.value ? new Date(e.target.value).toISOString() : null)}
            />
            {criteria.referenceTime ? (
              <button type="button" className="btn btn--sm" onClick={() => set("referenceTime", null)}>
                Maintenant
              </button>
            ) : null}
          </div>
          <p className="hint">Pour préparer un vol à l'avance : l'horizon s'ajoute à cette heure.</p>
        </details>
      </section>

      <section className="field" aria-labelledby="f-duration">
        <h3 className="field__label" id="f-duration">
          <Timer size={16} aria-hidden /> Durée de vol souhaitée
        </h3>
        <DurationRange min={criteria.durationMin} max={criteria.durationMax} onChange={(a, b) => setCriteria({ ...criteria, durationMin: a, durationMax: b })} />
      </section>

      <section className="field" aria-labelledby="f-level">
        <h3 className="field__label" id="f-level">
          <Gauge size={16} aria-hidden /> Ton niveau <span className="field__aside">= difficulté max acceptée</span>
        </h3>
        <div className="level-list" role="radiogroup" aria-labelledby="f-level">
          {DIFFICULTIES.map((d, i) => (
            <label key={d.value} className={`level${criteria.difficulty === d.value ? " level--on" : ""}`}>
              <input type="radio" name="difficulty" className="sr-only" checked={criteria.difficulty === d.value} onChange={() => set("difficulty", d.value as Difficulty)} />
              <span className="level-dots" aria-hidden>
                {[0, 1, 2, 3].map((k) => (
                  <i key={k} className={k <= i ? "on" : ""} />
                ))}
              </span>
              <span className="level__text">
                <span className="level__title">
                  {d.label} <span className="level__short">{d.short}</span>
                </span>
                <span className="level__desc">{d.description}</span>
              </span>
            </label>
          ))}
        </div>
      </section>

      <section className="field" aria-labelledby="f-thermals">
        <h3 className="field__label" id="f-thermals">
          <Sun size={16} aria-hidden /> Thermiques
        </h3>
        <ChipGroup<ThermalPreference>
          label="Préférence thermique"
          className="chips--fill"
          value={criteria.thermals}
          onChange={(v) => set("thermals", v)}
          options={THERMAL_PREFS.map((t) => ({ value: t.value, label: t.label, title: t.description }))}
        />
        <p className="hint">{THERMAL_PREFS.find((t) => t.value === criteria.thermals)?.description}</p>
      </section>

      <section className="field" aria-labelledby="f-types">
        <h3 className="field__label" id="f-types">
          <Plane size={16} aria-hidden /> Types de vol
        </h3>
        <ChipMulti<FlightType>
          label="Types de vol"
          values={criteria.flightTypes}
          onChange={(v) => set("flightTypes", v)}
          options={FLIGHT_TYPES.map((t) => ({ value: t.value, label: t.label, title: t.description }))}
        />
        {criteria.flightTypes.length === 0 ? <p className="hint">Aucun type coché : tous les types seront proposés.</p> : null}
      </section>

      <section className="field field--inline" aria-labelledby="f-glide">
        <h3 className="field__label" id="f-glide">
          <Wind size={16} aria-hidden /> <label htmlFor="glide">Finesse de l'aile</label>
        </h3>
        <div className="row">
          <input
            id="glide"
            className="input input--num"
            type="number"
            inputMode="decimal"
            min={4}
            max={14}
            step={0.1}
            value={criteria.glide}
            onChange={(e) => {
              const v = Number(e.target.value);
              if (Number.isFinite(v)) set("glide", Math.min(14, Math.max(4, v)));
            }}
          />
          <span className="hint">EN-A ≈ 8, EN-B ≈ 8,5-9, EN-C ≈ 9,5-10</span>
        </div>
      </section>
      <p className="hint hint--center">
        <Target size={13} aria-hidden /> Le calcul tient compte d'une finesse de sécurité réduite selon ton niveau.
      </p>
    </div>
  );
}
