/**
 * Sites de démonstration (fixtures). Coordonnées et altitudes approximatives, consignes
 * simplifiées : NE PAS utiliser pour voler — se référer aux fiches FFVL officielles.
 */
import type { Site } from "../api/types";

type SiteInput = Pick<Site, "id" | "name" | "kind" | "lat" | "lon" | "elevation_m"> & Partial<Site>;

function site(s: SiteInput): Site {
  return {
    orientations: [],
    difficulty: null,
    flight_types: [],
    description: null,
    access: null,
    restrictions: null,
    status: "open",
    source: "fixture",
    url: null,
    associated_landing_ids: [],
    ...s,
  };
}

export const MOCK_SITES: Site[] = [
  // ───────── Annecy ─────────
  site({
    id: "fixture:forclaz",
    name: "Col de la Forclaz",
    kind: "takeoff",
    lat: 45.8139,
    lon: 6.2462,
    elevation_m: 1250,
    orientations: ["WSW", "W", "WNW", "NW"],
    difficulty: "beginner",
    flight_types: ["local", "cross_country"],
    description: "Déco emblématique dominant le lac d'Annecy, très fréquenté (écoles, biplaces). Thermiques réguliers sur les pentes de la Forclaz et des Dents de Lanfon.",
    access: "Route du col depuis Talloires ou Doussard, parking au col (navette en saison).",
    restrictions: "Forte fréquentation : règles de l'air, priorité aux biplaces au décollage. Respecter le circuit d'approche de Doussard.",
    associated_landing_ids: ["fixture:doussard"],
  }),
  site({
    id: "fixture:doussard",
    name: "Doussard",
    kind: "landing",
    lat: 45.7861,
    lon: 6.2189,
    elevation_m: 460,
    difficulty: "beginner",
    description: "Grand atterrissage officiel au bout du lac, manche à air. Brise de lac de secteur N à NO l'après-midi.",
    restrictions: "Approche en U, ne pas survoler le camping ni la réserve naturelle du Bout du Lac.",
  }),
  site({
    id: "fixture:planfait",
    name: "Planfait",
    kind: "takeoff",
    lat: 45.8466,
    lon: 6.2357,
    elevation_m: 1180,
    orientations: ["W", "WNW", "NW"],
    difficulty: "intermediate",
    flight_types: ["local", "ridge_soaring"],
    description: "Déco au-dessus de Talloires, face au lac. Soaring possible par brise de lac établie.",
    access: "Piste depuis Talloires (4×4 ou à pied, 45 min).",
    associated_landing_ids: ["fixture:talloires", "fixture:doussard"],
  }),
  site({
    id: "fixture:talloires",
    name: "Talloires",
    kind: "landing",
    lat: 45.8402,
    lon: 6.2165,
    elevation_m: 450,
    description: "Atterrissage en bord de lac, de taille moyenne : arriver haut.",
  }),
  site({
    id: "fixture:montmin",
    name: "Montmin (déco Est)",
    kind: "takeoff",
    lat: 45.8118,
    lon: 6.2531,
    elevation_m: 1260,
    orientations: ["E", "ESE", "SE"],
    difficulty: "intermediate",
    flight_types: ["local"],
    description: "Déco du versant Montmin, utile le matin ou par léger flux d'est.",
    associated_landing_ids: ["fixture:montmin-atterro"],
  }),
  site({
    id: "fixture:montmin-atterro",
    name: "Montmin village",
    kind: "landing",
    lat: 45.8012,
    lon: 6.2702,
    elevation_m: 1030,
    description: "Prairie en altitude, aérologie parfois turbulente en milieu de journée.",
  }),
  site({
    id: "fixture:semnoz-est",
    name: "Semnoz (déco Est)",
    kind: "takeoff",
    lat: 45.8,
    lon: 6.105,
    elevation_m: 1600,
    orientations: ["NE", "ENE", "E"],
    difficulty: "intermediate",
    flight_types: ["local", "cross_country"],
    description: "Grand déco herbeux face au lac, transition vers la rive est possible par bonnes conditions.",
    access: "Route du Semnoz depuis Annecy ou Leschaux.",
    associated_landing_ids: ["fixture:st-jorioz"],
  }),
  site({
    id: "fixture:st-jorioz",
    name: "Saint-Jorioz",
    kind: "landing",
    lat: 45.83,
    lon: 6.163,
    elevation_m: 455,
  }),
  site({
    id: "fixture:semnoz-ouest",
    name: "Semnoz (déco Ouest)",
    kind: "takeoff",
    lat: 45.7905,
    lon: 6.0905,
    elevation_m: 1620,
    orientations: ["WSW", "W", "WNW"],
    difficulty: "advanced",
    flight_types: ["local", "cross_country"],
    description: "Versant ouest, plus exposé au vent météo. Réservé aux pilotes autonomes.",
    associated_landing_ids: ["fixture:gruffy"],
  }),
  site({
    id: "fixture:gruffy",
    name: "Gruffy",
    kind: "landing",
    lat: 45.787,
    lon: 6.056,
    elevation_m: 600,
  }),
  site({
    id: "fixture:veyrier",
    name: "Mont Veyrier",
    kind: "takeoff",
    lat: 45.907,
    lon: 6.186,
    elevation_m: 1200,
    orientations: ["SW", "WSW"],
    difficulty: "advanced",
    flight_types: ["local"],
    status: "closed",
    description: "Site fictif de démonstration (statut fermé) — illustre le filtrage des sites.",
    restrictions: "Fermé (données de démonstration). Proximité de la CTR d'Annecy.",
  }),

  // ───────── Chamonix ─────────
  site({
    id: "fixture:planpraz",
    name: "Planpraz (Brévent)",
    kind: "takeoff",
    lat: 45.93,
    lon: 6.8524,
    elevation_m: 2000,
    orientations: ["SSE", "S", "SSW"],
    difficulty: "intermediate",
    flight_types: ["local", "cross_country"],
    description: "Déco face au massif du Mont-Blanc, accès par la télécabine du Brévent.",
    restrictions: "Réglementation estivale spécifique dans le massif du Mont-Blanc : se renseigner avant de voler.",
    associated_landing_ids: ["fixture:bois-du-bouchet"],
  }),
  site({
    id: "fixture:plan-aiguille",
    name: "Plan de l'Aiguille",
    kind: "takeoff",
    lat: 45.905,
    lon: 6.892,
    elevation_m: 2310,
    orientations: ["W", "WNW", "NW"],
    difficulty: "advanced",
    flight_types: ["local", "cross_country"],
    description: "Déco haute montagne, aérologie engagée, glacier à proximité.",
    associated_landing_ids: ["fixture:bois-du-bouchet"],
  }),
  site({
    id: "fixture:bois-du-bouchet",
    name: "Le Bois du Bouchet",
    kind: "landing",
    lat: 45.9318,
    lon: 6.8783,
    elevation_m: 1040,
  }),

  // ───────── Saint-Hilaire ─────────
  site({
    id: "fixture:st-hilaire-sud",
    name: "Saint-Hilaire (déco Sud)",
    kind: "takeoff",
    lat: 45.3047,
    lon: 5.8873,
    elevation_m: 985,
    orientations: ["ESE", "SE", "SSE", "S"],
    difficulty: "beginner",
    flight_types: ["local", "ridge_soaring", "cross_country"],
    description: "Plateau des Petites Roches, grand classique du Grésivaudan.",
    associated_landing_ids: ["fixture:lumbin"],
  }),
  site({
    id: "fixture:st-hilaire-nord",
    name: "Saint-Hilaire (déco Nord)",
    kind: "takeoff",
    lat: 45.311,
    lon: 5.8905,
    elevation_m: 1000,
    orientations: ["NE", "ENE", "E"],
    difficulty: "intermediate",
    flight_types: ["local", "ridge_soaring"],
    associated_landing_ids: ["fixture:lumbin"],
  }),
  site({ id: "fixture:lumbin", name: "Lumbin", kind: "landing", lat: 45.304, lon: 5.9105, elevation_m: 240 }),

  // ───────── Saint-André-les-Alpes ─────────
  site({
    id: "fixture:chalvet",
    name: "Chalvet",
    kind: "takeoff",
    lat: 43.9755,
    lon: 6.488,
    elevation_m: 1600,
    orientations: ["SE", "SSE", "S", "SSW", "SW", "WSW", "W"],
    difficulty: "beginner",
    flight_types: ["local", "cross_country"],
    description: "Grand déco multi-orientations, réputé pour le cross.",
    associated_landing_ids: ["fixture:st-andre-atterro"],
  }),
  site({ id: "fixture:st-andre-atterro", name: "Saint-André (Aire des Iscles)", kind: "landing", lat: 43.966, lon: 6.505, elevation_m: 900 }),

  // ───────── Dune du Pilat ─────────
  site({
    id: "fixture:pilat",
    name: "Dune du Pilat",
    kind: "both",
    lat: 44.5893,
    lon: -1.2131,
    elevation_m: 100,
    orientations: ["W", "WNW", "NW"],
    difficulty: "intermediate",
    flight_types: ["ridge_soaring"],
    description: "Soaring de dune par vent de mer établi (15-25 km/h).",
    restrictions: "Ne pas survoler les baigneurs, respecter la zone naturelle protégée.",
    associated_landing_ids: ["fixture:pilat-plage"],
  }),
  site({ id: "fixture:pilat-plage", name: "Plage du Pilat", kind: "landing", lat: 44.588, lon: -1.2168, elevation_m: 5 }),

  // ───────── Puy de Dôme ─────────
  site({
    id: "fixture:pdd-ouest",
    name: "Puy de Dôme (déco Ouest)",
    kind: "takeoff",
    lat: 45.7726,
    lon: 2.9605,
    elevation_m: 1410,
    orientations: ["SW", "WSW", "W", "WNW"],
    difficulty: "intermediate",
    flight_types: ["local", "ridge_soaring", "cross_country"],
    associated_landing_ids: ["fixture:pdd-atterro-ouest"],
  }),
  site({ id: "fixture:pdd-atterro-ouest", name: "Col de Ceyssat", kind: "landing", lat: 45.765, lon: 2.944, elevation_m: 1080 }),
  site({
    id: "fixture:pdd-est",
    name: "Puy de Dôme (déco Est)",
    kind: "takeoff",
    lat: 45.774,
    lon: 2.968,
    elevation_m: 1400,
    orientations: ["NE", "ENE", "E"],
    difficulty: "intermediate",
    flight_types: ["local"],
    associated_landing_ids: ["fixture:orcines"],
  }),
  site({ id: "fixture:orcines", name: "Orcines", kind: "landing", lat: 45.781, lon: 2.998, elevation_m: 830 }),

  // ───────── Millau ─────────
  site({
    id: "fixture:puncho",
    name: "Puncho d'Agast",
    kind: "takeoff",
    lat: 44.0933,
    lon: 3.103,
    elevation_m: 815,
    orientations: ["SSW", "SW", "WSW", "W"],
    difficulty: "beginner",
    flight_types: ["local", "ridge_soaring", "cross_country"],
    associated_landing_ids: ["fixture:millau-atterro"],
  }),
  site({ id: "fixture:millau-atterro", name: "Millau (la Maladrerie)", kind: "landing", lat: 44.09, lon: 3.083, elevation_m: 370 }),
];

export const MOCK_SITES_BY_ID: Record<string, Site> = Object.fromEntries(MOCK_SITES.map((s) => [s.id, s]));

/**
 * Points tournants remarquables pour les cross de démonstration
 * (sinon le moteur mock génère des balises géométriques).
 */
export const CROSS_TURNPOINTS: Record<string, { name: string; lat: number; lon: number; altitude_m: number }[]> = {
  "fixture:forclaz": [
    { name: "Roc des Bœufs", lat: 45.7395, lon: 6.185, altitude_m: 1774 },
    { name: "Dents de Lanfon", lat: 45.8805, lon: 6.2305, altitude_m: 1824 },
  ],
  "fixture:semnoz-est": [
    { name: "Crêt de Châtillon", lat: 45.7926, lon: 6.0939, altitude_m: 1699 },
    { name: "Montagne d'Entrevernes", lat: 45.765, lon: 6.18, altitude_m: 1550 },
  ],
  "fixture:planpraz": [
    { name: "Aiguillette des Houches", lat: 45.8975, lon: 6.7765, altitude_m: 2285 },
    { name: "Aiguilles Rouges (Index)", lat: 45.9565, lon: 6.885, altitude_m: 2595 },
  ],
  "fixture:chalvet": [
    { name: "Crête du Cheiron", lat: 43.82, lon: 6.95, altitude_m: 1778 },
    { name: "Montagne de Coupe", lat: 43.95, lon: 6.63, altitude_m: 1900 },
  ],
};

/** Reliefs nommés utilisés comme déclencheurs thermiques (sinon générés). */
export const THERMAL_TRIGGERS: Record<string, { name: string; lat: number; lon: number; altitude_m: number }> = {
  "fixture:forclaz": { name: "Arête de la Forclaz", lat: 45.8205, lon: 6.2525, altitude_m: 1480 },
  "fixture:planfait": { name: "Rochers de Planfait", lat: 45.852, lon: 6.243, altitude_m: 1400 },
  "fixture:semnoz-est": { name: "Crêt de Châtillon", lat: 45.7926, lon: 6.0939, altitude_m: 1699 },
};
