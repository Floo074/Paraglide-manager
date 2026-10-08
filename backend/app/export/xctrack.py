"""Export de tâche XCTrack (format .xctsk, version 1).

Structure : {"taskType": "CLASSIC", "version": 1, "earthModel": "WGS84", "turnpoints": [...],
"sss": {...}, "goal": {...}}. Chaque balise : {"type"?: "TAKEOFF"|"SSS"|"ESS", "radius": m,
"waypoint": {"name", "lat", "lon", "altSmoothed", "description"}}. XCTrack n'a pas de type « GOAL » :
le but est la dernière balise (ici l'atterrissage, typée ESS) décrite par l'objet `goal`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.engine import rules
from app.models import FlightPlan

MAX_NAME = 30


def _wp(name: str, lat: float, lon: float, alt: float, desc: str) -> dict:
    return {
        "name": name[:MAX_NAME],
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "altSmoothed": int(round(alt)),
        "description": desc[:60],
    }


def _hhmmssz(iso: str, minutes: float = 0.0) -> str:
    t = datetime.fromisoformat(iso.replace("Z", "+00:00")) + timedelta(minutes=minutes)
    return t.strftime("%H:%M:%SZ")


def plan_to_xctsk(plan: FlightPlan) -> dict:
    tps: list[dict] = []
    takeoff = next((w for w in plan.waypoints if w.type == "takeoff"), None)
    if takeoff is None:
        raise ValueError("plan sans décollage")
    tps.append(
        {
            "type": "TAKEOFF",
            "radius": int(takeoff.radius_m or rules.TAKEOFF_RADIUS_M),
            "waypoint": _wp(takeoff.name, takeoff.lat, takeoff.lon, takeoff.altitude_m, "Décollage"),
        }
    )
    inner = [w for w in plan.waypoints if w.type in ("turnpoint", "thermal_trigger")]
    landing = next((w for w in plan.waypoints if w.type == "landing"), None)
    for i, w in enumerate(inner):
        tp = {"radius": int(w.radius_m or rules.TURNPOINT_RADIUS_M), "waypoint": _wp(w.name, w.lat, w.lon, w.altitude_m, w.note or w.type)}
        if i == 0:
            tp["type"] = "SSS"
        tps.append(tp)
    if landing is not None:
        tps.append(
            {
                "type": "ESS",
                "radius": int(landing.radius_m or rules.GOAL_RADIUS_M),
                "waypoint": _wp(landing.name, landing.lat, landing.lon, landing.altitude_m, "Atterrissage (but)"),
            }
        )
    if not inner:
        # tâche minimale : SSS à la sortie du cylindre de décollage
        tps[0]["type"] = "TAKEOFF"
        if len(tps) > 1:
            tps.insert(1, {"type": "SSS", "radius": int(rules.TAKEOFF_RADIUS_M) * 2,
                           "waypoint": _wp(takeoff.name + " SSS", takeoff.lat, takeoff.lon, takeoff.altitude_m, "Départ")})  # fmt: skip
    deadline = plan.window.latest_landing or plan.window.end
    return {
        "taskType": "CLASSIC",
        "version": 1,
        "earthModel": "WGS84",
        "turnpoints": tps,
        "sss": {"type": "RACE", "direction": "EXIT", "timeGates": [_hhmmssz(plan.window.start)]},
        "goal": {"type": "CYLINDER", "deadline": _hhmmssz(deadline)},
    }
