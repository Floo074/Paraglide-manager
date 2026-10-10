/** Icônes Leaflet (divIcon SVG) : décos avec secteurs, atterros, balises, waypoints, flèches de vent. */
import L from "leaflet";
import type { Beacon, LandingKind, Site, Waypoint } from "../../api/types";
import { compassToDeg, normalizeDeg } from "../../utils/units";
import { formatAgeShort } from "../../utils/format";

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);

function polar(cx: number, cy: number, r: number, deg: number): [number, number] {
  const a = ((deg - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}

/** Secteur annulaire (rose 16 points) centré sur `deg`. */
function wedge(cx: number, cy: number, r0: number, r1: number, deg: number, half = 11.25): string {
  const [x1, y1] = polar(cx, cy, r1, deg - half);
  const [x2, y2] = polar(cx, cy, r1, deg + half);
  const [x3, y3] = polar(cx, cy, r0, deg + half);
  const [x4, y4] = polar(cx, cy, r0, deg - half);
  return `M${x1.toFixed(1)},${y1.toFixed(1)} A${r1},${r1} 0 0 1 ${x2.toFixed(1)},${y2.toFixed(1)} L${x3.toFixed(1)},${y3.toFixed(1)} A${r0},${r0} 0 0 0 ${x4.toFixed(1)},${y4.toFixed(1)} Z`;
}

export interface SiteIconOptions {
  highlight?: boolean;
  dim?: boolean;
}

const STATUS_COLOR: Record<Site["status"], string> = {
  open: "#15803d",
  restricted: "#c2410c",
  closed: "#6b7280",
  unknown: "#15803d",
};

/** Décollage : pastille "D" entourée des secteurs d'orientation favorables (d'où vient le vent). */
export function takeoffIcon(site: Site, opts: SiteIconOptions = {}): L.DivIcon {
  const size = opts.highlight ? 58 : 48;
  const c = size / 2;
  const r0 = 10.5;
  const r1 = c - 2;
  const sectors = site.orientations
    .map(compassToDeg)
    .filter((d): d is number => d !== null)
    .map((d) => `<path d="${wedge(c, c, r0, r1, d)}" />`)
    .join("");
  const color = STATUS_COLOR[site.status];
  const closed = site.status === "closed";
  const html = `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" class="site-svg${opts.dim ? " site-svg--dim" : ""}">
    <circle cx="${c}" cy="${c}" r="${r1}" class="sector-ring"/>
    <g class="sectors${closed ? " sectors--closed" : ""}">${sectors}</g>
    <circle cx="${c}" cy="${c}" r="${r0}" fill="${color}" stroke="#fff" stroke-width="2"/>
    <text x="${c}" y="${c + 4.2}" text-anchor="middle" class="site-letter">D</text>
    ${closed ? `<path d="M${c - 6},${c - 6} L${c + 6},${c + 6} M${c + 6},${c - 6} L${c - 6},${c + 6}" stroke="#fff" stroke-width="2.4"/>` : ""}
  </svg>`;
  return L.divIcon({
    html,
    className: `site-icon${opts.highlight ? " site-icon--hl" : ""}`,
    iconSize: [size, size],
    iconAnchor: [c, c],
    popupAnchor: [0, -c + 4],
  });
}

/** Atterrissage : carré arrondi bleu "A". */
export function landingIcon(opts: SiteIconOptions & { alternate?: boolean } = {}): L.DivIcon {
  const s = opts.highlight ? 28 : 22;
  const fill = opts.alternate ? "#64748b" : "#1d4ed8";
  const html = `<svg width="${s}" height="${s}" viewBox="0 0 22 22" class="site-svg${opts.dim ? " site-svg--dim" : ""}">
    <rect x="1.5" y="1.5" width="19" height="19" rx="5" fill="${fill}" stroke="#fff" stroke-width="2" ${opts.alternate ? 'stroke-dasharray="3 2"' : ""}/>
    <text x="11" y="15.2" text-anchor="middle" class="site-letter">A</text>
  </svg>`;
  return L.divIcon({ html, className: "site-icon", iconSize: [s, s], iconAnchor: [s / 2, s / 2], popupAnchor: [0, -s / 2] });
}

/** Balise : flèche orientée dans le sens où va le vent, couleur selon la vitesse, étiquette moyenne/rafale + âge. */
export function beaconIcon(b: Beacon, color: string, now: Date): L.DivIcon {
  const speed = b.wind_speed_kmh;
  const dir = b.wind_direction_deg;
  const stale = b.stale;
  const fill = stale || speed === null ? "#94a3b8" : color;
  const arrow =
    dir === null || speed === null
      ? `<circle cx="17" cy="17" r="6" fill="${fill}" stroke="#0f172a" stroke-width="1.2"/>`
      : `<g transform="rotate(${normalizeDeg(dir + 180)} 17 17)">
           <path d="M17 3 L24.5 17.5 L19.6 16.2 L19.6 30 L14.4 30 L14.4 16.2 L9.5 17.5 Z" fill="${fill}" stroke="#0f172a" stroke-width="1.2" stroke-linejoin="round"/>
         </g>`;
  const label =
    speed === null
      ? "—"
      : `${Math.round(speed)}${b.wind_gust_kmh !== null && b.wind_gust_kmh > speed + 1 ? `<span class="beacon-gust">/${Math.round(b.wind_gust_kmh)}</span>` : ""}`;
  const html = `<div class="beacon${stale ? " beacon--stale" : ""}">
    <svg width="34" height="34" viewBox="0 0 34 34">${arrow}</svg>
    <span class="beacon-label">${label}<span class="beacon-age">${esc(formatAgeShort(b.observed_at, now))}</span></span>
  </div>`;
  return L.divIcon({ html, className: "beacon-icon", iconSize: [34, 48], iconAnchor: [17, 17], popupAnchor: [0, -14] });
}

const WP_STYLE: Record<Waypoint["type"], { fill: string; letter: string; shape: "circle" | "square" | "diamond" }> = {
  takeoff: { fill: "#15803d", letter: "D", shape: "circle" },
  turnpoint: { fill: "#7c3aed", letter: "", shape: "circle" },
  thermal_trigger: { fill: "#ea580c", letter: "T", shape: "diamond" },
  landing: { fill: "#1d4ed8", letter: "A", shape: "square" },
  alternate_landing: { fill: "#64748b", letter: "S", shape: "square" },
};

/** Waypoint du plan de vol (numéroté pour les balises). */
export function waypointIcon(type: Waypoint["type"], index: number): L.DivIcon {
  const st = WP_STYLE[type];
  const letter = st.letter || String(index);
  const shape =
    st.shape === "circle"
      ? `<circle cx="13" cy="13" r="10.5" fill="${st.fill}" stroke="#fff" stroke-width="2.2"/>`
      : st.shape === "square"
        ? `<rect x="2.5" y="2.5" width="21" height="21" rx="5" fill="${st.fill}" stroke="#fff" stroke-width="2.2" ${type === "alternate_landing" ? 'stroke-dasharray="3 2"' : ""}/>`
        : `<rect x="5" y="5" width="16" height="16" rx="3" transform="rotate(45 13 13)" fill="${st.fill}" stroke="#fff" stroke-width="2.2"/>`;
  const html = `<svg width="26" height="26" viewBox="0 0 26 26" class="wp-svg">${shape}<text x="13" y="17.3" text-anchor="middle" class="site-letter">${esc(letter)}</text></svg>`;
  return L.divIcon({ html, className: "wp-icon", iconSize: [26, 26], iconAnchor: [13, 13], popupAnchor: [0, -12] });
}

/** Flèche de vent de la grille météo (pointe vers où va le vent). */
export function windArrowIcon(speedKmh: number, dirDeg: number, color: string, showLabel: boolean): L.DivIcon {
  const len = 10 + Math.min(14, speedKmh / 3);
  const html = `<div class="grid-arrow"><svg width="30" height="30" viewBox="0 0 30 30"><g transform="rotate(${normalizeDeg(dirDeg + 180)} 15 15)">
    <line x1="15" y1="${15 + len / 2}" x2="15" y2="${15 - len / 2 + 3}" stroke="${color}" stroke-width="3" stroke-linecap="round"/>
    <path d="M15 ${15 - len / 2 - 2} L20 ${15 - len / 2 + 5} L10 ${15 - len / 2 + 5} Z" fill="${color}"/>
  </g></svg>${showLabel ? `<span class="grid-arrow__label">${Math.round(speedKmh)}</span>` : ""}</div>`;
  return L.divIcon({ html, className: "grid-arrow-icon", iconSize: [30, 30], iconAnchor: [15, 15] });
}

/** Bulle de regroupement de marqueurs. */
export function clusterIcon(count: number, kind: "site" | "beacon"): L.DivIcon {
  const size = count < 10 ? 32 : count < 50 ? 38 : 44;
  return L.divIcon({
    html: `<div class="cluster cluster--${kind}" style="width:${size}px;height:${size}px"><span>${count}</span></div>`,
    className: "cluster-icon",
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

/** Poignée de déplacement (centre / rayon de la zone). */
export function handleIcon(kind: "center" | "radius"): L.DivIcon {
  return L.divIcon({
    html: `<div class="zone-handle zone-handle--${kind}"></div>`,
    className: "zone-handle-icon",
    iconSize: [22, 22],
    iconAnchor: [11, 11],
  });
}

const LANDING_KIND_FILL: Record<LandingKind, string> = { official: "#16a34a", community: "#2563eb", field: "#ea580c" };

/** Atterro candidat : carré coloré par catégorie (officiel vert, communautaire bleu, champ orange), numéroté. */
export function landingCandidateIcon(kind: LandingKind, rank: number, selected = false): L.DivIcon {
  const s = selected ? 32 : 26;
  const fill = LANDING_KIND_FILL[kind];
  const dash = kind === "field" ? 'stroke-dasharray="3 2"' : "";
  const html = `<svg width="${s}" height="${s}" viewBox="0 0 26 26" class="site-svg">
    ${selected ? `<rect x="0.5" y="0.5" width="25" height="25" rx="7" fill="none" stroke="${fill}" stroke-width="1.5" opacity="0.7"/>` : ""}
    <rect x="3" y="3" width="20" height="20" rx="5" fill="${fill}" stroke="#fff" stroke-width="2.2" ${dash}/>
    <text x="13" y="17.3" text-anchor="middle" class="site-letter">${rank}</text>
  </svg>`;
  return L.divIcon({ html, className: `site-icon lc-icon${selected ? " site-icon--hl" : ""}`, iconSize: [s, s], iconAnchor: [s / 2, s / 2], popupAnchor: [0, -s / 2] });
}

/** Décollage libre : pastille « D » à anneau pointillé (+ secteurs si orientations connues). */
export function freeTakeoffIcon(orientations: string[]): L.DivIcon {
  const size = 52;
  const c = size / 2;
  const r0 = 11;
  const r1 = c - 3;
  const sectors = orientations
    .map(compassToDeg)
    .filter((d): d is number => d !== null)
    .map((d) => `<path d="${wedge(c, c, r0, r1, d)}" />`)
    .join("");
  const html = `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" class="site-svg free-takeoff-svg">
    <circle cx="${c}" cy="${c}" r="${c - 1.5}" fill="rgba(124,58,237,0.12)" stroke="#7c3aed" stroke-width="2" stroke-dasharray="4 3"/>
    <g class="sectors">${sectors}</g>
    <circle cx="${c}" cy="${c}" r="${r0}" fill="#7c3aed" stroke="#fff" stroke-width="2"/>
    <text x="${c}" y="${c + 4.2}" text-anchor="middle" class="site-letter">D</text>
  </svg>`;
  return L.divIcon({ html, className: "site-icon free-takeoff-icon", iconSize: [size, size], iconAnchor: [c, c], popupAnchor: [0, -c + 4] });
}

/**
 * Indicateur du vent sur la ligne de plané (fiche plan) : flèche orientée sur la carte le long de la route
 * (vers l'atterro = vent arrière, vers le déco = vent de face, rond = vent faible) + composante et effet sur la finesse.
 */
export function glideWindIcon(kind: "tail" | "head" | "weak", rotateDeg: number, label: string, sub: string | null): L.DivIcon {
  const shape =
    kind === "weak"
      ? `<circle cx="13" cy="13" r="5" class="gw-map__dot"/>`
      : `<g transform="rotate(${normalizeDeg(rotateDeg).toFixed(1)} 13 13)">
           <path d="M13 1.5 L20.5 12.5 L15.6 11.6 L15.6 24.5 L10.4 24.5 L10.4 11.6 L5.5 12.5 Z" class="gw-map__arrow"/>
         </g>`;
  const html = `<div class="gw-map gw-map--${kind}">
    <svg width="26" height="26" viewBox="0 0 26 26">${shape}</svg>
    <span class="gw-map__label"><strong>${esc(label)}</strong>${sub ? `<span class="gw-map__sub">${esc(sub)}</span>` : ""}</span>
  </div>`;
  return L.divIcon({ html, className: "gw-map-icon", iconSize: [26, 26], iconAnchor: [13, 13], tooltipAnchor: [14, 0] });
}
