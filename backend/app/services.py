"""Service de données : choisit live / mock selon DATA_MODE, gère le repli, le cache et l'état des sources.

DATA_MODE=auto : chaque source live est tentée (timeout court) ; en cas d'échec, repli silencieux
sur le mock et la source n'est pas retentée pendant `live_retry_after_s`. Les réponses indiquent le
mode effectivement utilisé (`data_mode`, `sources[].mode`).
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.cache import TTLCache
from app.config import Settings
from app.engine.context import Airspace, PointTimeline, SensitiveArea, SiteMeta
from app.geo import destination, expand_bbox
from app.meteo.ensemble import aggregate_hours, hour_spread
from app.meteo.snapshot import iso
from app.meteo.thermals import analyze_hour
from app.meteo.types import PointForecast
from app.models import Beacon, BeaconTrend, Site, SourceRef, SourceStatus
from app.providers.airspaces import OpenAipAirspaces, OpenAirFiles, fixture_airspace_list
from app.providers.base import ProviderDisabled, ProviderError, SourceState, make_client, now_utc
from app.providers.beacons import FfvlBeacons, FixtureBeacons, PioupiouBeacons, ages_from, filter_bbox
from app.providers.open_meteo import OpenMeteoElevation, OpenMeteoForecast
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
OPENWINDMAP_URL = "https://www.openwindmap.org"
PIOUPIOU_ATTRIBUTION = (
    "Pioupiou / OpenWindMap — balises temps réel et historique 1 h, (c) contributors of the OpenWindMap wind network "
    "(licence : https://developers.pioupiou.fr/data-licensing)"
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
        self.om = OpenMeteoForecast(self.client, settings.open_meteo_base_url, settings.open_meteo_model_list, settings.open_meteo_api_key)
        self.om_elev = OpenMeteoElevation(self.client, settings.open_meteo_elevation_url)
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
            "open-meteo-elevation": SourceState("Open-Meteo Elevation", "elevation", "https://open-meteo.com/en/docs/elevation-api"),
            "paraglidingearth": SourceState("ParaglidingEarth", "sites", "https://www.paraglidingearth.com"),
            "pioupiou": SourceState("Pioupiou / OpenWindMap", "beacons", "https://www.openwindmap.org"),
            "pioupiou-archive": SourceState("Pioupiou / OpenWindMap (historique 1 h, tendance)", "beacons",
                                            "https://developers.pioupiou.fr/api/archive/"),
            "openaip": SourceState("OpenAIP", "airspaces", "https://www.openaip.net", requires_api_key=True,
                                   api_key_configured=bool(s.openaip_api_key)),
            "openair": SourceState("Fichiers OpenAir locaux", "airspaces", None),
            "biodivsports": SourceState("Biodiv'Sports", "sensitive_areas", "https://biodiv-sports.fr"),
            "ffvl-sites": SourceState("FFVL (terrains)", "sites", "https://data.ffvl.fr", requires_api_key=True,
                                      api_key_configured=bool(s.ffvl_api_key)),
            "ffvl-beacons": SourceState("FFVL (balises)", "beacons", "https://data.ffvl.fr", requires_api_key=True,
                                        api_key_configured=bool(s.ffvl_api_key)),
            "spotair": SourceState("SpotAir", "sites", "https://www.spotair.mobi", requires_api_key=True,
                                   api_key_configured=bool(s.spotair_api_key)),
            "meteo-parapente": SourceState("Météo-Parapente", "forecast", "https://meteo-parapente.com", requires_api_key=True,
                                           api_key_configured=bool(s.meteo_parapente_api_key)),
            "fixtures": SourceState("Données de démonstration (fixtures + météo synthétique)", "sites", None),
        }  # fmt: skip
        if not s.ffvl_api_key:
            msg = ("Désactivé : clé API FFVL requise. Demande à faire auprès de la FFVL (data.ffvl.fr, formulaire de "
                   "demande d'accès aux données) puis renseigner FFVL_API_KEY.")  # fmt: skip
            st["ffvl-sites"].disabled_message = msg
            st["ffvl-beacons"].disabled_message = msg
        if not s.openaip_api_key:
            st["openaip"].disabled_message = (
                "Désactivé : clé OpenAIP absente. Créer un compte gratuit sur openaip.net puis générer une clé API dans "
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
                    )  # fmt: skip
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
                msg = f"Dernier appel en échec : {st.last_error}" + (" — repli sur les données de démonstration." if mode == "auto" else "")
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
        failed = [st for st in core if st.last_error and (st.last_success is None or (st.last_failure or 0) > st.last_success)]
        if not failed:
            return "live"
        if len(failed) == len(core):
            return "mock"
        return "mixed"

    # ------------------------------------------------------------------------------------------
    async def _try_live(self, key: str, live: Callable[[], Awaitable[Any]]) -> Any | None:
        """Exécute l'appel live selon DATA_MODE ; None si mock / repli. Lève en mode live strict."""
        st = self.states[key]
        mode = self.s.data_mode
        if mode == "mock" or st.disabled_message:
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
        missing = [k for k in dict.fromkeys(keys) if self.elev_cache.get(("e",) + k) is None]
        if missing:
            res = await self._try_live("open-meteo-elevation", lambda: self.om_elev.fetch(missing))
            if res is not None:
                for k, v in zip(missing, res, strict=True):
                    self.elev_cache.set(("e",) + k, (v, "live"))
            else:
                for k in missing:
                    self.elev_cache.set(("e",) + k, (terrain_elevation(*k), "mock"), ttl_s=600)
        return [self.elev_cache.get(("e",) + k) for k in keys]

    async def elevations(self, points: list[tuple[float, float]]) -> tuple[list[float], str]:
        vals = await self.elevations_detailed(points)
        mode = "live" if vals and all(v[1] == "live" for v in vals) else "mock"
        return [v[0] for v in vals], mode

    async def beacon_dem(self, beacons: list[Beacon]) -> dict[str, float]:
        """Altitude MNT au point des balises sans altitude (Pioupiou n'en fournit pas, CDC §12.1) : un seul appel
        Open-Meteo Elevation groupé pour les balises de la zone, en cache 7 j. Balises de démonstration : MNT de démo.
        Une balise réelle dont le MNT réel est indisponible est absente du résultat (« altitude inconnue »)."""
        unknown = [b for b in beacons if b.elevation_m is None]
        if not unknown:
            return {}
        out: dict[str, float] = {}
        demo = [b for b in unknown if b.source == "fixture"]
        for b in demo:
            out[b.id] = round(terrain_elevation(b.lat, b.lon))
        real = [b for b in unknown if b.source != "fixture"]
        if real and self.s.data_mode != "mock":
            vals = await self.elevations_detailed([(b.lat, b.lon) for b in real])
            for b, (v, mode) in zip(real, vals, strict=True):
                if mode == "live":
                    out[b.id] = round(v)
        return out

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

    async def terrain_function(self, bbox: tuple[float, float, float, float]) -> tuple[Callable[[float, float], float], bool]:
        """MNT pour le moteur. Live : grille Open-Meteo (pas ~0,015°, ≤ 2500 points, en cache 7 j) ;
        sinon MNT synthétique. Renvoie (fonction, est_réel)."""
        if self.s.data_mode == "mock":
            return terrain_elevation, False
        min_lon, min_lat, max_lon, max_lat = bbox
        step = 0.015
        nx = int((max_lon - min_lon) / step) + 2
        ny = int((max_lat - min_lat) / step) + 2
        if nx * ny > 2500:
            step = math.sqrt((max_lon - min_lon) * (max_lat - min_lat) / 2500.0)
            nx = int((max_lon - min_lon) / step) + 2
            ny = int((max_lat - min_lat) / step) + 2
        lat0 = math.floor(min_lat / step) * step
        lon0 = math.floor(min_lon / step) * step
        pts = [(round(lat0 + j * step, 4), round(lon0 + i * step, 4)) for j in range(ny) for i in range(nx)]
        vals, mode = await self.elevations(pts)
        if mode != "live":
            return terrain_elevation, False
        grid = {p: v for p, v in zip(pts, vals, strict=True)}

        def f(lat: float, lon: float) -> float:
            fy = (lat - lat0) / step
            fx = (lon - lon0) / step
            j, i = int(math.floor(fy)), int(math.floor(fx))
            ty, tx = fy - j, fx - i
            def g(jj: int, ii: int) -> float | None:
                return grid.get((round(lat0 + jj * step, 4), round(lon0 + ii * step, 4)))
            c = [g(j, i), g(j, i + 1), g(j + 1, i), g(j + 1, i + 1)]
            if any(x is None for x in c):
                return terrain_elevation(lat, lon)
            return (c[0] * (1 - tx) + c[1] * tx) * (1 - ty) + (c[2] * (1 - tx) + c[3] * tx) * ty

        return f, True

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
                refs.append(SourceRef(name=self.states[k].name, url=self.states[k].url, fetched_at=iso(now_utc()), mode="live"))
        if not live_any:
            sites_all, m = fixture_sites()
            min_lon, min_lat, max_lon, max_lat = expand_bbox(bbox, 15)
            fx = [s for s in sites_all if min_lat <= s.lat <= max_lat and min_lon <= s.lon <= max_lon]
            groups.append(fx)
            meta.update(m)
            refs.append(SourceRef(name="Sites de démonstration (fixtures)", url=None, fetched_at=iso(now_utc()), mode="mock"))
        merged = merge_sites(groups)
        # altitudes manquantes / incohérentes (règle PGE d)
        need = [s for s in merged if s.source != "fixture"]
        if need:
            elevs, emode = await self.elevations([(s.lat, s.lon) for s in need])
            for s, e in zip(need, elevs, strict=True):
                if s.elevation_m <= 0:
                    s.elevation_m = round(e)
                elif emode == "live" and abs(s.elevation_m - e) > 150 and s.kind != "landing":
                    warnings.append(f"Altitude de « {s.name} » corrigée par le MNT ({s.elevation_m:.0f} → {e:.0f} m).")
                    s.elevation_m = round(e)
        associate_landings(merged)
        result = (merged, meta, refs, warnings)
        self.sites_cache.set(key, result)
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
                    name, url = (PIOUPIOU_ATTRIBUTION, OPENWINDMAP_URL) if k == "pioupiou" else (self.states[k].name, self.states[k].url)
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
        out = (fixture_airspace_list(bbox), [SourceRef(name="Espaces aériens de démonstration (approximatifs)", url=None,
                                                       fetched_at=iso(now), mode="mock")])  # fmt: skip
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
            out = (merge_areas(res, parks), [SourceRef(name="Biodiv'Sports", url="https://biodiv-sports.fr", fetched_at=iso(now), mode="live")])
        else:
            out = (fixture_areas(bbox, parks_only=False),
                   [SourceRef(name="Zones sensibles de démonstration + cœurs de parcs (approximatifs)", url=None, fetched_at=iso(now), mode="mock")])  # fmt: skip
        self.sensitive_cache.set(key, out)
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
            refs.append(SourceRef(name="Open-Meteo (" + ", ".join(self.s.open_meteo_model_list) + ")", url="https://open-meteo.com",
                                  fetched_at=iso(min(pf.fetched_at for pf in fcs if pf.mode == "live")), mode="live"))  # fmt: skip
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
