import { AlertTriangle, FlaskConical, RefreshCw } from "lucide-react";
import type { Difficulty, LandingAnalyzeResponse } from "../../api/types";
import { FREE_MODE_WARNING } from "../../config/labels";
import { formatAltitude, formatDayTime } from "../../utils/format";
import { compassFr } from "../../utils/units";
import { LandingCandidateList, LandingKindLegend } from "../landing/LandingCandidates";

/** Onglet « Atterros » : résultat de POST /api/landings/analyze (cône de finesse sur la carte). */
export function LandingAnalysisPanel({
  analysis,
  level,
  stale,
  selectedId,
  onSelect,
  onReanalyze,
  now,
  demo,
}: {
  analysis: LandingAnalyzeResponse;
  level: Difficulty;
  stale: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onReanalyze: () => void;
  now: Date;
  demo: boolean;
}) {
  const t = analysis.takeoff;
  return (
    <div className="results">
      <div className="results__head">
        <div>
          <div className="results__target">
            Atterros depuis <strong>{t.name}</strong>
          </div>
          <div className="small muted">
            {formatAltitude(t.elevation_m)}
            {t.orientations.length ? ` · ${t.orientations.map(compassFr).join(", ")}` : ""} · départ {formatDayTime(analysis.target_time, now)}{" "}
            <span className="faint">(heure locale)</span>
          </div>
        </div>
      </div>
      <div className="alert alert--caution" role="note">
        <AlertTriangle size={16} aria-hidden />
        <span>
          <strong>{FREE_MODE_WARNING}.</strong>
        </span>
      </div>
      {demo ? (
        <div className="alert alert--demo" role="note">
          <FlaskConical size={16} aria-hidden />
          <span>
            <strong>Démo hors-ligne :</strong> relief, vent et atterros non officiels simulés.
          </span>
        </div>
      ) : null}
      {stale ? (
        <div className="alert alert--info" role="status">
          <span className="grow">Déco ou critères modifiés depuis cette analyse.</span>
          <button type="button" className="btn btn--sm" onClick={onReanalyze}>
            <RefreshCw size={14} aria-hidden /> Relancer
          </button>
        </div>
      ) : null}
      {analysis.warnings
        .filter((w) => !(demo && w.startsWith("Démo hors-ligne")) && !w.startsWith("Atterrissages non officiels"))
        .map((w, i) => (
          <div key={i} className="alert alert--caution">
            <AlertTriangle size={16} aria-hidden />
            <span>{w}</span>
          </div>
        ))}
      <LandingKindLegend />
      <p className="tiny faint">Polygone violet sur la carte : cône de finesse (zone atteignable avec marge, vent compris). Touche un atterro pour voir sa fiche.</p>
      {analysis.candidates.length ? (
        <LandingCandidateList candidates={analysis.candidates} level={level} from={t} selectedId={selectedId} onSelect={onSelect} firstLabel="Meilleur choix" />
      ) : (
        <div className="empty">
          <h3>Aucun atterrissage atteignable avec marge</h3>
          <p className="muted small">Essaie un point plus haut, une autre politique d'atterrissage, ou un site officiel.</p>
        </div>
      )}
    </div>
  );
}
