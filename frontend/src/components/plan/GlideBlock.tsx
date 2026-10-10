import type { Difficulty, FlightPlan } from "../../api/types";
import { formatAltitude, formatNumber } from "../../utils/format";
import { bearingDeg, haversineKm } from "../../utils/geo";
import {
  ARRIVAL_LABEL,
  GLIDE_MARGIN_LABEL,
  GLIDE_R_CAUTION,
  alongWindKind,
  arrivalLevel,
  formatAlongWind,
  formatArrivalHeight,
  formatGlideMarginPct,
  formatWindCredit,
  formatWindEffect,
  glideMarginLevel,
  glideTone,
  known,
  showCalmRatio,
  type GlideMarginLevel,
} from "../../utils/glide";
import { degToCardinalFr } from "../../utils/units";
import { GlideWindArrow } from "../common/GlideWindArrow";

const MARGIN_BADGE: Record<GlideMarginLevel, string> = { ok: "badge--go", low: "badge--marginal", over: "badge--nogo" };
const MARGIN_TEXT: Record<GlideMarginLevel, string> = { ok: "wv--ok", low: "wv--near", over: "wv--over" };
const BAR_MAX = 1.2;

/**
 * Bloc « Plané final » (CDC pilote §14) : finesse requise / disponible (et sans vent), vent rencontré sur le plané
 * relatif au cap et part comptée, hauteur d'arrivée attendue, commentaire du moniteur. Placé juste avant le bloc
 * Atterrissage (ordre du briefing : itinéraire → plané final → atterrissage).
 */
export function GlideBlock({ plan, level }: { plan: FlightPlan; level: Difficulty }) {
  const g = plan.glide;
  const along = g.wind_along_track_kmh;
  const hasWind = known(along);
  const kind = hasWind ? alongWindKind(along) : null;
  const margin = glideMarginLevel(g);
  const arrival = arrivalLevel(g.expected_arrival_height_m, along, level);
  const tone = glideTone(margin, arrival);
  const topLanding = g.required_ratio <= 0;
  const calm = showCalmRatio(g);
  const r = g.available_ratio > 0 ? g.required_ratio / g.available_ratio : BAR_MAX;
  const rCalm = calm ? g.required_ratio / g.calm_available_ratio : null;
  const pos = (v: number) => `${(Math.min(BAR_MAX, Math.max(0, v)) / BAR_MAX) * 100}%`;
  const distance = haversineKm(plan.takeoff, plan.landing);
  const cap = bearingDeg(plan.takeoff, plan.landing);
  const high = arrival === "high" || arrival === "very_high";

  return (
    <section className={`block glide-block glide-block--${tone}`} aria-labelledby="b-glide">
      <h2 id="b-glide" className="block__title">
        Plané final <span className={`badge ${MARGIN_BADGE[margin]}`}>{GLIDE_MARGIN_LABEL[margin]}</span>
        {high ? <span className="badge badge--info">{ARRIVAL_LABEL[arrival]}</span> : null}
        {arrival === "below" || arrival === "low" ? <span className="badge badge--marginal">{ARRIVAL_LABEL[arrival]}</span> : null}
      </h2>
      <p className="small muted">
        Vers <strong>{plan.landing.name}</strong> ({formatAltitude(plan.landing.elevation_m)}) · {formatNumber(distance, 1)} km depuis le déco, cap{" "}
        {degToCardinalFr(cap)} ({Math.round(cap)}°)
      </p>

      {topLanding ? (
        <p className="small">Atterrissage au sommet (top landing) : pas de plané final à vérifier. En cas de baisse du vent, pose-toi en bas de la pente côté au vent.</p>
      ) : (
        <>
          <div className="facts-grid glide-facts">
            <div className="fact">
              <span className="fact__k">Finesse requise / disponible</span>
              <span className="fact__v num">
                <span className={MARGIN_TEXT[margin]}>
                  {formatNumber(g.required_ratio, 1)} <span className="faint">/</span> {formatNumber(g.available_ratio, 1)}
                </span>
                {calm ? (
                  <>
                    {" "}
                    <s className="glide-calm" title="Finesse de calcul sans vent (même aile, même niveau)">
                      {formatNumber(g.calm_available_ratio, 1)}
                    </s>
                    <span className="sr-only"> sans vent</span>
                  </>
                ) : null}
              </span>
              <span className="fact__s">
                {calm ? `${formatWindEffect(g.calm_available_ratio, g.available_ratio)} (barré : sans vent) · ` : ""}
                {formatGlideMarginPct(g.required_ratio, g.available_ratio)}
              </span>
            </div>
            <div className={`fact glide-wind${kind ? ` glide-wind--${kind}` : ""}`}>
              <span className="fact__k">Vent sur le plané</span>
              {hasWind ? (
                <>
                  <span className="fact__v glide-wind__v">
                    <GlideWindArrow kmh={along} size={26} />
                    <span>{formatAlongWind(along)}</span>
                  </span>
                  <span className="fact__s">{formatWindCredit(along, g.wind_credit_kmh) || "rencontré sur la descente"}</span>
                </>
              ) : (
                <>
                  <span className="fact__v faint">—</span>
                  <span className="fact__s">non communiqué par le serveur</span>
                </>
              )}
            </div>
            <div className={`fact glide-arrival glide-arrival--${arrival}`}>
              <span className="fact__k">Arrivée estimée</span>
              <span className="fact__v num">{formatArrivalHeight(g.expected_arrival_height_m)}</span>
              <span className="fact__s">
                {known(g.expected_arrival_height_m) ? `${ARRIVAL_LABEL[arrival]}, au-dessus de l'atterro` : "non estimée"}
              </span>
            </div>
          </div>

          <div className="glide">
            <div className="glide__bar" role="img" aria-label={`Finesse requise ${formatNumber(r * 100)} % de la finesse disponible`}>
              <span
                className="glide__fill"
                style={{ width: pos(r), background: margin === "over" ? "var(--nogo)" : r > GLIDE_R_CAUTION ? "var(--marginal)" : "var(--go)" }}
              />
              {rCalm !== null ? <span className="glide__calm" style={{ left: pos(rCalm) }} title="Sans vent" /> : null}
              <span className="glide__limit" style={{ left: pos(1) }} />
            </div>
            <div className="glide__legend tiny faint">
              <span>part de la finesse disponible utilisée</span>
              {rCalm !== null ? (
                <span>
                  <i className="glide__calm-sw" aria-hidden /> sans vent
                </span>
              ) : null}
              <span>trait noir : limite</span>
            </div>
          </div>
        </>
      )}

      {g.comment ? <p className={`glide-comment glide-comment--${tone}`}>{g.comment}</p> : null}
      {!topLanding ? (
        <p className="tiny faint">
          Finesse de calcul sol, prudente : niveau, vent rencontré pendant la descente (brise d'atterro en bas, vent du déco en haut), une part
          seulement du vent arrière, le vent de face en entier. Valeur barrée : même calcul sans vent. Arrivée estimée avec le vent prévu et la
          finesse réelle moyenne. Plané le plus exigeant du vol (en général déco → atterro).
        </p>
      ) : null}
    </section>
  );
}
