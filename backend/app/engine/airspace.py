"""Espaces aériens (3D) et zones sensibles (faune, réserves, cœurs de parcs) vis-à-vis d'une route."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

import numpy as np
import shapely
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry

from app.engine import rules
from app.engine.context import Airspace, DataContext, SensitiveArea
from app.engine.findings import Finding
from app.geo import LocalProjection
from app.models import AirspaceWarning, Site

_MONTHS_FR = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


class Projector:
    """Projection locale (km) partagée pour une évaluation, avec cache des géométries projetées."""

    def __init__(self, lat0: float, lon0: float) -> None:
        self.proj = LocalProjection(lat0, lon0)
        self._cache: dict[int, BaseGeometry] = {}

    def geom(self, g: BaseGeometry) -> BaseGeometry:
        key = id(g)
        if key not in self._cache:
            kx, ky, lon0, lat0 = self.proj.kx, self.proj.ky, self.proj.lon0, self.proj.lat0
            self._cache[key] = shapely.transform(
                g, lambda c: np.column_stack(((c[:, 0] - lon0) * kx, (c[:, 1] - lat0) * ky))
            )
        return self._cache[key]

    def _xy(self, x, y, z=None):
        xa = np.asarray(x, dtype=float)
        ya = np.asarray(y, dtype=float)
        return (xa - self.proj.lon0) * self.proj.kx, (ya - self.proj.lat0) * self.proj.ky

    def line(self, coords: list[tuple[float, float, float]]) -> LineString:
        pts = [self.proj.to_xy(lat, lon) for lon, lat, _ in coords]
        if len(pts) == 1:
            pts = pts * 2
        return LineString(pts)

    def point(self, lat: float, lon: float) -> Point:
        return Point(*self.proj.to_xy(lat, lon))


def _vertical_overlap(lo: float, hi: float, floor: float, ceiling: float) -> bool:
    return lo < ceiling and hi > floor


def is_forbidden(a: Airspace) -> bool:
    cls = a.airspace_class.upper()
    typ = a.type.upper()
    if typ in rules.AIRSPACE_INFO_TYPES:
        return False
    return cls in rules.AIRSPACE_FORBIDDEN_CLASSES or typ in rules.AIRSPACE_FORBIDDEN_TYPES or cls == "P"


def is_activable(a: Airspace) -> bool:
    return a.type.upper() in rules.AIRSPACE_ACTIVATION_TYPES or a.airspace_class.upper() in ("R", "Q", "D_ZONE")


@dataclass(slots=True)
class AirspaceResult:
    warnings: list[AirspaceWarning]
    findings: list[Finding]
    altitude_cap_m: float | None  # plafond imposé par un espace au-dessus de la route
    blocking: bool  # la route traverse un espace interdit (à éviter par le routeur)


def route_conflicts(
    ctx: DataContext, proj: Projector, coords: list[tuple[float, float, float]], min_alt: float, max_alt: float
) -> bool:
    """Vrai si la route traverse un espace interdit (classe A-D, P) à une altitude atteinte."""
    line = proj.line(coords)
    for a in ctx.airspaces:
        if not is_forbidden(a):
            continue
        if not _vertical_overlap(min_alt, max_alt, a.floor_m, a.ceiling_m):
            continue
        if proj.geom(a.geometry).intersects(line):
            return True
    return False


def evaluate_airspaces(
    ctx: DataContext,
    proj: Projector,
    coords: list[tuple[float, float, float]],
    min_alt: float,
    max_alt: float,
) -> AirspaceResult:
    line = proj.line(coords)
    warnings: list[AirspaceWarning] = []
    findings: list[Finding] = []
    cap: float | None = None
    blocking = False
    for a in ctx.airspaces:
        typ = a.type.upper()
        g = proj.geom(a.geometry)
        dist = g.distance(line)
        if dist > rules.AIRSPACE_REPORT_RADIUS_KM:
            continue
        intersects = g.intersects(line)
        vert = _vertical_overlap(min_alt, max_alt, a.floor_m, a.ceiling_m)
        floor_txt = f"{a.floor_m:.0f} m{' sol' if a.floor_agl else ''}"
        warnings.append(
            AirspaceWarning(
                name=a.name,
                airspace_class=a.airspace_class,
                type=a.type,
                floor_m=round(a.floor_m),
                ceiling_m=round(a.ceiling_m),
                min_distance_km=round(dist, 2),
                intersects_route=bool(intersects and vert),
            )
        )
        if typ in rules.AIRSPACE_INFO_TYPES:
            continue
        label = f"{a.name} (classe {a.airspace_class}, {floor_txt} → {a.ceiling_m:.0f} m)"
        if is_forbidden(a):
            if intersects and vert:
                blocking = True
                findings.append(
                    Finding(
                        code="AIRSPACE",
                        title="Route dans un espace aérien interdit",
                        detail=f"La route traverse {label} : interdit sans clairance.",
                        criterion=None,
                        absolute_nogo=True,
                    )
                )
            elif intersects and a.floor_m > min_alt:
                # espace au-dessus de la route : plafonner l'altitude
                c = a.floor_m - rules.CEILING_MARGIN_BELOW_AIRSPACE_M
                cap = c if cap is None else min(cap, c)
            elif dist < rules.AIRSPACE_CAUTION_LATERAL_KM and vert:
                findings.append(
                    Finding(
                        code="AIRSPACE",
                        title="Espace aérien proche",
                        detail=f"{label} à {dist * 1000:.0f} m de la route : marge latérale < 1 km.",
                        caution=True,
                    )
                )
        elif is_activable(a):
            if intersects and vert:
                if a.activity_known and a.active:
                    blocking = True
                    findings.append(
                        Finding(
                            code="AIRSPACE_ACTIVATION",
                            title="Zone réglementée active sur la route",
                            detail=f"{label} est active : traversée interdite.",
                            absolute_nogo=True,
                        )
                    )
                else:
                    findings.append(
                        Finding(
                            code="AIRSPACE_ACTIVATION",
                            title="Zone activable traversée : statut à vérifier",
                            detail=f"La route traverse {label}, dont l'activité n'est pas connue : "
                            "vérifier NOTAM / SUP AIP / AZBA avant le vol.",
                            caution=True,
                        )
                    )
            elif dist < rules.AIRSPACE_CAUTION_LATERAL_KM:
                findings.append(
                    Finding(
                        code="AIRSPACE_ACTIVATION",
                        title="Zone activable à proximité",
                        detail=f"{label} à {dist * 1000:.0f} m de la route : vérifier son activation.",
                        info=True,
                    )
                )
        elif intersects and vert and a.airspace_class.upper() == "E":
            findings.append(
                Finding(
                    code="AIRSPACE",
                    title="Espace de classe E traversé",
                    detail=f"{label} : autorisé en VMC (300 m sous les nuages, 1,5 km horizontalement).",
                    info=True,
                )
            )
    return AirspaceResult(warnings, findings, cap, blocking)


# ---------------------------------------------------------------------------------------------
# Zones sensibles
# ---------------------------------------------------------------------------------------------
def months_label(months: list[int]) -> str:
    if not months or len(months) == 12:
        return "toute l'année"
    return ", ".join(_MONTHS_FR[m - 1] for m in sorted(months))


def park_text(area: SensitiveArea) -> str:
    return (
        f"{area.name} : décollage et atterrissage interdits ; survol à moins de 1000 m/sol à éviter "
        "(réglementation du parc). Vérifiez la fiche du site et la réglementation du parc avant de voler."
    )


def species_text(area: SensitiveArea, h: float) -> str:
    who = area.species or area.name
    rec = area.recommendation.strip()
    if rec and not rec.endswith("."):
        rec += "."
    return (
        f"Zone de quiétude {who} active ({months_label(area.period_months)}) : {rec} "
        f"Contournez ou survolez à plus de {h:.0f} m/sol."
    )


def site_in_area(proj: Projector, area: SensitiveArea, site: Site) -> bool:
    return proj.geom(area.geometry).contains(proj.point(site.lat, site.lon))


def _site_authorized(site: Site) -> bool:
    txt = (site.restrictions or "").lower()
    return "autoris" in txt and ("parc" in txt or "réserve" in txt or "reserve" in txt)


def route_height_violation(
    ctx: DataContext,
    proj: Projector,
    area: SensitiveArea,
    coords: list[tuple[float, float, float]],
    min_height: float,
    step_km: float = 0.25,
) -> bool:
    """La route passe-t-elle dans la zone à moins de `min_height` m au-dessus du terrain ?"""
    g = proj.geom(area.geometry)
    pts = [(lat, lon, alt) for lon, lat, alt in coords]
    for (la1, lo1, a1), (la2, lo2, a2) in pairwise(pts):
        p1, p2 = proj.point(la1, lo1), proj.point(la2, lo2)
        seg_len = p1.distance(p2)
        n = max(1, int(seg_len / step_km))
        for i in range(n + 1):
            f = i / n
            x = p1.x + f * (p2.x - p1.x)
            y = p1.y + f * (p2.y - p1.y)
            if not g.contains(Point(x, y)):
                continue
            lat, lon = proj.proj.to_latlon(x, y)
            alt = a1 + f * (a2 - a1)
            terrain = ctx.terrain_at(lat, lon)
            if terrain is None or alt - terrain < min_height:
                return True
    return False


def evaluate_sensitive_sites(ctx: DataContext, proj: Projector, takeoff: Site, landing: Site) -> list[Finding]:
    """Déco / atterro dans une zone sensible (indépendant de la route)."""
    out: list[Finding] = []
    month = ctx.target_time.month
    for area in ctx.sensitive_areas:
        for site, what in ((takeoff, "Décollage"), (landing, "Atterrissage")):
            if not site_in_area(proj, area, site):
                continue
            if area.kind == "national_park_core":
                authorized = _site_authorized(site)
                out.append(
                    Finding(
                        code="NATIONAL_PARK",
                        title="Décollage/atterrissage interdits en cœur de parc national",
                        detail=park_text(area),
                        absolute_nogo=not authorized,
                        caution=authorized,
                    )
                )
            elif area.kind == "regulatory":
                if not area.active_in_month(month):
                    continue
                authorized = _site_authorized(site)
                out.append(
                    Finding(
                        code="SENSITIVE_AREA",
                        title=f"{what} dans une zone réglementée",
                        detail=f"{area.name} : {area.recommendation or 'zone réglementée (arrêté)'} "
                        f"— {what.lower()} dans la zone à proscrire.",
                        absolute_nogo=not authorized,
                        caution=authorized,
                    )
                )
            elif area.active_in_month(month):
                h = area.min_height_agl_m or rules.SENSITIVE_AREA_DEFAULT_HEIGHT_AGL_M
                out.append(
                    Finding(
                        code="SENSITIVE_AREA",
                        title=f"{what} dans une zone de quiétude active",
                        detail=species_text(area, h),
                        caution=True,
                    )
                )
    return out


def route_sensitive_conflict(
    ctx: DataContext, proj: Projector, coords: list[tuple[float, float, float]]
) -> list[tuple[SensitiveArea, float]]:
    """Zones actives traversées sous la hauteur requise (pour que le routeur les évite)."""
    month = ctx.target_time.month
    out = []
    line = proj.line(coords)
    for area in ctx.sensitive_areas:
        if area.kind != "national_park_core" and not area.active_in_month(month):
            continue
        if not proj.geom(area.geometry).intersects(line):
            continue
        h = area.min_height_agl_m or (
            rules.PARK_MIN_HEIGHT_AGL_M
            if area.kind == "national_park_core"
            else rules.SENSITIVE_AREA_DEFAULT_HEIGHT_AGL_M
        )
        if route_height_violation(ctx, proj, area, coords, h):
            out.append((area, h))
    return out


def evaluate_sensitive_route(
    ctx: DataContext, proj: Projector, coords: list[tuple[float, float, float]], takeoff: Site, landing: Site
) -> list[Finding]:
    out: list[Finding] = []
    month = ctx.target_time.month
    line = proj.line(coords)
    for area in ctx.sensitive_areas:
        if not proj.geom(area.geometry).intersects(line):
            continue
        if site_in_area(proj, area, takeoff) or site_in_area(proj, area, landing):
            continue  # déjà traité par evaluate_sensitive_sites
        if area.kind == "national_park_core":
            h = area.min_height_agl_m or rules.PARK_MIN_HEIGHT_AGL_M
            below = route_height_violation(ctx, proj, area, coords, h)
            out.append(
                Finding(
                    code="NATIONAL_PARK",
                    title="Survol d'un cœur de parc national",
                    detail=park_text(area)
                    + (" La route passe sous 1000 m/sol : segment interdit." if below else ""),
                    absolute_nogo=below,
                    caution=not below,
                )
            )
        elif area.active_in_month(month):
            h = area.min_height_agl_m or rules.SENSITIVE_AREA_DEFAULT_HEIGHT_AGL_M
            if area.kind == "regulatory":
                below = route_height_violation(ctx, proj, area, coords, h)
                if below:
                    out.append(
                        Finding(
                            code="SENSITIVE_AREA",
                            title="Survol bas d'une zone réglementée",
                            detail=f"{area.name} : survol à moins de {h:.0f} m/sol à proscrire. "
                            f"{area.recommendation}".strip(),
                            caution=True,
                        )
                    )
            elif route_height_violation(ctx, proj, area, coords, h):
                out.append(
                    Finding(
                        code="SENSITIVE_AREA",
                        title="Zone de quiétude faune sur la route",
                        detail=species_text(area, h),
                        caution=True,
                    )
                )
    return out
