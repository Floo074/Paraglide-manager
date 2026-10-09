import { describe, expect, it } from "vitest";
import {
  HORIZONS,
  forecastStepMinutes,
  horizonToMinutes,
  isHorizon,
  isNowcastHorizon,
  isOnSiteHorizon,
  nearestHorizon,
  targetTimeFromHorizon,
} from "../utils/horizon";

describe("horizon", () => {
  it("liste et minutes (« 15 min » en premier)", () => {
    expect(HORIZONS.map((h) => h.value)).toEqual(["15m", "30m", "1h", "2h", "8h", "12h", "24h", "48h"]);
    expect(HORIZONS[0]!.label).toBe("15 min");
    expect(horizonToMinutes("15m")).toBe(15);
    expect(horizonToMinutes("30m")).toBe(30);
    expect(horizonToMinutes("48h")).toBe(2880);
    expect(isHorizon("15m")).toBe(true);
    expect(isHorizon("2h")).toBe(true);
    expect(isHorizon("3h")).toBe(false);
  });
  it("heure cible arrondie à l'heure la plus proche", () => {
    const ref = new Date("2026-10-08T12:10:00Z");
    expect(targetTimeFromHorizon(ref, "30m").toISOString()).toBe("2026-10-08T13:00:00.000Z"); // 12:40 → 13:00
    expect(targetTimeFromHorizon(ref, "2h").toISOString()).toBe("2026-10-08T14:00:00.000Z"); // 14:10 → 14:00
    expect(targetTimeFromHorizon(ref, "24h").toISOString()).toBe("2026-10-09T12:00:00.000Z");
  });
  it("« 15 min » : arrondi au quart d'heure, jamais avant l'heure de référence", () => {
    expect(forecastStepMinutes("15m")).toBe(15);
    expect(forecastStepMinutes("1h")).toBe(60);
    expect(targetTimeFromHorizon(new Date("2026-10-08T12:10:00Z"), "15m").toISOString()).toBe("2026-10-08T12:30:00.000Z"); // 12:25 → 12:30
    expect(targetTimeFromHorizon(new Date("2026-10-08T12:01:00Z"), "15m").toISOString()).toBe("2026-10-08T12:15:00.000Z"); // 12:16 → 12:15
    for (let m = 0; m < 60; m++) {
      const ref = new Date(Date.UTC(2026, 9, 8, 12, m));
      expect(targetTimeFromHorizon(ref, "15m").getTime()).toBeGreaterThan(ref.getTime());
    }
  });
  it("sans arrondi", () => {
    const ref = new Date("2026-10-08T12:10:00Z");
    expect(targetTimeFromHorizon(ref, "1h", 0).toISOString()).toBe("2026-10-08T13:10:00.000Z");
  });
  it("nowcasting jusqu'à 2 h, mode « au déco » jusqu'à 1 h", () => {
    expect(isNowcastHorizon("2h")).toBe(true);
    expect(isNowcastHorizon("8h")).toBe(false);
    expect(isOnSiteHorizon("15m")).toBe(true);
    expect(isOnSiteHorizon("1h")).toBe(true);
    expect(isOnSiteHorizon("2h")).toBe(false);
  });
  it("horizon le plus proche", () => {
    expect(nearestHorizon(-20)).toBe("15m");
    expect(nearestHorizon(20)).toBe("15m");
    expect(nearestHorizon(50)).toBe("1h");
    expect(nearestHorizon(600)).toBe("8h");
  });
});
