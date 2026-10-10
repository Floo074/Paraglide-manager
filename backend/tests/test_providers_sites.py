"""ParaglidingEarth : parsing de la vraie réponse bbox Annecy, statut officiel, dédoublonnage.

Fixture réelle : paraglidingearth_bbox_annecy.json (identique à l'appel live du 09/10/2026,
`https://www.paraglidingearth.com/api/geojson/getBoundingBoxSites.php`, bbox 6.05,45.75,6.35,45.95).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.models import COMPASS_16, Site
from app.providers.base import ProviderError
from app.providers.sites import (
    ParaglidingEarthSites,
    associate_landings,
    fixture_sites,
    https_link,
    merge_sites,
    parse_pge,
    pge_official,
    pge_orientations,
)

FIX = Path(__file__).parent / "fixtures"
HAS_OFFICIAL = "official" in Site.model_fields and "landing_kind" in Site.model_fields


@pytest.fixture(scope="module")
def raw() -> dict:
    return json.loads((FIX / "paraglidingearth_bbox_annecy.json").read_text(encoding="utf-8"))


@pytest.fixture()
def parsed(raw):
    sites, meta = parse_pge(copy.deepcopy(raw))
    return {s.id: s for s in sites}, meta


def test_counts_takeoffs_and_landings(parsed):
    by_id, meta = parsed
    takeoffs = [s for s in by_id.values() if s.kind == "takeoff"]
    landings = [s for s in by_id.values() if s.kind == "landing"]
    assert len(takeoffs) == 10
    # atterros documentés : Doussard (Forclaz), Marlens, Semnoz, Talloires (Planfait)
    assert sorted(s.id for s in landings) == [
        "pge:12643:landing",
        "pge:21829:landing",
        "pge:21842:landing",
        "pge:3046:landing",
    ]
    assert set(meta) == {s.id for s in takeoffs}
    assert all(s.source == "paraglidingearth" for s in by_id.values())


def test_forclaz_takeoff_and_doussard_landing(parsed):
    by_id, _ = parsed
    t = by_id["pge:3046"]
    assert t.name == "Montmin (Col de la Forclaz)"
    assert (t.lat, t.lon, t.elevation_m) == (45.8142, 6.247, 1265.0)
    # N = 2, NW = 2, W = 1 → secteurs intermédiaires NNW et WNW ajoutés
    assert t.orientations == ["N", "W", "WNW", "NW", "NNW"]
    assert t.flight_types == ["local", "cross_country"]
    assert t.associated_landing_ids == ["pge:3046:landing"]
    assert t.url == "https://www.paraglidingearth.com/?site=3046"
    assert t.access == "easy :-)"
    assert "\r" not in (t.description or "") and t.description.startswith("Alti: 1240m\nfrom Annecy")
    ldg = by_id["pge:3046:landing"]
    assert ldg.name == "Doussard" and ldg.elevation_m == 467.0
    assert (ldg.lat, ldg.lon) == (45.7819, 6.2221)
    assert ldg.orientations == [] and ldg.flight_types == []


def test_unknown_altitude_and_orientation(parsed):
    by_id, _ = parsed
    lanc = by_id["pge:21827"]  # Lancrenaz : altitude « -1 », aucun secteur noté
    assert lanc.elevation_m == -1.0 and lanc.orientations == [] and lanc.associated_landing_ids == []
    marlens = by_id["pge:12643"]  # tous secteurs notés 2 → rose complète
    assert marlens.orientations == COMPASS_16
    planfait = by_id["pge:21842"]
    assert planfait.flight_types == ["local", "ridge_soaring", "cross_country"]
    assert planfait.restrictions.startswith("air space info")
    assert by_id["pge:21842:landing"].name == "Talloires"
    semnoz_ldg = by_id["pge:21829:landing"]
    assert semnoz_ldg.name == "Atterro de Semnoz"  # landing_name vide


def test_all_links_are_https_www(parsed):
    by_id, _ = parsed
    assert all(s.url and s.url.startswith("https://www.paraglidingearth.com/") for s in by_id.values())
    assert https_link("http://paraglidingearth.com/?site=1") == "https://www.paraglidingearth.com/?site=1"
    assert https_link(None) is None


def test_official_rule(raw):
    props = {f["id"]: f["properties"] for f in raw["features"]}
    # fiche complète (altitude + orientation)
    assert pge_official(props["3046"], "Montmin (Col de la Forclaz)", 1265.0, ["N"])
    # fiche sommaire : ni altitude ni orientation
    assert not pge_official(props["21827"], "Lancrenaz", None, [])
    # altitude connue mais aucune orientation notée
    assert not pge_official(props["21825"], "Chalet de l'Aulp", 1575.0, [])
    # lien vers une fiche FFVL → référencé même incomplet
    assert pge_official({**props["21827"], "ffvl_site_id": "1234"}, "Lancrenaz", None, [])
    # mot-clé « sauvage » → jamais officiel
    assert not pge_official(props["3046"], "Déco sauvage du Lanfonnet", 1265.0, ["N"])


@pytest.mark.skipif(not HAS_OFFICIAL, reason="Site.official / landing_kind pas encore dans models.py")
def test_official_and_landing_kind_fields(parsed):
    by_id, _ = parsed
    assert by_id["pge:3046"].official is True and by_id["pge:3046"].landing_kind is None
    assert by_id["pge:3046:landing"].official is True and by_id["pge:3046:landing"].landing_kind == "official"
    assert by_id["pge:21827"].official is False
    sites, _ = fixture_sites()
    assert all(s.official for s in sites)
    assert all(s.landing_kind == "official" for s in sites if s.kind == "landing")


def test_closed_and_hanggliding_only_and_duplicates(raw):
    data = copy.deepcopy(raw)
    f0 = data["features"][0]
    hg = copy.deepcopy(f0)
    hg["id"] = hg["properties"]["pge_site_id"] = "999"
    hg["properties"]["paragliding"] = "0"  # delta uniquement
    closed = copy.deepcopy(f0)
    closed["id"] = closed["properties"]["pge_site_id"] = "998"
    closed["properties"]["name"] = "Ancien déco fermé"
    closed["properties"].pop("landing")
    closed["properties"]["landing_lat"] = closed["properties"]["landing_lng"] = ""
    data["features"] += [hg, closed, copy.deepcopy(f0)]  # + doublon exact de Forclaz
    by_id = {s.id: s for s in parse_pge(data)[0]}
    assert "pge:999" not in by_id
    assert by_id["pge:998"].status == "closed" and by_id["pge:998"].associated_landing_ids == []
    assert len([s for s in by_id.values() if s.kind == "takeoff"]) == 11


def test_malformed_response():
    with pytest.raises(ProviderError):
        parse_pge({"error": "x"})
    sites, _ = parse_pge({"features": [{"geometry": {"coordinates": []}, "properties": {}}, "junk"]})
    assert sites == []


def test_pge_orientations_intermediate_sectors():
    assert pge_orientations({"S": "2", "SW": "1"}) == ["S", "SSW", "SW"]
    assert pge_orientations({"N": "0"}) == []


# ---------------------------------------------------------------------------------------------
# Fusion / dédoublonnage / association
# ---------------------------------------------------------------------------------------------
def _site(**kw) -> Site:
    base = dict(
        id="x", name="x", kind="takeoff", lat=45.8, lon=6.2, elevation_m=1000.0, orientations=["N"],
        source="paraglidingearth",
    )  # fmt: skip
    base.update(kw)
    return Site(**base)


def test_shared_landing_deduplicated_and_references_rewritten(raw):
    data = copy.deepcopy(raw)
    twin = copy.deepcopy(next(f for f in data["features"] if f["id"] == "21842"))  # Planfait
    twin["id"] = twin["properties"]["pge_site_id"] = "50000"
    twin["properties"]["name"] = "Planfait sud"
    twin["geometry"]["coordinates"] = [6.2310, 45.8480]  # déco distinct (~800 m), même atterro
    data["features"].append(twin)
    sites, _ = parse_pge(data)
    merged = merge_sites([sites])
    by_id = {s.id: s for s in merged}
    landings = [s for s in merged if s.kind == "landing" and s.name == "Talloires"]
    assert len(landings) == 1
    kept = landings[0].id
    assert by_id["pge:21842"].associated_landing_ids == [kept]
    assert by_id["pge:50000"].associated_landing_ids == [kept]
    associate_landings(merged)
    assert by_id["pge:50000"].associated_landing_ids == [kept]  # association explicite conservée


def test_duplicate_takeoffs_keep_most_complete():
    poor = _site(id="pge:1", name="Forclaz", elevation_m=-1.0, orientations=[], description=None)
    rich = _site(id="pge:2", name="Col de la Forclaz", lat=45.8003, elevation_m=1250.0, orientations=["NW"],
                 description="déco principal")  # fmt: skip
    merged = merge_sites([[poor, rich]])
    assert [s.id for s in merged] == ["pge:2"]


def test_fixture_source_has_priority_and_is_completed():
    fx = _site(id="fixture:forclaz", source="fixture", url=None, description=None)
    pge = _site(id="pge:3046", url="https://www.paraglidingearth.com/?site=3046", description="desc", lat=45.8005)
    merged = merge_sites([[pge], [fx]])
    assert [s.id for s in merged] == ["fixture:forclaz"]
    assert merged[0].url.startswith("https://www.") and merged[0].description == "desc"


def test_associate_landings_drops_higher_landing_and_auto_associates():
    t = _site(id="t", elevation_m=1200.0, associated_landing_ids=["high"])
    high = _site(id="high", kind="landing", lat=45.79, elevation_m=1500.0, orientations=[])
    low = _site(id="low", kind="landing", lat=45.785, lon=6.21, elevation_m=450.0, orientations=[])
    sites = [t, high, low]
    associate_landings(sites)
    assert t.associated_landing_ids == ["low"]


# ---------------------------------------------------------------------------------------------
# Requête HTTP
# ---------------------------------------------------------------------------------------------
async def test_fetch_uses_https_www_and_bbox_params(raw):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=raw)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        prov = ParaglidingEarthSites(c, "http://paraglidingearth.com/api/geojson")  # mal configuré
        sites, _ = await prov.fetch((6.05, 45.75, 6.35, 45.95))
    url = urlparse(str(seen[0].url))
    assert (url.scheme, url.netloc) == ("https", "www.paraglidingearth.com")
    assert url.path == "/api/geojson/getBoundingBoxSites.php"
    q = parse_qs(url.query)
    assert (q["north"], q["south"], q["east"], q["west"]) == (["45.9500"], ["45.7500"], ["6.3500"], ["6.0500"])
    assert q["style"] == ["detailled"] and q["limit"] == [str(ParaglidingEarthSites.LIMIT)]
    assert len(sites) == 14


async def test_fetch_http_error_is_provider_error():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(ProviderError) as ei:
            await ParaglidingEarthSites(c, "https://www.paraglidingearth.com/api/geojson").fetch((6, 45, 7, 46))
    assert ei.value.http_status == 503


async def test_live_sites_served_when_dem_quota_exhausted(raw):
    """Quota Open-Meteo épuisé (MNT indisponible) en live : les sites PGE restent servis avec leur altitude,
    les sites sans altitude sont écartés (jamais d'altitude inventée) et le résultat n'est gardé que 10 min."""
    import time

    from app.config import Settings
    from app.services import DataService

    def handler(request: httpx.Request) -> httpx.Response:
        if "paraglidingearth" in request.url.host:
            return httpx.Response(200, json=copy.deepcopy(raw))
        if "open-meteo" in request.url.host:
            return httpx.Response(429, text=(FIX / "open_meteo_429.json").read_text(encoding="utf-8"))
        return httpx.Response(404)

    settings = Settings(_env_file=None, data_mode="live", openaip_api_key=None, ffvl_api_key=None)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        ds = DataService(settings, client=c)
        bbox = (6.05, 45.75, 6.35, 45.95)
        sites, _, refs, warnings = await ds.sites(bbox)
    names = {s.name for s in sites}
    assert "Montmin (Col de la Forclaz)" in names and "Lancrenaz" not in names and "Col du Varo" not in names
    assert all(s.elevation_m > 0 for s in sites) and refs[0].mode == "live"
    assert any(w.startswith("MNT indisponible") and "2 site(s) sans altitude" in w for w in warnings)
    expires, _ = ds.sites_cache._data[("sites", "live", tuple(round(x, 2) for x in bbox))]
    assert expires - time.monotonic() <= 600 + 1
