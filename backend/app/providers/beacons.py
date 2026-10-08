"""Balises vent temps réel : Pioupiou / OpenWindMap (libre), FFVL (clé), fixtures simulées (mock).

Pioupiou — structure réelle constatée (tests/fixtures/pioupiou_live_all.json) :
`{doc, license, attribution, data: [{id, meta: {name}, location: {latitude, longitude, date, success},
measurements: {date, wind_heading, wind_speed_avg, wind_speed_max, wind_speed_min, pressure},
status: {date, snr, state: "on"|"off"}}]}` ; vitesses en km/h, direction d'où vient le vent ;
mesures null fréquentes ; pas d'altitude (parfois dans le nom : « Passage du Croc Sire 1405m »).
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta

import httpx

from app.engine import rules
from app.geo import haversine_km
from app.meteo.snapshot import iso
from app.models import Beacon
from app.providers.base import ProviderDisabled, ProviderError, get_json
from app.providers.fixture_data import fixture_beacons_raw
from app.providers.synthetic_terrain import terrain_elevation
from app.providers.synthetic_weather import SyntheticWeather

_ALT_IN_NAME = re.compile(r"(\d{3,4})\s?m\b", re.IGNORECASE)


def _parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def parse_pioupiou(data, now: datetime) -> list[Beacon]:
    if not isinstance(data, dict) or "data" not in data:
        raise ProviderError("Pioupiou : réponse sans 'data'")
    out: list[Beacon] = []
    for st in data["data"]:
        loc = st.get("location") or {}
        meas = st.get("measurements") or {}
        lat, lon = loc.get("latitude"), loc.get("longitude")
        if lat is None or lon is None or meas.get("wind_speed_avg") is None:
            continue
        observed = _parse_time(meas.get("date"))
        if observed is None:
            continue
        name = ((st.get("meta") or {}).get("name") or f"Pioupiou {st.get('id')}").strip()
        m = _ALT_IN_NAME.search(name)
        elev = float(m.group(1)) if m else None
        state_on = (st.get("status") or {}).get("state", "on") == "on"
        age_min = (now - observed).total_seconds() / 60.0
        out.append(
            Beacon(
                id=f"pioupiou:{st.get('id')}",
                name=name,
                lat=float(lat),
                lon=float(lon),
                elevation_m=elev,
                observed_at=iso(observed),
                wind_speed_kmh=float(meas["wind_speed_avg"]),
                wind_gust_kmh=None if meas.get("wind_speed_max") is None else float(meas["wind_speed_max"]),
                wind_direction_deg=None if meas.get("wind_heading") is None else float(meas["wind_heading"]),
                temperature_c=None,
                source="pioupiou",
                stale=(age_min > rules.BEACON_STALE_MIN) or not state_on,
            )
        )
    return out


class PioupiouBeacons:
    name = "Pioupiou / OpenWindMap"

    def __init__(self, client: httpx.AsyncClient, url: str):
        self.client = client
        self.url = url

    async def fetch_all(self) -> list[Beacon]:
        data = await get_json(self.client, self.url)
        return parse_pioupiou(data, datetime.now(UTC))


def parse_ffvl_beacons(data, now: datetime) -> list[Beacon]:
    """Format FFVL non vérifié (pas de clé) : parseur défensif sur les noms de champs usuels."""
    items = data if isinstance(data, list) else (data.get("balises") or data.get("data") or []) if isinstance(data, dict) else []
    out = []
    for it in items:
        try:
            lat = float(it.get("latitude"))
            lon = float(it.get("longitude"))
        except (TypeError, ValueError):
            continue
        observed = _parse_time(str(it.get("date") or it.get("dateReleve") or "").replace(" ", "T"))
        if observed is None:
            continue
        def f(*keys):
            for k in keys:
                if it.get(k) not in (None, ""):
                    try:
                        return float(it[k])
                    except (TypeError, ValueError):
                        return None
            return None
        out.append(
            Beacon(
                id=f"ffvl:{it.get('idBalise') or it.get('idbalise') or it.get('id')}",
                name=str(it.get("nom") or it.get("name") or "Balise FFVL"),
                lat=lat, lon=lon, elevation_m=f("altitude"), observed_at=iso(observed),
                wind_speed_kmh=f("vitesseVentMoy"), wind_gust_kmh=f("vitesseVentMax"),
                wind_direction_deg=f("directVentMoy", "directVentInst"), temperature_c=f("temperature"),
                source="ffvl", stale=(now - observed) > timedelta(minutes=rules.BEACON_STALE_MIN),
            )  # fmt: skip
        )
    return out


class FfvlBeacons:
    name = "FFVL (balises)"

    def __init__(self, client: httpx.AsyncClient, api_url: str, api_key: str | None):
        self.client = client
        self.api_url = api_url
        self.api_key = api_key

    async def fetch_all(self) -> list[Beacon]:
        if not self.api_key:
            raise ProviderDisabled("clé FFVL absente")
        data = await get_json(self.client, self.api_url, {"base": "balises", "r": "list", "mode": "json", "key": self.api_key})
        return parse_ffvl_beacons(data, datetime.now(UTC))


class FixtureBeacons:
    """Balises de démonstration : mesure = météo synthétique au même instant + écart déterministe."""

    name = "Balises de démonstration"

    def __init__(self, weather: SyntheticWeather):
        self.weather = weather

    def fetch_sync(self, at: datetime) -> tuple[list[Beacon], dict[str, float]]:
        out: list[Beacon] = []
        ages: dict[str, float] = {}
        for raw in fixture_beacons_raw():
            h = int(hashlib.sha256(f"{raw['id']}{at:%Y%m%d%H}".encode()).hexdigest()[:4], 16)
            age = float(raw.get("stale_minutes", 2 + h % 12))
            observed = at - timedelta(minutes=age)
            ground = raw.get("elevation_m") or terrain_elevation(raw["lat"], raw["lon"])
            hour = self.weather.hour(raw["lat"], raw["lon"], ground, observed.replace(minute=0, second=0, microsecond=0))
            bias = raw.get("bias") or {}
            speed = max(0.0, (hour.wind_speed_10m or 0.0) + bias.get("speed", 0) + (h % 5 - 2) * 0.5)
            gust = max(speed, (hour.wind_gusts_10m or speed) + bias.get("speed", 0))
            direction = ((hour.wind_direction_10m or 0.0) + bias.get("dir", 0)) % 360
            out.append(
                Beacon(
                    id=raw["id"], name=raw["name"], lat=raw["lat"], lon=raw["lon"], elevation_m=raw.get("elevation_m"),
                    observed_at=iso(observed), wind_speed_kmh=round(speed, 1), wind_gust_kmh=round(gust, 1),
                    wind_direction_deg=round(direction), temperature_c=hour.temperature_2m, source="fixture",
                    stale=age > rules.BEACON_STALE_MIN,
                )  # fmt: skip
            )
            ages[raw["id"]] = age
        return out, ages


def filter_bbox(beacons: list[Beacon], bbox: tuple[float, float, float, float]) -> list[Beacon]:
    min_lon, min_lat, max_lon, max_lat = bbox
    return [b for b in beacons if min_lat <= b.lat <= max_lat and min_lon <= b.lon <= max_lon]


def ages_from(beacons: list[Beacon], now: datetime) -> dict[str, float]:
    out = {}
    for b in beacons:
        t = _parse_time(b.observed_at)
        if t is not None:
            out[b.id] = max(0.0, (now - t).total_seconds() / 60.0)
    return out


def nearest(beacons: list[Beacon], lat: float, lon: float, radius_km: float) -> list[Beacon]:
    return sorted(
        (b for b in beacons if haversine_km(lat, lon, b.lat, b.lon) <= radius_km),
        key=lambda b: haversine_km(lat, lon, b.lat, b.lon),
    )
