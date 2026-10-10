/**
 * Vent sur le plané et plané final — version SIMPLIFIÉE du moteur de DÉMONSTRATION (CDC pilote §14).
 *
 * - Vent rencontré par tranches de 50 m entre l'entrée de l'approche (atterro + marge) et l'altitude de départ :
 *   brise d'atterro (à l'heure d'arrivée) sur les 300 m du bas, vent du déco sur les 100 m sous le déco,
 *   interpolation (u, v) entre les deux, profil d'altitude au-dessus du déco. Moyenne vectorielle projetée sur le cap.
 * - Vent arrière crédité en partie (base du niveau, bonus brise établie, malus horizon / rafales, plafond),
 *   vent de face compté en entier et majoré par les rafales, travers toujours payé (crabe).
 * - Polaire simplifiée (catégorie d'aile) et accélérateur selon le niveau (jamais pour l'élève).
 * - Hauteur d'arrivée attendue : vent prévu à 100 %, finesse réelle moyenne (90 % de la polaire).
 * Le moteur de référence est le backend : ici, rien de plus qu'une illustration cohérente pour l'interface hors-ligne.
 */
import type { Difficulty, FlightPlanGlide, Horizon, Risk, WindLevel } from "../api/types";
import { formatNumber } from "../utils/format";
import { bearingDeg, haversineKm, type Pt } from "../utils/geo";
import { degToCardinalFr, normalizeDeg } from "../utils/units";

export interface WindVec {
  speed: number;
  dir: number; // provenance, degrés
  gust?: number;
}

/** Valeurs du CDC §14.9 (glide_wind, glide_tail_credit, glide_headwind_gust, wing_polar, high_arrival…). */
export const GLIDE_RULES = {
  sliceM: 50,
  breezeLayerM: 300,
  takeoffLayerM: 100,
  calmKmh: 5,
  tailBase: { beginner: 0.5, intermediate: 0.6, advanced: 0.7, expert: 0.7 } as Record<Difficulty, number>,
  tailCapKmh: { beginner: 8, intermediate: 10, advanced: 12, expert: 15 } as Record<Difficulty, number>,
  breeze: { bonus: 0.2, minKmh: 8, minTailKmh: 5, legalHours: [13, 17] as const },
  horizonMalus: { "24h": 0.1, "48h": 0.2 } as Partial<Record<Horizon, number>>,
  gustMalus: { over: 1.5, minWindKmh: 10, malus: 0.1 },
  headGust: { factor: 0.5, max: 1.2, minWindKmh: 10 },
  penetrationMinKmh: { beginner: 15, intermediate: 15, advanced: 12, expert: 10 } as Record<Difficulty, number>,
  speedBarFraction: { beginner: 0, intermediate: 0.5, advanced: 1, expert: 1 } as Record<Difficulty, number>,
  speedBarMaxGustSpreadKmh: { beginner: 0, intermediate: 8, advanced: 12, expert: 15 } as Record<Difficulty, number>,
  speedStepKmh: 0.5,
  expectedEfficiency: 0.9,
  highArrival: { minTailKmh: 5, infoM: 300, cautionM: { beginner: 500, intermediate: 500, advanced: 700, expert: 700 } as Record<Difficulty, number> },
  ptuEntryAglM: { beginner: 150, intermediate: 150, advanced: 120, expert: 100 } as Record<Difficulty, number>,
};

interface Polar {
  below: number;
  trim: number;
  half: number;
  rhoHalf: number;
  full: number;
  rhoFull: number;
}

/** Polaire simplifiée par catégorie (CDC §14.3) ; `below` = borne supérieure exclue de wing_glide_ratio. */
const POLARS: Polar[] = [
  { below: 8.5, trim: 36, half: 41, rhoHalf: 0.92, full: 46, rhoFull: 0.78 },
  { below: 9.5, trim: 37, half: 44, rhoHalf: 0.9, full: 51, rhoFull: 0.74 },
  { below: 10.5, trim: 39, half: 48, rhoHalf: 0.88, full: 57, rhoFull: 0.7 },
  { below: Infinity, trim: 40, half: 51, rhoHalf: 0.86, full: 62, rhoFull: 0.66 },
];

export function polarFor(wing: number): Polar {
  return POLARS.find((p) => wing < p.below) ?? POLARS[POLARS.length - 1]!;
}

/** ρ(V) = finesse(V) / finesse bras hauts, linéaire par morceaux. */
export function rho(p: Polar, v: number): number {
  if (v <= p.trim) return 1;
  if (v <= p.half) return 1 + ((p.rhoHalf - 1) * (v - p.trim)) / (p.half - p.trim);
  return p.rhoHalf + ((p.rhoFull - p.rhoHalf) * (Math.min(v, p.full) - p.half)) / (p.full - p.half);
}

// vecteur « vers où va le vent » (u vers l'E, v vers le N)
const rad = (d: number) => (d * Math.PI) / 180;
const toUV = (w: WindVec) => ({ u: w.speed * Math.sin(rad(w.dir + 180)), v: w.speed * Math.cos(rad(w.dir + 180)) });
const fromUV = (u: number, v: number): WindVec => ({ speed: Math.hypot(u, v), dir: normalizeDeg((Math.atan2(u, v) * 180) / Math.PI + 180) });
const lerpUV = (a: { u: number; v: number }, b: { u: number; v: number }, t: number) => ({ u: a.u + (b.u - a.u) * t, v: a.v + (b.v - a.v) * t });
const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));

/** Composante d'un vent le long d'un cap (+ = arrière) et travers (valeur absolue). */
export function trackComponents(w: WindVec, bearing: number): { along: number; cross: number } {
  const a = rad(bearing - w.dir);
  return { along: -w.speed * Math.cos(a), cross: Math.abs(w.speed * Math.sin(a)) };
}

/** Vent du profil d'altitude à z (interpolation (u, v)) ; sous le premier niveau : `fallback` (vent du déco). */
function profileAt(aloft: WindLevel[], z: number, fallback: WindVec): { u: number; v: number } {
  const lv = [...aloft].sort((a, b) => a.altitude_m - b.altitude_m);
  if (lv.length === 0 || z < lv[0]!.altitude_m) return toUV(fallback);
  for (let i = 1; i < lv.length; i++) {
    const a = lv[i - 1]!;
    const b = lv[i]!;
    if (z <= b.altitude_m) {
      const t = (z - a.altitude_m) / Math.max(1, b.altitude_m - a.altitude_m);
      return lerpUV(toUV({ speed: a.speed_kmh, dir: a.direction_deg }), toUV({ speed: b.speed_kmh, dir: b.direction_deg }), t);
    }
  }
  const top = lv[lv.length - 1]!;
  return toUV({ speed: top.speed_kmh, dir: top.direction_deg });
}

export interface GlideInput {
  from: Pt & { alt: number }; // point de départ du plané et altitude z0
  to: Pt & { elevation_m: number }; // atterro visé
  takeoffAlt: number; // altitude du déco (frontière vent du déco / profil)
  startIsTakeoff: boolean;
  takeoffWind: WindVec; // vent retenu au déco (rafale comprise)
  landingWind: WindVec; // vent retenu à l'atterro à l'heure d'arrivée
  aloft: WindLevel[]; // profil d'altitude au point de départ
  level: Difficulty;
  wing: number; // wing_glide_ratio
  k: number; // coefficient de finesse de calcul (niveau)
  kindFactor?: number; // f : 1 officiel, < 1 non officiel
  arrivalMarginM: number; // za = alt atterro + marge
  horizon?: Horizon;
  arrivalLegalHour?: number | null; // heure légale d'arrivée (bonus « brise établie »)
}

export interface GlideCalc {
  distanceKm: number;
  bearing: number;
  required: number;
  available: number;
  calm: number;
  wind: WindVec; // vent moyen rencontré
  along: number;
  cross: number;
  credit: number; // composante retenue (arrière × c plafonnée, face × g)
  creditFraction: number;
  gustFactor: number;
  speedKmh: number; // vitesse air retenue
  trimKmh: number;
  halfBarKmh: number;
  groundKmh: number; // vitesse sol retenue
  speedBarAllowed: boolean;
  penetrationOk: boolean;
  expectedRatio: number;
  expectedArrivalM: number;
}

/** Plané final avec le vent rencontré (CDC §14.1-14.4, simplifié : une branche droite). */
export function computeGlide(p: GlideInput): GlideCalc {
  const R = GLIDE_RULES;
  const f = p.kindFactor ?? 1;
  const distanceKm = haversineKm(p.from, p.to);
  const bearing = bearingDeg(p.from, p.to);
  const z0 = p.from.alt;
  const za = p.to.elevation_m + p.arrivalMarginM;
  const usable = z0 - za;
  const required = usable > 0 ? (distanceKm * 1000) / usable : 99;

  // vent rencontré, tranche par tranche (poids égaux : taux de chute constant)
  const landing = toUV(p.landingWind);
  const takeoff = toUV(p.takeoffWind);
  const breezeTop = p.to.elevation_m + R.breezeLayerM;
  const takeoffBottom = p.takeoffAlt - R.takeoffLayerM;
  const windAt = (z: number) => {
    if (z <= breezeTop) return landing;
    if (p.startIsTakeoff && z >= z0 - R.takeoffLayerM) return takeoff;
    if (z > p.takeoffAlt) return profileAt(p.aloft, z, p.takeoffWind);
    if (z >= takeoffBottom || takeoffBottom <= breezeTop) return takeoff;
    return lerpUV(landing, takeoff, clamp((z - breezeTop) / (takeoffBottom - breezeTop), 0, 1));
  };
  let su = 0;
  let sv = 0;
  let n = 0;
  const lo = Math.min(za, z0);
  const hi = Math.max(za, z0);
  for (let z = lo + R.sliceM / 2; z < hi || n === 0; z += R.sliceM) {
    const w = windAt(Math.min(z, hi));
    su += w.u;
    sv += w.v;
    n++;
  }
  const wind = fromUV(su / n, sv / n);
  const { along, cross } = trackComponents(wind, bearing);

  // part du vent arrière comptée (§14.2)
  const gustRatios = [p.takeoffWind, p.landingWind]
    .filter((w) => w.speed >= R.headGust.minWindKmh && (w.gust ?? 0) > w.speed)
    .map((w) => (w.gust ?? w.speed) / w.speed);
  const gustRatio = Math.max(1, ...gustRatios);
  let c = R.tailBase[p.level];
  const legal = p.arrivalLegalHour;
  const landingTail = trackComponents(p.landingWind, bearing).along;
  if (legal !== null && legal !== undefined && legal >= R.breeze.legalHours[0] && legal < R.breeze.legalHours[1] && p.landingWind.speed >= R.breeze.minKmh && landingTail >= R.breeze.minTailKmh)
    c += R.breeze.bonus;
  c -= (p.horizon && R.horizonMalus[p.horizon]) || 0;
  if (gustRatio > R.gustMalus.over) c -= R.gustMalus.malus;
  if (wind.speed < R.calmKmh) c = 0;
  c = clamp(c, 0, 1);
  const g = Math.min(R.headGust.max, 1 + R.headGust.factor * (gustRatio - 1));
  const credit = along > 0 ? Math.min(c * along, R.tailCapKmh[p.level]) : along * g;

  // vitesse : finesse sol max entre bras hauts et l'accélérateur permis (§14.3)
  const polar = polarFor(p.wing);
  const spread = Math.max(0, ...[p.takeoffWind, p.landingWind].map((w) => (w.gust ?? w.speed) - w.speed));
  const frac = R.speedBarFraction[p.level];
  const speedBarAllowed = frac > 0 && spread <= R.speedBarMaxGustSpreadKmh[p.level];
  const vmax = !speedBarAllowed ? polar.trim : frac >= 1 ? polar.full : polar.trim + (polar.half - polar.trim) * Math.min(1, frac * 2);
  let best = { v: polar.trim, ratio: Number.NEGATIVE_INFINITY, ground: 0 };
  for (let v = polar.trim; v <= vmax + 1e-9; v += R.speedStepKmh) {
    if (v <= cross) continue;
    const ground = Math.sqrt(v * v - cross * cross) + credit;
    const ratio = (rho(polar, v) * ground) / v;
    if (ratio > best.ratio + 1e-9) best = { v, ratio, ground };
  }
  const feasible = Number.isFinite(best.ratio) && best.ground > 0;
  const calm = p.wing * p.k * f;
  const available = feasible ? Math.max(0, calm * best.ratio) : 0;

  // hauteur d'arrivée attendue (§14.4) : vent prévu à 100 %, sans majoration, 90 % de la polaire
  const groundFull = best.v > cross ? Math.sqrt(best.v * best.v - cross * cross) + along : 0;
  const expectedRatio = Math.max(0, (p.wing * R.expectedEfficiency * rho(polar, best.v) * groundFull) / best.v);
  const expectedArrivalM = z0 - p.to.elevation_m - (distanceKm * 1000) / Math.max(0.5, expectedRatio);

  return {
    distanceKm,
    bearing,
    required,
    available,
    calm,
    wind,
    along,
    cross,
    credit,
    creditFraction: c,
    gustFactor: g,
    speedKmh: best.v,
    trimKmh: polar.trim,
    halfBarKmh: polar.half,
    groundKmh: feasible ? best.ground : 0,
    speedBarAllowed,
    penetrationOk: feasible && best.ground >= R.penetrationMinKmh[p.level],
    expectedRatio,
    expectedArrivalM,
  };
}

const f1 = (v: number) => formatNumber(v, 1);
const r10 = (v: number) => formatNumber(Math.round(v / 10) * 10);

/** HIGH_ARRIVAL (§14.4) : vent arrière ≥ 5 km/h et arrivée attendue ≥ 300 m ; jamais bloquant. */
export function isHighArrival(r: GlideCalc): boolean {
  return r.along >= GLIDE_RULES.highArrival.minTailKmh && r.expectedArrivalM >= GLIDE_RULES.highArrival.infoM;
}

/** Commentaire du moniteur (gabarits du CDC §14.7). */
export function glideComment(r: GlideCalc, ctx: { landingName: string; level: Difficulty }): string {
  const card = degToCardinalFr(r.wind.dir);
  const spd = Math.round(r.wind.speed);
  if (r.wind.speed < GLIDE_RULES.calmKmh) {
    const ratio = Math.abs(r.available - r.calm) < 0.05 ? `${f1(r.available)} (air calme)` : `${f1(r.available)} (${f1(r.calm)} sans vent)`;
    return `Vent faible sur le plané : finesse de calcul ${ratio}, arrivée attendue ≈ ${r10(r.expectedArrivalM)} m au-dessus de ${ctx.landingName}.`;
  }
  if (r.along >= GLIDE_RULES.highArrival.minTailKmh) {
    const counted = r.credit >= 0.5 ? `${f1(r.credit)} comptés` : "non comptés par prudence";
    const crossTxt = r.cross >= 3 ? `, ${Math.round(r.cross)} de travers` : "";
    let txt = `Vent du ${card} ≈ ${spd} km/h sur le plané : ${Math.round(r.along)} km/h dans le dos (${counted})${crossTxt}. Finesse de calcul ${f1(r.available)} au lieu de ${f1(r.calm)} sans vent ; finesse attendue ≈ ${f1(r.expectedRatio)}.`;
    if (isHighArrival(r)) txt += ` Arrivée haute à ${ctx.landingName} (≈ ${r10(r.expectedArrivalM)} m) : perds l'altitude au vent de l'atterro.`;
    return txt;
  }
  if (r.along <= -GLIDE_RULES.highArrival.minTailKmh) {
    const gust = -r.credit >= -r.along + 0.5 ? ` (${Math.round(-r.credit)} comptés avec les rafales)` : "";
    let txt = `Vent du ${card} ≈ ${spd} km/h de face sur le plané${gust} : finesse de calcul ${f1(r.available)} au lieu de ${f1(r.calm)} sans vent.`;
    if (r.speedKmh > r.trimKmh + 0.4) {
      const bar = r.speedKmh <= r.halfBarKmh + 0.1 ? "demi-barreau" : "accélérateur";
      txt += ` Accélère (${bar}, ≈ ${Math.round(r.speedKmh)} km/h) : vitesse sol ≈ ${Math.round(r.groundKmh)} km/h.`;
    } else if (ctx.level === "beginner") txt += " Élève : pas d'accélérateur, bras hauts.";
    else if (!r.speedBarAllowed) txt += " Rafales : pas d'accélérateur compté.";
    if (!r.penetrationOk)
      txt += ` Pénétration insuffisante : tu avancerais à ${Math.round(r.groundKmh)} km/h sol (minimum ${GLIDE_RULES.penetrationMinKmh[ctx.level]} à ton niveau).`;
    return txt;
  }
  if (r.cross >= 10) {
    const v = r.speedKmh;
    const crab = Math.round((Math.asin(Math.min(1, r.cross / v)) * 180) / Math.PI);
    const loss = Math.round(v - Math.sqrt(Math.max(0, v * v - r.cross * r.cross)));
    return `Vent de travers du ${card} ≈ ${spd} km/h sur le plané : en crabe (≈ ${crab}°), tu perds ${loss} km/h de vitesse sol ; finesse de calcul ${f1(r.available)} au lieu de ${f1(r.calm)}.`;
  }
  const tail = Math.round(r.along);
  const effect = tail === 0 ? "effet faible" : tail > 0 ? `${tail} km/h dans le dos seulement` : `${-tail} km/h de face seulement`;
  return `Vent du ${card} ≈ ${spd} km/h sur le plané, surtout de travers (${Math.round(r.cross)} km/h) : ${effect} ; finesse de calcul ${f1(r.available)} (${f1(r.calm)} sans vent), arrivée attendue ≈ ${r10(r.expectedArrivalM)} m au-dessus de ${ctx.landingName}.`;
}

const r1 = (v: number) => Math.round(v * 10) / 10;

/** FlightPlan.glide (contrat) à partir du calcul ; `marginOk` = toutes les vérifications du plan. */
export function toPlanGlide(r: GlideCalc, marginOk: boolean, comment: string): FlightPlanGlide {
  return {
    required_ratio: r1(Math.min(99, r.required)),
    available_ratio: r1(r.available),
    margin_ok: marginOk,
    calm_available_ratio: r1(r.calm),
    wind_along_track_kmh: r1(r.along),
    wind_credit_kmh: r1(r.credit),
    expected_arrival_height_m: Math.round(r.expectedArrivalM),
    comment,
  };
}

/** Risk HIGH_ARRIVAL (§14.4, §14.8) sur le plouf de référence déco → atterro principal ; null si non concerné. */
export function highArrivalRisk(r: GlideCalc, ctx: { landingName: string; level: Difficulty; landingWind: WindVec }): Risk | null {
  if (!isHighArrival(r)) return null;
  const R = GLIDE_RULES.highArrival;
  const caution = r.expectedArrivalM >= R.cautionM[ctx.level];
  const final = ctx.landingWind.speed >= 5 ? `finale face au ${degToCardinalFr(ctx.landingWind.dir)}` : "finale dans l'axe du terrain";
  const no360 = ctx.level === "beginner" ? "Pas de 360." : "Pas de 360 sous 150 m sol.";
  return {
    code: "HIGH_ARRIVAL",
    level: caution ? "caution" : "info",
    title: "Arrivée haute",
    detail:
      `Arrivée haute à ${ctx.landingName} : environ ${r10(r.expectedArrivalM)} m au-dessus de l'atterro avec le vent du ${degToCardinalFr(r.wind.dir)} dans le dos ` +
      `(${Math.round(r.along)} km/h). Perds l'altitude au vent de l'atterro et décalé sur le côté, en 8 face au vent, jamais derrière l'atterro : ` +
      `tu ne reviendrais pas contre la brise. ${no360} Entre dans la PTU vers ${GLIDE_RULES.ptuEntryAglM[ctx.level]} m sol, ${final}.`,
  };
}
