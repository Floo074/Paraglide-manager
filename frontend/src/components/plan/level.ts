import type { Difficulty, FlightPlan } from "../../api/types";
import { DIFFICULTY_ORDER } from "../../config/labels";
import { loadJson } from "../../utils/storage";

/** Niveau utilisé pour colorer les vents : celui choisi dans les critères, sinon la difficulté du plan. */
export function pilotLevel(plan: FlightPlan): Difficulty {
  const c = loadJson<{ difficulty?: Difficulty } | null>("pm.criteria.v1", null);
  return c?.difficulty && DIFFICULTY_ORDER.includes(c.difficulty) ? c.difficulty : plan.difficulty;
}
