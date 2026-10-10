import { afterEach, describe, expect, it, vi } from "vitest";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

/** Client neuf (mode « unknown ») et sa classe ApiError (même graphe de modules). */
async function freshClient() {
  vi.resetModules();
  const api = await import("../api/client");
  const { ApiError } = await import("../api/errors");
  return { api, ApiError };
}

describe("client API : erreurs du backend", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("503 JSON (source indisponible en live) : erreur affichée, pas de bascule en démonstration", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(503, { detail: "Open-Meteo Elevation indisponible : ConnectTimeout: " })));
    const { api, ApiError } = await freshClient();
    const err = await api.getForecastPoint(45.83, 6.22, "2026-10-10T08:00:00Z").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as InstanceType<typeof ApiError>).status).toBe(503);
    expect((err as InstanceType<typeof ApiError>).message).toContain("Open-Meteo Elevation indisponible");
    expect(api.getApiMode()).not.toBe("demo-fallback");
  });

  it("502 / réseau (backend injoignable) : bascule en démonstration", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("Bad Gateway", { status: 502, headers: { "content-type": "text/html" } })));
    const { api } = await freshClient();
    const res = await api.getHealth();
    expect(res.data_mode).toBeDefined();
    expect(api.getApiMode()).toBe("demo-fallback");
  });

  it("422 : message de validation lisible", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(422, { detail: [{ loc: ["body"], msg: "Value error, indique elevation_m" }] })));
    const { api, ApiError } = await freshClient();
    const err = await api.getHealth().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as InstanceType<typeof ApiError>).message).toBe("indique elevation_m");
  });
});

describe("messages d'erreur pour le pilote", () => {
  it("422 « indique elevation_m » (relief indisponible) : message en français sans nom de champ d'API", async () => {
    const { ApiError, pilotErrorMessage, layerErrorText } = await import("../api/errors");
    const msg = pilotErrorMessage(new ApiError(422, "Altitude du point de décollage inconnue (MNT indisponible) : indique elevation_m."));
    expect(msg).toContain("Altitude (m)");
    expect(msg).not.toContain("elevation_m");
    expect(pilotErrorMessage(new ApiError(422, "Rayon trop grand"))).toBe("Rayon trop grand");
    expect(layerErrorText(new ApiError(503, "x", "ParaglidingEarth indisponible : ConnectTimeout: "))).toBe("ParaglidingEarth indisponible : ConnectTimeout");
  });
});
