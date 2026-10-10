"""Contexte de données passé au moteur (synchrone, sans réseau).

Le moteur (`planner.evaluate_sites`) ne connaît que ces structures : il est alimenté soit par les
fournisseurs (live / mock, via `app.services`), soit directement par un scénario de test
(`app.engine.scenario`). Toutes les heures sont des `datetime` UTC « aware ».
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any

from shapely.geometry.base import BaseGeometry

from app.geo import wind_components, wind_from_components
from app.meteo.ensemble import Spread
from app.meteo.thermals import HourAnalysis
from app.models import Beacon, Site

_STEP = timedelta(minutes=15)
_HALF_STEP = timedelta(minutes=8)


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
    # vent 10 m au pas de 15 min (Open-Meteo `minutely_15`, horizons ≤ 2 h) : (heure, vent, direction, rafale)
    minutely: list[tuple[datetime, float, float, float]] = field(default_factory=list)

    def at(self, t: datetime) -> HourAnalysis:
        """Heure la plus proche de t."""
        return min(self.hours, key=lambda h: abs((h.time - t).total_seconds()))

    def wind10_at(self, t: datetime) -> tuple[float, float, float] | None:
        """Vent 10 m (vitesse, direction, rafale) à t, interpolé entre deux pas de 15 min ; None sans données au pas
        de 15 min couvrant t (on garde alors l'heure la plus proche)."""
        m = self.minutely
        if not m or t < m[0][0] - _HALF_STEP or t > m[-1][0] + _HALF_STEP:
            return None
        if t <= m[0][0]:
            return m[0][1], m[0][2], m[0][3]
        for (t0, v0, d0, g0), (t1, v1, d1, g1) in pairwise(m):
            if t0 <= t <= t1:
                if t1 - t0 > 2 * _STEP:  # trou dans la série : pas le plus proche
                    _, v, d, g = (t0, v0, d0, g0) if t - t0 <= t1 - t else (t1, v1, d1, g1)
                    return v, d, g
                f = (t - t0).total_seconds() / max(1.0, (t1 - t0).total_seconds())
                u0, w0 = wind_components(v0, d0)
                u1, w1 = wind_components(v1, d1)
                _, d = wind_from_components(u0 + f * (u1 - u0), w0 + f * (w1 - w0))
                return v0 + f * (v1 - v0), d, g0 + f * (g1 - g0)
        return m[-1][1], m[-1][2], m[-1][3]

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
    # limites publiées par rapport au sol (GND / ASFC, revue B7) : hauteur publiée, convertie point par point avec le
    # MNT par le moteur ; floor_m / ceiling_m gardent une valeur AMSL indicative (terrain au centre de la zone, ou la
    # hauteur seule quand le terrain est inconnu)
    ceiling_agl: bool = False
    floor_height_m: float | None = None
    ceiling_height_m: float | None = None


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
    # revue 7.4 : parapente / sports aériens interdits dans la zone (Biodiv'Sports « PARAGLIDING-FORBIDDEN », texte
    # « interdits dans la zone ») : traverser la zone, à toute hauteur, est un no-go ; le routeur la contourne
    flight_prohibited: bool = False

    def active_in_month(self, month: int) -> bool:
        return not self.period_months or month in self.period_months


@dataclass(slots=True)
class SiteMeta:
    """Métadonnées internes non exposées dans `Site` (issues des fixtures / heuristiques)."""

    big_valley: bool | None = None
    top_landing: bool = False
    # orientation du déco (revue 7.3) : « incertaine » quand la source note presque tous les secteurs ; exposition
    # MNT au point (direction vers laquelle la pente fait face) quand elle a pu être mesurée sur le MNT réel
    orientation_uncertain: bool = False
    orientation_note: str | None = None
    dem_aspect_deg: float | None = None


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
    terrain_is_real: bool = False  # MNT réel (Open-Meteo) : contrôle du relief sous la ligne de plané
    mock: bool = False  # données synthétiques → confiance affichée plafonnée + MOCK_DATA
    exact_inputs: bool = False  # scénario de test : données = source exacte
    warnings: list[str] = field(default_factory=list)
    beacon_timelines: dict[str, PointTimeline] = field(default_factory=dict)
    # altitude MNT au point des balises dont la source ne donne pas l'altitude (Pioupiou) ; absente = MNT
    # indisponible à ce point → « altitude inconnue » (CDC §12.1)
    beacon_dem_m: dict[str, float] = field(default_factory=dict)
    # cache des rattachements balise ↔ site (app.engine.stations), indépendants de l'instant évalué
    station_cache: dict = field(default_factory=dict)
    # décollage libre (CDC §12.6) : lecture du MNT (app.engine.terrain.TakeoffTerrain) par id de site « user:… »
    free_terrain: dict[str, Any] = field(default_factory=dict)
    # atterros candidats (CDC §12.7) : données du terrain (app.engine.landings.LandingSpot) par id de site ; un
    # atterro sans entrée est un site ordinaire (catégorie déduite de `official` / `landing_kind`)
    landing_spots: dict[str, Any] = field(default_factory=dict)
    # revue B6 : espaces aériens NON VÉRIFIÉS (OpenAIP indisponible, pas de fichier OpenAir) : texte de l'avertissement
    airspace_unverified: str | None = None
    request_key: str = ""  # empreinte de la requête (id des plans)

    def terrain_at(self, lat: float, lon: float) -> float | None:
        if self.terrain is None:
            return None
        try:
            return self.terrain(lat, lon)
        except Exception:  # pragma: no cover - terrain indisponible
            return None
