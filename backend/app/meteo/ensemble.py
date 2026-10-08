"""Agrégation multi-modèles : moyenne (vectorielle pour le vent) + dispersion → confiance."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime

from app.geo import wind_components, wind_from_components
from app.meteo.types import HourData, LevelData

_SCALAR_FIELDS = (
    "temperature_2m",
    "dew_point_2m",
    "wind_gusts_10m",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "precipitation",
    "cape",
    "lifted_index",
    "convective_inhibition",
    "freezing_level_height",
    "boundary_layer_height",
    "shortwave_radiation",
)


@dataclass(slots=True)
class Spread:
    """Dispersion inter-modèles pour une heure."""

    n_models: int
    wind_speed_sigma_kmh: float
    wind_dir_sigma_deg: float
    precip_max_mm_h: float
    cape_max_j_kg: float
    wind_speed_max_kmh: float
    models: list[str]


def _mean(values: list[float]) -> float | None:
    vals = [v for v in values if v is not None and not math.isnan(v)]
    return sum(vals) / len(vals) if vals else None


def circular_std_deg(directions: list[float], weights: list[float] | None = None) -> float:
    if len(directions) < 2:
        return 0.0
    w = weights or [1.0] * len(directions)
    s = sum(wi * math.sin(math.radians(d)) for d, wi in zip(directions, w, strict=False))
    c = sum(wi * math.cos(math.radians(d)) for d, wi in zip(directions, w, strict=False))
    r = math.hypot(s, c) / sum(w)
    r = min(1.0, max(1e-9, r))
    return math.degrees(math.sqrt(-2.0 * math.log(r)))


def aggregate_hours(hours: list[HourData], time: datetime) -> HourData:
    """Moyenne des modèles disponibles pour une heure (les champs absents d'un modèle sont ignorés)."""
    out = HourData(time=time)
    for f in _SCALAR_FIELDS:
        setattr(out, f, _mean([getattr(h, f) for h in hours]))
    # vent 10 m : moyenne vectorielle
    us, vs = [], []
    for h in hours:
        if h.wind_speed_10m is not None and h.wind_direction_10m is not None:
            u, v = wind_components(h.wind_speed_10m, h.wind_direction_10m)
            us.append(u)
            vs.append(v)
    if us:
        speed, direction = wind_from_components(sum(us) / len(us), sum(vs) / len(vs))
        # la moyenne vectorielle sous-estime la force si les directions divergent : on garde la force moyenne
        out.wind_speed_10m = _mean([h.wind_speed_10m for h in hours if h.wind_speed_10m is not None])
        out.wind_direction_10m = direction if speed > 0.1 else _mean(
            [h.wind_direction_10m for h in hours if h.wind_direction_10m is not None]
        )
    # niveaux de pression
    by_p: dict[float, list[LevelData]] = {}
    for h in hours:
        for lv in h.levels:
            by_p.setdefault(lv.pressure_hpa, []).append(lv)
    levels = []
    for p, lvs in sorted(by_p.items(), reverse=True):
        us = [wind_components(lv.wind_speed_kmh, lv.wind_direction_deg) for lv in lvs]
        _, d = wind_from_components(sum(u for u, _ in us) / len(us), sum(v for _, v in us) / len(us))
        levels.append(
            LevelData(
                pressure_hpa=p,
                height_m=sum(lv.height_m for lv in lvs) / len(lvs),
                temperature_c=sum(lv.temperature_c for lv in lvs) / len(lvs),
                dew_point_c=sum(lv.dew_point_c for lv in lvs) / len(lvs),
                wind_speed_kmh=sum(lv.wind_speed_kmh for lv in lvs) / len(lvs),
                wind_direction_deg=d,
            )
        )
    out.levels = levels
    return out


def hour_spread(hours: list[HourData], models: list[str]) -> Spread:
    speeds = [h.wind_speed_10m for h in hours if h.wind_speed_10m is not None]
    dirs = [h.wind_direction_10m for h in hours if h.wind_direction_10m is not None]
    weights = [max(1.0, h.wind_speed_10m or 0.0) for h in hours if h.wind_direction_10m is not None]
    return Spread(
        n_models=len(hours),
        wind_speed_sigma_kmh=statistics.pstdev(speeds) if len(speeds) > 1 else 0.0,
        wind_dir_sigma_deg=circular_std_deg(dirs, weights) if len(dirs) > 1 else 0.0,
        precip_max_mm_h=max([h.precipitation or 0.0 for h in hours] or [0.0]),
        cape_max_j_kg=max([h.cape or 0.0 for h in hours] or [0.0]),
        wind_speed_max_kmh=max(speeds or [0.0]),
        models=list(models),
    )
