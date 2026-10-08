import { describe, expect, it } from "vitest";
import { formatAge, formatAltitude, formatDayTime, formatDuration, formatDurationRange, formatKm, formatTime } from "../utils/format";

const TZ = "Europe/Paris";

describe("format", () => {
  it("durées", () => {
    expect(formatDuration(20)).toBe("20 min");
    expect(formatDuration(60)).toBe("1 h");
    expect(formatDuration(75)).toBe("1 h 15");
    expect(formatDuration(125)).toBe("2 h 05");
    expect(formatDurationRange(15, 120)).toBe("15 min – 2 h");
  });
  it("altitudes et distances au format français", () => {
    expect(formatAltitude(1250)).toBe("1 250 m");
    expect(formatAltitude(null)).toBe("—");
    expect(formatKm(6.24)).toBe("6,2 km");
    expect(formatKm(36.4)).toBe("36 km");
  });
  it("heure légale Europe/Paris (UTC+2 en été)", () => {
    expect(formatTime("2026-10-08T12:00:00Z", TZ)).toBe("14:00");
    expect(formatTime("2026-12-08T12:00:00Z", TZ)).toBe("13:00");
  });
  it("jour relatif", () => {
    const now = new Date("2026-10-08T08:00:00Z");
    expect(formatDayTime("2026-10-08T12:00:00Z", now, TZ)).toBe("aujourd'hui 14:00");
    expect(formatDayTime("2026-10-09T07:00:00Z", now, TZ)).toBe("demain 09:00");
    expect(formatDayTime("2026-10-10T12:00:00Z", now, TZ)).toMatch(/^sam\. 10 oct\. 14:00$/);
  });
  it("âge d'une mesure", () => {
    const now = new Date("2026-10-08T12:00:00Z");
    expect(formatAge("2026-10-08T12:00:20Z", now)).toBe("à l'instant");
    expect(formatAge("2026-10-08T11:55:00Z", now)).toBe("il y a 5 min");
    expect(formatAge("2026-10-08T09:50:00Z", now)).toBe("il y a 2 h 10");
    expect(formatAge("2026-10-05T12:00:00Z", now)).toBe("il y a 3 j");
  });
});
