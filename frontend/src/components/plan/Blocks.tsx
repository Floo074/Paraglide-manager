import { Check, ClipboardCopy, Phone, Radio, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import type { Difficulty, FlightPlan, Risk } from "../../api/types";
import { LANDING_KIND, RISK_CODE_LABEL, RISK_LEVEL, SOURCE_LABEL, criterionLabel } from "../../config/labels";
import { landingLimits, type WindLimits } from "../../config/thresholds";
import { copyToClipboard } from "../../utils/download";
import { waypointTypeLabel } from "../../utils/exports";
import { formatAge, formatAltitude, formatDuration, formatNumber, formatTime, formatVario } from "../../utils/format";
import { haversineKm } from "../../utils/geo";
import { landingKindOf } from "../../utils/landings";
import { LandingKindBadge } from "../landing/LandingCandidates";
import { loadJson, saveJson } from "../../utils/storage";
import { RiskIcon } from "../common/RiskLine";
import { sortRisks } from "../../utils/risks";
import { WindText } from "../common/WindText";
import { ScoreBar } from "../ui/ScoreGauge";
import { toast } from "../ui/toastBus";
import { fl } from "../map/mapHelpers";

/** Bloc 4 : briefing tel que reçu (ordre conservé, non tronqué). */
export function BriefingBlock({ plan }: { plan: FlightPlan }) {
  return (
    <section className="block" aria-labelledby="b-brief">
      <h2 id="b-brief" className="block__title">
        Briefing
      </h2>
      <ol className="briefing">
        {plan.briefing.map((b, i) => (
          <li key={i}>{b}</li>
        ))}
      </ol>
    </section>
  );
}

/** Bloc 6 : aérologie (plafond UTILE, base, vario, fenêtre convective, surdéveloppement). */
export function AerologyBlock({ plan, children }: { plan: FlightPlan; children?: React.ReactNode }) {
  const th = plan.thermals;
  const wx = plan.weather.takeoff;
  const od = { low: { label: "faible", cls: "wv--ok" }, moderate: { label: "modéré", cls: "wv--near" }, high: { label: "élevé", cls: "wv--over" } }[th.overdevelopment_risk];
  // frise 6 h → 21 h : fenêtre convective et créneau du vol
  const hourOf = (iso: string) => {
    const parts = new Intl.DateTimeFormat("fr-FR", { hour: "numeric", minute: "numeric", hour12: false, timeZone: "Europe/Paris" }).formatToParts(new Date(iso));
    const h = Number(parts.find((p) => p.type === "hour")?.value ?? 0);
    const m = Number(parts.find((p) => p.type === "minute")?.value ?? 0);
    return h + m / 60;
  };
  const pos = (h: number) => `${Math.max(0, Math.min(100, ((h - 6) / 15) * 100))}%`;
  return (
    <section className="block" aria-labelledby="b-aero">
      <h2 id="b-aero" className="block__title">
        Aérologie
      </h2>
      <div className="facts-grid">
        <div className="fact">
          <span className="fact__k">Thermiques</span>
          <span className="fact__v num">
            {th.convection_start ? formatTime(th.convection_start) : "—"} → {th.convection_end ? formatTime(th.convection_end) : "—"}
          </span>
          <span className="fact__s">pic {th.peak_time ? formatTime(th.peak_time) : "—"}</span>
        </div>
        <div className="fact">
          <span className="fact__k">Vario moyen</span>
          <span className="fact__v">{formatVario(wx.thermal_strength_ms)}</span>
          <span className="fact__s">pic de journée {formatVario(th.peak_strength_ms)}</span>
        </div>
        <div className="fact">
          <span className="fact__k">Plafond utile</span>
          <span className="fact__v">{formatAltitude(th.ceiling_m)}</span>
          <span className="fact__s">+{formatNumber(Math.max(0, th.ceiling_m - plan.takeoff.elevation_m))} m sur le déco</span>
        </div>
        <div className="fact">
          <span className="fact__k">Base des cumulus</span>
          <span className="fact__v">{wx.cloud_base_m !== null ? formatAltitude(wx.cloud_base_m) : "bleu"}</span>
          <span className="fact__s">{th.cumulus ? "cumulus" : "thermiques purs"}</span>
        </div>
        <div className="fact">
          <span className="fact__k">Surdéveloppement</span>
          <span className={`fact__v ${od.cls}`}>{od.label}</span>
          <span className="fact__s">CAPE {Math.round(wx.cape_j_kg)} J/kg</span>
        </div>
      </div>
      {th.convection_start && th.convection_end ? (
        <div className="dayline" aria-label="Fenêtre convective et créneau du vol">
          <div className="dayline__bar">
            <span className="dayline__conv" style={{ left: pos(hourOf(th.convection_start)), right: `calc(100% - ${pos(hourOf(th.convection_end))})` }} />
            <span className="dayline__win" style={{ left: pos(hourOf(plan.window.start)), right: `calc(100% - ${pos(hourOf(plan.window.end))})` }} />
            {th.peak_time ? <span className="dayline__peak" style={{ left: pos(hourOf(th.peak_time)) }} /> : null}
          </div>
          <div className="dayline__ticks">
            {[6, 9, 12, 15, 18, 21].map((h) => (
              <span key={h} style={{ left: pos(h) }}>
                {h}h
              </span>
            ))}
          </div>
          <div className="chart-legend tiny">
            <span>
              <i className="sw sw--box dayline__conv-sw" /> convection
            </span>
            <span>
              <i className="sw sw--box dayline__win-sw" /> créneau de décollage
            </span>
          </div>
        </div>
      ) : null}
      <p className="small">{th.comment}</p>
      {children}
    </section>
  );
}

/** Bloc 7 : risques complets, triés danger > prudence > info. */
export function RisksBlock({ risks }: { risks: Risk[] }) {
  const sorted = sortRisks(risks);
  return (
    <section className="block" aria-labelledby="b-risks">
      <h2 id="b-risks" className="block__title">
        Risques <span className="badge badge--neutral">{risks.length}</span>
      </h2>
      {sorted.length === 0 ? <p className="muted small">Aucun risque signalé.</p> : null}
      <ul className="risk-list">
        {sorted.map((r, i) => (
          <li key={i} className={`risk ${RISK_LEVEL[r.level].className}`}>
            <RiskIcon level={r.level} size={18} />
            <div>
              <div className="risk__title">
                {r.title} <span className="code-chip">{RISK_CODE_LABEL[r.code] ?? r.code}</span>
              </div>
              <div className="risk__detail">{r.detail}</div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Bloc 8 : atterrissage principal, vent à l'arrivée, atterros de secours (le plané final est dans GlideBlock, juste avant). */
export function LandingBlock({ plan, level }: { plan: FlightPlan; level: Difficulty }) {
  const land = plan.weather.landing;
  const lim: WindLimits = landingLimits(level, plan.flight_type);
  const kind = landingKindOf(plan.landing);
  return (
    <section className="block" aria-labelledby="b-landing">
      <h2 id="b-landing" className="block__title">
        Atterrissage
      </h2>
      <div className="landing-main">
        <div>
          <div className="landing-main__name">
            {plan.landing.name} <LandingKindBadge kind={kind} />
          </div>
          <div className="small muted">
            {formatAltitude(plan.landing.elevation_m)} · arrivée vers {formatTime(land.time)}
          </div>
        </div>
        <WindText speed={land.wind_10m.speed_kmh} gust={land.wind_10m.gust_kmh} dir={land.wind_10m.direction_deg} limits={lim} />
      </div>
      {plan.landing.restrictions ? <p className="small popup__warn">{plan.landing.restrictions}</p> : null}
      {kind !== "official" ? (
        <p className="alert alert--caution small" role="note">
          {LANDING_KIND[kind].description} Repérage et autorisation du propriétaire à vérifier.
        </p>
      ) : null}
      {plan.alternate_landings.length ? (
        <>
          <h3 className="block__sub">Atterrissages de secours</h3>
          <ul className="simple-list">
            {plan.alternate_landings.map((s) => (
              <li key={s.id}>
                <span className="grow">
                  {s.name} {landingKindOf(s) !== "official" ? <LandingKindBadge kind={landingKindOf(s)} /> : null}
                </span>
                <span className="small muted num">
                  {formatAltitude(s.elevation_m)} · {formatNumber(haversineKm(s, plan.landing), 1)} km de l'atterro
                </span>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="small muted">Pas d'atterrissage de secours identifié près de la route.</p>
      )}
    </section>
  );
}

/** Bloc 9 : espaces aériens et zones sensibles. */
export function AirspacesBlock({ plan }: { plan: FlightPlan }) {
  const sensitive = plan.risks.filter((r) => r.code === "SENSITIVE_AREA" || r.code === "NATIONAL_PARK");
  return (
    <section className="block" aria-labelledby="b-air">
      <h2 id="b-air" className="block__title">
        Espaces aériens et zones sensibles
      </h2>
      {plan.airspaces.length ? (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Nom</th>
                <th>Classe</th>
                <th>Plancher – plafond (AMSL)</th>
                <th>Distance</th>
              </tr>
            </thead>
            <tbody>
              {plan.airspaces.map((a, i) => (
                <tr key={i} className={a.intersects_route ? "row--danger" : ""}>
                  <td>
                    {a.name}
                    {a.intersects_route ? <span className="badge badge--nogo">traversé</span> : null}
                    <div className="tiny faint">{a.type}</div>
                  </td>
                  <td>{a.airspace_class}</td>
                  <td className="num nowrap">
                    {a.floor_m <= 0 ? "SFC" : formatAltitude(a.floor_m)} – {formatAltitude(a.ceiling_m)}
                    <div className="tiny faint">
                      {a.floor_m <= 0 ? "SFC" : fl(a.floor_m)} – {fl(a.ceiling_m)}
                    </div>
                  </td>
                  <td className="num nowrap">{formatNumber(a.min_distance_km, 1)} km</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="small muted">Aucun espace aérien signalé à proximité de la route.</p>
      )}
      {sensitive.length ? (
        <ul className="risk-list">
          {sensitive.map((r, i) => (
            <li key={i} className={`risk ${RISK_LEVEL[r.level].className}`}>
              <RiskIcon level={r.level} size={18} />
              <div>
                <div className="risk__title">{r.title}</div>
                <div className="risk__detail">{r.detail}</div>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="small muted">Aucune zone sensible active sur la route.</p>
      )}
      <p className="tiny faint">Vérifier les activations (NOTAM, SUP AIP, AZBA) le jour du vol.</p>
    </section>
  );
}

/** Bloc 10a : checklist cochable, mémorisée par plan. */
export function ChecklistBlock({ plan }: { plan: FlightPlan }) {
  const key = `pm.checklist.${plan.id}`;
  const [done, setDone] = useState<number[]>(() => loadJson<number[]>(key, []));
  useEffect(() => saveJson(key, done), [key, done]);
  const toggle = (i: number) => setDone((d) => (d.includes(i) ? d.filter((x) => x !== i) : [...d, i]));
  return (
    <section className="block" aria-labelledby="b-check">
      <h2 id="b-check" className="block__title">
        Checklist pré-vol{" "}
        <span className="badge badge--neutral num">
          {done.length}/{plan.checklist.length}
        </span>
        {done.length ? (
          <button type="button" className="icon-btn icon-btn--sm no-print" onClick={() => setDone([])} title="Tout décocher" aria-label="Tout décocher">
            <RotateCcw size={14} />
          </button>
        ) : null}
      </h2>
      <ul className="checklist">
        {plan.checklist.map((c, i) => (
          <li key={i}>
            <label className={`check-item${done.includes(i) ? " check-item--done" : ""}`}>
              <input type="checkbox" checked={done.includes(i)} onChange={() => toggle(i)} />
              <span className="check-item__box" aria-hidden>
                <Check size={14} />
              </span>
              <span>{c}</span>
            </label>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Bloc 10b : urgence (toujours visible). */
export function EmergencyBlock({ plan }: { plan: FlightPlan }) {
  const coords = (lat: number, lon: number) => `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
  const copy = async (label: string, text: string) => {
    const ok = await copyToClipboard(text);
    toast(ok ? `${label} copié : ${text}` : "Copie impossible");
  };
  return (
    <section className="block emergency" aria-labelledby="b-sos">
      <h2 id="b-sos" className="block__title">
        Urgence
      </h2>
      <div className="emergency__row">
        <a href="tel:112" className="btn btn--danger">
          <Phone size={16} aria-hidden /> 112
        </a>
        <span className="emergency__radio">
          <Radio size={16} aria-hidden /> Radio vol libre <strong className="num">143,9875 MHz</strong>
        </span>
      </div>
      <ul className="simple-list">
        {[
          { label: `Déco ${plan.takeoff.name}`, lat: plan.takeoff.lat, lon: plan.takeoff.lon, alt: plan.takeoff.elevation_m },
          { label: `Atterro ${plan.landing.name}`, lat: plan.landing.lat, lon: plan.landing.lon, alt: plan.landing.elevation_m },
        ].map((p) => (
          <li key={p.label}>
            <span className="grow">
              {p.label} <span className="faint small">{formatAltitude(p.alt)}</span>
              <div className="mono small">{coords(p.lat, p.lon)}</div>
            </span>
            <button type="button" className="btn btn--sm no-print" onClick={() => copy(p.label, coords(p.lat, p.lon))}>
              <ClipboardCopy size={14} aria-hidden /> Copier
            </button>
          </li>
        ))}
      </ul>
      <p className="tiny faint">Donner position GPS, altitude, état du blessé, vent et plafond pour l'hélicoptère. Prévenir le chauffeur en cas d'atterrissage hors terrain.</p>
    </section>
  );
}

/** Bloc 12 (replié) : décomposition du score, sources et fraîcheur, mode des données. */
export function TechnicalBlock({ plan, now }: { plan: FlightPlan; now: Date }) {
  const totalW = plan.score_breakdown.reduce((s, i) => s + i.weight, 0) || 1;
  const anyMock = plan.sources.some((s) => s.mode === "mock");
  return (
    <details className="block block--details">
      <summary className="block__title">Détails techniques : score, sources, données</summary>
      <h3 className="block__sub">Décomposition du score ({Math.round(plan.score)}/100)</h3>
      <table className="table score-table">
        <thead>
          <tr>
            <th>Critère</th>
            <th className="num">Poids</th>
            <th>Score</th>
          </tr>
        </thead>
        <tbody>
          {plan.score_breakdown.map((s) => (
            <tr key={s.criterion}>
              <td>
                {criterionLabel(s.criterion)}
                <div className="tiny faint">{s.comment}</div>
              </td>
              <td className="num">{Math.round((s.weight / totalW) * 100)} %</td>
              <td className="score-cell">
                <ScoreBar score={s.score} />
                <span className="num small">{Math.round(s.score)}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="tiny faint">Score non compensatoire : plafonné à 40 + le plus faible des critères de sécurité.</p>
      <h3 className="block__sub">Confiance : {Math.round(plan.confidence * 100)} %</h3>
      <h3 className="block__sub">Sources {anyMock ? <span className="badge badge--demo">données simulées</span> : <span className="badge badge--go">données réelles</span>}</h3>
      <ul className="simple-list">
        {plan.sources.map((s, i) => (
          <li key={i}>
            <span className="grow">
              {s.url ? (
                <a href={s.url} target="_blank" rel="noreferrer">
                  {s.name}
                </a>
              ) : (
                s.name
              )}
            </span>
            <span className={`badge ${s.mode === "live" ? "badge--go" : "badge--demo"}`}>{s.mode === "live" ? "réel" : "simulé"}</span>
            <span className="small faint nowrap">{formatAge(s.fetched_at, now)}</span>
          </li>
        ))}
      </ul>
      <p className="tiny faint mono">
        id {plan.id} · modèle {plan.weather.takeoff.model} · cible {new Date(plan.target_time).toISOString()} · {SOURCE_LABEL[plan.takeoff.source] ?? plan.takeoff.source}
      </p>
    </details>
  );
}

/** Tableau des waypoints (ETA en heure légale). */
export function WaypointTable({ plan }: { plan: FlightPlan }) {
  const start = new Date(plan.window.start).getTime();
  return (
    <div className="table-wrap">
      <table className="table wp-table">
        <thead>
          <tr>
            <th>Point</th>
            <th className="num">Alt.</th>
            <th className="num">Passage</th>
          </tr>
        </thead>
        <tbody>
          {plan.waypoints.map((w, i) => (
            <tr key={i}>
              <td>
                <span className={`wp-dot wp-dot--${w.type}`} aria-hidden /> {w.name}
                <div className="tiny faint">
                  {waypointTypeLabel(w.type)}
                  {w.radius_m ? ` · r ${formatNumber(w.radius_m)} m` : ""}
                  {w.note ? ` · ${w.note}` : ""}
                </div>
              </td>
              <td className="num nowrap">{formatAltitude(w.altitude_m)}</td>
              <td className="num nowrap">
                {w.eta_min !== null ? (
                  <>
                    {formatTime(new Date(start + w.eta_min * 60_000))}
                    <div className="tiny faint">+{formatDuration(w.eta_min)}</div>
                  </>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="tiny faint">Heures de passage pour un décollage à {formatTime(plan.window.start)} (début du créneau).</p>
    </div>
  );
}
