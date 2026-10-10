"""Service de données : choisit live / mock selon DATA_MODE, gère le repli, le cache et l'état des sources.

DATA_MODE=auto : chaque source live est tentée (timeout court) ; en cas d'échec, repli silencieux
sur le mock et la source n'est pas retentée pendant `live_retry_after_s`. Les réponses indiquent le
mode effectivement utilisé (`data_mode`, `sources[].mode`).
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.cache import TTLCache
from app.config import Settings
from app.engine.context import Airspace, PointTimeline, SensitiveArea, SiteMeta
from app.engine.landings import LandingSpot
from app.engine.terrain import (
    GRID_N,
    TakeoffTerrain,
    analyze_grid,
    axis_from_orientations,
    axis_points,
    axis_profile,
    dem_grid_points,
    downslope_slope_pct,
    profile_distances,
    slope_distances,
)
from app.geo import destination, expand_bbox, haversine_km
from app.meteo.ensemble import aggregate_hours, hour_spread
from app.meteo.snapshot import iso
from app.meteo.thermals import analyze_hour
from app.meteo.types import PointForecast
from app.models import Beacon, BeaconTrend, Site, SourceRef, SourceStatus
from app.providers.airspaces import OpenAipAirspaces, OpenAirFiles, fixture_airspace_list
from app.providers.base import ProviderDisabled, ProviderError, SourceState, make_client, now_utc
from app.providers.beacons import (
    FfvlBeacons,
    FixtureBeacons,
    PioupiouBeacons,
    ages_from,
    filter_bbox,
    fixture_beacon_dem,
)
from app.providers.landing_spots import (
    OSM_ATTRIBUTION,
    OSM_COPYRIGHT_URL,
    OverpassLandings,
    fixture_landing_spots,
)
from app.providers.open_meteo import OpenMeteoElevation, OpenMeteoForecast
from app.providers.open_meteo_minutely import OpenMeteoMinutely, Sample
from app.providers.sensitive import BiodivSports, fixture_areas, merge_areas
from app.providers.sites import (
    FfvlSites,
    ParaglidingEarthSites,
    SpotAirSites,
    associate_landings,
    fixture_sites,
    merge_sites,
)
from app.providers.synthetic_forecast import SyntheticElevation, SyntheticForecast
from app.providers.synthetic_terrain import terrain_elevation

log = logging.getLogger("paraglide.services")

MAX_TREND_CALLS = 10  # appels /v1/archive Pioupiou au plus par requête de plans
BEACON_DEM_RADIUS_KM = 8.0  # MNT demandé pour les balises sans altitude à moins de 8 km d'un site (rattachement ≤ 5 km)
MAX_BEACON_DEM_POINTS = 100  # un seul appel Open-Meteo Elevation (100 coordonnées par appel)
MINUTELY_TTL_S = 15 * 60
TERRAIN_STEPS_DEG = (0.015, 0.02, 0.025, 0.03, 0.04, 0.05, 0.075, 0.1)
MAX_TERRAIN_POINTS = 2500
# sources qui partagent un quota (même fournisseur, même adresse IP) : un 429 les suspend toutes
QUOTA_SHARED = {
    k: ("open-meteo", "open-meteo-15min", "open-meteo-elevation")
    for k in ("open-meteo", "open-meteo-15min", "open-meteo-elevation")
}
MIN_429_BACKOFF_S = {"openaip": 300.0}  # Cloudflare : au plus un appel toutes les 5 min
DAILY_429_MAX_BLOCK_S = 3600.0  # quota journalier : suspension d'au plus 1 h entre deux essais
OPENWINDMAP_URL = "https://www.openwindmap.org"
PIOUPIOU_ATTRIBUTION = (
    "Pioupiou / OpenWindMap — balises temps réel, (c) contributors of the OpenWindMap wind network "
    "(licence : https://developers.pioupiou.fr/data-licensing)"
)
PIOUPIOU_ARCHIVE_ATTRIBUTION = (
    "Pioupiou / OpenWindMap — historique 1 h des balises (tendance), (c) contributors of the OpenWindMap wind "
    "network (licence : https://developers.pioupiou.fr/data-licensing)"
)
DEMO_BEACONS_ATTRIBUTION = (
    "Balises de démonstration (mesures simulées ; positions de balises Pioupiou / OpenWindMap, "
    "(c) contributors of the OpenWindMap wind network)"
)


class DataService:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.s = settings
        self.client = client or make_client(settings.http_timeout_s)
        self._own_client = client is None
        self.forecast_cache = TTLCache(settings.cache_ttl_forecast_s, 5000)
        self.sites_cache = TTLCache(settings.cache_ttl_sites_s, 200)
        self.beacons_cache = TTLCache(settings.cache_ttl_beacons_s, 50)
        self.airspace_cache = TTLCache(settings.cache_ttl_airspaces_s, 100)
        self.sensitive_cache = TTLCache(settings.cache_ttl_sensitive_s, 100)
        self.elev_cache = TTLCache(settings.cache_ttl_elevation_s, 200_000)
        self.trend_cache = TTLCache(settings.cache_ttl_beacons_s, 2000)  # tendance des balises : 2 min
        # fournisseurs
        self.om = OpenMeteoForecast(
            self.client, settings.open_meteo_base_url, settings.open_meteo_model_list, settings.open_meteo_api_key
        )
        self.om_elev = OpenMeteoElevation(self.client, settings.open_meteo_elevation_url)
        self.om_15 = OpenMeteoMinutely(self.client, settings.open_meteo_base_url, settings.open_meteo_model_list,
                                       settings.open_meteo_api_key)  # fmt: skip
        self.minutely_cache = TTLCache(MINUTELY_TTL_S, 2000)
        self.synthetic = SyntheticForecast(settings.synthetic_scenario)
        self.syn_elev = SyntheticElevation()
        self.pge = ParaglidingEarthSites(self.client, settings.paraglidingearth_url)
        self.ffvl_sites = FfvlSites(self.client, settings.ffvl_api_url, settings.ffvl_api_key)
        self.ffvl_beacons = FfvlBeacons(self.client, settings.ffvl_api_url, settings.ffvl_api_key)
        self.spotair = SpotAirSites(self.client, settings.spotair_api_url, settings.spotair_api_key)
        self.pioupiou = PioupiouBeacons(self.client, settings.pioupiou_url)
        self.fixture_beacons = FixtureBeacons(self.synthetic.weather)
        self.openaip = OpenAipAirspaces(self.client, settings.openaip_url, settings.openaip_api_key)
        self.openair = OpenAirFiles(settings.airspace_openair_dir)
        self.biodiv = BiodivSports(self.client, settings.biodivsports_url)
        self.overpass = OverpassLandings(self.client, settings.overpass_url, settings.overpass_enabled)
        self.spots_cache = TTLCache(settings.cache_ttl_sites_s, 100)
        self._openaip_last_call = 0.0
        self.states = self._init_states()

    async def aclose(self) -> None:
        if self._own_client:
            await self.client.aclose()

    # ------------------------------------------------------------------------------------------
    # États des sources
    # ------------------------------------------------------------------------------------------
    def _init_states(self) -> dict[str, SourceState]:
        s = self.s
        st = {
            "open-meteo": SourceState("Open-Meteo (AROME HD, ICON-D2, ECMWF)", "forecast", "https://open-meteo.com"),
            "open-meteo-15min": SourceState(
                "Open-Meteo 15 min (AROME France HD, vent 10 m)",
                "forecast",
                "https://open-meteo.com/en/docs/meteofrance-api",
            ),
            "open-meteo-elevation": SourceState(
                "Open-Meteo Elevation", "elevation", "https://open-meteo.com/en/docs/elevation-api"
            ),
            "paraglidingearth": SourceState("ParaglidingEarth", "sites", "https://www.paraglidingearth.com"),
            "pioupiou": SourceState("Pioupiou / OpenWindMap", "beacons", "https://www.openwindmap.org"),
            "pioupiou-archive": SourceState(
                "Pioupiou / OpenWindMap (historique 1 h, tendance)",
                "beacons",
                "https://developers.pioupiou.fr/api/archive/",
            ),
            "openaip": SourceState(
                "OpenAIP",
                "airspaces",
                "https://www.openaip.net",
                requires_api_key=True,
                api_key_configured=bool(s.openaip_api_key),
            ),
            "openair": SourceState("Fichiers OpenAir locaux", "airspaces", None),
            "biodivsports": SourceState("Biodiv'Sports", "sensitive_areas", "https://biodiv-sports.fr"),
            "overpass": SourceState(
                "OpenStreetMap / Overpass (champs candidats, atterros vol libre, obstacles)",
                "sites",
                "https://www.openstreetmap.org/copyright",
            ),
            "ffvl-sites": SourceState(
                "FFVL (terrains)",
                "sites",
                "https://data.ffvl.fr",
                requires_api_key=True,
                api_key_configured=bool(s.ffvl_api_key),
            ),
            "ffvl-beacons": SourceState(
                "FFVL (balises)",
                "beacons",
                "https://data.ffvl.fr",
                requires_api_key=True,
                api_key_configured=bool(s.ffvl_api_key),
            ),
            "spotair": SourceState(
                "SpotAir",
                "sites",
                "https://www.spotair.mobi",
                requires_api_key=True,
                api_key_configured=bool(s.spotair_api_key),
            ),
            "meteo-parapente": SourceState(
                "Météo-Parapente",
                "forecast",
                "https://meteo-parapente.com",
                requires_api_key=True,
                api_key_configured=bool(s.meteo_parapente_api_key),
            ),
            "fixtures": SourceState("Données de démonstration (fixtures + météo synthétique)", "sites", None),
        }
        if not s.ffvl_api_key:
            msg = ("Désactivé : clé API FFVL requise. Demande à faire auprès de la FFVL (data.ffvl.fr, formulaire de "
                   "demande d'accès aux données) puis renseigner FFVL_API_KEY.")  # fmt: skip
            st["ffvl-sites"].disabled_message = msg
            st["ffvl-beacons"].disabled_message = msg
        if not s.openaip_api_key:
            st["openaip"].disabled_message = (
                "Désactivé : clé OpenAIP absente. Créer un compte gratuit sur openaip.net puis générer une clé API "
                "dans "
                "le profil (API clients) et renseigner OPENAIP_API_KEY. Repli : fichiers OpenAir locaux puis démo."
            )
        if not (s.spotair_api_url and s.spotair_api_key):
            st["spotair"].disabled_message = (
                "Désactivé : SpotAir n'a pas d'API publique. Un accord / partenariat est nécessaire "
                "(SPOTAIR_API_URL + SPOTAIR_API_KEY) ; aucun scraping n'est effectué."
            )
        if not (s.meteo_parapente_api_url and s.meteo_parapente_api_key):
            st["meteo-parapente"].disabled_message = (
                "Désactivé : Météo-Parapente n'a pas d'API publique. Une licence / un accord est nécessaire "
                "(METEO_PARAPENTE_API_URL + METEO_PARAPENTE_API_KEY) ; aucun scraping n'est effectué."
            )
        if not s.overpass_enabled:
            st["overpass"].disabled_message = (
                "Désactivé (OVERPASS_ENABLED=false) : l'API Overpass d'OpenStreetMap n'est pas joignable depuis ce "
                "serveur. À activer quand overpass-api.de est autorisé. Repli : terrains de démonstration en mode "
                "démo ; en live, seuls les atterros ParaglidingEarth (officiels et communautaires) sont évalués."
            )
        if not self.openair.files():
            st["openair"].disabled_message = (
                f"Aucun fichier OpenAir dans {self.s.airspace_openair_dir} : y déposer un fichier France "
                "(voir data/airspaces/README.md)."
            )
        return st

    def statuses(self) -> list[SourceStatus]:
        out = []
        mode = self.s.data_mode
        for key, st in self.states.items():
            if key == "fixtures":
                out.append(
                    SourceStatus(
                        name=st.name, kind="sites", mode="mock", healthy=True, requires_api_key=False,
                        api_key_configured=False,
                        message="Toujours disponible ; utilisé en DATA_MODE=mock ou en repli (auto).", url=None,
                    )
                )
                continue
            if key == "openair":
                st.disabled_message = None if self.openair.files() else st.disabled_message
            if st.disabled_message:
                out.append(SourceStatus(name=st.name, kind=st.kind, mode="disabled", healthy=False,
                                        requires_api_key=st.requires_api_key, api_key_configured=st.api_key_configured,
                                        message=st.disabled_message, url=st.url))  # fmt: skip
                continue
            if mode == "mock":
                eff, healthy, msg = "mock", True, "DATA_MODE=mock : données de démonstration."
            elif st.last_error and (st.last_success is None or (st.last_failure or 0) > st.last_success):
                eff = "mock" if mode == "auto" else "live"
                healthy = False
                msg = f"Dernier appel en échec : {st.last_error}" + (
                    " — repli sur les données de démonstration." if mode == "auto" else ""
                )
                if st.blocked():
                    msg += f" Source suspendue : {st.blocked_reason}."
            else:
                eff, healthy = "live", True
                msg = None if st.last_success else "Pas encore interrogée."
            if key == "openair":
                eff, healthy = "live", True
                msg = f"{len(self.openair.files())} fichier(s) dans {self.s.airspace_openair_dir}"
            out.append(SourceStatus(name=st.name, kind=st.kind, mode=eff, healthy=healthy,
                                    requires_api_key=st.requires_api_key, api_key_configured=st.api_key_configured,
                                    message=msg, url=st.url))  # fmt: skip
        return out

    def data_mode(self) -> str:
        if self.s.data_mode == "mock":
            return "mock"
        if self.s.data_mode == "live":
            return "live"
        core = [self.states[k] for k in ("open-meteo", "paraglidingearth", "pioupiou")]
        failed = [
            st for st in core if st.last_error and (st.last_success is None or (st.last_failure or 0) > st.last_success)
        ]
        if not failed:
            return "live"
        if len(failed) == len(core):
            return "mock"
        return "mixed"

    # ------------------------------------------------------------------------------------------
    async def _try_live(self, key: str, live: Callable[[], Awaitable[Any]]) -> Any | None:
        """Exécute l'appel live selon DATA_MODE ; None si mock / repli. Lève en mode live strict.

        Quota (HTTP 429) : la source n'est plus appelée avant l'échéance donnée par `quota_backoff_s` (quota
        journalier Open-Meteo : 1 h au plus, jusqu'à 00h00 UTC, pour les trois API Open-Meteo qui partagent le quota ;
        OpenAIP / Cloudflare : 5 min au moins), en mode auto comme en mode live (erreur immédiate, sans appel)."""
        st = self.states[key]
        mode = self.s.data_mode
        if mode == "mock" or st.disabled_message:
            return None
        if st.blocked():
            if mode == "live":
                raise ProviderError(f"{st.name} indisponible : {st.blocked_reason}")
            return None
        if mode == "auto" and st.recently_failed(self.s.live_retry_after_s):
            return None
        try:
            res = await asyncio.wait_for(live(), timeout=self.s.http_timeout_s * 3)
        except ProviderDisabled as e:
            st.disabled_message = str(e)
            return None
        except (ProviderError, TimeoutError, httpx.HTTPError) as e:
            st.record_failure(str(e) or type(e).__name__)
            log.info("source %s indisponible (%s) — repli", key, e)
            if getattr(e, "http_status", None) == 429:
                wait_s, why = quota_backoff_s(key, str(e), now_utc(), self.s.live_retry_after_s,
                                              self.s.quota_block_max_s)  # fmt: skip
                for k in QUOTA_SHARED.get(key, (key,)):
                    if k in self.states:
                        self.states[k].block(wait_s, why)
            if mode == "live":
                raise ProviderError(f"{st.name} indisponible : {e}") from e
            return None
        st.record_success()
        return res

    # ------------------------------------------------------------------------------------------
    # Élévation / MNT
    # ------------------------------------------------------------------------------------------
    async def elevations_detailed(self, points: list[tuple[float, float]]) -> list[tuple[float, str]]:
        """Altitude MNT par point et son origine (« live » = Open-Meteo / Copernicus 90 m, « mock » = MNT de démo).
        Les points absents du cache (7 j) partent en un seul appel groupé (≤ 100 points par requête)."""
        keys = [(round(la, 4), round(lo, 4)) for la, lo in points]
        missing = [k for k in dict.fromkeys(keys) if self.elev_cache.get(("e", *k)) is None]
        if missing:
            res = await self._try_live("open-meteo-elevation", lambda: self.om_elev.fetch(missing))
            if res is not None:
                for k, v in zip(missing, res, strict=True):
                    self.elev_cache.set(("e", *k), (v, "live"))
            else:
                for k in missing:
                    self.elev_cache.set(("e", *k), (terrain_elevation(*k), "mock"), ttl_s=600)
        return [self.elev_cache.get(("e", *k)) for k in keys]

    async def elevations(self, points: list[tuple[float, float]]) -> tuple[list[float], str]:
        vals = await self.elevations_detailed(points)
        mode = "live" if vals and all(v[1] == "live" for v in vals) else "mock"
        return [v[0] for v in vals], mode

    async def beacon_dem(self, beacons: list[Beacon], sites: list[Site] | None = None) -> dict[str, float]:
        """Altitude MNT au point des balises sans altitude (Pioupiou n'en fournit pas, CDC §12.1) : un seul appel
        Open-Meteo Elevation groupé (≤ 100 points) pour les balises à moins de 8 km d'un site du calcul, en cache 7 j.
        Balises de démonstration : MNT simulé (fixture, sinon MNT de démo). Une balise réelle dont le MNT réel est
        indisponible (quota, réseau) est absente du résultat : « altitude inconnue », poids réduit (§12.1). Un échec
        n'empêche jamais le calcul des plans."""
        unknown = [b for b in beacons if b.elevation_m is None]
        if sites:
            unknown = [
                b
                for b in unknown
                if any(haversine_km(b.lat, b.lon, x.lat, x.lon) <= BEACON_DEM_RADIUS_KM for x in sites)
            ]
        if not unknown:
            return {}
        out: dict[str, float] = {}
        demo_dem = fixture_beacon_dem()
        for b in unknown:
            if b.source == "fixture":
                out[b.id] = float(demo_dem.get(b.id) or round(terrain_elevation(b.lat, b.lon)))
        real = [b for b in unknown if b.source != "fixture"][:MAX_BEACON_DEM_POINTS]
        if real and self.s.data_mode != "mock":
            try:
                vals = await self.elevations_detailed([(b.lat, b.lon) for b in real])
            except ProviderError as e:  # DATA_MODE=live : MNT indisponible → altitude inconnue
                log.info("MNT des balises indisponible (%s) : altitude inconnue", e)
                vals = []
            for b, (v, mode) in zip(real, vals, strict=False):
                if mode == "live":
                    out[b.id] = float(round(v))
        return out

    async def minutely_winds(
        self, points: list[tuple[float, float, float | None]], start: datetime, end: datetime
    ) -> tuple[list[list[Sample]], list[SourceRef]]:
        """Vent 10 m au pas de 15 min (Open-Meteo `minutely_15`, AROME France HD) aux points demandés, en un appel
        groupé, cache 15 min. Mock, échec ou quota : listes vides (le moteur garde l'heure la plus proche)."""
        empty: list[list[Sample]] = [[] for _ in points]
        if not points or self.s.data_mode == "mock":
            return empty, []
        key = ("m15", tuple((round(a, 3), round(b, 3)) for a, b, _ in points), start.isoformat(), end.isoformat())
        cached = self.minutely_cache.get(key)
        if cached is None:
            try:
                cached = await self._try_live("open-meteo-15min", lambda: self.om_15.fetch(points, start, end))
            except ProviderError as e:  # DATA_MODE=live : on calcule quand même, au pas horaire
                log.info("Open-Meteo 15 min indisponible (%s) : pas horaire", e)
                cached = None
            if cached is None:
                return empty, []
            self.minutely_cache.set(key, cached)
        refs = []
        if any(cached):
            refs.append(SourceRef(name=self.om_15.name, url="https://open-meteo.com/en/docs/meteofrance-api",
                                  fetched_at=iso(now_utc()), mode="live"))  # fmt: skip
        return cached, refs

    async def beacon_trends(self, beacon_ids: list[str]) -> dict[str, BeaconTrend]:
        """Tendance sur la dernière heure (archive Pioupiou) pour au plus MAX_TREND_CALLS balises, en cache 2 min.
        Un échec n'empêche jamais le calcul des plans : la tendance reste « indisponible »."""
        out: dict[str, BeaconTrend] = {}
        st = self.states["pioupiou-archive"]
        if self.s.data_mode == "mock" or st.recently_failed(self.s.live_retry_after_s):
            return out
        todo: list[str] = []
        for bid in dict.fromkeys(beacon_ids):
            if not bid.startswith("pioupiou:"):
                continue
            cached = self.trend_cache.get(bid)
            if cached is not None:
                if cached != "none":
                    out[bid] = cached
                continue
            if len(todo) < MAX_TREND_CALLS:
                todo.append(bid)
        sem = asyncio.Semaphore(3)

        async def one(bid: str) -> None:
            async with sem:
                try:
                    t = await asyncio.wait_for(self.pioupiou.fetch_trend(bid), timeout=self.s.http_timeout_s * 2)
                except (ProviderError, TimeoutError, httpx.HTTPError) as e:
                    st.record_failure(str(e) or type(e).__name__)
                    log.info("tendance Pioupiou indisponible pour %s (%s)", bid, e)
                    return
                st.record_success()
                self.trend_cache.set(bid, t if t is not None else "none")
                if t is not None:
                    out[bid] = t

        await asyncio.gather(*(one(b) for b in todo))
        return out

    @staticmethod
    def trend_source_ref() -> SourceRef:
        """Attribution de l'historique Pioupiou (sources[] des plans dont la tendance vient de /v1/archive)."""
        return SourceRef(name=PIOUPIOU_ARCHIVE_ATTRIBUTION, url=OPENWINDMAP_URL, fetched_at=iso(now_utc()), mode="live")

    async def terrain_function(
        self, bbox: tuple[float, float, float, float]
    ) -> tuple[Callable[[float, float], float], bool]:
        """MNT pour le moteur. Live : grille Open-Meteo (pas ~0,015°, ≤ 2500 points, en cache 7 j) ;
        sinon MNT synthétique. Renvoie (fonction, est_réel)."""
        if self.s.data_mode == "mock":
            return terrain_elevation, False
        min_lon, min_lat, max_lon, max_lat = bbox
        # pas pris dans une liste fixe et grille calée sur un réseau global : deux zones qui se recouvrent
        # partagent les points déjà en cache (7 j), ce qui ménage le quota Open-Meteo
        for step in TERRAIN_STEPS_DEG:
            lat0 = math.floor(min_lat / step) * step
            lon0 = math.floor(min_lon / step) * step
            nx = math.ceil((max_lon - lon0) / step) + 1
            ny = math.ceil((max_lat - lat0) / step) + 1
            if nx * ny <= MAX_TERRAIN_POINTS:
                break
        pts = [(round(lat0 + j * step, 4), round(lon0 + i * step, 4)) for j in range(ny) for i in range(nx)]
        vals, mode = await self.elevations(pts)
        if mode != "live":
            return terrain_elevation, False
        grid = {p: v for p, v in zip(pts, vals, strict=True)}

        def f(lat: float, lon: float) -> float:
            fy = (lat - lat0) / step
            fx = (lon - lon0) / step
            j, i = math.floor(fy), math.floor(fx)
            ty, tx = fy - j, fx - i
            def g(jj: int, ii: int) -> float | None:
                return grid.get((round(lat0 + jj * step, 4), round(lon0 + ii * step, 4)))
            c = [g(j, i), g(j, i + 1), g(j + 1, i), g(j + 1, i + 1)]
            if any(x is None for x in c):
                return terrain_elevation(lat, lon)
            return (c[0] * (1 - tx) + c[1] * tx) * (1 - ty) + (c[2] * (1 - tx) + c[3] * tx) * ty

        return f, True

    # ------------------------------------------------------------------------------------------
    # Décollage libre (CDC §12.6) : pente et exposition au MNT
    # ------------------------------------------------------------------------------------------
    async def takeoff_terrain(self, lat: float, lon: float, orientations: list[str] | None = None) -> TakeoffTerrain:
        """Grille MNT 5 × 5 (pas 100 m, un appel Open-Meteo Elevation) → exposition ; puis ligne de pente (50-150 m)
        et profil dans l'axe (50-300 m), un second appel groupé. Cache 7 j par point. Mode démo : MNT de
        démonstration. MNT réel indisponible (quota, réseau) : pente et exposition inconnues (jamais le MNT de démo
        pour un vol réel)."""
        demo_ok = self.s.data_mode == "mock"
        try:
            vals = await self.elevations_detailed(dem_grid_points(lat, lon))
        except ProviderError as e:
            log.info("MNT du décollage libre indisponible (%s)", e)
            return TakeoffTerrain(None, None, None, source="none", notes=["MNT indisponible"])
        live = all(m == "live" for _, m in vals)
        if not live and not demo_ok:
            return TakeoffTerrain(None, None, None, source="none", notes=["MNT indisponible (repli)"])
        z = [v for v, _ in vals]
        z0 = z[(GRID_N * GRID_N) // 2]
        _, aspect = analyze_grid(z)
        axis = axis_from_orientations(orientations or []) if orientations else None
        axis = aspect if axis is None else axis
        ds, dp = slope_distances(), profile_distances()
        try:
            vals2 = await self.elevations_detailed(axis_points(lat, lon, aspect, ds) + axis_points(lat, lon, axis, dp))
        except ProviderError as e:
            log.info("MNT de l'axe indisponible (%s)", e)
            return TakeoffTerrain(round(z0), None, round(aspect), source="dem" if live else "demo")
        z2 = [v for v, _ in vals2]
        slope = downslope_slope_pct(z0, z2[: len(ds)], ds)
        ok, detail = axis_profile(z0, z2[len(ds):], dp)
        return TakeoffTerrain(
            elevation_m=round(z0), slope_pct=round(slope, 1), aspect_deg=round(aspect) % 360, profile_ok=ok,
            profile_detail=detail, axis_deg=round(axis) % 360, source="dem" if live else "demo",
        )  # fmt: skip

    # ------------------------------------------------------------------------------------------
    # Atterros candidats hors sites (CDC §12.7) : OpenStreetMap (Overpass) ou démonstration
    # ------------------------------------------------------------------------------------------
    async def landing_spots(
        self, bbox: tuple[float, float, float, float], center: tuple[float, float], demo_context: bool
    ) -> tuple[list[LandingSpot], list[SourceRef], list[str]]:
        """Champs candidats et atterros vol libre. Overpass si activé (cache 24 h) ; sinon terrains de démonstration
        (fictifs) en mode démo seulement ; en live, rien (jamais de terrain fictif dans un plan réel)."""
        key = ("spots", self.s.data_mode, tuple(round(x, 2) for x in bbox))
        cached = self.spots_cache.get(key)
        if cached is not None:
            return cached
        warnings: list[str] = []
        res = None
        if self.s.data_mode != "mock":
            try:
                res = await self._try_live("overpass", lambda: self.overpass.fetch(bbox, center))
            except ProviderError as e:  # DATA_MODE=live : les champs OSM ne bloquent jamais le calcul
                warnings.append(f"Champs candidats OpenStreetMap indisponibles : {e}")
        if res is not None:
            await self.fill_spot_dem(res)
            out = (res, [SourceRef(name=OSM_ATTRIBUTION, url=OSM_COPYRIGHT_URL, fetched_at=iso(now_utc()),
                                   mode="live")], warnings)  # fmt: skip
            self.spots_cache.set(key, out)
            return out
        if self.s.data_mode == "mock" or demo_context:
            spots = fixture_landing_spots(bbox)
            refs = []
            if spots:
                refs.append(SourceRef(name="Atterros communautaires et champs de démonstration (fictifs)", url=None,
                                      fetched_at=iso(now_utc()), mode="mock"))  # fmt: skip
                warnings.append("Atterros communautaires et champs candidats de DÉMONSTRATION (fictifs) : ne jamais "
                                "les utiliser pour voler.")  # fmt: skip
            out = (spots, refs, warnings)
            self.spots_cache.set(key, out, ttl_s=600)
            return out
        warnings.append(
            "Champs candidats et atterros OpenStreetMap indisponibles (Overpass désactivé ou injoignable) : seuls les "
            "atterros ParaglidingEarth (officiels et communautaires) sont évalués."
        )
        return [], [], warnings

    async def fill_spot_dem(self, spots: list[LandingSpot]) -> None:
        """Altitude (centre) et pente (max des pentes en long et en travers) des champs OSM au MNT : 5 points par champ,
        un appel groupé (cache 7 j). MNT indisponible : altitude du MNT de démo exclue, pente inconnue."""
        todo = [sp for sp in spots if sp.site.elevation_m <= 0 or (sp.slope_pct is None and sp.size is not None)]
        if not todo:
            return
        pts: list[tuple[float, float]] = []
        for sp in todo:
            pts.append((sp.site.lat, sp.site.lon))
            if sp.size is not None and sp.axis_deg is not None:
                half_l, half_w = sp.size[0] / 2.0, sp.size[1] / 2.0
                for brg, d in ((sp.axis_deg, half_l), (sp.axis_deg + 180, half_l), (sp.axis_deg + 90, half_w),
                               (sp.axis_deg + 270, half_w)):  # fmt: skip
                    pts += axis_points(sp.site.lat, sp.site.lon, brg % 360, [d])
        try:
            vals = await self.elevations_detailed(pts)
        except ProviderError as e:
            log.info("MNT des champs indisponible (%s)", e)
            return
        i = 0
        for sp in todo:
            z0, m0 = vals[i]
            i += 1
            if sp.site.elevation_m <= 0 and (m0 == "live" or self.s.data_mode == "mock"):
                sp.site.elevation_m = float(round(z0))
            if sp.size is not None and sp.axis_deg is not None:
                zs = vals[i : i + 4]
                i += 4
                if all(m == "live" for _, m in zs):
                    along = abs(zs[0][0] - zs[1][0]) / max(1.0, sp.size[0]) * 100.0
                    across = abs(zs[2][0] - zs[3][0]) / max(1.0, sp.size[1]) * 100.0
                    sp.slope_pct = round(max(along, across), 1)

    # ------------------------------------------------------------------------------------------
    # Sites
    # ------------------------------------------------------------------------------------------
    async def sites(self, bbox) -> tuple[list[Site], dict[str, SiteMeta], list[SourceRef], list[str]]:
        key = ("sites", self.s.data_mode, tuple(round(x, 2) for x in bbox))
        cached = self.sites_cache.get(key)
        if cached is not None:
            return cached
        warnings: list[str] = []
        refs: list[SourceRef] = []
        groups: list[list[Site]] = []
        meta: dict[str, SiteMeta] = {}
        live_any = False
        for k, prov in (("ffvl-sites", self.ffvl_sites), ("paraglidingearth", self.pge), ("spotair", self.spotair)):
            res = await self._try_live(k, lambda prov=prov: prov.fetch(bbox))
            if res is not None:
                sites, m = res
                groups.append(sites)
                meta.update(m)
                live_any = True
                refs.append(
                    SourceRef(name=self.states[k].name, url=self.states[k].url, fetched_at=iso(now_utc()), mode="live")
                )
        if not live_any:
            sites_all, m = fixture_sites()
            min_lon, min_lat, max_lon, max_lat = expand_bbox(bbox, 15)
            fx = [s for s in sites_all if min_lat <= s.lat <= max_lat and min_lon <= s.lon <= max_lon]
            groups.append(fx)
            meta.update(m)
            refs.append(
                SourceRef(name="Sites de démonstration (fixtures)", url=None, fetched_at=iso(now_utc()), mode="mock")
            )
        merged = merge_sites(groups)
        # altitudes manquantes / incohérentes (règle PGE d)
        need = [s for s in merged if s.source != "fixture"]
        dem_ok = True
        if need:
            try:
                elevs, emode = await self.elevations([(s.lat, s.lon) for s in need])
            except ProviderError as e:
                # MNT indisponible en live (quota, réseau) : les sites restent servis avec l'altitude de leur
                # source ; un site sans altitude est écarté (jamais d'altitude inventée) ; résultat en cache court.
                dem_ok = False
                unknown = {s.id for s in need if s.elevation_m <= 0}
                merged = [s for s in merged if s.id not in unknown]
                warnings.append(
                    f"MNT indisponible ({e}) : altitudes des sites non vérifiées"
                    + (f", {len(unknown)} site(s) sans altitude écarté(s)." if unknown else ".")
                )
            else:
                for s, el in zip(need, elevs, strict=True):
                    if s.elevation_m <= 0:
                        s.elevation_m = round(el)
                    elif emode == "live" and abs(s.elevation_m - el) > 150 and s.kind != "landing":
                        warnings.append(
                            f"Altitude de « {s.name} » corrigée par le MNT ({s.elevation_m:.0f} → {el:.0f} m)."
                        )
                        s.elevation_m = round(el)
        associate_landings(merged)
        result = (merged, meta, refs, warnings)
        # repli (échec live transitoire, MNT absent) : cache court, pour ne pas figer ce résultat pendant 24 h
        full = (live_any and dem_ok) or self.s.data_mode == "mock"
        self.sites_cache.set(key, result, ttl_s=None if full else 600)
        return result

    # ------------------------------------------------------------------------------------------
    # Balises
    # ------------------------------------------------------------------------------------------
    async def beacons(self, bbox, at: datetime | None = None) -> tuple[list[Beacon], dict[str, float], list[SourceRef]]:
        now = now_utc()
        at = at or now
        refs: list[SourceRef] = []
        out: list[Beacon] = []
        live_any = False
        if abs((at - now).total_seconds()) < 3600:
            for k, prov in (("pioupiou", self.pioupiou), ("ffvl-beacons", self.ffvl_beacons)):
                cached = self.beacons_cache.get(k)
                res = cached if cached is not None else await self._try_live(k, prov.fetch_all)
                if res is not None:
                    self.beacons_cache.set(k, res)
                    out += filter_bbox(res, bbox)
                    live_any = True
                    name, url = (
                        (PIOUPIOU_ATTRIBUTION, OPENWINDMAP_URL)
                        if k == "pioupiou"
                        else (self.states[k].name, self.states[k].url)
                    )
                    refs.append(SourceRef(name=name, url=url, fetched_at=iso(now), mode="live"))
        if live_any:
            return out, ages_from(out, now), refs
        if self.s.data_mode == "live":
            return [], {}, refs
        fb, ages = self.fixture_beacons.fetch_sync(at)
        fb = filter_bbox(fb, bbox)
        refs.append(SourceRef(name=DEMO_BEACONS_ATTRIBUTION, url=OPENWINDMAP_URL, fetched_at=iso(now), mode="mock"))
        return fb, {b.id: ages[b.id] for b in fb}, refs

    # ------------------------------------------------------------------------------------------
    # Espaces aériens : OpenAIP > OpenAir > fixtures
    # ------------------------------------------------------------------------------------------
    async def airspaces(self, bbox, terrain=None) -> tuple[list[Airspace], list[SourceRef]]:
        key = ("asp", tuple(round(x, 2) for x in bbox))
        cached = self.airspace_cache.get(key)
        if cached is not None:
            return cached
        now = now_utc()
        import time as _time

        res = None
        # OpenAIP : au plus un appel toutes les 5 min (limitation Cloudflare), pas de retry en boucle
        if _time.monotonic() - self._openaip_last_call > 300 or self._openaip_last_call == 0.0:
            if not self.states["openaip"].disabled_message and self.s.data_mode != "mock":
                self._openaip_last_call = _time.monotonic()
            res = await self._try_live("openaip", lambda: self.openaip.fetch(bbox, terrain))
        if res is not None:
            out = (res, [SourceRef(name="OpenAIP", url="https://www.openaip.net", fetched_at=iso(now), mode="live")])
            self.airspace_cache.set(key, out)
            return out
        if self.s.data_mode != "mock":
            try:
                oa = self.openair.fetch(bbox, terrain)
                out = (oa, [SourceRef(name="Fichiers OpenAir locaux", url=None, fetched_at=iso(now), mode="live")])
                self.airspace_cache.set(key, out, ttl_s=600)
                return out
            except ProviderDisabled:
                pass
            except Exception as e:  # fichier mal formé
                self.states["openair"].record_failure(str(e))
        out = (
            fixture_airspace_list(bbox),
            [
                SourceRef(
                    name="Espaces aériens de démonstration (approximatifs)", url=None, fetched_at=iso(now), mode="mock"
                )
            ],
        )
        self.airspace_cache.set(key, out, ttl_s=600)
        return out

    # ------------------------------------------------------------------------------------------
    # Zones sensibles
    # ------------------------------------------------------------------------------------------
    async def sensitive_areas(self, bbox) -> tuple[list[SensitiveArea], list[SourceRef]]:
        key = ("sens", self.s.data_mode, tuple(round(x, 2) for x in bbox))
        cached = self.sensitive_cache.get(key)
        if cached is not None:
            return cached
        now = now_utc()
        res = await self._try_live("biodivsports", lambda: self.biodiv.fetch(bbox))
        parks = fixture_areas(bbox, parks_only=True)
        if res is not None:
            out = (
                merge_areas(res, parks),
                [SourceRef(name="Biodiv'Sports", url="https://biodiv-sports.fr", fetched_at=iso(now), mode="live")],
            )
        else:
            out = (
                fixture_areas(bbox, parks_only=False),
                [
                    SourceRef(
                        name="Zones sensibles de démonstration + cœurs de parcs (approximatifs)",
                        url=None,
                        fetched_at=iso(now),
                        mode="mock",
                    )
                ],
            )
        # repli (échec live transitoire) : cache court (10 min) au lieu de 24 h
        self.sensitive_cache.set(key, out, ttl_s=None if res is not None or self.s.data_mode == "mock" else 600)
        return out

    # ------------------------------------------------------------------------------------------
    # Prévisions
    # ------------------------------------------------------------------------------------------
    async def forecasts(
        self,
        points: list[tuple[float, float, float | None]],
        start: datetime,
        end: datetime,
        issued_at: datetime,
        with_levels: bool = True,
    ) -> tuple[list[PointForecast], list[SourceRef]]:
        key_base = (start.isoformat(), end.isoformat(), with_levels)
        out: list[PointForecast | None] = []
        missing_idx = []
        for i, (la, lo, el) in enumerate(points):
            k = ("fc", round(la, 3), round(lo, 3), None if el is None else round(el), *key_base)
            v = self.forecast_cache.get(k)
            out.append(v)
            if v is None:
                missing_idx.append(i)
        if missing_idx:
            miss = [points[i] for i in missing_idx]
            res = await self._try_live("open-meteo", lambda: self.om.fetch(miss, start, end, with_levels))
            if res is None:
                res = self.synthetic.fetch_sync(miss, start, end, issued_at)
            for i, pf in zip(missing_idx, res, strict=True):
                la, lo, el = points[i]
                k = ("fc", round(la, 3), round(lo, 3), None if el is None else round(el), *key_base)
                self.forecast_cache.set(k, pf, ttl_s=None if pf.mode == "live" else 600)
                out[i] = pf
        fcs = [x for x in out if x is not None]
        modes = {pf.mode for pf in fcs}
        refs = []
        if "live" in modes:
            refs.append(
                SourceRef(
                    name="Open-Meteo (" + ", ".join(self.s.open_meteo_model_list) + ")",
                    url="https://open-meteo.com",
                    fetched_at=iso(min(pf.fetched_at for pf in fcs if pf.mode == "live")),
                    mode="live",
                )
            )
        if "mock" in modes:
            refs.append(SourceRef(name="Météo synthétique (démo)", url=None, fetched_at=iso(now_utc()), mode="mock"))
        return fcs, refs


# =============================================================================================
# Prévision brute → timeline analysée
# =============================================================================================
def build_timeline(pf: PointForecast, wind_ground_m: float | None, t_from: datetime, t_to: datetime) -> PointTimeline:
    times = [t for t in pf.times() if t_from <= t <= t_to]
    hours = []
    spreads = {}
    model_winds: dict[datetime, list[tuple[str, float, float]]] = {}
    labels = sorted({m.model for m in pf.models})
    for t in times:
        per_model = [(m.model, m.hour_at(t)) for m in pf.models]
        per_model = [(name, h) for name, h in per_model if h is not None]
        if not per_model:
            continue
        agg = aggregate_hours([h for _, h in per_model], t)
        try:
            a = analyze_hour(agg, pf.elevation_m, pf.lat, pf.lon, [n for n, _ in per_model], wind_ground_m)
        except ValueError:
            continue
        hours.append(a)
        spreads[t] = hour_spread([h for _, h in per_model], [n for n, _ in per_model])
        v_site, d_site = a.profile.wind(pf.elevation_m)
        ratio = v_site / a.wind_speed_kmh if a.wind_speed_kmh > 1 else 1.0
        rot = ((d_site - a.wind_direction_deg + 180) % 360) - 180
        model_winds[t] = [
            (name, (h.wind_speed_10m or 0.0) * ratio, ((h.wind_direction_10m or 0.0) + rot) % 360)
            for name, h in per_model
            if h.wind_speed_10m is not None
        ]
    label = "synthetic" if pf.mode == "mock" else "+".join(labels)
    return PointTimeline(pf.lat, pf.lon, pf.elevation_m, hours, spreads, model_winds, mode=pf.mode, model_label=label)


def smoothed_ground(terrain: Callable[[float, float], float], lat: float, lon: float, radius_km: float = 2.5) -> float:
    vals = [terrain(lat, lon)]
    for b in range(0, 360, 45):
        for r in (radius_km * 0.5, radius_km):
            la, lo = destination(lat, lon, b, r)
            vals.append(terrain(la, lo))
    return sum(vals) / len(vals)


def hours_window(target: datetime) -> tuple[datetime, datetime]:
    t = target.replace(minute=0, second=0, microsecond=0)
    return t - timedelta(hours=14), t + timedelta(hours=14)


def quota_backoff_s(
    key: str, message: str, now: datetime, default_s: float, daily_max_s: float = DAILY_429_MAX_BLOCK_S
) -> tuple[float, str]:
    """Durée de suspension d'une source après un HTTP 429 et motif lisible.

    Open-Meteo dit quelle limite est atteinte (« Daily / Hourly / Minutely API request limit exceeded ») : on attend
    le début du jour UTC suivant, de l'heure suivante ou 1 min. Un en-tête Retry-After (repris dans le message
    d'erreur) est respecté. OpenAIP (Cloudflare) : au moins 5 min. Jamais moins que `default_s`."""
    low = message.lower()
    wait = default_s
    why = "limitation de débit (HTTP 429)"
    if "daily" in low:
        # le quota se réinitialise à 00h00 UTC ; on réessaie au plus tard 1 h après (un appel par heure ne coûte
        # rien et rattrape un 429 passager : adresse de sortie partagée, proxy)
        nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        wait = max(wait, min((nxt - now).total_seconds() + 60, daily_max_s))
        why = (f"quota journalier atteint (HTTP 429, réinitialisé à 00h00 UTC) : nouvel essai dans "
               f"{max(wait, 60) / 60:.0f} min au plus")  # fmt: skip
    elif "hourly" in low:
        nxt = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        wait = max(wait, (nxt - now).total_seconds() + 30)
        why = "quota horaire atteint (HTTP 429) : nouvel essai à l'heure suivante"
    elif "minutely" in low:
        wait = max(wait, 60.0)
        why = "quota par minute atteint (HTTP 429)"
    m = re.search(r"réessayer dans (\d+) s", message)
    if m:
        wait = max(wait, float(m.group(1)))
    wait = max(wait, MIN_429_BACKOFF_S.get(key, 0.0))
    return wait, why
