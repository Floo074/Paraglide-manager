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
    label: "Élève / brevet initial",
    short: "Débutant",
    description: "Vent faible et laminaire, grands atterrissages, sites école. Pas de thermique fort ni de cross.",
  },
  {
    value: "intermediate",
    label: "Brevet de pilote",
    short: "Intermédiaire",
    description: "Vol thermique local en conditions modérées, soaring simple, petit cross avec retour à un atterro connu.",
  },
  {
    value: "advanced",
    label: "Brevet de pilote confirmé",
    short: "Avancé",
    description: "Thermiques soutenus, vent plus marqué, cross et transitions engagées.",
  },
  {
    value: "expert",
    label: "Cross / compétition",
    short: "Expert",
    description: "Conditions fortes, longues distances, gestion autonome des espaces aériens et des risques.",
  },
];

export const DIFFICULTY_ORDER: Difficulty[] = ["beginner", "intermediate", "advanced", "expert"];

/** Libellé principal (brevet FFVL). */
export function difficultyLabel(d: Difficulty | null): string {
  if (!d) return "Non précisé";
  return DIFFICULTIES.find((x) => x.value === d)?.label ?? d;
}

/** Libellé court secondaire (Débutant / Intermédiaire / Avancé / Expert). */
export function difficultyShort(d: Difficulty | null): string {
  if (!d) return "—";
  return DIFFICULTIES.find((x) => x.value === d)?.short ?? d;
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
  go: { label: "GO", className: "badge--go" },
  marginal: { label: "LIMITE", className: "badge--marginal" },
  no_go: { label: "NO-GO", className: "badge--nogo" },
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

/** Libellés français des critères de score (ScoreItem.criterion = identifiants CDC §9.2). */
export const CRITERION_LABEL: Record<string, string> = {
  takeoff_wind: "Vent au déco",
  wind_aloft: "Vent en altitude",
  landing: "Atterrissage",
  thermal_match: "Thermiques / préférence",
  duration_match: "Durée",
  convective_stability: "Stabilité / orages",
  data_confidence: "Confiance des données",
  site_fit: "Adéquation du site",
  airspace: "Espaces aériens",
};

export function criterionLabel(c: string): string {
  return CRITERION_LABEL[c] ?? c;
}

/** Libellés des codes de risque (catalogue backend / expert). */
export const RISK_CODE_LABEL: Record<string, string> = {
  RAIN: "Pluie",
  THUNDERSTORM: "Orage",
  OVERDEVELOPMENT: "Surdéveloppement",
  FOEHN: "Foehn",
  REGIONAL_WIND: "Vent régional",
  LOW_CLOUD_BASE: "Base basse",
  STRONG_WIND_ALOFT: "Vent en altitude",
  LEE_SIDE: "Dévent",
  TAKEOFF_WIND: "Vent déco",
  TAKEOFF_GUSTS: "Rafales",
  CROSSWIND: "Vent de travers",
  TAILWIND: "Vent arrière",
  LANDING_WIND: "Vent atterro",
  VALLEY_BREEZE: "Brise",
  GLIDE_MARGIN: "Finesse",
  SUNSET: "Coucher du soleil",
  AIRSPACE: "Espace aérien",
  AIRSPACE_ACTIVATION: "Activation",
  ALTITUDE_LIMIT: "Altitude max",
  SENSITIVE_AREA: "Zone sensible",
  NATIONAL_PARK: "Parc national",
  SITE_CLOSED: "Site fermé",
  SITE_RESTRICTED: "Consignes site",
  SITE_LEVEL: "Niveau du site",
  WIND_GRADIENT: "Gradient",
  WIND_SHEAR: "Cisaillement",
  STRONG_THERMALS: "Thermiques forts",
  WEAK_THERMALS: "Thermiques faibles",
  INVERSION: "Inversion",
  VENTURI: "Venturi",
  ROTOR: "Rotor",
  FRONT: "Front",
  FREEZING: "Froid",
  WIND_INCREASING: "Vent qui forcit",
  BEACON_MISMATCH: "Balises / modèle",
  STALE_BEACONS: "Balises",
  LOW_CONFIDENCE: "Confiance faible",
  MOCK_DATA: "Démo",
  ACCESS_TIME: "Accès",
};
