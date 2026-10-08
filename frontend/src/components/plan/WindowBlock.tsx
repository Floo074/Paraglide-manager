import { Sunset } from "lucide-react";
import type { Difficulty, FlightPlan, WeatherSnapshot } from "../../api/types";
import { VERDICT_CLASS, takeoffLimits, windVerdict } from "../../config/thresholds";
import { formatNumber, formatTime } from "../../utils/format";
import { planTimes } from "../../utils/planTimes";
import { degToCardinalFr, normalizeDeg } from "../../utils/units";

/** Bloc 2 : créneau en heure légale + frise horaire ±3 h au déco, fenêtre surlignée. */
export function WindowBlock({ plan, level }: { plan: FlightPlan; level: Difficulty }) {
  const t = planTimes(plan);
  const limits = takeoffLimits(level, plan.flight_type);
  const inWindow = (w: WeatherSnapshot) => {
    const ts = new Date(w.time).getTime();
    return ts >= t.start.getTime() - 30 * 60_000 && ts <= t.end.getTime() + 30 * 60_000;
  };
  const target = new Date(plan.target_time).getTime();
  return (
    <section className="block window-block" aria-labelledby="b-window">
      <h2 id="b-window" className="sr-only">
        Créneau
      </h2>
      <p className="window-line">
        <span>
          Décollage <strong className="num">{formatTime(t.start)}–{formatTime(t.end)}</strong>
        </span>
        <span className="sep" aria-hidden>
          ·
        </span>
        <span className={t.lateLanding ? "text-marginal" : ""}>
          posé avant <strong className="num">{formatTime(t.latestLanding)}</strong>
        </span>
        {t.sunset ? (
          <>
            <span className="sep" aria-hidden>
              ·
            </span>
            <span>
              <Sunset size={14} aria-hidden /> coucher <strong className="num">{formatTime(t.sunset)}</strong>
            </span>
          </>
        ) : null}
        <span className="faint small"> (heure locale)</span>
      </p>
      <div className="strip-wrap">
        <table className="strip" aria-label="Évolution horaire au déco">
          <thead>
            <tr>
              <th scope="row">Heure</th>
              {plan.weather.timeline.map((w) => (
                <th key={w.time} scope="col" className={`${inWindow(w) ? "in-window" : ""}${new Date(w.time).getTime() === target ? " is-target" : ""}`}>
                  {formatTime(w.time)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">Vent</th>
              {plan.weather.timeline.map((w) => {
                const v = windVerdict(w.wind_10m.speed_kmh, w.wind_10m.gust_kmh, limits);
                return (
                  <td key={w.time} className={`${inWindow(w) ? "in-window " : ""}${v ? VERDICT_CLASS[v] : ""}`}>
                    <span className="strip__dir" title={`Vent de ${degToCardinalFr(w.wind_10m.direction_deg)}`}>
                      <span className="strip__arrow" style={{ transform: `rotate(${normalizeDeg(w.wind_10m.direction_deg + 180)}deg)` }} aria-hidden>
                        ↑
                      </span>
                      {degToCardinalFr(w.wind_10m.direction_deg)}
                    </span>
                    <span className="num">
                      {Math.round(w.wind_10m.speed_kmh)}
                      <span className="strip__gust">/{Math.round(w.wind_10m.gust_kmh)}</span>
                    </span>
                  </td>
                );
              })}
            </tr>
            <tr>
              <th scope="row">Vario</th>
              {plan.weather.timeline.map((w) => (
                <td key={w.time} className={`num${inWindow(w) ? " in-window" : ""}`}>
                  {w.thermal_strength_ms < 0.3 ? "–" : formatNumber(w.thermal_strength_ms, 1, 1)}
                </td>
              ))}
            </tr>
            <tr>
              <th scope="row">CAPE</th>
              {plan.weather.timeline.map((w) => (
                <td key={w.time} className={`num${inWindow(w) ? " in-window" : ""}${w.cape_j_kg >= 800 ? " wv--over" : w.cape_j_kg >= 300 ? " wv--near" : ""}`}>
                  {Math.round(w.cape_j_kg)}
                </td>
              ))}
            </tr>
            <tr>
              <th scope="row">Pluie</th>
              {plan.weather.timeline.map((w) => (
                <td key={w.time} className={`num${inWindow(w) ? " in-window" : ""}${w.precipitation_mm_h >= 0.2 ? " wv--over" : ""}`}>
                  {w.precipitation_mm_h > 0 ? formatNumber(w.precipitation_mm_h, 1) : "–"}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
      <p className="tiny faint">
        <span className="hide-sm">Vent moy./raf. (couleur : seuils de ton niveau) · </span>km/h · m/s · J/kg · mm/h · <span className="strip-key">surligné</span> = créneau
      </p>
    </section>
  );
}
