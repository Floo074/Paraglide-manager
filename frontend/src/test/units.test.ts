import { describe, expect, it } from "vitest";
import { angleDiff, compassFr, compassToDeg, degToCardinalFr, degToCompass, groundGlideRatio, kmhToKt, kmhToMs, msToKmh, normalizeDeg, standardPressureHpa } from "../utils/units";

describe("units", () => {
  it("normalise les angles", () => {
    expect(normalizeDeg(-90)).toBe(270);
    expect(normalizeDeg(725)).toBe(5);
  });
  it("écart angulaire minimal", () => {
    expect(angleDiff(350, 10)).toBe(20);
    expect(angleDiff(90, 270)).toBe(180);
    expect(angleDiff(0, 0)).toBe(0);
  });
  it("degrés ↔ rose 16 points", () => {
    expect(degToCompass(0)).toBe("N");
    expect(degToCompass(292.5)).toBe("WNW");
    expect(degToCompass(349)).toBe("N");
    expect(degToCardinalFr(270)).toBe("O");
    expect(degToCardinalFr(315)).toBe("NO");
    expect(compassToDeg("SW")).toBe(225);
    expect(compassToDeg("wnw")).toBe(292.5);
    expect(compassToDeg("X")).toBeNull();
    expect(compassFr("WSW")).toBe("OSO");
  });
  it("conversions de vitesse", () => {
    expect(kmhToMs(36)).toBeCloseTo(10);
    expect(msToKmh(2)).toBeCloseTo(7.2);
    expect(kmhToKt(18.52)).toBeCloseTo(10);
  });
  it("pression standard", () => {
    expect(standardPressureHpa(0)).toBeCloseTo(1013.25, 1);
    expect(standardPressureHpa(1500)).toBeCloseTo(845.6, 0);
  });
  it("finesse sol avec vent de face (exemple du cahier des charges)", () => {
    // 5,1 × (37 − 15) / 37 ≈ 3,0
    expect(groundGlideRatio(5.1, 15, 37)).toBeCloseTo(3.03, 1);
    expect(groundGlideRatio(8.5, 40)).toBe(0);
  });
});

import { niceTicks } from "../utils/ticks";
describe("graduations", () => {
  it("pas ronds", () => {
    expect(niceTicks(0, 25)).toEqual([0, 10, 20, 30]);
    expect(niceTicks(0, 2.2, 3)).toEqual([0, 1, 2, 3]);
    expect(niceTicks(1050, 2550)).toEqual([1000, 1500, 2000, 2500, 3000]);
  });
});
