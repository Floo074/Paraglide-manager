import { AlertTriangle, Crosshair, Landmark, Loader2, LocateFixed, MapPin, Trash2 } from "lucide-react";
import type { LandingAnalyzeResponse, LandingPolicy } from "../../api/types";
import { FREE_MODE_WARNING, LANDING_POLICY_OPTIONS } from "../../config/labels";
import { formatAltitude, formatNumber } from "../../utils/format";
import { COMPASS_16, compassFr } from "../../utils/units";
import { ChipGroup, ChipMulti } from "../ui/Chips";
import type { Criteria, FreeTakeoff } from "./criteria";

const fmtCoord = (v: number, pos: string, neg: string) => `${formatNumber(Math.abs(v), 5, 5)}° ${v >= 0 ? pos : neg}`;

/**
 * Décollage libre : point posé sur la carte (marqueur déplaçable), altitude et orientations
 * facultatives, politique d'atterrissage, analyse des atterrissages (cône de finesse + candidats).
 */
export function FreeTakeoffSection({
  criteria,
  setCriteria,
  takeoff,
  onTakeoff,
  picking,
  onPicking,
  onLocate,
  locating,
  onAnalyze,
  analyzing,
  analysisError,
  analysis,
  analysisStale,
  onShowAnalysis,
}: {
  criteria: Criteria;
  setCriteria: (c: Criteria) => void;
  takeoff: FreeTakeoff | null;
  onTakeoff: (t: FreeTakeoff | null) => void;
  picking: boolean;
  onPicking: (on: boolean) => void;
  onLocate: () => void;
  locating: boolean;
  onAnalyze: () => void;
  analyzing: boolean;
  analysisError: string | null;
  analysis: LandingAnalyzeResponse | null;
  analysisStale: boolean;
  onShowAnalysis: () => void;
}) {
  const set = <K extends keyof FreeTakeoff>(k: K, v: FreeTakeoff[K]) => takeoff && onTakeoff({ ...takeoff, [k]: v });
  const beginner = criteria.difficulty === "beginner";
  const policy = LANDING_POLICY_OPTIONS.find((p) => p.value === criteria.landingPolicy);
  return (
    <>
      <div className="alert alert--caution free-warning" role="note">
        <AlertTriangle size={16} aria-hidden />
        <span>
          <strong>{FREE_MODE_WARNING}.</strong> Décollage hors site officiel : autorisation, reconnaissance à pied et manche à air obligatoires.
        </span>
      </div>
      {beginner ? (
        <div className="alert alert--danger" role="alert">
          Décollage libre jamais proposé au niveau élève (cahier des charges pilote) : la recherche ne renverra aucun vol. Choisis un site officiel encadré.
        </div>
      ) : null}

      <section className="field" aria-labelledby="f-free">
        <h3 className="field__label" id="f-free">
          <MapPin size={16} aria-hidden /> Point de décollage
          {takeoff ? (
            <span className="field__aside num">
              {fmtCoord(takeoff.lat, "N", "S")} · {fmtCoord(takeoff.lon, "E", "O")}
            </span>
          ) : null}
        </h3>
        {!takeoff ? (
          <p className="hint">
            {picking ? "Touche la carte à l'endroit du décollage." : "Pose le décollage sur la carte (ou utilise ta position)."} Altitude et orientation sont déduites du relief si tu ne les
            indiques pas.
          </p>
        ) : (
          <p className="hint">Marqueur violet déplaçable sur la carte.</p>
        )}
        <div className="row row--wrap">
          <button type="button" className={`btn btn--sm${picking ? " btn--primary" : ""}`} onClick={() => onPicking(!picking)} aria-pressed={picking}>
            <Crosshair size={15} aria-hidden /> {picking ? "Touche la carte…" : takeoff ? "Reposer sur la carte" : "Poser sur la carte"}
          </button>
          <button type="button" className="btn btn--sm" onClick={onLocate} disabled={locating}>
            {locating ? <Loader2 size={15} className="spin" aria-hidden /> : <LocateFixed size={15} aria-hidden />} Ma position
          </button>
          {takeoff ? (
            <button type="button" className="btn btn--sm" onClick={() => onTakeoff(null)}>
              <Trash2 size={15} aria-hidden /> Effacer
            </button>
          ) : null}
        </div>
        {takeoff ? (
          <div className="free-fields">
            <label className="field-row">
              <span>Nom</span>
              <input className="input" type="text" maxLength={60} placeholder="ex. Sommet de la Tournette" value={takeoff.name} onChange={(e) => set("name", e.target.value)} />
            </label>
            <label className="field-row">
              <span>Altitude (m)</span>
              <input
                className="input input--num"
                type="number"
                inputMode="numeric"
                min={0}
                max={5000}
                step={10}
                placeholder={analysis && !analysisStale ? String(analysis.takeoff.elevation_m) : "relief"}
                value={takeoff.elevation ?? ""}
                onChange={(e) => {
                  const v = e.target.value === "" ? null : Number(e.target.value);
                  set("elevation", v === null || !Number.isFinite(v) ? null : Math.max(0, Math.min(5000, v)));
                }}
              />
              {analysis && !analysisStale && takeoff.elevation === null ? <span className="tiny faint">relief : {formatAltitude(analysis.takeoff.elevation_m)}</span> : null}
            </label>
            <fieldset className="free-orient">
              <legend className="small">
                Orientations du décollage <span className="faint">(d'où doit venir le vent)</span>
              </legend>
              <ChipMulti<string>
                label="Orientations du décollage"
                className="chips--compass"
                values={takeoff.orientations}
                onChange={(v) => set("orientations", COMPASS_16.filter((p) => v.includes(p)))}
                options={COMPASS_16.map((p) => ({ value: p, label: compassFr(p) }))}
              />
              <p className="hint">
                {takeoff.orientations.length
                  ? `${takeoff.orientations.map(compassFr).join(", ")}`
                  : analysis && !analysisStale
                    ? `Aucune cochée : déduite de la pente (${analysis.takeoff.orientations.map(compassFr).join(", ") || "?"}).`
                    : "Aucune cochée : déduite de la pente."}
              </p>
            </fieldset>
          </div>
        ) : null}
      </section>

      <section className="field" aria-labelledby="f-policy">
        <h3 className="field__label" id="f-policy">
          <Landmark size={16} aria-hidden /> Atterrissages acceptés
        </h3>
        <ChipGroup<LandingPolicy>
          label="Atterrissages acceptés"
          className="chips--fill"
          value={criteria.landingPolicy}
          onChange={(v) => setCriteria({ ...criteria, landingPolicy: v })}
          options={LANDING_POLICY_OPTIONS.map((p) => ({ value: p.value, label: p.label, title: p.description }))}
        />
        <p className="hint">{policy?.description}</p>
        <button type="button" className="btn btn--block" onClick={onAnalyze} disabled={!takeoff || analyzing}>
          {analyzing ? <Loader2 size={16} className="spin" aria-hidden /> : <Landmark size={16} aria-hidden />}
          {analyzing ? "Analyse en cours…" : "Analyser les atterrissages"}
        </button>
        {analysisError ? (
          <p className="field__error" role="alert">
            {analysisError}
          </p>
        ) : null}
        {analysis ? (
          <p className="small">
            {analysisStale ? <span className="text-marginal">Paramètres modifiés : relance l'analyse. </span> : null}
            <button type="button" className="link-btn" onClick={onShowAnalysis}>
              {analysis.candidates.length} atterrissage{analysis.candidates.length > 1 ? "s" : ""} atteignable{analysis.candidates.length > 1 ? "s" : ""} — voir la liste
            </button>
          </p>
        ) : null}
      </section>
    </>
  );
}
