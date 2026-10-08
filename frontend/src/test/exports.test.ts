import { describe, expect, it } from "vitest";
import { buildGpx, buildXctsk, escapeXml, safeFilename } from "../utils/exports";
import { mockPlans } from "../mocks/planner";
import { setMockNow } from "../mocks/weather";

const now = new Date("2026-10-08T09:00:00Z");
setMockNow(now);

function aPlan() {
  const res = mockPlans(
    {
      zone: { type: "circle", center: { lat: 45.81, lon: 6.2 }, radius_km: 18 },
      horizon: "2h",
      reference_time: now.toISOString(),
      filters: { duration_min_minutes: 30, duration_max_minutes: 240, difficulty: "advanced", thermals: "allowed" },
    },
    now,
  );
  expect(res.plans.length).toBeGreaterThan(0);
  return res.plans[0]!;
}

describe("exports", () => {
  it("échappe le XML", () => {
    expect(escapeXml(`a<b & "c"`)).toBe("a&lt;b &amp; &quot;c&quot;");
  });
  it("GPX 1.1 : métadonnées, waypoints, route", () => {
    const plan = aPlan();
    const gpx = buildGpx(plan, now);
    expect(gpx.startsWith('<?xml version="1.0" encoding="UTF-8"?>')).toBe(true);
    expect(gpx).toContain('<gpx version="1.1"');
    expect(gpx).toContain("<metadata>");
    expect((gpx.match(/<wpt /g) ?? []).length).toBe(plan.waypoints.length);
    expect(gpx).toContain("<rte>");
    expect(gpx).toContain("<trkseg>");
  });
  it("tâche XCTrack : TAKEOFF en premier, atterro en dernier (but)", () => {
    const plan = aPlan();
    const task = buildXctsk(plan);
    expect(task.version).toBe(1);
    expect(task.taskType).toBe("CLASSIC");
    expect(task.turnpoints[0]!.type).toBe("TAKEOFF");
    expect(task.turnpoints.at(-1)!.waypoint.name).toBe(plan.landing.name.slice(0, 40));
    expect(task.turnpoints.at(-1)!.type).toBe("ESS");
    expect(task.goal.type).toBe("CYLINDER");
  });
  it("nom de fichier sûr", () => {
    expect(safeFilename("Col de la Forclaz → Doussard · local 1h30", "gpx")).toBe("col-de-la-forclaz-doussard-local-1h30.gpx");
  });
});
