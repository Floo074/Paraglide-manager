"""Décollage libre (CDC §12.6) : pente et exposition au MNT, orientations 16 points, profil dans l'axe, cône de
finesse, seuils de vent propres au décollage libre, niveaux autorisés, difficulté du plan, briefing et checklist.

Les cas moteur partent du scénario S32 du moniteur (scenarios-validation.yaml, bloc `scenarios_phase2`) et n'en
changent qu'un paramètre à la fois.
"""

from __future__ import annotations

import copy
import math
from pathlib import Path

import pytest
import yaml

from app.engine import rules
from app.engine.scenario import run_scenario
from app.engine.terrain import (
    analyze_grid,
    axis_from_orientations,
    axis_profile,
    dem_grid_points,
    downslope_slope_pct,
    glide_cone,
    orientations_from_aspect,
    plane_fit,
    profile_distances,
    slope_distances,
)
from app.geo import bearing_deg, haversine_km

YAML_PATH = Path(__file__).resolve().parents[2] / "docs" / "expert" / "scenarios-validation.yaml"
DATA = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
ALL = {s["id"]: s for s in [*DATA["scenarios"], *DATA["scenarios_phase2"]]}
LEVELS = list(rules.LEVELS)


def s32(**changes) -> dict:
    s = copy.deepcopy(ALL["S32"])
    for k, v in changes.items():
        if k == "filters":
            s["filters"].update(v)
        elif k == "custom_takeoff":
            s["custom_takeoff"].update(v)
        else:
            s[k] = v
    return s


def with_takeoff_wind(spec: dict, speed: float, direction: float, gust: float | None = None) -> dict:
    """Vent au déco (10 m et niveau 1500 m = altitude du déco, d'où le vent est interpolé)."""
    w = copy.deepcopy(spec["weather"])
    w["takeoff_wind_kmh"], w["takeoff_wind_dir"] = speed, direction
    w["takeoff_gust_kmh"] = gust if gust is not None else speed + 4
    w["winds_aloft"] = {**w["winds_aloft"], 1500: [speed, direction]}
    spec["weather"] = w
    return spec


def codes(res) -> dict[str, str]:
    out: dict[str, str] = {}
    if res.plans:
        out.update({r.code: r.level for r in res.plans[0].risks})
    for rj in res.rejected:
        for reason in rj.reasons:
            if reason.startswith("["):
                out.setdefault(reason[1 : reason.index("]")], "rejet")
    return out


def reasons(res) -> str:
    return " ".join(r for rj in res.rejected for r in rj.reasons)


# ---------------------------------------------------------------------------------------------
# MNT : pente, exposition, orientations, profil
# ---------------------------------------------------------------------------------------------
def _grid_values(lat: float, lon: float, f) -> list[float]:
    """Altitudes d'une grille dem_grid_points calculées par f(x_est_m, y_nord_m)."""
    out = []
    ky = 111_320.0
    kx = 111_320.0 * math.cos(math.radians(lat))
    for la, lo in dem_grid_points(lat, lon):
        out.append(f((lo - lon) * kx, (la - lat) * ky))
    return out


@pytest.mark.parametrize(("aspect", "slope"), [(270.0, 40.0), (135.0, 30.0), (0.0, 55.0), (200.0, 18.0)])
def test_plane_slope_and_aspect(aspect: float, slope: float):
    # pente qui descend vers `aspect` : z diminue dans cette direction
    ux, uy = math.sin(math.radians(aspect)), math.cos(math.radians(aspect))
    z = _grid_values(45.8, 6.2, lambda x, y: 1000.0 - slope / 100.0 * (x * ux + y * uy))
    s, a = analyze_grid(z)
    assert s == pytest.approx(slope, abs=0.5)
    assert min(abs(a - aspect), 360 - abs(a - aspect)) < 1.0


def test_grid_is_5x5_100m_and_center_first_flat_fallback():
    pts = dem_grid_points(45.8, 6.2)
    assert len(pts) == 25 and pts[12] == (45.8, 6.2)
    assert haversine_km(*pts[12], *pts[13]) * 1000 == pytest.approx(100, abs=1)
    assert bearing_deg(*pts[12], *pts[13]) == pytest.approx(90, abs=0.5)  # ouest → est
    assert bearing_deg(*pts[12], *pts[17]) == pytest.approx(0, abs=0.5)  # sud → nord
    # centre plat (< 5 %) : le plan de la grille entière donne l'exposition
    z = _grid_values(45.8, 6.2, lambda x, y: 1000.0 + (0.0 if abs(x) < 150 and abs(y) < 150 else -0.3 * x))
    a, b = plane_fit(z, 5, 100.0, inner=3)
    assert math.hypot(a, b) < 0.05
    assert analyze_grid(z)[1] == pytest.approx(90, abs=10)


def test_orientations_from_aspect_16_points():
    assert orientations_from_aspect(135) == ["ESE", "SE", "SSE"]  # bornes ± 22,5° comprises
    assert orientations_from_aspect(140) == ["SE", "SSE"]
    assert orientations_from_aspect(355) == ["N", "NNW"]
    assert axis_from_orientations(["ESE", "SE", "SSE"]) == pytest.approx(135, abs=0.01)


def test_downslope_slope_and_axis_profile():
    ds, dp = slope_distances(), profile_distances()
    assert ds == [50, 100, 150] and dp == [50, 100, 150, 200, 250, 300]
    assert downslope_slope_pct(1500, [1480, 1460, 1440], ds) == pytest.approx(40)
    ok, detail = axis_profile(1500, [1480, 1460, 1440, 1420, 1400, 1380], dp)
    assert ok and detail is None
    # bosse à 150 m : 1500 − 150/6 = 1475 < 1490
    ok, detail = axis_profile(1500, [1480, 1470, 1490, 1420, 1400, 1380], dp)
    assert not ok and "150 m" in detail and "15 m" in detail


# ---------------------------------------------------------------------------------------------
# Cône de finesse
# ---------------------------------------------------------------------------------------------
def test_glide_cone_flat_no_wind_is_a_circle():
    ring = glide_cone(45.7, 6.4, 1500.0, lambda _b: 5.0, None, 100.0, 500.0)
    assert ring[0] == ring[-1] and len(ring) == 37
    radii = [haversine_km(45.7, 6.4, la, lo) for lo, la in ring[:-1]]
    assert all(r == pytest.approx((1500 - 500 - 100) * 5 / 1000, rel=0.01) for r in radii)


def test_glide_cone_shifted_downwind():
    from app.engine.routing import finesse_sol

    wind = (20.0, 270.0)  # vent d'ouest : on va plus loin vers l'est
    ring = glide_cone(45.7, 6.4, 1500.0, lambda b: finesse_sol(8.5, "intermediate", *wind, b), None, 100.0, 500.0)
    by_brg = {round(bearing_deg(45.7, 6.4, la, lo)) % 360: haversine_km(45.7, 6.4, la, lo) for lo, la in ring[:-1]}
    assert by_brg[90] > 1.5 * by_brg[270]
    assert by_brg[0] == pytest.approx(by_brg[180], rel=0.02)


def test_glide_cone_cut_by_relief():
    # crête de 1400 m à 2 km à l'est du point : le plané vers l'est s'arrête avant, l'ouest reste ouvert
    def terrain(lat, lon):
        x = (lon - 6.4) * 111.32 * math.cos(math.radians(45.7))
        return 1400.0 if 1.8 < x < 2.4 else 500.0

    ring = glide_cone(45.7, 6.4, 1500.0, lambda _b: 6.0, terrain, 100.0, 500.0)
    by_brg = {round(bearing_deg(45.7, 6.4, la, lo)) % 360: haversine_km(45.7, 6.4, la, lo) for lo, la in ring[:-1]}
    assert by_brg[90] < 1.9
    assert by_brg[270] == pytest.approx((1500 - 500 - 100) * 6 / 1000, abs=0.3)


# ---------------------------------------------------------------------------------------------
# Moteur : niveaux, pente, vent (à partir de S32)
# ---------------------------------------------------------------------------------------------
def test_s32_reference_plan():
    res = run_scenario(s32())
    p = res.plans[0]
    assert p.flyability == "go" and p.takeoff.source == "user" and not p.takeoff.official
    assert p.difficulty == "intermediate"  # décollage libre = site de niveau intermediate
    c = codes(res)
    assert c["FREE_TAKEOFF"] == "info" and c["UNOFFICIAL_LANDING"] == "info"
    # glide.available_ratio inclut le facteur f = 0,90 de l'atterro communautaire
    la = p.landing_analysis[0]
    assert la.site.id == p.landing.id and la.kind == "community"
    assert p.glide.available_ratio == pytest.approx(la.available_glide_ratio, abs=0.05)
    assert p.glide.available_ratio < 8.5 * 0.72 * 0.9 + 1e-6
    # briefing : avertissement en tête du bloc Décollage, contrôles obligatoires ; checklist
    txt = " ".join(p.briefing)
    assert rules.FREE_TAKEOFF["warning"] in txt and "Contrôles obligatoires" in txt and "Non officiel" in txt
    assert p.checklist[0].startswith("Décollage libre — Autorisation du propriétaire")
    assert sum("Décollage libre —" in x for x in p.checklist) == 6
    assert "Décollage libre hors site officiel" in p.summary


def test_beginner_never_free_takeoff_and_all_reasons_listed():
    res = run_scenario(s32(filters={"difficulty": "beginner"}))
    assert not res.plans
    txt = reasons(res)
    assert rules.FREE_TAKEOFF["refusal_beginner"] in txt
    # seul un atterro communautaire à portée (le champ est exclu par la politique, l'officiel hors de portée)
    assert "[UNOFFICIAL_LANDING] Seul un atterro communautaire est à portée : non proposé à un élève." in txt


def test_intermediate_free_takeoff_is_at_best_marginal():
    res = run_scenario(s32(filters={"difficulty": "intermediate"}))
    p = res.plans[0]
    assert p.flyability == "marginal"
    c = codes(res)
    assert c["FREE_TAKEOFF"] == "caution" and c["UNOFFICIAL_LANDING"] == "caution"


def test_slope_too_steep_for_level():
    res = run_scenario(s32(custom_takeoff={"slope_pct": 75}))  # max 70 % confirmé, 80 % expert
    assert not res.plans and "trop raide" in reasons(res) and "OK pour pilote cross" in reasons(res)
    res = run_scenario(s32(custom_takeoff={"slope_pct": 75}, filters={"difficulty": "expert"}))
    assert res.plans and res.plans[0].difficulty == "expert"


def test_slope_too_gentle_depends_on_headwind():
    res = run_scenario(s32(custom_takeoff={"slope_pct": 20}))  # 8 km/h de face < 10 : 25 % requis
    assert not res.plans and "pente trop faible pour décoller" in reasons(res)
    sc = with_takeoff_wind(s32(custom_takeoff={"slope_pct": 20}), 12, 135, 15)  # 12 km/h de face : 15 % suffit
    res = run_scenario(sc)
    assert res.plans, reasons(res)


def test_tailwind_forbidden_from_3_kmh():
    res = run_scenario(with_takeoff_wind(s32(), 4, 315, 6))  # 4 km/h de dos (vent de NW, pente SE)
    assert not res.plans and "[TAILWIND]" in reasons(res) and "dès 3 km/h" in reasons(res)


def test_wind_slope_angle_without_sector_tolerance():
    # 35° hors de l'exposition (135°) : > 30° (confirmé) mais ≤ 45° (expert) ; un déco officiel orienté
    # ESE/SE/SSE l'aurait accepté (tolérance de ± 11,25° autour de SSE)
    sc = with_takeoff_wind(s32(), 9, 170, 12)
    res = run_scenario(sc)
    assert not res.plans and "[CROSSWIND]" in reasons(res)
    sc["filters"]["difficulty"] = "expert"
    assert run_scenario(sc).plans


def test_free_takeoff_wind_thresholds_lower_than_official():
    # 18 km/h de face : sous le seuil officiel confirmé (25) et sous celui du décollage libre (20) mais dans la
    # bande 80-100 % → caution, au mieux marginal ; 22 km/h → no-go pour un confirmé (OK expert)
    res = run_scenario(with_takeoff_wind(s32(), 17, 135, 21))
    p = res.plans[0]
    assert p.flyability == "marginal" and codes(res).get("TAKEOFF_WIND") == "caution"
    res = run_scenario(with_takeoff_wind(s32(), 22, 135, 26))
    assert not res.plans and "[TAKEOFF_WIND]" in reasons(res)


def test_unmeasured_slope_caution_and_missing_orientation():
    res = run_scenario(s32(custom_takeoff={"slope_pct": None}))
    assert res.plans and res.plans[0].flyability == "marginal"
    assert any(r.code == "FREE_TAKEOFF" and "Pente non mesurée" in r.detail for r in res.plans[0].risks)
    res = run_scenario(s32(custom_takeoff={"orientations": [], "aspect_deg": None}))
    assert not res.plans and "Orientation du déco inconnue" in reasons(res)


def test_invariants_free_takeoff_plans():
    for lv in ("intermediate", "advanced", "expert"):
        res = run_scenario(s32(filters={"difficulty": lv, "landing_policy": "include_fields"}))
        for p in res.plans:
            assert LEVELS.index(p.difficulty) >= LEVELS.index("intermediate")
            for s in [p.landing, *p.alternate_landings]:
                assert s.landing_kind is not None
            for la in p.landing_analysis:  # I19 : « Non officiel » dans les warnings de tout atterro non officiel
                if la.kind != "official":
                    assert any("Non officiel" in w for w in la.warnings)
            if lv == "intermediate":
                assert p.landing.landing_kind != "field"
