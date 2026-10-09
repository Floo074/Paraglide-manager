"""Balises : Pioupiou live (réponse réelle), archive 1 h → Beacon.trend (réponse réelle), MNT des balises sans
altitude, tendance limitée aux balises des plans, attribution OpenWindMap, fixtures de démonstration.

Fixtures réelles : pioupiou_live_all.json (08/10/2026), pioupiou_archive_1708.json (09/10/2026,
`GET /v1/archive/1708?start=last-hour&stop=now`).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.config import Settings
from app.engine.stations import trend_label, usable_trend
from app.models import Beacon, BeaconTrend
from app.providers.base import ProviderError
from app.providers.beacons import (
    FixtureBeacons,
    PioupiouBeacons,
    archive_url,
    fixture_beacon_dem,
    parse_pioupiou,
    parse_pioupiou_archive,
    trend_from_samples,
)
from app.providers.synthetic_weather import SyntheticWeather
from app.services import MAX_TREND_CALLS, DataService

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 8, 19, 40, tzinfo=UTC)


def _load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _settings(mode: str = "auto") -> Settings:
    return Settings(data_mode=mode, openaip_api_key=None, ffvl_api_key=None)


def _beacon(bid: str, lat: float, lon: float, elevation_m: float | None = None, source: str = "pioupiou") -> Beacon:
    return Beacon(id=bid, name=bid, lat=lat, lon=lon, elevation_m=elevation_m, observed_at="2026-10-09T12:00:00Z",
                  wind_speed_kmh=10, wind_gust_kmh=15, wind_direction_deg=270, source=source, stale=False)  # fmt: skip


# ---------------------------------------------------------------------------------------------
# Archive Pioupiou (réponse réelle) → tendance
# ---------------------------------------------------------------------------------------------
def test_archive_real_response_parsed_into_trend():
    t = parse_pioupiou_archive(_load("pioupiou_archive_1708.json"))
    assert t is not None
    assert t.samples == 12  # ~1 mesure / 5 min sur la dernière heure
    assert t.window_min == pytest.approx(55.2, abs=0.1)  # 04:46:54 → 05:42:08
    # moyenne des 10 premières minutes (3,25 ; 3,5) vs 10 dernières (2,25 ; 2,0)
    assert t.speed_change_kmh == pytest.approx(2.125 - 3.375, abs=0.06)
    assert t.gust_max_kmh == 10.0
    assert 0 < t.direction_change_deg < 20  # 270 → ~281 : rotation horaire faible
    assert usable_trend(_beacon("x", 45, 6).model_copy(update={"trend": t}))


def test_archive_columns_located_by_legend_not_position():
    raw = _load("pioupiou_archive_1708.json")
    order = [7, 6, 5, 4, 3, 2, 1, 0]  # colonnes inversées : le parseur suit `legend`
    raw["legend"] = [raw["legend"][i] for i in order]
    raw["units"] = [raw["units"][i] for i in order]
    raw["data"] = [[row[i] for i in order] for row in raw["data"]]
    assert parse_pioupiou_archive(raw) == parse_pioupiou_archive(_load("pioupiou_archive_1708.json"))


def test_archive_rejects_bad_format_and_units():
    with pytest.raises(ProviderError):
        parse_pioupiou_archive({"data": []})
    raw = _load("pioupiou_archive_1708.json")
    raw["legend"] = [x for x in raw["legend"] if x != "wind_heading"]
    with pytest.raises(ProviderError):
        parse_pioupiou_archive(raw)
    raw = _load("pioupiou_archive_1708.json")
    raw["units"][4] = "m/s"
    with pytest.raises(ProviderError):
        parse_pioupiou_archive(raw)


def test_archive_short_history_is_not_a_usable_trend():
    raw = _load("pioupiou_archive_1708.json")
    raw["data"] = raw["data"][:1]
    assert parse_pioupiou_archive(raw) is None  # une mesure : pas de tendance
    raw = _load("pioupiou_archive_1708.json")
    raw["data"] = raw["data"][-3:]  # 10 min, 3 mesures : < 45 min / < 4 mesures (§12.2)
    t = parse_pioupiou_archive(raw)
    b = _beacon("x", 45, 6).model_copy(update={"trend": t})
    assert t is not None and not usable_trend(b)
    assert trend_label(b) == "tendance indisponible"


def test_trend_from_samples_increase_and_rotation():
    t0 = datetime(2026, 10, 9, 11, 0, tzinfo=UTC)
    rows = [(t0 + timedelta(minutes=5 * i), 5.0 + i, 9.0 + i, (0.0 + 9 * i) % 360) for i in range(13)]
    t = trend_from_samples(rows)
    assert t is not None and t.window_min == 60 and t.samples == 13
    assert t.speed_change_kmh == pytest.approx(10.0)  # (15+16+17)/3 − (5+6+7)/3 : moyennes sur 10 min
    assert t.direction_change_deg > 60  # rotation horaire
    assert t.gust_max_kmh == 21.0
    b = _beacon("x", 45, 6).model_copy(update={"trend": t})
    assert "km/h en 1 h" in trend_label(b) and "rotation" in trend_label(b)


def test_archive_url():
    assert archive_url("https://api.pioupiou.fr/v1/live/all", "1708") == "https://api.pioupiou.fr/v1/archive/1708"


async def test_fetch_trend_calls_archive_endpoint_with_last_hour():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url)
        return httpx.Response(200, json=_load("pioupiou_archive_1708.json"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        t = await PioupiouBeacons(c, "https://api.pioupiou.fr/v1/live/all").fetch_trend("pioupiou:1708")
    assert t is not None and t.samples == 12
    u = urlparse(str(seen[0]))
    assert u.netloc == "api.pioupiou.fr" and u.path == "/v1/archive/1708"
    assert parse_qs(u.query) == {"start": ["last-hour"], "stop": ["now"]}


# ---------------------------------------------------------------------------------------------
# Pioupiou live (réponse réelle)
# ---------------------------------------------------------------------------------------------
def test_live_keeps_silent_beacons_as_stale_and_reads_altitude_in_name():
    bs = {b.id: b for b in parse_pioupiou(_load("pioupiou_live_all.json"), NOW)}
    b1720 = bs["pioupiou:1720"]  # « Atterrissage de Doussard » : mesures null → muette, gardée pour la dire absente
    assert b1720.name == "Atterrissage de Doussard" and b1720.wind_speed_kmh is None and b1720.stale
    assert b1720.elevation_m is None  # Pioupiou ne fournit pas d'altitude
    assert bs["pioupiou:1708"].elevation_m == 1570  # « Déco Anglettaz 1570m »
    assert bs["pioupiou:1476"].elevation_m is None and bs["pioupiou:1476"].wind_speed_kmh == 14


# ---------------------------------------------------------------------------------------------
# Service : tendances (≤ 10 appels, cache 2 min, tolérance aux échecs)
# ---------------------------------------------------------------------------------------------
async def test_beacon_trends_limited_cached_and_tolerant():
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        if req.url.path.endswith("/13"):
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json=_load("pioupiou_archive_1708.json"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        ds = DataService(_settings(), client=c)
        ids = [f"pioupiou:{i}" for i in range(1, 16)] + ["fixture:b-forclaz", "ffvl:3"]
        out = await ds.beacon_trends(ids)
        assert len(calls) == MAX_TREND_CALLS  # jamais plus de 10 appels /v1/archive par requête
        assert all(p.startswith("/v1/archive/") for p in calls)
        assert set(out) == {f"pioupiou:{i}" for i in range(1, 11)}
        n = len(calls)
        again = await ds.beacon_trends(ids[:10])
        assert len(calls) == n and set(again) == set(out)  # cache 2 min


async def test_beacon_trends_failure_is_swallowed():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": True, "reason": "limit"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        ds = DataService(_settings("live"), client=c)
        assert await ds.beacon_trends(["pioupiou:1708"]) == {}
        ds_mock = DataService(_settings("mock"), client=c)
        assert await ds_mock.beacon_trends(["pioupiou:1708"]) == {}


# ---------------------------------------------------------------------------------------------
# Service : MNT des balises sans altitude (un seul appel groupé, cache 7 j)
# ---------------------------------------------------------------------------------------------
async def test_beacon_dem_single_grouped_call_cached():
    calls: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        q = parse_qs(urlparse(str(req.url)).query)
        calls.append(q)
        n = len(q["latitude"][0].split(","))
        return httpx.Response(200, json={"elevation": [450.0 + i for i in range(n)]})

    near = [_beacon(f"pioupiou:{i}", 45.79 + i * 0.001, 6.22) for i in range(5)]
    far = _beacon("pioupiou:99", 46.5, 7.5)
    known = _beacon("pioupiou:7", 45.79, 6.22, elevation_m=1250)
    site = type("S", (), {"lat": 45.789, "lon": 6.2225})()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        ds = DataService(_settings(), client=c)
        dem = await ds.beacon_dem([*near, far, known], [site])
        assert len(calls) == 1 and len(calls[0]["latitude"][0].split(",")) == 5  # balises proches seulement
        assert set(dem) == {b.id for b in near}  # balise lointaine et altitude connue : pas de MNT
        assert dem["pioupiou:0"] == 450.0
        await ds.beacon_dem(near, [site])
        assert len(calls) == 1  # cache 7 j


async def test_beacon_dem_unavailable_means_unknown_altitude():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": True, "reason": "Daily API request limit exceeded."})

    b = _beacon("pioupiou:1", 45.79, 6.22)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        for mode in ("auto", "live"):  # en live strict non plus, le calcul n'échoue pas
            assert await DataService(_settings(mode), client=c).beacon_dem([b]) == {}


async def test_beacon_dem_demo_beacons_use_simulated_dem():
    ds = DataService(_settings("mock"))
    try:
        fb = FixtureBeacons(SyntheticWeather())
        beacons, _ = fb.fetch_sync(datetime(2026, 10, 11, 10, 45, tzinfo=UTC))
        dem = await ds.beacon_dem(beacons)
    finally:
        await ds.aclose()
    assert dem["fixture:pioupiou-1720"] == fixture_beacon_dem()["fixture:pioupiou-1720"] == 455
    assert "fixture:pioupiou-1708" not in dem  # altitude connue (nom)


# ---------------------------------------------------------------------------------------------
# Attribution Pioupiou / OpenWindMap dans sources[]
# ---------------------------------------------------------------------------------------------
async def test_live_beacons_carry_openwindmap_attribution():
    def handler(req: httpx.Request) -> httpx.Response:
        if "pioupiou" in req.url.host:
            return httpx.Response(200, json=_load("pioupiou_live_all.json"))
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        ds = DataService(_settings(), client=c)
        bs, _ages, refs = await ds.beacons((6.0, 45.6, 6.5, 46.0), at=datetime.now(UTC))
    assert any(b.id == "pioupiou:1720" for b in bs)
    ref = next(r for r in refs if "OpenWindMap" in r.name)
    assert ref.mode == "live" and ref.url == "https://www.openwindmap.org"
    assert "(c) contributors of the OpenWindMap wind network" in ref.name


async def test_demo_beacons_attribution_and_real_pioupiou_positions():
    ds = DataService(_settings("mock"))
    try:
        bs, _, refs = await ds.beacons((6.0, 45.6, 6.5, 46.1), at=datetime(2026, 10, 11, 10, 45, tzinfo=UTC))
    finally:
        await ds.aclose()
    names = {b.name for b in bs}
    assert {"Atterrissage de Doussard", "Veyrier Club Nautique"} <= names
    assert any(n.startswith("Déco Anglettaz") for n in names)
    live = {b["id"]: b for b in _load("pioupiou_live_all.json")["data"] if b["id"] in (1720, 1708, 1476)}
    for b in bs:
        if b.id.startswith("fixture:pioupiou-"):
            raw = live[int(b.id.rsplit("-", 1)[1])]
            assert (b.lat, b.lon) == (raw["location"]["latitude"], raw["location"]["longitude"])
            assert b.trend is not None and b.trend.samples >= 4  # tendance simulée en démo
    assert any("OpenWindMap" in r.name and r.mode == "mock" for r in refs)


def test_trend_model_roundtrip():
    t = BeaconTrend(window_min=60, speed_change_kmh=10, direction_change_deg=-30, gust_max_kmh=None, samples=12)
    b = _beacon("x", 45, 6).model_copy(update={"trend": t})
    assert Beacon.model_validate(b.model_dump()).trend == t
