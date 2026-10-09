import { describe, expect, it } from "vitest";
import type { Beacon, BeaconTrend, StationReading } from "../api/types";
import {
  beaconAgeMinutes,
  formatRotation,
  formatSpeedTrend,
  formatTrend,
  formatTrendWindow,
  hasPioupiou,
  isBeaconOutdated,
  readingsByRole,
  trendArrow,
  trendLevel,
} from "../utils/beacons";

const NBSP = " ";
const MINUS = "−";
const trend = (speed: number, dir = 0, window_min = 60): BeaconTrend => ({ window_min, speed_change_kmh: speed, direction_change_deg: dir, gust_max_kmh: 22, samples: 15 });

const beacon = (over: Partial<Beacon> = {}): Beacon => ({
  id: "pioupiou:1720",
  name: "Atterrissage de Doussard",
  lat: 45.781728,
  lon: 6.222627,
  elevation_m: 450,
  observed_at: "2026-10-08T12:00:00Z",
  wind_speed_kmh: 12,
  wind_gust_kmh: 18,
  wind_direction_deg: 340,
  temperature_c: 16,
  source: "pioupiou",
  stale: false,
  trend: trend(8, 40),
  ...over,
});

describe("tendance des balises", () => {
  it("flèche : ↗ forcit, ↘ mollit, → stable", () => {
    expect(trendArrow(trend(8))).toBe("↗");
    expect(trendArrow(trend(2))).toBe("↗");
    expect(trendArrow(trend(1))).toBe("→");
    expect(trendArrow(trend(-1.5))).toBe("→");
    expect(trendArrow(trend(-3))).toBe("↘");
  });
  it("variation du vent moyen sur la fenêtre", () => {
    expect(formatSpeedTrend(trend(8))).toBe(`+8${NBSP}km/h en 1 h`);
    expect(formatSpeedTrend(trend(-3.4))).toBe(`${MINUS}3${NBSP}km/h en 1 h`);
    expect(formatSpeedTrend(trend(0.3))).toBe("stable en 1 h");
    expect(formatSpeedTrend(trend(5, 0, 30))).toBe(`+5${NBSP}km/h en 30 min`);
    expect(formatTrendWindow(90)).toBe("1 h 30");
  });
  it("rotation signée (+ = horaire), ignorée sous 15°", () => {
    expect(formatRotation(trend(0, 40))).toBe("rotation +40° (horaire)");
    expect(formatRotation(trend(0, -35))).toBe(`rotation ${MINUS}35° (anti-horaire)`);
    expect(formatRotation(trend(0, 10))).toBeNull();
    expect(formatRotation(trend(0, 10), 5)).toBe("rotation +10° (horaire)");
  });
  it("ligne complète", () => {
    expect(formatTrend(trend(8, 40))).toBe(`↗ +8${NBSP}km/h en 1 h · rotation +40° (horaire)`);
    expect(formatTrend(trend(-4, 5))).toBe(`↘ ${MINUS}4${NBSP}km/h en 1 h`);
  });
  it("niveau d'alerte (CDC §12.2 : +6 / +10 km/h/h, rotation 45° / 90° si vent ≥ 8 km/h)", () => {
    expect(trendLevel(trend(5), 12)).toBeNull();
    expect(trendLevel(trend(6), 12)).toBe("caution");
    expect(trendLevel(trend(10), 12)).toBe("danger");
    expect(trendLevel(trend(4, 50), 12)).toBe("caution");
    expect(trendLevel(trend(4, 95), 12)).toBe("danger");
    expect(trendLevel(trend(4, 95), 5)).toBeNull(); // vent faible : la direction ne compte pas
    expect(trendLevel(trend(4, 0, 30), 12)).toBe("caution"); // +4 en 30 min = +8 km/h/h
  });
});

describe("âge des mesures", () => {
  const now = new Date("2026-10-08T12:31:00Z");
  it("minutes écoulées, jamais négatives", () => {
    expect(beaconAgeMinutes("2026-10-08T12:00:00Z", now)).toBe(31);
    expect(beaconAgeMinutes("2026-10-08T12:40:00Z", now)).toBe(0);
  });
  it("trop ancienne au-delà de 30 min ou si le serveur l'a marquée stale", () => {
    expect(isBeaconOutdated(beacon(), now)).toBe(true);
    expect(isBeaconOutdated(beacon({ observed_at: "2026-10-08T12:05:00Z" }), now)).toBe(false);
    expect(isBeaconOutdated(beacon({ observed_at: "2026-10-08T12:25:00Z", stale: true }), now)).toBe(true);
  });
});

describe("balises rattachées", () => {
  const reading = (over: Partial<StationReading>): StationReading => ({
    site_role: "landing",
    site_id: "fixture:doussard",
    beacon: beacon(),
    distance_km: 0.5,
    altitude_diff_m: -10,
    representative: true,
    weight: 0.5,
    comment: "",
    ...over,
  });
  it("groupées par rôle, représentatives d'abord puis par poids", () => {
    const by = readingsByRole([
      reading({ representative: false, weight: 0, beacon: beacon({ id: "a" }) }),
      reading({ weight: 0.3, beacon: beacon({ id: "b" }) }),
      reading({ weight: 0.6, beacon: beacon({ id: "c" }) }),
      reading({ site_role: "takeoff", site_id: "fixture:forclaz", beacon: beacon({ id: "d" }) }),
    ]);
    expect(by.landing.map((r) => r.beacon.id)).toEqual(["c", "b", "a"]);
    expect(by.takeoff.map((r) => r.beacon.id)).toEqual(["d"]);
    expect(by.alternate_landing).toEqual([]);
  });
  it("attribution Pioupiou requise dès qu'une balise Pioupiou est affichée", () => {
    expect(hasPioupiou([beacon()])).toBe(true);
    expect(hasPioupiou([beacon({ source: "ffvl" }), beacon({ source: "fixture" })])).toBe(false);
  });
});
