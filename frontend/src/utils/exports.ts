/**
 * Génération côté client des exports GPX 1.1 et tâche XCTrack (v1).
 * Utilisée en mode démonstration ; avec le backend, les liens `plan.links.*` sont utilisés.
 */
import type { FlightPlan, Waypoint } from "../api/types";

export function escapeXml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

const coord = (v: number) => v.toFixed(6);

const GPX_SYM: Record<Waypoint["type"], string> = {
  takeoff: "Airport",
  turnpoint: "Flag, Blue",
  thermal_trigger: "Summit",
  landing: "Flag, Green",
  alternate_landing: "Flag, Red",
};

const WAYPOINT_TYPE_FR: Record<Waypoint["type"], string> = {
  takeoff: "Décollage",
  turnpoint: "Balise",
  thermal_trigger: "Déclencheur thermique",
  landing: "Atterrissage",
  alternate_landing: "Atterrissage de secours",
};

export function waypointTypeLabel(t: Waypoint["type"]): string {
  return WAYPOINT_TYPE_FR[t];
}

/** GPX 1.1 : wpt (déco, balises, atterros), rte (ordre du vol), trk (trace prévue), metadata. */
export function buildGpx(plan: FlightPlan, generatedAt: Date = new Date()): string {
  const lines: string[] = [];
  lines.push('<?xml version="1.0" encoding="UTF-8"?>');
  lines.push(
    '<gpx version="1.1" creator="Paraglide Manager" xmlns="http://www.topografix.com/GPX/1/1" ' +
      'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" ' +
      'xsi:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd">',
  );
  lines.push("  <metadata>");
  lines.push(`    <name>${escapeXml(plan.title)}</name>`);
  lines.push(`    <desc>${escapeXml([plan.summary, ...plan.briefing.slice(0, 4)].join(" • "))}</desc>`);
  lines.push(`    <time>${generatedAt.toISOString()}</time>`);
  lines.push("  </metadata>");
  for (const w of plan.waypoints) {
    lines.push(`  <wpt lat="${coord(w.lat)}" lon="${coord(w.lon)}">`);
    lines.push(`    <ele>${Math.round(w.altitude_m)}</ele>`);
    lines.push(`    <name>${escapeXml(w.name)}</name>`);
    const desc = [WAYPOINT_TYPE_FR[w.type], w.note].filter(Boolean).join(" — ");
    lines.push(`    <desc>${escapeXml(desc)}</desc>`);
    lines.push(`    <sym>${GPX_SYM[w.type]}</sym>`);
    lines.push(`    <type>${w.type}</type>`);
    lines.push("  </wpt>");
  }
  const routePts = plan.waypoints.filter((w) => w.type !== "alternate_landing");
  lines.push("  <rte>");
  lines.push(`    <name>${escapeXml(plan.title)}</name>`);
  for (const w of routePts) {
    lines.push(`    <rtept lat="${coord(w.lat)}" lon="${coord(w.lon)}"><ele>${Math.round(w.altitude_m)}</ele><name>${escapeXml(w.name)}</name></rtept>`);
  }
  lines.push("  </rte>");
  if (plan.route.coordinates.length > 1) {
    lines.push("  <trk>");
    lines.push("    <name>Trace prévue</name>");
    lines.push("    <trkseg>");
    for (const [lon, lat, alt] of plan.route.coordinates) {
      lines.push(`      <trkpt lat="${coord(lat)}" lon="${coord(lon)}"><ele>${Math.round(alt)}</ele></trkpt>`);
    }
    lines.push("    </trkseg>");
    lines.push("  </trk>");
  }
  lines.push("</gpx>");
  return lines.join("\n") + "\n";
}

export interface XctskTurnpoint {
  type?: "TAKEOFF" | "SSS" | "ESS";
  radius: number;
  waypoint: { name: string; description: string; lat: number; lon: number; altSmoothed: number };
}

export interface XctskTask {
  taskType: "CLASSIC";
  version: 1;
  earthModel: "WGS84";
  turnpoints: XctskTurnpoint[];
  goal: { type: "CYLINDER" | "LINE" };
}

/**
 * Tâche XCTrack (format v1, contrat) : déco en TAKEOFF, balises, atterrissage = dernière balise
 * typée ESS et décrite par l'objet `goal` (XCTrack n'a pas de type « GOAL »). Les déclencheurs
 * thermiques et les atterrissages de secours ne sont pas des balises de tâche.
 */
export function buildXctsk(plan: FlightPlan): XctskTask {
  const name = (w: Waypoint) => w.name.slice(0, 40);
  const tp = (w: Waypoint, defaultRadius: number, type?: XctskTurnpoint["type"]): XctskTurnpoint => ({
    ...(type ? { type } : {}),
    radius: Math.round(w.radius_m ?? defaultRadius),
    waypoint: {
      name: name(w),
      description: w.note ?? WAYPOINT_TYPE_FR[w.type],
      lat: Number(w.lat.toFixed(6)),
      lon: Number(w.lon.toFixed(6)),
      altSmoothed: Math.round(w.altitude_m),
    },
  });
  const takeoff = plan.waypoints.find((w) => w.type === "takeoff");
  const turnpoints = plan.waypoints.filter((w) => w.type === "turnpoint");
  const landing = plan.waypoints.find((w) => w.type === "landing");
  const list: XctskTurnpoint[] = [];
  if (takeoff) list.push(tp(takeoff, 400, "TAKEOFF"));
  for (const w of turnpoints) list.push(tp(w, 400));
  if (landing) list.push(tp(landing, 200, "ESS"));
  return { taskType: "CLASSIC", version: 1, earthModel: "WGS84", turnpoints: list, goal: { type: "CYLINDER" } };
}

/** Nom de fichier sûr à partir d'un titre. */
export function safeFilename(title: string, ext: string): string {
  const base = title
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-zA-Z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .toLowerCase()
    .slice(0, 60);
  return `${base || "plan-de-vol"}.${ext}`;
}
