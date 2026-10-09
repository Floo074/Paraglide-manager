"""Biodiv'Sports : parsing des vraies réponses (zones sensibles, pratiques), filtres, en-tête Accept.

Fixtures réelles :
- biodivsports_sensitivearea_annecy_bbox.json : appel live du 09/10/2026, `in_bbox=6.05,45.75,6.35,45.95`,
  `practices=3`, `period=ignore`, `format=geojson`, `language=fr` → 17 zones ;
- biodivsports_sensitivearea_annecy.json : enregistrement antérieur (bbox plus petite, 7 zones) ;
- biodivsports_practices.json (sans langue : noms {fr, en, it}) / biodivsports_practices_fr.json
  (`language=fr` : noms en chaîne).
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.providers.base import ProviderError
from app.providers.sensitive import (
    GEOJSON_ACCEPT,
    BiodivSports,
    area_feature,
    fixture_areas,
    merge_areas,
    parse_biodivsports,
    parse_practices,
)

FIX = Path(__file__).parent / "fixtures"
BBOX = (6.05, 45.75, 6.35, 45.95)


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def live() -> dict:
    return _load("biodivsports_sensitivearea_annecy_bbox.json")


@pytest.fixture()
def areas(live):
    items, nxt = parse_biodivsports(copy.deepcopy(live), [3])
    assert nxt is None
    return {a.id: a for a in items}


def test_counts_and_kinds(areas, live):
    assert live["count"] == 17 and len(areas) == 17
    kinds = {}
    for a in areas.values():
        kinds[a.kind] = kinds.get(a.kind, 0) + 1
    assert kinds == {"regulatory": 4, "species": 13}
    assert all(a.source == "biodivsports" and a.id.startswith("biodivsports:") for a in areas.values())
    assert all(a.geometry.is_valid and not a.geometry.is_empty for a in areas.values())


def test_species_zone_months_and_height(areas):
    eagle = areas["biodivsports:749"]
    assert (eagle.kind, eagle.species, eagle.name) == ("species", "Aigle royal", "Aigle royal")
    assert eagle.period_months == [1, 2, 3, 4, 5, 6, 7, 8]
    assert eagle.min_height_agl_m == 250.0
    assert eagle.active_in_month(3) and not eagle.active_in_month(10)
    falcon = areas["biodivsports:2181"]
    assert falcon.period_months == [2, 3, 4, 5, 6]
    circaete = areas["biodivsports:740"]
    assert circaete.species == "Circaète Jean-le-Blanc" and circaete.period_months == [3, 4, 5, 6, 7, 8, 9]


def test_regulatory_zones(areas):
    bout_du_lac = areas["biodivsports:1564"]
    assert bout_du_lac.kind == "regulatory" and bout_du_lac.species is None
    assert bout_du_lac.period_months == list(range(1, 13))
    # règle PARAGLIDING-FORBIDDEN reprise en tête de la consigne
    assert bout_du_lac.recommendation.startswith("Parapente et autres sports aériens interdits")
    assert bout_du_lac.url == "http://www.cen-haute-savoie.org/reserve-naturelle/bout-lac-annecy"
    semnoz = areas["biodivsports:2230"]
    assert semnoz.period_months == [5, 6, 7, 8, 9, 10]
    assert semnoz.min_height_agl_m is None
    assert areas["biodivsports:684"].min_height_agl_m == 300.0  # RNN du Roc de Chère
    assert areas["biodivsports:2201"].geometry.geom_type == "MultiPolygon"


def test_html_description_cleaned(areas):
    for a in areas.values():
        r = a.recommendation
        assert r and "<" not in r and "&eacute;" not in r and "&nbsp;" not in r
        assert len(r) <= 280 + len("Parapente et autres sports aériens interdits dans la zone. ")
    assert "é" in areas["biodivsports:1564"].recommendation


def test_older_fixture_still_parses():
    items, _ = parse_biodivsports(_load("biodivsports_sensitivearea_annecy.json"))
    assert len(items) == 7


def test_practices_both_formats():
    assert parse_practices(_load("biodivsports_practices.json")) == [3]  # {"fr": "Aerien", ...}
    assert parse_practices(_load("biodivsports_practices_fr.json")) == [3]  # "Aerien"
    assert parse_practices({"results": []}) == [3]  # repli


def test_client_side_filters(live):
    data = copy.deepcopy(live)
    feats = data["features"]
    feats[0]["properties"]["practices"] = [1, 2]  # pas de pratique aérienne
    feats[1]["properties"]["published"] = False
    feats[2]["geometry"] = {"type": "LineString", "coordinates": [[6.1, 45.8], [6.2, 45.9]]}
    feats[3]["geometry"] = {
        "type": "GeometryCollection",
        "geometries": [
            {"type": "Point", "coordinates": [6.2, 45.8]},
            {"type": "Polygon", "coordinates": [[[6.2, 45.8], [6.21, 45.8], [6.21, 45.81], [6.2, 45.8]]]},
        ],
    }
    feats[4]["geometry"] = {"type": "Point", "coordinates": [6.25, 45.85]}
    feats[5]["properties"]["period"] = None
    feats[5]["properties"]["name"] = {"fr": "Gypaète barbu", "en": "Bearded vulture"}
    items = {a.id: a for a in parse_biodivsports(data, [3])[0]}
    assert len(items) == 17 - 3
    gc = items[f"biodivsports:{feats[3]['id']}"]
    assert gc.geometry.geom_type == "Polygon"
    pt = items[f"biodivsports:{feats[4]['id']}"]
    assert pt.geometry.geom_type == "Polygon" and pt.geometry.area > 0  # point → tampon ~500 m
    gyp = items[f"biodivsports:{feats[5]['id']}"]
    assert gyp.name == "Gypaète barbu" and gyp.period_months == list(range(1, 13))
    # sans liste de pratiques : pas de filtre côté client
    assert len(parse_biodivsports(copy.deepcopy(live))[0]) == 17


def test_next_link_forced_to_https(live):
    data = copy.deepcopy(live)
    data["next"] = "http://biodiv-sports.fr/api/v2/sensitivearea/?page=2"
    _, nxt = parse_biodivsports(data)
    assert nxt == "https://biodiv-sports.fr/api/v2/sensitivearea/?page=2"
    with pytest.raises(ProviderError):
        parse_biodivsports({"results": []})


def test_area_feature_contract(areas):
    f = area_feature(areas["biodivsports:749"], datetime(2026, 4, 1, tzinfo=UTC))
    p = f["properties"]
    assert set(p) == {
        "id", "name", "species", "kind", "period_months", "active_now", "recommendation", "min_height_agl_m",
        "source", "url",
    }  # fmt: skip
    assert p["active_now"] is True and p["source"] == "biodivsports"
    october = area_feature(areas["biodivsports:749"], datetime(2026, 10, 1, tzinfo=UTC))
    assert october["properties"]["active_now"] is False


def test_merge_with_national_park_cores(areas):
    parks = fixture_areas((5.0, 44.0, 8.0, 46.5), parks_only=True)
    merged = merge_areas(list(areas.values()), parks)
    assert len(merged) == 17 + len(parks)  # aucun cœur de parc dans la bbox d'Annecy côté Biodiv'Sports


# ---------------------------------------------------------------------------------------------
# Requêtes HTTP
# ---------------------------------------------------------------------------------------------
async def test_fetch_params_accept_header_and_pagination(live):
    seen: list[httpx.Request] = []
    page2 = copy.deepcopy(live)
    page2["features"] = page2["features"][:2]
    page1 = copy.deepcopy(live)
    page1["next"] = "http://biodiv-sports.fr/api/v2/sensitivearea/?page=2"

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        path = urlparse(str(req.url)).path
        if path.endswith("/sensitivearea_practice/"):
            return httpx.Response(200, content=(FIX / "biodivsports_practices_fr.json").read_bytes())
        accept = req.headers.get("accept", "")
        if "geo+json" not in accept and "*/*" not in accept:
            return httpx.Response(406, json={"detail": "L'en-tête « Accept » n'a pas pu être satisfaite."})
        if "page=2" in str(req.url):
            return httpx.Response(200, json=page2)
        return httpx.Response(200, json=page1)

    headers = {"Accept": "application/json"}  # en-tête par défaut du client de l'application
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), headers=headers) as c:
        out = await BiodivSports(c, "https://biodiv-sports.fr/api/v2").fetch(BBOX)
    assert len(out) == 17 + 2
    assert [urlparse(str(r.url)).scheme for r in seen] == ["https"] * 3
    q = parse_qs(urlparse(str(seen[1].url)).query)
    assert q["in_bbox"] == ["6.0500,45.7500,6.3500,45.9500"]
    assert q["practices"] == ["3"] and q["period"] == ["ignore"] and q["format"] == ["geojson"]
    assert seen[1].headers["accept"] == GEOJSON_ACCEPT


async def test_fetch_406_is_reported_precisely():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(406, json={"detail": "L'en-tête « Accept » n'a pas pu être satisfaite."})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(ProviderError) as ei:
            await BiodivSports(c, "https://biodiv-sports.fr/api/v2").fetch(BBOX)
    assert ei.value.http_status == 406 and "Accept" in str(ei.value)
