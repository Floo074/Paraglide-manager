"""Relief autour d'un décollage libre (CDC §12.6) et cône de finesse.

- `dem_grid_points` / `analyze_grid` : petite grille MNT (5 × 5, pas de 100 m) autour du point → plan ajusté par
  moindres carrés sur les 3 × 3 points centraux (± 100 m) : pente du plan et exposition (direction vers laquelle
  la pente fait face = direction de plus grande descente).
- `axis_points` / `takeoff_terrain` : pente moyenne sur les 150 m sous le point dans la ligne de plus grande pente
  (un point tous les 50 m) et profil dans l'axe de décollage sur 300 m (aucun point au-dessus de alt − d/6).
- `orientations_from_aspect` : secteurs de la rose 16 points à ± 22,5° de l'exposition.
- `glide_cone` : polygone de la zone atteignable en plané (finesse de calcul du niveau, vent compris, marge
  d'arrivée), raccourci là où la ligne de plané touche le relief.

Fonctions pures (aucun appel réseau) : les altitudes sont fournies par l'appelant (`DataService`).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from app.engine import rules
from app.geo import angle_diff, destination
from app.models import COMPASS_16

GRID_N = rules.FREE_TAKEOFF_DEM["grid_n"]
GRID_STEP_M = rules.FREE_TAKEOFF_DEM["grid_step_m"]


@dataclass(slots=True)
class TakeoffTerrain:
    """Lecture du MNT au point de décollage libre (valeurs imposées dans les scénarios de test)."""

    elevation_m: float | None  # altitude MNT au point
    slope_pct: float | None  # pente moyenne sur 150 m sous le point (ligne de plus grande pente)
    aspect_deg: float | None  # direction vers laquelle la pente fait face
    profile_ok: bool | None = None  # profil dans l'axe sur 300 m : None = non contrôlé (MNT indisponible)
    profile_detail: str | None = None  # « bosse à 150 m (12 m au-dessus de la ligne alt − d/6) »
    axis_deg: float | None = None  # axe de décollage retenu (orientations du pilote, sinon exposition)
    source: str = "dem"  # dem (Open-Meteo / Copernicus 90 m) | demo (MNT de démonstration) | scenario | none
    notes: list[str] = field(default_factory=list)

    @property
    def measured(self) -> bool:
        return self.slope_pct is not None and self.aspect_deg is not None


def _offset(lat: float, lon: float, dx_m: float, dy_m: float) -> tuple[float, float]:
    ky = 111_320.0
    kx = 111_320.0 * max(0.05, math.cos(math.radians(lat)))
    return round(lat + dy_m / ky, 6), round(lon + dx_m / kx, 6)


def dem_grid_points(lat: float, lon: float, n: int = GRID_N, step_m: float = GRID_STEP_M) -> list[tuple[float, float]]:
    """Grille n × n centrée sur le point, ligne par ligne du sud au nord, d'ouest en est."""
    h = (n - 1) / 2.0
    return [_offset(lat, lon, (i - h) * step_m, (j - h) * step_m) for j in range(n) for i in range(n)]


def plane_fit(z: list[float], n: int, step_m: float, inner: int | None = None) -> tuple[float, float]:
    """Plan z = a·x + b·y + c (x vers l'est, y vers le nord, en m) ajusté par moindres carrés sur les `inner` × `inner`
    points centraux d'une grille n × n ; renvoie (dz/dx, dz/dy)."""
    k = inner or n
    off = (n - k) // 2
    h = (n - 1) / 2.0
    sx = sy = sxx = syy = sxy = sz = sxz = syz = 0.0
    m = 0
    for j in range(off, off + k):
        for i in range(off, off + k):
            x, y, zz = (i - h) * step_m, (j - h) * step_m, z[j * n + i]
            sx += x
            sy += y
            sxx += x * x
            syy += y * y
            sxy += x * y
            sz += zz
            sxz += x * zz
            syz += y * zz
            m += 1
    # grille symétrique centrée : sx = sy = sxy = 0
    a = sxz / sxx if sxx else 0.0
    b = syz / syy if syy else 0.0
    return a, b


def analyze_grid(z: list[float], n: int = GRID_N, step_m: float = GRID_STEP_M) -> tuple[float, float]:
    """(pente du plan en %, exposition en degrés) : plan des 3 × 3 points centraux (± 1 pas), ou de la grille entière
    si le centre est presque plat (< 5 %)."""
    a, b = plane_fit(z, n, step_m, inner=3 if n >= 3 else n)
    if math.hypot(a, b) < 0.05 and n > 3:
        a, b = plane_fit(z, n, step_m)
    slope = math.hypot(a, b) * 100.0
    aspect = (math.degrees(math.atan2(-a, -b)) + 360.0) % 360.0  # direction de plus grande descente
    return slope, aspect


def orientations_from_aspect(aspect_deg: float, halfwidth: float = rules.FREE_TAKEOFF["orientation_halfwidth_deg"]):
    """Secteurs (rose 16 points) dont le centre est à ± `halfwidth` de l'exposition (bornes comprises)."""
    out = [s for i, s in enumerate(COMPASS_16) if angle_diff(i * 22.5, aspect_deg) <= halfwidth + 1e-6]
    return out or [COMPASS_16[int(((aspect_deg % 360) + 11.25) // 22.5) % 16]]


def axis_points(lat: float, lon: float, bearing: float, distances_m: list[float]) -> list[tuple[float, float]]:
    out = []
    for d in distances_m:
        la, lo = destination(lat, lon, bearing, d / 1000.0)
        out.append((round(la, 6), round(lo, 6)))
    return out


def slope_distances() -> list[float]:
    s = rules.FREE_TAKEOFF["slope_sampling"]
    return [float(d) for d in range(s["step_m"], s["downslope_m"] + 1, s["step_m"])]


def profile_distances() -> list[float]:
    s = rules.FREE_TAKEOFF["slope_sampling"]
    p = rules.FREE_TAKEOFF["axis_profile"]
    return [float(d) for d in range(s["step_m"], p["distance_m"] + 1, s["step_m"])]


def downslope_slope_pct(z0: float, z_line: list[float], distances_m: list[float]) -> float:
    """Pente moyenne (%) entre le point et le dernier point de la ligne de pente (150 m)."""
    if not z_line:
        return 0.0
    return max(0.0, (z0 - z_line[-1]) / distances_m[-1] * 100.0)


def axis_profile(z0: float, z_axis: list[float], distances_m: list[float]) -> tuple[bool, str | None]:
    """Aucun point du MNT au-dessus de la droite alt − d/6 sur 300 m dans l'axe (bosse, contre-pente)."""
    k = rules.FREE_TAKEOFF["axis_profile"]["max_slope_line"]
    worst: tuple[float, float] | None = None
    for d, z in zip(distances_m, z_axis, strict=False):
        excess = z - (z0 - d * k)
        if excess > 0 and (worst is None or excess > worst[1]):
            worst = (d, excess)
    if worst is None:
        return True, None
    return False, (
        f"terrain {worst[1]:.0f} m au-dessus de la ligne de décollage (pente 1/6) à {worst[0]:.0f} m dans l'axe"
    )


def axis_from_orientations(orientations: list[str]) -> float | None:
    if not orientations:
        return None
    xs = sum(math.sin(math.radians(COMPASS_16.index(o) * 22.5)) for o in orientations)
    ys = sum(math.cos(math.radians(COMPASS_16.index(o) * 22.5)) for o in orientations)
    if abs(xs) < 1e-9 and abs(ys) < 1e-9:
        return None
    return (math.degrees(math.atan2(xs, ys)) + 360.0) % 360.0


# ---------------------------------------------------------------------------------------------
# Cône de finesse
# ---------------------------------------------------------------------------------------------
def glide_cone(
    lat: float,
    lon: float,
    alt: float,
    finesse: Callable[[float], float],
    terrain: Callable[[float, float], float | None] | None,
    margin_m: float,
    floor_m: float,
    bearings: int = rules.GLIDE_CONE["bearings"],
    step_km: float = rules.GLIDE_CONE["step_km"],
    max_km: float = rules.GLIDE_CONE["max_km"],
) -> list[tuple[float, float]]:
    """Anneau (lon, lat) de la zone atteignable. Sur chaque cap, on avance pas à pas : un point est atteignable si
    l'altitude de plané alt − d / finesse(cap) y dépasse le sol + `margin_m` (marge d'arrivée), et si la ligne de
    plané est restée à plus de TERRAIN_CLEARANCE_M du relief depuis 0,5 km (sinon le relief coupe le plané : on
    s'arrête). Sol = MNT, ou `floor_m` sans MNT. `finesse(cap)` = finesse de calcul sol du niveau, vent compris
    (plus longue sous le vent : le cône est décalé sous le vent)."""
    ring: list[tuple[float, float]] = []
    for k in range(bearings):
        brg = k * 360.0 / bearings
        fs = max(0.5, finesse(brg))
        limit = min(max_km, max(0.0, (alt - floor_m - margin_m) * fs / 1000.0))
        reach = limit if terrain is None else 0.0
        d = step_km
        while terrain is not None and d <= max_km + 1e-9:
            la, lo = destination(lat, lon, brg, d)
            ground = terrain(la, lo)
            ground = floor_m if ground is None else ground
            glide_alt = alt - d * 1000.0 / fs
            if d >= rules.GLIDE_CONE["clearance_from_km"] and glide_alt < ground + rules.TERRAIN_CLEARANCE_M:
                break  # le relief coupe la ligne de plané
            if glide_alt >= ground + margin_m:
                reach = d
            if glide_alt < floor_m:
                break
            d += step_km
        la, lo = destination(lat, lon, brg, max(reach, 0.05))
        ring.append((round(lo, 5), round(la, 5)))
    ring.append(ring[0])
    return ring


def cone_geojson(ring: list[tuple[float, float]]) -> dict:
    return {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}
