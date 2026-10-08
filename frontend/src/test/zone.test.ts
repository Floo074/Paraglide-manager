import { describe, expect, it } from "vitest";
import type { Zone } from "../api/types";
import { bboxFromCorners, bboxParam, describeZone, parseZone, serializeZone, validateZone, zoneContains, zoneToBBox } from "../utils/zone";

describe("sérialisation de zone", () => {
  it("cercle aller-retour", () => {
    const z: Zone = { type: "circle", center: { lat: 45.81234567, lon: 6.2 }, radius_km: 18 };
    const s = serializeZone(z);
    expect(s).toBe("c:45.8123,6.2,18");
    expect(parseZone(s)).toEqual({ type: "circle", center: { lat: 45.8123, lon: 6.2 }, radius_km: 18 });
  });
  it("rectangle aller-retour et normalisation des coins", () => {
    const z = bboxFromCorners({ lat: 45.95, lon: 6.4 }, { lat: 45.7, lon: 6.1 });
    expect(z).toEqual({ type: "bbox", min_lat: 45.7, min_lon: 6.1, max_lat: 45.95, max_lon: 6.4 });
    expect(serializeZone(z)).toBe("b:45.7,6.1,45.95,6.4");
    expect(parseZone("b:45.95,6.4,45.7,6.1")).toEqual(z);
  });
  it("rejette les chaînes invalides", () => {
    for (const bad of [null, "", "x:1,2,3", "c:1,2", "c:a,b,c", "c:95,6,10", "c:45,6,-3", "b:1,2,3"]) {
      expect(parseZone(bad)).toBeNull();
    }
  });
  it("validation (limites du contrat)", () => {
    expect(validateZone({ type: "circle", center: { lat: 45, lon: 6 }, radius_km: 150 })).toBeNull();
    expect(validateZone({ type: "circle", center: { lat: 45, lon: 6 }, radius_km: 151 })).toMatch(/Rayon/);
    expect(validateZone(bboxFromCorners({ lat: 44, lon: 5 }, { lat: 47.5, lon: 6 }))).toMatch(/Rectangle/);
  });
  it("bbox d'un cercle, paramètre d'API, appartenance", () => {
    const z: Zone = { type: "circle", center: { lat: 45.8, lon: 6.2 }, radius_km: 10 };
    const b = zoneToBBox(z);
    expect(b.max_lat - b.min_lat).toBeCloseTo(0.181, 2);
    expect(bboxParam({ type: "bbox", min_lat: 45.7, min_lon: 6.1, max_lat: 45.9, max_lon: 6.3 })).toBe("6.1,45.7,6.3,45.9");
    expect(zoneContains(z, { lat: 45.81, lon: 6.21 })).toBe(true);
    expect(zoneContains(z, { lat: 46, lon: 6.2 })).toBe(false);
    expect(describeZone(z)).toBe("cercle de 10 km");
  });
});
