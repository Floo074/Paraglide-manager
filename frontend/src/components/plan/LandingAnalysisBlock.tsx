import { AlertTriangle } from "lucide-react";
import type { Difficulty, FlightPlan } from "../../api/types";
import { FREE_MODE_WARNING } from "../../config/labels";
import { LandingCandidateList, LandingKindLegend } from "../landing/LandingCandidates";

/** Section « Analyse des atterrissages » (FlightPlan.landing_analysis, le 1er = atterro retenu). */
export function LandingAnalysisBlock({ plan, level }: { plan: FlightPlan; level: Difficulty }) {
  const list = plan.landing_analysis;
  const unofficial = list.some((c) => c.kind !== "official") || plan.takeoff.source === "user";
  return (
    <section className="block" aria-labelledby="b-landings">
      <h2 id="b-landings" className="block__title">
        Analyse des atterrissages <span className="badge badge--neutral">{list.length}</span>
      </h2>
      {list.length === 0 ? (
        <p className="small muted">Pas d'analyse détaillée des atterrissages pour ce plan.</p>
      ) : (
        <>
          <p className="small muted">Atterros évalués depuis le déco (finesse vent compris, hauteur d'arrivée, terrain, vent à l'arrivée), du plus sûr au moins sûr.</p>
          {unofficial ? (
            <div className="alert alert--caution" role="note">
              <AlertTriangle size={16} aria-hidden />
              <span>{FREE_MODE_WARNING}.</span>
            </div>
          ) : null}
          <LandingKindLegend />
          <LandingCandidateList candidates={list} level={level} from={plan.takeoff} firstLabel="Atterro retenu" />
        </>
      )}
    </section>
  );
}
