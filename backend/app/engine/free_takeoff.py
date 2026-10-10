"""Décollage libre (vol rando, point cliqué, `mode = "custom_takeoff"`) : constats du CDC §12.6.

- `site_findings` : avertissement FREE_TAKEOFF (danger élève, caution brevet, info confirmé / expert), pente maximale
  par niveau, profil dans l'axe (bosse / contre-pente), pente non mesurée ;
- `wind_findings` : seuils de vent propres au décollage libre (15 / 20 / 25 km/h…), angle vent / pente sans tolérance
  de secteur, vent arrière interdit dès 3 km/h, pente minimale selon le vent de face (25 % ; 15 % avec ≥ 10 km/h).
"""

from __future__ import annotations

import math

from app.engine import rules
from app.engine.conditions import TakeoffWind, dir_label
from app.engine.findings import Finding
from app.engine.terrain import TakeoffTerrain
from app.geo import angle_diff
from app.models import Site

FT = rules.FREE_TAKEOFF
LEVEL_LIMIT_NOTE = "maximum {i} % brevet de pilote, {a} % confirmé, {e} % expert"


def _per_level(values: dict) -> dict[str, float | None]:
    """Seuils par niveau du décollage libre (élève : None = interdit)."""
    return {"beginner": None, **{k: float(v) for k, v in values.items()}}


def is_free_takeoff(site: Site) -> bool:
    return site.source == "user"


def pct_txt(x: float, threshold: float | None = None) -> str:
    """Pente lisible : une décimale près d'un seuil (« 24,6 % » et non « 25 % (minimum 25 %) », revue 7.18)."""
    if threshold is not None and abs(x - threshold) < 1.0:
        return f"{x:.1f}".replace(".", ",")
    return f"{x:.0f}"


def site_findings(site: Site, terrain: TakeoffTerrain | None) -> list[Finding]:
    out: list[Finding] = [
        Finding("FREE_TAKEOFF", "Décollage libre (hors site officiel)", FT["warning"],
                level_risk=dict(rules.RISK_LEVELS["FREE_TAKEOFF"]))
    ]  # fmt: skip
    if terrain is not None and terrain.elevation_note:
        out.append(Finding("FREE_TAKEOFF", "Altitude saisie différente du MNT", terrain.elevation_note, caution=True))
    if terrain is None or terrain.slope_pct is None:
        out.append(Finding(
            "FREE_TAKEOFF", "Pente non mesurée",
            f"Pente non mesurée (MNT indisponible) : vérifie sur place qu'elle fait au moins "
            f"{FT['slope_pct']['min_without_headwind']} % ({FT['slope_pct']['min']} % avec au moins "
            f"{FT['slope_pct']['headwind_for_gentle_kmh']} km/h de vent de face).", caution=True,
        ))  # fmt: skip
        return out
    mx = FT["slope_pct"]["max"]
    note = LEVEL_LIMIT_NOTE.format(i=mx["intermediate"], a=mx["advanced"], e=mx["expert"])
    out.append(Finding(
        "FREE_TAKEOFF", "Pente trop raide",
        f"Pente MNT de {pct_txt(terrain.slope_pct)} % sur les 150 m sous le point : pente trop raide pour gonfler et "
        f"courir en sécurité ({note}).",
        value=terrain.slope_pct, limits=_per_level(mx), band=False,
    ))  # fmt: skip
    if terrain.profile_ok is False:
        out.append(Finding(
            "FREE_TAKEOFF", "Bosse ou contre-pente dans l'axe",
            f"Bosse ou contre-pente dans l'axe de décollage : {terrain.profile_detail}.", absolute_nogo=True,
        ))  # fmt: skip
    return out


def wind_findings(tw: TakeoffWind, terrain: TakeoffTerrain | None, site: Site) -> list[Finding]:
    """Vent au point (interpolé à l'altitude du déco) contre les seuils du décollage libre."""
    out: list[Finding] = []
    v, g, d = tw.speed_kmh, tw.gust_kmh, tw.direction_deg
    axis = terrain.axis_deg if terrain is not None and terrain.axis_deg is not None else None
    if axis is None and terrain is not None and terrain.aspect_deg is not None:
        axis = terrain.aspect_deg
    out.append(Finding(
        "TAKEOFF_WIND", "Vent moyen au décollage libre",
        f"Vent au point {dir_label(d)} {v:.0f} km/h (seuils du décollage libre : 15 / 20 / 25 km/h).",
        criterion="takeoff_wind", value=v, limits=_per_level(FT["wind_max_kmh"]),
    ))  # fmt: skip
    out.append(Finding(
        "TAKEOFF_GUSTS", "Rafales au décollage libre", f"Rafales {g:.0f} km/h au point (seuils 20 / 25 / 30 km/h).",
        criterion="takeoff_wind", value=g, limits=_per_level(FT["gust_max_kmh"]),
    ))  # fmt: skip
    out.append(Finding(
        "TAKEOFF_GUSTS", "Écart rafales / vent moyen au décollage libre",
        f"Écart rafale − moyenne de {max(0.0, g - v):.0f} km/h (seuils 8 / 10 / 12 km/h).",
        criterion="takeoff_wind", value=max(0.0, g - v), limits=_per_level(FT["gust_spread_max_kmh"]),
    ))  # fmt: skip
    if axis is None:
        return out
    ang = angle_diff(d, axis)
    head = v * math.cos(math.radians(ang))
    if ang > rules.TAILWIND_ANGLE_DEG and v >= FT["tailwind_max_kmh"]:
        out.append(Finding(
            "TAILWIND", "Vent arrière au décollage libre",
            f"Vent arrière de {v:.0f} km/h ({dir_label(d)}) sur la pente : interdit en décollage libre dès "
            f"{FT['tailwind_max_kmh']} km/h.", absolute_nogo=True,
        ))  # fmt: skip
    elif v >= FT["calm_kmh"]:
        out.append(Finding(
            "CROSSWIND", "Vent de travers sur la pente",
            f"Vent à {ang:.0f}° de l'orientation de la pente ({dir_label(axis)}) (maximum 20° / 30° / 45° selon le "
            f"niveau, sans tolérance de secteur).",
            criterion="takeoff_wind", value=ang, limits=_per_level(FT["wind_slope_angle_max_deg"]),
        ))  # fmt: skip
    if terrain is not None and terrain.slope_pct is not None:
        sp = FT["slope_pct"]
        gentle = head >= sp["headwind_for_gentle_kmh"]
        need = sp["min"] if gentle else sp["min_without_headwind"]
        if terrain.slope_pct < need:
            if gentle:
                why = f"minimum {need} % même avec {head:.0f} km/h de vent de face"
            else:
                why = (f"minimum {need} %, ou {sp['min']} % avec au moins {sp['headwind_for_gentle_kmh']} km/h de vent "
                       f"de face ; vent de face prévu : {max(0.0, head):.0f} km/h")  # fmt: skip
            out.append(Finding(
                "FREE_TAKEOFF", "Pente trop faible pour décoller",
                f"Pente MNT de {pct_txt(terrain.slope_pct, need)} % : pente trop faible pour décoller ({why}).",
                absolute_nogo=True,
            ))  # fmt: skip
    return out


def wind_limits(level: str) -> tuple[float, float, float]:
    """(vent moyen max, rafale max, vent arrière max) du décollage libre au niveau donné (créneau, §12.6)."""
    lv = level if level in FT["wind_max_kmh"] else "intermediate"
    return float(FT["wind_max_kmh"][lv]), float(FT["gust_max_kmh"][lv]), float(FT["tailwind_max_kmh"])


def mandatory_checks() -> list[str]:
    return list(FT["mandatory_checks"])
