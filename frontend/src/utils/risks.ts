import type { Risk } from "../api/types";

export const RISK_ORDER = { danger: 0, caution: 1, info: 2 } as const;

/** Tri danger > prudence > info (ordre stable). */
export function sortRisks(risks: Risk[]): Risk[] {
  return [...risks].sort((a, b) => RISK_ORDER[a.level] - RISK_ORDER[b.level]);
}
