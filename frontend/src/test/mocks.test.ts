import { describe, expect, it } from "vitest";
import { describeErrorDetail, splitReasonCode, ApiError } from "../api/errors";
import { decodePlanId, mockPlanById, mockPlans } from "../mocks/planner";
import { setMockNow } from "../mocks/weather";
import { windVerdict, takeoffLimits } from "../config/thresholds";
import type { PlanRequest } from "../api/types";

const now = new Date("2026-10-08T09:00:00Z"); // 11:00 heure de Paris
setMockNow(now);

const base: PlanRequest = {
  zone: { type: "circle", center: { lat: 45.81, lon: 6.2 }, radius_km: 18 },
  horizon: "2h",
  reference_time: now.toISOString(),
  filters: { duration_min_minutes: 30, duration_max_minutes: 180, difficulty: "intermediate", thermals: "allowed" },
};

describe("moteur de démonstration", () => {
  it("plans triés par score, au plus 2 par déco, identifiants décodables", () => {
    const res = mockPlans(base, now);
    expect(res.data_mode).toBe("mock");
    expect(res.target_time).toBe("2026-10-08T11:00:00.000Z");
    const scores = res.plans.map((p) => p.score);
    expect([...scores].sort((a, b) => b - a)).toEqual(scores);
    const perSite = new Map<string, number>();
    res.plans.forEach((p) => perSite.set(p.takeoff.id, (perSite.get(p.takeoff.id) ?? 0) + 1));
    expect(Math.max(...perSite.values())).toBeLessThanOrEqual(2);
    res.plans.forEach((p, i) => {
      expect(p.rank).toBe(i + 1);
      expect(decodePlanId(p.id)).not.toBeNull();
      expect(p.links.gpx).toBe(`/api/plans/${p.id}/gpx`);
    });
  });
  it("un plan se recalcule depuis son identifiant (lien partageable)", () => {
    const res = mockPlans(base, now);
    const p = res.plans[0]!;
    const again = mockPlanById(p.id, now);
    expect(again.id).toBe(p.id);
    expect(again.takeoff.id).toBe(p.takeoff.id);
    expect(again.flight_type).toBe(p.flight_type);
  });
  it("le site fermé est écarté avec une raison codée", () => {
    const res = mockPlans({ ...base, zone: { type: "circle", center: { lat: 45.9, lon: 6.19 }, radius_km: 5 } }, now);
    const veyrier = res.rejected.find((r) => r.site.id === "fixture:veyrier");
    expect(veyrier).toBeDefined();
    expect(splitReasonCode(veyrier!.reasons[0]!).code).toBe("SITE_CLOSED");
  });
  it("de nuit, aucun vol", () => {
    const res = mockPlans({ ...base, reference_time: "2026-10-08T19:30:00Z", horizon: "30m" }, now);
    expect(res.plans).toHaveLength(0);
    expect(res.rejected.length).toBeGreaterThan(0);
  });
  it("422 si la zone est trop grande", () => {
    expect(() => mockPlans({ ...base, zone: { type: "circle", center: { lat: 45, lon: 6 }, radius_km: 400 } }, now)).toThrow(ApiError);
  });
});

describe("erreurs et seuils", () => {
  it("détail d'erreur FastAPI", () => {
    expect(describeErrorDetail("Plan introuvable")).toBe("Plan introuvable");
    expect(describeErrorDetail([{ loc: ["body"], msg: "Value error, Rayon trop grand" }])).toBe("Rayon trop grand");
    expect(describeErrorDetail(42)).toBeNull();
    expect(splitReasonCode("[LEE_SIDE] Dévent : vent de NO")).toEqual({ code: "LEE_SIDE", text: "Dévent : vent de NO" });
    expect(splitReasonCode("Sans code")).toEqual({ code: null, text: "Sans code" });
  });
  it("couleur selon les seuils du niveau (vert < 80 %, orange 80-100 %, rouge au-delà)", () => {
    const lim = takeoffLimits("intermediate");
    expect(windVerdict(12, 15, lim)).toBe("ok");
    expect(windVerdict(17, 18, lim)).toBe("near");
    expect(windVerdict(21, 22, lim)).toBe("over");
    expect(windVerdict(10, 27, lim)).toBe("over");
    // soaring : seuils dynamiques plus hauts
    expect(windVerdict(18, 20, takeoffLimits("beginner", "ridge_soaring"))).toBe("near");
    expect(windVerdict(18, 20, takeoffLimits("beginner"))).toBe("over");
  });
});
