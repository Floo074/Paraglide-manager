"""Structures internes des données de prévision brutes (indépendantes de la source)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# Niveaux de pression demandés aux modèles (du bas vers le haut)
PRESSURE_LEVELS_HPA: tuple[int, ...] = (1000, 950, 925, 900, 850, 800, 700, 600, 500)


@dataclass(slots=True)
class LevelData:
    """Données d'un niveau de pression pour une heure donnée."""

    pressure_hpa: float
    height_m: float  # géopotentiel ≈ altitude AMSL
    temperature_c: float
    dew_point_c: float
    wind_speed_kmh: float
    wind_direction_deg: float


@dataclass(slots=True)
class HourData:
    """Sortie d'un modèle pour un point et une heure (valeurs None si non fournies)."""

    time: datetime
    temperature_2m: float | None = None
    dew_point_2m: float | None = None
    wind_speed_10m: float | None = None
    wind_direction_10m: float | None = None
    wind_gusts_10m: float | None = None
    cloud_cover: float | None = None
    cloud_cover_low: float | None = None
    cloud_cover_mid: float | None = None
    cloud_cover_high: float | None = None
    precipitation: float | None = None
    cape: float | None = None
    lifted_index: float | None = None
    convective_inhibition: float | None = None
    freezing_level_height: float | None = None
    boundary_layer_height: float | None = None
    shortwave_radiation: float | None = None
    levels: list[LevelData] = field(default_factory=list)


@dataclass(slots=True)
class ModelSeries:
    """Série horaire d'un modèle pour un point."""

    model: str
    lat: float
    lon: float
    elevation_m: float
    hours: list[HourData]

    def hour_at(self, t: datetime) -> HourData | None:
        for h in self.hours:
            if h.time == t:
                return h
        return None


@dataclass(slots=True)
class PointForecast:
    """Prévision multi-modèles d'un point."""

    lat: float
    lon: float
    elevation_m: float
    models: list[ModelSeries]
    mode: str  # "live" | "mock"
    source_name: str
    source_url: str | None
    fetched_at: datetime

    def times(self) -> list[datetime]:
        ts: set[datetime] = set()
        for m in self.models:
            ts.update(h.time for h in m.hours)
        return sorted(ts)
