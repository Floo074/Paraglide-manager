"""Export GPX 1.1 (http://www.topografix.com/GPX/1/1) : metadata, wpt (déco, points, balises, atterros), rte."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from app.models import FlightPlan

GPX_NS = "http://www.topografix.com/GPX/1/1"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
SCHEMA_LOC = "http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd"

_SYM = {
    "takeoff": "Flag, Green",
    "turnpoint": "Flag, Blue",
    "thermal_trigger": "Summit",
    "landing": "Flag, Red",
    "alternate_landing": "Flag, Red",
}


def _sub(parent: ET.Element, tag: str, text: str | None = None, **attrs) -> ET.Element:
    el = ET.SubElement(parent, f"{{{GPX_NS}}}{tag}", attrs)
    if text is not None:
        el.text = text
    return el


def plan_to_gpx(plan: FlightPlan) -> str:
    ET.register_namespace("", GPX_NS)
    ET.register_namespace("xsi", XSI_NS)
    root = ET.Element(
        f"{{{GPX_NS}}}gpx",
        {"version": "1.1", "creator": "Paraglide Manager", f"{{{XSI_NS}}}schemaLocation": SCHEMA_LOC},
    )
    # ordre imposé par le schéma : metadata, wpt*, rte*, trk*, extensions
    md = _sub(root, "metadata")
    _sub(md, "name", plan.title)
    _sub(md, "desc", " | ".join([plan.summary, *plan.briefing[:3]]))
    _sub(md, "author").append(_name_el("Paraglide Manager"))
    _sub(md, "time", plan.target_time)
    _sub(md, "keywords", f"parapente,{plan.flight_type},{plan.flyability}")

    def wpt(lat, lon, ele, name, desc, sym, typ):
        w = _sub(root, "wpt", lat=f"{lat:.6f}", lon=f"{lon:.6f}")
        _sub(w, "ele", f"{ele:.0f}")
        _sub(w, "name", name)
        if desc:
            _sub(w, "desc", desc)
        _sub(w, "sym", sym)
        _sub(w, "type", typ)

    for w in plan.waypoints:
        wpt(w.lat, w.lon, w.altitude_m, w.name, w.note, _SYM.get(w.type, "Waypoint"), w.type)
    for b in plan.beacons_nearby:
        desc = f"Balise {b.source}"
        if b.wind_speed_kmh is not None:
            desc += f" : {b.wind_speed_kmh:.0f} km/h ({b.observed_at})"
        wpt(b.lat, b.lon, b.elevation_m or 0.0, f"Balise {b.name}", desc, "Weather Station", "beacon")

    rte = _sub(root, "rte")
    _sub(rte, "name", plan.title)
    _sub(rte, "desc", f"{plan.distance_km:.1f} km, ~{plan.est_duration_min:.0f} min, verdict {plan.flyability}")
    for i, (lon, lat, alt) in enumerate(plan.route.coordinates):
        p = _sub(rte, "rtept", lat=f"{lat:.6f}", lon=f"{lon:.6f}")
        _sub(p, "ele", f"{alt:.0f}")
        _sub(p, "name", f"P{i + 1}")
    xml = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml


def _name_el(name: str) -> ET.Element:
    el = ET.Element(f"{{{GPX_NS}}}name")
    el.text = name
    return el
