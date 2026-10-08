"""Chargement des données hors-ligne (app/fixtures/)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


@lru_cache
def load_json(name: str) -> Any:
    with (FIXTURES_DIR / name).open(encoding="utf-8") as f:
        return json.load(f)


def fixture_sites_raw() -> list[dict]:
    return list(load_json("sites.json")["sites"])


def fixture_relief() -> list[dict]:
    return list(load_json("relief.json")["points"])


def fixture_beacons_raw() -> list[dict]:
    return list(load_json("beacons.json")["beacons"])


def fixture_airspaces() -> dict:
    return load_json("airspaces.geojson")


def fixture_sensitive_areas() -> dict:
    return load_json("sensitive_areas.geojson")


@lru_cache
def terrain_anchors() -> tuple[tuple[float, float, float], ...]:
    """Points (lat, lon, altitude) qui contraignent le MNT synthétique."""
    pts = [(s["lat"], s["lon"], float(s["elevation_m"])) for s in fixture_sites_raw()]
    pts += [(p["lat"], p["lon"], float(p["elevation_m"])) for p in fixture_relief()]
    return tuple(pts)
