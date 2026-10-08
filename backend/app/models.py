"""Modèles Pydantic — reflet exact de docs/API_CONTRACT.md (source de vérité)."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Horizon = Literal["30m", "1h", "2h", "8h", "12h", "24h", "48h"]
Difficulty = Literal["beginner", "intermediate", "advanced", "expert"]
ThermalPreference = Literal["required", "allowed", "avoid"]
FlightType = Literal["local", "ridge_soaring", "cross_country"]
Flyability = Literal["go", "marginal", "no_go"]
RiskLevel = Literal["info", "caution", "danger"]
SiteSource = Literal["ffvl", "paraglidingearth", "spotair", "fixture"]
BeaconSource = Literal["ffvl", "pioupiou", "fixture"]
DataMode = Literal["live", "mock", "mixed"]
SourceMode = Literal["live", "mock"]

HORIZON_MINUTES: dict[str, int] = {
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "8h": 480,
    "12h": 720,
    "24h": 1440,
    "48h": 2880,
}
DIFFICULTY_ORDER: list[str] = ["beginner", "intermediate", "advanced", "expert"]
COMPASS_16: list[str] = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]  # fmt: skip

MAX_ZONE_RADIUS_KM = 150.0
MAX_BBOX_SIDE_DEG = 3.0


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class LatLon(_Model):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class BBoxZone(_Model):
    type: Literal["bbox"]
    min_lat: float = Field(ge=-90, le=90)
    min_lon: float = Field(ge=-180, le=180)
    max_lat: float = Field(ge=-90, le=90)
    max_lon: float = Field(ge=-180, le=180)

    @model_validator(mode="after")
    def _check(self) -> BBoxZone:
        if self.min_lat >= self.max_lat or self.min_lon >= self.max_lon:
            raise ValueError("bbox invalide : min doit être < max")
        if (self.max_lat - self.min_lat) > MAX_BBOX_SIDE_DEG or (
            self.max_lon - self.min_lon
        ) > MAX_BBOX_SIDE_DEG:
            raise ValueError(f"bbox trop grande (> {MAX_BBOX_SIDE_DEG}° de côté)")
        return self


class CircleZone(_Model):
    type: Literal["circle"]
    center: LatLon
    radius_km: float = Field(gt=0)

    @field_validator("radius_km")
    @classmethod
    def _radius(cls, v: float) -> float:
        if v > MAX_ZONE_RADIUS_KM:
            raise ValueError(f"rayon de zone trop grand (> {MAX_ZONE_RADIUS_KM:.0f} km)")
        return v


Zone = Annotated[BBoxZone | CircleZone, Field(discriminator="type")]


def zone_bbox(zone: BBoxZone | CircleZone) -> tuple[float, float, float, float]:
    """(min_lon, min_lat, max_lon, max_lat) englobant la zone."""
    if isinstance(zone, BBoxZone):
        return zone.min_lon, zone.min_lat, zone.max_lon, zone.max_lat
    dlat = zone.radius_km / 111.32
    dlon = zone.radius_km / (111.32 * max(0.05, math.cos(math.radians(zone.center.lat))))
    return (
        zone.center.lon - dlon,
        zone.center.lat - dlat,
        zone.center.lon + dlon,
        zone.center.lat + dlat,
    )


class Site(_Model):
    id: str
    name: str
    kind: Literal["takeoff", "landing", "both"]
    lat: float
    lon: float
    elevation_m: float
    orientations: list[str] = Field(default_factory=list)
    difficulty: Difficulty | None = None
    flight_types: list[FlightType] = Field(default_factory=list)
    description: str | None = None
    access: str | None = None
    restrictions: str | None = None
    status: Literal["open", "restricted", "closed", "unknown"] = "unknown"
    source: SiteSource
    url: str | None = None
    associated_landing_ids: list[str] = Field(default_factory=list)


class Beacon(_Model):
    id: str
    name: str
    lat: float
    lon: float
    elevation_m: float | None = None
    observed_at: str
    wind_speed_kmh: float | None = None
    wind_gust_kmh: float | None = None
    wind_direction_deg: float | None = None
    temperature_c: float | None = None
    source: BeaconSource
    stale: bool


class WindLevel(_Model):
    altitude_m: float
    pressure_hpa: float | None
    speed_kmh: float
    direction_deg: float


class SoundingLevel(_Model):
    pressure_hpa: float
    altitude_m: float
    temperature_c: float
    dew_point_c: float
    wind_speed_kmh: float
    wind_direction_deg: float


class Wind10m(_Model):
    speed_kmh: float
    direction_deg: float
    gust_kmh: float


class NowcastCorrection(_Model):
    beacon_ids: list[str]
    wind_speed_bias_kmh: float
    wind_direction_bias_deg: float


class WeatherSnapshot(_Model):
    time: str
    model: str
    lat: float
    lon: float
    elevation_m: float
    temperature_c: float
    dew_point_c: float
    wind_10m: Wind10m
    winds_aloft: list[WindLevel]
    cloud_cover_pct: float
    cloud_cover_low_pct: float
    precipitation_mm_h: float
    cape_j_kg: float
    lifted_index: float | None
    cin_j_kg: float | None
    freezing_level_m: float | None
    boundary_layer_height_agl_m: float
    thermal_ceiling_m: float
    cloud_base_m: float | None
    thermal_strength_ms: float
    wstar_ms: float
    shortwave_radiation_w_m2: float
    nowcast_correction: NowcastCorrection | None = None


class ThermalAnalysis(_Model):
    convection_start: str | None
    convection_end: str | None
    peak_time: str | None
    peak_strength_ms: float
    ceiling_m: float
    cumulus: bool
    overdevelopment_risk: Literal["low", "moderate", "high"]
    comment: str


class Risk(_Model):
    code: str
    level: RiskLevel
    title: str
    detail: str


class Waypoint(_Model):
    name: str
    lat: float
    lon: float
    altitude_m: float
    type: Literal["takeoff", "turnpoint", "thermal_trigger", "landing", "alternate_landing"]
    radius_m: float | None = None
    eta_min: float | None = None
    note: str | None = None


class AirspaceWarning(_Model):
    name: str
    airspace_class: str
    type: str
    floor_m: float
    ceiling_m: float
    min_distance_km: float
    intersects_route: bool


class ScoreItem(_Model):
    criterion: str
    score: float
    weight: float
    comment: str


class Glide(_Model):
    required_ratio: float
    available_ratio: float
    margin_ok: bool


class PlanWeather(_Model):
    takeoff: WeatherSnapshot
    landing: WeatherSnapshot
    timeline: list[WeatherSnapshot]


class TimeWindow(_Model):
    start: str
    end: str


class RouteGeometry(_Model):
    type: Literal["LineString"] = "LineString"
    coordinates: list[tuple[float, float, float]]


class SourceRef(_Model):
    name: str
    url: str | None
    fetched_at: str
    mode: SourceMode


class PlanLinks(_Model):
    gpx: str
    xctsk: str


class FlightPlan(_Model):
    id: str
    rank: int
    score: float
    flyability: Flyability
    difficulty: Difficulty
    flight_type: FlightType
    thermal_usage: Literal["none", "optional", "essential"]
    title: str
    summary: str
    target_time: str
    window: TimeWindow
    takeoff: Site
    landing: Site
    alternate_landings: list[Site]
    waypoints: list[Waypoint]
    route: RouteGeometry
    distance_km: float
    est_duration_min: float
    max_altitude_m: float
    glide: Glide
    weather: PlanWeather
    thermals: ThermalAnalysis
    sounding: list[SoundingLevel]
    beacons_nearby: list[Beacon]
    airspaces: list[AirspaceWarning]
    risks: list[Risk]
    briefing: list[str]
    checklist: list[str]
    score_breakdown: list[ScoreItem]
    confidence: float
    sources: list[SourceRef]
    links: PlanLinks


class PlanFilters(_Model):
    duration_min_minutes: float = Field(ge=0, le=12 * 60)
    duration_max_minutes: float = Field(gt=0, le=12 * 60)
    difficulty: Difficulty
    thermals: ThermalPreference
    flight_types: list[FlightType] | None = None
    max_results: int = Field(default=5, ge=1, le=20)
    wing_glide_ratio: float = Field(default=8.5, ge=4.0, le=14.0)

    @model_validator(mode="after")
    def _check(self) -> PlanFilters:
        if self.duration_min_minutes > self.duration_max_minutes:
            raise ValueError("duration_min_minutes doit être <= duration_max_minutes")
        if self.flight_types is not None and len(self.flight_types) == 0:
            raise ValueError("flight_types ne peut pas être vide (omettre pour tous les types)")
        return self


class PlanRequest(_Model):
    zone: Zone
    horizon: Horizon
    reference_time: str | None = None
    filters: PlanFilters


class RejectedSite(_Model):
    site: Site
    reasons: list[str]


class PlanResponse(_Model):
    request_id: str
    generated_at: str
    target_time: str
    horizon: Horizon
    zone: Zone
    data_mode: DataMode
    plans: list[FlightPlan]
    rejected: list[RejectedSite]
    warnings: list[str]


class HealthResponse(_Model):
    status: Literal["ok"] = "ok"
    data_mode: DataMode
    version: str


class SourceStatus(_Model):
    name: str
    kind: Literal["forecast", "sites", "beacons", "airspaces", "elevation"]
    mode: Literal["live", "mock", "disabled"]
    healthy: bool
    requires_api_key: bool
    api_key_configured: bool
    message: str | None
    url: str | None


class SourcesResponse(_Model):
    sources: list[SourceStatus]


class GridPoint(_Model):
    lat: float
    lon: float
    value: float
    direction_deg: float | None


class GridLegend(_Model):
    min: float
    max: float


class GridResponse(_Model):
    time: str
    layer: str
    altitude_m: float | None
    unit: str
    resolution_deg: float
    points: list[GridPoint]
    legend: GridLegend


class PointForecastResponse(_Model):
    snapshot: WeatherSnapshot
    sounding: list[SoundingLevel]
    timeline: list[WeatherSnapshot]
