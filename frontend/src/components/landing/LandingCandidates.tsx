import { AlertTriangle, ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Difficulty, LandingCandidate } from "../../api/types";
import { COMMUNITY_USAGE_LABEL, LANDING_KIND } from "../../config/labels";
import { landingLimits } from "../../config/thresholds";
import { formatAltitude, formatNumber } from "../../utils/format";
import { haversineKm, type Pt } from "../../utils/geo";
import { glideVerdict } from "../../utils/landings";
import { WindText } from "../common/WindText";

const GLIDE_TEXT = { ok: "marge OK", near: "marge juste", over: "hors de portée" } as const;

export function LandingKindBadge({ kind }: { kind: LandingCandidate["kind"] }) {
  const k = LANDING_KIND[kind];
  return (
    <span className={`badge lk-badge ${k.className}`} title={k.description}>
      {k.label}
    </span>
  );
}

/** Légende des couleurs des atterros. */
export function LandingKindLegend() {
  return (
    <div className="lk-legend tiny" aria-label="Légende des atterrissages">
      {(Object.keys(LANDING_KIND) as LandingCandidate["kind"][]).map((k) => (
        <span key={k} title={LANDING_KIND[k].description}>
          <i className="lk-swatch" style={{ background: LANDING_KIND[k].color }} aria-hidden /> {LANDING_KIND[k].label}
        </span>
      ))}
    </div>
  );
}

/** Fiche d'un atterro candidat : score, finesse, arrivée, terrain, obstacles, vent, avertissements, raisons. */
export function LandingCandidateCard({
  candidate: c,
  rank,
  level,
  from,
  selected = false,
  onSelect,
  label,
  defaultOpen = false,
}: {
  candidate: LandingCandidate;
  rank: number;
  level: Difficulty;
  /** Point de départ (déco) pour afficher la distance. */
  from?: Pt | null;
  selected?: boolean;
  onSelect?: (id: string) => void;
  /** Étiquette complémentaire, ex. « Atterro retenu ». */
  label?: string;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!selected) return;
    setOpen(true);
    ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selected]);
  const k = LANDING_KIND[c.kind];
  const gv = glideVerdict(c.required_glide_ratio, c.available_glide_ratio);
  const dist = from ? haversineKm(from, c.site) : null;
  const w = c.wind_at_arrival;
  const bodyId = `lc-body-${c.site.id.replace(/[^a-zA-Z0-9_-]/g, "_")}`;
  return (
    <article ref={ref} className={`lc-card ${k.className}${selected ? " lc-card--selected" : ""}`} aria-label={`Atterrissage ${rank} : ${c.site.name}`}>
      <button
        type="button"
        className="lc-card__head"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => {
          setOpen(!open);
          onSelect?.(c.site.id);
        }}
      >
        <span className="lc-rank" style={{ background: k.color }} aria-hidden>
          {rank}
        </span>
        <span className="lc-card__name">
          <span className="lc-card__title">{c.site.name}</span>
          <span className="lc-card__tags">
            <LandingKindBadge kind={c.kind} />
            {label ? <span className="badge badge--info">{label}</span> : null}
          </span>
        </span>
        <span className="lc-card__score num" title="Score de l'atterrissage sur 100">
          {Math.round(c.score)}
          <span className="faint">/100</span>
        </span>
        <ChevronDown size={16} className={`lc-card__chev${open ? " is-open" : ""}`} aria-hidden />
      </button>

      <div className="lc-facts">
        <span className={`wv--${gv}`} title="Finesse sol nécessaire depuis le déco (vent compris) / finesse de calcul retenue (prudente)">
          Finesse <strong className="num">{formatNumber(c.required_glide_ratio, 1)}</strong> / {formatNumber(c.available_glide_ratio, 1)} · {GLIDE_TEXT[gv]}
        </span>
        <span>
          Arrivée{" "}
          <strong className={`num ${c.arrival_height_m < 0 ? "text-nogo" : ""}`}>
            {c.arrival_height_m >= 0 ? "+" : "−"}
            {formatNumber(Math.abs(Math.round(c.arrival_height_m)))} m
          </strong>{" "}
          <span className="faint">/sol</span>
        </span>
        {dist !== null ? <span className="num">{formatNumber(dist, 1)} km</span> : null}
        <span>
          <span className="muted">Vent</span>{" "}
          {w ? <WindText speed={w.speed_kmh} gust={w.gust_kmh} dir={w.direction_deg} limits={landingLimits(level)} compact /> : <span className="faint">inconnu</span>}
        </span>
      </div>

      {c.warnings.length ? (
        <ul className="lc-warnings">
          {c.warnings.map((t, i) => (
            <li key={i}>
              <AlertTriangle size={14} aria-hidden /> <span>{t}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {open ? (
        <div className="lc-body" id={bodyId}>
          <dl className="lc-dl">
            <div>
              <dt>Altitude</dt>
              <dd>{formatAltitude(c.site.elevation_m)}</dd>
            </div>
            <div>
              <dt>Taille</dt>
              <dd className="num">{c.size_m ? `${formatNumber(c.size_m.length)} × ${formatNumber(c.size_m.width)} m` : "inconnue"}</dd>
            </div>
            <div>
              <dt>Pente</dt>
              <dd className="num">{c.slope_pct !== null ? `${formatNumber(c.slope_pct, 1)} %` : "inconnue"}</dd>
            </div>
            <div>
              <dt>Surface</dt>
              <dd>{c.surface ?? "inconnue"}</dd>
            </div>
            <div>
              <dt>Usage communautaire</dt>
              <dd>{COMMUNITY_USAGE_LABEL[c.community_usage]}</dd>
            </div>
            <div>
              <dt>Accès</dt>
              <dd>{c.access ?? "non renseigné"}</dd>
            </div>
            {w ? (
              <div>
                <dt>Vent à l'arrivée</dt>
                <dd>
                  <WindText speed={w.speed_kmh} gust={w.gust_kmh} dir={w.direction_deg} limits={landingLimits(level)} />
                </dd>
              </div>
            ) : null}
            <div>
              <dt>Finesse requise / disponible</dt>
              <dd className="num">
                {formatNumber(c.required_glide_ratio, 1)} / {formatNumber(c.available_glide_ratio, 1)}
              </dd>
            </div>
          </dl>
          <h4 className="lc-sub">Obstacles</h4>
          {c.obstacles.length ? (
            <ul className="lc-list">
              {c.obstacles.map((o, i) => (
                <li key={i}>{o}</li>
              ))}
            </ul>
          ) : (
            <p className="small muted">Aucun obstacle signalé (à vérifier sur place).</p>
          )}
          {c.reasons.length ? (
            <>
              <h4 className="lc-sub">Pourquoi ce classement</h4>
              <ul className="lc-list">
                {c.reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </>
          ) : null}
          {c.site.description ? <p className="tiny faint">{c.site.description}</p> : null}
          <p className="tiny faint mono">
            {c.site.lat.toFixed(5)}, {c.site.lon.toFixed(5)}
          </p>
        </div>
      ) : null}
    </article>
  );
}

/** Liste classée des atterros candidats. */
export function LandingCandidateList({
  candidates,
  level,
  from,
  selectedId,
  onSelect,
  firstLabel,
}: {
  candidates: LandingCandidate[];
  level: Difficulty;
  from?: Pt | null;
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  firstLabel?: string;
}) {
  return (
    <ol className="lc-list-cards">
      {candidates.map((c, i) => (
        <li key={c.site.id}>
          <LandingCandidateCard
            candidate={c}
            rank={i + 1}
            level={level}
            from={from}
            selected={selectedId === c.site.id}
            onSelect={onSelect}
            label={i === 0 ? firstLabel : undefined}
          />
        </li>
      ))}
    </ol>
  );
}
