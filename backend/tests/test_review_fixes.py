"""Non-régression des constats de la revue finale (docs/expert/revue-backend.md, lot 7, 09/10/2026).

Chaque test reprend la requête (mock) ou le scénario hors ligne cité en preuve dans le constat.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.config import Settings
from app.engine import rules
from app.engine.landings import LandingEval, LandingSpot, capped_score, compute_subscores, reasons_for
from app.engine.routing import GlideCheck
from app.engine.scenario import run_scenario
from app.main import create_app
from app.models import Site

YAML_PATH = Path(__file__).resolve().parents[2] / "docs" / "expert" / "scenarios-validation.yaml"
ZONES = {"annecy": (45.82, 6.22), "chamonix": (45.93, 6.87), "sthilaire": (45.31, 5.89), "standre": (43.97, 6.51)}


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app(Settings(_env_file=None, data_mode="mock"))) as c:
        yield c


def plans(client, zone: str, horizon: str, ref: str, level: str, thermals: str, dmin: float, dmax: float, **filters):
    lat, lon = ZONES[zone]
    body = {
        "zone": {"type": "circle", "center": {"lat": lat, "lon": lon}, "radius_km": 25},
        "horizon": horizon,
        "reference_time": ref,
        "filters": {"duration_min_minutes": dmin, "duration_max_minutes": dmax, "difficulty": level,
                    "thermals": thermals, **filters},
    }  # fmt: skip
    r = client.post("/api/plans", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def scenario(sid: str, patch: dict | None = None) -> dict:
    data = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
    scs = {s["id"]: s for s in list(data["scenarios"]) + list(data.get("scenarios_phase2") or [])}
    sc = copy.deepcopy(scs[sid])

    def merge(a: dict, b: dict) -> None:
        for k, v in b.items():
            if isinstance(v, dict) and isinstance(a.get(k), dict):
                merge(a[k], v)
            else:
                a[k] = v

    merge(sc, patch or {})
    return sc


def check_window(p: dict) -> None:
    """Invariants du créneau (revue 7.2, 7.6) : window.end + durée ≤ latest_landing ≤ coucher − 30 min ; entre
    coucher − 30 min et le coucher seulement avec la caution SUNSET et un verdict qui n'est pas GO (§3 #11)."""
    w = p["window"]
    start, end, latest = _t(w["start"]), _t(w["end"]), _t(w["latest_landing"])
    dur = timedelta(minutes=p["est_duration_min"])
    assert start <= end, w
    assert end + dur <= latest + timedelta(minutes=1), (p["title"], w, p["est_duration_min"])
    if p["sun"]["sunset"]:
        sunset = _t(p["sun"]["sunset"])
        assert latest <= sunset, (p["title"], w)
        if latest > sunset - timedelta(minutes=rules.LANDING_BEFORE_SUNSET_MIN) + timedelta(minutes=1):
            assert end == start, (p["title"], w)  # pas de créneau au-delà de coucher − 30 min − durée
            assert p["flyability"] != "go" and any(r["code"] == "SUNSET" for r in p["risks"]), (p["title"], w)


# ---------------------------------------------------------------------------------------------
# 7.1 (B) : atterros hors de portée publiés comme secours
# ---------------------------------------------------------------------------------------------
def test_7_1_alternates_always_reachable(client):
    j = plans(client, "annecy", "24h", "2026-10-14T09:00:00Z", "intermediate", "allowed", 15, 30)
    assert j["plans"]
    for p in j["plans"]:
        alt_names = {a["name"] for a in p["alternate_landings"]}
        la = p["landing_analysis"]
        # les secours publiés sont dans l'analyse, atteignables (r ≤ 1, arrivée au-dessus du sol)
        for c in la[1:]:
            assert c["required_glide_ratio"] <= c["available_glide_ratio"], c
            assert c["arrival_height_m"] > 0, c
            assert not any("hors de portée" in r for r in c["reasons"]), c
        assert alt_names <= {c["site"]["name"] for c in la}
        wp_alt = {w["name"] for w in p["waypoints"] if w["type"] == "alternate_landing"}
        assert wp_alt == alt_names
        sec = next(b for b in p["briefing"] if b.startswith("Atterrissage"))
        if "secours : " in sec:
            listed = sec.split("secours : ", 1)[1]
            assert all(n in alt_names for n in alt_names if n in listed)
            assert not any(c["site"]["name"] in listed for c in la if c["site"]["name"] not in alt_names
                           and c["site"]["id"] != p["landing"]["id"])  # fmt: skip
        if p["takeoff"]["name"].startswith("Planfait"):
            # Montmin village (derrière la crête de Lanfon), Doussard et Saint-Jorioz sont hors de portée du plouf
            assert not alt_names & {"Montmin village", "Doussard (atterrissage officiel)", "Saint-Jorioz"}
            assert "secours" not in sec


def _ev(ratio: float, wind_sub: float = 100.0) -> LandingEval:
    site = Site(id="x", name="X", kind="landing", lat=45.8, lon=6.2, elevation_m=450, source="fixture")
    g = GlideCheck(required_ratio=ratio * 6.0, available_ratio=6.0, margin_ok=ratio <= 1.0)
    ev = LandingEval(spot=LandingSpot(site=site, kind="official"), distance_km=8.4, bearing_deg=180.0,
                     reachable=ratio <= 1.0, std_glide=g, glide=g, arrival_height_m=-587.0, wind=None, use="main",
                     policy_ok=True)  # fmt: skip
    ev.subscores = compute_subscores(ev, "intermediate")
    ev.subscores["wind_at_arrival"] = wind_sub
    return ev


def test_7_1_phrase_and_capped_score():
    ev = _ev(2.0)
    assert ev.subscores["glide_margin"] == 0.0
    # score plafonné à 40 + min(finesse, vent d'arrivée) : un terrain hors de portée ne dépasse jamais 40
    assert capped_score(ev.subscores, "official") <= rules.SAFETY_CAP_OFFSET
    assert "hors de portée (finesse requise 12,0 pour 6,0)" in reasons_for(ev)[0]
    ok = _ev(0.6)
    assert "marge de finesse confortable" in reasons_for(ok)[0]


# ---------------------------------------------------------------------------------------------
# 7.12 (M) : atterro officiel au vent d'arrivée hors niveau, proposé comme utilisable
# ---------------------------------------------------------------------------------------------
def test_7_12_landing_wind_over_level_is_excluded_from_analysis(client):
    body = {"takeoff": {"lat": 45.755, "lon": 6.245}, "horizon": "24h", "reference_time": "2026-10-14T12:00:00Z",
            "difficulty": "intermediate", "landing_policy": "include_fields"}  # fmt: skip
    r = client.post("/api/landings/analyze", json=body)
    assert r.status_code == 200, r.text
    j = r.json()
    lim_w, lim_g = rules.LANDING_WIND_MAX_KMH["intermediate"], rules.LANDING_GUST_MAX_KMH["intermediate"]
    for c in j["candidates"]:
        w = c["wind_at_arrival"]
        assert w is None or (w["speed_kmh"] <= lim_w and w["gust_kmh"] <= lim_g), c
    assert not any(c["site"]["name"].startswith("Doussard") for c in j["candidates"])
    assert any("Doussard" in w and f"(seuils {lim_w} / {lim_g})" in w for w in j["warnings"])


# ---------------------------------------------------------------------------------------------
# 7.2 (B) : surdéveloppement « moderate » : vol à l'heure du surdéveloppement, ou après
# ---------------------------------------------------------------------------------------------
S22_MODERATE = {
    "reference_time": "2026-07-24T11:00:00Z",
    "weather": {"hourly": {str(h): {"cape_j_kg": c, "lifted_index": -1, "precipitation_mm_h": 0}
                           for h, c in ((10, 450), (11, 550), (12, 650), (13, 700), (14, 700), (15, 700), (16, 700))}},
}  # fmt: skip


def test_7_2_moderate_overdevelopment_before_flight_is_rejected():
    res = run_scenario(scenario("S22", S22_MODERATE))
    assert not res.plans
    reasons = [r for rj in res.rejected for r in rj.reasons]
    assert any(r.startswith("[OVERDEVELOPMENT] Surdéveloppement possible vers") and "plus de créneau" in r
               for r in reasons), reasons  # fmt: skip


def test_7_2_window_never_ends_after_latest_landing(client):
    j = plans(client, "chamonix", "24h", "2026-10-20T11:00:00Z", "expert", "allowed", 120, 300)
    for p in j["plans"]:
        check_window(p)
        assert not any("surdéveloppement" in b and "13h16" in b for b in p["briefing"])
    # S22 d'origine (surdév 14Z, vol du matin) reste marginal, posé avant 13:00Z
    res = run_scenario(scenario("S22"))
    assert res.plans and res.plans[0].flyability == "marginal"
    assert _t(res.plans[0].window.latest_landing) <= _t("2026-07-25T13:00:00Z")


# ---------------------------------------------------------------------------------------------
# 7.3 (B) : orientations ParaglidingEarth « tous secteurs » ou incohérentes
# ---------------------------------------------------------------------------------------------
ALL16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


@pytest.mark.parametrize("sid", ["S04", "S18"])
def test_7_3_all_sectors_without_dem_is_not_proposed(sid):
    res = run_scenario(scenario(sid, {"takeoff": {"orientations": ALL16}}))
    assert not res.plans
    reasons = [r for rj in res.rejected for r in rj.reasons]
    assert any("Orientation du déco incertaine" in r and "MNT indisponible" in r for r in reasons), reasons


def test_7_3_all_sectors_with_dem_uses_exposure():
    # Forclaz : exposition MNT ouest → W ± 22,5° ; S04 (dévent d'ESE) et S18 (vent arrière) restent no_go
    res = run_scenario(scenario("S04", {"takeoff": {"orientations": ALL16, "dem_aspect_deg": 280}}))
    assert not res.plans
    assert any("[LEE_SIDE]" in r for rj in res.rejected for r in rj.reasons)
    res = run_scenario(scenario("S18", {"takeoff": {"orientations": ALL16, "dem_aspect_deg": 280}}))
    assert not res.plans
    assert any("[TAILWIND]" in r for rj in res.rejected for r in rj.reasons)
    # un cas volable garde la caution « vérifie sur place » (jamais GO)
    ok = run_scenario(scenario("S01", {"takeoff": {"orientations": ALL16, "dem_aspect_deg": 285}}))
    for p in ok.plans:
        assert p.flyability != "go"
        r = next(r for r in p.risks if r.code == "TAKEOFF_WIND")
        assert r.level == "caution" and "Orientation du déco incertaine" in r.detail and "vérifie sur place" in r.detail


def test_7_3_pge_sectors_rules():
    from app.providers.sites import parse_pge, pge_orientations

    allrated = {s: "1" for s in ("N", "NE", "E", "SE", "S", "SW", "W", "NW")}
    assert pge_orientations(allrated) == ALL16
    # (b) ≥ 6 secteurs notés dont 2 « bons » : les secteurs notés 2 sont retenus
    assert pge_orientations({**allrated, "S": "2", "SW": "2"}) == ["S", "SSW", "SW"]
    # < 6 secteurs notés : inchangé (Forclaz : W noté 1 = axe principal)
    assert pge_orientations({"N": "2", "NW": "2", "W": "1"}) == ["N", "W", "WNW", "NW", "NNW"]
    feat = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [6.8, 45.9]},
            "properties": {"name": "Plaine Joux", "pge_site_id": "3021", "takeoff_altitude": "1350", "paragliding": "1",
                           **allrated}}  # fmt: skip
    _, meta = parse_pge({"type": "FeatureCollection", "features": [feat]})
    assert meta["pge:3021"].orientation_uncertain and "8 secteurs notés sur 8" in meta["pge:3021"].orientation_note


def test_7_3_filter_by_dem_exposure():
    from app.engine.terrain import aspect_from_cross, filter_by_aspect

    # Plan Praz noté ['NE', 'S'] ; pente orientée sud : le NE (vent arrière) est écarté
    assert filter_by_aspect(["NE", "S"], 180.0) == ["S"]
    # N, S, E, O : la pente descend vers le sud (N haut, S bas) → exposition 180°
    slope, aspect = aspect_from_cross([2100.0, 1900.0, 2000.0, 2000.0])
    assert round(aspect) == 180 and slope > 60


def _pge_feature(pid: str, lat: float, lon: float, alt: str, **sectors) -> dict:
    return {"type": "Feature", "id": pid, "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"name": f"Déco {pid}", "pge_site_id": pid, "takeoff_altitude": alt, "paragliding": "1",
                           **sectors}}  # fmt: skip


def _dem_handler(features: list[dict], dem, om_status: int = 200):
    """Transport httpx : ParaglidingEarth renvoie `features`, Open-Meteo Elevation `dem(lat, lon)`."""
    import json

    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        if "paraglidingearth" in request.url.host:
            return httpx.Response(200, json={"type": "FeatureCollection", "features": features})
        if "open-meteo" in request.url.host and "elevation" in request.url.path:
            if om_status != 200:
                return httpx.Response(om_status, text=json.dumps({"error": True, "reason": "Daily API request limit "
                                                                                           "exceeded"}))
            lats = [float(x) for x in request.url.params["latitude"].split(",")]
            lons = [float(x) for x in request.url.params["longitude"].split(",")]
            return httpx.Response(200, json={"elevation": [dem(a, b) for a, b in zip(lats, lons, strict=True)]})
        return httpx.Response(404)

    return handler


async def test_7_3_live_sites_orientation_from_dem():
    import httpx

    from app.services import DataService

    def dem(lat: float, lon: float) -> float:  # pente orientée sud (le terrain monte vers le nord), 60 %
        return 2000.0 + (lat - 45.93) * 111_320.0 * 0.6

    feats = [_pge_feature("100", 45.93, 6.85, "2000", NE="1", S="2"),  # Plan Praz noté NE + S
             _pge_feature("101", 45.93, 6.95, "2000", **{s: "1" for s in ("N", "NE", "E", "SE", "S", "SW", "W", "NW")})]
    settings = Settings(_env_file=None, data_mode="live", openaip_api_key=None, ffvl_api_key=None)
    async with httpx.AsyncClient(transport=httpx.MockTransport(_dem_handler(feats, dem))) as c:
        ds = DataService(settings, client=c)
        sites, meta, _, _ = await ds.sites((6.8, 45.9, 7.0, 45.96))
    by = {s.id: s for s in sites}
    assert by["pge:100"].orientations == ["S"]  # NE à plus de 90° de l'exposition : écarté
    assert by["pge:101"].orientations == ["SSE", "S", "SSW"]  # tous secteurs → exposition MNT ± 22,5°
    assert meta["pge:101"].orientation_uncertain and round(meta["pge:101"].dem_aspect_deg) == 180


# ---------------------------------------------------------------------------------------------
# B5 : en DATA_MODE=auto, MNT synthétique jamais utilisé comme altitude d'un site ou d'une prévision réelle
# ---------------------------------------------------------------------------------------------
async def test_b5_auto_mode_never_invents_site_elevation():
    import time

    import httpx

    from app.services import DataService

    feats = [_pge_feature("999", 45.85, 6.25, "0", W="2"), _pge_feature("998", 45.86, 6.26, "1300", W="2")]
    settings = Settings(_env_file=None, data_mode="auto", openaip_api_key=None, ffvl_api_key=None)
    async with httpx.AsyncClient(transport=httpx.MockTransport(_dem_handler(feats, None, om_status=429))) as c:
        ds = DataService(settings, client=c)
        bbox = (6.2, 45.8, 6.3, 45.9)
        sites, _, refs, warnings = await ds.sites(bbox)
    ids = {s.id for s in sites}
    assert "pge:999" not in ids and "pge:998" in ids  # sans altitude → écarté ; altitude de la source gardée
    assert refs[0].mode == "live"
    assert any(w.startswith("MNT indisponible") and "1 site(s) sans altitude" in w for w in warnings)
    expires, _ = ds.sites_cache._data[("sites", "auto", tuple(round(x, 2) for x in bbox))]
    assert expires - time.monotonic() <= 600 + 1


def test_b5_forecast_point_without_real_dem_sends_no_elevation(monkeypatch):
    from app.services import DataService

    seen: list = []

    async def fake_elev(self, points):
        return [(150.0, "mock") for _ in points]  # repli : MNT de démonstration

    orig = DataService.forecasts

    async def spy(self, points, *a, **kw):
        seen.extend(points)
        return await orig(self, points, *a, **kw)

    monkeypatch.setattr(DataService, "elevations_detailed", fake_elev)
    monkeypatch.setattr(DataService, "forecasts", spy)
    with TestClient(create_app(Settings(_env_file=None, data_mode="auto", openaip_api_key=None))) as c:
        # Open-Meteo injoignable en test : repli synthétique, mais l'altitude demandée n'est jamais celle du MNT démo
        monkeypatch.setattr(c.app.state.data, "_try_live", _none_live)
        c.get("/api/forecast/point", params={"lat": 45.83, "lon": 6.22, "time": "2026-10-10T08:00:00Z"})
    assert seen and all(p[2] is None for p in seen)


async def _none_live(*a, **kw):
    return None


# ---------------------------------------------------------------------------------------------
# 7.4 (B) : zones où le parapente est interdit (Biodiv'Sports), survol réglementé, LOW_OVERFLIGHT
# ---------------------------------------------------------------------------------------------
FIX = Path(__file__).resolve().parent / "fixtures"


def _bout_du_lac():
    import json

    from app.providers.sensitive import parse_biodivsports

    areas, _ = parse_biodivsports(json.loads((FIX / "biodivsports_sensitivearea_annecy.json").read_text()), [3])
    return next(a for a in areas if "Bout du Lac" in a.name)


def test_7_4_biodivsports_paragliding_forbidden_detected():
    from app.providers.sensitive import text_prohibits_flight

    a = _bout_du_lac()
    assert a.flight_prohibited and a.min_height_agl_m is None
    assert text_prohibits_flight("Réserve naturelle nationale des Aiguilles Rouges : Parapente et autres sports "
                                 "aériens interdits dans la zone")  # fmt: skip
    assert text_prohibits_flight("Vol libre interdit.") and text_prohibits_flight("Survol interdit")
    assert not text_prohibits_flight("Survol interdit à moins de 300 m/sol")  # hauteur : zone réglementée
    assert not text_prohibits_flight("Chiens interdits dans la zone")


def _s01_bout_du_lac(**over) -> dict:
    a = _bout_du_lac()
    poly = [list(c) for c in a.geometry.exterior.coords]
    zone = {"name": a.name, "kind": "regulatory", "polygon": poly, "flight_prohibited": True, **over}
    return scenario("S01", {"landing": {"lat": 45.7820, "lon": 6.2224}, "sensitive_areas": [zone]})


def test_7_4_route_goes_around_prohibited_reserve():
    from shapely.geometry import LineString

    a = _bout_du_lac()
    sc = _s01_bout_du_lac()
    res = run_scenario(sc)
    assert res.plans, [r.reasons for r in res.rejected]
    for p in res.plans:
        line = LineString([(c[0], c[1]) for c in p.route.coordinates])
        assert not line.intersects(a.geometry), p.title  # la route contourne la réserve
        assert not any(r.code == "SENSITIVE_AREA" and r.level == "danger" for r in p.risks)
        land = next(b for b in p.briefing if b.startswith("Atterrissage"))
        assert "PTU et approche hors de la zone « Réserve naturelle nationale du Bout du Lac" in land


def test_7_4_prohibited_zone_crossed_or_landing_inside_is_no_go():
    from app.engine.airspace import Projector, evaluate_sensitive_route, evaluate_sensitive_sites
    from app.engine.scenario import build_context

    ctx, _ = build_context(_s01_bout_du_lac())
    t = ctx.takeoffs[0]
    ldg = next(iter(ctx.landings.values()))
    proj = Projector(t.lat, t.lon)
    # ligne droite Forclaz → Doussard : traverse la réserve, à toute hauteur → no-go
    f = evaluate_sensitive_route(ctx, proj, [(t.lon, t.lat, 3000.0), (ldg.lon, ldg.lat, 3000.0)], t, ldg)
    assert any(x.absolute_nogo and "vol libre est interdit" in x.title for x in f)
    inside = ldg.model_copy(update={"lat": 45.792, "lon": 6.226})
    f = evaluate_sensitive_sites(ctx, proj, t, inside)
    assert any(x.absolute_nogo for x in f)


def test_7_4_regulatory_overflight_below_height_is_no_go():
    from app.engine.airspace import Projector, evaluate_sensitive_route
    from app.engine.scenario import build_context

    ctx, _ = build_context(_s01_bout_du_lac(flight_prohibited=False, min_height_agl_m=300))
    t = ctx.takeoffs[0]
    ldg = next(iter(ctx.landings.values()))
    proj = Projector(t.lat, t.lon)
    low = evaluate_sensitive_route(ctx, proj, [(t.lon, t.lat, t.elevation_m), (ldg.lon, ldg.lat, 500.0)], t, ldg)
    assert any(x.code == "SENSITIVE_AREA" and x.absolute_nogo for x in low)  # sous 300 m/sol : no-go, pas caution
    high = evaluate_sensitive_route(ctx, proj, [(t.lon, t.lat, 3000.0), (ldg.lon, ldg.lat, 3000.0)], t, ldg)
    assert not any(x.code == "SENSITIVE_AREA" for x in high)


def test_7_4_low_overflight_airspace_is_a_regulated_zone():
    from app.providers.airspaces import parse_openaip

    item = {"name": "PARC/RESERVE AIGUILLES ROUGES", "type": 29, "icaoClass": 8,
            "lowerLimit": {"value": 0, "unit": 1, "referenceDatum": 0},
            "upperLimit": {"value": 300, "unit": 0, "referenceDatum": 1},
            "geometry": {"type": "Polygon", "coordinates": [[[6.84, 45.95], [6.92, 45.97], [6.95, 46.03],
                                                             [6.88, 46.04], [6.84, 45.95]]]}}  # fmt: skip
    (asp,), _ = parse_openaip({"items": [item]})
    assert asp.type == "LOW_OVERFLIGHT" and asp.ceiling_agl and asp.ceiling_height_m == 300
    from app.engine.airspace import low_overflight_areas

    (z,) = low_overflight_areas([asp])
    assert z.kind == "regulatory" and z.min_height_agl_m == 300 and not z.flight_prohibited


# ---------------------------------------------------------------------------------------------
# B6 : limite OpenAIP globale → espaces de démonstration servis en live
# ---------------------------------------------------------------------------------------------
async def test_b6_openaip_tiles_cached_and_never_demo_in_live():
    import json

    import httpx

    from app.services import DataService

    page = json.loads((FIX / "openaip_airspaces_annecy.json").read_text())
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "openaip" in request.url.host:
            calls.append(request.url.params["bbox"])
            return httpx.Response(200, json={**page, "nextPage": None})
        return httpx.Response(404)

    settings = Settings(_env_file=None, data_mode="live", openaip_api_key="cle-de-test", ffvl_api_key=None)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        ds = DataService(settings, client=c)
        a1, r1, w1 = await ds.airspaces((6.0, 45.7, 6.5, 46.0))
        # autre bbox dans la même tuile (pan de carte, autre clic) : cache, pas d'appel, données réelles
        a2, _, w2 = await ds.airspaces((6.1, 45.75, 6.3, 45.9))
        # autre massif dans les 5 min : pas de nouvel appel, et JAMAIS d'espaces de démonstration
        a3, r3, w3 = await ds.airspaces((5.6, 44.1, 6.0, 44.4))
    assert len(calls) == 1 and calls[0] == "6.0000,45.0000,7.0000,46.0000"  # une tuile de 1° entière
    assert a1 and w1 is None and r1[0].mode == "live"
    assert a2 and w2 is None and all(x.name in {a.name for a in a1} for x in a2)
    assert w3 is not None and "NON VÉRIFIÉS" in w3
    assert not any("approx" in a.name for a in a3) and all(r.mode == "live" for r in r3)


def test_b6_plan_says_airspaces_unverified(monkeypatch):
    from app.services import DataService

    async def unverified(self, bbox, terrain=None):
        return [], [], "Espaces aériens NON VÉRIFIÉS (aucune donnée : OpenAIP indisponible) : vérifie la carte."

    monkeypatch.setattr(DataService, "airspaces", unverified)
    with TestClient(create_app(Settings(_env_file=None, data_mode="mock"))) as c:
        lat, lon = ZONES["annecy"]
        r = c.post("/api/plans", json={"zone": {"type": "circle", "center": {"lat": lat, "lon": lon}, "radius_km": 25},
                                       "horizon": "24h", "reference_time": "2026-10-14T09:00:00Z",
                                       "filters": {"duration_min_minutes": 15, "duration_max_minutes": 30,
                                                   "difficulty": "intermediate", "thermals": "allowed"}})  # fmt: skip
        g = c.get("/api/airspaces", params={"bbox": "6.0,45.7,6.5,46.0"})
    j = r.json()
    assert any("NON VÉRIFIÉS" in w for w in j["warnings"])
    for p in j["plans"]:
        assert any(x["code"] == "AIRSPACE" and x["level"] == "caution" and "non vérifiés" in x["detail"]
                   for x in p["risks"])  # fmt: skip
        assert p["flyability"] != "go"
    assert g.json()["unverified"] is True and "NON VÉRIFIÉS" in g.json()["warning"]


# ---------------------------------------------------------------------------------------------
# B7 / 7.16 : plafonds référencés au sol (GND / ASFC)
# ---------------------------------------------------------------------------------------------
def _agl_item(ceiling_ft: float = 1000.0) -> dict:
    return {"name": "LF-R30C MONT BLANC", "type": 1, "icaoClass": 8,
            "lowerLimit": {"value": 0, "unit": 1, "referenceDatum": 0},
            "upperLimit": {"value": ceiling_ft, "unit": 1, "referenceDatum": 0},
            "geometry": {"type": "Polygon", "coordinates": [[[6.8, 45.85], [6.95, 45.85], [6.95, 45.95], [6.8, 45.95],
                                                             [6.8, 45.85]]]}}  # fmt: skip


def test_b7_agl_ceiling_kept_as_height_and_checked_point_by_point():
    from app.engine.airspace import Projector, agl_overlap, limits_at
    from app.engine.context import DataContext
    from app.providers.airspaces import parse_openaip, with_ground

    (a,), _ = parse_openaip({"items": [_agl_item()]})  # sans MNT : la hauteur est gardée, jamais lue en AMSL
    assert a.ceiling_agl and round(a.ceiling_height_m) == 305 and not a.floor_agl
    assert with_ground(a, 1400.0).ceiling_m == 1705
    t = _t("2026-10-10T10:00:00Z")
    ctx = DataContext(reference_time=t, target_time=t, horizon="2h", takeoffs=[], landings={}, timelines={},
                      terrain=lambda la, lo: 1400.0, terrain_is_real=True)  # fmt: skip
    assert limits_at(ctx, a, 45.9, 6.87) == pytest.approx((0.0, 1704.8))
    proj = Projector(45.9, 6.87)
    low = [(6.82, 45.9, 1500.0), (6.9, 45.9, 1500.0)]
    high = [(6.82, 45.9, 2500.0), (6.9, 45.9, 2500.0)]
    assert agl_overlap(ctx, proj, a, low) and not agl_overlap(ctx, proj, a, high)
    # MNT inconnu : prudence, chevauchement supposé
    ctx.terrain, ctx.terrain_is_real = None, False
    assert agl_overlap(ctx, proj, a, high)


def test_b7_r30c_route_below_305m_gives_activation_caution():
    from app.engine.airspace import Projector, evaluate_airspaces
    from app.engine.context import DataContext
    from app.providers.airspaces import parse_openaip

    (a,), _ = parse_openaip({"items": [_agl_item()]})
    t = _t("2026-10-10T10:00:00Z")
    ctx = DataContext(reference_time=t, target_time=t, horizon="2h", takeoffs=[], landings={}, timelines={},
                      terrain=lambda la, lo: 1400.0, terrain_is_real=True, airspaces=[a])  # fmt: skip
    proj = Projector(45.9, 6.87)
    res = evaluate_airspaces(ctx, proj, [(6.82, 45.9, 1600.0), (6.9, 45.9, 1500.0)], 1040.0, 2000.0)
    assert any(f.code == "AIRSPACE_ACTIVATION" and f.caution and "305 m/sol" in f.detail for f in res.findings)
    res = evaluate_airspaces(ctx, proj, [(6.82, 45.9, 2500.0), (6.9, 45.9, 2500.0)], 2500.0, 2500.0)
    assert not any(f.code == "AIRSPACE_ACTIVATION" and f.caution for f in res.findings)


# ---------------------------------------------------------------------------------------------
# 7.5-7.7, 7.10, 7.19 : créneau, raison de l'heure limite, difficulté, arrondi
# ---------------------------------------------------------------------------------------------
REQS = [
    ("annecy", "24h", "2026-10-14T09:00:00Z", "intermediate", "allowed", 15, 30),
    ("sthilaire", "24h", "2026-10-14T15:00:00Z", "beginner", "avoid", 15, 30),
    ("annecy", "24h", "2026-10-14T15:00:00Z", "intermediate", "avoid", 15, 30),
    ("sthilaire", "48h", "2026-10-13T10:00:00Z", "intermediate", "allowed", 45, 90),
    ("sthilaire", "24h", "2026-10-14T10:00:00Z", "beginner", "allowed", 60, 120),
    ("chamonix", "24h", "2026-10-20T11:00:00Z", "expert", "allowed", 120, 300),
]


@pytest.fixture(scope="module")
def many(client):
    return {r: plans(client, *r) for r in REQS}


def test_7_5_no_go_plan_with_blocking_wind_increasing(many):
    for j in many.values():
        for p in j["plans"]:
            check_window(p)
            wi = [r for r in p["risks"] if r["code"] == "WIND_INCREASING"]
            if p["flyability"] == "go":
                assert not any(r["level"] == "caution" for r in wi), (p["title"], wi)
    p = next(p for p in many[REQS[0]]["plans"] if p["title"].startswith("Planfait") and "plouf" in p["title"])
    assert p["flyability"] == "go"
    assert _t(p["window"]["end"]) < _t("2026-10-15T11:30:00Z")  # le vent forcit à 13h30 légales
    assert any(r["code"] == "WIND_INCREASING" and r["level"] == "info" and "Fin du créneau" in r["detail"]
               for r in p["risks"])  # fmt: skip


def test_7_6_window_respects_sunset_and_east_face_shade(many):
    from app.meteo.solar import solar_local_hour

    for j in many.values():
        for p in j["plans"]:
            check_window(p)  # posé 30 min avant le coucher, quelle que soit la variante
            if p["takeoff"]["name"].endswith("Nord"):  # déco E/ENE/NE : fermé après 12h30 solaires sans vent d'E
                assert solar_local_hour(_t(p["window"]["end"]), p["takeoff"]["lon"]) <= 12.5 + 1e-6, p["window"]


def test_7_7_landing_reason_and_duration_causes(many):
    for j in many.values():
        for p in j["plans"]:
            cre = next(b for b in p["briefing"] if b.startswith("Créneau"))
            reason = cre.split("être posé avant ", 1)[1].split(")", 1)[0]
            latest, sunset = _t(p["window"]["latest_landing"]), _t(p["sun"]["sunset"])
            if sunset - latest > timedelta(hours=1):
                assert "(coucher du soleil" not in reason, cre
            if "plouf" in p["title"] and "Seul un plouf" in p["summary"]:
                assert "dénivelé" in p["summary"] and "avant le coucher" not in p["summary"]
            assert "(fin des thermiques)" not in p["summary"]
    s = [p for p in many[REQS[4]]["plans"] if "local thermique" in p["title"]]
    assert s and "limite élève 45 min" in s[0]["summary"]


def test_7_10_difficulty_is_smallest_level_not_no_go(client, many):
    j = plans(client, "annecy", "24h", "2026-10-14T09:00:00Z", "advanced", "allowed", 15, 30)
    for p in j["plans"]:
        lv = p["difficulty"]
        again = plans(client, "annecy", "24h", "2026-10-14T09:00:00Z", lv, "allowed", 15, 30, max_results=20)
        same = [q for q in again["plans"] if q["title"] == p["title"]]
        assert same and same[0]["flyability"] != "no_go", (p["title"], lv, [r["reasons"] for r in again["rejected"]])
    for j2 in many.values():
        for p in j2["plans"]:
            if p["est_duration_min"] > 45:
                assert p["difficulty"] != "beginner", p["title"]


def test_7_19_quarter_hour_from_12h(many):
    for (_, horizon, *_), j in many.items():
        for p in j["plans"]:
            if horizon in ("12h", "24h", "48h"):
                assert _t(p["window"]["latest_landing"]).minute % 15 == 0, p["window"]


# ---------------------------------------------------------------------------------------------
# 7.8 (M) : points de décision du local thermique ; 7.11 (M) : cross sur thermiques faibles, noms des sommets
# ---------------------------------------------------------------------------------------------
def test_7_8_local_thermal_decision_points_have_safety_altitudes(many):
    seen = 0
    for j in many.values():
        for p in j["plans"]:
            if "local thermique" not in p["title"]:
                continue
            dps = [b for b in p["briefing"] if b.startswith("Point de décision")]
            for dp in dps:
                seen += 1
                assert f"au-dessus de {p['takeoff']['elevation_m']:.0f} m" not in dp, dp
                assert "sois au-dessus de" in dp or "accessible directement" in dp, dp
                assert "rentre vers" in dp
    assert seen


def test_7_11_no_cross_on_weak_thermals_and_named_turnpoints(client):
    from app.engine.context import DataContext, ReliefPoint
    from app.engine.routing import _relief_name

    j = plans(client, "sthilaire", "24h", "2026-10-14T09:00:00Z", "expert", "allowed", 120, 300)
    assert not any("cross" in p["title"] for p in j["plans"])
    t = _t("2026-10-14T09:00:00Z")
    ctx = DataContext(reference_time=t, target_time=t, horizon="24h", takeoffs=[], landings={}, timelines={},
                      relief=[ReliefPoint("Dent de Crolles", 45.309, 5.853, 2062, ["W"])])  # fmt: skip
    assert _relief_name(ctx, 45.310, 5.852, "Relief à 7 km au O") == "Dent de Crolles"
    assert _relief_name(ctx, 45.40, 5.70, "Relief à 9 km au NNO") == "Relief à 9 km au NNO"
    # S05 (cross sur Planpraz, thermiques ≥ 1,5 m/s) reste proposé
    res = run_scenario(scenario("S05", {"weather": {"thermal_strength_ms": 1.0}}))
    reasons = [r for rj in res.rejected for r in rj.reasons] + [x for p in res.plans for x in [p.title]]
    assert not any("cross" in p.title for p in res.plans), reasons


# ---------------------------------------------------------------------------------------------
# 7.13 (M) : k « paire associée » (Forclaz → Doussard, plouf école de référence)
# ---------------------------------------------------------------------------------------------
def test_7_13_associated_pair_glide_k(client):
    from app.engine.routing import finesse_sol

    assert finesse_sol(8.5, "beginner", 0, 0, 0, pair=True) == pytest.approx(6.8)
    assert finesse_sol(8.5, "beginner", 0, 0, 0) == pytest.approx(8.5 * 0.65)
    j = plans(client, "annecy", "24h", "2026-10-14T09:00:00Z", "beginner", "allowed", 15, 30)
    p = next(p for p in j["plans"] if p["takeoff"]["name"].startswith("Col de la Forclaz"))
    assert p["flyability"] == "go" and p["glide"]["available_ratio"] == pytest.approx(6.8, abs=0.15)
    assert p["glide"]["required_ratio"] / p["glide"]["available_ratio"] < 0.9
    # 10 km/h de face : finesse 4,96, plus de plané possible → no-go (vent nul au déco du scénario S01 remplacé)
    sc = scenario("S01", {"filters": {"difficulty": "beginner", "flight_types": ["local"], "thermals": "avoid",
                                      "duration_min_minutes": 10, "duration_max_minutes": 30},
                          "weather": {"takeoff_wind_kmh": 10, "takeoff_wind_dir": 225, "landing_wind_kmh": 10,
                                      "landing_wind_dir": 225, "thermal_strength_ms": 0.0}})  # fmt: skip
    res = run_scenario(sc)
    assert not any(pp.flyability == "go" for pp in res.plans)


def test_7_13_deduced_association_keeps_level_k():
    from app.engine.routing import is_source_pair
    from app.providers.sites import associate_landings

    deco = Site(id="d", name="D", kind="takeoff", lat=45.81, lon=6.24, elevation_m=1250, source="paraglidingearth")
    ldg = Site(id="l", name="L", kind="landing", lat=45.79, lon=6.22, elevation_m=450, source="paraglidingearth")
    associate_landings([deco, ldg])
    assert deco.associated_landing_ids == ["l"] and not is_source_pair(deco, ldg)  # déduite par proximité
    deco2 = deco.model_copy(update={"associated_landing_ids": ["l"], "deduced_landing_ids": []})
    assert is_source_pair(deco2, ldg)
    assert "deduced_landing_ids" not in deco.model_dump()  # interne, hors contrat


# ---------------------------------------------------------------------------------------------
# 7.14 (M) : fixture Plaine-Joux → Chedde (2,6 km), GO élève par vent calme
# ---------------------------------------------------------------------------------------------
def test_7_14_plaine_joux_school_plouf(client):
    from app.geo import haversine_km

    j = plans(client, "chamonix", "24h", "2026-10-14T09:00:00Z", "beginner", "allowed", 15, 30)
    p = next(p for p in j["plans"] if p["takeoff"]["name"] == "Passy – Plaine-Joux")
    assert p["flyability"] == "go" and p["glide"]["margin_ok"]
    # Chedde (45,9285 ; 6,7246 ; 603 m, coordonnées de la revue) ; déco de démo à 3,2 km (au lieu de 4,8 km)
    assert haversine_km(p["takeoff"]["lat"], p["takeoff"]["lon"], p["landing"]["lat"], p["landing"]["lon"]) <= 3.2


# ---------------------------------------------------------------------------------------------
# 7.15 (M) : décollage au-dessus du FL115
# ---------------------------------------------------------------------------------------------
def test_7_15_takeoff_above_fl115():
    res = run_scenario(scenario("S05", {"takeoff": {"elevation_m": 3593}, "filters": {"thermals": "allowed"}}))
    assert not res.plans  # brevet confirmé : réservé aux experts
    reasons = [r for rj in res.rejected for r in rj.reasons]
    assert any(r.startswith("[ALTITUDE_LIMIT] Décollage à 3593 m, au-dessus du plafond réglementaire FL115") for r in
               reasons)  # fmt: skip
    assert not any("plafond utile -" in r.lower() for r in reasons)
    req = run_scenario(scenario("S05", {"takeoff": {"elevation_m": 3593},
                                        "filters": {"thermals": "required", "difficulty": "expert"}}))  # fmt: skip
    reasons = [r for rj in req.rejected for r in rj.reasons]
    assert any("Plafond limité par le FL115" in r and "sous l'altitude du déco" in r for r in reasons), reasons
    ex = run_scenario(scenario("S05", {"takeoff": {"elevation_m": 3593},
                                       "filters": {"thermals": "allowed", "difficulty": "expert"}}))  # fmt: skip
    for p in ex.plans:
        assert p.flyability != "go" and p.difficulty == "expert"
        assert any(r.code == "ALTITUDE_LIMIT" and r.level == "caution" for r in p.risks)


# ---------------------------------------------------------------------------------------------
# TMA au-dessus du déco : on plafonne au lieu de rejeter le vol thermique
# ---------------------------------------------------------------------------------------------
def _tma(floor: float) -> dict:
    return {"name": "TMA TEST", "airspace_class": "D", "type": "TMA", "floor_m": floor, "ceiling_m": 4500,
            "polygon": [[6.70, 45.85], [7.00, 45.85], [7.00, 46.05], [6.70, 46.05], [6.70, 45.85]]}  # fmt: skip


def test_tma_above_takeoff_caps_ceiling_instead_of_no_go():
    high = {"weather": {"thermal_ceiling_m": 3400, "cloud_base_m": 3700}}
    base = run_scenario(scenario("S26b", high))
    assert any("local thermique" in p.title and p.max_altitude_m > 2800 for p in base.plans)
    res = run_scenario(scenario("S26b", {**high, "airspaces": [_tma(2800)]}))
    th = [p for p in res.plans if "local thermique" in p.title]
    assert th, [r.reasons for r in res.rejected]
    for p in th:
        assert p.max_altitude_m <= 2700
        assert any(r.code == "ALTITUDE_LIMIT" for r in p.risks)
        assert not any(r.code == "AIRSPACE" and r.level == "danger" for r in p.risks)
    # plancher SOUS le déco (2000 m) : vraiment dans l'espace → rejet
    low = run_scenario(scenario("S26b", {"airspaces": [_tma(1500)]}))
    assert not low.plans
    assert any("[AIRSPACE]" in r for rj in low.rejected for r in rj.reasons)


# ---------------------------------------------------------------------------------------------
# 7.17 (M) : règles du CDC désormais lues (pression, rotor, relief d'un cross) ou listées « non vérifiées »
# ---------------------------------------------------------------------------------------------
def test_7_17_pressure_drop_front_is_no_go():
    hourly = {str(h): {"pressure_msl_hpa": p} for h, p in ((9, 1016.0), (10, 1015.0), (11, 1014.0), (12, 1012.5),
                                                           (13, 1011.0), (14, 1010.0), (15, 1009.0))}  # fmt: skip
    res = run_scenario(scenario("S01", {"weather": {"hourly": hourly}}))
    assert not res.plans
    assert any(r.startswith("[FRONT] La pression baisse de") for rj in res.rejected for r in rj.reasons)
    calm = {str(h): {"pressure_msl_hpa": 1016.0 - 0.3 * (h - 9)} for h in range(9, 16)}
    ok = run_scenario(scenario("S01", {"weather": {"hourly": calm}}))
    assert ok.plans


def test_7_17_rotor_and_xc_relief_on_real_dem():
    from app.engine.planner import rotor_finding, route_relief_max
    from app.engine.routing import GlideCheck, Route
    from app.engine.scenario import build_context

    ctx, _ = build_context(scenario("S01"))
    ldg = next(iter(ctx.landings.values()))

    def ridge(lat, lon):  # crête de 1500 m au nord de l'atterro (2 km), plaine ailleurs
        return 1950.0 if lat > ldg.lat + 0.015 else 450.0

    ctx.terrain, ctx.terrain_is_real = ridge, True
    f = rotor_finding(ctx, ldg, "Atterro", (20.0, 0.0))  # vent du N à 20 km/h : sous le vent de la crête
    assert f is not None and f.absolute_nogo and f.code == "ROTOR"
    assert rotor_finding(ctx, ldg, "Atterro", (10.0, 0.0)) is None  # < 15 km/h à la crête
    assert rotor_finding(ctx, ldg, "Atterro", (20.0, 180.0)) is None  # vent du S : crête sous le vent de l'atterro
    r = Route("xc", [(ldg.lon, ldg.lat, 2500.0), (ldg.lon, ldg.lat + 0.05, 2500.0)], [], 5.0, 2500.0,
              GlideCheck(1.0, 6.0, True))  # fmt: skip
    assert route_relief_max(ctx, r) == 1950.0
    ctx.terrain_is_real = False
    assert route_relief_max(ctx, r) is None and rotor_finding(ctx, ldg, "Atterro", (20.0, 0.0)) is None


def test_7_17_unchecked_rules_listed(many):
    for j in many.values():
        for p in j["plans"]:
            u = [r for r in p["risks"] if r["code"] == "UNCHECKED"]
            assert u and u[0]["level"] == "info" and "venturi" in u[0]["detail"]


# ---------------------------------------------------------------------------------------------
# 7.9 (M) : rafale fusionnée (facteur de rafale non borné)
# ---------------------------------------------------------------------------------------------
def test_7_9_gust_fusion_is_additive_and_bounded(client):
    from app.engine.stations import StationNowcast, fuse

    site = Site(id="x", name="Lumbin", kind="landing", lat=45.3, lon=5.9, elevation_m=240, source="fixture")
    nc = StationNowcast(role="landing", site=site, eval_time=_t("2026-10-15T12:30:00Z"), dt_min=60, w_nominal=0.67,
                        attachments=[], representative=[object()], speed_bias_kmh=3.0, weight=0.67,
                        beacon_gust_kmh=13.0, gust_bias_kmh=0.0)  # fmt: skip
    v, _, g, _, _ = fuse(nc, 4.0, 200.0, 13.0, "30m")
    assert v == pytest.approx(6.0, abs=0.05)
    assert g == pytest.approx(13.0)  # avant : 13 × 6 / 4 = 19,5 → plus que la balise ET que le modèle
    nc.gust_bias_kmh = None  # balise sans rafale : décalage du vent moyen
    assert fuse(nc, 4.0, 200.0, 13.0, "2h")[2] == pytest.approx(15.0, abs=0.05)
    j = plans(client, "sthilaire", "30m", "2026-10-15T11:30:00Z", "intermediate", "allowed", 15, 30)
    for p in j["plans"]:
        assert p["weather"]["landing"]["wind_10m"]["gust_kmh"] <= 16, p["weather"]["landing"]["wind_10m"]


# ---------------------------------------------------------------------------------------------
# Heure cible : même arrondi côté moteur, PlanResponse et FlightPlan (et front) ; ids de plans sans collision
# ---------------------------------------------------------------------------------------------
def test_target_time_rounding_consistent(client):
    from app.plan_service import round_target, target_for

    assert target_for(_t("2026-10-09T10:07:00Z"), "30m") == _t("2026-10-09T10:30:00Z")
    assert target_for(_t("2026-10-09T10:20:00Z"), "1h") == _t("2026-10-09T11:15:00Z")
    assert target_for(_t("2026-10-09T10:20:00Z"), "2h") == _t("2026-10-09T12:00:00Z")  # le moteur évaluait 12:20
    assert round_target(_t("2026-10-09T10:07:30Z"), "15m") == _t("2026-10-09T10:15:00Z")  # demie vers le haut
    assert round_target(_t("2026-10-09T10:30:00Z"), "2h") == _t("2026-10-09T11:00:00Z")
    j = plans(client, "annecy", "2h", "2026-10-15T08:20:00Z", "intermediate", "allowed", 15, 30)
    assert j["target_time"] == "2026-10-15T10:00:00Z"
    for p in j["plans"]:
        assert p["target_time"] == j["target_time"]


def test_plan_ids_depend_on_the_whole_request(client):
    a = plans(client, "annecy", "24h", "2026-10-14T09:00:00Z", "intermediate", "allowed", 15, 30)
    b = plans(client, "annecy", "24h", "2026-10-14T09:00:00Z", "intermediate", "allowed", 15, 30,
              wing_glide_ratio=5.0)  # fmt: skip
    ids_a = {p["id"] for p in a["plans"]}
    assert ids_a and not ids_a & {p["id"] for p in b["plans"]}
    for p in a["plans"]:  # GET /api/plans/{id} renvoie toujours le plan de la PREMIÈRE requête
        got = client.get(f"/api/plans/{p['id']}").json()
        assert got["glide"] == p["glide"]
    again = plans(client, "annecy", "24h", "2026-10-14T09:00:00Z", "intermediate", "allowed", 15, 30)
    assert {p["id"] for p in again["plans"]} == ids_a  # même requête → mêmes ids (stables)


# ---------------------------------------------------------------------------------------------
# Décollage libre : altitude saisie très différente du MNT ; balises de démo jamais en live
# ---------------------------------------------------------------------------------------------
def test_custom_takeoff_elevation_checked_against_dem(client):
    base = {"horizon": "24h", "reference_time": "2026-10-14T09:00:00Z", "difficulty": "intermediate",
            "landing_policy": "include_community"}  # fmt: skip
    ref = client.post("/api/landings/analyze", json={**base, "takeoff": {"lat": 45.815, "lon": 6.2465}}).json()
    bad = {"lat": 45.815, "lon": 6.2465, "elevation_m": 2600}
    typo = client.post("/api/landings/analyze", json={**base, "takeoff": bad}).json()
    dem = ref["takeoff"]["elevation_m"]
    assert typo["takeoff"]["elevation_m"] <= dem + 50
    assert any("très différente du MNT" in w for w in typo["warnings"])
    assert len(typo["candidates"]) == len(ref["candidates"])
    near = client.post("/api/landings/analyze",
                       json={**base, "takeoff": {"lat": 45.815, "lon": 6.2465, "elevation_m": dem + 150}}).json()
    assert near["takeoff"]["elevation_m"] == dem + 150 and any("différente du MNT" in w for w in near["warnings"])


async def test_demo_beacons_never_used_for_real_forecast():
    from datetime import UTC, datetime

    from app.services import DataService

    ds = DataService(Settings(_env_file=None, data_mode="auto", openaip_api_key=None))
    ds.states["pioupiou"].block(3600, "test")  # Pioupiou injoignable
    ds.states["ffvl-beacons"].disabled_message = "test"
    later = datetime.now(UTC) + timedelta(hours=3)
    bs, _, refs = await ds.beacons((6.1, 45.7, 6.4, 45.95), at=later, allow_demo=False)
    assert bs == [] and not any(r.mode == "mock" for r in refs)
    demo, _, _ = await ds.beacons((6.1, 45.7, 6.4, 45.95), at=later)  # carte en mode auto : démo signalée
    assert demo and all(b.source == "fixture" for b in demo)



# ---------------------------------------------------------------------------------------------
# 7.18 (m) : raisons de rejet sans doublon, codes justes
# ---------------------------------------------------------------------------------------------
def test_7_18_reasons_deduplicated_by_code(client):
    from app.engine.planner import dedupe_reasons

    got = dedupe_reasons(["[VALLEY_BREEZE] Brise vers 12h14.", "[VALLEY_BREEZE] Brise vers 13h30.",
                          "[TAKEOFF_GUSTS] Rafales 20 km/h.", "[TAKEOFF_GUSTS] Rafales 41 km/h : hors limites.",
                          "Sans code."])  # fmt: skip
    assert got == ["[VALLEY_BREEZE] Brise vers 12h14.", "[TAKEOFF_GUSTS] Rafales 41 km/h : hors limites.", "Sans code."]
    for args in (("annecy", "15m", "2026-10-15T11:30:00Z", "intermediate", "allowed", 15, 30),
                 ("sthilaire", "24h", "2026-10-09T11:00:00Z", "intermediate", "allowed", 15, 30)):  # fmt: skip
        j = plans(client, *args)
        for rj in j["rejected"]:
            codes = [r[1 : r.index("]")] for r in rj["reasons"] if r.startswith("[")]
            assert len(codes) == len(set(codes)), rj["reasons"]
            assert not any("seuil de ton niveau appliqué" in r for r in rj["reasons"])
            assert not any(r.startswith("[TAKEOFF_WIND] Vent jusqu'à") for r in rj["reasons"])


# ---------------------------------------------------------------------------------------------
# 7.20, 7.21 (m) : restitution, textes et détails
# ---------------------------------------------------------------------------------------------
def test_7_20_restitution_when_window_overlaps(many):
    j = many[REQS[2]]  # Annecy 24h avoid, cible 17h00 légales
    assert any("restitution" in p["title"] for p in j["plans"]), [p["title"] for p in j["plans"]]


def test_7_21_texts_and_details():
    from app.export.xctrack import plan_to_xctsk
    from app.providers.sites import parse_pge

    feat = {"type": "Feature", "id": "3045", "geometry": {"type": "Point", "coordinates": [6.2, 45.8]},
            "properties": {"name": "Déco X", "pge_site_id": "3045", "takeoff_altitude": "1200", "paragliding": "1",
                           "W": "2", "landing": {"landing_name": "null", "landing_lat": "45.79", "landing_lng": "6.19",
                                                 "landing_altitude": "450"}}}  # fmt: skip
    sites, _ = parse_pge({"type": "FeatureCollection", "features": [feat]})
    assert any(s.name == "Atterrissage PGE n° 3045" for s in sites)
    res = run_scenario(scenario("S05"))
    xc = [p for p in res.plans if p.flight_type == "cross_country"]
    assert xc and xc[0].summary.startswith("Cross en triangle FAI")  # et non « triangle fai »
    for p in xc:
        task = plan_to_xctsk(p)
        tps = task["turnpoints"]
        assert tps[0]["type"] == "TAKEOFF" and tps[1]["type"] == "SSS"
        assert tps[1]["waypoint"]["lat"] == tps[0]["waypoint"]["lat"]  # départ autour du déco


def test_7_22_sources_show_shared_open_meteo_quota():
    from app.services import DataService

    ds = DataService(Settings(_env_file=None, data_mode="live", openaip_api_key=None))
    st = ds.states["open-meteo-elevation"]
    st.record_failure("HTTP 429 Daily API request limit exceeded")
    for k in ("open-meteo", "open-meteo-15min", "open-meteo-elevation"):
        ds.states[k].block(3600, "quota journalier Open-Meteo atteint")
    by = {s.name: s for s in ds.statuses()}
    om = by[ds.states["open-meteo"].name]
    assert not om.healthy and "suspendue" in (om.message or "") and "Pas encore interrogée" not in (om.message or "")


# ---------------------------------------------------------------------------------------------
# Exports : contenu GPX et .xctsk (et plus seulement le statut 200)
# ---------------------------------------------------------------------------------------------
def test_exports_content(client):
    import json
    from xml.etree import ElementTree as ET

    j = plans(client, "annecy", "30m", "2026-10-15T11:30:00Z", "intermediate", "allowed", 15, 30)
    if not j["plans"]:
        j = plans(client, "annecy", "24h", "2026-10-14T09:00:00Z", "intermediate", "allowed", 15, 30)
    p = j["plans"][0]
    gpx = client.get(p["links"]["gpx"])
    assert gpx.status_code == 200
    root = ET.fromstring(gpx.text.split("\n", 1)[1])
    ns = "{http://www.topografix.com/GPX/1/1}"
    tags = [c.tag.replace(ns, "") for c in root]
    assert tags[0] == "metadata" and tags[-1] == "rte" and set(tags[1:-1]) == {"wpt"}  # ordre du schéma
    for w in root.findall(f"{ns}wpt"):
        ele = w.find(f"{ns}ele")
        assert ele is None or float(ele.text) > 0, ET.tostring(w)  # jamais « 0 » pour une altitude inconnue
    rte = root.find(f"{ns}rte")
    assert len(rte.findall(f"{ns}rtept")) == len(p["route"]["coordinates"])
    task = json.loads(client.get(p["links"]["xctsk"]).text)
    assert task["taskType"] == "CLASSIC" and task["version"] == 1
    types = [tp.get("type") for tp in task["turnpoints"]]
    assert types[0] == "TAKEOFF" and "SSS" in types and types[-1] == "ESS"
    assert task["sss"]["timeGates"] and task["goal"]["deadline"].endswith("Z")


def test_precipitation_window_open_meteo_convention():
    from app.engine.planner import cloud_precip_findings
    from app.engine.scenario import build_context

    def prev_rain(hour: int) -> bool:
        ctx, _ = build_context(scenario("S01", {"weather": {"hourly": {str(hour): {"precipitation_mm_h": 1.2}}}}))
        tl = ctx.timelines[ctx.takeoffs[0].id]
        ldg = next(iter(ctx.landings.values()))
        start = _t("2026-07-15T12:00:00Z")
        f = cloud_precip_findings(tl, tl, ctx.takeoffs[0], ldg, start, start + timedelta(hours=1))
        return any(x.title == "Pluie dans les 3 h précédentes" for x in f)

    assert prev_rain(10)  # valeur 10 h = pluie de 9 h à 10 h : dans les 3 h avant 12 h
    assert not prev_rain(9)  # valeur 9 h = pluie de 8 h à 9 h : plus de 3 h avant


def test_airspace_vertical_margin_caution():
    from shapely.geometry import box

    from app.engine.airspace import Projector, evaluate_airspaces
    from app.engine.context import Airspace, DataContext

    t = _t("2026-10-10T10:00:00Z")
    ctr = Airspace(name="CTR TEST", airspace_class="D", type="CTR", floor_m=0, ceiling_m=1500,
                   geometry=box(6.0, 45.7, 6.4, 45.9))  # fmt: skip
    ctx = DataContext(reference_time=t, target_time=t, horizon="24h", takeoffs=[], landings={}, timelines={},
                      airspaces=[ctr])  # fmt: skip
    proj = Projector(45.8, 6.2)
    coords = [(6.1, 45.8, 1550.0), (6.3, 45.8, 1550.0)]
    res = evaluate_airspaces(ctx, proj, coords, 1550.0, 2000.0)
    assert any(f.code == "AIRSPACE" and f.caution and "marge verticale" in f.detail for f in res.findings)
    res = evaluate_airspaces(ctx, proj, [(c[0], c[1], 1800.0) for c in coords], 1800.0, 2000.0)
    assert not any(f.code == "AIRSPACE" and f.caution for f in res.findings)


def test_end_of_range_single_model_label():
    import json

    from app.meteo.snapshot import snapshot_from_analysis
    from app.providers.open_meteo import parse_forecast_response
    from app.services import build_timeline

    models = ["meteofrance_arome_france_hd", "icon_d2", "ecmwf_ifs025"]
    raw = json.loads((FIX / "open_meteo_forclaz_3models.json").read_text())
    pf = parse_forecast_response(raw, [(45.81, 6.25, 1245.0)], models, _t("2026-10-08T06:00:00Z"), "u")[0]
    tl = build_timeline(pf, None, _t("2026-10-10T12:00:00Z"), _t("2026-10-10T22:00:00Z"))
    late = tl.at(_t("2026-10-10T19:00:00Z"))
    assert late.models == ["ecmwf_ifs025"] and len(tl.model_winds[late.time]) == 1
    from app.engine.planner import _models

    assert _models(late, tl) == "ecmwf_ifs025"  # et non « arome_france_hd+ecmwf_ifs025+icon_d2 »
    assert snapshot_from_analysis(late, _models(late, tl)).model == "ecmwf_ifs025"


async def test_concurrent_identical_forecasts_single_call(monkeypatch):
    import asyncio

    from app.services import DataService

    ds = DataService(Settings(_env_file=None, data_mode="auto", openaip_api_key=None))
    calls = 0
    orig = ds.synthetic.fetch_sync

    async def slow_live(*a, **k):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.2)
        return None  # repli synthétique

    monkeypatch.setattr(ds, "_try_live", slow_live)
    monkeypatch.setattr(ds.synthetic, "fetch_sync", orig)
    start, end = _t("2026-10-15T08:00:00Z"), _t("2026-10-15T16:00:00Z")
    await asyncio.gather(*(ds.forecasts([(45.8, 6.2, 1200.0)], start, end, start) for _ in range(5)))
    assert calls == 1


def test_7_21_api_beacons_carry_trend(monkeypatch):
    from app.models import BeaconTrend
    from app.services import DataService

    asked: list[str] = []

    async def fake(self, ids):
        asked.extend(ids)
        return {i: BeaconTrend(window_min=60, speed_change_kmh=3, direction_change_deg=10, gust_max_kmh=20,
                               samples=12) for i in ids}  # fmt: skip

    monkeypatch.setattr(DataService, "beacon_trends", fake)
    with TestClient(create_app(Settings(_env_file=None, data_mode="mock"))) as c:
        r = c.get("/api/beacons", params={"bbox": "6.0,45.7,6.5,46.0"}).json()
    with_trend = [b for b in r["beacons"] if b["trend"] is not None]
    assert with_trend and len(asked) <= 8


def test_7_18_official_only_names_excluded_community_landing(client):
    body = {"takeoff": {"lat": 45.755, "lon": 6.245}, "horizon": "24h", "reference_time": "2026-10-14T09:00:00Z",
            "difficulty": "intermediate", "landing_policy": "official_only"}  # fmt: skip
    j = client.post("/api/landings/analyze", json=body).json()
    assert all(c["kind"] == "official" for c in j["candidates"])
    assert any("(atterro communautaire) écarté : exclu par ta politique d'atterrissage" in w for w in j["warnings"])
