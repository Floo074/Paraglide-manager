import { RadioTower } from "lucide-react";
import type { Difficulty, FlightPlan, WeatherSnapshot } from "../../api/types";
import { aloftLimit, landingLimits, takeoffLimits } from "../../config/thresholds";
import { formatAge, formatNumber, formatTime } from "../../utils/format";
import { haversineKm } from "../../utils/geo";
import { WindText } from "../common/WindText";

function aloft(wx: WeatherSnapshot, alt: number) {
  const l = wx.winds_aloft.find((w) => Math.abs(w.altitude_m - alt) <= 150);
  return l ?? null;
}

/** Bloc 3 : vent au déco, en altitude (1500/2000/3000), à l'atterro à l'heure d'arrivée. */
export function WindBlock({ plan, level, now }: { plan: FlightPlan; level: Difficulty; now: Date }) {
  const wx = plan.weather.takeoff;
  const land = plan.weather.landing;
  const nc = wx.nowcast_correction;
  return (
    <section className="block" aria-labelledby="b-wind">
      <h2 id="b-wind" className="block__title">
        Vent
      </h2>
      <div className="wind-tiles">
        <div className="tile tile--deco">
          <div className="tile__k">Déco · {formatTime(wx.time)}</div>
          <div className="tile__v">
            <WindText speed={wx.wind_10m.speed_kmh} gust={wx.wind_10m.gust_kmh} dir={wx.wind_10m.direction_deg} limits={takeoffLimits(level, plan.flight_type)} />
          </div>
        </div>
        <div className="tile tile--alt">
          <div className="tile__k">En altitude</div>
          <ul className="tile__list">
            {[1500, 2000, 3000].map((a) => {
              const l = aloft(wx, a);
              return (
                <li key={a}>
                  <span className="tile__alt num">{formatNumber(a)} m</span>
                  {l ? <WindText speed={l.speed_kmh} dir={l.direction_deg} limits={{ wind: aloftLimit(level, a) ?? 999, gust: null }} compact /> : <span className="faint">—</span>}
                </li>
              );
            })}
          </ul>
        </div>
        <div className="tile tile--land">
          <div className="tile__k">Atterro · arrivée {formatTime(land.time)}</div>
          <div className="tile__v">
            <WindText speed={land.wind_10m.speed_kmh} gust={land.wind_10m.gust_kmh} dir={land.wind_10m.direction_deg} limits={landingLimits(level, plan.flight_type)} />
          </div>
          <div className="tile__sub">{plan.landing.name}, brise comprise</div>
        </div>
      </div>
      {nc ? (
        <p className="small muted">
          <RadioTower size={13} aria-hidden /> Prévision corrigée par les balises ({nc.beacon_ids.length}) : {nc.wind_speed_bias_kmh >= 0 ? "+" : ""}
          {formatNumber(nc.wind_speed_bias_kmh, 1)} km/h, {nc.wind_direction_bias_deg >= 0 ? "+" : ""}
          {Math.round(nc.wind_direction_bias_deg)}°.
        </p>
      ) : null}
      {plan.beacons_nearby.length ? (
        <details className="beacons-near">
          <summary>
            Balises proches ({plan.beacons_nearby.length}) — mesures réelles à comparer
          </summary>
          <ul>
            {plan.beacons_nearby.map((b) => (
              <li key={b.id} className={b.stale ? "is-stale" : ""}>
                <span className="grow">
                  {b.name}{" "}
                  <span className="faint small">
                    {formatNumber(haversineKm(b, plan.takeoff), 1)} km{b.elevation_m !== null ? ` · ${formatNumber(b.elevation_m)} m` : ""}
                  </span>
                </span>
                <WindText speed={b.wind_speed_kmh} gust={b.wind_gust_kmh} dir={b.wind_direction_deg} limits={takeoffLimits(level)} compact />
                <span className={`small nowrap ${b.stale ? "text-marginal" : "faint"}`}>{formatAge(b.observed_at, now)}</span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}
