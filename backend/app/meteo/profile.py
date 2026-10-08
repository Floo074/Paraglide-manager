"""Profil vertical (sondage) construit à partir des niveaux de pression d'un modèle.

Les niveaux situés sous le sol (extrapolés par les modèles en montagne) sont ignorés ; le niveau
« 2 m » au sol est inséré en premier. L'interpolation est linéaire en altitude pour T/Td et sur les
composantes (u, v) pour le vent ; logarithmique pour la pression.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass

from app.geo import wind_components, wind_from_components
from app.meteo.thermo import std_pressure_hpa
from app.meteo.types import HourData, LevelData


@dataclass(slots=True)
class ProfilePoint:
    z: float
    p: float
    t: float
    td: float
    u: float
    v: float


class VerticalProfile:
    def __init__(self, points: list[ProfilePoint], ground_m: float) -> None:
        if not points:
            raise ValueError("profil vide")
        self.points = sorted(points, key=lambda pt: pt.z)
        self.ground_m = ground_m
        self._zs = [pt.z for pt in self.points]

    @classmethod
    def from_hour(cls, hour: HourData, ground_m: float) -> VerticalProfile:
        pts: list[ProfilePoint] = []
        t2 = hour.temperature_2m
        td2 = hour.dew_point_2m
        if t2 is not None:
            u, v = wind_components(hour.wind_speed_10m or 0.0, hour.wind_direction_10m or 0.0)
            pts.append(
                ProfilePoint(
                    z=ground_m,
                    p=std_pressure_hpa(ground_m),
                    t=t2,
                    td=min(t2, td2 if td2 is not None else t2 - 8.0),
                    u=u,
                    v=v,
                )
            )
        # On garde les niveaux au moins 150 m au-dessus du sol (sinon trop influencés par l'extrapolation)
        min_z = ground_m + (150.0 if pts else -1e9)
        for lv in sorted(hour.levels, key=lambda lv_: lv_.height_m):
            if lv.height_m < min_z:
                continue
            u, v = wind_components(lv.wind_speed_kmh, lv.wind_direction_deg)
            pts.append(
                ProfilePoint(
                    z=lv.height_m,
                    p=lv.pressure_hpa,
                    t=lv.temperature_c,
                    td=min(lv.temperature_c, lv.dew_point_c),
                    u=u,
                    v=v,
                )
            )
        if not pts:
            raise ValueError("aucune donnée de profil")
        if len(pts) == 1:
            # Pas de niveaux de pression : atmosphère standard humide au-dessus du sol
            base = pts[0]
            for dz in (500.0, 1000.0, 2000.0, 3000.0, 4500.0):
                pts.append(
                    ProfilePoint(
                        z=base.z + dz,
                        p=std_pressure_hpa(base.z + dz),
                        t=base.t - 0.0065 * dz,
                        td=base.td - 0.0065 * dz - 0.001 * dz,
                        u=base.u * (1 + dz / 2000.0),
                        v=base.v * (1 + dz / 2000.0),
                    )
                )
        return cls(pts, ground_m)

    @property
    def top_m(self) -> float:
        return self._zs[-1]

    def _bracket(self, z: float) -> tuple[ProfilePoint, ProfilePoint, float]:
        zs = self._zs
        if z <= zs[0]:
            a, b = self.points[0], self.points[min(1, len(self.points) - 1)]
        elif z >= zs[-1]:
            a, b = self.points[-2] if len(self.points) > 1 else self.points[-1], self.points[-1]
        else:
            i = bisect.bisect_right(zs, z)
            a, b = self.points[i - 1], self.points[i]
        if b.z == a.z:
            return a, b, 0.0
        return a, b, (z - a.z) / (b.z - a.z)

    def temperature(self, z: float) -> float:
        a, b, f = self._bracket(z)
        if z > self._zs[-1]:
            # extrapolation au-dessus du dernier niveau : gradient standard
            return self.points[-1].t - 0.0065 * (z - self._zs[-1])
        if z < self._zs[0]:
            return self.points[0].t
        return a.t + f * (b.t - a.t)

    def dew_point(self, z: float) -> float:
        a, b, f = self._bracket(z)
        if z > self._zs[-1]:
            return self.points[-1].td - 0.008 * (z - self._zs[-1])
        if z < self._zs[0]:
            return self.points[0].td
        return a.td + f * (b.td - a.td)

    def pressure(self, z: float) -> float:
        a, b, f = self._bracket(z)
        if a.p <= 0 or b.p <= 0 or a.z == b.z:
            return std_pressure_hpa(z)
        if z < self._zs[0] or z > self._zs[-1]:
            return std_pressure_hpa(z) * (a.p / std_pressure_hpa(a.z))
        return math.exp(math.log(a.p) + f * (math.log(b.p) - math.log(a.p)))

    def wind(self, z: float) -> tuple[float, float]:
        """(vitesse km/h, direction °) à l'altitude z."""
        if z <= self._zs[0]:
            p = self.points[0]
            return wind_from_components(p.u, p.v)
        if z >= self._zs[-1]:
            p = self.points[-1]
            return wind_from_components(p.u, p.v)
        a, b, f = self._bracket(z)
        return wind_from_components(a.u + f * (b.u - a.u), a.v + f * (b.v - a.v))

    def wind_uv(self, z: float) -> tuple[float, float]:
        s, d = self.wind(z)
        return wind_components(s, d)

    def mean_wind(self, z_bottom: float, z_top: float, step: float = 100.0) -> tuple[float, float]:
        """Vent moyen vectoriel sur une couche."""
        if z_top <= z_bottom:
            return self.wind(z_bottom)
        n = max(2, int((z_top - z_bottom) / step) + 1)
        us = vs = 0.0
        for i in range(n):
            u, v = self.wind_uv(z_bottom + (z_top - z_bottom) * i / (n - 1))
            us += u
            vs += v
        return wind_from_components(us / n, vs / n)

    def max_wind(self, z_bottom: float, z_top: float, step: float = 100.0) -> float:
        n = max(2, int((z_top - z_bottom) / step) + 1)
        return max(self.wind(z_bottom + (z_top - z_bottom) * i / (n - 1))[0] for i in range(n))

    def mean_rh(self, z_bottom: float, z_top: float, step: float = 200.0) -> float:
        from app.meteo.thermo import rh_from_dew_point

        n = max(2, int((z_top - z_bottom) / step) + 1)
        vals = []
        for i in range(n):
            z = z_bottom + (z_top - z_bottom) * i / (n - 1)
            vals.append(rh_from_dew_point(self.temperature(z), self.dew_point(z)))
        return sum(vals) / len(vals)

    def isotherm_height(self, t_c: float) -> float | None:
        """Première altitude (au-dessus du sol) où la température passe sous t_c."""
        pts = self.points
        if pts[0].t <= t_c:
            return pts[0].z
        for a, b in zip(pts, pts[1:], strict=False):
            if a.t > t_c >= b.t:
                return a.z + (a.t - t_c) / (a.t - b.t) * (b.z - a.z)
        last = pts[-1]
        # extrapolation au gradient standard
        return last.z + (last.t - t_c) / 0.0065

    def levels(self) -> list[ProfilePoint]:
        return list(self.points)


def levels_from_profile(profile: VerticalProfile) -> list[LevelData]:
    out = []
    for pt in profile.points:
        s, d = wind_from_components(pt.u, pt.v)
        out.append(LevelData(pt.p, pt.z, pt.t, pt.td, s, d))
    return out
