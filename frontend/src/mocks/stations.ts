/**
 * Rattachement des balises aux sites d'un plan (DÉMONSTRATION), d'après le CDC §12.2 :
 * déco ≤ 5 km et |Δalt| ≤ 300 m, atterro ≤ 3 km et |Δalt| ≤ 150 m (pas de balise de sommet),
 * fraîcheur 10-30 min, poids décroissant avec l'horizon (l'heure d'ARRIVÉE pour l'atterro).
 */
import type { Beacon, Site, StationReading, StationRole, WeatherSnapshot } from "../api/types";
import { beaconAgeMinutes } from "../utils/beacons";
import { formatNumber } from "../utils/format";
import { haversineKm } from "../utils/geo";
import { degToCardinalFr } from "../utils/units";

/** CDC §12.2 beacon_weight_by_minutes (interpolation linéaire). */
const WEIGHT_BY_MIN: [number, number][] = [
  [15, 0.85],
  [30, 0.7],
  [60, 0.5],
  [120, 0.3],
  [480, 0.1],
  [720, 0],
];

export function beaconWeightForMinutes(minutes: number): number {
  if (minutes <= WEIGHT_BY_MIN[0]![0]) return WEIGHT_BY_MIN[0]![1];
  for (let i = 1; i < WEIGHT_BY_MIN.length; i++) {
    const [m1, w1] = WEIGHT_BY_MIN[i]!;
    const [m0, w0] = WEIGHT_BY_MIN[i - 1]!;
    if (minutes <= m1) return w0 + ((w1 - w0) * (minutes - m0)) / (m1 - m0);
  }
  return 0;
}

const ATTACH = {
  takeoff: { maxKm: 5, fullKm: 1, maxAlt: 300, fullAlt: 150 },
  landing: { maxKm: 3, fullKm: 1.5, maxAlt: 150, fullAlt: 150 },
};
const SUMMIT = /d[ée]co|sommet|cr[êe]te|\bcol\b/i;

function freshness(age: number): number {
  if (age <= 10) return 1;
  if (age > 30) return 0;
  return 1 - ((age - 10) / 20) * 0.7;
}

export interface StationSite {
  role: StationRole;
  site: Site;
  /** Prévision retenue au site (pour comparer la mesure). */
  forecast: WeatherSnapshot;
  /** Minutes entre maintenant et l'heure d'utilisation (cible pour le déco, arrivée pour l'atterro). */
  minutesAhead: number;
}

function conformity(b: Beacon, forecast: WeatherSnapshot): string {
  if (b.wind_speed_kmh === null) return "mesure de vent indisponible";
  const diff = Math.round(b.wind_speed_kmh - forecast.wind_10m.speed_kmh);
  if (Math.abs(diff) < 5) return "conforme à la prévision";
  return diff > 0 ? `plus fort que prévu (+${diff} km/h)` : `plus faible que prévu (${diff} km/h)`;
}

function measureText(b: Beacon, age: number): string {
  if (b.wind_speed_kmh === null) return `${b.name} : pas de mesure de vent`;
  const dir = b.wind_direction_deg !== null ? ` ${degToCardinalFr(b.wind_direction_deg)}` : " variable";
  const gust = b.wind_gust_kmh !== null ? `, rafales ${Math.round(b.wind_gust_kmh)}` : "";
  return `${b.name} : ${Math.round(b.wind_speed_kmh)} km/h${dir}${gust}, il y a ${age} min`;
}

/** Balises rattachées à chaque site (au plus 3 par site, y compris celles seulement indicatives). */
export function stationReadings(sites: StationSite[], beacons: Beacon[], now: Date): StationReading[] {
  const out: StationReading[] = [];
  for (const s of sites) {
    const lim = s.role === "takeoff" ? ATTACH.takeoff : ATTACH.landing;
    const horizonW = beaconWeightForMinutes(Math.max(0, s.minutesAhead));
    const near = beacons
      .map((b) => ({ b, d: haversineKm(b, s.site) }))
      .filter((x) => x.d <= lim.maxKm * 1.6)
      // au-delà de 2× le dénivelé admis, ou balise de sommet pour un atterro : sans intérêt, non listée
      .filter((x) => x.b.elevation_m === null || Math.abs(x.b.elevation_m - s.site.elevation_m) <= lim.maxAlt * 2)
      .filter((x) => s.role === "takeoff" || !SUMMIT.test(x.b.name))
      .sort((a, b) => a.d - b.d)
      .slice(0, 3);
    for (const { b, d } of near) {
      const age = beaconAgeMinutes(b.observed_at, now);
      const dAlt = b.elevation_m !== null ? Math.round(b.elevation_m - s.site.elevation_m) : 0;
      const issues: string[] = [];
      if (b.stale || age > 30) issues.push(`mesure trop ancienne (il y a ${age} min) : ignorée`);
      if (b.elevation_m === null) issues.push("altitude de la balise inconnue");
      if (d > lim.maxKm) issues.push(`trop loin du site (${formatNumber(d, 1)} km)`);
      if (Math.abs(dAlt) > lim.maxAlt) issues.push(`dénivelé de ${formatNumber(Math.abs(dAlt))} m avec le site`);
      if (b.wind_speed_kmh === null) issues.push("pas de mesure de vent");
      const representative = issues.length === 0 && horizonW > 0;
      let distFactor: number;
      if (s.role === "takeoff") distFactor = d > lim.fullKm || Math.abs(dAlt) > lim.fullAlt ? 0.5 : 1;
      else distFactor = d <= lim.fullKm ? 1 : 1 - (0.5 * (d - lim.fullKm)) / (lim.maxKm - lim.fullKm);
      const weight = representative ? Math.round(horizonW * freshness(age) * distFactor * 100) / 100 : 0;
      const comment = representative
        ? `${measureText(b, age)} — ${conformity(b, s.forecast)}`
        : `${measureText(b, age)} — indicative seulement : ${issues.join(", ")}`;
      out.push({
        site_role: s.role,
        site_id: s.site.id,
        beacon: b,
        distance_km: Math.round(d * 100) / 100,
        altitude_diff_m: dAlt,
        representative,
        weight,
        comment,
      });
    }
  }
  return out;
}

/** Correction de prévision par les balises représentatives d'un rôle (affichage uniquement en démo). */
export function nowcastFrom(readings: StationReading[], forecast: WeatherSnapshot): WeatherSnapshot["nowcast_correction"] {
  const rep = readings.filter((r) => r.representative && r.beacon.wind_speed_kmh !== null);
  if (rep.length === 0) return null;
  const wsum = rep.reduce((s, r) => s + r.weight, 0) || 1;
  const speedBias = rep.reduce((s, r) => s + r.weight * ((r.beacon.wind_speed_kmh ?? 0) - forecast.wind_10m.speed_kmh), 0) / wsum;
  const dirs = rep.filter((r) => r.beacon.wind_direction_deg !== null);
  const dirBias = dirs.length
    ? dirs.reduce((s, r) => {
        let dd = (r.beacon.wind_direction_deg ?? 0) - forecast.wind_10m.direction_deg;
        dd = ((dd + 540) % 360) - 180;
        return s + r.weight * dd;
      }, 0) / (dirs.reduce((s, r) => s + r.weight, 0) || 1)
    : 0;
  const w = Math.max(...rep.map((r) => r.weight));
  return {
    beacon_ids: rep.map((r) => r.beacon.id),
    wind_speed_bias_kmh: Math.round(speedBias * w * 10) / 10,
    wind_direction_bias_deg: Math.round(dirBias * w),
  };
}
