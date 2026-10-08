"""Position du soleil, lever/coucher, rayonnement ciel clair (algorithme NOAA simplifié)."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta


def _julian_century(dt: datetime) -> float:
    jd = dt.timestamp() / 86400.0 + 2440587.5
    return (jd - 2451545.0) / 36525.0


def _declination_and_eot(dt: datetime) -> tuple[float, float]:
    """(déclinaison en radians, équation du temps en minutes)."""
    t = _julian_century(dt)
    l0 = math.radians((280.46646 + t * (36000.76983 + t * 0.0003032)) % 360)
    m = math.radians(357.52911 + t * (35999.05029 - 0.0001537 * t))
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    c = (
        math.sin(m) * (1.914602 - t * (0.004817 + 0.000014 * t))
        + math.sin(2 * m) * (0.019993 - 0.000101 * t)
        + math.sin(3 * m) * 0.000289
    )
    true_long = l0 + math.radians(c)
    omega = math.radians(125.04 - 1934.136 * t)
    app_long = true_long - math.radians(0.00569 + 0.00478 * math.sin(omega))
    eps0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
    eps = math.radians(eps0 + 0.00256 * math.cos(omega))
    decl = math.asin(math.sin(eps) * math.sin(app_long))
    y = math.tan(eps / 2) ** 2
    eot = 4 * math.degrees(
        y * math.sin(2 * l0)
        - 2 * e * math.sin(m)
        + 4 * e * y * math.sin(m) * math.cos(2 * l0)
        - 0.5 * y * y * math.sin(4 * l0)
        - 1.25 * e * e * math.sin(2 * m)
    )
    return decl, eot


def sun_elevation_deg(dt: datetime, lat: float, lon: float) -> float:
    """Hauteur du soleil au-dessus de l'horizon (degrés)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    decl, eot = _declination_and_eot(dt)
    minutes = dt.hour * 60 + dt.minute + dt.second / 60
    true_solar = (minutes + eot + 4 * lon) % 1440
    ha = math.radians(true_solar / 4 - 180)
    phi = math.radians(lat)
    cos_zen = math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(ha)
    return 90.0 - math.degrees(math.acos(max(-1.0, min(1.0, cos_zen))))


def sun_azimuth_deg(dt: datetime, lat: float, lon: float) -> float:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    decl, eot = _declination_and_eot(dt)
    minutes = dt.hour * 60 + dt.minute + dt.second / 60
    true_solar = (minutes + eot + 4 * lon) % 1440
    ha = math.radians(true_solar / 4 - 180)
    phi = math.radians(lat)
    az = math.atan2(math.sin(ha), math.cos(ha) * math.sin(phi) - math.tan(decl) * math.cos(phi))
    return (math.degrees(az) + 180.0) % 360.0


def sunrise_sunset(day: date, lat: float, lon: float) -> tuple[datetime | None, datetime | None]:
    """Lever et coucher du soleil (UTC) ; None si jour/nuit polaire."""
    noon = datetime(day.year, day.month, day.day, 12, tzinfo=UTC)
    decl, eot = _declination_and_eot(noon)
    phi = math.radians(lat)
    cos_ha = (math.cos(math.radians(90.833)) - math.sin(phi) * math.sin(decl)) / (
        math.cos(phi) * math.cos(decl)
    )
    if cos_ha > 1 or cos_ha < -1:
        return None, None
    ha = math.degrees(math.acos(cos_ha))
    solar_noon_min = 720 - 4 * lon - eot
    base = datetime(day.year, day.month, day.day, tzinfo=UTC)
    rise = base + timedelta(minutes=solar_noon_min - 4 * ha)
    sset = base + timedelta(minutes=solar_noon_min + 4 * ha)
    return rise, sset


def solar_local_hour(dt: datetime, lon: float) -> float:
    """Heure solaire locale approchée (0..24)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    _, eot = _declination_and_eot(dt)
    minutes = dt.hour * 60 + dt.minute + eot + 4 * lon
    return (minutes / 60.0) % 24.0


def clear_sky_ghi(elev_deg: float, altitude_m: float = 0.0) -> float:
    """Rayonnement global ciel clair (W/m²) — modèle simple (Haurwitz modifié + altitude)."""
    if elev_deg <= 0:
        return 0.0
    cz = math.sin(math.radians(elev_deg))
    ghi = 1098.0 * cz * math.exp(-0.059 / max(cz, 0.02))
    return ghi * (1.0 + 0.08 * altitude_m / 1000.0)


def cloud_attenuation(cloud_cover_pct: float) -> float:
    """Facteur de transmission selon la nébulosité (Kasten & Czeplak)."""
    n = max(0.0, min(1.0, cloud_cover_pct / 100.0))
    return 1.0 - 0.75 * n**3.4
