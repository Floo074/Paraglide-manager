import type { GridLayer } from "../../api/types";
import { WIND_GRID_ALTITUDES } from "../../api/types";
import { CAPE_STOPS, HEIGHT_STOPS, PRECIP_STOPS, THERMAL_STOPS, WIND_STOPS, type ColorStop } from "../../utils/colors";
import { formatNumber } from "../../utils/format";

export type WeatherLayerChoice = GridLayer | "none";

export const WEATHER_LAYERS: { value: WeatherLayerChoice; label: string; unit: string; stops: ColorStop[] | null; hint: string }[] = [
  { value: "none", label: "Aucune", unit: "", stops: null, hint: "" },
  { value: "wind", label: "Vent", unit: "km/h", stops: WIND_STOPS, hint: "Flèche = sens du vent (vers où il souffle)" },
  { value: "ceiling", label: "Plafond thermique", unit: "m", stops: HEIGHT_STOPS, hint: "Plafond AMSL" },
  { value: "cloudbase", label: "Base des nuages", unit: "m", stops: HEIGHT_STOPS, hint: "Base des cumulus AMSL (vide = thermiques bleus)" },
  { value: "thermal", label: "Vario (thermiques)", unit: "m/s", stops: THERMAL_STOPS, hint: "Vario moyen estimé" },
  { value: "cape", label: "CAPE (orages)", unit: "J/kg", stops: CAPE_STOPS, hint: "Énergie convective : > 800 J/kg = risque orageux" },
  { value: "precipitation", label: "Pluie", unit: "mm/h", stops: PRECIP_STOPS, hint: "Précipitations" },
];

/** Altitudes du sélecteur, niveaux de vol prioritaires d'abord (CDC §8.3). */
export const WIND_ALTITUDE_OPTIONS: { value: number; label: string }[] = [
  { value: 10, label: "Sol (modèle, 10 m)" },
  { value: 1500, label: "1 500 m" },
  { value: 2000, label: "2 000 m" },
  { value: 3000, label: "3 000 m" },
  ...WIND_GRID_ALTITUDES.filter((a) => ![10, 1500, 2000, 3000].includes(a)).map((a) => ({ value: a, label: `${formatNumber(a)} m` })),
];

