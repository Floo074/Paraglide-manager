/** Atterrissages : catégorie d'un site, marge de finesse (affichage). */
import type { LandingKind, Site } from "../api/types";

/** Catégorie d'atterrissage d'un site (repli : officiel si `official`, sinon communautaire). */
export function landingKindOf(site: Pick<Site, "landing_kind" | "official" | "source">): LandingKind {
  if (site.landing_kind) return site.landing_kind;
  if (site.official) return "official";
  return site.source === "osm" ? "field" : "community";
}

/** Marge de finesse : vert ≤ 70 % de la finesse disponible, orange jusqu'à 100 %, rouge au-delà. */
export function glideVerdict(required: number, available: number): "ok" | "near" | "over" {
  if (!(available > 0)) return "over";
  const r = required / available;
  return r > 1 ? "over" : r > 0.7 ? "near" : "ok";
}
