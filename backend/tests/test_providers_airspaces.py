"""Espaces aériens : OpenAIP (vraies réponses) et OpenAir local.

Fixtures réelles : openaip_airspaces_annecy.json (limit=5, page 1, nextPage 2) et
openaip_airspaces_annecy_full.json (appel live du 09/10/2026, bbox 6.05,45.75,6.35,45.95, limit=500 :
23 espaces, racine {items, limit, page} SANS nextPage ni totalCount sur la dernière page).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.engine import rules
from app.engine.airspace import is_activable, is_forbidden
from app.providers.airspaces import (
    FT,
    OpenAipAirspaces,
    OpenAirFiles,
    airspace_feature,
    limit_to_m,
    parse_openaip,
    parse_openair,
    parse_openair_altitude,
)
from app.providers.base import ProviderDisabled, ProviderError

FIX = Path(__file__).parent / "fixtures"
BBOX = (6.05, 45.75, 6.35, 45.95)
DUMMY_KEY = "cle-de-test"  # jamais la vraie clé dans les tests


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def full() -> dict:
    return _load("openaip_airspaces_annecy_full.json")


@pytest.fixture()
def by_name(full):
    items, nxt = parse_openaip(copy.deepcopy(full))
    assert nxt is None
    return {a.name: a for a in items}


def test_root_structure_and_pagination_fields():
    small = _load("openaip_airspaces_annecy.json")
    assert set(small) == {"items", "limit", "page", "nextPage"}  # pas de totalCount
    items, nxt = parse_openaip(small)
    assert len(items) == 5 and nxt == 2
    full = _load("openaip_airspaces_annecy_full.json")
    assert "nextPage" not in full and "totalCount" not in full
    assert len(parse_openaip(full)[0]) == 23


def test_limits_units_and_datums(by_name):
    cta = by_name["CTA MARSEILLE 7"]  # FL145 → FL195, classe D (icaoClass 3), type 26
    assert (cta.type, cta.airspace_class) == ("CTA", "D")
    assert cta.floor_m == round(145 * 100 * FT) == 4420 and cta.ceiling_m == 5944 and not cta.floor_agl
    chambery = by_name["TMA CHAMBERY 1"]  # 3000 ft MSL → FL95, classe E
    assert (chambery.type, chambery.airspace_class) == ("TMA", "E")
    assert chambery.floor_m == round(3000 * FT) == 914 and chambery.ceiling_m == round(9500 * FT)
    geneva = by_name["TMA GENEVA 8"]  # classe C (icaoClass 2)
    assert (geneva.type, geneva.airspace_class, geneva.floor_m) == ("TMA", "C", 2896)
    ctr = by_name["CTR ANNECY"]  # SFC (0 ft GND) → 4000 ft MSL, classe D
    assert (ctr.type, ctr.airspace_class, ctr.floor_m, ctr.ceiling_m) == ("CTR", "D", 0, 1219)
    assert ctr.floor_agl is False  # « sol » : rien à convertir
    lta = [a for n, a in by_name.items() if n.startswith("LTA 3 ALPES")]
    assert {a.type for a in lta} == {"LTA"}


def test_siv_is_information_only(by_name):
    sivs = [a for a in by_name.values() if a.type == "SIV"]
    assert len(sivs) == 8
    for a in sivs:
        assert a.airspace_class == "SIV"  # icaoClass 8 (non classé) + type 33
        assert not is_forbidden(a) and not is_activable(a)
        assert a.type in rules.AIRSPACE_INFO_TYPES
    fir = by_name["MARSEILLE FIR LFMM"]
    assert (fir.type, fir.airspace_class) == ("FIR", "UNCLASSIFIED") and not is_forbidden(fir)


def test_restricted_zones_activation_unknown(by_name):
    for name in ("ZRT SEMNOZ", "LF-R185 SACCONGES (NOTAM)"):
        a = by_name[name]
        assert (a.type, a.airspace_class) == ("R", "R")
        assert a.activity_known is False and is_activable(a) and not is_forbidden(a)
    assert by_name["ZRT SEMNOZ"].ceiling_m == round(5000 * FT)


def test_controlled_classes_forbidden(by_name):
    forbidden = {n for n, a in by_name.items() if is_forbidden(a)}
    assert {"CTR ANNECY", "CTA MARSEILLE 7", "TMA GENEVA 8"} <= forbidden
    assert "TMA CHAMBERY 1" not in forbidden  # classe E : autorisée en VMC


def test_limit_to_m():
    assert limit_to_m(1500, 0, 0) == (1500, True)  # m sol
    assert limit_to_m(1000, 1, 1) == pytest.approx((304.8, False))  # ft MSL
    assert limit_to_m(115, 6, 2) == pytest.approx((3505.2, False))  # FL115
    assert limit_to_m(9500, 1, 2) == pytest.approx((2895.6, False))  # ft STD ≈ FL95


def test_agl_floor_converted_with_terrain(full):
    data = {"items": [copy.deepcopy(full["items"][0])], "limit": 500, "page": 1}
    data["items"][0]["lowerLimit"] = {"value": 1000, "unit": 1, "referenceDatum": 0}  # 1000 ft sol
    data["items"][0]["upperLimit"] = {"value": 500, "unit": 0, "referenceDatum": 0}  # 500 m sol
    [a], _ = parse_openaip(data, terrain=lambda lat, lon: 1200.0)
    assert a.floor_agl is True and a.floor_m == round(304.8 + 1200) and a.ceiling_m == 1700
    [b], _ = parse_openaip(copy.deepcopy(data))  # sans MNT : hauteur seule, signalée sol
    assert b.floor_agl is True and b.floor_m == 305


def test_unknown_type_and_bad_geometry_tolerated(full):
    it = copy.deepcopy(full["items"][0])
    it["type"] = 99
    it["icaoClass"] = None
    bow = copy.deepcopy(it)
    ring = [[6.0, 45.0], [6.1, 45.1], [6.1, 45.0], [6.0, 45.1], [6.0, 45.0]]  # nœud papillon (invalide)
    bow["geometry"] = {"type": "Polygon", "coordinates": [ring]}
    none_geom = copy.deepcopy(it)
    none_geom["geometry"] = None
    items, _ = parse_openaip({"items": [it, bow, none_geom], "page": 1})
    assert [a.type for a in items] == ["OTHER", "OTHER"]
    assert all(a.geometry.is_valid for a in items)
    assert items[0].airspace_class == "UNCLASSIFIED"
    with pytest.raises(ProviderError):
        parse_openaip({"totalCount": 0})


def test_airspace_feature_contract(by_name):
    f = airspace_feature(by_name["TMA CHAMBERY 1"])
    assert f["type"] == "Feature" and f["geometry"]["type"] == "Polygon"
    assert f["properties"] == {
        "name": "TMA CHAMBERY 1", "airspace_class": "E", "type": "TMA", "floor_m": 914, "ceiling_m": 2896,
        "floor_reference": "AMSL", "ceiling_reference": "AMSL", "floor_height_m": None, "ceiling_height_m": None,
    }  # fmt: skip


# ---------------------------------------------------------------------------------------------
# Requêtes : en-tête de clé, pagination bornée, 429
# ---------------------------------------------------------------------------------------------
def _page(full: dict, page: int, next_page, n: int = 3) -> dict:
    items = copy.deepcopy(full["items"][(page - 1) * n : page * n])
    out = {"items": items, "limit": n, "page": page}
    if next_page is not None:
        out["nextPage"] = next_page
    return out


async def test_fetch_follows_next_page_then_stops(full):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        page = int(parse_qs(urlparse(str(req.url)).query)["page"][0])
        return httpx.Response(200, json=_page(full, page, 2 if page == 1 else None))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        out = await OpenAipAirspaces(c, "https://api.core.openaip.net/api", DUMMY_KEY).fetch(BBOX)
    assert len(seen) == 2 and len(out) == 6
    assert seen[0].headers["x-openaip-api-key"] == DUMMY_KEY
    assert DUMMY_KEY not in str(seen[0].url)  # clé en en-tête, jamais dans l'URL
    q = parse_qs(urlparse(str(seen[0].url)).query)
    assert q["bbox"] == ["6.0500,45.7500,6.3500,45.9500"]


async def test_fetch_pagination_is_bounded(full):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        page = int(parse_qs(urlparse(str(req.url)).query)["page"][0])
        calls.append(page)
        return httpx.Response(200, json=_page(full, 1, page + 1))  # nextPage toujours renseigné

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        out = await OpenAipAirspaces(c, "https://api.core.openaip.net/api", DUMMY_KEY).fetch(BBOX)
    assert calls == list(range(1, OpenAipAirspaces.MAX_PAGES + 1))
    assert len(out) == 3  # mêmes espaces à chaque page → dédoublonnés


async def test_fetch_stops_on_non_increasing_next_page(full):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=_page(full, 1, 1))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        await OpenAipAirspaces(c, "https://api.core.openaip.net/api", DUMMY_KEY).fetch(BBOX)
    assert len(calls) == 1


async def test_fetch_without_key_makes_no_request():
    def handler(req: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("aucun appel attendu")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(ProviderDisabled):
            await OpenAipAirspaces(c, "https://api.core.openaip.net/api", None).fetch(BBOX)


async def test_fetch_429_cloudflare():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="error code: 1015", headers={"retry-after": "300"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(ProviderError) as ei:
            await OpenAipAirspaces(c, "https://api.core.openaip.net/api", DUMMY_KEY).fetch(BBOX)
    assert ei.value.http_status == 429
    assert "réessayer dans 300 s" in str(ei.value) and DUMMY_KEY not in str(ei.value)


# ---------------------------------------------------------------------------------------------
# OpenAir
# ---------------------------------------------------------------------------------------------
OPENAIR = """\
* Extrait de démonstration (coordonnées fictives autour d'Annecy)
AC CTR
AN CTR TEST
AL SFC
AH 4000ft AMSL
DP 45:56:00 N 006:05:00 E
DP 45:56:00 N 006:10:00 E
DP 45:53:00 N 006:10:00 E
DP 45:53:00 N 006:05:00 E

AC R
AN ZRT TEST
AL 300 m AGL
AH FL65
V X=45:50:00 N 006:15:00 E
DC 2

AC E
AN TMA ARC
AL 1500ft
AH FL115
V X=45:48:00 N 006:12:00 E
V D=+
DP 45:48:00 N 006:16:00 E
DA 3,90,180
DP 45:48:00 N 006:12:00 E

AC GP
AN PROHIBITED GLIDERS
AL GND
AH UNLIM
V X=45:45:00 N 006:20:00 E
DC 0.5

AC D
AN HORS ZONE
AL SFC
AH 2000ft
DP 47:00:00 N 001:00:00 E
DP 47:01:00 N 001:00:00 E
DP 47:01:00 N 001:01:00 E
"""


def test_openair_altitudes():
    assert parse_openair_altitude("SFC") == (0.0, True)
    assert parse_openair_altitude("FL 65") == pytest.approx((6500 * FT, False))
    assert parse_openair_altitude("1500ft") == pytest.approx((1500 * FT, False))
    assert parse_openair_altitude("300 m AGL") == (300.0, True)
    assert parse_openair_altitude("2000 ft ASFC") == pytest.approx((2000 * FT, True))
    assert parse_openair_altitude("UNLIM")[0] == 99999.0


def test_openair_parse_classes_and_geometries():
    items = {a.name: a for a in parse_openair(OPENAIR, terrain=lambda lat, lon: 500.0)}
    ctr = items["CTR TEST"]
    assert (ctr.airspace_class, ctr.type, ctr.floor_m, ctr.ceiling_m) == ("D", "CTR", 0, 1219)
    assert is_forbidden(ctr) and ctr.activity_known
    zrt = items["ZRT TEST"]
    assert (zrt.airspace_class, zrt.floor_m, zrt.floor_agl) == ("R", 800, True)  # 300 m sol + MNT 500 m
    assert zrt.activity_known is False and is_activable(zrt)
    assert 0.003 < zrt.geometry.area < 0.005  # cercle de 2 NM
    arc = items["TMA ARC"]
    assert (arc.airspace_class, arc.type) == ("E", "TMA") and len(arc.geometry.exterior.coords) > 10
    gp = items["PROHIBITED GLIDERS"]
    assert gp.airspace_class == "P" and is_forbidden(gp) and gp.ceiling_m == 99999


def test_openair_latin1_file(tmp_path):
    text = OPENAIR.replace("AN ZRT TEST", "AN ZRT ÉCRINS")
    (tmp_path / "france.txt").write_bytes(text.encode("cp1252"))
    names = {a.name for a in OpenAirFiles(tmp_path).load()}
    assert "ZRT ÉCRINS" in names


def test_openair_files_bbox_filter(tmp_path):
    (tmp_path / "france.txt").write_text(OPENAIR, encoding="utf-8")
    (tmp_path / "notes.md").write_text("ignoré", encoding="utf-8")
    prov = OpenAirFiles(tmp_path)
    assert [p.name for p in prov.files()] == ["france.txt"]
    names = {a.name for a in prov.fetch(BBOX)}
    assert "HORS ZONE" not in names and {"CTR TEST", "ZRT TEST", "TMA ARC"} <= names
    with pytest.raises(ProviderDisabled):
        OpenAirFiles(tmp_path / "absent").load()
