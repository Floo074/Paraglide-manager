"""Atterros candidats (CDC §12.7) : usage par niveau, landing_policy, critères minimaux, marges de finesse renforcées,
score pondéré, avertissements, rejet expliqué ; mode classique (officiels seulement) ; adaptateur Overpass
(réponse fabriquée au format Overpass JSON) ; service (fixtures de démo, live sans Overpass, MNT du décollage
libre, quotas 429) ; API (POST /api/landings/analyze, POST /api/plans mode custom_takeoff)."""

from __future__ import annotations

import copy
import math
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from shapely.geometry import Point, Polygon

from app.config import Settings
from app.engine import rules
from app.engine.landings import (
    LandingSpot,
    compute_subscores,
    criteria_failures,
    evaluate_spot,
    explain_no_main,
    kind_use,
    select_landings,
    weighted_score,
)
from app.engine.routing import glide_to
from app.engine.scenario import build_context, run_scenario
from app.engine.terrain import TakeoffTerrain
from app.main import create_app
from app.models import PlanRequest, Site
from app.providers.base import ProviderDisabled
from app.providers.landing_spots import (
    OverpassLandings,
    build_spots,
    field_dimensions,
    fields_query,
    fixture_landing_spots,
    obstacles_query,
    parse_fields,
    parse_obstacles,
)
from app.services import DataService, quota_backoff_s

YAML_PATH = Path(__file__).resolve().parents[2] / "docs" / "expert" / "scenarios-validation.yaml"
DATA = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
ALL = {s["id"]: s for s in [*DATA["scenarios"], *DATA["scenarios_phase2"]]}
SITES = DATA["sites"]


def s32(**filters) -> dict:
    s = copy.deepcopy(ALL["S32"])
    s["filters"].update(filters)
    return s


def reasons(res) -> str:
    return " ".join(r for rj in res.rejected for r in rj.reasons)


def _site(sid: str, kind: str = "field", lat: float = 45.69, lon: float = 6.41, elev: float = 800.0) -> Site:
    return Site(id=sid, name=sid, kind="landing", lat=lat, lon=lon, elevation_m=elev, source="fixture",
                official=kind == "official", landing_kind=kind)  # fmt: skip


def _spot(kind: str = "field", **kw) -> LandingSpot:
    base = {"size": (170.0, 60.0), "slope_pct": 4.0, "community_usage": "unknown",
            "clearances": {"power_line": 160.0, "trees_buildings": 40.0, "water": 400.0, "road": 250.0}}  # fmt: skip
    base.update(kw)
    return LandingSpot(site=_site(f"x:{kind}", kind), kind=kind, **base)


# ---------------------------------------------------------------------------------------------
# Tables du §12.7
# ---------------------------------------------------------------------------------------------
def test_kind_use_table():
    assert kind_use("community", "beginner", "frequent") == "never"
    assert kind_use("community", "intermediate", "frequent") == "main"
    assert kind_use("community", "intermediate", "occasional") == "alternate"
    assert kind_use("community", "advanced", "unknown") == "main"
    assert kind_use("field", "beginner", "unknown") == "never"
    assert kind_use("field", "intermediate", "unknown") == "alternate"
    assert kind_use("field", "expert", "unknown") == "main_marginal"
    assert all(kind_use("official", lv, "unknown") == "main" for lv in rules.LEVELS)


def test_criteria_by_level():
    sp = _spot(size=(140.0, 45.0), slope_pct=9.0, clearances={"power_line": 120.0, "trees_buildings": 26.0,
                                                               "water": 60.0, "road": 35.0})  # fmt: skip
    f_int, _ = criteria_failures(sp, "intermediate", None)
    assert any("140 × 45" in f for f in f_int) and any("pente de 9 %" in f for f in f_int)
    assert any("ligne électrique à 120 m" in f for f in f_int) and any("eau à 60 m" in f for f in f_int)
    assert any("arbres / bâtiments à 26 m" in f for f in f_int)
    assert criteria_failures(sp, "advanced", None)[0] == []  # 120 × 40, 10 %, 100 / 25 / 50 m : tout passe
    assert criteria_failures(sp, "expert", None)[0] == []
    # route à moins de 30 m : exclu à tous les niveaux
    near_road = _spot(clearances={"road": 20.0})
    assert any("route à 20 m" in f for f in criteria_failures(near_road, "expert", None)[0])


def test_unknown_data_not_excluding_but_noted():
    sp = _spot(size=None, slope_pct=None, clearances={})
    fails, notes = criteria_failures(sp, "advanced", None)
    assert fails == []
    assert any("Taille non renseignée" in n for n in notes) and any("Pente non mesurée" in n for n in notes)


def test_approach_obstacle_final_and_useful_length():
    from app.engine.conditions import LandingWind
    from app.engine.landings import ApproachObstacle

    lw = LandingWind(datetime(2026, 9, 20, 10, tzinfo=UTC), 10.0, 30.0, 14.0, 1.0, None)  # vent de NNE
    tall = _spot(size=(200.0, 60.0), axis_deg=30.0, approach=[ApproachObstacle(210.0, 20.0, 60.0, "forêt")])
    assert any("dans l'axe de finale" in f for f in criteria_failures(tall, "expert", lw)[0])
    hedge = _spot(size=(160.0, 60.0), axis_deg=30.0, approach=[ApproachObstacle(210.0, 6.0, 0.0, "haie")])
    fails, _ = criteria_failures(hedge, "intermediate", lw)  # 160 − 5 × 6 = 130 < 150
    assert any("longueur utile 130 m" in f for f in fails)
    # vent du SSW : on approche par l'autre bout, la forêt ne gêne plus
    lw2 = LandingWind(lw.time, 10.0, 210.0, 14.0, 1.0, None)
    assert criteria_failures(tall, "expert", lw2)[0] == []
    # vent à 60° de l'axe du terrain : > 45°
    lw3 = LandingWind(lw.time, 10.0, 90.0, 14.0, 1.0, None)
    assert any("de l'axe du terrain" in f for f in criteria_failures(_spot(axis_deg=30.0), "expert", lw3)[0])


def test_glide_margins_by_kind():
    ctx, _ = build_context(s32())
    t = ctx.takeoffs[0]
    ldg = ctx.landings["scenario:cand1"]  # pré communautaire à 1,6 km, 800 m
    official = glide_to(ctx, t.lat, t.lon, t.elevation_m, ldg, "advanced", 8.5, (0.0, 0.0), kind="official")
    community = glide_to(ctx, t.lat, t.lon, t.elevation_m, ldg, "advanced", 8.5, (0.0, 0.0))
    field = glide_to(ctx, t.lat, t.lon, t.elevation_m, ldg, "advanced", 8.5, (0.0, 0.0), kind="field")
    assert community.available_ratio == pytest.approx(official.available_ratio * 0.90)
    assert field.available_ratio == pytest.approx(official.available_ratio * 0.80)
    d = 1600.0
    assert community.required_ratio == pytest.approx(d / (1500 - 800 - 120), rel=0.02)  # arrivée mini 120 m
    assert field.required_ratio == pytest.approx(d / (1500 - 800 - 150), rel=0.02)  # 150 m


def test_subscores_and_category_bonus():
    ctx, _ = build_context(s32())
    t = ctx.takeoffs[0]
    sp = ctx.landing_spots["scenario:cand1"]
    ev = evaluate_spot(ctx, t, sp, "advanced", 8.5, (8.0, 135.0), ctx.target_time, "include_community")
    s = ev.subscores
    assert s["community_usage"] == 80 and s["glide_margin"] == 100 and s["slope"] == 100
    assert s["obstacles"] == 100 and s["access"] == 100  # la route (50 m) compte pour l'accès, pas les obstacles
    assert s["size"] == pytest.approx(66.7, abs=0.1)  # 200 / 120 = 1,67 × la longueur mini (100 à 2 ×)
    assert ev.score == weighted_score(s, "community")
    # même terrain classé « officiel » : + 15 au lieu de + 5, plafonné à 100
    assert weighted_score(s, "official") == min(100, weighted_score(s, "community") + 10)
    assert ev.reasons[0].startswith("1,6 km, marge de finesse confortable")
    # obstacle non cartographié : sous-score 50 + avertissement
    sp2 = copy.deepcopy(sp)
    sp2.clearances.pop("power_line")
    ev2 = evaluate_spot(ctx, t, sp2, "advanced", 8.5, (8.0, 135.0), ctx.target_time, "include_community")
    assert ev2.subscores["obstacles"] == 50
    assert rules.UNOFFICIAL_WARNINGS["unknown_clearance"] in ev2.warnings
    assert compute_subscores(ev2, "advanced")["obstacles"] == 50


def test_mandatory_warnings_field_season():
    ctx, _ = build_context(s32(landing_policy="include_fields"))
    t = ctx.takeoffs[0]
    ev = evaluate_spot(ctx, t, ctx.landing_spots["scenario:cand2"], "advanced", 8.5, (8.0, 135.0), ctx.target_time,
                       "include_fields")  # fmt: skip
    w = " ".join(ev.warnings)
    assert rules.UNOFFICIAL_WARNINGS["field"] in w and rules.UNOFFICIAL_WARNINGS["field_season"] in w  # septembre
    assert "Ligne électrique à 160 m" in w  # < 2 × 100 m


# ---------------------------------------------------------------------------------------------
# landing_policy, niveau, choix du principal et rejet expliqué
# ---------------------------------------------------------------------------------------------
def test_policy_filters_first_then_level():
    ctx, _ = build_context(s32(landing_policy="include_fields"))
    sel = select_landings(ctx, ctx.takeoffs[0], "advanced", 8.5, "include_fields")
    assert sel.main.kind == "community" and [e.kind for e in sel.alternates] == ["field"]
    sel = select_landings(ctx, ctx.takeoffs[0], "advanced", 8.5, "include_community")
    assert sel.main.kind == "community" and sel.alternates == []
    sel = select_landings(ctx, ctx.takeoffs[0], "advanced", 8.5, "official_only")
    assert sel.main is None and "exclu par ta politique" in sel.reasons[0] and sel.reasons[0].startswith(
        "[UNOFFICIAL_LANDING]")
    sel = select_landings(ctx, ctx.takeoffs[0], "beginner", 8.5, "include_fields")
    assert sel.policy == "official_only" and rules.UNOFFICIAL_WARNINGS["beginner_policy"] in sel.warnings


def test_field_alone_is_main_for_advanced_but_marginal():
    sc = s32(landing_policy="include_fields")
    sc["landing_candidates"] = [c for c in sc["landing_candidates"] if c.get("landing_kind") != "community"]
    res = run_scenario(sc)
    p = res.plans[0]
    assert p.landing.landing_kind == "field" and p.flyability == "marginal"
    assert any(r.code == "DETECTED_FIELD" and r.level == "caution" for r in p.risks)
    assert p.difficulty in ("advanced", "expert")
    # brevet de pilote : un champ n'est jamais l'atterro principal
    sc["filters"]["difficulty"] = "intermediate"
    res = run_scenario(sc)
    assert not res.plans and "[DETECTED_FIELD] Seul un champ détecté" in reasons(res)


def test_community_occasional_is_only_alternate_for_intermediate():
    sc = s32(difficulty="intermediate")
    for c in sc["landing_candidates"]:
        if c.get("landing_kind") == "community":
            c["community_usage"] = "occasional"
    res = run_scenario(sc)
    assert not res.plans and "ne sert que de secours" in reasons(res)


def test_nothing_reachable_glide_margin():
    sc = s32()
    sc["landing_candidates"] = [sc["landing_candidates"][0]]  # officiel à 15 km
    res = run_scenario(sc)
    assert "[GLIDE_MARGIN] Aucun atterro à portée de plané avec la marge requise." in reasons(res)
    assert explain_no_main([], "expert", "include_fields")[0].startswith("[GLIDE_MARGIN]")


def test_excluded_by_criteria_named():
    sc = s32()
    for c in sc["landing_candidates"]:
        if c.get("landing_kind") == "community":
            c["slope_pct"] = 15
    res = run_scenario(sc)
    assert not res.plans
    assert "Meilleur candidat écarté : « Pré des parapentistes" in reasons(res) and "pente de 15 %" in reasons(res)


# ---------------------------------------------------------------------------------------------
# Mode classique : atterros officiels seulement, landing_analysis
# ---------------------------------------------------------------------------------------------
def test_classic_landing_analysis_official_first_is_landing():
    res = run_scenario(copy.deepcopy(ALL["S01"]))
    p = res.plans[0]
    assert p.landing_analysis and p.landing_analysis[0].site.id == p.landing.id
    assert all(la.kind == "official" for la in p.landing_analysis)
    assert p.landing_analysis[0].warnings == []


def test_classic_ignores_unofficial_landings():
    from app.engine.planner import evaluate_takeoff

    ctx, f = build_context(copy.deepcopy(ALL["S01"]))
    to = ctx.takeoffs[0]
    ldg = ctx.landings[to.associated_landing_ids[0]]
    ctx.landings[ldg.id] = ldg.model_copy(update={"official": False, "landing_kind": "community"})
    cands, why = evaluate_takeoff(ctx, to, f)
    assert not cands and "[UNOFFICIAL_LANDING]" in why[0] and "mode classique" in why[0]


def test_site_landing_kind_always_set():
    s = Site(id="a", name="a", kind="landing", lat=45, lon=6, elevation_m=400, source="paraglidingearth",
             official=False)  # fmt: skip
    assert s.landing_kind == "community"
    assert Site(id="b", name="b", kind="landing", lat=45, lon=6, elevation_m=400, source="fixture").landing_kind == (
        "official")
    assert Site(id="c", name="c", kind="takeoff", lat=45, lon=6, elevation_m=900, source="fixture").landing_kind is None


# ---------------------------------------------------------------------------------------------
# Overpass (réponse fabriquée au format JSON d'Overpass, `out geom`)
# ---------------------------------------------------------------------------------------------
LAT0, LON0 = 45.80, 6.23
KY = 111_320.0
KX = 111_320.0 * math.cos(math.radians(LAT0))


def _ll(x: float, y: float) -> dict:
    return {"lat": LAT0 + y / KY, "lon": LON0 + x / KX}


def _rect(x0, y0, x1, y1) -> list[dict]:
    return [_ll(x0, y0), _ll(x1, y0), _ll(x1, y1), _ll(x0, y1), _ll(x0, y0)]


def _overpass_fields() -> dict:
    return {"elements": [
        {"type": "way", "id": 1, "tags": {"landuse": "meadow", "name": "Pré du Lac"}, "geometry": _rect(0, 0, 80, 220)},
        {"type": "way", "id": 2, "tags": {"landuse": "farmland"}, "geometry": _rect(400, 0, 600, 30)},  # 200 × 30
        {"type": "way", "id": 3, "tags": {"landuse": "grass"}, "geometry": _rect(1000, 0, 1050, 50)},  # trop petit
        {"type": "way", "id": 4, "tags": {"natural": "grassland"}, "geometry": _rect(2000, 0, 2120, 160)},
        {"type": "node", "id": 9, **_ll(2060, 80), "tags": {"free_flying:site": "landing", "name": "Atterro club"}},
        {"type": "node", "id": 10, **_ll(5000, 5000), "tags": {"free_flying:site": "landing"}},
    ]}  # fmt: skip


def _overpass_obstacles() -> dict:
    return {"elements": [
        {"type": "way", "id": 20, "tags": {"power": "line"}, "geometry": [_ll(200, -100), _ll(200, 400)]},
        {"type": "way", "id": 21, "tags": {"landuse": "forest"}, "geometry": _rect(-50, 230, 130, 330)},
        {"type": "way", "id": 22, "tags": {"building": "yes"}, "geometry": _rect(-60, 50, -40, 70)},
        {"type": "way", "id": 23, "tags": {"waterway": "river"}, "geometry": [_ll(-150, -100), _ll(-150, 400)]},
        {"type": "way", "id": 24, "tags": {"highway": "track"}, "geometry": [_ll(90, -50), _ll(90, 300)]},
    ]}  # fmt: skip


def test_overpass_queries():
    q = fields_query((6.1, 45.7, 6.4, 45.9))
    assert "[out:json]" in q and 'landuse"~"^(meadow|grass|farmland)$"' in q and "45.70000,6.10000,45.90000" in q
    assert "free_flying:site" in q and q.endswith("out geom;")
    q2 = obstacles_query([1, 4])
    assert "way(id:1,4)->.f" in q2 and "around.f:300" in q2 and '"power"' in q2 and '"building"' in q2


def test_parse_fields_sizes_and_free_flying():
    fields, ff = parse_fields(_overpass_fields(), (LAT0, LON0))
    by_id = {f["way_id"]: f for f in fields}
    assert set(by_id) == {1, 2, 4}  # le pré de 50 × 50 m est écarté
    assert by_id[1]["length"] == pytest.approx(220, abs=3) and by_id[1]["width"] == pytest.approx(80, abs=2)
    assert by_id[1]["axis"] == pytest.approx(0, abs=1) or by_id[1]["axis"] == pytest.approx(180, abs=1)
    assert by_id[4]["free_flying"] and by_id[4]["name"] == "Atterro club"  # nœud vol libre dans le pré
    assert [f["id"] for f in ff] == ["osm:node/10"]
    assert by_id[2]["surface"].startswith("terre agricole")


def test_field_dimensions_irregular_shape_reduced():
    from shapely.geometry import Polygon

    l_shape = Polygon([(0, 0), (200, 0), (200, 40), (40, 40), (40, 200), (0, 200)])
    length, width, _ = field_dimensions(l_shape)
    assert length < 200 and width < 200  # taux de remplissage faible : dimensions réduites


def test_build_spots_clearances_and_approach():
    fields, ff = parse_fields(_overpass_fields(), (LAT0, LON0))
    obstacles = parse_obstacles(_overpass_obstacles(), (LAT0, LON0))
    spots = {s.site.id: s for s in build_spots(fields, ff, obstacles, (LAT0, LON0))}
    pre = spots["osm:way/1"]
    assert pre.kind == "field" and pre.site.source == "osm" and not pre.site.official
    assert pre.clearances["power_line"] == pytest.approx(120, abs=2)
    assert pre.clearances["trees_buildings"] == pytest.approx(10, abs=2)  # forêt à 10 m au nord
    assert pre.clearances["water"] == pytest.approx(150, abs=2)
    assert pre.clearances["road"] == pytest.approx(10, abs=2)  # chemin le long du pré
    assert any(o.label == "forêt" and o.height_m == 20 for o in pre.approach)
    assert spots["osm:way/4"].kind == "community"
    assert "power_line" not in spots["osm:way/2"].clearances or spots["osm:way/2"].clearances["power_line"] is not None
    assert spots["osm:node/10"].kind == "community" and spots["osm:node/10"].size is None


async def test_overpass_adapter_disabled_and_two_calls():
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        q = parse_qs(req.content.decode())["data"][0]
        calls.append(q)
        return httpx.Response(200, json=_overpass_obstacles() if "->.f" in q else _overpass_fields())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(ProviderDisabled):
            await OverpassLandings(c, "https://overpass-api.de/api/interpreter", enabled=False).fetch(
                (6.2, 45.79, 6.3, 45.82), (LAT0, LON0))
        assert calls == []
        spots = await OverpassLandings(c, "https://overpass-api.de/api/interpreter", enabled=True).fetch(
            (6.2, 45.79, 6.3, 45.82), (LAT0, LON0))
    assert len(calls) == 2 and "way(id:" in calls[1]
    assert {s.site.id for s in spots} >= {"osm:way/1", "osm:way/4", "osm:node/10"}


# ---------------------------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------------------------
def _settings(mode: str) -> Settings:
    return Settings(_env_file=None, data_mode=mode, openaip_api_key=None, ffvl_api_key=None)


def test_fixture_spots_are_demo_and_fictitious():
    spots = fixture_landing_spots()
    assert len(spots) >= 10 and all(s.demo and "démo" in s.site.name for s in spots)
    assert {s.kind for s in spots} == {"community", "field"}
    near_annecy = fixture_landing_spots((6.1, 45.7, 6.35, 45.9))
    assert len(near_annecy) >= 4


async def test_landing_spots_mock_live_without_overpass():
    ds = DataService(_settings("mock"))
    spots, refs, warns = await ds.landing_spots((6.1, 45.7, 6.35, 45.9), (45.8, 6.23), demo_context=False)
    assert spots and refs[0].mode == "mock" and "DÉMONSTRATION" in warns[0]
    calls: list = []
    transport = httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as c:
        live = DataService(_settings("live"), client=c)
        spots, refs, warns = await live.landing_spots((6.1, 45.7, 6.35, 45.9), (45.8, 6.23), demo_context=False)
        assert spots == [] and refs == [] and "Overpass" in warns[0] and calls == []  # jamais de terrain fictif
        st = {s.name: s for s in live.statuses()}
        assert st[live.states["overpass"].name].mode == "disabled"


async def test_takeoff_terrain_from_dem_two_grouped_calls():
    calls: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        q = parse_qs(urlparse(str(req.url)).query)
        lats = [float(x) for x in q["latitude"][0].split(",")]
        lons = [float(x) for x in q["longitude"][0].split(",")]
        calls.append(len(lats))
        kx = 111_320.0 * math.cos(math.radians(45.835))
        # pente de 45 % face à l'ouest (le terrain monte vers l'est)
        return httpx.Response(200, json={"elevation": [1000.0 + 0.45 * (lo - 6.23) * kx for lo in lons]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        ds = DataService(_settings("live"), client=c)
        t = await ds.takeoff_terrain(45.835, 6.23)
        assert calls[0] == 25 and len(calls) == 2 and t.source == "dem"  # grille, puis axes (points absents)
        assert t.slope_pct == pytest.approx(45, abs=1) and t.aspect_deg == 270 and t.profile_ok is True
        assert t.elevation_m == 1000
        n = len(calls)
        await ds.takeoff_terrain(45.835, 6.23)
        assert len(calls) == n  # cache 7 j

    def fail(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": True, "reason": "Daily API request limit exceeded."})

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as c:
        for mode in ("auto", "live"):  # jamais le MNT de démo pour un vol réel
            t = await DataService(_settings(mode), client=c).takeoff_terrain(45.835, 6.23)
            assert t.slope_pct is None and t.aspect_deg is None and t.source == "none"


async def test_quota_429_blocks_all_open_meteo_sources():
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(429, json={"error": True, "reason": "Daily API request limit exceeded."})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        ds = DataService(_settings("auto"), client=c)
        await ds.elevations([(45.8, 6.2)])
        assert len(calls) == 1
        for k in ("open-meteo", "open-meteo-15min", "open-meteo-elevation"):
            assert ds.states[k].blocked() and "00h00 UTC" in ds.states[k].blocked_reason
        start = datetime(2026, 10, 9, 6, tzinfo=UTC)
        fcs, _ = await ds.forecasts([(45.8, 6.2, 1000.0)], start, start, start)
        assert fcs[0].mode == "mock" and len(calls) == 1  # repli sans nouvel appel
        live = DataService(_settings("live"), client=c)
        live.states["open-meteo"].block(3600, "quota journalier atteint")
        with pytest.raises(Exception, match="quota journalier"):
            await live.forecasts([(45.8, 6.2, 1000.0)], start, start, start)
        assert len(calls) == 1


def test_quota_backoff_durations():
    now = datetime(2026, 10, 9, 22, 30, tzinfo=UTC)
    wait, why = quota_backoff_s("open-meteo", "HTTP 429 : Daily API request limit exceeded.", now, 120)
    assert wait == 3600 and "00h00 UTC" in why  # 1 h au plus entre deux essais
    late = datetime(2026, 10, 9, 23, 40, tzinfo=UTC)
    assert quota_backoff_s("open-meteo", "Daily API request limit exceeded", late, 120)[0] == pytest.approx(1260)
    wait, _ = quota_backoff_s("open-meteo", "HTTP 429 : Hourly API request limit exceeded.", now, 120)
    assert wait == pytest.approx(1800 + 30)
    wait, _ = quota_backoff_s("openaip", "HTTP 429 (quota / limitation de débit), réessayer dans 60 s", now, 120)
    assert wait == 300
    wait, _ = quota_backoff_s("pioupiou", "HTTP 429, réessayer dans 900 s", now, 120)
    assert wait == 900


async def test_sites_fallback_cached_briefly():
    transport = httpx.MockTransport(lambda r: httpx.Response(503))
    async with httpx.AsyncClient(transport=transport) as c:
        ds = DataService(_settings("auto"), client=c)
        await ds.sites((6.1, 45.7, 6.35, 45.9))
        import time

        expires, (sites, _, refs, _) = ds.sites_cache._data[("sites", "auto", (6.1, 45.7, 6.35, 45.9))]
        assert refs[0].mode == "mock" and sites  # repli sur les sites de démo…
        assert expires - time.monotonic() <= 600 + 1  # … gardé 10 min seulement, pas 24 h


# ---------------------------------------------------------------------------------------------
# API (mode démo)
# ---------------------------------------------------------------------------------------------
@pytest.fixture
def client(monkeypatch):
    async def steep(self, lat, lon, orientations=None):
        return TakeoffTerrain(elevation_m=1050, slope_pct=42, aspect_deg=285, profile_ok=True, axis_deg=285,
                              source="demo")  # fmt: skip

    monkeypatch.setattr(DataService, "takeoff_terrain", steep)
    app = create_app(Settings(_env_file=None, data_mode="mock", synthetic_scenario="thermal_good"))
    with TestClient(app) as c:
        yield c


def test_api_analyze_landings(client):
    r = client.post("/api/landings/analyze", json={
        "takeoff": {"lat": 45.835, "lon": 6.23}, "horizon": "24h", "reference_time": "2026-10-10T08:00:00Z",
        "difficulty": "advanced", "landing_policy": "include_fields"})  # fmt: skip
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["takeoff"]["source"] == "user" and d["takeoff"]["orientations"] == ["W", "WNW"]
    ring = d["glide_cone"]["coordinates"][0]
    assert d["glide_cone"]["type"] == "Polygon" and ring[0] == ring[-1] and len(ring) == 37
    # MNT de démonstration : le relief ne coupe pas le cône (contrat : MNT réel) ; les candidats atteignables y sont
    cone = Polygon([(x, y) for x, y in ring])
    assert cone.area > 0 and all(cone.contains(Point(c["site"]["lon"], c["site"]["lat"])) for c in d["candidates"])
    kinds = [c["kind"] for c in d["candidates"]]
    assert kinds and kinds[0] == "official" and "community" in kinds
    for c in d["candidates"]:
        assert 0 <= c["score"] <= 100 and c["reasons"]
        if c["kind"] != "official":
            assert any("Non officiel" in w for w in c["warnings"]) and any("DÉMONSTRATION" in w for w in c["warnings"])
    beg = client.post("/api/landings/analyze", json={
        "takeoff": {"lat": 45.835, "lon": 6.23}, "horizon": "24h", "reference_time": "2026-10-10T08:00:00Z",
        "difficulty": "beginner", "landing_policy": "include_fields"}).json()  # fmt: skip
    assert all(c["kind"] == "official" for c in beg["candidates"])
    assert rules.FREE_TAKEOFF["refusal_beginner"] in beg["warnings"]


def test_api_plans_custom_takeoff(client):
    body = {"zone": {"type": "circle", "center": {"lat": 45.835, "lon": 6.23}, "radius_km": 10}, "horizon": "24h",
            "reference_time": "2026-10-10T08:00:00Z", "mode": "custom_takeoff",
            "custom_takeoff": {"lat": 45.835, "lon": 6.23, "name": "Sous la Tournette"},
            "filters": {"duration_min_minutes": 10, "duration_max_minutes": 60, "difficulty": "advanced",
                        "thermals": "allowed", "landing_policy": "include_fields"}}  # fmt: skip
    r = client.post("/api/plans", json=body)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["plans"], d["rejected"]
    for p in d["plans"]:
        assert p["takeoff"]["name"] == "Sous la Tournette" and p["takeoff"]["source"] == "user"
        assert p["landing_analysis"][0]["site"]["id"] == p["landing"]["id"]
        assert any(r_["code"] == "FREE_TAKEOFF" for r_ in p["risks"])
        assert p["links"]["gpx"].startswith("/api/plans/")
        assert client.get(p["links"]["gpx"]).status_code == 200
    body["filters"]["difficulty"] = "beginner"
    d = client.post("/api/plans", json=body).json()
    assert not d["plans"] and "[FREE_TAKEOFF]" in " ".join(d["rejected"][0]["reasons"])
    body.pop("custom_takeoff")
    assert client.post("/api/plans", json=body).status_code == 422


def test_api_classic_mode_official_only(client):
    body = {"zone": {"type": "circle", "center": {"lat": 45.83, "lon": 6.23}, "radius_km": 10}, "horizon": "24h",
            "reference_time": "2026-10-10T08:00:00Z",
            "filters": {"duration_min_minutes": 10, "duration_max_minutes": 60, "difficulty": "intermediate",
                        "thermals": "allowed", "landing_policy": "include_fields"}}  # fmt: skip
    d = client.post("/api/plans", json=body).json()
    assert any("Mode classique" in w for w in d["warnings"])
    for p in d["plans"]:
        assert p["takeoff"]["official"] and p["landing"]["landing_kind"] == "official"
        assert all(a["landing_kind"] == "official" for a in p["alternate_landings"])
        assert p["landing_analysis"] and all(la["kind"] == "official" for la in p["landing_analysis"])


def test_plan_request_validation():
    base = {"zone": {"type": "circle", "center": {"lat": 45.8, "lon": 6.2}, "radius_km": 10}, "horizon": "2h",
            "filters": {"duration_min_minutes": 10, "duration_max_minutes": 60, "difficulty": "advanced",
                        "thermals": "allowed"}}  # fmt: skip
    assert PlanRequest(**base).mode == "classic"
    ct = {"lat": 45.8, "lon": 6.2, "orientations": ["so", "O"]}
    r = PlanRequest(**base, mode="custom_takeoff", custom_takeoff=ct)
    assert r.custom_takeoff.orientations == ["SW", "W"]
    with pytest.raises(ValueError):
        PlanRequest(**base, mode="custom_takeoff", custom_takeoff={"lat": 45.8, "lon": 6.2, "orientations": ["XX"]})
