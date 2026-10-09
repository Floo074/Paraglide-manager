import { useId } from "react";

export interface ChipOption<T extends string> {
  value: T;
  label: React.ReactNode;
  sub?: React.ReactNode;
  title?: string;
}

/** Groupe de puces à choix unique (radiogroup accessible). */
export function ChipGroup<T extends string>({
  options,
  value,
  onChange,
  label,
  className = "",
}: {
  options: ChipOption<T>[];
  value: T;
  onChange: (v: T) => void;
  label: string;
  className?: string;
}) {
  const name = useId();
  return (
    <div className={`chips ${className}`} role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <label key={o.value} className={`chip${o.value === value ? " chip--on" : ""}`} title={o.title}>
          <input type="radio" name={name} value={o.value} checked={o.value === value} onChange={() => onChange(o.value)} className="sr-only" />
          <span className="chip__label">{o.label}</span>
          {o.sub ? <span className="chip__sub">{o.sub}</span> : null}
        </label>
      ))}
    </div>
  );
}

/** Groupe de puces à choix multiples. */
export function ChipMulti<T extends string>({
  options,
  values,
  onChange,
  label,
  className = "",
}: {
  options: ChipOption<T>[];
  values: T[];
  onChange: (v: T[]) => void;
  label: string;
  className?: string;
}) {
  return (
    <div className={`chips ${className}`} role="group" aria-label={label}>
      {options.map((o) => {
        const on = values.includes(o.value);
        return (
          <label key={o.value} className={`chip${on ? " chip--on" : ""}`} title={o.title}>
            <input
              type="checkbox"
              checked={on}
              className="sr-only"
              onChange={() => onChange(on ? values.filter((v) => v !== o.value) : [...values, o.value])}
            />
            <span className="chip__label">{o.label}</span>
            {o.sub ? <span className="chip__sub">{o.sub}</span> : null}
          </label>
        );
      })}
    </div>
  );
}
