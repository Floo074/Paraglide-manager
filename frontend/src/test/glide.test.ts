import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { FlightPlan, FlightPlanGlide, LandingCandidate, PlanRequest } from "../api/types";
import { normalizeGlide, normalizePlan } from "../api/normalize";
import { LandingCandidateCard } from "../components/landing/LandingCandidates";
import { GlideBlock } from "../components/plan/GlideBlock";
import { computeGlide } from "../mocks/glideWind";
import { mockAnalyzeLandings } from "../mocks/landings";
import { mockPlans } from "../mocks/planner";
import { setMockNow } from "../mocks/weather";
import {
  alongWindKind,
  arrivalLevel,
  formatAlongWind,
  formatArrivalHeight,
  formatCandidateWind,
  formatGlideMarginPct,
  formatSignedKmh,
  formatWindCredit,
  formatWindEffect,
  formatWindGain,
  glideMapSummary,
  glideMarginLevel,
  glideTone,
  known,
  showCalmRatio,
} from "../utils/glide";

const NB = " ";
const MINUS = "−";

const glide = (over: Partial<FlightPlanGlide> = {}): FlightPlanGlide => ({
  required_ratio: 5.9,
  available_ratio: 8.3,
  margin_ok: true,
  calm_available_ratio: 6.8,
  wind_along_track_kmh: 10.8,
  wind_credit_kmh: 8.6,
  expected_arrival_height_m: 372,
  comment: "Vent du N ≈ 13 km/h sur le plané : 11 km/h dans le dos (8,6 comptés), 7 de travers.",
  ...over,
});

describe("plané final : formatage du vent sur le plané", () => {
  it("composante signée relative au cap (+ = dans le dos, − = de face)", () => {
    expect(formatSignedKmh(14.2)).toBe(`+14${NB}km/h`);
    expect(formatSignedKmh(-11.6)).toBe(`${MINUS}12${NB}km/h`);
    expect(formatSignedKmh(0.3)).toBe(`0${NB}km/h`);
    expect(formatAlongWind(14)).toBe(`+14${NB}km/h dans le dos`);
    expect(formatAlongWind(-12)).toBe(`${MINUS}12${NB}km/h de face`);
    expect(formatAlongWind(-0.4)).toBe("vent nul");
  });
  it("arrière, face ou faible (seuil 5 km/h du CDC §14.2)", () => {
    expect(alongWindKind(5)).toBe("tail");
    expect(alongWindKind(4.9)).toBe("weak");
    expect(alongWindKind(-4.9)).toBe("weak");
    expect(alongWindKind(-5)).toBe("head");
  });
  it("candidat : composante inconnue (backend antérieur) → « inconnu »", () => {
    expect(formatCandidateWind(9.6)).toBe(`+10${NB}km/h dans le dos`);
    expect(formatCandidateWind(null)).toBe("inconnu");
    expect(formatCandidateWind(undefined)).toBe("inconnu");
    expect(known(Number.NaN)).toBe(false);
    expect(known(0)).toBe(true);
  });
  it("part du vent comptée dans la finesse de calcul", () => {
    expect(formatWindCredit(10.8, 8.6)).toBe(`8,6${NB}km/h comptés (80${NB}%)`);
    expect(formatWindCredit(12, 12)).toBe("compté en entier");
    expect(formatWindCredit(9, 0)).toBe("non compté par prudence");
    expect(formatWindCredit(3, 0)).toBe("trop faible pour être compté");
    expect(formatWindCredit(1.5, 1)).toBe(`1${NB}km/h compté (67${NB}%)`);
    // face : en entier, majoré par les rafales (g ≤ 1,2)
    expect(formatWindCredit(-12.5, -14.9)).toBe(`14,9${NB}km/h comptés avec les rafales`);
    expect(formatWindCredit(-12.5, -12.5)).toBe("compté en entier");
    expect(formatWindCredit(0.2, 0)).toBe("");
    expect(formatWindCredit(Number.NaN, 0)).toBe("");
  });
});

describe("plané final : finesse, marge, arrivée", () => {
  it("marge : OK, faible au-delà de r = 0,90, hors de portée au-delà de 1", () => {
    expect(glideMarginLevel(glide())).toBe("ok");
    expect(glideMarginLevel(glide({ required_ratio: 7.6 }))).toBe("low");
    expect(glideMarginLevel(glide({ required_ratio: 8.4 }))).toBe("over");
    expect(glideMarginLevel(glide({ margin_ok: false }))).toBe("over");
    expect(glideMarginLevel(glide({ required_ratio: 0 }))).toBe("ok"); // top landing
    expect(formatGlideMarginPct(5.9, 8.3)).toBe(`marge 29${NB}%`);
    expect(formatGlideMarginPct(5.9, 4.1)).toBe(`il manque 44${NB}%`);
    expect(formatGlideMarginPct(0, 8)).toBe("pas de plané à vérifier");
  });
  it("effet du vent par rapport à l'air calme (valeur barrée)", () => {
    expect(formatWindGain(6.8, 8.3)).toBe(`+22${NB}%`);
    expect(formatWindGain(6.8, 4.1)).toBe(`${MINUS}40${NB}%`);
    expect(formatWindGain(6.8, 6.8)).toBe("=");
    expect(formatWindGain(Number.NaN, 6.8)).toBe("");
    expect(formatWindEffect(6.8, 8.3)).toBe(`+22${NB}% grâce au vent`);
    expect(formatWindEffect(6.8, 4.1)).toBe(`${MINUS}40${NB}% à cause du vent`);
    expect(showCalmRatio(glide())).toBe(true);
    expect(showCalmRatio(glide({ available_ratio: 6.82 }))).toBe(false);
    expect(showCalmRatio(glide({ calm_available_ratio: Number.NaN }))).toBe(false);
  });
  it("hauteur d'arrivée : haute avec vent arrière ≥ 300 m, très haute au seuil du niveau (CDC §14.4)", () => {
    expect(arrivalLevel(372, 10.8, "intermediate")).toBe("high");
    expect(arrivalLevel(520, 10.8, "intermediate")).toBe("very_high");
    expect(arrivalLevel(520, 10.8, "advanced")).toBe("high");
    expect(arrivalLevel(372, 2, "intermediate")).toBe("normal"); // pas de vent arrière : pas d'« arrivée haute »
    expect(arrivalLevel(60, -12, "advanced")).toBe("low");
    expect(arrivalLevel(-25, -12, "advanced")).toBe("below");
    expect(arrivalLevel(null, 10, "expert")).toBe("unknown");
    expect(formatArrivalHeight(372)).toBe(`≈${NB}370${NB}m`);
    expect(formatArrivalHeight(-25)).toBe(`${MINUS}30${NB}m`);
    expect(formatArrivalHeight(null)).toBe("—");
  });
  it("couleur du bloc : rouge > orange > bleu (arrivée haute) > vert", () => {
    expect(glideTone("over", "high")).toBe("nogo");
    expect(glideTone("ok", "below")).toBe("nogo");
    expect(glideTone("low", "high")).toBe("marginal");
    expect(glideTone("ok", "very_high")).toBe("high");
    expect(glideTone("ok", "normal")).toBe("ok");
  });
  it("résumé de l'indicateur de carte", () => {
    expect(glideMapSummary(glide())).toBe(`Vent sur le plané +11${NB}km/h dans le dos · finesse 6,8 → 8,3 · arrivée ≈${NB}370${NB}m`);
    expect(glideMapSummary(glide({ wind_along_track_kmh: Number.NaN, available_ratio: 6.8, expected_arrival_height_m: null }))).toBe("finesse 6,8");
  });
});

describe("normalisation du plané (backend antérieur au §14)", () => {
  it("champs absents → NaN / null / '' : rien d'inventé", () => {
    const g = normalizeGlide({ required_ratio: 5.9, available_ratio: 8.4, margin_ok: true } as FlightPlanGlide);
    expect(g.required_ratio).toBe(5.9);
    expect(Number.isNaN(g.calm_available_ratio)).toBe(true);
    expect(Number.isNaN(g.wind_along_track_kmh)).toBe(true);
    expect(Number.isNaN(g.wind_credit_kmh)).toBe(true);
    expect(g.expected_arrival_height_m).toBeNull();
    expect(g.comment).toBe("");
    expect(showCalmRatio(g)).toBe(false);
  });
});

// Moteur de démonstration : mêmes chiffres que les références du CDC pilote §14.6 (Forclaz → Doussard).
const forclaz = { lat: 45.815, lon: 6.2465, alt: 1245 };
const doussard = { lat: 45.782, lon: 6.2224, elevation_m: 452 };
const base = { from: forclaz, to: doussard, takeoffAlt: 1245, startIsTakeoff: true, wing: 8.5, k: 0.8, arrivalMarginM: 100, horizon: "12h" as const };

describe("démo : plané Forclaz → Doussard (références CDC §14.6)", () => {
  it("S33 : N 13 km/h et brise du lac → 11 km/h dans le dos, 8,6 comptés, finesse 8,3 au lieu de 6,8, arrivée ≈ 370 m", () => {
    const r = computeGlide({
      ...base,
      takeoffWind: { speed: 13, dir: 345, gust: 18 },
      landingWind: { speed: 13, dir: 0, gust: 18 },
      aloft: [{ altitude_m: 1550, pressure_hpa: 845, speed_kmh: 15, direction_deg: 350 }],
      level: "intermediate",
      arrivalLegalHour: 14.25,
    });
    expect(r.required).toBeCloseTo(5.94, 1);
    expect(r.along).toBeCloseTo(10.8, 0);
    expect(r.cross).toBeCloseTo(7.1, 0);
    expect(r.credit).toBeCloseTo(8.6, 1);
    expect(r.calm).toBeCloseTo(6.8, 5);
    expect(r.available).toBeCloseTo(8.26, 1);
    expect(r.expectedArrivalM).toBeGreaterThan(330);
    expect(r.expectedArrivalM).toBeLessThan(430);
  });
  it("S38 : S jusqu'à Doussard → 12,5 km/h de face, 14,9 comptés avec les rafales, finesse 4,1 : ne passe pas", () => {
    const r = computeGlide({
      ...base,
      takeoffWind: { speed: 9, dir: 280, gust: 13 },
      landingWind: { speed: 21, dir: 190, gust: 29 },
      aloft: [{ altitude_m: 1550, pressure_hpa: 845, speed_kmh: 16, direction_deg: 190 }],
      level: "advanced",
      arrivalLegalHour: 14.75,
    });
    expect(r.along).toBeCloseTo(-12.5, 0);
    expect(r.credit).toBeCloseTo(-14.9, 0);
    expect(r.available).toBeCloseTo(4.1, 1);
    expect(r.required / r.available).toBeGreaterThan(1.4);
    expect(r.expectedArrivalM).toBeLessThan(0);
  });
  it("air calme : finesse de calcul = wing × k, arrivée ≈ 255 m", () => {
    const r = computeGlide({ ...base, takeoffWind: { speed: 0, dir: 0 }, landingWind: { speed: 0, dir: 0 }, aloft: [], level: "beginner", arrivalLegalHour: 14 });
    expect(r.available).toBeCloseTo(6.8, 5);
    expect(r.credit).toBe(0);
    expect(r.expectedArrivalM).toBeCloseTo(255, -1);
  });
});

describe("démo : plans par flux de N (J+1)", () => {
  const now = new Date("2026-10-08T07:00:00Z");
  setMockNow(now);
  const req = (difficulty: PlanRequest["filters"]["difficulty"]): PlanRequest => ({
    zone: { type: "circle", center: { lat: 45.81, lon: 6.2 }, radius_km: 18 },
    horizon: "2h",
    reference_time: "2026-10-09T09:00:00Z", // cible 13 h légales, flux de N
    filters: { duration_min_minutes: 5, duration_max_minutes: 300, difficulty, thermals: "allowed" },
  });
  const plans = (["intermediate", "advanced"] as const).flatMap((d) => mockPlans(req(d), now).plans);

  it("Forclaz → Doussard : vent dans le dos, finesse au-dessus de l'air calme, arrivée haute (non bloquante)", () => {
    const fd = plans.filter((p) => p.takeoff.id === "fixture:forclaz" && p.landing.id === "fixture:doussard");
    expect(fd.length).toBeGreaterThan(0);
    for (const p of fd) {
      const g = p.glide;
      expect(g.wind_along_track_kmh, p.title).toBeGreaterThanOrEqual(8);
      expect(g.available_ratio, p.title).toBeGreaterThan(g.calm_available_ratio + 1);
      expect(g.expected_arrival_height_m!, p.title).toBeGreaterThanOrEqual(300);
      expect(g.comment).toContain("dans le dos");
      expect(g.comment).toContain("Arrivée haute");
      expect(p.risks.find((r) => r.code === "HIGH_ARRIVAL")?.level, p.title).toBe("info");
    }
    expect(fd.some((p) => p.flyability === "go")).toBe(true); // l'arrivée haute ne retire rien au verdict
  });
  it("un plané face au vent (Semnoz → Saint-Jorioz) : finesse sous l'air calme, refusé", () => {
    const head = plans.filter((p) => p.glide.wind_along_track_kmh <= -5);
    expect(head.length).toBeGreaterThan(0);
    for (const p of head) {
      expect(p.glide.available_ratio, p.title).toBeLessThan(p.glide.calm_available_ratio);
      expect(p.glide.comment).toContain("de face");
    }
    expect(head.some((p) => !p.glide.margin_ok && p.risks.some((r) => r.code === "GLIDE_MARGIN" && r.level === "danger"))).toBe(true);
  });
  it("invariants du contrat : part retenue ≤ composante brute, commentaire renseigné", () => {
    for (const p of plans) {
      expect(p.glide.wind_credit_kmh, p.title).toBeLessThanOrEqual(p.glide.wind_along_track_kmh + 0.11);
      expect(p.glide.comment.length).toBeGreaterThan(0);
      for (const c of p.landing_analysis) expect(known(c.wind_along_track_kmh), c.site.name).toBe(true);
    }
  });
  it("décollage libre : vent sur le plané de chaque candidat", () => {
    const res = mockAnalyzeLandings(
      { takeoff: { lat: 45.8205, lon: 6.2525, elevation_m: 1450 }, horizon: "2h", reference_time: "2026-10-09T09:00:00Z", difficulty: "advanced" },
      now,
    );
    expect(res.candidates.length).toBeGreaterThan(0);
    for (const c of res.candidates) expect(known(c.wind_along_track_kmh), c.site.name).toBe(true);
  });

  const render = (el: ReturnType<typeof createElement>) => renderToStaticMarkup(el).replace(/&#x27;/g, "'");
  it("bloc « Plané final » : requise / disponible, valeur sans vent barrée, vent dans le dos, part comptée, arrivée haute, commentaire", () => {
    const p = plans.find((x) => x.takeoff.id === "fixture:forclaz" && x.landing.id === "fixture:doussard")!;
    const html = render(createElement(GlideBlock, { plan: p, level: "intermediate" }));
    expect(html).toContain("Plané final");
    expect(html).toMatch(/<s class="glide-calm"[^>]*>6,8<\/s>/);
    expect(html).toContain("grâce au vent");
    expect(html).toContain("dans le dos");
    expect(html).toContain("comptés");
    expect(html).toContain("arrivée haute");
    expect(html).toContain("glide-block--high");
    expect(html).toContain(p.glide.comment.replace(/'/g, "'").slice(0, 30));
  });
  it("bloc « Plané final » d'un backend antérieur : pas de chiffre inventé", () => {
    const p = plans[0]!;
    const raw = JSON.parse(JSON.stringify(p)) as FlightPlan;
    raw.glide = { required_ratio: 5, available_ratio: 7, margin_ok: true } as FlightPlanGlide;
    const html = render(createElement(GlideBlock, { plan: normalizePlan(raw), level: "intermediate" }));
    expect(html).toContain("non communiqué par le serveur");
    expect(html).toContain("non estimée");
    expect(html).not.toContain("NaN");
    expect(html).not.toContain("glide-calm");
  });
  it("fiche candidat : vent sur le plané vers ce terrain", () => {
    const p = plans.find((x) => x.landing_analysis.some((c) => (c.wind_along_track_kmh ?? 0) >= 5))!;
    const c = p.landing_analysis.find((x) => (x.wind_along_track_kmh ?? 0) >= 5)! as LandingCandidate;
    const html = render(createElement(LandingCandidateCard, { candidate: c, rank: 1, level: "intermediate", defaultOpen: true }));
    expect(html).toContain("lc-glide-wind--tail");
    expect(html).toContain("Vent sur le plané");
    expect(html).toContain(formatAlongWind(c.wind_along_track_kmh!));
  });
});
