"""Balises vent temps réel : Pioupiou / OpenWindMap (libre), FFVL (clé), fixtures simulées (mock).

Pioupiou — structure réelle constatée (tests/fixtures/pioupiou_live_all.json) :
`{doc, license, attribution, data: [{id, meta: {name}, location: {latitude, longitude, date, success},
measurements: {date, wind_heading, wind_speed_avg, wind_speed_max, wind_speed_min, pressure},
status: {date, snr, state: "on"|"off"}}]}` ; vitesses en km/h, direction d'où vient le vent ;
mesures null fréquentes ; pas d'altitude (parfois dans le nom : « Passage du Croc Sire 1405m »).
Licence : https://developers.pioupiou.fr/data-licensing — attribution « (c) contributors of the OpenWindMap wind
network <https://www.openwindmap.org> » (reprise dans `sources[]` des plans).

Pioupiou archive — structure réelle constatée (tests/fixtures/pioupiou_archive_1708.json, appel du 09/10/2026) :
`GET /v1/archive/{id}?start=last-hour&stop=now` → `{doc, license, attribution, legend: ["time", "latitude",
"longitude", "wind_speed_min", "wind_speed_avg", "wind_speed_max", "wind_heading", "pressure"], units: ["utc",
"degrees", "degrees", "km/h", "km/h", "km/h", "degrees", "(deprecated)"], data: [[...], ...]}` ; environ une mesure
toutes les 5 min, triées par date croissante ; `wind_heading` par pas de 22,5°.
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import UTC, datetime, timedelta

import httpx

from app.engine import rules
from app.geo import haversine_km, signed_angle_diff, wind_components, wind_from_components
from app.meteo.snapshot import iso
from app.models import Beacon, BeaconTrend
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
        if lat is None or lon is None:
            continue
        # mesure absente (vent null) : balise gardée mais « muette » (périmée), pour la dire absente au pilote
        no_measure = meas.get("wind_speed_avg") is None
        observed = _parse_time(meas.get("date")) or _parse_time((st.get("status") or {}).get("date"))
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
                wind_speed_kmh=None if no_measure else float(meas["wind_speed_avg"]),
                wind_gust_kmh=None if meas.get("wind_speed_max") is None else float(meas["wind_speed_max"]),
                wind_direction_deg=None if meas.get("wind_heading") is None else float(meas["wind_heading"]),
                temperature_c=None,
                source="pioupiou",
                # revue 7.21 : `stale` = mesure ANCIENNE (ou balise éteinte) ; une mesure absente reste
                # wind_speed_kmh = null (« mesure absente »), le moteur ne l'utilise pas
                stale=(age_min > rules.BEACON_STALE_MIN) or not state_on,
            )
        )
    return out


# Tendance : moyenne des mesures des 10 premières / 10 dernières minutes de la fenêtre (§8.1 : moyenne sur 10-20 min)
TREND_EDGE_MIN = 10.0


def _circ_mean(samples: list[tuple[float, float]]) -> float | None:
    """Direction moyenne pondérée par la vitesse (vecteurs) ; None si vent nul."""
    us = vs = 0.0
    for v, d in samples:
        u, w = wind_components(max(v, 0.1), d)
        us += u
        vs += w
    if math.hypot(us, vs) < 1e-6:
        return None
    return wind_from_components(us, vs)[1]


def trend_from_samples(rows: list[tuple[datetime, float | None, float | None, float | None]]) -> BeaconTrend | None:
    """rows = [(heure, vent moyen, vent max, direction)] → Beacon.trend (None si moins de 2 mesures exploitables)."""
    pts = sorted((r for r in rows if r[1] is not None), key=lambda r: r[0])
    if len(pts) < 2:
        return None
    t0, t1 = pts[0][0], pts[-1][0]
    window = (t1 - t0).total_seconds() / 60.0
    first = [r for r in pts if (r[0] - t0).total_seconds() / 60.0 <= TREND_EDGE_MIN] or pts[:1]
    last = [r for r in pts if (t1 - r[0]).total_seconds() / 60.0 <= TREND_EDGE_MIN] or pts[-1:]
    # revue : pente par régression linéaire sur TOUS les échantillons (l'écart des moyennes des 10 premières et des
    # 10 dernières minutes divisé par toute la fenêtre sous-estimait le taux d'environ 18 % sur 1 h) ; publiée comme
    # speed_change_kmh = pente × fenêtre, pour garder le contrat (taux = speed_change × 60 / window_min)
    xs = [(r[0] - t0).total_seconds() / 60.0 for r in pts]
    ys = [float(r[1]) for r in pts]  # type: ignore[arg-type]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx if sxx > 0 else 0.0
    d0 = _circ_mean([(r[1], r[3]) for r in first if r[3] is not None])  # type: ignore[misc]
    d1 = _circ_mean([(r[1], r[3]) for r in last if r[3] is not None])  # type: ignore[misc]
    dchange = 0.0 if d0 is None or d1 is None else signed_angle_diff(d1, d0)
    gusts = [r[2] for r in pts if r[2] is not None]
    return BeaconTrend(
        window_min=round(window, 1),
        speed_change_kmh=round(slope * window, 1),
        direction_change_deg=round(dchange, 1),
        gust_max_kmh=max(gusts) if gusts else None,
        samples=len(pts),
    )


def parse_pioupiou_archive(data) -> BeaconTrend | None:
    """Réponse de /v1/archive/{id} → tendance (colonnes repérées par `legend`, unités contrôlées)."""
    if not isinstance(data, dict) or not isinstance(data.get("data"), list) or not isinstance(data.get("legend"), list):
        raise ProviderError("Pioupiou archive : réponse sans 'legend' / 'data'")
    legend = data["legend"]
    try:
        it, iavg = legend.index("time"), legend.index("wind_speed_avg")
        imax, ihead = legend.index("wind_speed_max"), legend.index("wind_heading")
    except ValueError as e:
        raise ProviderError(f"Pioupiou archive : colonne absente ({e})") from e
    units = data.get("units") or []
    if len(units) > iavg and str(units[iavg]).lower() not in ("km/h", "kmh"):
        raise ProviderError(f"Pioupiou archive : unité de vent inattendue {units[iavg]!r}")

    def num(row: list, i: int) -> float | None:
        v = row[i] if i < len(row) else None
        return None if v is None else float(v)

    rows = []
    for row in data["data"]:
        if not isinstance(row, list) or len(row) <= max(it, iavg, imax, ihead):
            continue
        t = _parse_time(row[it])
        if t is None:
            continue
        rows.append((t, num(row, iavg), num(row, imax), num(row, ihead)))
    return trend_from_samples(rows)


def archive_url(live_url: str, station_id: str) -> str:
    """https://api.pioupiou.fr/v1/live/all → https://api.pioupiou.fr/v1/archive/{id}"""
    base = live_url.split("/live")[0] if "/live" in live_url else live_url.rstrip("/")
    return f"{base}/archive/{station_id}"


class PioupiouBeacons:
    name = "Pioupiou / OpenWindMap"

    def __init__(self, client: httpx.AsyncClient, url: str):
        self.client = client
        self.url = url

    async def fetch_all(self) -> list[Beacon]:
        data = await get_json(self.client, self.url)
        return parse_pioupiou(data, datetime.now(UTC))

    async def fetch_trend(self, beacon_id: str) -> BeaconTrend | None:
        """Tendance sur la dernière heure (un appel /v1/archive par balise ; « pioupiou:1720 » → 1720)."""
        sid = beacon_id.split(":", 1)[-1]
        data = await get_json(self.client, archive_url(self.url, sid), {"start": "last-hour", "stop": "now"})
        return parse_pioupiou_archive(data)


def parse_ffvl_beacons(data, now: datetime) -> list[Beacon]:
    """Format FFVL non vérifié (pas de clé) : parseur défensif sur les noms de champs usuels."""
    items = (
        data
        if isinstance(data, list)
        else (data.get("balises") or data.get("data") or [])
        if isinstance(data, dict)
        else []
    )
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
        def f(*keys, it=it):
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
            )
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
        data = await get_json(
            self.client, self.api_url, {"base": "balises", "r": "list", "mode": "json", "key": self.api_key}
        )
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
            ground = raw.get("elevation_m") or raw.get("dem_elevation_m") or terrain_elevation(raw["lat"], raw["lon"])
            hour0 = observed.replace(minute=0, second=0, microsecond=0)
            hour = self.weather.hour(raw["lat"], raw["lon"], ground, hour0)
            bias = raw.get("bias") or {}
            speed = max(0.0, (hour.wind_speed_10m or 0.0) + bias.get("speed", 0) + (h % 5 - 2) * 0.5)
            gust = max(speed, (hour.wind_gusts_10m or speed) + bias.get("speed", 0))
            direction = ((hour.wind_direction_10m or 0.0) + bias.get("dir", 0)) % 360
            # tendance simulée : même calcul une heure plus tôt (12 mesures « toutes les 5 min »)
            prev = self.weather.hour(raw["lat"], raw["lon"], ground, hour0 - timedelta(hours=1))
            pspeed = max(0.0, (prev.wind_speed_10m or 0.0) + bias.get("speed", 0) + (h % 5 - 2) * 0.5)
            pgust = max(pspeed, (prev.wind_gusts_10m or pspeed) + bias.get("speed", 0))
            pdir = ((prev.wind_direction_10m or 0.0) + bias.get("dir", 0)) % 360
            trend = None
            if age <= rules.BEACON_STALE_MIN:
                trend = BeaconTrend(
                    window_min=60.0,
                    speed_change_kmh=round(speed - pspeed, 1),
                    direction_change_deg=round(signed_angle_diff(direction, pdir), 1)
                    if min(speed, pspeed) >= 3
                    else 0.0,
                    gust_max_kmh=round(max(gust, pgust), 1),
                    samples=12,
                )
            out.append(
                Beacon(
                    id=raw["id"], name=raw["name"], lat=raw["lat"], lon=raw["lon"], elevation_m=raw.get("elevation_m"),
                    observed_at=iso(observed), wind_speed_kmh=round(speed, 1), wind_gust_kmh=round(gust, 1),
                    wind_direction_deg=round(direction), temperature_c=hour.temperature_2m, source="fixture",
                    stale=age > rules.BEACON_STALE_MIN, trend=trend,
                )
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


def fixture_beacon_dem() -> dict[str, float]:
    """Altitude « MNT » simulée des balises de démonstration sans altitude (`dem_elevation_m` des fixtures)."""
    return {r["id"]: float(r["dem_elevation_m"]) for r in fixture_beacons_raw() if r.get("dem_elevation_m") is not None}
