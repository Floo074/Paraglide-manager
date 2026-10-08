import { AlertTriangle, CloudOff, FlaskConical, HelpCircle } from "lucide-react";
import type { Difficulty, Horizon, PlanResponse } from "../../api/types";
import { splitReasonCode } from "../../api/errors";
import { isDemoMode } from "../../api/client";
import { RISK_CODE_LABEL } from "../../config/labels";
import { HORIZONS } from "../../utils/horizon";
import { formatDayTime } from "../../utils/format";
import { describeZone } from "../../utils/zone";
import { Disclaimer } from "../layout/Disclaimer";
import { PlanCard } from "./PlanCard";

export function ResultsPanel({
  response,
  level,
  stale,
  hovered,
  onHover,
  onTryHorizon,
  now,
}: {
  response: PlanResponse;
  level: Difficulty;
  stale: boolean;
  hovered: string | null;
  onHover: (id: string | null) => void;
  onTryHorizon: (h: Horizon) => void;
  now: Date;
}) {
  const demo = response.data_mode === "mock" ? (isDemoMode() || response.request_id.startsWith("demo-") ? "offline" : "server") : null;
  const empty = response.plans.length === 0;
  const others = HORIZONS.filter((h) => h.value !== response.horizon);
  return (
    <div className="results">
      <div className="results__head">
        <div>
          <div className="results__target">
            Pour <strong>{formatDayTime(response.target_time, now)}</strong> <span className="faint">(heure locale)</span>
          </div>
          <div className="small muted">
            Horizon {HORIZONS.find((h) => h.value === response.horizon)?.label} · {describeZone(response.zone)} · {response.plans.length} plan
            {response.plans.length > 1 ? "s" : ""}
          </div>
        </div>
      </div>
      {demo ? (
        <div className="alert alert--demo" role="note">
          <FlaskConical size={16} aria-hidden />
          <span>
            <strong>{demo === "offline" ? "Démo hors-ligne" : "Serveur en mode démo"} : données synthétiques.</strong> Les plans ci-dessous ne reflètent pas la
            météo réelle.
          </span>
        </div>
      ) : null}
      {stale ? (
        <div className="alert alert--info" role="status">
          Critères modifiés depuis ce calcul : relance la recherche pour mettre à jour.
        </div>
      ) : null}
      {response.warnings
        .filter((w) => !(demo === "offline" && w.startsWith("Démo hors-ligne")))
        .map((w, i) => (
          <div key={i} className="alert alert--caution">
            <AlertTriangle size={16} aria-hidden />
            <span>{w}</span>
          </div>
        ))}

      {empty ? (
        <div className="empty">
          <CloudOff size={28} aria-hidden />
          <h3>Rien de volable dans la zone à cette heure</h3>
          <p className="muted small">Les raisons sont détaillées ci-dessous. Essaie un autre horizon :</p>
          <div className="chips chips--compact" role="group" aria-label="Autres horizons">
            {others.map((h) => (
              <button key={h.value} type="button" className="chip" onClick={() => onTryHorizon(h.value)}>
                <span className="chip__label">{h.label}</span>
              </button>
            ))}
          </div>
        </div>
      ) : (
        <ol className="plan-list">
          {response.plans.map((p) => (
            <li key={p.id}>
              <PlanCard plan={p} level={level} demo={demo} active={hovered === p.id} onHover={onHover} />
            </li>
          ))}
        </ol>
      )}

      {response.rejected.length ? (
        <details className="rejected" open={empty}>
          <summary>
            <HelpCircle size={16} aria-hidden /> Pourquoi pas ces sites ? <span className="badge badge--neutral">{response.rejected.length}</span>
          </summary>
          <ul className="rejected__list">
            {response.rejected.map((r) => (
              <li key={r.site.id}>
                <div className="rejected__name">{r.site.name}</div>
                <ul className="rejected__reasons">
                  {r.reasons.map((reason, i) => {
                    const { code, text } = splitReasonCode(reason);
                    return (
                      <li key={i}>
                        {code ? <span className="code-chip" title={code}>{RISK_CODE_LABEL[code] ?? code}</span> : null}
                        <span>{text}</span>
                      </li>
                    );
                  })}
                </ul>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <Disclaimer compact />
    </div>
  );
}
