import { it } from "vitest";
import { computeGlide } from "../mocks/glideWind";
const forclaz = { lat: 45.815, lon: 6.2465, alt: 1245 };
const doussard = { lat: 45.782, lon: 6.2224, elevation_m: 452 };
it("probe", () => {
  const s33 = computeGlide({ from: forclaz, to: doussard, takeoffAlt: 1245, startIsTakeoff: true,
    takeoffWind: { speed: 13, dir: 345, gust: 18 }, landingWind: { speed: 13, dir: 0, gust: 18 },
    aloft: [{ altitude_m: 1550, pressure_hpa: 840, speed_kmh: 15, direction_deg: 350 }], level: "intermediate", wing: 8.5, k: 0.8, arrivalMarginM: 100, horizon: "12h", arrivalLegalHour: 14.25 });
  console.log("S33", JSON.stringify(s33));
  const s38 = computeGlide({ from: forclaz, to: doussard, takeoffAlt: 1245, startIsTakeoff: true,
    takeoffWind: { speed: 9, dir: 280, gust: 13 }, landingWind: { speed: 21, dir: 190, gust: 29 },
    aloft: [{ altitude_m: 1550, pressure_hpa: 840, speed_kmh: 16, direction_deg: 190 }], level: "advanced", wing: 8.5, k: 0.8, arrivalMarginM: 100, horizon: "12h", arrivalLegalHour: 14.75 });
  console.log("S38", JSON.stringify(s38));
  const calm = computeGlide({ from: forclaz, to: doussard, takeoffAlt: 1245, startIsTakeoff: true,
    takeoffWind: { speed: 0, dir: 0 }, landingWind: { speed: 0, dir: 0 },
    aloft: [], level: "beginner", wing: 8.5, k: 0.8, arrivalMarginM: 100, horizon: "12h", arrivalLegalHour: 14.75 });
  console.log("CALM", JSON.stringify(calm));
});
