"""Application FastAPI — routes /api (cf. docs/API_CONTRACT.md)."""

from __future__ import annotations

import logging
import math
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.config import APP_VERSION, Settings, get_settings
from app.engine import rules
from app.export.gpx import plan_to_gpx
from app.export.xctrack import plan_to_xctsk
from app.geo import parse_bbox
from app.meteo.snapshot import iso, snapshot_from_analysis, sounding_from_analysis
from app.meteo.thermals import analyze_hour
from app.models import (
    FlightPlan,
    GridLegend,
    GridPoint,
    GridResponse,
    HealthResponse,
    PlanRequest,
    PlanResponse,
    PointForecastResponse,
    SourcesResponse,
)
from app.plan_service import PlanService
from app.providers.airspaces import airspace_feature
from app.providers.sensitive import area_feature
from app.providers.synthetic_terrain import terrain_elevation
from app.services import DataService, build_timeline

log = logging.getLogger("paraglide")

GRID_LAYERS = {
    "wind": "km/h",
    "thermal": "m/s",
    "cloudbase": "m",
    "ceiling": "m",
    "cape": "J/kg",
    "precipitation": "mm/h",
    "useful_height": "m",
}
GRID_ALTITUDES = (10, 1000, 1500, 2000, 2500, 3000, 4000)
MAX_GET_BBOX_DEG = 5.0


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        data = DataService(settings)
        app.state.data = data
        app.state.plans = PlanService(data, settings.cache_ttl_plans_s)
        yield
        await data.aclose()

    app = FastAPI(
        title="Paraglide Manager API",
        version=APP_VERSION,
        description="Aide à la décision pour le vol en parapente. Ne remplace jamais l'analyse du pilote sur place.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ValueError)
    async def value_error_handler(_: Request, exc: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    def data(request: Request) -> DataService:
        return request.app.state.data

    def bbox_param(raw: str) -> tuple[float, float, float, float]:
        try:
            b = parse_bbox(raw)
        except ValueError as e:
            raise HTTPException(422, detail=f"bbox invalide : {e}") from e
        if b[2] - b[0] > MAX_GET_BBOX_DEG or b[3] - b[1] > MAX_GET_BBOX_DEG:
            raise HTTPException(422, detail=f"bbox trop grande (> {MAX_GET_BBOX_DEG:.0f}° de côté)")
        return b

    def time_param(raw: str | None) -> datetime:
        if not raw:
            return datetime.now(UTC)
        try:
            t = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as e:
            raise HTTPException(422, detail="time invalide (ISO 8601 attendu)") from e
        return t if t.tzinfo else t.replace(tzinfo=UTC)

    # ------------------------------------------------------------------------------------------
    @app.get("/api/health", response_model=HealthResponse)
    async def health(request: Request):
        return HealthResponse(status="ok", data_mode=data(request).data_mode(), version=APP_VERSION)

    @app.get("/api/sources", response_model=SourcesResponse)
    async def sources(request: Request):
        return SourcesResponse(sources=data(request).statuses())

    @app.get("/api/sites")
    async def sites(request: Request, bbox: str = Query(...)):
        b = bbox_param(bbox)
        all_sites, _, _, _ = await data(request).sites(b)
        min_lon, min_lat, max_lon, max_lat = b
        out = [s for s in all_sites if min_lat <= s.lat <= max_lat and min_lon <= s.lon <= max_lon]
        return {"sites": [s.model_dump() for s in out]}

    @app.get("/api/beacons")
    async def beacons(request: Request, bbox: str = Query(...)):
        b = bbox_param(bbox)
        bs, _, _ = await data(request).beacons(b)
        return {"beacons": [x.model_dump() for x in bs]}

    @app.get("/api/airspaces")
    async def airspaces(request: Request, bbox: str = Query(...)):
        b = bbox_param(bbox)
        items, _ = await data(request).airspaces(b)
        return {"type": "FeatureCollection", "features": [airspace_feature(a) for a in items]}

    @app.get("/api/sensitive-areas")
    async def sensitive_areas(request: Request, bbox: str = Query(...), time: str | None = None):
        b = bbox_param(bbox)
        at = time_param(time)
        items, _ = await data(request).sensitive_areas(b)
        return {"type": "FeatureCollection", "features": [area_feature(a, at) for a in items]}

    @app.get("/api/forecast/point", response_model=PointForecastResponse)
    async def forecast_point(request: Request, lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180),
                             time: str | None = None):  # fmt: skip
        t = time_param(time)
        ds = data(request)
        (elev,), _ = await ds.elevations([(lat, lon)])
        day = t.replace(hour=0, minute=0, second=0, microsecond=0)
        start, end = day, day + timedelta(hours=23)
        if t < start or t > end:
            start, end = t.replace(minute=0, second=0, microsecond=0) - timedelta(hours=12), t + timedelta(hours=12)
        fcs, _ = await ds.forecasts([(lat, lon, elev)], start, end, datetime.now(UTC), with_levels=True)
        tl = build_timeline(fcs[0], None, start, end)
        if not tl.hours:
            raise HTTPException(503, detail="Prévision indisponible pour ce point / cette heure.")
        a = tl.at(t)
        return PointForecastResponse(
            snapshot=snapshot_from_analysis(a, tl.model_label),
            sounding=sounding_from_analysis(a),
            timeline=[snapshot_from_analysis(h, tl.model_label) for h in tl.hours if day <= h.time <= day + timedelta(hours=23)],
        )

    @app.get("/api/forecast/grid", response_model=GridResponse)
    async def forecast_grid(request: Request, bbox: str = Query(...), time: str | None = None, layer: str = "wind",
                            altitude_m: int | None = None):  # fmt: skip
        if layer not in GRID_LAYERS:
            raise HTTPException(422, detail=f"layer inconnu : {layer} (choix : {', '.join(GRID_LAYERS)})")
        alt = altitude_m if altitude_m is not None else (10 if layer == "wind" else None)
        if layer == "wind" and alt not in GRID_ALTITUDES:
            raise HTTPException(422, detail=f"altitude_m doit être dans {GRID_ALTITUDES}")
        b = bbox_param(bbox)
        t = time_param(time).replace(minute=0, second=0, microsecond=0)
        ds = data(request)
        max_n = 20 if ds.s.data_mode == "mock" else 10  # live : limite les appels Open-Meteo
        min_lon, min_lat, max_lon, max_lat = b
        span = max(max_lon - min_lon, max_lat - min_lat)
        res = max(span / (max_n - 1), 0.01)
        nx = min(max_n, max(2, int(math.floor((max_lon - min_lon) / res)) + 1))
        ny = min(max_n, max(2, int(math.floor((max_lat - min_lat) / res)) + 1))
        pts = [
            (min_lat + j * (max_lat - min_lat) / (ny - 1), min_lon + i * (max_lon - min_lon) / (nx - 1))
            for j in range(ny)
            for i in range(nx)
        ]
        elevs, emode = await ds.elevations(pts) if ds.s.data_mode != "mock" else ([terrain_elevation(*p) for p in pts], "mock")
        fcs, _ = await ds.forecasts([(la, lo, e) for (la, lo), e in zip(pts, elevs, strict=True)], t, t, datetime.now(UTC),
                                    with_levels=layer not in ("cape", "precipitation") and not (layer == "wind" and alt == 10))  # fmt: skip
        points: list[GridPoint] = []
        for pf in fcs:
            tl = build_timeline(pf, None, t - timedelta(hours=1), t + timedelta(hours=1))
            if not tl.hours:
                continue
            a = tl.at(t)
            direction = None
            if layer == "wind":
                if alt == 10 or alt < a.ground_m:
                    v, direction = a.wind_speed_kmh, a.wind_direction_deg
                else:
                    v, direction = a.profile.wind(float(alt))
            elif layer == "thermal":
                v = a.thermal_strength_ms
            elif layer == "cloudbase":
                if a.cloud_base_m is None:
                    continue  # thermiques bleus : point omis
                v = a.cloud_base_m
            elif layer == "ceiling":
                v = a.thermal_ceiling_m
            elif layer == "cape":
                v = a.cape_j_kg
            elif layer == "precipitation":
                v = a.precipitation_mm_h
            else:  # useful_height : plafond utile − terrain (m/sol)
                v = max(0.0, min(a.usable_ceiling_m, rules.FL115_M_STANDARD) - a.ground_m)
            points.append(GridPoint(lat=round(pf.lat, 4), lon=round(pf.lon, 4), value=round(float(v), 2),
                                    direction_deg=None if direction is None else round(direction) % 360))  # fmt: skip
        vals = [p.value for p in points]
        return GridResponse(
            time=iso(t),
            layer=layer,
            altitude_m=alt if layer == "wind" else None,
            unit=GRID_LAYERS[layer],
            resolution_deg=round(max((max_lon - min_lon) / (nx - 1), (max_lat - min_lat) / (ny - 1)), 4),
            points=points,
            legend=GridLegend(min=min(vals) if vals else 0.0, max=max(vals) if vals else 0.0),
        )

    @app.post("/api/plans", response_model=PlanResponse)
    async def create_plans(request: Request, req: PlanRequest):
        try:
            return await request.app.state.plans.create(req)
        except Exception as e:
            from app.providers.base import ProviderError

            if isinstance(e, ProviderError):
                raise HTTPException(503, detail=str(e)) from e
            raise

    def get_plan(request: Request, plan_id: str) -> FlightPlan:
        p = request.app.state.plans.get(plan_id)
        if p is None:
            raise HTTPException(404, detail="Plan inconnu ou expiré (cache 6 h) : relancer la recherche.")
        return p

    @app.get("/api/plans/{plan_id}", response_model=FlightPlan)
    async def plan(request: Request, plan_id: str):
        return get_plan(request, plan_id)

    @app.get("/api/plans/{plan_id}/gpx")
    async def plan_gpx(request: Request, plan_id: str):
        p = get_plan(request, plan_id)
        return Response(
            content=plan_to_gpx(p),
            media_type="application/gpx+xml",
            headers={"Content-Disposition": f'attachment; filename="paraglide-{plan_id}.gpx"'},
        )

    @app.get("/api/plans/{plan_id}/xctsk")
    async def plan_xctsk(request: Request, plan_id: str):
        p = get_plan(request, plan_id)
        return JSONResponse(
            content=plan_to_xctsk(p),
            headers={"Content-Disposition": f'attachment; filename="paraglide-{plan_id}.xctsk"'},
        )

    return app


app = create_app()
