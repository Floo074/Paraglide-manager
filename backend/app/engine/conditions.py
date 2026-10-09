"""Conditions au décollage / à l'atterrissage à un instant donné (vent interpolé, nowcasting, brise)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.engine import rules
from app.engine.context import DataContext, PointTimeline
from app.engine.stations import StationNowcast, breeze_factor, fuse, station_nowcast
from app.geo import angle_diff, sector_to_deg, wind_components, wind_from_components
from app.meteo.solar import solar_local_hour, sunrise_sunset
from app.meteo.thermals import HourAnalysis
from app.models import Site

PARIS = ZoneInfo("Europe/Paris")


def legal_time(t: datetime) -> datetime:
    """Heure légale française (affichage et règles « heure légale » du cahier des charges)."""
    return t.astimezone(PARIS)


def fmt_hm(t: datetime) -> str:
    return legal_time(t).strftime("%Hh%M")


def solar_hour(t: datetime, lon: float) -> float:
    return solar_local_hour(t, lon)


def sun_times(t: datetime, lat: float, lon: float) -> tuple[datetime | None, datetime | None]:
    local_day = (t + timedelta(hours=lon / 15.0)).date()
    return sunrise_sunset(local_day, lat, lon)


@dataclass(slots=True)
class WindAngle:
    ecart_deg: float  # écart au secteur favorable le plus proche (− demi-secteur, borné à 0)
    raw_deg: float  # angle au centre du secteur le plus proche
    calm: bool
    category: str  # calm | face | cross | tail
    cross_component_kmh: float
    tail_component_kmh: float


def wind_angle(speed: float, direction: float, orientations: list[str]) -> WindAngle:
    centers = [sector_to_deg(o) for o in orientations]
    raw = min(angle_diff(direction, c) for c in centers) if centers else 180.0
    ecart = max(0.0, raw - rules.SECTOR_HALF_WIDTH_DEG)
    calm = speed < rules.CALM_WIND_KMH
    if calm:
        cat = "calm"
    elif ecart == 0:
        cat = "face"
    elif ecart <= rules.TAILWIND_ANGLE_DEG:
        cat = "cross"
    else:
        cat = "tail"
    cross = speed * math.sin(math.radians(min(ecart, 90.0))) if cat == "cross" else 0.0
    if cat == "tail":
        cross = speed * abs(math.sin(math.radians(raw)))
    # vent arrière : on compare la VITESSE du vent au seuil (S18, plus prudent que la composante)
    tail = speed if cat == "tail" else 0.0
    return WindAngle(ecart, raw, calm, cat, cross, tail)


def lee_angle(direction: float, orientations: list[str]) -> float:
    centers = [sector_to_deg(o) for o in orientations]
    return min(angle_diff(direction, c) for c in centers) if centers else 0.0


@dataclass(slots=True)
class TakeoffWind:
    time: datetime
    speed_kmh: float  # vent RETENU (fusion balises + extrapolation de tendance, jamais à la baisse)
    direction_deg: float
    gust_kmh: float
    model_speed_kmh: float
    model_direction_deg: float
    model_gust_kmh: float
    crest_speed_kmh: float
    crest_direction_deg: float
    angle: WindAngle
    nowcast: StationNowcast | None
    hour: HourAnalysis
    fused_speed_kmh: float = 0.0  # fusion modèle + balise, avant extrapolation de la tendance
    fused_gust_kmh: float = 0.0


def model_takeoff_wind(a: HourAnalysis, elevation_m: float) -> tuple[float, float, float]:
    """(vitesse, direction, rafale) au déco : profil interpolé à l'altitude réelle (lot 1.4)."""
    v, d = a.profile.wind(elevation_m)
    v10 = a.wind_speed_kmh
    g10 = a.wind_gust_kmh
    if v10 >= 1.0:
        gust = g10 * (v / v10)
    else:
        gust = v * rules.GUST_FACTOR_DEFAULT
    gust = min(max(gust, v), v + rules.TAKEOFF_GUST_EXTRA_MAX_KMH)
    return v, d, gust


def takeoff_wind(ctx: DataContext, site: Site, timeline: PointTimeline, t: datetime) -> TakeoffWind:
    """Vent retenu au déco à l'instant t (début du créneau) : modèle à l'altitude du déco, corrigé par les balises
    rattachées au déco (poids selon Δt = t − reference_time, §12.1) et la tendance (§12.2)."""
    a = timeline.at(t)
    mv, md, mg = model_takeoff_wind(a, site.elevation_m)
    nc = station_nowcast(ctx, site, "takeoff", timeline, t)
    fv, d, fg, v, g = fuse(nc, mv, md, mg, ctx.horizon)
    cv, cd = a.profile.wind(site.elevation_m + rules.CREST_CHECK_ABOVE_TAKEOFF_M)
    angle = wind_angle(v, d, site.orientations)
    return TakeoffWind(t, v, d, g, mv, md, mg, cv, cd, angle, nc, a, fv, fg)


@dataclass(slots=True)
class LandingWind:
    time: datetime
    speed_kmh: float  # vent RETENU à l'arrivée (brise + balises de l'atterro + tendance)
    direction_deg: float
    gust_kmh: float
    breeze_factor: float
    hour: HourAnalysis
    model_speed_kmh: float = 0.0  # modèle × brise, sans balise
    model_direction_deg: float = 0.0
    model_gust_kmh: float = 0.0
    fused_speed_kmh: float = 0.0
    fused_gust_kmh: float = 0.0
    nowcast: StationNowcast | None = None


def landing_wind(
    timeline: PointTimeline,
    t: datetime,
    big_valley: bool,
    ctx: DataContext | None = None,
    landing: Site | None = None,
    role: str = "landing",
) -> LandingWind:
    """Vent à l'atterro à l'heure d'arrivée t : modèle × facteur de brise (§4.3), corrigé par les balises de
    l'atterro (poids selon Δt = arrivée − reference_time) puis par la tendance (§12.1-12.2)."""
    a = timeline.at(t)
    factor = breeze_factor(t, big_valley)
    mv, md, mg = a.wind_speed_kmh * factor, a.wind_direction_deg, a.wind_gust_kmh * factor
    nc = None
    if ctx is not None and landing is not None:
        nc = station_nowcast(ctx, landing, role, timeline, t, big_valley)
    fv, d, fg, v, g = fuse(nc, mv, md, mg, ctx.horizon if ctx is not None else "")
    return LandingWind(t, v, d, g, factor, a, mv, md, mg, fv, fg, nc)


def vector_mean(winds: list[tuple[float, float]]) -> tuple[float, float]:
    us = vs = 0.0
    for s, d in winds:
        u, v = wind_components(s, d)
        us += u
        vs += v
    n = max(1, len(winds))
    return wind_from_components(us / n, vs / n)


def along_track_component(speed: float, direction_from: float, track_deg: float) -> float:
    """Composante du vent le long de la route (positive = vent arrière)."""
    to_dir = (direction_from + 180.0) % 360.0
    return speed * math.cos(math.radians(to_dir - track_deg))


_LABELS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"]


def _dir_label(deg: float) -> str:
    return _LABELS[int(((deg % 360) + 11.25) // 22.5) % 16]


def dir_label(deg: float) -> str:
    """Secteur en notation française (O = ouest) pour les textes destinés au pilote."""
    return _dir_label(deg)
