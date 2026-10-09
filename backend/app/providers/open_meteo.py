"""Adaptateur Open-Meteo (prévisions multi-modèles + niveaux de pression, élévation).

Constats sur réponses réelles (enregistrées dans tests/fixtures/open_meteo_forclaz_3models.json,
appel du 08/10/2026) :
- une seule coordonnée → objet JSON ; plusieurs coordonnées → liste d'objets (même ordre) ;
- plusieurs modèles → chaque variable est suffixée par le nom du modèle (`temperature_2m_icon_d2`) ;
- `meteofrance_arome_france_hd` : surface seulement (pas de niveaux de pression, pas de `cloud_cover`
  total, pas de `shortwave_radiation`), ~42 h d'échéance (valeurs null au-delà) ;
- `icon_d2` : niveaux 1000…500 hPa complets, CAPE, CIN, isotherme 0, rayonnement, ~48 h ;
- `ecmwf_ifs025` : niveaux 1000/925/850/700/600/500 (pas 950/900/800), CAPE, rayonnement ;
  pas de lifted_index / CIN / freezing_level ;
- `boundary_layer_height` et `lifted_index` : null pour ces 3 modèles (calculés par nous) ;
- heures en GMT au format « 2026-10-08T00:00 » ; vent en km/h avec `wind_speed_unit=kmh` ;
- `elevation=<alt>` : Open-Meteo ramène T2m à l'altitude demandée (indispensable en montagne) ;
- quota journalier : 429 « Daily API request limit exceeded » (repli mock en mode auto) ; le
  corps JSON `{"error": true, "reason": …}` est repris tel quel dans le message d'erreur ;
- `hourly_units` : « km/h » pour les vents (contrôlé : conversion si l'unité diffère), « undefined »
  pour une variable non fournie par le modèle.
Coût : Open-Meteo compte une requête de plus de 10 variables comme plusieurs appels (≈ variables / 10
par point) : la requête complète (61 variables) pèse au moins 6 appels par point, davantage si les
modèles sont comptés séparément — d'où le 429 « Daily API request limit exceeded » du 08/10/2026.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from app.meteo.thermo import dew_point_from_rh
from app.meteo.types import HourData, LevelData, ModelSeries, PointForecast
from app.providers.base import ProviderError, get_json

SURFACE_VARS = (
    "temperature_2m",
    "dew_point_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "precipitation",
    "cape",
    "lifted_index",
    "convective_inhibition",
    "freezing_level_height",
    "boundary_layer_height",
    "shortwave_radiation",
)
# niveaux demandés (ECMWF n'a pas 950/900/800, ICON-D2 les a)
REQUEST_LEVELS = (1000, 950, 925, 900, 850, 800, 700, 600, 500)
LEVEL_VARS = ("temperature", "relative_humidity", "wind_speed", "wind_direction", "geopotential_height")
MAX_LOCATIONS_PER_CALL = 50

MODEL_LABELS = {
    "meteofrance_arome_france_hd": "arome_france_hd",
    "meteofrance_arome_france": "arome_france",
    "icon_d2": "icon_d2",
    "icon_eu": "icon_eu",
    "ecmwf_ifs025": "ecmwf_ifs025",
    "best_match": "best_match",
    "gfs_seamless": "gfs",
}


def model_label(name: str) -> str:
    return MODEL_LABELS.get(name, name)


def hourly_variables(with_levels: bool) -> list[str]:
    out = list(SURFACE_VARS)
    if with_levels:
        for v in LEVEL_VARS:
            for p in REQUEST_LEVELS:
                out.append(f"{v}_{p}hPa")
    return out


def build_params(
    points: list[tuple[float, float, float | None]],
    models: list[str],
    start: datetime,
    end: datetime,
    with_levels: bool,
    variables: list[str] | None = None,
) -> dict:
    params = {
        "latitude": ",".join(f"{p[0]:.4f}" for p in points),
        "longitude": ",".join(f"{p[1]:.4f}" for p in points),
        "hourly": ",".join(variables or hourly_variables(with_levels)),
        "models": ",".join(models),
        "wind_speed_unit": "kmh",
        "timezone": "GMT",
        "start_hour": start.astimezone(UTC).strftime("%Y-%m-%dT%H:00"),
        "end_hour": end.astimezone(UTC).strftime("%Y-%m-%dT%H:00"),
    }
    if all(p[2] is not None for p in points):
        params["elevation"] = ",".join(f"{p[2]:.0f}" for p in points)
    return params


# conversion vers km/h selon `hourly_units` (on demande wind_speed_unit=kmh, mais on vérifie)
_WIND_FACTORS = {"km/h": 1.0, "kmh": 1.0, "m/s": 3.6, "ms": 3.6, "kn": 1.852, "mp/h": 1.609344, "mph": 1.609344}


def _key(h: dict, var: str, model: str, single: bool) -> str:
    """Nom de la variable dans la réponse : suffixée par le modèle s'il y en a plusieurs."""
    suffixed = f"{var}_{model}"
    if single and suffixed not in h:
        return var
    return suffixed


def _get(h: dict, var: str, model: str, single: bool, i: int):
    arr = h.get(_key(h, var, model, single))
    if arr is None or i >= len(arr):
        return None
    return arr[i]


def _wind_factor(units: dict, key: str) -> float:
    u = units.get(key)
    if u is None:
        return 1.0
    f = _WIND_FACTORS.get(str(u).strip().lower())
    if f is None:
        if str(u) == "undefined":
            return 1.0
        raise ProviderError(f"Open-Meteo : unité de vent inattendue pour {key} : {u!r}")
    return f


def _times(loc: dict) -> list[datetime]:
    """Horodatages UTC (on demande timezone=GMT ; `utc_offset_seconds` est appliqué par sécurité)."""
    h = loc.get("hourly") or {}
    offset = timedelta(seconds=int(loc.get("utc_offset_seconds") or 0))
    out = []
    for ts in h.get("time") or []:
        t = datetime.fromisoformat(ts)
        if t.tzinfo is None:
            t = (t - offset).replace(tzinfo=UTC)
        out.append(t.astimezone(UTC))
    return out


def parse_location(loc: dict, models: list[str]) -> list[ModelSeries]:
    """Une localisation de la réponse → une série par modèle (heures sans donnée ignorées)."""
    h = loc.get("hourly") or {}
    units = loc.get("hourly_units") or {}
    times = _times(loc)
    if not times:
        raise ProviderError("réponse Open-Meteo sans 'hourly.time'")
    single = len(models) == 1
    out: list[ModelSeries] = []
    for m in models:
        wind_f = {
            v: _wind_factor(units, _key(h, v, m, single))
            for v in ("wind_speed_10m", "wind_gusts_10m", *(f"wind_speed_{p}hPa" for p in REQUEST_LEVELS))
        }
        hours: list[HourData] = []
        for i, t in enumerate(times):
            t2 = _get(h, "temperature_2m", m, single, i)
            if t2 is None:
                continue  # hors échéance du modèle (valeurs null en bout d'horizon)
            hd = HourData(time=t)
            for var in SURFACE_VARS:
                val = _get(h, var, m, single, i)
                if val is not None and var in wind_f:
                    val = val * wind_f[var]
                setattr(hd, var, val)
            if hd.dew_point_2m is None:
                rh = _get(h, "relative_humidity_2m", m, single, i)
                if rh is not None:
                    hd.dew_point_2m = dew_point_from_rh(t2, rh)
            if hd.cloud_cover is None:
                parts = [x for x in (hd.cloud_cover_low, hd.cloud_cover_mid, hd.cloud_cover_high) if x is not None]
                if parts:
                    # recouvrement maximal-aléatoire simplifié
                    rest = 1.0
                    for x in parts:
                        rest *= 1.0 - x / 100.0
                    hd.cloud_cover = max(max(parts), 100.0 * (1.0 - rest) * 0.85)
            levels = []
            for p in REQUEST_LEVELS:
                tp = _get(h, f"temperature_{p}hPa", m, single, i)
                z = _get(h, f"geopotential_height_{p}hPa", m, single, i)
                ws = _get(h, f"wind_speed_{p}hPa", m, single, i)
                wd = _get(h, f"wind_direction_{p}hPa", m, single, i)
                if tp is None or z is None or ws is None or wd is None:
                    continue  # niveau non fourni par ce modèle (AROME HD : aucun ; ECMWF : ni 950, 900, 800)
                ws = ws * wind_f[f"wind_speed_{p}hPa"]
                rh = _get(h, f"relative_humidity_{p}hPa", m, single, i)
                td = dew_point_from_rh(tp, rh) if rh is not None else tp - 10.0
                levels.append(LevelData(float(p), float(z), float(tp), float(td), float(ws), float(wd)))
            hd.levels = levels
            hours.append(hd)
        if hours:
            out.append(
                ModelSeries(
                    model=model_label(m),
                    lat=float(loc.get("latitude", 0.0)),
                    lon=float(loc.get("longitude", 0.0)),
                    elevation_m=float(loc.get("elevation", 0.0)),
                    hours=hours,
                )
            )
    return out


def parse_forecast_response(
    data, points: list[tuple[float, float, float | None]], models: list[str], fetched_at: datetime, url: str
) -> list[PointForecast]:
    if isinstance(data, dict) and data.get("error"):
        raise ProviderError(f"Open-Meteo : {data.get('reason')}")
    locs = data if isinstance(data, list) else [data]
    if not all(isinstance(x, dict) for x in locs):
        raise ProviderError("Open-Meteo : réponse inattendue (ni objet ni liste d'objets)")
    if len(locs) != len(points):
        raise ProviderError(f"Open-Meteo : {len(locs)} localisations reçues pour {len(points)} demandées")
    out = []
    for loc, (lat, lon, elev) in zip(locs, points, strict=True):
        series = parse_location(loc, models)
        if not series:
            raise ProviderError("Open-Meteo : aucune donnée de modèle exploitable")
        out.append(
            PointForecast(
                lat=lat,
                lon=lon,
                elevation_m=float(elev if elev is not None else loc.get("elevation", 0.0)),
                models=series,
                mode="live",
                source_name="Open-Meteo",
                source_url="https://open-meteo.com",
                fetched_at=fetched_at,
            )
        )
    return out


class OpenMeteoForecast:
    name = "Open-Meteo"

    def __init__(self, client: httpx.AsyncClient, base_url: str, models: list[str], api_key: str | None = None):
        self.client = client
        self.base_url = base_url
        self.models = models
        self.api_key = api_key

    async def fetch(
        self,
        points: list[tuple[float, float, float | None]],
        start: datetime,
        end: datetime,
        with_levels: bool = True,
        models: list[str] | None = None,
        variables: list[str] | None = None,
    ) -> list[PointForecast]:
        models = models or self.models
        out: list[PointForecast] = []
        fetched = datetime.now(UTC)
        for i in range(0, len(points), MAX_LOCATIONS_PER_CALL):
            chunk = points[i : i + MAX_LOCATIONS_PER_CALL]
            params = build_params(chunk, models, start, end, with_levels, variables)
            if self.api_key:
                params["apikey"] = self.api_key
            data = await get_json(self.client, self.base_url, params)
            out += parse_forecast_response(data, chunk, models, fetched, self.base_url)
        return out


def parse_elevation_response(data, n: int) -> list[float]:
    """`{"elevation": [m, …]}` (MNT Copernicus 90 m), même ordre que les coordonnées demandées."""
    if isinstance(data, dict) and data.get("error"):
        raise ProviderError(f"Open-Meteo Elevation : {data.get('reason')}")
    if not isinstance(data, dict) or "elevation" not in data:
        raise ProviderError("réponse Elevation sans champ 'elevation'")
    vals = data["elevation"]
    if len(vals) != n:
        raise ProviderError(f"Elevation : {len(vals)} valeurs pour {n} points")
    return [float(v) if v is not None else 0.0 for v in vals]


class OpenMeteoElevation:
    name = "Open-Meteo Elevation"
    MAX_PER_CALL = 100

    def __init__(self, client: httpx.AsyncClient, url: str):
        self.client = client
        self.url = url

    async def fetch(self, points: list[tuple[float, float]]) -> list[float]:
        out: list[float] = []
        for i in range(0, len(points), self.MAX_PER_CALL):
            chunk = points[i : i + self.MAX_PER_CALL]
            params = {
                "latitude": ",".join(f"{p[0]:.5f}" for p in chunk),
                "longitude": ",".join(f"{p[1]:.5f}" for p in chunk),
            }
            data = await get_json(self.client, self.url, params)
            out += parse_elevation_response(data, len(chunk))
        return out


def series_summary(pf: PointForecast) -> str:
    """Résumé lisible : heures et niveaux de pression disponibles par modèle (diagnostic, check_sources)."""
    parts = []
    for ms in pf.models:
        n_lv = max((len(h.levels) for h in ms.hours), default=0)
        parts.append(f"{ms.model} {len(ms.hours)} h/{n_lv} niv.")
    return ", ".join(parts)


def day_range(target: datetime) -> tuple[datetime, datetime]:
    """Plage horaire à demander autour de l'heure cible (journée + marge pour ±3 h)."""
    t = target.astimezone(UTC)
    start = (t - timedelta(hours=14)).replace(minute=0, second=0, microsecond=0)
    end = (t + timedelta(hours=14)).replace(minute=0, second=0, microsecond=0)
    return start, end
