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


def _terrain_known(ctx: DataContext) -> bool:
    """MNT utilisable pour convertir une limite sol : réel, ou celui de la démo / du scénario (données exactes)."""
    return ctx.terrain is not None and (ctx.terrain_is_real or ctx.mock or ctx.exact_inputs)


def limits_at(ctx: DataContext, a: Airspace, lat: float, lon: float) -> tuple[float, float]:
    """(plancher, plafond) AMSL de l'espace au point (revue B7) : une limite sol vaut hauteur publiée + terrain au
    point ; terrain inconnu → prudence : plancher au sol, plafond infini (chevauchement supposé)."""
    ground = ctx.terrain_at(lat, lon) if _terrain_known(ctx) and (a.floor_agl or a.ceiling_agl) else None
    floor, ceil = a.floor_m, a.ceiling_m
    if a.floor_agl and a.floor_height_m is not None:
        floor = a.floor_height_m + ground if ground is not None else 0.0
    if a.ceiling_agl and a.ceiling_height_m is not None:
        ceil = a.ceiling_height_m + ground if ground is not None else 1e9
    return floor, ceil


def _sample_route(proj: Projector, coords: list[tuple[float, float, float]], step_km: float = 0.25):
    """Points de la route tous les `step_km` : (x, y, lat, lon, altitude interpolée)."""
    for (lo1, la1, a1), (lo2, la2, a2) in pairwise(coords):
        p1, p2 = proj.point(la1, lo1), proj.point(la2, lo2)
        n = max(1, int(p1.distance(p2) / step_km))
        for i in range(n + 1):
            f = i / n
            x, y = p1.x + f * (p2.x - p1.x), p1.y + f * (p2.y - p1.y)
            lat, lon = proj.proj.to_latlon(x, y)
            yield x, y, lat, lon, a1 + f * (a2 - a1)


def agl_overlap(ctx: DataContext, proj: Projector, a: Airspace, coords: list[tuple[float, float, float]]) -> bool:
    """Espace à limite sol : la route (altitudes interpolées entre ses points) passe-t-elle dans [plancher(p),
    plafond(p)] en un point de la zone ? (recouvrement vertical calculé point par point, revue B7 / 7.16)"""
    g = proj.geom(a.geometry)
    for x, y, lat, lon, alt in _sample_route(proj, coords):
        if not g.contains(Point(x, y)):
            continue
        floor, ceil = limits_at(ctx, a, lat, lon)
        if floor <= alt < ceil:
            return True
    return False


def vertical_overlap(
    ctx: DataContext, proj: Projector, a: Airspace, coords: list[tuple[float, float, float]], lo: float, hi: float
) -> bool:
    if a.floor_agl or a.ceiling_agl:
        return agl_overlap(ctx, proj, a, coords)
    return _vertical_overlap(lo, hi, a.floor_m, a.ceiling_m)


def limits_label(ctx: DataContext, a: Airspace) -> tuple[str, str]:
    """Textes du plancher et du plafond (« 305 m/sol » pour une limite sol)."""
    f = f"{a.floor_height_m:.0f} m/sol" if a.floor_agl and a.floor_height_m is not None else f"{a.floor_m:.0f} m"
    agl_c = a.ceiling_agl and a.ceiling_height_m is not None
    c = f"{a.ceiling_height_m:.0f} m/sol" if agl_c else f"{a.ceiling_m:.0f} m"
    return f, c


def is_forbidden(a: Airspace) -> bool:
    cls = a.airspace_class.upper()
    typ = a.type.upper()
    if typ in rules.AIRSPACE_INFO_TYPES:
        return False
    return cls in rules.AIRSPACE_FORBIDDEN_CLASSES or typ in rules.AIRSPACE_FORBIDDEN_TYPES or cls == "P"


def is_activable(a: Airspace) -> bool:
    return a.type.upper() in rules.AIRSPACE_ACTIVATION_TYPES or a.airspace_class.upper() in ("R", "Q", "D_ZONE")


def _cap_below(
    ctx: DataContext, proj: Projector, a: Airspace, coords: list[tuple[float, float, float]]
) -> float | None:
    """Plafond possible sous un espace interdit traversé : plancher (au point le plus bas de la zone sur la route) −
    100 m, s'il reste au-dessus du déco, de l'atterro et du relief de la route dans la zone (+ 100 m) ; None sinon
    (la route est vraiment dans l'espace : rejet)."""
    g = proj.geom(a.geometry)
    margin = rules.CEILING_MARGIN_BELOW_AIRSPACE_M
    floors: list[float] = []
    ground_max = -1e9
    known = _terrain_known(ctx)
    for x, y, lat, lon, _ in _sample_route(proj, coords):
        if not g.contains(Point(x, y)):
            continue
        floors.append(limits_at(ctx, a, lat, lon)[0])
        if known:
            t = ctx.terrain_at(lat, lon)
            if t is not None:
                ground_max = max(ground_max, t)
    floor = min(floors) if floors else a.floor_m
    cap = floor - margin
    ends = max(coords[0][2], coords[-1][2]) if coords else 0.0
    if floor <= 0 or cap < ends or cap < ground_max + margin:
        return None
    return cap


def _rep_latlon(a: Airspace) -> tuple[float, float]:
    rp = a.geometry.representative_point()
    return rp.y, rp.x


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
        if not proj.geom(a.geometry).intersects(line):
            continue
        if vertical_overlap(ctx, proj, a, coords, min_alt, max_alt):
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
        vert = intersects and vertical_overlap(ctx, proj, a, coords, min_alt, max_alt)
        if not intersects:
            vert = _vertical_overlap(min_alt, max_alt, *limits_at(ctx, a, *_rep_latlon(a)))
        floor_txt, ceil_txt = limits_label(ctx, a)
        disp_floor, disp_ceil = limits_at(ctx, a, *_rep_latlon(a))
        warnings.append(
            AirspaceWarning(
                name=a.name,
                airspace_class=a.airspace_class,
                type=a.type,
                floor_m=round(disp_floor if disp_floor < 1e8 else a.floor_m),
                ceiling_m=round(disp_ceil if disp_ceil < 1e8 else a.ceiling_m),
                min_distance_km=round(dist, 2),
                intersects_route=bool(intersects and vert),
            )
        )
        if typ in rules.AIRSPACE_INFO_TYPES or typ == "LOW_OVERFLIGHT":  # LOW_OVERFLIGHT : zone réglementée (7.4)
            continue
        label = f"{a.name} (classe {a.airspace_class}, {floor_txt} → {ceil_txt})"
        if is_forbidden(a):
            c = _cap_below(ctx, proj, a, coords) if intersects and vert else None
            if c is not None:
                # revue (TMA) : espace interdit AU-DESSUS du déco, de l'atterro et du relief de la route → on plafonne
                # l'altitude (plancher − 100 m, ALTITUDE_LIMIT non bloquant) au lieu de rejeter le vol
                cap = c if cap is None else min(cap, c)
            elif intersects and vert:
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
            elif intersects and 0.0 <= min_alt - disp_ceil < rules.AIRSPACE_CAUTION_VERTICAL_M:
                # CDC §3 #12 (revue, m) : route au-dessus de l'espace avec moins de 100 m de marge verticale
                findings.append(
                    Finding(
                        code="AIRSPACE",
                        title="Espace aérien juste sous la route",
                        detail=f"La route passe à {min_alt - disp_ceil:.0f} m au-dessus du plafond de {label} : marge "
                        f"verticale < {rules.AIRSPACE_CAUTION_VERTICAL_M:.0f} m.",
                        caution=True,
                    )
                )
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
            if area.flight_prohibited and area.kind != "national_park_core" and area.active_in_month(month):
                authorized = _site_authorized(site)
                out.append(
                    Finding(
                        code="SENSITIVE_AREA",
                        title=f"{what} dans une zone où le vol libre est interdit",
                        detail=f"{area.name} : {prohibited_text(area)} — {what.lower()} dans la zone interdit.",
                        absolute_nogo=not authorized,
                        caution=authorized,
                    )
                )
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
        if area.flight_prohibited:  # interdit à toute hauteur (revue 7.4)
            out.append((area, float("inf")))
            continue
        h = area.min_height_agl_m or (
            rules.PARK_MIN_HEIGHT_AGL_M
            if area.kind == "national_park_core"
            else rules.SENSITIVE_AREA_DEFAULT_HEIGHT_AGL_M
        )
        if route_height_violation(ctx, proj, area, coords, h):
            out.append((area, h))
    return out


def prohibited_text(area: SensitiveArea) -> str:
    return "parapente et autres sports aériens interdits dans la zone, à toute hauteur"


def prohibited_areas(ctx: DataContext) -> list[SensitiveArea]:
    """Zones où le vol libre est interdit à toute hauteur, actives au mois de l'heure cible (revue 7.4)."""
    month = ctx.target_time.month
    return [a for a in ctx.sensitive_areas if a.flight_prohibited and a.active_in_month(month)]


def low_overflight_areas(airspaces: list[Airspace]) -> list[SensitiveArea]:
    """Revue 7.4 / 7.16 : zones OpenAIP « survol basse altitude restreint » (LOW_OVERFLIGHT : parcs, réserves, ZSM)
    traitées comme une zone réglementée Biodiv'Sports ; leur plafond est lu comme une hauteur sol."""
    out: list[SensitiveArea] = []
    for i, a in enumerate(airspaces):
        if a.type.upper() != "LOW_OVERFLIGHT":
            continue
        h = a.ceiling_height_m if a.ceiling_height_m is not None else a.ceiling_m
        out.append(
            SensitiveArea(
                id=f"openaip:low-overflight:{i}", name=a.name, kind="regulatory", species=None, period_months=[],
                recommendation=f"Survol à moins de {h:.0f} m/sol restreint (espace aérien {a.name}).",
                min_height_agl_m=float(h), geometry=a.geometry, source="openaip",
            )
        )  # fmt: skip
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
        if area.flight_prohibited and area.kind != "national_park_core" and area.active_in_month(month):
            out.append(
                Finding(
                    code="SENSITIVE_AREA",
                    title="Route dans une zone où le vol libre est interdit",
                    detail=f"La route traverse {area.name} : {prohibited_text(area)}. Contourne la zone.",
                    absolute_nogo=True,
                )
            )
            continue
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
                if below:  # revue 7.4 : survol d'une zone réglementée sous sa hauteur = no-go (CDC §3 #12)
                    out.append(
                        Finding(
                            code="SENSITIVE_AREA",
                            title="Survol bas d'une zone réglementée",
                            detail=f"{area.name} : la route passe à moins de {h:.0f} m/sol, survol interdit sous cette "
                            f"hauteur. {area.recommendation}".strip(),
                            absolute_nogo=True,
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
