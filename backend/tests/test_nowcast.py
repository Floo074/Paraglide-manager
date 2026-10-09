"""Nowcasting par balises (CDC §12.1-12.5) : horizon 15m, balises du déco (début du créneau) et des atterros
(heure d'ARRIVÉE), altitude inconnue (MNT), périmées / suspectes / isolées, tendance 1 h, StationReading,
briefing[1], pas de 15 min (Open-Meteo minutely_15), bout en bout en mode démo.

Les cas partent des scénarios S28-S30 du moniteur (scenarios-validation.yaml, bloc `scenarios_phase2`) et n'en
changent qu'un paramètre à la fois.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from app.config import Settings
from app.engine import rules
from app.engine.conditions import landing_wind
from app.engine.scenario import build_context, run_scenario
from app.engine.stations import site_attachments, station_nowcast
from app.main import create_app
from app.models import HORIZON_MINUTES, PlanRequest
from app.plan_service import round_target, trend_candidates
from app.providers.open_meteo_minutely import (
    build_minutely_params,
    minutely_window,
    parse_minutely_response,
    pick_model,
)
from app.services import DataService

YAML_PATH = Path(__file__).resolve().parents[2] / "docs" / "expert" / "scenarios-validation.yaml"
DATA = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
ALL = {s["id"]: s for s in [*DATA["scenarios"], *DATA["scenarios_phase2"]]}


def spec(sid: str, **changes) -> dict:
    s = copy.deepcopy(ALL[sid])
    s.update(changes)
    return s


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _arrival(p) -> datetime:
    return _t(p.window.start) + timedelta(minutes=p.est_duration_min)


def _dt(p, t: datetime, sc: dict) -> float:
    return (t - _t(sc["reference_time"])).total_seconds() / 60


def _readings(p, role: str):
    return [r for r in p.station_readings if r.site_role == role]


def _codes(res) -> dict[str, str]:
    out: dict[str, str] = {}
    if res.plans:
        out |= {r.code: r.level for r in res.plans[0].risks}
    for rj in res.rejected:
        for reason in rj.reasons:
            if reason.startswith("["):
                out.setdefault(reason[1 : reason.index("]")], "danger")
    return out


# ---------------------------------------------------------------------------------------------
# Horizon 15m, poids nominal, cible
# ---------------------------------------------------------------------------------------------
def test_horizon_15m_everywhere():
    assert HORIZON_MINUTES["15m"] == 15
    assert rules.HORIZON_BEACON_WEIGHT["15m"] == 0.85 and rules.HORIZON_BASE_CONFIDENCE["15m"] == 0.92
    req = PlanRequest.model_validate(
        {
            "zone": {"type": "circle", "center": {"lat": 45.82, "lon": 6.22}, "radius_km": 25},
            "horizon": "15m",
            "filters": {
                "duration_min_minutes": 15,
                "duration_max_minutes": 60,
                "difficulty": "intermediate",
                "thermals": "allowed",
            },
        }
    )
    assert req.horizon == "15m"


@pytest.mark.parametrize(
    ("dt", "w"), [(0, 0.90), (15, 0.85), (30, 0.70), (45, 0.60), (90, 0.40), (720, 0.0), (900, 0.0)]
)
def test_beacon_weight_by_minutes(dt, w):
    assert rules.beacon_weight_by_minutes(dt) == pytest.approx(w)


def test_target_rounded_to_15_min_for_short_horizons():
    t = datetime(2026, 10, 9, 12, 7, 31, tzinfo=UTC)
    assert round_target(t, "15m") == datetime(2026, 10, 9, 12, 15, tzinfo=UTC)
    assert round_target(t.replace(minute=51), "30m") == datetime(2026, 10, 9, 12, 45, tzinfo=UTC)
    assert round_target(t, "2h") == datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------------------------
# Atterro à l'heure d'arrivée (S28)
# ---------------------------------------------------------------------------------------------
def test_s28_landing_beacon_weighted_on_arrival_and_trend_extrapolated():
    sc = spec("S28")
    res = run_scenario(sc)
    p = res.plans[0]
    to, ldg = _readings(p, "takeoff"), _readings(p, "landing")
    assert to and to[0].representative and ldg and ldg[0].representative
    arr = _arrival(p)
    w_arr = rules.beacon_weight_by_minutes(_dt(p, arr, sc))
    assert ldg[0].weight <= w_arr + 0.006  # poids de l'atterro calculé sur l'heure d'ARRIVÉE
    assert ldg[0].weight < rules.beacon_weight_by_minutes(_dt(p, _t(p.window.start), sc))
    assert "Doussard atterro : 12 km/h" in ldg[0].comment and "il y a 3 min" in ldg[0].comment
    # vent retenu à l'arrivée = max(fusion, extrapolation 12 + 10 × Δt/60), le modèle seul donne ~5 km/h
    v_ext = 12 + min(15, 10 * min(_dt(p, arr, sc), 60) / 60)
    lw = p.weather.landing
    assert lw.wind_10m.speed_kmh == pytest.approx(v_ext, abs=0.6)
    assert lw.nowcast_correction is not None and lw.nowcast_correction.beacon_ids
    assert lw.nowcast_correction.wind_speed_bias_kmh > 5
    wi = next(r for r in p.risks if r.code == "WIND_INCREASING")
    assert wi.level == "caution" and "à l'atterro" in wi.title and "ton arrivée" in wi.detail
    assert p.flyability == "marginal"


def test_s28_intermediate_arrives_above_threshold():
    """§12.2 : brevet de pilote (seuils 20 / 25) → la valeur extrapolée à l'arrivée réelle fait le verdict."""
    sc = spec("S28")
    sc["filters"] = {**sc["filters"], "difficulty": "intermediate"}
    res = run_scenario(sc)
    for p in res.plans:
        assert p.weather.landing.wind_10m.speed_kmh <= rules.LANDING_WIND_MAX_KMH["intermediate"]
        assert p.flyability in ("marginal", "no_go")


def test_wind_increase_above_20_per_hour_is_no_go():
    sc = spec("S28")
    sc["beacons"][1]["trend"]["speed_change_kmh"] = 22  # r = 22 km/h/h > 20 : changement de régime
    sc["beacons"][1]["wind_speed_kmh"] = 12
    res = run_scenario(sc)
    assert not res.plans
    assert "WIND_INCREASING" in _codes(res)


@pytest.mark.parametrize(("change", "level", "expected"), [
    (70, "advanced", "caution"),   # rotation ≥ 60° : caution aux horizons 15m / 30m
    (150, "advanced", "caution"),  # bascule ≥ 120° : caution pour brevet confirmé
    (150, "intermediate", "danger"),  # … danger pour brevet de pilote
])  # fmt: skip
def test_wind_shift(change, level, expected):
    sc = spec("S28")
    sc["filters"] = {**sc["filters"], "difficulty": level}
    sc["beacons"][1]["trend"] = {"window_min": 60, "speed_change_kmh": 1, "direction_change_deg": change,
                                 "gust_max_kmh": 17, "samples": 12}  # fmt: skip
    res = run_scenario(sc)
    codes = _codes(res)
    assert codes.get("WIND_SHIFT") == expected
    if expected == "danger":
        assert not res.plans
    else:
        assert res.plans[0].flyability == "marginal"


def test_gust_max_of_the_hour_far_above_threshold_is_danger():
    sc = spec("S28")
    sc["beacons"][1]["trend"] = {
        "window_min": 60,
        "speed_change_kmh": 1,
        "direction_change_deg": 0,
        "gust_max_kmh": rules.LANDING_GUST_MAX_KMH["advanced"] + 12,
        "samples": 12,
    }
    res = run_scenario(sc)
    assert not res.plans and "LANDING_WIND" in _codes(res)


def test_trend_ignored_beyond_one_hour_window_rules():
    """Tendance trop courte (< 45 min ou < 4 mesures) : « tendance indisponible », aucune règle."""
    sc = spec("S28")
    sc["beacons"][1]["trend"] = {"window_min": 20, "speed_change_kmh": 10, "direction_change_deg": 0,
                                 "gust_max_kmh": 17, "samples": 4}  # fmt: skip
    res = run_scenario(sc)
    p = res.plans[0]
    assert "WIND_INCREASING" not in {r.code for r in p.risks if r.detail.startswith("Doussard")}
    assert "tendance indisponible" in _readings(p, "landing")[0].comment


# ---------------------------------------------------------------------------------------------
# Pas de balise représentative à l'atterro (S29), balise périmée, suspecte
# ---------------------------------------------------------------------------------------------
def test_s29_no_landing_beacon_non_blocking_and_confidence():
    res = run_scenario(spec("S29"))
    p = res.plans[0]
    nb = next(r for r in p.risks if r.code == "NO_LANDING_BEACON")
    assert nb.level == "caution" and p.flyability == "go"  # caution NON bloquante
    assert p.confidence == pytest.approx(0.92 * 1.1 * 0.9, abs=0.005)
    assert "Pas de balise à l'atterro" in p.briefing[1] and "confiance réduite" in p.briefing[1]
    assert any("manche à air" in c for c in p.checklist)


def test_no_landing_beacon_is_info_outside_breeze_hours():
    sc = spec("S29", reference_time="2026-10-10T07:45:00Z")  # arrivée vers 10 h légales
    sc["weather"] = {**sc["weather"], "convection": {"start": "07:30", "end": "14:30"}}
    res = run_scenario(sc)
    risks = {r.code: r.level for p in res.plans for r in p.risks}
    assert risks.get("NO_LANDING_BEACON") == "info"


def test_stale_landing_beacon_counts_as_absent():
    sc = spec("S28")
    sc["beacons"][1]["age_min"] = 47
    res = run_scenario(sc)
    p = res.plans[0]
    codes = {r.code: r.level for r in p.risks}
    assert codes.get("NO_LANDING_BEACON") == "caution" and codes.get("STALE_BEACONS") == "info"
    r = next(x for x in p.station_readings if x.beacon.name == "Doussard atterro")
    assert r.weight == 0 and not r.representative and "muette depuis 47 min" in r.comment


def test_suspect_beacon_has_zero_weight():
    sc = spec("S28")
    sc["weather"] = {
        **sc["weather"],
        "takeoff_wind_kmh": 14,
        "winds_aloft": {1550: [14, 280], 2000: [16, 270], 3000: [20, 260]},
    }
    sc["beacons"][0].update({"wind_speed_kmh": 0, "wind_gust_kmh": 0, "trend": None})
    ctx, _ = build_context(sc)
    site = ctx.takeoffs[0]
    att = next(
        a for a in site_attachments(ctx, site, "takeoff", ctx.timelines[site.id]) if a.beacon.name == "Balise Forclaz"
    )
    assert att.suspect and not att.representative and "suspecte" in (att.reason or "")


# ---------------------------------------------------------------------------------------------
# Altitude inconnue (S30), rattachement, isolée
# ---------------------------------------------------------------------------------------------
def test_s30_unknown_altitude_no_dem_name_bonus():
    res = run_scenario(spec("S30"))
    r = next(x for x in _readings(res.plans[0], "landing") if x.representative)
    assert r.weight <= 0.35 and "altitude inconnue" in r.comment and r.altitude_diff_m == 0


def test_unknown_altitude_with_dem_factor_08():
    sc = spec("S30")
    sc["beacons"][1]["dem_elevation_m"] = 455
    res = run_scenario(sc)
    p = res.plans[0]
    r = next(x for x in _readings(p, "landing") if x.representative)
    assert "altitude estimée (MNT)" in r.comment and r.altitude_diff_m == 5
    w_arr = rules.beacon_weight_by_minutes(_dt(p, _arrival(p), sc))
    assert r.weight == pytest.approx(w_arr * 0.8 * 1.0, abs=0.02)  # f_distance 1 (0,36 km), fraîcheur 1


def test_unknown_altitude_no_dem_without_name_bonus_not_representative():
    sc = spec("S30")
    sc["beacons"][1]["name"] = "Pioupiou 1234"
    res = run_scenario(sc)
    p = res.plans[0]
    assert not any(r.representative for r in _readings(p, "landing"))
    assert any(r.code == "NO_LANDING_BEACON" for r in p.risks)
    shown = [r for r in _readings(p, "landing") if r.beacon.name == "Pioupiou 1234"]
    assert shown and shown[0].weight == 0 and "non représentative" in shown[0].comment


def test_takeoff_beacon_400m_higher_is_synoptic_only():
    sc = spec("S29")
    sc["beacons"][0].update({"elevation_m": 1650, "name": "Balise crête"})
    ctx, _ = build_context(sc)
    site = ctx.takeoffs[0]
    att = site_attachments(ctx, site, "takeoff", ctx.timelines[site.id])[0]
    assert att.synoptic and att.f_altitude == rules.TAKEOFF_BEACON_ATTACH["alt_diff_m"]["factor_synoptic"]


def test_landing_named_beacon_not_used_at_takeoff():
    ctx, _ = build_context(spec("S28"))
    site = ctx.takeoffs[0]
    names = {a.beacon.name for a in site_attachments(ctx, site, "takeoff", ctx.timelines[site.id])}
    assert "Doussard atterro" not in names and "Balise Forclaz" in names


def test_outlier_beacon_factor_reduced():
    sc = spec("S29")
    b0 = sc["beacons"][0]
    sc["beacons"] = [
        b0,
        {**b0, "name": "Forclaz 2", "lat": 45.8130, "wind_speed_kmh": 12},
        {**b0, "name": "Forclaz 3", "lat": 45.8118, "wind_speed_kmh": 30, "wind_gust_kmh": 38},
    ]
    res = run_scenario(sc)
    plans_to = [r for p in res.plans for r in _readings(p, "takeoff") if r.beacon.name == "Forclaz 3"]
    assert plans_to and "possiblement abritée ou trop exposée" in plans_to[0].comment


# ---------------------------------------------------------------------------------------------
# Atterros de secours à l'heure d'arrivée
# ---------------------------------------------------------------------------------------------
def test_alternate_landing_readings():
    sc = spec("S28")
    sc["alternate_landings"] = [
        {"name": "Bout du Lac", "lat": 45.796, "lon": 6.214, "elevation_m": 450, "big_valley": True}
    ]
    sc["beacons"].append(
        {
            "name": "Bout du Lac atterro",
            "lat": 45.7965,
            "lon": 6.2145,
            "elevation_m": 452,
            "wind_speed_kmh": 10,
            "wind_gust_kmh": 14,
            "wind_direction_deg": 10,
            "age_min": 5,
        }
    )
    res = run_scenario(sc)
    p = res.plans[0]
    assert any(a.name == "Bout du Lac" for a in p.alternate_landings)
    alt = [r for r in _readings(p, "alternate_landing") if r.beacon.name == "Bout du Lac atterro"]
    assert alt and alt[0].representative and alt[0].site_id != p.landing.id
    assert alt[0].weight <= rules.beacon_weight_by_minutes(_dt(p, _arrival(p), sc)) + 0.006


# ---------------------------------------------------------------------------------------------
# Briefing : lecture des balises juste après le verdict (§12.5)
# ---------------------------------------------------------------------------------------------
def test_briefing_beacons_line_s28():
    p = run_scenario(spec("S28")).plans[0]
    b1 = p.briefing[1]
    assert b1.startswith("Balises (il y a 4 min)")
    assert "déco (Balise Forclaz) ONO 11 km/h (raf. 15), stable" in b1
    assert "atterro (Doussard atterro)" in b1 and "+10 km/h en 1 h, la brise forcit" in b1
    assert "attendus à ton arrivée" in b1


def test_briefing_without_any_beacon():
    sc = spec("S29", beacons=[])
    p = run_scenario(sc).plans[0]
    assert p.briefing[1].startswith("Pas de balise représentative au déco ni à l'atterro")
    assert "confiance réduite" in p.briefing[1]
    assert p.station_readings == []


def test_no_nowcast_beyond_2h():
    sc = spec("S28", horizon="8h", reference_time="2026-10-10T04:00:00Z")
    ctx, _ = build_context(sc)
    site = ctx.takeoffs[0]
    assert station_nowcast(ctx, site, "takeoff", ctx.timelines[site.id], ctx.target_time) is None
    res = run_scenario(sc)
    assert all(not p.station_readings for p in res.plans)


# ---------------------------------------------------------------------------------------------
# Tendance : seulement les balises Pioupiou des plans retenus (≤ 10)
# ---------------------------------------------------------------------------------------------
def test_trend_candidates_pioupiou_of_retained_plans_only():
    p = run_scenario(spec("S29")).plans[0]
    r0 = p.station_readings[0]
    readings = []
    for i in range(14):
        b = r0.beacon.model_copy(update={"id": f"pioupiou:{i}", "source": "pioupiou", "trend": None})
        readings.append(r0.model_copy(update={"beacon": b, "representative": i % 2 == 0}))
    stale = r0.beacon.model_copy(update={"id": "pioupiou:99", "source": "pioupiou", "stale": True, "trend": None})
    readings.append(r0.model_copy(update={"beacon": stale}))
    plan = p.model_copy(update={"station_readings": readings})
    ids = trend_candidates([plan])
    assert len(ids) == 10 and "pioupiou:99" not in ids
    assert set(ids[:7]) == {f"pioupiou:{i}" for i in range(0, 14, 2)}  # représentatives d'abord


# ---------------------------------------------------------------------------------------------
# Pas de 15 min (Open-Meteo minutely_15)
# ---------------------------------------------------------------------------------------------
def _minutely_payload(times: list[str], speeds: list[float | None], model: str | None = None) -> dict:
    sfx = f"_{model}" if model else ""
    return {
        "latitude": 45.79,
        "longitude": 6.22,
        "minutely_15_units": {
            "time": "iso8601",
            f"wind_speed_10m{sfx}": "km/h",
            f"wind_gusts_10m{sfx}": "km/h",
            f"wind_direction_10m{sfx}": "°",
        },
        "minutely_15": {
            "time": times,
            f"wind_speed_10m{sfx}": speeds,
            f"wind_direction_10m{sfx}": [0, 10, 20, 30][: len(times)],
            f"wind_gusts_10m{sfx}": [s + 5 if s is not None else None for s in speeds],
        },
    }


def test_minutely_parser_and_interpolation():
    times = ["2026-10-10T12:00", "2026-10-10T12:15", "2026-10-10T12:30", "2026-10-10T12:45"]
    data = [
        _minutely_payload(times, [4, 6, 10, None]),
        _minutely_payload(times, [1, 2, 3, 4], "meteofrance_arome_france_hd"),
    ]
    series = parse_minutely_response(data, 2, "meteofrance_arome_france_hd")
    assert len(series[0]) == 3 and len(series[1]) == 4  # pas null ignoré, suffixe de modèle accepté
    assert series[0][1] == (datetime(2026, 10, 10, 12, 15, tzinfo=UTC), 6.0, 10.0, 11.0)
    ctx, _ = build_context(spec("S29"))
    ltl = ctx.timelines[next(iter(ctx.landings))]
    ltl.minutely = series[0]
    v, d, g = ltl.wind10_at(datetime(2026, 10, 10, 12, 25, tzinfo=UTC))
    assert v == pytest.approx(6 + 4 * 10 / 15) and 10 < d < 20 and g == pytest.approx(v + 5)
    assert ltl.wind10_at(datetime(2026, 10, 10, 13, 30, tzinfo=UTC)) is None  # hors série : heure la plus proche
    # landing_wind : vent 10 m au pas de 15 min × brise
    lw = landing_wind(ltl, datetime(2026, 10, 10, 12, 15, tzinfo=UTC), True)
    assert lw.model_speed_kmh == pytest.approx(6 * lw.breeze_factor)


def test_minutely_params_and_model_choice():
    start, end = minutely_window(datetime(2026, 10, 10, 11, 47, tzinfo=UTC), 15, 45)
    p = build_minutely_params([(45.79, 6.22, 450.0)], "meteofrance_arome_france_hd", start, end)
    assert p["minutely_15"] == "wind_speed_10m,wind_direction_10m,wind_gusts_10m"
    assert p["start_minutely_15"] == "2026-10-10T11:45" and p["elevation"] == "450"
    assert pick_model(["icon_d2", "meteofrance_arome_france_hd"]) == "meteofrance_arome_france_hd"


async def test_minutely_service_one_call_and_tolerant():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(parse_qs(urlparse(str(req.url)).query))
        if len(calls) > 1:
            return httpx.Response(429, json={"error": True, "reason": "Daily API request limit exceeded."})
        times = ["2026-10-10T12:00", "2026-10-10T12:15"]
        return httpx.Response(200, json=[_minutely_payload(times, [4, 6]), _minutely_payload(times, [5, 7])])

    pts = [(45.79, 6.22, 450.0), (45.85, 6.21, 450.0)]
    s0, s1 = datetime(2026, 10, 10, 12, tzinfo=UTC), datetime(2026, 10, 10, 13, tzinfo=UTC)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        ds = DataService(Settings(data_mode="live", openaip_api_key=None), client=c)
        series, refs = await ds.minutely_winds(pts, s0, s1)
        assert len(calls) == 1 and "minutely_15" in calls[0] and [len(x) for x in series] == [2, 2]
        assert refs and refs[0].mode == "live"
        series2, _ = await ds.minutely_winds(pts, s0, s1)
        assert len(calls) == 1 and series2 == series  # cache
        empty, refs3 = await ds.minutely_winds(pts, s0, s1 + timedelta(hours=1))  # 429 en live : pas d'exception
        assert empty == [[], []] and refs3 == []


# ---------------------------------------------------------------------------------------------
# Bout en bout (mode démo) : POST /api/plans 15m et 30m sur Annecy
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("horizon", "ref", "target"), [
    ("15m", "2026-10-11T10:47:00Z", "2026-10-11T11:00:00Z"),
    ("30m", "2026-10-11T10:30:00Z", "2026-10-11T11:00:00Z"),
])  # fmt: skip
def test_api_short_horizon_mock(horizon, ref, target):
    body = {"zone": {"type": "circle", "center": {"lat": 45.82, "lon": 6.22}, "radius_km": 25}, "horizon": horizon,
            "reference_time": ref, "filters": {"duration_min_minutes": 15, "duration_max_minutes": 90,
                                               "difficulty": "intermediate", "thermals": "allowed"}}  # fmt: skip
    with TestClient(create_app(Settings(data_mode="mock", openaip_api_key=None))) as c:
        r = c.post("/api/plans", json=body)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["horizon"] == horizon and d["target_time"] == target
    assert d["plans"]
    for p in d["plans"]:
        assert p["station_readings"], p["title"]
        assert p["briefing"][1].startswith("Balises") or p["briefing"][1].startswith("Pas de balise")
        lo, hi = rules.NOWCAST_WINDOW_START_MIN[horizon]
        ws = _t(p["window"]["start"])
        assert _t(target) + timedelta(minutes=lo) <= ws <= _t(target) + timedelta(minutes=hi)
        assert ws >= _t(ref) + timedelta(minutes=rules.NOWCAST_MIN_LEAD_MIN)
        for sr in p["station_readings"]:
            assert sr["site_role"] in ("takeoff", "landing", "alternate_landing")
            assert sr["comment"].startswith(sr["beacon"]["name"])
            assert (sr["weight"] > 0) == sr["representative"]
        assert any("OpenWindMap" in s["name"] for s in p["sources"])
    names = {sr["beacon"]["name"] for p in d["plans"] for sr in p["station_readings"]}
    assert "Atterrissage de Doussard" in names


async def test_plan_service_fetches_trends_for_retained_plans_and_reevaluates(monkeypatch):
    """Tendance (archive Pioupiou) demandée pour les balises des plans retenus seulement, puis réévaluation :
    la tendance change le vent retenu, les risques et le verdict ; attribution de l'historique dans sources[]."""
    from app.models import BeaconTrend, PlanRequest
    from app.plan_service import PlanService

    ds = DataService(Settings(data_mode="mock", openaip_api_key=None))
    orig_beacons = ds.beacons

    async def beacons_as_pioupiou(bbox, at=None):
        bs, ages, refs = await orig_beacons(bbox, at=at)
        conv = [b.model_copy(update={"id": b.id.replace("fixture:", "pioupiou:"), "source": "pioupiou", "trend": None})
                for b in bs]  # fmt: skip
        return conv, {k.replace("fixture:", "pioupiou:"): v for k, v in ages.items()}, refs

    asked: list[list[str]] = []

    async def fake_trends(ids):
        asked.append(list(ids))
        up = BeaconTrend(window_min=60, speed_change_kmh=8, direction_change_deg=0, gust_max_kmh=None, samples=12)
        return {i: up for i in ids}

    monkeypatch.setattr(ds, "beacons", beacons_as_pioupiou)
    monkeypatch.setattr(ds, "beacon_trends", fake_trends)
    req = PlanRequest.model_validate(
        {
            "zone": {"type": "circle", "center": {"lat": 45.82, "lon": 6.22}, "radius_km": 25},
            "horizon": "15m",
            "reference_time": "2026-10-11T10:45:00Z",
            "filters": {
                "duration_min_minutes": 15,
                "duration_max_minutes": 90,
                "difficulty": "intermediate",
                "thermals": "allowed",
            },
        }
    )
    try:
        res = await PlanService(ds, 600).create(req)
    finally:
        await ds.aclose()
    assert len(asked) == 1 and 0 < len(asked[0]) <= 10 and all(i.startswith("pioupiou:") for i in asked[0])
    used = {sr.beacon.id for p in res.plans for sr in p.station_readings if sr.beacon.trend is not None}
    assert used and used <= set(asked[0])
    assert any("historique 1 h" in s.name for s in res.plans[0].sources)
    assert any(sr.beacon.trend and "+8 km/h en 1 h" in sr.comment for p in res.plans for sr in p.station_readings
               if sr.representative)  # fmt: skip


def test_role_names_crest_variant_and_shared_village_name():
    """« Crêt du Loup » = sommet (mauvais rôle pour un atterro) ; le nom du village commun au déco et à l'atterro
    (« La Clusaz ») ne donne pas de bonus de nom (cas réel Pioupiou « Crêt du Loup, La Clusaz »)."""
    from app.engine.stations import attach, name_has_keyword

    assert name_has_keyword("Crêt du Loup, La Clusaz", rules.LANDING_BEACON_ATTACH["wrong_role"]["keywords"])
    assert not name_has_keyword("Crêtes de Doussard", ["col"]) and not name_has_keyword("Colombier", ["col"])
    sc = spec("S30")
    sc["takeoff"] = {**sc["takeoff"], "name": "La Clusaz - Crêt du Loup"}
    sc["landing"] = {**sc["landing"], "name": "Atterro de La Clusaz"}
    ctx, _ = build_context(sc)
    site_to, site_ldg = ctx.takeoffs[0], next(iter(ctx.landings.values()))
    b = ctx.beacons[1].model_copy(update={"name": "Pioupiou La Clusaz"})
    assert not attach(ctx, b, site_ldg, "landing").name_bonus  # « Clusaz » est aussi dans le nom du déco
    b2 = ctx.beacons[0].model_copy(update={"name": "Crêt du Loup, La Clusaz"})
    assert attach(ctx, b2, site_to, "takeoff").name_bonus  # « Crêt », « Loup » : propres au déco
    at = attach(
        ctx, b2.model_copy(update={"lat": site_ldg.lat, "lon": site_ldg.lon, "elevation_m": None}), site_ldg, "landing"
    )
    assert not at.attached and "sommet" in (at.reason or "")
