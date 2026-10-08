/** Fonds de carte (tous sans clé d'API) et couche optionnelle KK7. */

export interface BaseLayerDef {
  id: "topo" | "osm" | "satellite";
  name: string;
  url: string;
  attribution: string;
  maxZoom: number;
  maxNativeZoom?: number;
  subdomains?: string;
}

export const BASE_LAYERS: BaseLayerDef[] = [
  {
    id: "topo",
    name: "Relief (OpenTopoMap)",
    // hôte sans sous-domaine : HTTP/2, pas besoin de répartir sur a/b/c
    url: "https://tile.opentopomap.org/{z}/{x}/{y}.png",
    attribution:
      'Données : &copy; <a href="https://www.openstreetmap.org/copyright">contributeurs OpenStreetMap</a>, SRTM | ' +
      'Style : &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>)',
    maxZoom: 17,
    maxNativeZoom: 17,
  },
  {
    id: "osm",
    name: "Plan (OpenStreetMap)",
    url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">contributeurs OpenStreetMap</a>',
    maxZoom: 19,
  },
  {
    id: "satellite",
    name: "Satellite (Esri)",
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution:
      "Imagerie &copy; Esri — Source : Esri, Maxar, Earthstar Geographics, USDA, USGS, AeroGRID, IGN et la communauté des utilisateurs SIG",
    maxZoom: 19,
    maxNativeZoom: 18,
  },
];

export type BaseLayerId = BaseLayerDef["id"];
export const DEFAULT_BASE_LAYER: BaseLayerId = "topo";

/** Couche KK7 (hotspots thermiques). Désactivée si VITE_KK7_TILES_URL n'est pas renseignée. */
export const KK7 = {
  url: (import.meta.env.VITE_KK7_TILES_URL ?? "").trim(),
  tms: (import.meta.env.VITE_KK7_TMS ?? "true").toLowerCase() !== "false",
  attribution: 'Hotspots thermiques &copy; <a href="https://thermal.kk7.ch">thermal.kk7.ch</a> (CC BY-NC-SA 4.0)',
  maxNativeZoom: 12,
};
