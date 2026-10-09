import { ArrowUp, Loader2, RadioTower, RefreshCw } from "lucide-react";
import type { Difficulty, FlightPlan, Site, StationReading } from "../../api/types";
import { SOURCE_LABEL } from "../../config/labels";
import { landingLimits, takeoffLimits } from "../../config/thresholds";
import {
  NO_LANDING_BEACON_TEXT,
  NO_TAKEOFF_BEACON_TEXT,
  PIOUPIOU_ATTRIBUTION_TEXT,
  STATION_ROLE_LABEL,
  beaconAgeMinutes,
  formatRotation,
  formatSpeedTrend,
  hasPioupiou,
  isBeaconOutdated,
  readingsByRole,
  trendArrow,
  trendLevel,
} from "../../utils/beacons";
import { formatAge, formatNumber, formatSpeed, formatTime } from "../../utils/format";
import { degToCardinalFr, normalizeDeg } from "../../utils/units";


function ReadingCard({ r, level, flightType, now }: { r: StationReading; level: Difficulty; flightType: FlightPlan["flight_type"]; now: Date }) {
  const b = r.beacon;
  const age = beaconAgeMinutes(b.observed_at, now);
  const old = isBeaconOutdated(b, now);
  const lim = r.site_role === "takeoff" ? takeoffLimits(level, flightType) : landingLimits(level, flightType);
  const t = b.trend;
  const tl = t ? trendLevel(t, b.wind_speed_kmh) : null;
  const rot = t ? formatRotation(t) : null;
  const windCls = (v: number | null, max: number | null) => (v === null || max === null ? "" : v > max ? "wv--over" : v > 0.8 * max ? "wv--near" : "wv--ok");
  return (
    <li className={`reading${r.representative ? " reading--rep" : " reading--indicative"}${old ? " reading--old" : ""}`}>
      <div className="reading__head">
        <span className="reading__name">{b.name}</span>
        {r.representative ? (
          <span className="badge badge--go" title={`Poids dans la correction de prévision : ${Math.round(r.weight * 100)} %`}>
            représentative
          </span>
        ) : (
          <span className="badge badge--neutral" title="Trop loin, trop ancienne ou à une altitude différente : ne corrige pas la prévision">
            indicative
          </span>
        )}
      </div>
      <div className="reading__meta tiny faint">
        {SOURCE_LABEL[b.source] ?? b.source} · {formatNumber(r.distance_km, 1)} km · {r.altitude_diff_m >= 0 ? "+" : "−"}
        {formatNumber(Math.abs(r.altitude_diff_m))} m
        {r.representative ? ` · poids ${Math.round(r.weight * 100)} %` : ""}
      </div>
      <div className="reading__values">
        <span className="reading__dir" title={b.wind_direction_deg !== null ? `Vent de ${degToCardinalFr(b.wind_direction_deg)} (${Math.round(b.wind_direction_deg)}°) — la flèche indique où va le vent` : "Direction variable"}>
          {b.wind_direction_deg !== null ? (
            <ArrowUp size={22} aria-hidden style={{ transform: `rotate(${normalizeDeg(b.wind_direction_deg + 180)}deg)` }} />
          ) : (
            <span className="reading__var" aria-hidden>
              ~
            </span>
          )}
          <span>{b.wind_direction_deg !== null ? degToCardinalFr(b.wind_direction_deg) : "var."}</span>
        </span>
        <span className="reading__num">
          <span className="reading__k">moy.</span>
          <strong className={`num ${windCls(b.wind_speed_kmh, lim.wind)}`}>{b.wind_speed_kmh !== null ? Math.round(b.wind_speed_kmh) : "—"}</strong>
        </span>
        <span className="reading__num">
          <span className="reading__k">raf.</span>
          <strong className={`num ${windCls(b.wind_gust_kmh, lim.gust)}`}>{b.wind_gust_kmh !== null ? Math.round(b.wind_gust_kmh) : "—"}</strong>
        </span>
        <span className="reading__unit faint">km/h</span>
        <span className={`reading__age${old ? " text-nogo" : ""}`} title={`Mesure de ${formatTime(b.observed_at)}`}>
          {formatAge(b.observed_at, now)}
          {old ? " · trop ancienne" : ""}
        </span>
      </div>
      {t ? (
        <div className={`reading__trend${tl ? ` reading__trend--${tl}` : ""}`}>
          <span className="reading__arrow" aria-hidden>
            {trendArrow(t)}
          </span>
          <span>
            {formatSpeedTrend(t)}
            {rot ? `, ${rot}` : ""}
            {t.gust_max_kmh !== null ? ` · rafale max ${formatSpeed(t.gust_max_kmh)}` : ""}
          </span>
          {tl === "danger" ? <span className="badge badge--nogo">forcit</span> : tl === "caution" ? <span className="badge badge--marginal">à surveiller</span> : null}
        </div>
      ) : (
        <div className="reading__trend faint small">Tendance indisponible (pas d'historique)</div>
      )}
      <p className="reading__comment small">{r.comment}</p>
      {age > 30 && !b.stale ? <p className="tiny text-nogo">Mesure vieillie depuis le calcul du plan : actualiser.</p> : null}
    </li>
  );
}

function Column({
  title,
  site,
  readings,
  empty,
  level,
  flightType,
  now,
}: {
  title: string;
  site: Site | null;
  readings: StationReading[];
  empty: string;
  level: Difficulty;
  flightType: FlightPlan["flight_type"];
  now: Date;
}) {
  const hasRep = readings.some((r) => r.representative);
  return (
    <div className="live-col">
      <h3 className="live-col__title">
        {title}
        {site ? <span className="faint small"> · {site.name}</span> : null}
      </h3>
      {!hasRep ? (
        <p className="alert alert--caution live-col__empty" role="note">
          {empty}
        </p>
      ) : null}
      {readings.length ? (
        <ul className="readings">
          {readings.map((r) => (
            <ReadingCard key={`${r.site_id}-${r.beacon.id}`} r={r} level={level} flightType={flightType} now={now} />
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** Bloc « Balises en direct » : balises rattachées au déco, à l'atterro et aux secours (nowcasting). */
export function StationReadingsBlock({
  plan,
  level,
  now,
  updatedAt,
  onRefresh,
  refreshing,
  rebuilt,
}: {
  plan: FlightPlan;
  level: Difficulty;
  now: Date;
  /** Heure du calcul du plan (dernière mise à jour). */
  updatedAt: string | null;
  onRefresh: () => void;
  refreshing: boolean;
  /** La requête d'origine est inconnue (lien partagé) : elle sera reconstituée. */
  rebuilt: boolean;
}) {
  const by = readingsByRole(plan.station_readings);
  const altSites = plan.alternate_landings;
  const alternates = by.alternate_landing;
  const showAttribution = hasPioupiou(plan.station_readings.map((r) => r.beacon));
  return (
    <section className="block live-block" aria-labelledby="b-live">
      <h2 id="b-live" className="block__title">
        <RadioTower size={18} aria-hidden /> Balises en direct
      </h2>
      <div className="live-block__bar">
        <span className="small muted">
          {updatedAt ? (
            <>
              Mis à jour à <strong className="num">{formatTime(updatedAt)}</strong> ({formatAge(updatedAt, now)})
            </>
          ) : (
            "Heure de mise à jour inconnue"
          )}
        </span>
        <button type="button" className="btn btn--sm no-print" onClick={onRefresh} disabled={refreshing} title={rebuilt ? "Requête reconstituée depuis le plan (lien partagé)" : "Relance le calcul avec la même requête"}>
          {refreshing ? <Loader2 size={15} className="spin" aria-hidden /> : <RefreshCw size={15} aria-hidden />}
          {refreshing ? "Actualisation…" : "Actualiser les balises"}
        </button>
      </div>
      <div className="live-cols">
        <Column title="Déco" site={plan.takeoff} readings={by.takeoff} empty={NO_TAKEOFF_BEACON_TEXT} level={level} flightType={plan.flight_type} now={now} />
        <Column title="Atterro" site={plan.landing} readings={by.landing} empty={NO_LANDING_BEACON_TEXT} level={level} flightType={plan.flight_type} now={now} />
      </div>
      {alternates.length ? (
        <details className="sub-details">
          <summary>
            Atterros de secours ({alternates.filter((r) => r.representative).length} balise{alternates.filter((r) => r.representative).length > 1 ? "s" : ""} représentative
            {alternates.filter((r) => r.representative).length > 1 ? "s" : ""})
          </summary>
          {altSites
            .filter((s) => alternates.some((r) => r.site_id === s.id))
            .map((s) => (
              <Column
                key={s.id}
                title={STATION_ROLE_LABEL.alternate_landing}
                site={s}
                readings={alternates.filter((r) => r.site_id === s.id)}
                empty="Pas de balise représentative à cet atterro de secours."
                level={level}
                flightType={plan.flight_type}
                now={now}
              />
            ))}
          {alternates.some((r) => !altSites.some((s) => s.id === r.site_id)) ? (
            <Column
              title={STATION_ROLE_LABEL.alternate_landing}
              site={null}
              readings={alternates.filter((r) => !altSites.some((s) => s.id === r.site_id))}
              empty="Pas de balise représentative."
              level={level}
              flightType={plan.flight_type}
              now={now}
            />
          ) : null}
        </details>
      ) : null}
      <p className="tiny faint">
        Moyenne et rafale sur 10 min ; tendance = moyenne des 10 dernières minutes comparée à celle d'il y a 1 h. Une balise ne remplace pas
        l'observation sur place (manche à air, autres voiles).
        {showAttribution ? <> Données {PIOUPIOU_ATTRIBUTION_TEXT}.</> : null}
      </p>
    </section>
  );
}
