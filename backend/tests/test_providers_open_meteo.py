"""Open-Meteo : parsing sur la vraie réponse enregistrée (3 modèles, Forclaz) + 429 + élévation.

Fixtures réelles : open_meteo_forclaz_3models.json (08/10/2026, identique en structure à l'appel du
09/10/2026), open_meteo_429.json (quota journalier), open_meteo_elevation_forclaz_doussard.json.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.config import Settings
from app.providers.base import ProviderError
from app.providers.open_meteo import (
    MAX_LOCATIONS_PER_CALL,
    REQUEST_LEVELS,
    OpenMeteoElevation,
    OpenMeteoForecast,
    build_params,
    hourly_variables,
    parse_elevation_response,
    parse_forecast_response,
    parse_location,
    series_summary,
)

FIX = Path(__file__).parent / "fixtures"
MODELS = ["meteofrance_arome_france_hd", "icon_d2", "ecmwf_ifs025"]
FORCLAZ = (45.81, 6.25, 1245.0)
FETCHED = datetime(2026, 10, 8, 6, tzinfo=UTC)


def _load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def raw() -> dict:
    return _load("open_meteo_forclaz_3models.json")


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _by_model(series):
    return {s.model: s for s in series}


# ---------------------------------------------------------------------------------------------
# Réponse multi-modèles réelle
# ---------------------------------------------------------------------------------------------
def test_three_models_parsed_with_model_suffixes(raw):
    pfs = parse_forecast_response(raw, [FORCLAZ], MODELS, FETCHED, "u")
    assert len(pfs) == 1
    pf = pfs[0]
    assert pf.mode == "live" and pf.source_name == "Open-Meteo"
    assert pf.elevation_m == 1245.0  # altitude demandée (downscaling Open-Meteo)
    m = _by_model(pf.models)
    assert set(m) == {"arome_france_hd", "icon_d2", "ecmwf_ifs025"}


def test_null_values_at_end_of_horizon_are_dropped(raw):
    m = _by_model(parse_location(raw, MODELS))
    # 72 heures demandées ; AROME HD et ICON-D2 s'arrêtent à l'index 66 (valeurs null ensuite)
    assert len(raw["hourly"]["time"]) == 72
    assert len(m["arome_france_hd"].hours) == 67
    assert len(m["icon_d2"].hours) == 67
    assert len(m["ecmwf_ifs025"].hours) == 72
    assert all(h.temperature_2m is not None for s in m.values() for h in s.hours)


def test_times_are_utc_aware(raw):
    m = _by_model(parse_location(raw, MODELS))
    h0 = m["icon_d2"].hours[0]
    assert h0.time == datetime(2026, 10, 8, 0, tzinfo=UTC)
    assert m["ecmwf_ifs025"].hours[-1].time == datetime(2026, 10, 10, 23, tzinfo=UTC)


def test_pressure_levels_available_per_model(raw):
    m = _by_model(parse_location(raw, MODELS))
    # AROME HD : surface uniquement
    assert all(h.levels == [] for h in m["arome_france_hd"].hours)
    # ICON-D2 : les 9 niveaux demandés
    assert [lv.pressure_hpa for lv in m["icon_d2"].hours[12].levels] == [float(p) for p in REQUEST_LEVELS]
    # ECMWF IFS 0,25° : pas de 950 / 900 / 800 hPa
    assert [lv.pressure_hpa for lv in m["ecmwf_ifs025"].hours[12].levels] == [1000.0, 925.0, 850.0, 700.0, 600.0, 500.0]
    lv850 = next(lv for lv in m["icon_d2"].hours[12].levels if lv.pressure_hpa == 850)
    assert 1000 < lv850.height_m < 1800  # géopotentiel ≈ altitude
    assert lv850.dew_point_c <= lv850.temperature_c + 1e-6


def test_surface_values_kmh_and_missing_variables(raw):
    m = _by_model(parse_location(raw, MODELS))
    i = 14
    h = raw["hourly"]
    icon = m["icon_d2"].hours[i]
    assert icon.wind_speed_10m == h["wind_speed_10m_icon_d2"][i]  # km/h, pas de conversion
    assert icon.wind_gusts_10m == h["wind_gusts_10m_icon_d2"][i]
    assert raw["hourly_units"]["wind_speed_10m_icon_d2"] == "km/h"
    assert icon.cape is not None and icon.convective_inhibition is not None and icon.shortwave_radiation is not None
    # non fournis par ces modèles → None (calculés par le moteur)
    assert all(hd.lifted_index is None and hd.boundary_layer_height is None for s in m.values() for hd in s.hours)
    ec = m["ecmwf_ifs025"].hours[i]
    assert ec.freezing_level_height is None and ec.convective_inhibition is None and ec.cape is not None


def test_arome_total_cloud_cover_rebuilt_from_layers(raw):
    """AROME HD ne fournit pas `cloud_cover` : reconstruit à partir des couches basse/moyenne/haute."""
    m = _by_model(parse_location(raw, MODELS))
    for hd in m["arome_france_hd"].hours:
        assert hd.cloud_cover is not None
        layers = [x for x in (hd.cloud_cover_low, hd.cloud_cover_mid, hd.cloud_cover_high) if x is not None]
        assert max(layers) - 1e-6 <= hd.cloud_cover <= 100.0


def test_series_summary(raw):
    pf = parse_forecast_response(raw, [FORCLAZ], MODELS, FETCHED, "u")[0]
    assert series_summary(pf) == "arome_france_hd 67 h/0 niv., icon_d2 67 h/9 niv., ecmwf_ifs025 72 h/6 niv."


def test_single_model_response_without_suffix(raw):
    """Avec un seul modèle, Open-Meteo ne suffixe pas les variables."""
    single = {k: v for k, v in raw.items() if k not in ("hourly", "hourly_units")}
    single["hourly"] = {"time": raw["hourly"]["time"]}
    single["hourly_units"] = {}
    for k, v in raw["hourly"].items():
        if k.endswith("_icon_d2"):
            single["hourly"][k[: -len("_icon_d2")]] = v
            single["hourly_units"][k[: -len("_icon_d2")]] = raw["hourly_units"][k]
    series = parse_location(single, ["icon_d2"])
    assert len(series) == 1 and series[0].model == "icon_d2"
    assert len(series[0].hours) == 67 and len(series[0].hours[10].levels) == 9


def test_multi_location_list_response(raw):
    loc2 = copy.deepcopy(raw)
    loc2["latitude"], loc2["longitude"] = 45.78, 6.22
    pts = [FORCLAZ, (45.7819, 6.2221, 467.0)]
    pfs = parse_forecast_response([raw, loc2], pts, MODELS, FETCHED, "u")
    assert [(p.lat, p.elevation_m) for p in pfs] == [(45.81, 1245.0), (45.7819, 467.0)]


def test_location_count_mismatch_raises(raw):
    with pytest.raises(ProviderError, match="2 demandées"):
        parse_forecast_response(raw, [FORCLAZ, FORCLAZ], MODELS, FETCHED, "u")


def test_wind_unit_conversion_if_not_kmh(raw):
    ms = copy.deepcopy(raw)
    for k in ms["hourly_units"]:
        if k.startswith("wind_speed") or k.startswith("wind_gusts"):
            ms["hourly_units"][k] = "m/s"
    a = _by_model(parse_location(raw, MODELS))["icon_d2"].hours[14]
    b = _by_model(parse_location(ms, MODELS))["icon_d2"].hours[14]
    assert b.wind_speed_10m == pytest.approx(a.wind_speed_10m * 3.6)
    assert b.levels[4].wind_speed_kmh == pytest.approx(a.levels[4].wind_speed_kmh * 3.6)


def test_unexpected_wind_unit_raises(raw):
    bad = copy.deepcopy(raw)
    bad["hourly_units"]["wind_speed_10m_icon_d2"] = "beaufort"
    with pytest.raises(ProviderError, match="unité de vent"):
        parse_location(bad, MODELS)


def test_utc_offset_applied_if_not_gmt(raw):
    shifted = copy.deepcopy(raw)
    shifted["utc_offset_seconds"] = 7200
    h0 = _by_model(parse_location(shifted, MODELS))["icon_d2"].hours[0]
    assert h0.time == datetime(2026, 10, 7, 22, tzinfo=UTC)


def test_error_body_and_missing_time():
    with pytest.raises(ProviderError, match="Daily API request limit exceeded"):
        parse_forecast_response(_load("open_meteo_429.json"), [FORCLAZ], MODELS, FETCHED, "u")
    with pytest.raises(ProviderError, match=r"hourly\.time"):
        parse_location({"hourly": {}}, MODELS)


# ---------------------------------------------------------------------------------------------
# Requête construite
# ---------------------------------------------------------------------------------------------
def test_build_params():
    start = datetime(2026, 10, 9, 5, 30, tzinfo=UTC)
    p = build_params([FORCLAZ], MODELS, start, start + timedelta(hours=36), with_levels=True)
    assert p["wind_speed_unit"] == "kmh" and p["timezone"] == "GMT"
    assert p["models"] == ",".join(MODELS)
    assert p["start_hour"] == "2026-10-09T05:00" and p["end_hour"] == "2026-10-10T17:00"
    assert p["elevation"] == "1245" and p["latitude"] == "45.8100" and p["longitude"] == "6.2500"
    hv = p["hourly"].split(",")
    assert "geopotential_height_500hPa" in hv and "wind_gusts_10m" in hv
    assert len(hv) == len(hourly_variables(True)) == 16 + 5 * 9
    # une altitude inconnue → pas de paramètre elevation (sinon les listes seraient de tailles différentes)
    p2 = build_params([FORCLAZ, (45.0, 6.0, None)], MODELS, start, start, with_levels=False)
    assert "elevation" not in p2 and "temperature_850hPa" not in p2["hourly"]


async def test_fetch_sends_expected_query_and_parses(raw):
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=raw)

    async with _client(handler) as c:
        prov = OpenMeteoForecast(c, "https://api.open-meteo.com/v1/forecast", MODELS)
        start = datetime(2026, 10, 8, 0, tzinfo=UTC)
        pfs = await prov.fetch([FORCLAZ], start, start + timedelta(hours=71))
    assert len(seen) == 1
    q = parse_qs(urlparse(str(seen[0].url)).query)
    assert q["models"] == [",".join(MODELS)] and q["wind_speed_unit"] == ["kmh"] and q["timezone"] == ["GMT"]
    assert "apikey" not in q
    assert len(pfs[0].models) == 3


async def test_fetch_chunks_locations(raw):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        n = len(parse_qs(urlparse(str(req.url)).query)["latitude"][0].split(","))
        calls.append(n)
        return httpx.Response(200, json=[raw] * n)

    pts = [(45.0 + i * 0.01, 6.0, 1000.0) for i in range(MAX_LOCATIONS_PER_CALL + 5)]
    async with _client(handler) as c:
        prov = OpenMeteoForecast(c, "https://api.open-meteo.com/v1/forecast", MODELS)
        start = datetime(2026, 10, 8, 0, tzinfo=UTC)
        pfs = await prov.fetch(pts, start, start + timedelta(hours=3))
    assert calls == [MAX_LOCATIONS_PER_CALL, 5]
    assert len(pfs) == len(pts)


# ---------------------------------------------------------------------------------------------
# 429 → erreur propre, puis repli sur la météo synthétique en DATA_MODE=auto
# ---------------------------------------------------------------------------------------------
def _handler_429(counter: list):
    body = (FIX / "open_meteo_429.json").read_bytes()

    def handler(req: httpx.Request) -> httpx.Response:
        counter.append(str(req.url))
        return httpx.Response(429, content=body, headers={"content-type": "application/json"})

    return handler


async def test_429_raises_provider_error_with_status_and_reason():
    calls: list = []
    async with _client(_handler_429(calls)) as c:
        prov = OpenMeteoForecast(c, "https://api.open-meteo.com/v1/forecast", MODELS)
        start = datetime(2026, 10, 8, 0, tzinfo=UTC)
        with pytest.raises(ProviderError) as ei:
            await prov.fetch([FORCLAZ], start, start + timedelta(hours=3))
    assert ei.value.http_status == 429
    assert "HTTP 429" in str(ei.value) and "Daily API request limit exceeded" in str(ei.value)
    assert len(calls) == 1  # pas de nouvelle tentative en boucle


async def test_429_falls_back_to_synthetic_in_auto_mode():
    from app.services import DataService

    calls: list = []
    settings = Settings(_env_file=None, data_mode="auto")
    client = _client(_handler_429(calls))
    svc = DataService(settings, client=client)
    try:
        start = datetime(2026, 10, 9, 6, tzinfo=UTC)
        fcs, refs = await svc.forecasts([FORCLAZ], start, start + timedelta(hours=6), start)
        assert len(fcs) == 1 and fcs[0].mode == "mock"
        assert [r.mode for r in refs] == ["mock"]
        st = svc.states["open-meteo"]
        assert st.last_error and "429" in st.last_error
        # pas de nouvel appel pendant live_retry_after_s
        await svc.forecasts([(45.9, 6.1, 1000.0)], start, start + timedelta(hours=6), start)
        assert len(calls) == 1
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------------------------
# Élévation
# ---------------------------------------------------------------------------------------------
def test_parse_real_elevation_response():
    assert parse_elevation_response(_load("open_meteo_elevation_forclaz_doussard.json"), 2) == [1244.0, 463.0]
    assert parse_elevation_response({"elevation": [None]}, 1) == [0.0]
    with pytest.raises(ProviderError):
        parse_elevation_response({"elevation": [1.0]}, 2)
    with pytest.raises(ProviderError, match="Elevation"):
        parse_elevation_response({"error": True, "reason": "Latitude must be in range"}, 1)


async def test_elevation_fetch_batches_by_100():
    sizes = []

    def handler(req: httpx.Request) -> httpx.Response:
        n = len(parse_qs(urlparse(str(req.url)).query)["latitude"][0].split(","))
        sizes.append(n)
        return httpx.Response(200, json={"elevation": [500.0] * n})

    async with _client(handler) as c:
        vals = await OpenMeteoElevation(c, "https://api.open-meteo.com/v1/elevation").fetch(
            [(45.0 + i * 0.001, 6.0) for i in range(150)]
        )
    assert sizes == [100, 50] and len(vals) == 150
