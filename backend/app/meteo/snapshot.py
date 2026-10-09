"""Conversion des analyses internes vers les objets du contrat (WeatherSnapshot, SoundingLevel…)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.geo import wind_from_components
from app.meteo.thermals import HourAnalysis
from app.models import NowcastCorrection, SoundingLevel, WeatherSnapshot, Wind10m, WindLevel

ALOFT_ALTITUDES_M = (1000, 1500, 2000, 2500, 3000, 3500, 4000, 5000)


def iso(t: datetime) -> str:
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _r(x: float | None, nd: int = 1) -> float | None:
    return None if x is None else round(float(x), nd)


def snapshot_from_analysis(
    a: HourAnalysis,
    model_label: str,
    wind_override: tuple[float, float, float] | None = None,
    nowcast: NowcastCorrection | None = None,
) -> WeatherSnapshot:
    """`wind_override` = (vitesse, direction, rafale) retenus au site (plans de vol, lot expert 5.4)."""
    speed, direction, gust = (
        wind_override if wind_override is not None else (a.wind_speed_kmh, a.wind_direction_deg, a.wind_gust_kmh)
    )
    aloft: list[WindLevel] = []
    for z in ALOFT_ALTITUDES_M:
        if z < a.ground_m + 50:
            continue
        s, d = a.profile.wind(z)
        aloft.append(
            WindLevel(
                altitude_m=z,
                pressure_hpa=round(a.profile.pressure(z), 0),
                speed_kmh=round(s, 1),
                direction_deg=round(d),
            )
        )
    return WeatherSnapshot(
        time=iso(a.time),
        model=model_label,
        lat=round(a.lat, 5),
        lon=round(a.lon, 5),
        elevation_m=round(a.ground_m),
        temperature_c=round(a.temperature_c, 1),
        dew_point_c=round(a.dew_point_c, 1),
        wind_10m=Wind10m(speed_kmh=round(speed, 1), direction_deg=round(direction) % 360, gust_kmh=round(gust, 1)),
        winds_aloft=aloft,
        cloud_cover_pct=round(a.cloud_cover_pct),
        cloud_cover_low_pct=round(a.cloud_cover_low_pct),
        precipitation_mm_h=round(a.precipitation_mm_h, 2),
        cape_j_kg=round(a.cape_j_kg),
        lifted_index=_r(a.lifted_index),
        cin_j_kg=_r(a.cin_j_kg, 0),
        freezing_level_m=_r(a.freezing_level_m, 0),
        boundary_layer_height_agl_m=round(a.blh_agl_m),
        thermal_ceiling_m=round(a.thermal_ceiling_m),
        cloud_base_m=None if a.cloud_base_m is None else round(a.cloud_base_m),
        thermal_strength_ms=round(a.thermal_strength_ms, 1),
        wstar_ms=round(a.wstar_ms, 2),
        shortwave_radiation_w_m2=round(a.shortwave_w_m2),
        nowcast_correction=nowcast,
    )


def sounding_from_analysis(a: HourAnalysis) -> list[SoundingLevel]:
    out = []
    for pt in a.profile.points:
        s, d = wind_from_components(pt.u, pt.v)
        out.append(
            SoundingLevel(
                pressure_hpa=round(pt.p, 1),
                altitude_m=round(pt.z),
                temperature_c=round(pt.t, 1),
                dew_point_c=round(pt.td, 1),
                wind_speed_kmh=round(s, 1),
                wind_direction_deg=round(d) % 360,
            )
        )
    # le vent du profil thermodynamique n'inclut pas forcément le point « sol lissé » : on aligne
    for lv in out:
        s, d = a.profile.wind(lv.altitude_m)
        lv.wind_speed_kmh = round(s, 1)
        lv.wind_direction_deg = round(d) % 360
    return out
