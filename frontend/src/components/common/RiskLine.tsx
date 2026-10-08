import { AlertOctagon, AlertTriangle, Info } from "lucide-react";
import type { Risk } from "../../api/types";
import { RISK_LEVEL } from "../../config/labels";

export const RISK_ORDER = { danger: 0, caution: 1, info: 2 } as const;

export function sortRisks(risks: Risk[]): Risk[] {
  return [...risks].sort((a, b) => RISK_ORDER[a.level] - RISK_ORDER[b.level]);
}

export function RiskIcon({ level, size = 15 }: { level: Risk["level"]; size?: number }) {
  const Icon = level === "danger" ? AlertOctagon : level === "caution" ? AlertTriangle : Info;
  return <Icon size={size} aria-label={RISK_LEVEL[level].label} className={`risk-icon risk-icon--${level}`} />;
}

/** Risque sur une ligne (titre seul). */
export function RiskLine({ risk }: { risk: Risk }) {
  return (
    <li className={`risk-line ${RISK_LEVEL[risk.level].className}`}>
      <RiskIcon level={risk.level} />
      <span>{risk.title}</span>
    </li>
  );
}
