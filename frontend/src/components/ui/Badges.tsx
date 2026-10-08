import { AlertOctagon, AlertTriangle, CheckCircle2 } from "lucide-react";
import type { Difficulty, Flyability } from "../../api/types";
import { FLYABILITY, difficultyLabel } from "../../config/labels";

export function FlyabilityBadge({ value, large = false }: { value: Flyability; large?: boolean }) {
  const f = FLYABILITY[value];
  const Icon = value === "go" ? CheckCircle2 : value === "marginal" ? AlertTriangle : AlertOctagon;
  return (
    <span className={`badge ${f.className}${large ? " badge--lg" : ""}`}>
      <Icon size={large ? 16 : 13} aria-hidden />
      {f.label}
    </span>
  );
}

const LEVEL_DOTS: Record<Difficulty, number> = { beginner: 1, intermediate: 2, advanced: 3, expert: 4 };

export function DifficultyBadge({ value, prefix }: { value: Difficulty; prefix?: string }) {
  const n = LEVEL_DOTS[value];
  return (
    <span className="badge badge--neutral" title={`Difficulté : ${difficultyLabel(value)}`}>
      <span className="level-dots" aria-hidden>
        {[1, 2, 3, 4].map((i) => (
          <i key={i} className={i <= n ? "on" : ""} />
        ))}
      </span>
      {prefix ? `${prefix} ` : ""}
      {difficultyLabel(value)}
    </span>
  );
}

export function Pill({ children, tone = "neutral", title }: { children: React.ReactNode; tone?: "neutral" | "go" | "marginal" | "nogo" | "info" | "demo"; title?: string }) {
  return (
    <span className={`badge badge--${tone}`} title={title}>
      {children}
    </span>
  );
}
