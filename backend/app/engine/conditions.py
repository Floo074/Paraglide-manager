"""Conditions au décollage / à l'atterrissage à un instant donné (vent interpolé, nowcasting, brise)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.engine import rules
from app.engine.context import DataContext, PointTimeline
from app.geo import angle_diff, haversine_km, sector_to_deg, signed_angle_diff, wind_components, wind_from_components
from app.meteo.solar import solar_local_hour, sunrise_sunset
from app.meteo.thermals import HourAnalysis
from app.models import Beacon, Site

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
    tail = speed * max(0.0, -math.cos(math.radians(raw))) if cat == "tail" else 0.0
    return WindAngle(ecart, raw, calm, cat, cross, tail)


def lee_angle(direction: float, orientations: list[str]) -> float:
    centers = [sector_to_deg(o) for o in orientations]
    return min(angle_diff(direction, c) for c in centers) if centers else 0.0


@dataclass(slots=True)
class Nowcast:
    beacon_ids: list[str]
    speed_bias_kmh: float
    dir_bias_deg: float
    weight: float
    max_gust_kmh: float | None
    mismatch: bool
    coherent: bool
    details: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TakeoffWind:
    time: datetime
    speed_kmh: float
    direction_deg: float
    gust_kmh: float
    model_speed_kmh: float
    model_direction_deg: float
    model_gust_kmh: float
    crest_speed_kmh: float
    crest_direction_deg: float
    angle: WindAngle
    nowcast: Nowcast | None
    hour: HourAnalysis


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


def compute_nowcast(
    ctx: DataContext, site: Site, timeline: PointTimeline, t: datetime, model_v: float, model_d: float
) -> Nowcast | None:
    horizon_min = (ctx.target_time - ctx.reference_time).total_seconds() / 60.0
    weight_h = rules.HORIZON_BEACON_WEIGHT.get(ctx.horizon, 0.0)
    if weight_h <= 0 or horizon_min > rules.NOWCAST_MAX_HORIZON_MIN + 1:
        return None
    used: list[tuple[Beacon, float, float, float]] = []  # beacon, w, dv, dd
    gusts: list[float] = []
    details: list[str] = []
    a = timeline.at(t)
    for b in ctx.beacons:
        if b.stale or b.wind_speed_kmh is None or b.wind_direction_deg is None:
            continue
        d_km = haversine_km(site.lat, site.lon, b.lat, b.lon)
        if d_km > rules.BEACON_MAX_DISTANCE_KM:
            continue
        b_elev = b.elevation_m if b.elevation_m is not None else ctx.terrain_at(b.lat, b.lon)
        w = 1.0
        if b_elev is None or abs(b_elev - site.elevation_m) > rules.BEACON_MAX_ALT_DIFF_M:
            w *= 0.5
        age = ctx.beacon_ages_min.get(b.id, 0.0)
        w *= max(0.1, 1.0 - age / rules.BEACON_STALE_MIN)
        # vent modèle à l'altitude de la balise
        if b_elev is not None and abs(b_elev - site.elevation_m) > 50:
            mv, md = a.profile.wind(b_elev)
        else:
            mv, md = model_v, model_d
        dv = b.wind_speed_kmh - mv
        dd = signed_angle_diff(b.wind_direction_deg, md) if b.wind_speed_kmh >= rules.CALM_WIND_KMH else 0.0
        used.append((b, w, dv, dd))
        if b.wind_gust_kmh is not None:
            gusts.append(b.wind_gust_kmh)
        details.append(
            f"{b.name} : {b.wind_speed_kmh:.0f} km/h ({b.wind_gust_kmh or 0:.0f} en rafales) du "
            f"{_dir_label(b.wind_direction_deg)} contre {mv:.0f} km/h du {_dir_label(md)} prévus"
        )
    if not used:
        return None
    sw = sum(w for _, w, _, _ in used)
    dv = sum(w * x for _, w, x, _ in used) / sw
    dd = sum(w * x for _, w, _, x in used) / sw
    dv = max(-rules.NOWCAST_MAX_SPEED_BIAS_KMH, min(rules.NOWCAST_MAX_SPEED_BIAS_KMH, dv))
    dd = max(-rules.NOWCAST_MAX_DIR_BIAS_DEG, min(rules.NOWCAST_MAX_DIR_BIAS_DEG, dd))
    mismatch = abs(dv) > rules.BEACON_CONTRADICTION_KMH or abs(dd) > rules.BEACON_CONTRADICTION_DEG
    coherent = abs(dv) < rules.BEACON_COHERENT_KMH and abs(dd) < rules.BEACON_COHERENT_DEG
    return Nowcast(
        beacon_ids=[b.id for b, *_ in used],
        speed_bias_kmh=dv,
        dir_bias_deg=dd,
        weight=weight_h,
        max_gust_kmh=max(gusts) if gusts else None,
        mismatch=mismatch,
        coherent=coherent,
        details=details,
    )


def takeoff_wind(ctx: DataContext, site: Site, timeline: PointTimeline, t: datetime) -> TakeoffWind:
    a = timeline.at(t)
    mv, md, mg = model_takeoff_wind(a, site.elevation_m)
    v, d, g = mv, md, mg
    nc = compute_nowcast(ctx, site, timeline, t, mv, md)
    if nc is not None:
        v = max(0.0, mv + nc.weight * nc.speed_bias_kmh)
        d = (md + nc.weight * nc.dir_bias_deg) % 360.0
        g = max(v, mg * (v / mv) if mv > 1 else v * rules.GUST_FACTOR_DEFAULT)
        if nc.max_gust_kmh is not None and ctx.horizon in rules.BEACON_GUST_HORIZONS:
            g = max(g, nc.max_gust_kmh)
    cv, cd = a.profile.wind(site.elevation_m + rules.CREST_CHECK_ABOVE_TAKEOFF_M)
    angle = wind_angle(v, d, site.orientations)
    return TakeoffWind(t, v, d, g, mv, md, mg, cv, cd, angle, nc, a)


@dataclass(slots=True)
class LandingWind:
    time: datetime
    speed_kmh: float
    direction_deg: float
    gust_kmh: float
    breeze_factor: float
    hour: HourAnalysis


def landing_wind(timeline: PointTimeline, t: datetime, big_valley: bool) -> LandingWind:
    a = timeline.at(t)
    factor = 1.0
    lh = legal_time(t).hour + legal_time(t).minute / 60.0
    h0, h1 = rules.VALLEY_BREEZE_HOURS_LEGAL
    if big_valley:
        if h0 <= lh < h1:
            factor = rules.VALLEY_BREEZE_AFTERNOON_FACTOR
        elif any(r0 <= lh < r1 for r0, r1 in rules.VALLEY_BREEZE_RAMP_HOURS_LEGAL):
            factor = rules.VALLEY_BREEZE_RAMP_FACTOR
    return LandingWind(t, a.wind_speed_kmh * factor, a.wind_direction_deg, a.wind_gust_kmh * factor, factor, a)


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
