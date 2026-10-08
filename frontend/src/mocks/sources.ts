/** Simulation de GET /api/sources en mode démonstration. */
import type { SourcesResponse } from "../api/types";

export function mockSources(): SourcesResponse {
  return {
    sources: [
      { name: "Open-Meteo (AROME France HD, ICON-D2, ECMWF)", kind: "forecast", mode: "mock", healthy: true, requires_api_key: false, api_key_configured: false, message: "Démonstration : prévisions synthétiques générées dans le navigateur.", url: "https://open-meteo.com" },
      { name: "Open-Meteo Elevation", kind: "elevation", mode: "mock", healthy: true, requires_api_key: false, api_key_configured: false, message: null, url: "https://open-meteo.com/en/docs/elevation-api" },
      { name: "ParaglidingEarth", kind: "sites", mode: "mock", healthy: true, requires_api_key: false, api_key_configured: false, message: "Démonstration : sites approximatifs embarqués.", url: "https://www.paraglidingearth.com" },
      { name: "FFVL — sites de pratique", kind: "sites", mode: "disabled", healthy: false, requires_api_key: true, api_key_configured: false, message: "Clé API FFVL non configurée.", url: "https://data.ffvl.fr" },
      { name: "FFVL — balises", kind: "beacons", mode: "disabled", healthy: false, requires_api_key: true, api_key_configured: false, message: "Clé API FFVL non configurée.", url: "https://data.ffvl.fr" },
      { name: "SpotAir", kind: "sites", mode: "disabled", healthy: false, requires_api_key: false, api_key_configured: false, message: "Pas d'API publique : adaptateur prêt, nécessite un accord.", url: "https://www.spotair.mobi" },
      { name: "Pioupiou / OpenWindMap", kind: "beacons", mode: "mock", healthy: true, requires_api_key: false, api_key_configured: false, message: "Démonstration : balises simulées.", url: "https://www.openwindmap.org" },
      { name: "OpenAIP", kind: "airspaces", mode: "mock", healthy: true, requires_api_key: true, api_key_configured: false, message: "Démonstration : espaces aériens simplifiés.", url: "https://www.openaip.net" },
      { name: "Biodiv'Sports", kind: "sensitive_areas", mode: "mock", healthy: true, requires_api_key: false, api_key_configured: false, message: "Démonstration : zones sensibles approximatives.", url: "https://biodiv-sports.fr" },
      { name: "Météo-Parapente", kind: "forecast", mode: "disabled", healthy: false, requires_api_key: true, api_key_configured: false, message: "Pas d'API publique : adaptateur prêt, nécessite une licence.", url: "https://meteo-parapente.com" },
    ],
  };
}
