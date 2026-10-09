"""Open-Meteo, pas de 15 min (`minutely_15`) : vent 10 m aux atterros pour les horizons de nowcasting (≤ 2 h).

Pourquoi : à 15 min / 30 min / 1 h, l'heure d'arrivée tombe rarement sur une heure ronde, et c'est au fond de vallée
que la brise s'installe ou forcit en moins d'une heure. AROME France HD est publié au pas de 15 min sur la France
(ailleurs, Open-Meteo interpole l'horaire) : on prend le vent 10 m à l'heure d'arrivée au lieu de l'heure la plus
proche. Le vent du déco reste tiré du profil horaire (pas de niveaux de pression au pas de 15 min).

Requête : `GET /v1/forecast?latitude=a,b&longitude=c,d&minutely_15=wind_speed_10m,wind_direction_10m,wind_gusts_10m
&models=meteofrance_arome_france_hd&wind_speed_unit=kmh&timezone=GMT&start_minutely_15=…&end_minutely_15=…` ;
réponse (même convention que l'horaire) : objet pour une coordonnée, liste d'objets sinon ; `minutely_15.time` au
format « 2026-10-09T12:15 » (GMT) ; variables suffixées par le modèle s'il y en a plusieurs ; valeurs null hors
domaine ou hors échéance. 3 variables par point : une requête compte pour un appel par point (quota Open-Meteo).

Module séparé de `open_meteo.py` (fournisseur horaire) : aucun changement de ce dernier.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from app.providers.base import ProviderError, get_json

MINUTELY_VARS = ("wind_speed_10m", "wind_direction_10m", "wind_gusts_10m")
MAX_LOCATIONS_PER_CALL = 50
PREFERRED_MODEL = "meteofrance_arome_france_hd"  # seul modèle à pas de 15 min natif sur la France
_WIND_FACTORS = {"km/h": 1.0, "kmh": 1.0, "m/s": 3.6, "ms": 3.6, "kn": 1.852, "mp/h": 1.609344, "mph": 1.609344}

# (heure UTC, vent moyen km/h, direction °, rafale km/h)
Sample = tuple[datetime, float, float, float]


def floor_15(t: datetime) -> datetime:
    t = t.astimezone(UTC)
    return t.replace(minute=t.minute - t.minute % 15, second=0, microsecond=0)


def pick_model(models: list[str]) -> str:
    return PREFERRED_MODEL if PREFERRED_MODEL in models or not models else models[0]


def build_minutely_params(
    points: list[tuple[float, float, float | None]], model: str, start: datetime, end: datetime
) -> dict:
    params = {
        "latitude": ",".join(f"{p[0]:.4f}" for p in points),
        "longitude": ",".join(f"{p[1]:.4f}" for p in points),
        "minutely_15": ",".join(MINUTELY_VARS),
        "models": model,
        "wind_speed_unit": "kmh",
        "timezone": "GMT",
        "start_minutely_15": floor_15(start).strftime("%Y-%m-%dT%H:%M"),
        "end_minutely_15": floor_15(end).strftime("%Y-%m-%dT%H:%M"),
    }
    if all(p[2] is not None for p in points):
        params["elevation"] = ",".join(f"{p[2]:.0f}" for p in points)
    return params


def _series(block: dict, var: str, model: str) -> list | None:
    for k in (var, f"{var}_{model}"):
        v = block.get(k)
        if isinstance(v, list):
            return v
    return None


def _factor(units: dict, var: str, model: str) -> float:
    u = units.get(var) or units.get(f"{var}_{model}") or "km/h"
    f = _WIND_FACTORS.get(str(u).strip().lower())
    if f is None:
        raise ProviderError(f"Open-Meteo 15 min : unité de vent inattendue {u!r}")
    return f


def parse_minutely_location(loc: dict, model: str) -> list[Sample]:
    """Une localisation → échantillons triés ; les pas incomplets (null hors domaine/échéance) sont ignorés."""
    if not isinstance(loc, dict):
        raise ProviderError("Open-Meteo 15 min : localisation illisible")
    if loc.get("error"):
        raise ProviderError(f"Open-Meteo 15 min : {loc.get('reason')}")
    block = loc.get("minutely_15")
    if not isinstance(block, dict) or not isinstance(block.get("time"), list):
        raise ProviderError("Open-Meteo 15 min : réponse sans 'minutely_15.time'")
    units = loc.get("minutely_15_units") or {}
    speed, direc, gust = (_series(block, v, model) for v in MINUTELY_VARS)
    if speed is None or direc is None:
        return []
    fs, fg = _factor(units, "wind_speed_10m", model), _factor(units, "wind_gusts_10m", model)
    out: list[Sample] = []
    for i, ts in enumerate(block["time"]):
        try:
            t = datetime.fromisoformat(str(ts)).replace(tzinfo=UTC)
        except ValueError:
            continue
        v = speed[i] if i < len(speed) else None
        d = direc[i] if i < len(direc) else None
        if v is None or d is None:
            continue
        g = gust[i] if gust is not None and i < len(gust) else None
        vv = float(v) * fs
        out.append((t, vv, float(d) % 360.0, max(vv, float(g) * fg) if g is not None else vv))
    out.sort(key=lambda s: s[0])
    return out


def parse_minutely_response(data, n: int, model: str) -> list[list[Sample]]:
    if isinstance(data, dict) and data.get("error"):
        raise ProviderError(f"Open-Meteo 15 min : {data.get('reason')}")
    locs = data if isinstance(data, list) else [data]
    if len(locs) != n:
        raise ProviderError(f"Open-Meteo 15 min : {len(locs)} localisations pour {n} points")
    return [parse_minutely_location(loc, model) for loc in locs]


class OpenMeteoMinutely:
    name = "Open-Meteo 15 min (AROME France HD, vent 10 m)"

    def __init__(self, client: httpx.AsyncClient, base_url: str, models: list[str], api_key: str | None = None):
        self.client = client
        self.base_url = base_url
        self.model = pick_model(models)
        self.api_key = api_key

    async def fetch(
        self, points: list[tuple[float, float, float | None]], start: datetime, end: datetime
    ) -> list[list[Sample]]:
        out: list[list[Sample]] = []
        for i in range(0, len(points), MAX_LOCATIONS_PER_CALL):
            chunk = points[i : i + MAX_LOCATIONS_PER_CALL]
            params = build_minutely_params(chunk, self.model, start, end)
            if self.api_key:
                params["apikey"] = self.api_key
            data = await get_json(self.client, self.base_url, params)
            out += parse_minutely_response(data, len(chunk), self.model)
        return out


def minutely_window(reference: datetime, horizon_min: int, max_duration_min: float) -> tuple[datetime, datetime]:
    """Plage utile : de reference_time (vent « maintenant » pour comparer aux balises) à la dernière arrivée possible
    (cible + 1 h 30 de créneau + durée max), plafonnée à 8 h."""
    start = floor_15(reference)
    end = reference + timedelta(minutes=horizon_min + 90 + max_duration_min + 15)
    return start, min(end, start + timedelta(hours=8))
