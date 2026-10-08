/** Formatage des valeurs pour l'affichage (français). */

const LOCALE = "fr-FR";

function nf(maxFrac: number, minFrac = 0): Intl.NumberFormat {
  return new Intl.NumberFormat(LOCALE, { maximumFractionDigits: maxFrac, minimumFractionDigits: minFrac });
}

/** Nombre au format français : espace insécable fine pour les milliers, virgule décimale. */
export function formatNumber(value: number, maxFrac = 0, minFrac = 0): string {
  return nf(maxFrac, minFrac).format(value).replace(/ /g, " ");
}

/** 75 → "1 h 15", 60 → "1 h", 20 → "20 min", 125 → "2 h 05". */
export function formatDuration(minutes: number): string {
  const m = Math.max(0, Math.round(minutes));
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const r = m % 60;
  return r === 0 ? `${h} h` : `${h} h ${String(r).padStart(2, "0")}`;
}

/** Plage de durées : "15 min – 2 h". */
export function formatDurationRange(min: number, max: number): string {
  return `${formatDuration(min)} – ${formatDuration(max)}`;
}

export function formatAltitude(m: number | null | undefined): string {
  if (m === null || m === undefined || Number.isNaN(m)) return "—";
  return `${formatNumber(Math.round(m))} m`;
}

export function formatKm(km: number): string {
  return `${formatNumber(km, km < 10 ? 1 : 0)} km`;
}

export function formatSpeed(kmh: number | null | undefined): string {
  if (kmh === null || kmh === undefined) return "—";
  return `${formatNumber(Math.round(kmh))} km/h`;
}

export function formatVario(ms: number): string {
  return `${formatNumber(ms, 1, 1)} m/s`;
}

export function formatPercent(ratio01: number): string {
  return `${Math.round(ratio01 * 100)} %`;
}

function timeParts(date: Date, timeZone?: string): Intl.DateTimeFormatOptions {
  return { hour: "2-digit", minute: "2-digit", hour12: false, ...(timeZone ? { timeZone } : {}) } satisfies Intl.DateTimeFormatOptions;
}

/** "14:00" (heure locale du navigateur, ou du fuseau demandé). */
export function formatTime(iso: string | Date, timeZone?: string): string {
  const d = typeof iso === "string" ? new Date(iso) : iso;
  return new Intl.DateTimeFormat(LOCALE, timeParts(d, timeZone)).format(d);
}

/** Clé jour "AAAA-MM-JJ" dans le fuseau demandé (pour comparer des jours calendaires). */
function dayKey(d: Date, timeZone?: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric", month: "2-digit", day: "2-digit", ...(timeZone ? { timeZone } : {}),
  }).format(d);
}

/**
 * Date relative lisible : "aujourd'hui 14:00", "demain 09:00", "sam. 10 oct. 14:00".
 */
export function formatDayTime(iso: string | Date, now: Date = new Date(), timeZone?: string): string {
  const d = typeof iso === "string" ? new Date(iso) : iso;
  const time = formatTime(d, timeZone);
  const k = dayKey(d, timeZone);
  if (k === dayKey(now, timeZone)) return `aujourd'hui ${time}`;
  const tomorrow = new Date(now.getTime() + 86_400_000);
  if (k === dayKey(tomorrow, timeZone)) return `demain ${time}`;
  const yesterday = new Date(now.getTime() - 86_400_000);
  if (k === dayKey(yesterday, timeZone)) return `hier ${time}`;
  const day = new Intl.DateTimeFormat(LOCALE, {
    weekday: "short", day: "numeric", month: "short", ...(timeZone ? { timeZone } : {}),
  }).format(d);
  return `${day} ${time}`;
}

/** Créneau "13:00 – 15:30". */
export function formatWindow(start: string, end: string, timeZone?: string): string {
  return `${formatTime(start, timeZone)} – ${formatTime(end, timeZone)}`;
}

/** Âge d'une mesure : "à l'instant", "il y a 5 min", "il y a 2 h 10", "il y a 3 j". */
export function formatAge(iso: string | Date, now: Date = new Date()): string {
  const d = typeof iso === "string" ? new Date(iso) : iso;
  const minutes = Math.round((now.getTime() - d.getTime()) / 60_000);
  if (minutes < 1) return "à l'instant";
  if (minutes < 60) return `il y a ${minutes} min`;
  if (minutes < 48 * 60) return `il y a ${formatDuration(minutes)}`;
  return `il y a ${Math.round(minutes / 1440)} j`;
}

/** Âge court pour une étiquette de carte : "5 min", "2 h", "3 j". */
export function formatAgeShort(iso: string | Date, now: Date = new Date()): string {
  const d = typeof iso === "string" ? new Date(iso) : iso;
  const minutes = Math.max(0, Math.round((now.getTime() - d.getTime()) / 60_000));
  if (minutes < 60) return `${minutes} min`;
  if (minutes < 48 * 60) return `${Math.round(minutes / 60)} h`;
  return `${Math.round(minutes / 1440)} j`;
}
