"""Outils géographiques : distances, caps, rose des vents, projection locale."""

from __future__ import annotations

import math
from collections.abc import Iterable

from app.models import COMPASS_16

EARTH_RADIUS_KM = 6371.0088

# Correspondances des orientations françaises/anglaises vers la rose 16 points
_FR_TO_EN = {"O": "W", "NO": "NW", "SO": "SW", "ONO": "WNW", "OSO": "WSW", "NNO": "NNW", "SSO": "SSW"}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Cap initial (0 = N, sens horaire) de 1 vers 2."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def destination(lat: float, lon: float, bearing: float, distance_km: float) -> tuple[float, float]:
    """Point à `distance_km` dans la direction `bearing` (grand cercle)."""
    d = distance_km / EARTH_RADIUS_KM
    b = math.radians(bearing)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540.0) % 360.0 - 180.0


def angle_diff(a: float, b: float) -> float:
    """Écart angulaire absolu 0..180°."""
    d = abs((a - b) % 360.0)
    return 360.0 - d if d > 180.0 else d


def signed_angle_diff(a: float, b: float) -> float:
    """a - b ramené dans ]-180, 180]."""
    d = (a - b + 180.0) % 360.0 - 180.0
    return 180.0 if d == -180.0 else d


def sector_to_deg(sector: str) -> float:
    s = normalize_sector(sector)
    return COMPASS_16.index(s) * 22.5


def deg_to_sector(deg: float) -> str:
    return COMPASS_16[int(((deg % 360.0) + 11.25) // 22.5) % 16]


def normalize_sector(sector: str) -> str:
    s = sector.strip().upper()
    s = _FR_TO_EN.get(s, s)
    if s not in COMPASS_16:
        raise ValueError(f"secteur inconnu : {sector}")
    return s


def parse_orientations(raw: str | Iterable[str] | None) -> list[str]:
    """Analyse des orientations « N;NE », « SO,O », « N-NE », listes… → secteurs 16 points uniques."""
    if raw is None:
        return []
    if isinstance(raw, str):
        tokens = [t for t in _split_tokens(raw) if t]
    else:
        tokens = [str(t) for t in raw]
    out: list[str] = []
    for t in tokens:
        try:
            s = normalize_sector(t)
        except ValueError:
            continue
        if s not in out:
            out.append(s)
    return sorted(out, key=COMPASS_16.index)


def _split_tokens(raw: str) -> list[str]:
    for sep in [";", ",", "/", "-", "|", " "]:
        raw = raw.replace(sep, " ")
    return raw.split()


def km_per_deg(lat: float) -> tuple[float, float]:
    """(km par degré de latitude, km par degré de longitude) à la latitude donnée."""
    return 111.32, 111.32 * math.cos(math.radians(lat))


class LocalProjection:
    """Projection équirectangulaire locale (km), suffisante à l'échelle d'une zone de vol."""

    def __init__(self, lat0: float, lon0: float) -> None:
        self.lat0 = lat0
        self.lon0 = lon0
        self.ky, self.kx = km_per_deg(lat0)

    def to_xy(self, lat: float, lon: float) -> tuple[float, float]:
        return (lon - self.lon0) * self.kx, (lat - self.lat0) * self.ky

    def to_latlon(self, x: float, y: float) -> tuple[float, float]:
        return self.lat0 + y / self.ky, self.lon0 + x / self.kx


def wind_components(speed: float, direction_from_deg: float) -> tuple[float, float]:
    """(u, v) vers où souffle le vent (u vers l'est, v vers le nord)."""
    rad = math.radians(direction_from_deg)
    return -speed * math.sin(rad), -speed * math.cos(rad)


def wind_from_components(u: float, v: float) -> tuple[float, float]:
    """(vitesse, direction d'où vient le vent)."""
    speed = math.hypot(u, v)
    if speed < 1e-9:
        return 0.0, 0.0
    direction = (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0
    return speed, direction


def point_in_bbox(lat: float, lon: float, bbox: tuple[float, float, float, float], margin_km: float = 0) -> bool:
    min_lon, min_lat, max_lon, max_lat = bbox
    if margin_km:
        ky, kx = km_per_deg(lat)
        dlat, dlon = margin_km / ky, margin_km / max(kx, 1e-6)
        min_lat, max_lat, min_lon, max_lon = min_lat - dlat, max_lat + dlat, min_lon - dlon, max_lon + dlon
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


def expand_bbox(bbox: tuple[float, float, float, float], margin_km: float) -> tuple[float, float, float, float]:
    min_lon, min_lat, max_lon, max_lat = bbox
    ky, kx = km_per_deg((min_lat + max_lat) / 2)
    dlat, dlon = margin_km / ky, margin_km / max(kx, 1e-6)
    return min_lon - dlon, min_lat - dlat, max_lon + dlon, max_lat + dlat


def parse_bbox(raw: str) -> tuple[float, float, float, float]:
    """« min_lon,min_lat,max_lon,max_lat » → tuple, avec validation."""
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox attendu : min_lon,min_lat,max_lon,max_lat")
    min_lon, min_lat, max_lon, max_lat = (float(p) for p in parts)
    if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
        raise ValueError("bbox invalide (min doit être < max, coordonnées WGS84)")
    return min_lon, min_lat, max_lon, max_lat
