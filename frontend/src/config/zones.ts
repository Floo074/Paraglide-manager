import type { Zone } from "../api/types";

export interface PresetZone {
  id: string;
  name: string;
  region: string;
  zone: Zone;
}

/** Raccourcis vers des zones de vol connues (cercles). Les Alpes du Nord sont la priorité. */
export const PRESET_ZONES: PresetZone[] = [
  { id: "annecy", name: "Annecy", region: "Haute-Savoie", zone: { type: "circle", center: { lat: 45.81, lon: 6.2 }, radius_km: 18 } },
  { id: "chamonix", name: "Chamonix", region: "Haute-Savoie", zone: { type: "circle", center: { lat: 45.92, lon: 6.87 }, radius_km: 15 } },
  { id: "st-hilaire", name: "Saint-Hilaire", region: "Isère", zone: { type: "circle", center: { lat: 45.31, lon: 5.89 }, radius_km: 12 } },
  { id: "st-andre", name: "Saint-André-les-Alpes", region: "Alpes-de-Haute-Provence", zone: { type: "circle", center: { lat: 43.97, lon: 6.5 }, radius_km: 15 } },
  { id: "pilat", name: "Dune du Pilat", region: "Gironde", zone: { type: "circle", center: { lat: 44.59, lon: -1.21 }, radius_km: 8 } },
  { id: "puy-de-dome", name: "Puy de Dôme", region: "Auvergne", zone: { type: "circle", center: { lat: 45.77, lon: 2.97 }, radius_km: 12 } },
  { id: "millau", name: "Millau", region: "Aveyron", zone: { type: "circle", center: { lat: 44.1, lon: 3.08 }, radius_km: 12 } },
];

/** Zone par défaut : Annecy (Alpes du Nord). */
export const DEFAULT_ZONE: Zone = PRESET_ZONES[0]!.zone;

/** Rayon utilisé par le bouton "ma position". */
export const GEOLOCATION_RADIUS_KM = 30;
