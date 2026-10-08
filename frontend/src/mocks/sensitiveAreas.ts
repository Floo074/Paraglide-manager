/**
 * Zones sensibles de démonstration (façon Biodiv'Sports + cœurs de parcs nationaux).
 * Géométries et périodes APPROXIMATIVES — consulter biodiv-sports.fr et les fiches de site.
 */
import type { SensitiveAreaFeature, SensitiveAreaFeatureCollection, SensitiveAreaProperties } from "../api/types";

const ALL_YEAR = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];

type Def = Omit<SensitiveAreaProperties, "active_now" | "source"> & { ring: [number, number][] };

const DEFS: Def[] = [
  {
    id: "fixture:sa-bout-du-lac",
    name: "Réserve naturelle du Bout du Lac",
    species: null,
    kind: "regulatory",
    period_months: ALL_YEAR,
    recommendation: "Réserve naturelle : survol à moins de 300 m/sol interdit, pas d'atterrissage.",
    min_height_agl_m: 300,
    url: null,
    ring: [[6.2225, 45.7905], [6.236, 45.7915], [6.2385, 45.8005], [6.226, 45.802]],
  },
  {
    id: "fixture:sa-roc-de-chere",
    name: "Falaises du Roc de Chère",
    species: "Faucon pèlerin",
    kind: "species",
    period_months: [2, 3, 4, 5, 6, 7],
    recommendation: "Nidification : rester à plus de 300 m des falaises de février à juillet.",
    min_height_agl_m: 300,
    url: null,
    ring: [[6.196, 45.868], [6.214, 45.868], [6.216, 45.882], [6.198, 45.884]],
  },
  {
    id: "fixture:sa-lanfon",
    name: "Dents de Lanfon — versant nord",
    species: "Aigle royal",
    kind: "species",
    period_months: [12, 1, 2, 3, 4, 5, 6, 7],
    recommendation: "Zone de quiétude : éviter le survol à moins de 500 m/sol de décembre à juillet.",
    min_height_agl_m: 500,
    url: null,
    ring: [[6.222, 45.884], [6.242, 45.883], [6.244, 45.896], [6.224, 45.897]],
  },
  {
    id: "fixture:sa-tournette",
    name: "La Tournette — combes est",
    species: "Tétras-lyre",
    kind: "species",
    period_months: [10, 11, 12, 1, 2, 3, 4, 5, 6],
    recommendation: "Hivernage et reproduction : ne pas survoler les combes à moins de 300 m/sol.",
    min_height_agl_m: 300,
    url: null,
    ring: [[6.288, 45.818], [6.31, 45.82], [6.312, 45.838], [6.29, 45.84]],
  },
  {
    id: "fixture:sa-vanoise",
    name: "Cœur du Parc national de la Vanoise",
    species: null,
    kind: "national_park_core",
    period_months: ALL_YEAR,
    recommendation: "Cœur de parc : décollage et atterrissage interdits, survol à moins de 1000 m/sol interdit.",
    min_height_agl_m: 1000,
    url: "https://www.vanoise-parcnational.fr",
    ring: [[6.62, 45.33], [6.86, 45.27], [7.05, 45.36], [7.0, 45.5], [6.78, 45.52], [6.65, 45.44]],
  },
  {
    id: "fixture:sa-mercantour",
    name: "Cœur du Parc national du Mercantour",
    species: null,
    kind: "national_park_core",
    period_months: ALL_YEAR,
    recommendation: "Cœur de parc : décollage et atterrissage interdits, survol à moins de 1000 m/sol interdit.",
    min_height_agl_m: 1000,
    url: "https://www.mercantour-parcnational.fr",
    ring: [[6.75, 44.33], [7.0, 44.2], [7.35, 44.1], [7.5, 44.15], [7.2, 44.3], [6.9, 44.42]],
  },
];

export function isActiveInMonth(periodMonths: number[], month1to12: number): boolean {
  return periodMonths.length === 0 || periodMonths.includes(month1to12);
}

export function mockSensitiveAreas(at: Date = new Date()): SensitiveAreaFeature[] {
  const month = at.getUTCMonth() + 1;
  return DEFS.map(({ ring, ...p }) => ({
    type: "Feature",
    id: p.id,
    geometry: { type: "Polygon", coordinates: [[...ring, ring[0]!]] },
    properties: { ...p, source: "fixture", active_now: isActiveInMonth(p.period_months, month) },
  }));
}

export function mockSensitiveAreaCollection(at?: Date): SensitiveAreaFeatureCollection {
  return { type: "FeatureCollection", features: mockSensitiveAreas(at) };
}
