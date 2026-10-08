import { FlaskConical } from "lucide-react";
import type { FlightPlan } from "../../api/types";
import { difficultyLabel, difficultyShort } from "../../config/labels";
import { RiskLine } from "../common/RiskLine";
import { sortRisks } from "../../utils/risks";
import { FlyabilityBadge } from "../ui/Badges";

/** Bloc 1 : verdict, niveau requis, confiance, puis le « pourquoi » (risques danger/caution). */
export function VerdictBanner({ plan, demo }: { plan: FlightPlan; demo: boolean }) {
  const why = sortRisks(plan.risks.filter((r) => (r.level === "danger" || r.level === "caution") && r.code !== "MOCK_DATA"));
  return (
    <section className={`verdict verdict--${plan.flyability}`} aria-label="Verdict">
      <div className="verdict__row">
        <FlyabilityBadge value={plan.flyability} large />
        <div className="verdict__level">
          <span className="verdict__k">Niveau requis</span>
          <strong>{difficultyLabel(plan.difficulty)}</strong> <span className="faint small">({difficultyShort(plan.difficulty)})</span>
        </div>
        <div className="verdict__conf">
          <span className="verdict__k">Confiance</span>
          <strong className="num">{Math.round(plan.confidence * 100)} %</strong>
        </div>
      </div>
      {demo ? (
        <div className="demo-tag demo-tag--block">
          <FlaskConical size={14} aria-hidden /> Démo hors-ligne : données synthétiques — ne pas utiliser pour voler
        </div>
      ) : null}
      {why.length ? (
        <ul className="verdict__why" aria-label="Pourquoi">
          {why.map((r, i) => (
            <RiskLine key={i} risk={r} />
          ))}
        </ul>
      ) : (
        <p className="verdict__ok small">Aucun point de vigilance majeur relevé par l'outil.</p>
      )}
      {plan.flyability !== "no_go" ? (
        <p className="verdict__onsite small">L'analyse sur place (balises, ciel, manche à air, autres pilotes) prime toujours.</p>
      ) : null}
    </section>
  );
}
