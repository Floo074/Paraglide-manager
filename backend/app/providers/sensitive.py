"""Zones sensibles : Biodiv'Sports (API Geotrek libre) + cœurs de parcs nationaux (fixtures).

Biodiv'Sports — constats sur réponses réelles (tests/fixtures/biodivsports_*.json) :
- le filtre géographique est `in_bbox=minlon,minlat,maxlon,maxlat` (le paramètre `bbox` est IGNORÉ) ;
- `practices=3` = pratique « Aérien » (liste : /api/v2/sportpractice/ → redirigé vers
  /api/v2/sensitivearea_practice/ ; résultats {id, name: {fr, en, it}}) ;
- `period=ignore` renvoie toutes les zones quelle que soit la période ;
- FeatureCollection paginée (`count`, `next`) ; properties : name (str en `language=fr`),
  species_id (null pour les zones réglementaires / cœurs de parc), elevation (hauteur de survol
  recommandée en m, souvent null), period (12 booléens), practices (ids), info_url, description (HTML) ;
- géométries Polygon, MultiPolygon et parfois GeometryCollection.
"""

from __future__ import annotations

import html
import re
from datetime import datetime

import httpx
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from app.engine.context import SensitiveArea
from app.providers.base import ProviderError, get_json
from app.providers.fixture_data import fixture_sensitive_areas

DEFAULT_AERIAL_PRACTICE_IDS = [3]
MAX_PAGES = 5


def _polygons(g: BaseGeometry) -> BaseGeometry | None:
    if isinstance(g, Polygon | MultiPolygon):
        return g
    if isinstance(g, GeometryCollection):
        polys = [x for x in g.geoms if isinstance(x, Polygon | MultiPolygon)]
        return unary_union(polys) if polys else None
    if g.geom_type == "Point":
        return g.buffer(0.005)  # ~500 m
    return None


def _strip_html(s: str | None, max_len: int = 280) -> str:
    if not s:
        return ""
    t = html.unescape(re.sub(r"<[^>]+>", " ", s))
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= max_len else t[: max_len - 1].rsplit(" ", 1)[0] + "…"


def _kind(props: dict) -> str:
    name = (props.get("name") or "").lower()
    if props.get("species_id") is not None:
        return "species"
    if ("coeur" in name or "cœur" in name) and "parc national" in name:
        return "national_park_core"
    return "regulatory"


def parse_biodivsports(data) -> tuple[list[SensitiveArea], str | None]:
    if not isinstance(data, dict) or "features" not in data:
        raise ProviderError("Biodiv'Sports : réponse sans 'features'")
    out = []
    for f in data["features"]:
        props = f.get("properties") or {}
        try:
            g = _polygons(shape(f["geometry"]))
        except Exception:
            continue
        if g is None or g.is_empty:
            continue
        period = props.get("period") or []
        months = [i + 1 for i, v in enumerate(period) if v] if period else list(range(1, 13))
        kind = _kind(props)
        name = props.get("name") or "Zone sensible"
        if isinstance(name, dict):
            name = name.get("fr") or next(iter(name.values()), "Zone sensible")
        rec = _strip_html(props.get("description"))
        if kind == "species" and not rec:
            rec = "Zone de quiétude de la faune : éviter le survol bas et les approches des falaises."
        elif not rec:
            rec = "Zone réglementée : se référer à l'arrêté de protection."
        out.append(
            SensitiveArea(
                id=f"biodivsports:{f.get('id') or props.get('id')}",
                name=str(name),
                kind=kind,
                species=str(name) if kind == "species" else None,
                period_months=months or list(range(1, 13)),
                recommendation=rec,
                min_height_agl_m=props.get("elevation"),
                geometry=g,
                source="biodivsports",
                url=props.get("info_url") or props.get("url"),
            )
        )
    return out, data.get("next")


def parse_practices(data) -> list[int]:
    res = data.get("results") if isinstance(data, dict) else data
    ids = []
    for p in res or []:
        name = p.get("name")
        txt = " ".join(v for v in name.values() if v) if isinstance(name, dict) else str(name or "")
        txt = txt.lower()
        if "aérien" in txt or "aerien" in txt or "aerial" in txt or "vol libre" in txt:
            ids.append(int(p["id"]))
    return ids or DEFAULT_AERIAL_PRACTICE_IDS


class BiodivSports:
    name = "Biodiv'Sports"

    def __init__(self, client: httpx.AsyncClient, base_url: str):
        self.client = client
        self.base_url = base_url.rstrip("/")
        self._practices: list[int] | None = None

    async def practices(self) -> list[int]:
        if self._practices is None:
            try:
                data = await get_json(self.client, f"{self.base_url}/sportpractice/", {"language": "fr"})
                self._practices = parse_practices(data)
            except ProviderError:
                self._practices = DEFAULT_AERIAL_PRACTICE_IDS
        return self._practices

    async def fetch(self, bbox) -> list[SensitiveArea]:
        prac = await self.practices()
        params = {
            "format": "geojson",
            "language": "fr",
            "in_bbox": ",".join(f"{x:.4f}" for x in bbox),
            "period": "ignore",
            "practices": ",".join(str(p) for p in prac),
        }
        out: list[SensitiveArea] = []
        url: str | None = f"{self.base_url}/sensitivearea/"
        for _ in range(MAX_PAGES):
            data = await get_json(self.client, url, params)
            items, nxt = parse_biodivsports(data)
            out += items
            if not nxt:
                break
            url, params = nxt, None
        return out


def fixture_areas(bbox, parks_only: bool) -> list[SensitiveArea]:
    b = box(*bbox)
    out = []
    for f in fixture_sensitive_areas()["features"]:
        p = f["properties"]
        if parks_only and not p.get("always_included"):
            continue
        g = shape(f["geometry"])
        if not g.intersects(b):
            continue
        out.append(
            SensitiveArea(
                id=p["id"], name=p["name"], kind=p["kind"], species=p.get("species"), period_months=list(p["period_months"]),
                recommendation=p["recommendation"], min_height_agl_m=p.get("min_height_agl_m"), geometry=g,
                source="fixture", url=p.get("url"),
            )  # fmt: skip
        )
    return out


def merge_areas(live: list[SensitiveArea], parks: list[SensitiveArea]) -> list[SensitiveArea]:
    """Ajoute les cœurs de parcs des fixtures s'ils ne sont pas déjà fournis par Biodiv'Sports."""
    out = list(live)
    live_names = " | ".join(a.name.lower() for a in live if a.kind == "national_park_core")
    for p in parks:
        key = p.name.lower().split("parc national")[-1].strip(" dedulaes'")
        if key and key in live_names:
            continue
        out.append(p)
    return out


def area_feature(a: SensitiveArea, at: datetime) -> dict:
    from shapely.geometry import mapping

    return {
        "type": "Feature",
        "geometry": mapping(a.geometry),
        "properties": {
            "id": a.id,
            "name": a.name,
            "species": a.species,
            "kind": a.kind,
            "period_months": a.period_months,
            "active_now": a.active_in_month(at.month),
            "recommendation": a.recommendation,
            "min_height_agl_m": a.min_height_agl_m,
            "source": a.source if a.source in ("biodivsports", "fixture") else "fixture",
            "url": a.url,
        },
    }
