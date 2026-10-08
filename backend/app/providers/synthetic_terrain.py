"""MNT synthétique déterministe (mode mock) : relief régional lissé + ancrage sur les sites/sommets
des fixtures (interpolation pondérée par l'inverse de la distance). Sert à l'altitude des points de
grille, au sol « lissé » du modèle, à la pente (brises) et au contrôle de dégagement des routes.
"""

from __future__ import annotations

import math
from functools import lru_cache

from app.geo import haversine_km
from app.providers.fixture_data import terrain_anchors

# Massifs (centre lat, centre lon, demi-axe lat, demi-axe lon, altitude moyenne, amplitude)
_MASSIFS = (
    (45.45, 6.60, 1.15, 0.95, 1350.0, 650.0),  # Alpes du Nord
    (44.30, 6.50, 0.75, 0.90, 1250.0, 550.0),  # Alpes du Sud
    (45.50, 2.90, 0.90, 0.80, 850.0, 250.0),  # Massif central
    (44.10, 3.20, 0.40, 0.50, 750.0, 150.0),  # Causses
    (42.80, 0.80, 0.30, 1.50, 1400.0, 600.0),  # Pyrénées
    (46.50, 6.20, 0.40, 0.70, 1000.0, 300.0),  # Jura
)
_PLAIN_M = 150.0


def smooth_noise(lat: float, lon: float, seed: int = 0) -> float:
    """Bruit spatial lisse dans [-1, 1] (somme de sinusoïdes, longueurs d'onde 15-80 km)."""
    s = seed * 1.618
    v = (
        math.sin(lat * 7.1 + lon * 3.3 + s)
        + 0.7 * math.sin(lat * 3.7 - lon * 6.9 + 2.1 * s + 1.3)
        + 0.5 * math.sin(lat * 13.3 + lon * 11.1 + 0.7 * s + 2.9)
    )
    return v / 2.2


def regional_elevation(lat: float, lon: float) -> float:
    elev = _PLAIN_M
    for clat, clon, alat, alon, mean, amp in _MASSIFS:
        d = math.hypot((lat - clat) / alat, (lon - clon) / alon)
        w = math.exp(-(d**4))
        if w > 0.01:
            local = mean + amp * smooth_noise(lat, lon, seed=3)
            elev = max(elev, _PLAIN_M + (local - _PLAIN_M) * w)
    return elev


@lru_cache(maxsize=200_000)
def _terrain_cached(lat_r: float, lon_r: float) -> float:
    lat, lon = lat_r, lon_r
    base = regional_elevation(lat, lon)
    num = den = 0.0
    dmin = 1e9
    for alat, alon, aelev in terrain_anchors():
        if abs(alat - lat) > 0.12 or abs(alon - lon) > 0.16:
            continue
        d = haversine_km(lat, lon, alat, alon)
        dmin = min(dmin, d)
        if d < 8.0:
            w = 1.0 / (d * d + 0.04)
            num += w * aelev
            den += w
    if den == 0:
        return base
    idw = num / den
    blend = math.exp(-((dmin / 3.0) ** 2))
    return max(0.0, base * (1 - blend) + idw * blend)


def terrain_elevation(lat: float, lon: float) -> float:
    """Altitude du terrain (m) — arrondi spatial ~50 m pour le cache."""
    return _terrain_cached(round(lat, 4), round(lon, 4))


def smoothed_terrain(lat: float, lon: float, radius_km: float = 2.5) -> float:
    """Sol « lissé » (moyenne sur un disque), comme l'orographie d'un modèle à 1-3 km."""
    from app.geo import destination

    vals = [terrain_elevation(lat, lon)]
    for b in range(0, 360, 45):
        for r in (radius_km * 0.5, radius_km):
            la, lo = destination(lat, lon, b, r)
            vals.append(terrain_elevation(la, lo))
    return sum(vals) / len(vals)


def terrain_gradient(lat: float, lon: float, step_km: float = 0.4) -> tuple[float, float]:
    """Pente (m/km) vers l'est et vers le nord."""
    dlat = step_km / 111.32
    dlon = step_km / (111.32 * math.cos(math.radians(lat)))
    gx = (terrain_elevation(lat, lon + dlon) - terrain_elevation(lat, lon - dlon)) / (2 * step_km)
    gy = (terrain_elevation(lat + dlat, lon) - terrain_elevation(lat - dlat, lon)) / (2 * step_km)
    return gx, gy
