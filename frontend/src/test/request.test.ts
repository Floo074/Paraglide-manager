import { describe, expect, it } from "vitest";
import {
  CUSTOM_ZONE_RADIUS_KM,
  DEFAULT_CRITERIA,
  buildLandingAnalyzeRequest,
  buildPlanRequest,
  isCriteria,
  isFreeTakeoff,
  planRequestError,
  toCustomTakeoff,
  withCriteriaDefaults,
  type Criteria,
  type FreeTakeoff,
} from "../components/planner/criteria";
import type { Zone } from "../api/types";

const zone: Zone = { type: "circle", center: { lat: 45.81, lon: 6.2 }, radius_km: 18 };
const free: Criteria = { ...DEFAULT_CRITERIA, mode: "custom_takeoff", landingPolicy: "include_community", difficulty: "advanced", horizon: "15m" };
const point: FreeTakeoff = { lat: 45.8205123456, lon: 6.2525987654, elevation: null, orientations: [], name: "" };

describe("requête POST /api/plans", () => {
  it("mode classique : mode explicite, atterros officiels, pas de custom_takeoff", () => {
    const req = buildPlanRequest(zone, DEFAULT_CRITERIA);
    expect(req.mode).toBe("classic");
    expect(req.zone).toEqual(zone);
    expect(req.filters.landing_policy).toBe("official_only");
    expect(req).not.toHaveProperty("custom_takeoff");
    // un point posé est ignoré en mode classique
    expect(buildPlanRequest(zone, DEFAULT_CRITERIA, point)).toEqual(req);
  });
  it("décollage libre : custom_takeoff, landing_policy et zone centrée sur le point", () => {
    const req = buildPlanRequest(zone, free, point);
    expect(req.mode).toBe("custom_takeoff");
    expect(req.horizon).toBe("15m");
    expect(req.custom_takeoff).toEqual({ lat: 45.82051, lon: 6.2526 });
    expect(req.filters.landing_policy).toBe("include_community");
    expect(req.filters.difficulty).toBe("advanced");
    expect(req.zone).toEqual({ type: "circle", center: { lat: 45.82051, lon: 6.2526 }, radius_km: CUSTOM_ZONE_RADIUS_KM });
    // sérialisation JSON : aucun champ facultatif vide
    const json = JSON.parse(JSON.stringify(req));
    expect(json.custom_takeoff).toEqual({ lat: 45.82051, lon: 6.2526 });
  });
  it("décollage libre complet : altitude arrondie, orientations dans l'ordre de la rose, nom nettoyé", () => {
    const t: FreeTakeoff = { ...point, elevation: 1612.6, orientations: ["WNW", "N", "W"], name: "  Sommet de la Tournette " };
    expect(toCustomTakeoff(t)).toEqual({ lat: 45.82051, lon: 6.2526, elevation_m: 1613, orientations: ["N", "W", "WNW"], name: "Sommet de la Tournette" });
    expect(buildPlanRequest(zone, free, t).custom_takeoff).toEqual(toCustomTakeoff(t));
  });
  it("heure de référence conservée en ISO", () => {
    const req = buildPlanRequest(zone, { ...free, referenceTime: "2026-10-08T07:00:00.000Z" }, point);
    expect(req.reference_time).toBe("2026-10-08T07:00:00.000Z");
  });
  it("sans point posé : recherche bloquée avec un message explicite", () => {
    expect(planRequestError(free, null)).toBe("Pose d'abord le point de décollage sur la carte.");
    expect(planRequestError(free, point)).toBeNull();
    expect(planRequestError(DEFAULT_CRITERIA, null)).toBeNull();
    expect(buildPlanRequest(zone, free, null).mode).toBe("classic");
  });
});

describe("requête POST /api/landings/analyze", () => {
  it("décollage, horizon, niveau, finesse et politique d'atterrissage", () => {
    const req = buildLandingAnalyzeRequest({ ...free, glide: 9.04 }, { ...point, elevation: 1600, orientations: ["W"] });
    expect(req).toEqual({
      takeoff: { lat: 45.82051, lon: 6.2526, elevation_m: 1600, orientations: ["W"] },
      horizon: "15m",
      wing_glide_ratio: 9,
      difficulty: "advanced",
      landing_policy: "include_community",
    });
  });
  it("altitude et orientations omises si non saisies (déduites du relief par le serveur)", () => {
    const req = buildLandingAnalyzeRequest(free, point);
    expect(req.takeoff).toEqual({ lat: 45.82051, lon: 6.2526 });
    expect(Object.keys(JSON.parse(JSON.stringify(req.takeoff)))).toEqual(["lat", "lon"]);
  });
});

describe("critères mémorisés", () => {
  it("anciens critères (sans mode) acceptés puis complétés", () => {
    const old: Record<string, unknown> = { ...DEFAULT_CRITERIA };
    delete old.mode;
    delete old.landingPolicy;
    expect(isCriteria(old)).toBe(true);
    const c = withCriteriaDefaults(old as unknown as Criteria);
    expect(c.mode).toBe("classic");
    expect(c.landingPolicy).toBe("official_only");
    expect(isCriteria({ ...DEFAULT_CRITERIA, mode: "rando" })).toBe(false);
    expect(isCriteria({ ...DEFAULT_CRITERIA, horizon: "15m" })).toBe(true);
  });
  it("point de décollage mémorisé valide", () => {
    expect(isFreeTakeoff(null)).toBe(true);
    expect(isFreeTakeoff(point)).toBe(true);
    expect(isFreeTakeoff({ lat: "45", lon: 6 })).toBe(false);
    expect(isFreeTakeoff({ ...point, lat: Number.NaN })).toBe(false);
  });
});
