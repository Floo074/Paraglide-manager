"""Contexte de données passé au moteur (synchrone, sans réseau).

Le moteur (`planner.evaluate_sites`) ne connaît que ces structures : il est alimenté soit par les
fournisseurs (live / mock, via `app.services`), soit directement par un scénario de test
(`app.engine.scenario`). Toutes les heures sont des `datetime` UTC « aware ».
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from shapely.geometry.base import BaseGeometry

from app.meteo.ensemble import Spread
from app.meteo.thermals import HourAnalysis
from app.models import Beacon, Site


@dataclass(slots=True)
class PointTimeline:
    """Analyses horaires (agrégées multi-modèles) en un point + dispersion inter-modèles."""

    lat: float
    lon: float
    elevation_m: float
    hours: list[HourAnalysis]
    spreads: dict[datetime, Spread] = field(default_factory=dict)
    # valeurs par modèle pour le vent au site (dispersion → confiance, « une source no-go »)
    model_winds: dict[datetime, list[tuple[str, float, float]]] = field(default_factory=dict)
    mode: str = "mock"
    model_label: str = "synthetic"

    def at(self, t: datetime) -> HourAnalysis:
        """Heure la plus proche de t."""
        return min(self.hours, key=lambda h: abs((h.time - t).total_seconds()))

    def between(self, start: datetime, end: datetime) -> list[HourAnalysis]:
        out = [h for h in self.hours if start <= h.time <= end]
        if not out:
            out = [self.at(start)]
        return out


@dataclass(slots=True)
class Airspace:
    name: str
    airspace_class: str
    type: str
    floor_m: float
    ceiling_m: float
    geometry: BaseGeometry  # en lon/lat
    floor_agl: bool = False
    activity_known: bool = False  # R/ZRT : activité connue (sinon « à vérifier »)
    active: bool = False


@dataclass(slots=True)
class SensitiveArea:
    id: str
    name: str
    kind: str  # species | regulatory | national_park_core
    species: str | None
    period_months: list[int]
    recommendation: str
    min_height_agl_m: float | None
    geometry: BaseGeometry
    source: str = "fixture"
    url: str | None = None

    def active_in_month(self, month: int) -> bool:
        return not self.period_months or month in self.period_months


@dataclass(slots=True)
class SiteMeta:
    """Métadonnées internes non exposées dans `Site` (issues des fixtures / heuristiques)."""

    big_valley: bool | None = None
    top_landing: bool = False


@dataclass(slots=True)
class ReliefPoint:
    name: str
    lat: float
    lon: float
    elevation_m: float
    faces: list[str]
    valley: bool = False


@dataclass
class DataContext:
    reference_time: datetime
    target_time: datetime
    horizon: str
    takeoffs: list[Site]
    landings: dict[str, Site]
    timelines: dict[str, PointTimeline]  # clé : id de site (déco ou atterro)
    beacons: list[Beacon] = field(default_factory=list)
    beacon_ages_min: dict[str, float] = field(default_factory=dict)
    airspaces: list[Airspace] = field(default_factory=list)
    sensitive_areas: list[SensitiveArea] = field(default_factory=list)
    relief: list[ReliefPoint] = field(default_factory=list)
    site_meta: dict[str, SiteMeta] = field(default_factory=dict)
    terrain: Callable[[float, float], float] | None = None
    mock: bool = False  # données synthétiques → confiance affichée plafonnée + MOCK_DATA
    exact_inputs: bool = False  # scénario de test : données = source exacte
    warnings: list[str] = field(default_factory=list)
    beacon_timelines: dict[str, PointTimeline] = field(default_factory=dict)

    def terrain_at(self, lat: float, lon: float) -> float | None:
        if self.terrain is None:
            return None
        try:
            return self.terrain(lat, lon)
        except Exception:  # pragma: no cover - terrain indisponible
            return None
