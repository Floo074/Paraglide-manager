"""Exécution d'un scénario de validation métier (docs/expert/scenarios-validation.yaml).

`run_scenario(spec) -> PlanResponse` : construit un contexte de données à partir de conditions
imposées (vent au déco, vents en altitude, plafond, base, CAPE, pluie…), sans réseau, puis exécute le
moteur réel. Les données injectées sont traitées comme « source exacte » (pas de plafonnement mock).

Format du spec : voir le message d'interface backend ↔ expert et l'en-tête du fichier YAML.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from shapely.geometry import Polygon

from app.engine import rules
from app.engine.airspace import low_overflight_areas
from app.engine.context import Airspace, DataContext, PointTimeline, ReliefPoint, SensitiveArea, SiteMeta
from app.engine.landings import LandingSpot
from app.engine.planner import evaluate_sites
from app.engine.terrain import TakeoffTerrain, axis_from_orientations, orientations_from_aspect
from app.meteo.ensemble import Spread
from app.meteo.profile import VerticalProfile
from app.meteo.snapshot import iso
from app.meteo.thermals import HourAnalysis
from app.meteo.types import HourData, LevelData
from app.models import HORIZON_MINUTES, Beacon, BeaconTrend, CircleZone, LatLon, PlanFilters, PlanResponse, Site
from app.providers.fixture_data import fixture_relief
from app.providers.synthetic_terrain import terrain_elevation


def _parse_time(s: str) -> datetime:
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _hm(s: str, day: datetime) -> datetime:
    h, m = (int(x) for x in str(s).split(":"))
    return day.replace(hour=h, minute=m, second=0, microsecond=0)


def _site(spec: dict, sid: str, kind: str, landing_ids: list[str] | None = None, **extra) -> Site:
    return Site(
        id=sid,
        name=spec["name"],
        kind=kind,
        lat=float(spec["lat"]),
        lon=float(spec["lon"]),
        elevation_m=float(spec["elevation_m"]),
        orientations=list(spec.get("orientations", [])),
        difficulty=spec.get("difficulty"),
        flight_types=list(spec.get("flight_types", [])) if kind != "landing" else [],
        description=None,
        access=spec.get("access"),
        restrictions=spec.get("restrictions"),
        status=spec.get("status", "open"),
        source="fixture",
        url=None,
        associated_landing_ids=landing_ids or [],
        **extra,
    )


def _hour_values(weather: dict, t: datetime) -> dict:
    vals = {k: v for k, v in weather.items() if k not in ("hourly", "winds_aloft", "convection")}
    hourly = weather.get("hourly") or {}
    over = hourly.get(str(t.hour)) or hourly.get(f"{t.hour:02d}") or {}
    vals.update(over)
    vals["winds_aloft"] = over.get("winds_aloft", weather.get("winds_aloft", {}))
    return vals


def _levels(winds_aloft: dict, t_ground: float, td_ground: float, ground_m: float) -> list[LevelData]:
    out = []
    for z, sd in sorted(((float(k), v) for k, v in winds_aloft.items()), key=lambda x: x[0]):
        speed, direction = float(sd[0]), float(sd[1])
        t = t_ground - 0.0065 * (z - ground_m)
        td = min(t - 1.0, td_ground - 0.002 * (z - ground_m))
        out.append(
            LevelData(
                pressure_hpa=round(1013.25 * (1 - 2.25577e-5 * z) ** 5.25588, 1),
                height_m=z,
                temperature_c=t,
                dew_point_c=td,
                wind_speed_kmh=speed,
                wind_direction_deg=direction,
            )
        )
    return out


def _analysis(
    t: datetime,
    lat: float,
    lon: float,
    ground_m: float,
    vals: dict,
    wind: tuple[float, float, float],
    temp: float,
    dew: float,
    low_cc: float,
    in_conv: bool,
    takeoff_alt: float,
) -> HourAnalysis:
    hd = HourData(
        time=t,
        temperature_2m=temp,
        dew_point_2m=dew,
        wind_speed_10m=wind[0],
        wind_direction_10m=wind[1],
        wind_gusts_10m=wind[2],
        levels=_levels(vals.get("winds_aloft", {}), temp, dew, ground_m),
    )
    profile = VerticalProfile.from_hour(hd, ground_m)
    ceiling = float(vals.get("thermal_ceiling_m", takeoff_alt))
    base = vals.get("cloud_base_m")
    strength = float(vals.get("thermal_strength_ms", 0.0)) if in_conv else 0.0
    if not in_conv:
        ceiling = takeoff_alt
    usable = ceiling if base is None else min(ceiling, float(base) - 300.0)
    usable = max(ground_m, usable)
    cape = float(vals.get("cape_j_kg", 0.0))
    li = vals.get("lifted_index")
    rh700 = None
    return HourAnalysis(
        time=t,
        lat=lat,
        lon=lon,
        ground_m=ground_m,
        profile=profile,
        temperature_c=temp,
        dew_point_c=dew,
        wind_speed_kmh=wind[0],
        wind_direction_deg=wind[1],
        wind_gust_kmh=wind[2],
        cloud_cover_pct=float(vals.get("cloud_cover_pct", 0.0)),
        cloud_cover_low_pct=low_cc,
        cloud_cover_midhigh_pct=max(0.0, float(vals.get("cloud_cover_pct", 0.0)) - low_cc),
        precipitation_mm_h=float(vals.get("precipitation_mm_h", 0.0)),
        cape_j_kg=cape,
        lifted_index=None if li is None else float(li),
        cin_j_kg=None,
        freezing_level_m=profile.isotherm_height(0.0),
        shortwave_w_m2=600.0 if in_conv else 100.0,
        blh_agl_m=max(0.0, ceiling - ground_m) if in_conv else 0.0,
        dry_top_m=ceiling,
        lcl_m=float(base) if base is not None else 99999.0,
        thermal_ceiling_m=ceiling,
        cloud_base_m=None if base is None else float(base),
        cumulus=base is not None and float(base) < ceiling + 1,
        usable_ceiling_m=usable,
        wstar_ms=strength + 1.0 if in_conv else 0.0,
        thermal_strength_ms=strength,
        rh700_pct=rh700,
        el_m=None,
        models=["scenario"],
        pressure_msl_hpa=None if vals.get("pressure_msl_hpa") is None else float(vals["pressure_msl_hpa"]),
    )


def _custom_takeoff(spec: dict) -> tuple[Site, TakeoffTerrain]:
    """Décollage libre d'un scénario : site source « user » (difficulté null = intermediate) ; pente et exposition MNT
    imposées (`slope_pct`, `aspect_deg`) ; profil dans l'axe non contrôlé (pas de MNT réel)."""
    ct = spec["custom_takeoff"]
    aspect = ct.get("aspect_deg")
    orientations = list(ct.get("orientations") or (orientations_from_aspect(float(aspect)) if aspect is not None
                                                   else []))  # fmt: skip
    site = Site(
        id="user:scenario", name=ct.get("name") or "Décollage libre", kind="takeoff", lat=float(ct["lat"]),
        lon=float(ct["lon"]), elevation_m=float(ct["elevation_m"]), orientations=orientations, difficulty=None,
        flight_types=list(rules.FREE_TAKEOFF_FLIGHT_TYPES), source="user", status="unknown", official=False,
    )  # fmt: skip
    terrain = TakeoffTerrain(
        elevation_m=float(ct["elevation_m"]),
        slope_pct=None if ct.get("slope_pct") is None else float(ct["slope_pct"]),
        aspect_deg=None if aspect is None else float(aspect),
        profile_ok=None,
        axis_deg=axis_from_orientations(orientations) if orientations else aspect,
        source="scenario",
    )
    return site, terrain


def _spot(site: Site, spec: dict) -> LandingSpot:
    """Données d'un atterro candidat d'un scénario (`landing_candidates`, CDC §12.7)."""
    size = spec.get("size_m")
    clear = spec.get("clearances_m")
    clearances: dict[str, float | None] = {}
    if isinstance(clear, dict):  # null = rien dans un rayon de 500 m ; clé absente = non cartographié
        clearances = {k: (None if v is None else float(v)) for k, v in clear.items()}
    return LandingSpot(
        site=site,
        kind=spec.get("landing_kind", "official"),
        size=(float(size["length"]), float(size["width"])) if size else None,
        axis_deg=spec.get("axis_deg"),
        slope_pct=spec.get("slope_pct"),
        surface=spec.get("surface"),
        community_usage=spec.get("community_usage", "unknown"),
        access=spec.get("access"),
        road_m=clearances.get("road"),
        clearances=clearances,
    )


def build_context(spec: dict) -> tuple[DataContext, PlanFilters]:
    mode = spec.get("mode", "classic")
    ref = _parse_time(spec["reference_time"])
    horizon = spec["horizon"]
    target = ref + timedelta(minutes=HORIZON_MINUTES[horizon])
    filters = PlanFilters(**spec["filters"])
    weather = spec["weather"]
    free_terrain: dict[str, TakeoffTerrain] = {}
    spots: dict[str, LandingSpot] = {}
    if mode == "custom_takeoff":
        # décollage libre : `landing_candidates` remplace landing / alternate_landings ; le moteur choisit
        takeoff, terrain = _custom_takeoff(spec)
        free_terrain[takeoff.id] = terrain
        cand_specs = list(spec.get("landing_candidates") or [])
        cands = []
        for i, c in enumerate(cand_specs):
            kind = c.get("landing_kind", "official")
            site = _site(c, f"scenario:cand{i}", "landing", official=kind == "official", landing_kind=kind)
            cands.append(site)
            spots[site.id] = _spot(site, c)
        landing, alternates, alt_specs = cands[0], cands[1:], cand_specs[1:]
        landing_spec = cand_specs[0]
    else:
        alt_specs = spec.get("alternate_landings") or []
        landing_ids = ["scenario:landing"] + [f"scenario:alt{i}" for i in range(len(alt_specs))]
        takeoff = _site(spec["takeoff"], "scenario:takeoff", "takeoff", landing_ids)
        landing = _site(spec["landing"], "scenario:landing", "landing")
        alternates = [_site(a, f"scenario:alt{i}", "landing") for i, a in enumerate(alt_specs)]
        landing_spec = spec["landing"]
    meta = {
        landing.id: SiteMeta(big_valley=landing_spec.get("big_valley"), top_landing=False),
        **{a.id: SiteMeta(big_valley=s.get("big_valley")) for a, s in zip(alternates, alt_specs, strict=False)},
    }
    if mode != "custom_takeoff" and spec["takeoff"].get("dem_aspect_deg") is not None:
        # exposition mesurée sur le MNT réel (revue 7.3) : imposée par le scénario
        meta[takeoff.id] = SiteMeta(dem_aspect_deg=float(spec["takeoff"]["dem_aspect_deg"]))
    day0 = target.replace(hour=0, minute=0, second=0, microsecond=0)
    hours = [day0 - timedelta(hours=6) + timedelta(hours=i) for i in range(36)]
    conv = weather.get("convection") or {}
    tl_hours: list[HourAnalysis] = []
    l_hours: dict[str, list[HourAnalysis]] = {landing.id: [], **{a.id: [] for a in alternates}}
    prev3 = float(weather.get("precip_prev_3h_mm", 0.0) or 0.0)
    target_hour = target.replace(minute=0, second=0, microsecond=0)
    for t in hours:
        vals = _hour_values(weather, t)
        day = t.replace(hour=0, minute=0)
        in_conv = bool(conv) and _hm(conv["start"], day) <= t <= _hm(conv["end"], day)
        # pluie des 3 h avant la cible : valeurs horodatées cible − 2 h … cible (cumul de l'heure précédente, comme
        # Open-Meteo)
        if prev3 > 0 and target_hour - timedelta(hours=2) <= t <= target_hour and "precipitation_mm_h" not in (
            (weather.get("hourly") or {}).get(str(t.hour)) or {}
        ):
            vals["precipitation_mm_h"] = max(float(vals.get("precipitation_mm_h", 0.0)), prev3 / 3.0)
        tw = (float(vals["takeoff_wind_kmh"]), float(vals["takeoff_wind_dir"]), float(vals["takeoff_gust_kmh"]))
        t_to = float(vals.get("temperature_c", 15.0))
        td_to = float(vals.get("dew_point_c", t_to - 8.0))
        low = float(vals.get("cloud_cover_low_pct", 0.0))
        tl_hours.append(
            _analysis(
                t,
                takeoff.lat,
                takeoff.lon,
                takeoff.elevation_m,
                vals,
                tw,
                t_to,
                td_to,
                low,
                in_conv,
                takeoff.elevation_m,
            )
        )
        for ldg in [landing, *alternates]:
            lw = (float(vals["landing_wind_kmh"]), float(vals["landing_wind_dir"]), float(vals["landing_gust_kmh"]))
            dz = takeoff.elevation_m - ldg.elevation_m
            t_l = float(vals.get("landing_temperature_c", t_to + 0.0065 * dz))
            td_l = float(vals.get("landing_dew_point_c", td_to + 0.002 * dz))
            low_l = float(vals.get("landing_cloud_cover_low_pct", low))
            l_hours[ldg.id].append(
                _analysis(
                    t, ldg.lat, ldg.lon, ldg.elevation_m, vals, lw, t_l, td_l, low_l, in_conv, takeoff.elevation_m
                )
            )
    model_winds: dict[datetime, list[tuple[str, float, float]]] = {}
    spreads: dict[datetime, Spread] = {}
    models = spec.get("models") or {}
    if models:
        for t in hours:
            mw = [(name, float(m["takeoff_wind_kmh"]), float(m["takeoff_wind_dir"])) for name, m in models.items()]
            model_winds[t] = mw
            vals = _hour_values(weather, t)
            spreads[t] = Spread(
                n_models=len(mw),
                wind_speed_sigma_kmh=0.0,
                wind_dir_sigma_deg=0.0,
                precip_max_mm_h=float(vals.get("precipitation_mm_h", 0.0)),
                cape_max_j_kg=float(vals.get("cape_j_kg", 0.0)),
                wind_speed_max_kmh=max(v for _, v, _ in mw),
                gust_max_kmh=max(v for _, v, _ in mw)
                * (float(vals["takeoff_gust_kmh"]) / max(1.0, float(vals["takeoff_wind_kmh"]))),
                li_min=None if vals.get("lifted_index") is None else float(vals["lifted_index"]),
                models=list(models),
            )
    timelines = {
        takeoff.id: PointTimeline(
            takeoff.lat,
            takeoff.lon,
            takeoff.elevation_m,
            tl_hours,
            spreads,
            model_winds,
            mode="live",
            model_label="scenario",
        ),
        **{
            ldg.id: PointTimeline(
                ldg.lat, ldg.lon, ldg.elevation_m, l_hours[ldg.id], mode="live", model_label="scenario"
            )
            for ldg in [landing, *alternates]
        },
    }
    beacons: list[Beacon] = []
    ages: dict[str, float] = {}
    beacon_dem: dict[str, float] = {}
    for i, b in enumerate(spec.get("beacons") or []):
        age = float(b.get("age_min", 5))
        bid = f"scenario:beacon{i}"
        trend = b.get("trend")
        beacons.append(
            Beacon(
                id=bid, name=b["name"], lat=float(b["lat"]), lon=float(b["lon"]), elevation_m=b.get("elevation_m"),
                observed_at=iso(ref - timedelta(minutes=age)), wind_speed_kmh=b.get("wind_speed_kmh"),
                wind_gust_kmh=b.get("wind_gust_kmh"), wind_direction_deg=b.get("wind_direction_deg"),
                temperature_c=b.get("temperature_c"), source="fixture", stale=age > 30,
                trend=BeaconTrend(**trend) if trend else None,
            )
        )
        ages[bid] = age
        # altitude inconnue (null) : MNT imposé par `dem_elevation_m`, sinon MNT indisponible à ce point (CDC §12.1)
        if b.get("elevation_m") is None and b.get("dem_elevation_m") is not None:
            beacon_dem[bid] = float(b["dem_elevation_m"])
    airspaces = [
        Airspace(
            name=a["name"], airspace_class=str(a["airspace_class"]), type=str(a.get("type", a["airspace_class"])),
            floor_m=float(a["floor_m"]), ceiling_m=float(a["ceiling_m"]), geometry=Polygon(a["polygon"]),
            activity_known=bool(a.get("activity_known", False)), active=bool(a.get("active", False)),
            floor_agl=bool(a.get("floor_agl", False)), ceiling_agl=bool(a.get("ceiling_agl", False)),
            floor_height_m=float(a["floor_m"]) if a.get("floor_agl") else None,
            ceiling_height_m=float(a["ceiling_m"]) if a.get("ceiling_agl") else None,
        )
        for a in spec.get("airspaces") or []
    ]
    areas = [
        SensitiveArea(
            id=f"scenario:area{i}",
            name=z["name"],
            kind=z.get("kind", "species"),
            species=z.get("species"),
            period_months=list(z.get("period_months") or list(range(1, 13))),
            recommendation=z.get("recommendation", ""),
            min_height_agl_m=z.get("min_height_agl_m"),
            geometry=Polygon(z["polygon"]),
            flight_prohibited=bool(z.get("flight_prohibited", False)),
        )
        for i, z in enumerate(spec.get("sensitive_areas") or [])
    ]
    areas += low_overflight_areas(airspaces)
    relief = [
        ReliefPoint(
            p["name"], p["lat"], p["lon"], float(p["elevation_m"]), list(p.get("faces", [])), bool(p.get("valley"))
        )
        for p in fixture_relief()
    ]
    ctx = DataContext(
        reference_time=ref,
        target_time=target,
        horizon=horizon,
        takeoffs=[takeoff],
        landings={landing.id: landing, **{a.id: a for a in alternates}},
        timelines=timelines,
        beacons=beacons,
        beacon_ages_min=ages,
        airspaces=airspaces,
        sensitive_areas=areas,
        relief=relief,
        site_meta=meta,
        terrain=terrain_elevation,
        mock=False,
        exact_inputs=True,
        beacon_dem_m=beacon_dem,
        free_terrain=free_terrain,
        landing_spots=spots,
    )
    return ctx, filters


def run_scenario(spec: dict) -> PlanResponse:
    ctx, filters = build_context(spec)
    plans, rejected, warnings, _ = evaluate_sites(ctx, filters)
    t = spec.get("takeoff") or spec["custom_takeoff"]
    zone = CircleZone(type="circle", center=LatLon(lat=t["lat"], lon=t["lon"]), radius_km=10)
    return PlanResponse(
        request_id=str(uuid.uuid4()),
        generated_at=iso(datetime.now(UTC)),
        target_time=iso(ctx.target_time),
        horizon=spec["horizon"],
        zone=zone,
        data_mode="live",
        plans=plans,
        rejected=rejected,
        warnings=warnings,
    )


__all__ = ["build_context", "run_scenario"]
