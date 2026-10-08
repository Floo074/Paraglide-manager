"""Fournisseurs du mode mock : météo synthétique (3 membres) et MNT synthétique."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.meteo.types import ModelSeries, PointForecast
from app.providers.synthetic_terrain import terrain_elevation
from app.providers.synthetic_weather import MEMBERS, SyntheticWeather


class SyntheticForecast:
    name = "Météo synthétique (démo)"

    def __init__(self, forced_scenario: str | None = None) -> None:
        self.weather = SyntheticWeather(forced_scenario)

    def fetch_sync(
        self,
        points: list[tuple[float, float, float | None]],
        start: datetime,
        end: datetime,
        issued_at: datetime | None = None,
        members: int = 3,
    ) -> list[PointForecast]:
        out = []
        fetched = datetime.now(UTC)
        n_hours = int((end - start).total_seconds() // 3600) + 1
        for lat, lon, elev in points:
            ground = elev if elev is not None else terrain_elevation(lat, lon)
            series = []
            for m in range(members):
                hours = [
                    self.weather.hour(lat, lon, ground, start + timedelta(hours=i), member=m, issued_at=issued_at)
                    for i in range(n_hours)
                ]
                series.append(ModelSeries(model=MEMBERS[m], lat=lat, lon=lon, elevation_m=ground, hours=hours))
            out.append(
                PointForecast(
                    lat=lat,
                    lon=lon,
                    elevation_m=ground,
                    models=series,
                    mode="mock",
                    source_name=self.name,
                    source_url=None,
                    fetched_at=fetched,
                )
            )
        return out

    async def fetch(self, points, start, end, issued_at=None, members: int = 3) -> list[PointForecast]:
        return self.fetch_sync(points, start, end, issued_at, members)


class SyntheticElevation:
    name = "MNT synthétique (démo)"

    async def fetch(self, points: list[tuple[float, float]]) -> list[float]:
        return [terrain_elevation(lat, lon) for lat, lon in points]
