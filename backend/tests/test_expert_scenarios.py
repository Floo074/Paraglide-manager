"""Scénarios de validation métier de l'expert (docs/expert/scenarios-validation.yaml) + invariants §3.

Chaque scénario est exécuté par le vrai moteur via `app.engine.scenario.run_scenario` (sans réseau).
Blocs chargés : `scenarios` + `scenarios_phase2` (CDC §12 : horizon 15m, balises d'atterro, tendance, décollage libre
et atterros non officiels).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from app.engine import rules
from app.engine.scenario import build_context, run_scenario
from app.geo import angle_diff, bearing_deg
from app.meteo.solar import sunrise_sunset
from app.models import PlanResponse

ROOT = Path(__file__).resolve().parents[2]
YAML_PATH = ROOT / "docs" / "expert" / "scenarios-validation.yaml"
LEVELS = list(rules.LEVELS)


def _load() -> list[dict]:
    if not YAML_PATH.exists():  # pragma: no cover
        return []
    data = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
    return list(data["scenarios"]) + list(data.get("scenarios_phase2") or [])


SCENARIOS = _load()


def _param(sc: dict):
    return pytest.param(sc, id=sc["id"])


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _codes(res: PlanResponse) -> set[str]:
    codes: set[str] = set()
    if res.plans:
        codes |= {r.code for r in res.plans[0].risks}
    for rj in res.rejected:
        for reason in rj.reasons:
            if reason.startswith("["):
                codes.add(reason[1 : reason.index("]")])
    return codes


@pytest.fixture(scope="module")
def results() -> dict[str, PlanResponse | Exception]:
    out: dict[str, PlanResponse | Exception] = {}
    for sc in SCENARIOS:
        try:
            out[sc["id"]] = run_scenario(sc)
        except Exception as e:  # erreur du moteur : signalée par le test du scénario
            out[sc["id"]] = e
    return out


@pytest.mark.parametrize("sc", [_param(s) for s in SCENARIOS])
def test_scenario(sc: dict, results: dict[str, PlanResponse | Exception]) -> None:
    res = results[sc["id"]]
    if isinstance(res, Exception):
        raise res
    exp = sc["expect"]
    plans = res.plans
    best = plans[0] if plans else None
    fly = best.flyability if best else "no_go"
    assert fly == exp["flyability"], f"verdict {fly} ≠ {exp['flyability']} ; rejets={[r.reasons for r in res.rejected]}"
    codes = _codes(res)
    for c in exp.get("risk_codes", []):
        assert c in codes, f"code {c} absent ({sorted(codes)})"
    for c in exp.get("risk_codes_forbidden", []):
        for p in plans:
            # « ne doivent apparaître dans AUCUN plan » (YAML) : quel que soit le niveau, info compris (revue)
            assert not any(r.code == c for r in p.risks), f"{c} présent dans {p.title}"
    if "rejected_reason_contains" in exp:
        txt = " ".join(r for rj in res.rejected for r in rj.reasons).lower()
        assert exp["rejected_reason_contains"].lower() in txt
    if best is None:
        return
    lv = LEVELS.index
    if "difficulty_min" in exp:
        assert lv(best.difficulty) >= lv(exp["difficulty_min"])
    if "difficulty_max" in exp:
        assert lv(best.difficulty) <= lv(exp["difficulty_max"])
    if "flight_type" in exp:
        assert best.flight_type == exp["flight_type"]
    for ft in exp.get("flight_types_forbidden", []):
        assert all(p.flight_type != ft for p in plans)
    if "thermal_usage_in" in exp:
        assert best.thermal_usage in exp["thermal_usage_in"]
    if "min_duration_min" in exp:
        assert best.est_duration_min >= exp["min_duration_min"], best.est_duration_min
    if "max_duration_min" in exp:
        assert best.est_duration_min <= exp["max_duration_min"], best.est_duration_min
    if "max_altitude_m_max" in exp:
        assert all(p.max_altitude_m <= exp["max_altitude_m_max"] for p in plans)
    if "landing_before_utc" in exp:
        h, m = (int(x) for x in exp["landing_before_utc"].split(":"))
        for p in plans:
            land = _t(p.window.start) + timedelta(minutes=p.est_duration_min)
            limit = land.replace(hour=h, minute=m, second=0, microsecond=0)
            assert land <= limit + timedelta(minutes=1), f"atterrissage {land} > {limit}"
    if exp.get("landing_before_sunset"):
        for p in plans:
            land = _t(p.window.start) + timedelta(minutes=p.est_duration_min)
            _, sset = sunrise_sunset(land.date(), p.takeoff.lat, p.takeoff.lon)
            assert land <= sset
    if "confidence_max" in exp:
        assert best.confidence <= exp["confidence_max"]
    if "distance_km_min" in exp:
        assert best.distance_km >= exp["distance_km_min"]
    if "distance_km_max" in exp:
        assert best.distance_km <= exp["distance_km_max"]
    if "first_leg_upwind_of_deg" in exp:
        tp = next(w for w in best.waypoints if w.type == "turnpoint")
        brg = bearing_deg(best.takeoff.lat, best.takeoff.lon, tp.lat, tp.lon)
        assert angle_diff(brg, exp["first_leg_upwind_of_deg"]) <= 60, brg
    if exp.get("summary_explains_duration"):
        s = best.summary.lower()
        assert "plus court" in s or "seul" in s or "coucher" in s
    for cls in exp.get("no_route_intersects_classes", []):
        assert not any(a.intersects_route and a.airspace_class == cls for p in plans for a in p.airspaces)
    # --- phase 2 (CDC §12) -----------------------------------------------------------------------
    ldg_readings = [r for r in best.station_readings if r.site_role == "landing"]
    if "landing_beacon_representative" in exp:
        rep = [r for r in ldg_readings if r.representative]
        assert bool(rep) == exp["landing_beacon_representative"], [(r.beacon.name, r.comment) for r in ldg_readings]
    if "landing_beacon_weight_max" in exp:
        rep = [r for r in ldg_readings if r.representative]
        assert rep and all(r.weight <= exp["landing_beacon_weight_max"] + 1e-9 for r in rep), [r.weight for r in rep]
    if "landing_beacon_comment_contains" in exp:
        rep = [r for r in ldg_readings if r.representative]
        assert any(exp["landing_beacon_comment_contains"].lower() in r.comment.lower() for r in rep), [
            r.comment for r in rep
        ]
    if "landing_kind" in exp:
        kind = best.landing.landing_kind or ("official" if best.landing.official else None)
        assert kind == exp["landing_kind"], kind
    for k in exp.get("landing_kinds_forbidden", []):
        for p in plans:
            assert all(s.landing_kind != k for s in [p.landing, *p.alternate_landings]), p.title
    if "landing_warnings_contains" in exp:
        la = getattr(best, "landing_analysis", None) or []
        assert la and exp["landing_warnings_contains"].lower() in " ".join(la[0].warnings).lower()


# ---------------------------------------------------------------------------------------------
# Invariants globaux (scenarios-validation.md §3)
# ---------------------------------------------------------------------------------------------
def _all_plans(results):
    for sid, res in results.items():
        if isinstance(res, Exception):
            continue
        sc = next(s for s in SCENARIOS if s["id"] == sid)
        for p in res.plans:
            yield sc, res, p


def test_invariants(results: dict[str, PlanResponse]) -> None:
    for sc, res, p in _all_plans(results):
        f = sc["filters"]
        level = f["difficulty"]
        tag = f"{sc['id']} {p.title}"
        # I1 / I2
        assert not any(r.level == "danger" for r in p.risks), tag
        if p.flyability == "marginal":
            assert any(r.level == "caution" for r in p.risks), tag
        # I3
        if level == "beginner":
            assert p.flight_type != "cross_country", tag
            assert p.est_duration_min <= 45, tag
        # I4
        assert LEVELS.index(p.difficulty) <= LEVELS.index(level), tag
        site_lvl = p.takeoff.difficulty or "intermediate"
        assert LEVELS.index(p.difficulty) >= LEVELS.index(site_lvl), tag
        # I5
        land = _t(p.window.start) + timedelta(minutes=p.est_duration_min)
        if p.sun and p.sun.sunset:
            sset = _t(p.sun.sunset)
            assert land <= sset, tag
            if land > sset - timedelta(minutes=30):
                assert any(r.code == "SUNSET" for r in p.risks) and p.flyability != "go", tag
        # I6
        assert p.max_altitude_m <= 3405 + 1, tag
        # I7
        wing = f.get("wing_glide_ratio", 8.5)
        assert p.glide.margin_ok, tag
        if p.glide.required_ratio > 0:
            assert p.glide.available_ratio <= wing * 0.75 * (37 + 40) / 37, tag
        # I9
        # I10
        assert p.est_duration_min <= f["duration_max_minutes"] + 0.5, tag
        if p.est_duration_min < f["duration_min_minutes"]:
            assert p.summary, tag
        # I11
        if p.thermal_usage == "none" and p.flight_type != "ridge_soaring":
            drop = p.takeoff.elevation_m - p.landing.elevation_m
            assert p.est_duration_min <= drop / 1.0 / 60 + 5 + 0.5, tag
        # I12
        b0 = p.briefing[0]
        assert any(v in b0 for v in ("GO", "MARGINAL", "NO-GO")), tag
        assert any(lbl in b0 for lbl in rules.LEVEL_LABEL_FR.values()), tag
        txt = " ".join(p.briefing)
        assert "entre" in txt and "112" in txt and ("143,9875" in txt or "143.9875" in txt), tag
        assert p.landing.name in txt, tag
        # I13
        ck = " ".join(p.checklist).lower()
        for word in ("parachute de secours", "sellette", "mousquetons", "casque", "radio", "notam", "balises"):
            assert word in ck, (tag, word)
        # I14
        base = rules.HORIZON_BASE_CONFIDENCE[sc["horizon"]]
        assert p.confidence <= min(0.95, base * 1.1) + 1e-6, tag
        # I15
        if p.flight_type == "cross_country":
            assert p.distance_km <= rules.XC_MAX_DISTANCE_KM[level] + 0.1, tag
        # I20 (phase 2) : horizons ≤ 1 h, créneau borné (§12.5) et briefing[1] = lecture des balises
        if sc["horizon"] in rules.NOWCAST_WINDOW_START_MIN:
            lo, hi = rules.NOWCAST_WINDOW_START_MIN[sc["horizon"]]
            ref = _t(sc["reference_time"])
            target = _t(res.target_time)
            ws = _t(p.window.start)
            assert ws >= ref + timedelta(minutes=rules.NOWCAST_MIN_LEAD_MIN) - timedelta(seconds=1), tag
            assert target + timedelta(minutes=lo) - timedelta(seconds=1) <= ws <= target + timedelta(minutes=hi), tag
            assert p.briefing[1].startswith("Balises") or "Pas de balise" in p.briefing[1], (tag, p.briefing[1])
            assert any("manche à air" in x for x in p.checklist), tag
        # I21 (phase 2) : balise non représentative → poids nul ; poids ≤ beacon_weight_by_minutes(Δt)
        for r in p.station_readings:
            if not r.representative:
                assert r.weight == 0, (tag, r.beacon.name)
            assert r.weight <= rules.beacon_weight_by_minutes(0) + 1e-9, tag
            if r.site_role == "takeoff":
                dt = (_t(p.window.start) - _t(sc["reference_time"])).total_seconds() / 60
                assert r.weight <= rules.beacon_weight_by_minutes(dt) + 0.006, (tag, r.weight, dt)
    # I9 : au plus 2 plans par décollage
    for res in results.values():
        if isinstance(res, Exception):
            continue
        ids = [p.takeoff.id for p in res.plans]
        assert all(ids.count(i) <= 2 for i in ids)


def test_cross_first_leg_upwind(results: dict[str, PlanResponse]) -> None:
    """I15 : le premier segment d'un cross part face au vent moyen de la couche (± 60°) si ≥ 10 km/h."""
    for sc, _res, p in _all_plans(results):
        if p.flight_type != "cross_country":
            continue
        ctx, _ = build_context(sc)
        a = ctx.timelines[ctx.takeoffs[0].id].at(_t(p.window.start))
        v, d = a.profile.mean_wind(p.takeoff.elevation_m, p.max_altitude_m)
        if v < 10:
            continue
        tp = next(w for w in p.waypoints if w.type == "turnpoint")
        assert angle_diff(bearing_deg(p.takeoff.lat, p.takeoff.lon, tp.lat, tp.lon), d) <= 60
