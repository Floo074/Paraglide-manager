import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { FlightPlan, PlanRequest } from "../api/types";
import { normalizePlan } from "../api/normalize";
import { LandingCandidateCard } from "../components/landing/LandingCandidates";
import { CriteriaPanel } from "../components/planner/CriteriaPanel";
import { DEFAULT_CRITERIA, type Criteria } from "../components/planner/criteria";
import { FreeTakeoffSection } from "../components/planner/FreeTakeoffSection";
import { LandingAnalysisPanel } from "../components/planner/LandingAnalysisPanel";
import { LandingAnalysisBlock } from "../components/plan/LandingAnalysisBlock";
import { StationReadingsBlock } from "../components/plan/StationReadingsBlock";
import { mockBeacons } from "../mocks/beacons";
import { mockAnalyzeLandings } from "../mocks/landings";
import { decodePlanId, mockPlanById, mockPlans } from "../mocks/planner";
import { setMockNow } from "../mocks/weather";
import { NO_LANDING_BEACON_TEXT } from "../utils/beacons";
import { beaconsFirst, findEquivalentPlan, refreshRequestFor } from "../utils/planRefresh";

const now = new Date("2026-10-08T12:00:00Z"); // 14:00 heure de Paris
setMockNow(now);
const takeoff = { lat: 45.8205, lon: 6.2525 };

const annecy: PlanRequest = {
  zone: { type: "circle", center: { lat: 45.81, lon: 6.2 }, radius_km: 18 },
  horizon: "30m",
  reference_time: now.toISOString(),
  filters: { duration_min_minutes: 30, duration_max_minutes: 180, difficulty: "intermediate", thermals: "allowed" },
};

describe("balises de démonstration", () => {
  it("balises Pioupiou réelles d'Annecy (id, nom, position) avec tendance", () => {
    const list = mockBeacons(now);
    const byId = Object.fromEntries(list.map((b) => [b.id, b]));
    expect(byId["pioupiou:1720"]?.name).toBe("Atterrissage de Doussard");
    expect(byId["pioupiou:1708"]?.name).toBe("Déco Anglettaz 1570m");
    expect(byId["pioupiou:1476"]?.name).toBe("Veyrier Club Nautique");
    expect(byId["pioupiou:1720"]?.lat).toBeCloseTo(45.781728, 5);
    expect(byId["pioupiou:1720"]?.trend?.window_min).toBe(60);
    expect(list.some((b) => b.trend === null)).toBe(true);
    expect(list.every((b) => b.stale === Date.parse(b.observed_at) < now.getTime() - 30 * 60_000)).toBe(true);
  });
});

describe("balises rattachées aux plans (station_readings)", () => {
  const res = mockPlans(annecy, now);
  it("Forclaz → Doussard : balise atterro Pioupiou 1720 représentative, briefing qui commence par les balises", () => {
    const p = res.plans.find((x) => x.takeoff.id === "fixture:forclaz");
    expect(p).toBeDefined();
    const land = p!.station_readings.filter((r) => r.site_role === "landing" && r.representative);
    expect(land.map((r) => r.beacon.id)).toContain("pioupiou:1720");
    expect(land[0]!.weight).toBeGreaterThan(0);
    expect(land[0]!.weight).toBeLessThanOrEqual(1);
    expect(p!.station_readings.some((r) => r.site_role === "takeoff" && r.representative)).toBe(true);
    expect(p!.briefing[0]).toMatch(/^Balises \(il y a \d+ min\)/);
    expect(p!.risks.some((r) => r.code === "NO_LANDING_BEACON")).toBe(false);
  });
  it("Planfait → Talloires : balise atterro trop ancienne → aucune représentative et risque NO_LANDING_BEACON", () => {
    const p = res.plans.find((x) => x.takeoff.id === "fixture:planfait");
    expect(p).toBeDefined();
    const land = p!.station_readings.filter((r) => r.site_role === "landing");
    expect(land.length).toBeGreaterThan(0);
    expect(land.every((r) => !r.representative && r.weight === 0)).toBe(true);
    expect(p!.risks.some((r) => r.code === "NO_LANDING_BEACON")).toBe(true);
  });
  it("landing_analysis : le premier candidat est l'atterro retenu", () => {
    for (const p of res.plans) {
      expect(p.landing_analysis.length).toBeGreaterThan(0);
      expect(p.landing_analysis[0]!.site.id).toBe(p.landing.id);
    }
  });
  it("au-delà de 2 h : pas de correction par les balises", () => {
    const later = mockPlans({ ...annecy, horizon: "8h" }, now);
    for (const p of later.plans) {
      expect(p.weather.takeoff.nowcast_correction).toBeNull();
      expect(p.station_readings.every((r) => !r.representative)).toBe(true);
    }
  });
});

describe("analyse des atterrissages (POST /api/landings/analyze)", () => {
  const run = (policy: "official_only" | "include_community" | "include_fields", difficulty: "beginner" | "intermediate" | "advanced" | "expert" = "advanced") =>
    mockAnalyzeLandings({ takeoff, horizon: "1h", reference_time: now.toISOString(), difficulty, landing_policy: policy }, now);

  it("politique « officiels uniquement »", () => {
    const a = run("official_only");
    expect(a.takeoff.source).toBe("user");
    expect(a.takeoff.official).toBe(false);
    expect(a.candidates.length).toBeGreaterThan(0);
    expect(a.candidates.every((c) => c.kind === "official" && c.site.landing_kind === "official")).toBe(true);
  });
  it("communautaires et champs ajoutés selon la politique, avec avertissements", () => {
    const comm = run("include_community");
    expect(comm.candidates.some((c) => c.kind === "community")).toBe(true);
    expect(comm.candidates.some((c) => c.kind === "field")).toBe(false);
    const fields = run("include_fields");
    const field = fields.candidates.find((c) => c.kind === "field");
    expect(field).toBeDefined();
    expect(field!.site.source).toBe("osm");
    expect(field!.warnings.join(" ")).toMatch(/SANS vérification humaine/);
    expect(fields.warnings).toContain("Atterrissages non officiels : repérage et autorisation du propriétaire à vérifier.");
  });
  it("candidats atteignables, classés (atterros principaux possibles d'abord, puis score)", () => {
    const a = run("include_fields");
    for (const c of a.candidates) {
      expect(c.required_glide_ratio).toBeLessThanOrEqual(c.available_glide_ratio);
      expect(c.score).toBeGreaterThanOrEqual(0);
      expect(c.score).toBeLessThanOrEqual(100);
      expect(c.wind_at_arrival).not.toBeNull();
      expect(c.reasons.length).toBeGreaterThan(0);
    }
    const mainOk = a.candidates.map((c) => c.kind === "official" || c.kind === "community");
    expect(mainOk.indexOf(false) === -1 || mainOk.slice(mainOk.indexOf(false)).every((x) => !x)).toBe(true);
  });
  it("jamais d'atterro non officiel pour un élève ; champs refusés au niveau intermédiaire", () => {
    expect(run("include_fields", "beginner").candidates.every((c) => c.kind === "official")).toBe(true);
    expect(run("include_fields", "intermediate").candidates.some((c) => c.kind === "field")).toBe(false);
  });
  it("cône de finesse : polygone fermé autour du déco", () => {
    const ring = run("official_only").glide_cone.coordinates[0]!;
    expect(ring.length).toBeGreaterThan(10);
    expect(ring[0]).toEqual(ring[ring.length - 1]);
    const lats = ring.map((c) => c[1]!);
    const lons = ring.map((c) => c[0]!);
    expect(Math.min(...lats)).toBeLessThan(takeoff.lat);
    expect(Math.max(...lats)).toBeGreaterThan(takeoff.lat);
    expect(Math.min(...lons)).toBeLessThan(takeoff.lon);
    expect(Math.max(...lons)).toBeGreaterThan(takeoff.lon);
  });
  it("altitude et orientations déduites si absentes, conservées si fournies", () => {
    const a = mockAnalyzeLandings({ takeoff: { ...takeoff, elevation_m: 1500, orientations: ["W"] }, horizon: "1h", difficulty: "advanced", landing_policy: "official_only" }, now);
    expect(a.takeoff.elevation_m).toBe(1500);
    expect(a.takeoff.orientations).toEqual(["W"]);
    const b = run("official_only");
    expect(b.takeoff.orientations.length).toBeGreaterThan(0);
    expect(b.warnings.some((w) => w.startsWith("Altitude déduite du relief"))).toBe(true);
  });
});

describe("plans en décollage libre (mode custom_takeoff)", () => {
  const req: PlanRequest = {
    ...annecy,
    horizon: "1h",
    zone: { type: "circle", center: takeoff, radius_km: 15 },
    mode: "custom_takeoff",
    custom_takeoff: { ...takeoff, orientations: ["W", "WNW"] },
    filters: { ...annecy.filters, difficulty: "advanced", landing_policy: "include_fields", duration_min_minutes: 15, duration_max_minutes: 120 },
  };
  it("plans depuis le point, identifiant décodable et recalculable", () => {
    const res = mockPlans(req, now);
    expect(res.plans.length).toBeGreaterThan(0);
    const p = res.plans[0]!;
    expect(p.takeoff.source).toBe("user");
    expect(p.takeoff.orientations).toEqual(["W", "WNW"]);
    expect(p.risks.some((r) => r.code === "FREE_TAKEOFF")).toBe(true);
    expect(p.landing_analysis[0]!.site.id).toBe(p.landing.id);
    const key = decodePlanId(p.id);
    expect(key?.custom?.policy).toBe("include_fields");
    expect(key?.custom?.takeoff.orientations).toEqual(["W", "WNW"]);
    const again = mockPlanById(p.id, now);
    expect(again.takeoff.id).toBe(p.takeoff.id);
    expect(again.landing.id).toBe(p.landing.id);
  });
  it("refusé au niveau élève (FREE_TAKEOFF)", () => {
    const res = mockPlans({ ...req, filters: { ...req.filters, difficulty: "beginner" } }, now);
    expect(res.plans).toHaveLength(0);
    expect(res.rejected[0]!.reasons[0]).toMatch(/^\[FREE_TAKEOFF\]/);
  });
  it("au mieux LIMITE au niveau intermédiaire", () => {
    const res = mockPlans({ ...req, filters: { ...req.filters, difficulty: "intermediate" } }, now);
    expect(res.plans.every((p) => p.flyability !== "go")).toBe(true);
  });
  it("422 sans point de décollage", () => {
    expect(() => mockPlans({ ...req, custom_takeoff: undefined }, now)).toThrow();
  });
});

describe("actualisation des balises", () => {
  const res = mockPlans(annecy, now);
  const p = res.plans[0]!;
  it("plan équivalent retrouvé dans une nouvelle réponse", () => {
    const later = mockPlans({ ...annecy, reference_time: new Date(now.getTime() + 10 * 60_000).toISOString() }, now);
    const eq = findEquivalentPlan(p, later.plans);
    expect(eq?.takeoff.id).toBe(p.takeoff.id);
    expect(findEquivalentPlan(p, [])).toBeNull();
  });
  it("même requête si connue, sinon requête reconstituée autour du déco", () => {
    expect(refreshRequestFor(p, annecy, "intermediate", now)).toEqual({ request: annecy, rebuilt: false });
    const { request, rebuilt } = refreshRequestFor(p, null, "advanced", now);
    expect(rebuilt).toBe(true);
    expect(request.zone).toMatchObject({ type: "circle", center: { lat: p.takeoff.lat, lon: p.takeoff.lon } });
    expect(request.filters.difficulty).toBe("advanced");
    expect(request.mode).toBe("classic");
  });
  it("bloc balises en tête jusqu'à 1 h d'horizon", () => {
    expect(beaconsFirst(p, { ...annecy, horizon: "15m" }, null, now)).toBe(true);
    expect(beaconsFirst(p, { ...annecy, horizon: "1h" }, null, now)).toBe(true);
    expect(beaconsFirst(p, { ...annecy, horizon: "2h" }, null, now)).toBe(false);
    expect(beaconsFirst(p, null, now.toISOString(), now)).toBe(true); // cible à 30 min du calcul
  });
});

describe("normalisation (backend en retard sur le contrat)", () => {
  it("champs récents absents complétés sans rien inventer", () => {
    const p = mockPlans(annecy, now).plans[0]!;
    const raw = JSON.parse(JSON.stringify(p)) as Record<string, unknown>;
    delete raw.station_readings;
    delete raw.landing_analysis;
    const t = raw.takeoff as Record<string, unknown>;
    delete t.official;
    delete t.landing_kind;
    (raw.beacons_nearby as Record<string, unknown>[]).forEach((b) => delete b.trend);
    const n = normalizePlan(raw as unknown as FlightPlan);
    expect(n.station_readings).toEqual([]);
    expect(n.landing_analysis).toEqual([]);
    expect(n.takeoff.official).toBe(true);
    expect(n.takeoff.landing_kind).toBeNull();
    expect(n.landing.landing_kind).toBe("official");
    expect(n.beacons_nearby.every((b) => b.trend === null)).toBe(true);
  });
});

describe("rendu des nouveaux blocs (sans navigateur)", () => {
  const res = mockPlans(annecy, now);
  const planfait = res.plans.find((x) => x.takeoff.id === "fixture:planfait")!;
  const forclaz = res.plans.find((x) => x.takeoff.id === "fixture:forclaz")!;
  const block = (plan: FlightPlan) =>
    renderToStaticMarkup(
      createElement(StationReadingsBlock, { plan, level: "intermediate", now, updatedAt: now.toISOString(), onRefresh: () => {}, refreshing: false, rebuilt: false }),
    ).replace(/&#x27;/g, "'");
  it("« Balises en direct » : colonnes, tendance, attribution, message sans balise atterro", () => {
    const html = block(forclaz);
    expect(html).toContain("Balises en direct");
    expect(html).toContain("Atterrissage de Doussard");
    expect(html).toContain("représentative");
    expect(html).toContain("Actualiser les balises");
    expect(html).toContain("km/h en 1");
    expect(html).toContain("contributeurs OpenWindMap / Pioupiou");
    expect(block(planfait)).toContain(NO_LANDING_BEACON_TEXT);
  });
  it("fiche candidat et section « Analyse des atterrissages »", () => {
    const a = mockAnalyzeLandings({ takeoff, horizon: "1h", reference_time: now.toISOString(), difficulty: "advanced", landing_policy: "include_fields" }, now);
    const field = a.candidates.find((c) => c.kind === "field")!;
    const html = renderToStaticMarkup(createElement(LandingCandidateCard, { candidate: field, rank: 3, level: "advanced", from: takeoff, defaultOpen: true }));
    expect(html).toContain("Champ détecté");
    expect(html).toContain("Obstacles");
    expect(html).toContain("Pourquoi ce classement");
    expect(html).toContain("Usage communautaire");
    const section = renderToStaticMarkup(createElement(LandingAnalysisBlock, { plan: forclaz, level: "intermediate" }));
    expect(section).toContain("Analyse des atterrissages");
    expect(section).toContain("Atterro retenu");
  });
  it("panneau de critères en décollage libre et onglet Atterros", () => {
    const criteria: Criteria = { ...DEFAULT_CRITERIA, mode: "custom_takeoff", horizon: "15m", landingPolicy: "include_fields", difficulty: "advanced" };
    const a = mockAnalyzeLandings({ takeoff, horizon: "15m", reference_time: now.toISOString(), difficulty: "advanced", landing_policy: "include_fields" }, now);
    const noop = () => {};
    const section = createElement(FreeTakeoffSection, {
      criteria,
      setCriteria: noop,
      takeoff: { ...takeoff, elevation: null, orientations: ["W"], name: "" },
      onTakeoff: noop,
      picking: false,
      onPicking: noop,
      onLocate: noop,
      locating: false,
      onAnalyze: noop,
      analyzing: false,
      analysisError: null,
      analysis: a,
      analysisStale: false,
      onShowAnalysis: noop,
    });
    const html = renderToStaticMarkup(
      createElement(CriteriaPanel, { criteria, setCriteria: noop, zone: annecy.zone, onZone: noop, now, placeSection: section }),
    ).replace(/&#x27;/g, "'");
    expect(html).toContain("Décollage libre");
    expect(html).toContain("Atterrissages non officiels : repérage et autorisation du propriétaire à vérifier");
    expect(html).toContain("Officiels uniquement");
    expect(html).toContain("+ champs détectés");
    expect(html).toContain("Analyser les atterrissages");
    expect(html).toContain("15 min");
    expect(html.indexOf("15 min")).toBeLessThan(html.indexOf("30 min"));
    const panel = renderToStaticMarkup(
      createElement(LandingAnalysisPanel, { analysis: a, level: "advanced", stale: false, selectedId: null, onSelect: noop, onReanalyze: noop, now, demo: true }),
    );
    expect(panel).toContain("Meilleur choix");
    expect(panel).toContain("Champ détecté");
  });
});
