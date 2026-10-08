import type { Difficulty, FlightType, Flyability, RiskLevel, ThermalPreference, FlightPlan } from "../api/types";

export interface DifficultyInfo {
  value: Difficulty;
  label: string;
  short: string;
  description: string;
}

export const DIFFICULTIES: DifficultyInfo[] = [
  {
    value: "beginner",
    label: "Débutant",
    short: "Élève / brevet initial",
    description: "Vent faible et laminaire, grands atterrissages, sites école. Pas de thermique fort.",
  },
  {
    value: "intermediate",
    label: "Intermédiaire",
    short: "Brevet de pilote",
    description: "Vol thermique local en conditions modérées, soaring simple, atterrissages connus.",
  },
  {
    value: "advanced",
    label: "Avancé",
    short: "Brevet de pilote confirmé",
    description: "Thermiques soutenus, vent plus marqué, premiers cross et transitions engagées.",
  },
  {
    value: "expert",
    label: "Expert",
    short: "Compétiteur / cross aguerri",
    description: "Conditions fortes, longues distances, gestion autonome des espaces aériens et des risques.",
  },
];

export const DIFFICULTY_ORDER: Difficulty[] = ["beginner", "intermediate", "advanced", "expert"];

export function difficultyLabel(d: Difficulty | null): string {
  if (!d) return "Non précisé";
  return DIFFICULTIES.find((x) => x.value === d)?.label ?? d;
}

export const FLIGHT_TYPES: { value: FlightType; label: string; description: string }[] = [
  { value: "local", label: "Local", description: "Vol autour du site, retour à l'atterrissage officiel." },
  { value: "ridge_soaring", label: "Soaring", description: "Vol de pente dans le vent dynamique, le long du relief." },
  { value: "cross_country", label: "Cross", description: "Vol de distance (triangle ou aller-retour) en thermique." },
];

export function flightTypeLabel(t: FlightType): string {
  return FLIGHT_TYPES.find((x) => x.value === t)?.label ?? t;
}

export const THERMAL_PREFS: { value: ThermalPreference; label: string; description: string }[] = [
  { value: "required", label: "Exploiter", description: "Je cherche à enrouler et à monter." },
  { value: "allowed", label: "Indifférent", description: "Thermiques acceptés s'ils sont présents." },
  { value: "avoid", label: "Éviter", description: "Air calme recherché (plouf, vol du soir, débutant)." },
];

export const THERMAL_USAGE_LABEL: Record<FlightPlan["thermal_usage"], string> = {
  none: "sans thermique",
  optional: "thermiques en option",
  essential: "thermiques indispensables",
};

export const FLYABILITY: Record<Flyability, { label: string; className: string }> = {
  go: { label: "Volable", className: "badge--go" },
  marginal: { label: "Limite", className: "badge--marginal" },
  no_go: { label: "Non volable", className: "badge--nogo" },
};

export const RISK_LEVEL: Record<RiskLevel, { label: string; className: string }> = {
  info: { label: "Info", className: "risk--info" },
  caution: { label: "Prudence", className: "risk--caution" },
  danger: { label: "Danger", className: "risk--danger" },
};

export const SITE_KIND_LABEL = { takeoff: "Décollage", landing: "Atterrissage", both: "Déco / atterro" } as const;

export const SITE_STATUS_LABEL = {
  open: "Ouvert",
  restricted: "Restrictions",
  closed: "Fermé",
  unknown: "Statut inconnu",
} as const;

export const SOURCE_LABEL: Record<string, string> = {
  ffvl: "FFVL",
  paraglidingearth: "ParaglidingEarth",
  spotair: "SpotAir",
  fixture: "Données locales",
  pioupiou: "Pioupiou / OpenWindMap",
};
