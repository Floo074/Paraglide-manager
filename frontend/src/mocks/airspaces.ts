/**
 * Espaces aériens de démonstration (géométries simplifiées et APPROXIMATIVES).
 * Ne remplacent en aucun cas une carte aéronautique à jour (SIA / OpenAIP).
 */
import type { AirspaceFeature, AirspaceFeatureCollection } from "../api/types";

function poly(
  id: string,
  name: string,
  airspace_class: string,
  type: string,
  floor_m: number,
  ceiling_m: number,
  ring: [number, number][],
): AirspaceFeature {
  const closed = [...ring, ring[0]!];
  return {
    type: "Feature",
    id,
    geometry: { type: "Polygon", coordinates: [closed] },
    properties: { name, airspace_class, type, floor_m, ceiling_m },
  };
}

export const MOCK_AIRSPACES: AirspaceFeature[] = [
  poly("ctr-annecy", "CTR Annecy (démo)", "D", "CTR", 0, 1676, [
    [6.03, 45.885], [6.17, 45.875], [6.205, 45.93], [6.19, 45.985], [6.05, 45.99], [6.015, 45.94],
  ]),
  poly("tma-annecy-1", "TMA Annecy 1 (démo)", "D", "TMA", 1676, 2591, [
    [5.96, 45.86], [6.14, 45.855], [6.245, 45.87], [6.27, 45.95], [6.24, 46.05], [5.98, 46.05],
  ]),
  poly("tma-geneve", "TMA Genève (démo)", "C", "TMA", 1981, 5944, [
    [5.95, 46.07], [6.35, 46.07], [6.45, 46.25], [6.0, 46.3],
  ]),
  poly("r-mont-blanc", "Zone réglementée Mont-Blanc (démo)", "R", "RESTRICTED", 0, 4810 + 1000, [
    [6.84, 45.82], [6.9, 45.81], [6.93, 45.86], [6.87, 45.88],
  ]),
];

export function mockAirspaceCollection(): AirspaceFeatureCollection {
  return { type: "FeatureCollection", features: MOCK_AIRSPACES };
}
