/**
 * Position du soleil (formules NOAA simplifiées, précision ~1-2 min) :
 * utile pour l'heure légale de fin de vol (pas de vol de nuit) et la météo synthétique.
 */

const rad = (d: number) => (d * Math.PI) / 180;
const deg = (r: number) => (r * 180) / Math.PI;

function julianCentury(date: Date): number {
  const jd = date.getTime() / 86_400_000 + 2440587.5;
  return (jd - 2451545) / 36525;
}

function solarParams(date: Date) {
  const t = julianCentury(date);
  const L0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360;
  const M = 357.52911 + t * (35999.05029 - 0.0001537 * t);
  const e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t);
  const C =
    Math.sin(rad(M)) * (1.914602 - t * (0.004817 + 0.000014 * t)) +
    Math.sin(rad(2 * M)) * (0.019993 - 0.000101 * t) +
    Math.sin(rad(3 * M)) * 0.000289;
  const trueLong = L0 + C;
  const omega = 125.04 - 1934.136 * t;
  const lambda = trueLong - 0.00569 - 0.00478 * Math.sin(rad(omega));
  const eps0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60;
  const eps = eps0 + 0.00256 * Math.cos(rad(omega));
  const decl = deg(Math.asin(Math.sin(rad(eps)) * Math.sin(rad(lambda))));
  const y = Math.tan(rad(eps / 2)) ** 2;
  const eqTime =
    4 *
    deg(
      y * Math.sin(2 * rad(L0)) -
        2 * e * Math.sin(rad(M)) +
        4 * e * y * Math.sin(rad(M)) * Math.cos(2 * rad(L0)) -
        0.5 * y * y * Math.sin(4 * rad(L0)) -
        1.25 * e * e * Math.sin(2 * rad(M)),
    );
  return { decl, eqTime };
}

/** Élévation du soleil (degrés) au-dessus de l'horizon. */
export function solarElevationDeg(lat: number, lon: number, date: Date): number {
  const { decl, eqTime } = solarParams(date);
  const minutesUtc = date.getUTCHours() * 60 + date.getUTCMinutes() + date.getUTCSeconds() / 60;
  const trueSolarTime = (((minutesUtc + eqTime + 4 * lon) % 1440) + 1440) % 1440;
  const hourAngle = trueSolarTime / 4 - 180;
  const cosZenith =
    Math.sin(rad(lat)) * Math.sin(rad(decl)) + Math.cos(rad(lat)) * Math.cos(rad(decl)) * Math.cos(rad(hourAngle));
  return 90 - deg(Math.acos(Math.max(-1, Math.min(1, cosZenith))));
}

/** Heure solaire vraie locale (heures décimales 0..24). */
export function solarHour(lon: number, date: Date): number {
  const { eqTime } = solarParams(date);
  const minutesUtc = date.getUTCHours() * 60 + date.getUTCMinutes();
  return ((((minutesUtc + eqTime + 4 * lon) % 1440) + 1440) % 1440) / 60;
}

/**
 * Lever et coucher du soleil (UTC) pour le jour UTC contenant `date`.
 * Renvoie null pour les jours polaires (sans objet en France).
 */
export function sunTimes(lat: number, lon: number, date: Date): { sunrise: Date; sunset: Date } | null {
  const noon = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate(), 12));
  const { decl, eqTime } = solarParams(noon);
  const cosH =
    Math.cos(rad(90.833)) / (Math.cos(rad(lat)) * Math.cos(rad(decl))) - Math.tan(rad(lat)) * Math.tan(rad(decl));
  if (cosH < -1 || cosH > 1) return null;
  const ha = deg(Math.acos(cosH));
  const solarNoonMin = 720 - 4 * lon - eqTime;
  const base = Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
  return {
    sunrise: new Date(base + (solarNoonMin - 4 * ha) * 60_000),
    sunset: new Date(base + (solarNoonMin + 4 * ha) * 60_000),
  };
}

/** Le moment est-il de jour (entre lever et coucher du soleil) ? */
export function isDaylight(lat: number, lon: number, date: Date): boolean {
  return solarElevationDeg(lat, lon, date) > -0.833;
}
