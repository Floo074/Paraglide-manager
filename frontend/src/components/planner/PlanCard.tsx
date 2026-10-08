import { ChevronRight, Clock, Mountain, Navigation, TrendingUp } from "lucide-react";
import { Link } from "react-router-dom";
import type { Difficulty, FlightPlan } from "../../api/types";
import { THERMAL_USAGE_LABEL, difficultyLabel, flightTypeLabel } from "../../config/labels";
import { takeoffLimits } from "../../config/thresholds";
import { formatAltitude, formatDuration, formatKm, formatTime, formatVario } from "../../utils/format";
import { planTimes } from "../../utils/planTimes";
import { RiskLine, sortRisks } from "../common/RiskLine";
import { WindText } from "../common/WindText";
import { FlyabilityBadge } from "../ui/Badges";

/** Carte résumé d'un plan (ordre défini par l'expert : verdict, niveau, créneau, vent, plafond…). */
export function PlanCard({
  plan,
  level,
  demo,
  active,
  onHover,
}: {
  plan: FlightPlan;
  level: Difficulty;
  demo: boolean;
  active: boolean;
  onHover: (id: string | null) => void;
}) {
  const t = planTimes(plan);
  const wx = plan.weather.takeoff;
  const topRisks = sortRisks(plan.risks.filter((r) => r.code !== "MOCK_DATA" && r.level !== "info")).slice(0, 2);
  const typeLabel = plan.flight_type === "local" && plan.thermal_usage === "none" ? "Plouf" : flightTypeLabel(plan.flight_type);
  return (
    <article
      className={`plan-card plan-card--${plan.flyability}${active ? " plan-card--active" : ""}`}
      onMouseEnter={() => onHover(plan.id)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(plan.id)}
      onBlur={() => onHover(null)}
    >
      <div className="plan-card__top">
        <span className="plan-card__rank" aria-label={`Rang ${plan.rank}`}>
          {plan.rank}
        </span>
        <FlyabilityBadge value={plan.flyability} />
        <span className="plan-card__level">{difficultyLabel(plan.difficulty)}</span>
        <span className="plan-card__score num" title="Score sur 100">
          {plan.score}
          <span className="faint">/100</span>
        </span>
      </div>
      {demo ? <div className="demo-tag">Démo hors-ligne : données synthétiques</div> : null}
      <h3 className="plan-card__title">
        <Link to={`/plan/${encodeURIComponent(plan.id)}`} className="stretched">
          {plan.title}
        </Link>
      </h3>
      <div className="plan-card__facts">
        <span>
          <Clock size={14} aria-hidden /> Déco <strong className="num">{formatTime(t.start)}–{formatTime(t.end)}</strong>
          <span className={t.lateLanding ? "text-marginal" : "muted"}>
            {" "}· posé avant <strong className="num">{formatTime(t.latestLanding)}</strong>
          </span>
        </span>
        <span>
          <Navigation size={14} aria-hidden /> {typeLabel} · {formatDuration(plan.est_duration_min)} · {formatKm(plan.distance_km)}
        </span>
        <span>
          <span className="muted">Vent déco</span>{" "}
          <WindText speed={wx.wind_10m.speed_kmh} gust={wx.wind_10m.gust_kmh} dir={wx.wind_10m.direction_deg} limits={takeoffLimits(level, plan.flight_type)} compact />
        </span>
        <span>
          <Mountain size={14} aria-hidden /> Plafond utile <strong>{formatAltitude(plan.thermals.ceiling_m)}</strong>
        </span>
        <span>
          <TrendingUp size={14} aria-hidden />{" "}
          {plan.thermal_usage === "none" ? (
            "Air calme"
          ) : (
            <>
              Vario {formatVario(wx.thermal_strength_ms)} <span className="faint">({THERMAL_USAGE_LABEL[plan.thermal_usage]})</span>
            </>
          )}
        </span>
        <span>
          <span className="muted">Atterro</span> {plan.landing.name}
        </span>
      </div>
      {topRisks.length ? (
        <ul className="plan-card__risks">
          {topRisks.map((r, i) => (
            <RiskLine key={i} risk={r} />
          ))}
        </ul>
      ) : null}
      <p className="plan-card__summary">{plan.summary}</p>
      <ChevronRight className="plan-card__chev" size={18} aria-hidden />
    </article>
  );
}
