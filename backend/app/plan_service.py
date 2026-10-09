"""Orchestration d'une requête POST /api/plans : collecte des données, moteur, cache des plans."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.cache import TTLCache
from app.engine import rules
from app.engine.context import DataContext, ReliefPoint, SiteMeta
from app.engine.planner import evaluate_sites
from app.geo import expand_bbox, haversine_km
from app.meteo.snapshot import iso
from app.meteo.solar import sunrise_sunset
from app.models import (
    HORIZON_MINUTES,
    BBoxZone,
    CircleZone,
    FlightPlan,
    PlanRequest,
    PlanResponse,
    SourceRef,
    zone_bbox,
)
from app.providers.fixture_data import fixture_relief
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
    return base + timedelta(hours=1) if t.minute >= 30 else base


def round_target(t: datetime, horizon: str) -> datetime:
    """Heure cible arrondie au pas de prévision : l'heure (modèles horaires), ou 15 min pour les horizons ≤ 1 h,
    où le vent retenu vient surtout des balises (nowcasting, pas de 15 min, CDC §12.5)."""
    if horizon in rules.NOWCAST_WINDOW_START_MIN:
        q = round((t.minute * 60 + t.second) / 900.0)
        return t.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=15 * q)
    return round_hour(t)


def in_zone(zone: BBoxZone | CircleZone, lat: float, lon: float) -> bool:
    if isinstance(zone, BBoxZone):
        return zone.min_lat <= lat <= zone.max_lat and zone.min_lon <= lon <= zone.max_lon
    return haversine_km(zone.center.lat, zone.center.lon, lat, lon) <= zone.radius_km


def zone_center(zone: BBoxZone | CircleZone) -> tuple[float, float]:
    if isinstance(zone, BBoxZone):
        return (zone.min_lat + zone.max_lat) / 2, (zone.min_lon + zone.max_lon) / 2
    return zone.center.lat, zone.center.lon


class PlanService:
    def __init__(self, data: DataService, plans_ttl_s: int) -> None:
        self.data = data
        self.plans = TTLCache(plans_ttl_s, 2000)

    def get(self, plan_id: str) -> FlightPlan | None:
        return self.plans.get(plan_id)

    async def create(self, req: PlanRequest) -> PlanResponse:
        ref = parse_reference(req.reference_time)
        target = ref + timedelta(minutes=HORIZON_MINUTES[req.horizon])
        bbox = zone_bbox(req.zone)
        big_bbox = expand_bbox(bbox, 15)
        warnings: list[str] = []
        sites, meta, site_refs, site_warn = await self.data.sites(big_bbox)
        warnings += site_warn
        clat, clon = zone_center(req.zone)
        takeoffs = [s for s in sites if s.kind in ("takeoff", "both") and in_zone(req.zone, s.lat, s.lon)]
        takeoffs.sort(key=lambda s: haversine_km(clat, clon, s.lat, s.lon))
        if len(takeoffs) > MAX_TAKEOFFS:
            warnings.append(f"{len(takeoffs)} décollages dans la zone : seuls les {MAX_TAKEOFFS} plus proches du centre sont évalués.")
            takeoffs = takeoffs[:MAX_TAKEOFFS]
        landings = {s.id: s for s in sites if s.kind in ("landing", "both")}
        needed_landings: dict[str, object] = {}
        for t in takeoffs:
            for lid in t.associated_landing_ids[:3]:
                if lid in landings:
                    needed_landings[lid] = landings[lid]
        terrain, terrain_real = await self.data.terrain_function(big_bbox)
        start, end = hours_window(target)
        to_pts = [(s.lat, s.lon, s.elevation_m) for s in takeoffs]
        ld_list = list(needed_landings.values())
        ld_pts = [(s.lat, s.lon, s.elevation_m) for s in ld_list]
        refs: list[SourceRef] = list(site_refs)
        timelines = {}
        if to_pts:
            fcs, frefs = await self.data.forecasts(to_pts, start, end, ref, with_levels=True)
            refs += frefs
            for s, pf in zip(takeoffs, fcs, strict=True):
                sg = smoothed_ground(terrain, s.lat, s.lon) if terrain_real else smoothed_terrain(s.lat, s.lon)
                timelines[s.id] = build_timeline(pf, sg, start, end)
        if ld_pts:
            fcs, frefs = await self.data.forecasts(ld_pts, start, end, ref, with_levels=self.data.s.data_mode == "mock")
            refs += [r for r in frefs if r.name not in {x.name for x in refs}]
            for s, pf in zip(ld_list, fcs, strict=True):
                timelines[s.id] = build_timeline(pf, None, start, end)
        beacons, ages, brefs = await self.data.beacons(expand_bbox(bbox, 15), at=ref)
        refs += brefs
        beacon_dem = await self.data.beacon_dem(beacons)  # altitude MNT des balises sans altitude (Pioupiou)
        airspaces, arefs = await self.data.airspaces(expand_bbox(bbox, 20), terrain if terrain_real else None)
        refs += arefs
        areas, srefs = await self.data.sensitive_areas(expand_bbox(bbox, 10))
        refs += srefs
        relief = [
            ReliefPoint(p["name"], p["lat"], p["lon"], float(p["elevation_m"]), list(p.get("faces", [])), bool(p.get("valley")))
            for p in fixture_relief()
        ]
        modes = {r.mode for r in refs}
        data_mode = "live" if modes == {"live"} else ("mock" if modes == {"mock"} else "mixed")
        mock_weather = any(r.mode == "mock" and "synthétique" in r.name.lower() for r in refs)
        if not terrain_real:
            warnings.append("Profil de terrain non vérifié (MNT de démonstration) : le relief sous les lignes de plané n'est pas contrôlé.")
        rise, sset = sunrise_sunset((target + timedelta(hours=clon / 15)).date(), clat, clon)
        if sset and (target > sset or (rise and target < rise)):
            warnings.append(
                f"L'heure cible tombe de nuit (lever {iso(rise) if rise else '—'}, coucher {iso(sset)}) : "
                "le vol libre se pratique de jour, choisissez un autre horizon."
            )
        if not takeoffs:
            warnings.append("Aucun décollage connu dans la zone sélectionnée.")
        meta_all: dict[str, SiteMeta] = dict(meta)
        ctx = DataContext(
            reference_time=ref,
            target_time=target,
            horizon=req.horizon,
            takeoffs=takeoffs,
            landings=landings,
            timelines=timelines,
            beacons=beacons,
            beacon_ages_min=ages,
            airspaces=airspaces,
            sensitive_areas=areas,
            relief=relief,
            site_meta=meta_all,
            terrain=terrain,
            terrain_is_real=terrain_real,
            mock=mock_weather,
            warnings=warnings,
            beacon_dem_m=beacon_dem,
        )
        sources = _dedupe_refs(refs)
        plans, rejected, warns, _ = evaluate_sites(ctx, req.filters, sources)
        # tendance 1 h (archive Pioupiou) des balises rattachées aux plans retenus, puis réévaluation : la
        # tendance modifie le vent retenu, les risques et le verdict (CDC §12.2)
        ids = trend_candidates(plans)
        if ids:
            trends = await self.data.beacon_trends(ids)
            if trends:
                ctx.beacons = [b.model_copy(update={"trend": trends[b.id]}) if b.id in trends else b for b in ctx.beacons]
                ctx.station_cache.clear()
                plans, rejected, warns, _ = evaluate_sites(ctx, req.filters, sources)
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
            rejected=rejected,
            warnings=list(dict.fromkeys(warns)),
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
