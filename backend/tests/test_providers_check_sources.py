"""app.check_sources rejoué hors ligne : vraies réponses enregistrées servies par httpx.MockTransport."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest

from app.check_sources import format_table, run_checks, save_fixtures
from app.config import Settings

FIX = Path(__file__).parent / "fixtures"
DUMMY_KEY = "cle-de-test-0123456789"  # jamais la vraie clé dans les tests
PGE_PATH = "/api/geojson/getBoundingBoxSites.php"


def _routes(overrides: dict | None = None):
    routes = {
        ("api.open-meteo.com", "/v1/forecast"): (200, "open_meteo_forclaz_3models.json"),
        ("api.open-meteo.com", "/v1/elevation"): (200, "open_meteo_elevation_forclaz_doussard.json"),
        ("www.paraglidingearth.com", PGE_PATH): (200, "paraglidingearth_bbox_annecy.json"),
        ("api.pioupiou.fr", "/v1/live/all"): (200, "pioupiou_live_all.json"),
        ("api.core.openaip.net", "/api/airspaces"): (200, "openaip_airspaces_annecy_full.json"),
        ("biodiv-sports.fr", "/api/v2/sensitivearea_practice/"): (200, "biodivsports_practices_fr.json"),
        ("biodiv-sports.fr", "/api/v2/sensitivearea/"): (200, "biodivsports_sensitivearea_annecy_bbox.json"),
    }
    routes.update(overrides or {})
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        u = urlparse(str(req.url))
        status, name = routes[(u.netloc, u.path)]
        return httpx.Response(status, content=(FIX / name).read_bytes(), headers={"content-type": "application/json"})

    return handler, seen


@pytest.fixture()
def settings(tmp_path) -> Settings:
    return Settings(_env_file=None, openaip_api_key=DUMMY_KEY, airspace_openair_dir=tmp_path / "openair")


async def test_all_sources_ok_on_recorded_responses(settings, tmp_path):
    handler, seen = _routes()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        res = await run_checks(settings, c, openaip_guard=tmp_path / "guard")
    by = {r.key: r for r in res}
    assert [r.key for r in res] == [
        "open-meteo", "open-meteo-elevation", "paraglidingearth", "pioupiou", "openaip", "openair", "biodivsports",
    ]  # fmt: skip
    assert {k: r.status for k, r in by.items()} == {
        "open-meteo": "OK", "open-meteo-elevation": "OK", "paraglidingearth": "OK", "pioupiou": "OK",
        "openaip": "OK", "openair": "DÉSACTIVÉ", "biodivsports": "OK",
    }  # fmt: skip
    assert by["open-meteo"].count == 67 + 67 + 72
    assert "icon_d2 67 h/9 niv." in by["open-meteo"].detail
    assert by["open-meteo-elevation"].detail == "Forclaz 1244 m, Doussard 463 m"
    assert by["paraglidingearth"].count == 14 and by["paraglidingearth"].detail.startswith("10 décos, 4 atterros")
    assert by["openaip"].count == 23 and by["openaip"].detail.startswith("clé configurée")
    assert by["biodivsports"].count == 17 and by["biodivsports"].http == "200+200"
    assert not any(r.failed for r in res)
    assert by["openair"].expected is False
    # la clé n'apparaît nulle part dans le rapport
    table = format_table(res)
    assert DUMMY_KEY not in table and "OpenAIP" in table
    openaip_req = next(r for r in seen if r.url.host == "api.core.openaip.net")
    assert DUMMY_KEY not in str(openaip_req.url)


async def test_failure_is_reported_with_http_code_and_exit_flag(settings, tmp_path):
    handler, _ = _routes({("api.open-meteo.com", "/v1/forecast"): (429, "open_meteo_429.json")})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        res = await run_checks(settings, c, only=["open-meteo"], openaip_guard=tmp_path / "guard")
    [r] = res
    assert (r.status, r.http, r.failed) == ("ÉCHEC", "429", True)
    assert "HTTP 429" in r.detail and "Daily API request limit exceeded" in r.detail


async def test_openaip_guard_prevents_second_call_within_5_min(settings, tmp_path):
    guard = tmp_path / "guard"
    handler, seen = _routes()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        first = await run_checks(settings, c, only=["openaip"], openaip_guard=guard)
        second = await run_checks(settings, c, only=["openaip"], openaip_guard=guard)
    assert first[0].status == "OK"
    assert second[0].status == "IGNORÉ" and second[0].expected is False and not second[0].failed
    assert sum(1 for r in seen if r.url.host == "api.core.openaip.net") == 1


async def test_openaip_without_key_is_disabled_not_failed(tmp_path):
    s = Settings(_env_file=None, openaip_api_key=None, airspace_openair_dir=tmp_path)
    handler, seen = _routes()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        [r] = await run_checks(s, c, only=["openaip"], openaip_guard=tmp_path / "guard")
    assert (r.status, r.failed) == ("DÉSACTIVÉ", False) and not seen


async def test_save_fixtures_masks_secrets(settings, tmp_path):
    handler, _ = _routes()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        res = await run_checks(settings, c, only=["open-meteo-elevation", "biodivsports"], openaip_guard=None)
    res[0].responses[0]._content = json.dumps({"elevation": [1.0], "echo": DUMMY_KEY}).encode()
    out = save_fixtures(res, tmp_path / "out", [DUMMY_KEY])
    assert sorted(p.name for p in out) == ["biodivsports_1.json", "biodivsports_2.json", "open_meteo_elevation.json"]
    assert all(DUMMY_KEY not in p.read_text(encoding="utf-8") for p in out)
