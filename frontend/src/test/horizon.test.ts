import { describe, expect, it } from "vitest";
import { HORIZONS, horizonToMinutes, isHorizon, isNowcastHorizon, targetTimeFromHorizon } from "../utils/horizon";

describe("horizon", () => {
  it("liste et minutes", () => {
    expect(HORIZONS.map((h) => h.value)).toEqual(["30m", "1h", "2h", "8h", "12h", "24h", "48h"]);
    expect(horizonToMinutes("30m")).toBe(30);
    expect(horizonToMinutes("48h")).toBe(2880);
    expect(isHorizon("2h")).toBe(true);
    expect(isHorizon("3h")).toBe(false);
  });
  it("heure cible arrondie à l'heure la plus proche", () => {
    const ref = new Date("2026-10-08T12:10:00Z");
    expect(targetTimeFromHorizon(ref, "30m").toISOString()).toBe("2026-10-08T13:00:00.000Z"); // 12:40 → 13:00
    expect(targetTimeFromHorizon(ref, "2h").toISOString()).toBe("2026-10-08T14:00:00.000Z"); // 14:10 → 14:00
    expect(targetTimeFromHorizon(ref, "24h").toISOString()).toBe("2026-10-09T12:00:00.000Z");
  });
  it("sans arrondi", () => {
    const ref = new Date("2026-10-08T12:10:00Z");
    expect(targetTimeFromHorizon(ref, "1h", 0).toISOString()).toBe("2026-10-08T13:10:00.000Z");
  });
  it("nowcasting jusqu'à 2 h", () => {
    expect(isNowcastHorizon("2h")).toBe(true);
    expect(isNowcastHorizon("8h")).toBe(false);
  });
});
