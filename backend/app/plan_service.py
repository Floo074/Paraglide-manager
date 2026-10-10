"""Orchestration des requêtes POST /api/plans (modes classique et décollage libre) et POST /api/landings/analyze :
collecte des données, moteur, cache des plans."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.cache import TTLCache
from app.engine import rules
from app.engine.airspace import low_overflight_areas
from app.engine.conditions import dir_label
from app.engine.context import DataContext, PointTimeline, ReliefPoint, SiteMeta
from app.engine.free_takeoff import pct_txt
from app.engine.landings import LandingSpot, analyze_free_takeoff
from app.engine.planner import evaluate_sites
from app.engine.routing import landing_kind_of
from app.engine.terrain import TakeoffTerrain, orientations_from_aspect
from app.geo import expand_bbox, haversine_km
from app.meteo.snapshot import iso
from app.meteo.solar import sunrise_sunset
from app.models import (
    HORIZON_MINUTES,
    BBoxZone,
    CircleZone,
    CustomTakeoff,
    FlightPlan,
    LandingsAnalyzeRequest,
    LandingsAnalyzeResponse,
    PlanFilters,
    PlanRequest,
    PlanResponse,
    RejectedSite,
    Site,
    SourceRef,
    zone_bbox,
)
from app.providers.fixture_data import fixture_relief
from app.providers.open_meteo_minutely import minutely_window
from app.providers.synthetic_terrain import smoothed_terrain
from app.services import DataService, build_timeline, hours_window, smoothed_ground

MAX_TAKEOFFS = 25


def parse_reference(s: str | None) -> datetime:
    if not s:
        return datetime.now(UTC).replace(microsecond=0)
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def round_hour(t: datetime) -> datetime:
    base = t.replace(minute=0, second=0, microsecond=0)
    return base + timedelta(hours=1) if (t.minute * 60 + t.second) >= 1800 else base


def round_target(t: datetime, horizon: str) -> datetime:
    """Heure cible arrondie au pas de prévision : l'heure (modèles horaires), ou 15 min pour les horizons ≤ 1 h,
    où le vent retenu vient surtout des balises (nowcasting, pas de 15 min, CDC §12.5). La demie est arrondie vers le
    haut (floor(x + 0,5)), comme `Math.round` côté front (frontend/src/utils/horizon.ts)."""
    if horizon in rules.NOWCAST_WINDOW_START_MIN:
        q = math.floor((t.minute * 60 + t.second) / 900.0 + 0.5)
        return t.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=15 * q)
    return round_hour(t)


def target_for(ref: datetime, horizon: str) -> datetime:
    """Heure cible du moteur = heure cible publiée (PlanResponse.target_time, FlightPlan.target_time) : toujours
    arrondie au pas de prévision (revue : le moteur évaluait 12:20 en annonçant 12:00)."""
    return round_target(ref + timedelta(minutes=HORIZON_MINUTES[horizon]), horizon)


def request_key(req) -> str:
    """Empreinte de la requête normalisée (zone, horizon, référence, mode, décollage libre, tous les filtres) : entre
    dans l'id des plans, pour qu'un id ne désigne jamais deux contenus différents (revue : collision d'ids)."""
    raw = json.dumps(req.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode()).hexdigest()[:10]


def in_zone(zone: BBoxZone | CircleZone, lat: float, lon: float) -> bool:
    if isinstance(zone, BBoxZone):
        return zone.min_lat <= lat <= zone.max_lat and zone.min_lon <= lon <= zone.max_lon
    return haversine_km(zone.center.lat, zone.center.lon, lat, lon) <= zone.radius_km


def zone_center(zone: BBoxZone | CircleZone) -> tuple[float, float]:
    if isinstance(zone, BBoxZone):
        return (zone.min_lat + zone.max_lat) / 2, (zone.min_lon + zone.max_lon) / 2
    return zone.center.lat, zone.center.lon


def reach_bound_km(takeoff_alt: float, landing_alt: float, wing: float) -> float:
    """Portée maximale vraisemblable (pré-filtre large : k = 0,75, fort vent arrière) ; calcul exact : le moteur."""
    return max(0.0, takeoff_alt - landing_alt) * wing * 0.75 * 1.6 / 1000.0


def cluster_forecast_points(origin: Site, sites: list[Site]) -> list[tuple[Site, list[Site]]]:
    """Regroupe les atterros candidats autour d'au plus N points de prévision (≤ 3 km : même prévision, maille AROME
    1,3 km) pour ménager le quota Open-Meteo."""
    clusters: list[tuple[Site, list[Site]]] = []
    for s in sorted(sites, key=lambda x: haversine_km(origin.lat, origin.lon, x.lat, x.lon)):
        best = min(clusters, key=lambda c: haversine_km(c[0].lat, c[0].lon, s.lat, s.lon), default=None)
        if best is not None and (
            haversine_km(best[0].lat, best[0].lon, s.lat, s.lon) <= rules.LANDING_FORECAST_CLUSTER_KM
            or len(clusters) >= rules.LANDING_FORECAST_CLUSTERS
        ):
            best[1].append(s)
        else:
            clusters.append((s, [s]))
    return clusters


def terrain_text(t: TakeoffTerrain) -> str:
    """Lecture du MNT au point, pour les avertissements de l'analyse."""
    if not t.measured:
        return "Pente et orientation du point non mesurées (MNT indisponible) : à vérifier sur place."
    src = "MNT de démonstration" if t.source == "demo" else "MNT Copernicus 90 m (Open-Meteo)"
    prof = {True: "profil de l'axe dégagé sur 300 m", False: f"profil de l'axe : {t.profile_detail}",
            None: "profil de l'axe non contrôlé"}[t.profile_ok]  # fmt: skip
    sp = rules.FREE_TAKEOFF["slope_pct"]
    x = t.slope_pct
    if x < sp["min"]:  # revue 7.21 : la lecture dit si la pente convient
        verdict = f"trop faible pour décoller (minimum {sp['min']} % avec du vent de face)"
    elif x < sp["min_without_headwind"]:
        verdict = (f"insuffisante sans vent de face (minimum {sp['min_without_headwind']} %, ou {sp['min']} % avec au "
                   f"moins {sp['headwind_for_gentle_kmh']} km/h de vent de face)")  # fmt: skip
    elif x > max(sp["max"].values()):
        verdict = f"trop raide (maximum {max(sp['max'].values())} %)"
    elif x > min(sp["max"].values()):
        verdict = "raide : réservée aux pilotes confirmés"
    else:
        verdict = "convenable"
    return (f"Terrain au point ({src}) : pente {pct_txt(x, sp['min_without_headwind'])} % sur 150 m, "
            f"{verdict}, orientée {dir_label(t.aspect_deg)} ; {prof}.")  # fmt: skip


@dataclass
class _Gathered:
    """Données collectées pour un calcul (communes aux deux modes)."""

    ref: datetime
    target: datetime
    horizon: str
    takeoffs: list[Site]
    landings: dict[str, Site]
    meta: dict[str, SiteMeta]
    timelines: dict[str, PointTimeline]
    refs: list[SourceRef]
    warnings: list[str]
    bbox: tuple[float, float, float, float]
    terrain: object = None
    terrain_real: bool = False
    free_terrain: dict[str, TakeoffTerrain] = field(default_factory=dict)
    spots: dict[str, LandingSpot] = field(default_factory=dict)
    rejected: list[RejectedSite] = field(default_factory=list)
    landing_points: list[Site] = field(default_factory=list)  # points de prévision des atterros


class PlanService:
    def __init__(self, data: DataService, plans_ttl_s: int) -> None:
        self.data = data
        self.plans = TTLCache(plans_ttl_s, 2000)

    def get(self, plan_id: str) -> FlightPlan | None:
        return self.plans.get(plan_id)

    # ------------------------------------------------------------------------------------------
    # POST /api/plans
    # ------------------------------------------------------------------------------------------
    async def create(self, req: PlanRequest) -> PlanResponse:
        ref = parse_reference(req.reference_time)
        target = target_for(ref, req.horizon)
        if req.mode == "custom_takeoff" and req.custom_takeoff is not None:
            g = await self._gather_free(req.custom_takeoff, ref, target, req.horizon, req.filters)
        else:
            g = await self._gather_classic(req, ref, target)
        ctx, data_mode = await self._context(g, req.filters.duration_max_minutes)
        ctx.request_key = request_key(req)
        plans, rejected, warns = await self._evaluate(ctx, req.filters, g)
        for p in plans:
            self.plans.set(p.id, p)
        return PlanResponse(
            request_id=str(uuid.uuid4()),
            generated_at=iso(datetime.now(UTC)),
            target_time=iso(round_target(target, req.horizon)),
            horizon=req.horizon,
            zone=req.zone,
            data_mode=data_mode,
            plans=plans,
            rejected=[*g.rejected, *rejected],
            warnings=list(dict.fromkeys(warns)),
        )

    async def _gather_classic(self, req: PlanRequest, ref: datetime, target: datetime) -> _Gathered:
        """Mode classique : déco ET atterro officiels (CDC §12.7) ; les décos communautaires sont listés en rejet."""
        bbox = zone_bbox(req.zone)
        big_bbox = expand_bbox(bbox, 15)
        warnings: list[str] = []
        sites, meta, site_refs, site_warn = await self.data.sites(big_bbox)
        warnings += site_warn
        clat, clon = zone_center(req.zone)
        in_area = [s for s in sites if s.kind in ("takeoff", "both") and in_zone(req.zone, s.lat, s.lon)]
        takeoffs = [s for s in in_area if s.official]
        unofficial_txt = (
            "Déco non officiel (fiche communautaire) : non évalué en mode classique — "
            "étudie-le en mode décollage libre."
        )
        rejected = [RejectedSite(site=s, reasons=[unofficial_txt]) for s in in_area if not s.official]
        takeoffs.sort(key=lambda s: haversine_km(clat, clon, s.lat, s.lon))
        if len(takeoffs) > MAX_TAKEOFFS:
            warnings.append(f"{len(takeoffs)} décollages dans la zone : seuls les {MAX_TAKEOFFS} plus proches du "
                            f"centre sont évalués.")  # fmt: skip
            takeoffs = takeoffs[:MAX_TAKEOFFS]
        if req.filters.landing_policy != "official_only":
            warnings.append("Mode classique : seuls les atterros officiels sont utilisés. Les atterros communautaires "
                            "et les champs se choisissent en mode décollage libre.")  # fmt: skip
        landings = {s.id: s for s in sites if s.kind in ("landing", "both") and landing_kind_of(s) == "official"}
        needed: dict[str, Site] = {}
        for t in takeoffs:
            for lid in t.associated_landing_ids[:3]:
                if lid in landings:
                    needed[lid] = landings[lid]
        terrain, terrain_real = await self.data.terrain_function(big_bbox)
        start, end = hours_window(target)
        refs: list[SourceRef] = list(site_refs)
        timelines: dict[str, PointTimeline] = {}
        if takeoffs:
            fcs, frefs = await self.data.forecasts(
                [(s.lat, s.lon, s.elevation_m) for s in takeoffs], start, end, ref, with_levels=True
            )
            refs += frefs
            for s, pf in zip(takeoffs, fcs, strict=True):
                sg = smoothed_ground(terrain, s.lat, s.lon) if terrain_real else smoothed_terrain(s.lat, s.lon)
                timelines[s.id] = build_timeline(pf, sg, start, end)
        ld_list = list(needed.values())
        if ld_list:
            fcs, frefs = await self.data.forecasts([(s.lat, s.lon, s.elevation_m) for s in ld_list], start, end, ref,
                                                   with_levels=self.data.s.data_mode == "mock")  # fmt: skip
            refs += [r for r in frefs if r.name not in {x.name for x in refs}]
            for s, pf in zip(ld_list, fcs, strict=True):
                timelines[s.id] = build_timeline(pf, None, start, end)
        if not takeoffs:
            warnings.append("Aucun décollage officiel connu dans la zone sélectionnée.")
        return _Gathered(
            ref=ref, target=target, horizon=req.horizon, takeoffs=takeoffs, landings=landings, meta=dict(meta),
            timelines=timelines, refs=refs, warnings=warnings, bbox=bbox, terrain=terrain, terrain_real=terrain_real,
            rejected=rejected, landing_points=ld_list,
        )  # fmt: skip

    async def _gather_free(
        self, ct: CustomTakeoff, ref: datetime, target: datetime, horizon: str, filters: PlanFilters
    ) -> _Gathered:
        """Décollage libre (CDC §12.6) : MNT au point (pente, exposition), atterros candidats (officiels,
        communautaires, champs selon landing_policy) dans la portée de plané, prévisions groupées."""
        terrain_info = await self.data.takeoff_terrain(ct.lat, ct.lon, ct.orientations)
        elev = ct.elevation_m if ct.elevation_m is not None else terrain_info.elevation_m
        dem = terrain_info.elevation_m if terrain_info.source in ("dem", "demo", "scenario") else None
        if ct.elevation_m is not None and dem is not None:
            # revue : une faute de frappe (+1000 m) rendait « atteignables » des atterros hors de portée
            diff = ct.elevation_m - dem
            if abs(diff) > rules.CUSTOM_ELEVATION_MAX_DIFF_M:
                elev = min(ct.elevation_m, dem + rules.CUSTOM_ELEVATION_CLIFF_M)
                terrain_info.elevation_note = (
                    f"Altitude saisie {ct.elevation_m:.0f} m très différente du MNT ({dem:.0f} m, écart {diff:+.0f} m) "
                    f": altitude retenue pour les calculs de plané {elev:.0f} m. Vérifie le point ou l'altitude.")
            elif abs(diff) > rules.CUSTOM_ELEVATION_WARN_DIFF_M:
                terrain_info.elevation_note = (
                    f"Altitude saisie {ct.elevation_m:.0f} m différente du MNT ({dem:.0f} m, écart {diff:+.0f} m) : "
                    f"vérifie le point (bord de falaise ?) ou l'altitude.")
        if elev is None:
            raise ValueError("Altitude du point de décollage inconnue (MNT indisponible) : indique elevation_m.")
        orientations = list(ct.orientations or (orientations_from_aspect(terrain_info.aspect_deg)
                                                if terrain_info.aspect_deg is not None else []))  # fmt: skip
        site = Site(
            id=f"user:{ct.lat:.5f},{ct.lon:.5f}", name=ct.name or f"Décollage libre ({ct.lat:.4f}, {ct.lon:.4f})",
            kind="takeoff", lat=ct.lat, lon=ct.lon, elevation_m=float(round(elev)), orientations=orientations,
            difficulty=None, flight_types=list(rules.FREE_TAKEOFF_FLIGHT_TYPES), description=None, access=None,
            restrictions=None, status="unknown", source="user", url=None, associated_landing_ids=[], official=False,
            landing_kind=None,
        )  # fmt: skip
        point = (ct.lon, ct.lat, ct.lon, ct.lat)
        bbox = expand_bbox(point, rules.LANDING_SEARCH_RADIUS_KM)
        warnings: list[str] = [terrain_text(terrain_info)]
        if terrain_info.elevation_note:
            warnings.append(terrain_info.elevation_note)
        sites, meta, site_refs, site_warn = await self.data.sites(bbox)
        warnings += site_warn
        refs: list[SourceRef] = list(site_refs)
        demo = any(r.mode == "mock" for r in site_refs)
        cands: list[Site] = [s for s in sites if s.kind in ("landing", "both")]
        spots: dict[str, LandingSpot] = {}
        if True:  # revue 7.18 : toujours chargés, pour NOMMER un terrain à portée exclu par la politique (§12.7)
            sp, sp_refs, sp_warn = await self.data.landing_spots(bbox, (ct.lat, ct.lon), demo)
            refs += sp_refs
            warnings += sp_warn
            for s in sp:
                spots[s.site.id] = s
                cands.append(s.site)
        wing = filters.wing_glide_ratio
        cands = [
            s for s in cands
            if s.elevation_m >= 0 and s.elevation_m < site.elevation_m - rules.TOP_LANDING_MAX_DROP_M
            and haversine_km(site.lat, site.lon, s.lat, s.lon) <= reach_bound_km(site.elevation_m, s.elevation_m, wing)
        ]  # fmt: skip
        cands.sort(key=lambda s: haversine_km(site.lat, site.lon, s.lat, s.lon))
        cands = cands[: rules.LANDING_MAX_CANDIDATES]
        landings = {s.id: s for s in cands}
        reach = max((reach_bound_km(site.elevation_m, s.elevation_m, wing) for s in cands), default=5.0)
        terrain, terrain_real = await self.data.terrain_function(expand_bbox(point, min(reach, 25.0) + 1.0))
        start, end = hours_window(target)
        fcs, frefs = await self.data.forecasts([(site.lat, site.lon, site.elevation_m)], start, end, ref,
                                               with_levels=True)  # fmt: skip
        refs += frefs
        sg = smoothed_ground(terrain, site.lat, site.lon) if terrain_real else smoothed_terrain(site.lat, site.lon)
        timelines: dict[str, PointTimeline] = {site.id: build_timeline(fcs[0], sg, start, end)}
        clusters = cluster_forecast_points(site, cands)
        if clusters:
            pts = [(c.lat, c.lon, c.elevation_m) for c, _ in clusters]
            lfcs, lrefs = await self.data.forecasts(pts, start, end, ref, with_levels=self.data.s.data_mode == "mock")
            refs += [r for r in lrefs if r.name not in {x.name for x in refs}]
            for (_, members), pf in zip(clusters, lfcs, strict=True):
                tl = build_timeline(pf, None, start, end)
                for m in members:
                    timelines[m.id] = tl
        if not cands:
            warnings.append("Aucun atterro connu dans la portée de plané du point.")
        return _Gathered(
            ref=ref, target=target, horizon=horizon, takeoffs=[site], landings=landings, meta=dict(meta),
            timelines=timelines, refs=refs, warnings=warnings, bbox=point, terrain=terrain, terrain_real=terrain_real,
            free_terrain={site.id: terrain_info}, spots=spots, landing_points=[c for c, _ in clusters],
        )  # fmt: skip

    async def _context(
        self, g: _Gathered, duration_max_min: float, with_airspaces: bool = True
    ) -> tuple[DataContext, str]:
        """Balises (MNT des balises sans altitude, vent 15 min aux atterros), espaces aériens (sauf analyse des
        atterros : OpenAIP ménagé), zones sensibles, relief : contexte complet du moteur et data_mode."""
        refs = g.refs
        warnings = g.warnings
        synthetic_weather = any(r.mode == "mock" and "synthétique" in r.name.lower() for r in refs)
        demo_ok = self.data.s.data_mode == "mock" or synthetic_weather
        beacons, ages, brefs = await self.data.beacons(expand_bbox(g.bbox, 15), at=g.ref, allow_demo=demo_ok)
        refs += brefs
        if (not beacons and not demo_ok and g.horizon in rules.NOWCAST_HORIZONS
                and abs((g.ref - datetime.now(UTC)).total_seconds()) >= 3600):  # fmt: skip
            warnings.append("Balises temps réel non applicables à cette heure de référence (à plus d'1 h de "
                            "maintenant) : prévision non corrigée par les balises.")  # fmt: skip
        # altitude MNT des balises sans altitude (Pioupiou) proches des sites : un appel groupé, cache 7 j
        beacon_dem = await self.data.beacon_dem(beacons, [*g.takeoffs, *g.landing_points])
        if g.horizon in rules.NOWCAST_HORIZONS and g.landing_points:
            # vent 10 m au pas de 15 min aux atterros (heure d'arrivée rarement ronde aux horizons courts)
            m_start, m_end = minutely_window(g.ref, HORIZON_MINUTES[g.horizon], duration_max_min)
            pts = [(s.lat, s.lon, s.elevation_m) for s in g.landing_points]
            series, mrefs = await self.data.minutely_winds(pts, m_start, m_end)
            refs += mrefs
            for site, ser in zip(g.landing_points, series, strict=True):
                if ser and site.id in g.timelines:
                    g.timelines[site.id].minutely = ser
        airspaces = []
        asp_warning: str | None = None
        if with_airspaces:
            airspaces, arefs, asp_warning = await self.data.airspaces(expand_bbox(g.bbox, 20))
            refs += arefs
            if asp_warning:
                warnings.append(asp_warning)
        areas, srefs = await self.data.sensitive_areas(expand_bbox(g.bbox, 10))
        refs += srefs
        # revue 7.4 / 7.16 : zones OpenAIP « survol basse altitude restreint » = zones réglementées (hauteur sol)
        areas = [*areas, *low_overflight_areas(airspaces)]
        relief = [
            ReliefPoint(
                p["name"], p["lat"], p["lon"], float(p["elevation_m"]), list(p.get("faces", [])), bool(p.get("valley"))
            )
            for p in fixture_relief()
        ]
        modes = {r.mode for r in refs}
        data_mode = "live" if modes == {"live"} else ("mock" if modes == {"mock"} else "mixed")
        mock_weather = any(r.mode == "mock" and "synthétique" in r.name.lower() for r in refs)
        if not g.terrain_real:
            warnings.append("Profil de terrain non vérifié (MNT de démonstration) : le relief sous les lignes de plané "
                            "n'est pas contrôlé.")  # fmt: skip
        clat = (g.bbox[1] + g.bbox[3]) / 2
        clon = (g.bbox[0] + g.bbox[2]) / 2
        rise, sset = sunrise_sunset((g.target + timedelta(hours=clon / 15)).date(), clat, clon)
        if sset and (g.target > sset or (rise and g.target < rise)):
            warnings.append(
                f"L'heure cible tombe de nuit (lever {iso(rise) if rise else '—'}, coucher {iso(sset)}) : "
                "le vol libre se pratique de jour, choisissez un autre horizon."
            )
        ctx = DataContext(
            reference_time=g.ref,
            target_time=g.target,
            horizon=g.horizon,
            takeoffs=g.takeoffs,
            landings=g.landings,
            timelines=g.timelines,
            beacons=beacons,
            beacon_ages_min=ages,
            airspaces=airspaces,
            sensitive_areas=areas,
            relief=relief,
            site_meta=g.meta,
            terrain=g.terrain,
            terrain_is_real=g.terrain_real,
            mock=mock_weather,
            warnings=warnings,
            beacon_dem_m=beacon_dem,
            free_terrain=g.free_terrain,
            landing_spots=g.spots,
            airspace_unverified=asp_warning,
        )
        return ctx, data_mode

    async def _evaluate(
        self, ctx: DataContext, filters: PlanFilters, g: _Gathered
    ) -> tuple[list[FlightPlan], list[RejectedSite], list[str]]:
        sources = _dedupe_refs(g.refs)
        plans, rejected, warns, _ = evaluate_sites(ctx, filters, sources)
        # tendance 1 h (archive Pioupiou) des balises rattachées aux plans retenus, puis réévaluation : la
        # tendance modifie le vent retenu, les risques et le verdict (CDC §12.2)
        ids = trend_candidates(plans)
        if ids:
            trends = await self.data.beacon_trends(ids)
            if trends:
                ctx.beacons = [
                    b.model_copy(update={"trend": trends[b.id]}) if b.id in trends else b for b in ctx.beacons
                ]
                ctx.station_cache.clear()
                sources = _dedupe_refs([*sources, self.data.trend_source_ref()])
                plans, rejected, warns, _ = evaluate_sites(ctx, filters, sources)
        return plans, rejected, warns

    # ------------------------------------------------------------------------------------------
    # POST /api/landings/analyze
    # ------------------------------------------------------------------------------------------
    async def analyze_landings(self, req: LandingsAnalyzeRequest) -> LandingsAnalyzeResponse:
        ref = parse_reference(req.reference_time)
        target = target_for(ref, req.horizon)
        filters = PlanFilters(
            duration_min_minutes=0, duration_max_minutes=60, difficulty=req.difficulty, thermals="allowed",
            wing_glide_ratio=req.wing_glide_ratio, landing_policy=req.landing_policy,
        )  # fmt: skip
        g = await self._gather_free(req.takeoff, ref, target, req.horizon, filters)
        ctx, _ = await self._context(g, 60, with_airspaces=False)
        site = g.takeoffs[0]
        candidates, cone, warns = analyze_free_takeoff(
            ctx, site, req.difficulty, req.wing_glide_ratio, req.landing_policy
        )
        return LandingsAnalyzeResponse(
            takeoff=site,
            target_time=iso(round_target(target, req.horizon)),
            glide_cone=cone,
            candidates=candidates,
            warnings=list(dict.fromkeys([*warns, *ctx.warnings])),
        )


def trend_candidates(plans: list[FlightPlan], limit: int = 10) -> list[str]:
    """Balises Pioupiou rattachées (déco, atterro, secours) aux plans retenus, sans tendance : représentatives et
    rôles déco/atterro d'abord ; au plus `limit` (un appel /v1/archive chacune)."""
    scored: list[tuple[tuple, str]] = []
    for rank, p in enumerate(plans):
        for r in p.station_readings:
            b = r.beacon
            if b.source != "pioupiou" or b.stale or b.trend is not None or b.wind_speed_kmh is None:
                continue
            role = {"takeoff": 0, "landing": 0, "alternate_landing": 1}[r.site_role]
            scored.append(((not r.representative, role, rank, r.distance_km), b.id))
    out: list[str] = []
    for _, bid in sorted(scored):
        if bid not in out:
            out.append(bid)
    return out[:limit]


def _dedupe_refs(refs: list[SourceRef]) -> list[SourceRef]:
    seen = set()
    out = []
    for r in refs:
        if r.name in seen:
            continue
        seen.add(r.name)
        out.append(r)
    return out
