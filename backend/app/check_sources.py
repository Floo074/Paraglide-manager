"""Vérification des sources de données live : un vrai appel par fournisseur, zone d'Annecy.

Usage :
    uv run python -m app.check_sources [--save-fixtures DIR] [--only a,b] [--skip a,b]

Sources (clés utilisables avec --only / --skip) :
    open-meteo            prévision Forclaz, 3 modèles (AROME HD, ICON-D2, ECMWF) + niveaux de pression
    open-meteo-elevation  MNT Open-Meteo (Forclaz + Doussard)
    paraglidingearth      sites PGE de la bbox d'Annecy (https://www. uniquement)
    pioupiou              balises Pioupiou / OpenWindMap (parseur de providers/beacons.py)
    openaip               espaces aériens OpenAIP (si clé configurée ; au plus un appel / 5 min)
    openair               fichiers OpenAir locaux (data/airspaces/, si présents)
    biodivsports          zones sensibles Biodiv'Sports (pratique aérienne)

Affiche un tableau source / état / HTTP / éléments analysés / durée / détail ou erreur précise.
Code de sortie 1 si une source attendue échoue (une source désactivée faute de clé ou de fichier
n'est pas attendue), 0 sinon. La clé OpenAIP n'est jamais affichée ni enregistrée.

`--save-fixtures DIR` enregistre chaque réponse brute en JSON (`<source>.json`, tronquée au-delà de
~400 Ko, secrets masqués) pour comparer avec tests/fixtures/.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from app.config import Settings, get_settings
from app.providers.airspaces import OpenAipAirspaces, OpenAirFiles
from app.providers.base import ProviderDisabled, ProviderError, make_client, redact
from app.providers.beacons import PioupiouBeacons, filter_bbox
from app.providers.open_meteo import OpenMeteoElevation, OpenMeteoForecast, model_label, series_summary
from app.providers.sensitive import BiodivSports
from app.providers.sites import ParaglidingEarthSites

ANNECY_BBOX = (6.05, 45.75, 6.35, 45.95)  # min_lon, min_lat, max_lon, max_lat
FORCLAZ = (45.81, 6.25, 1245.0)  # col de la Forclaz (déco de Montmin) — lat, lon, altitude
DOUSSARD = (45.7819, 6.2221)  # atterro de Doussard
OPENAIP_MIN_INTERVAL_S = 300  # Cloudflare : au plus un appel toutes les 5 min
MAX_FIXTURE_BYTES = 400_000
FIXTURE_KEEP_ITEMS = 60

SOURCE_KEYS = (
    "open-meteo",
    "open-meteo-elevation",
    "paraglidingearth",
    "pioupiou",
    "openaip",
    "openair",
    "biodivsports",
)


@dataclass
class CheckResult:
    key: str
    name: str
    status: str  # OK | ÉCHEC | DÉSACTIVÉ | IGNORÉ
    expected: bool
    http: str = "-"
    count: int | None = None
    duration_s: float = 0.0
    detail: str = ""
    responses: list[httpx.Response] = field(default_factory=list, repr=False)

    @property
    def failed(self) -> bool:
        return self.expected and self.status == "ÉCHEC"


class _Recorder:
    """Hook httpx : garde les réponses reçues pendant une vérification (code HTTP, corps)."""

    def __init__(self) -> None:
        self.responses: list[httpx.Response] = []

    async def hook(self, response: httpx.Response) -> None:
        await response.aread()
        self.responses.append(response)


# ---------------------------------------------------------------------------------------------
# Vérifications unitaires : chacune renvoie (nombre d'éléments analysés, détail)
# ---------------------------------------------------------------------------------------------
async def _check_open_meteo(s: Settings, client: httpx.AsyncClient, bbox) -> tuple[int, str]:
    prov = OpenMeteoForecast(client, s.open_meteo_base_url, s.open_meteo_model_list, s.open_meteo_api_key)
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    pfs = await prov.fetch([FORCLAZ], now, now + timedelta(hours=36), with_levels=True)
    pf = pfs[0]
    n = sum(len(m.hours) for m in pf.models)
    missing = [m for m in s.open_meteo_model_list if model_label(m) not in {x.model for x in pf.models}]
    detail = series_summary(pf)
    if missing:
        detail += " ; sans donnée : " + ", ".join(missing)
    return n, detail


async def _check_elevation(s: Settings, client: httpx.AsyncClient, bbox) -> tuple[int, str]:
    prov = OpenMeteoElevation(client, s.open_meteo_elevation_url)
    vals = await prov.fetch([FORCLAZ[:2], DOUSSARD])
    return len(vals), f"Forclaz {vals[0]:.0f} m, Doussard {vals[1]:.0f} m"


async def _check_pge(s: Settings, client: httpx.AsyncClient, bbox) -> tuple[int, str]:
    prov = ParaglidingEarthSites(client, s.paraglidingearth_url)
    sites, _ = await prov.fetch(bbox)
    tk = [x for x in sites if x.kind != "landing"]
    ld = [x for x in sites if x.kind == "landing"]
    no_or = sum(1 for x in tk if not x.orientations)
    no_alt = sum(1 for x in tk if x.elevation_m <= 0)
    detail = f"{len(tk)} décos, {len(ld)} atterros ; {no_or} décos sans orientation, {no_alt} sans altitude"
    if tk and hasattr(tk[0], "official"):
        detail += f" ; {sum(1 for x in tk if getattr(x, 'official', False))} décos référencés"
    return len(sites), detail


async def _check_pioupiou(s: Settings, client: httpx.AsyncClient, bbox) -> tuple[int, str]:
    prov = PioupiouBeacons(client, s.pioupiou_url)
    beacons = await prov.fetch_all()
    local = filter_bbox(beacons, bbox)
    fresh = sum(1 for b in local if not b.stale)
    return len(beacons), f"{len(local)} dans la zone (dont {fresh} à jour)"


async def _check_openaip(s: Settings, client: httpx.AsyncClient, bbox) -> tuple[int, str]:
    prov = OpenAipAirspaces(client, s.openaip_url, s.openaip_api_key)
    items = await prov.fetch(bbox)
    by_cls: dict[str, int] = {}
    for a in items:
        by_cls[a.airspace_class] = by_cls.get(a.airspace_class, 0) + 1
    cls_txt = ", ".join(f"{k} {v}" for k, v in sorted(by_cls.items()))
    return len(items), f"clé configurée ; classes : {cls_txt or 'aucune'}"


async def _check_openair(s: Settings, client: httpx.AsyncClient, bbox) -> tuple[int, str]:
    prov = OpenAirFiles(s.airspace_openair_dir)
    files = prov.files()
    if not files:
        raise ProviderDisabled(f"aucun fichier OpenAir dans {s.airspace_openair_dir}")
    items = prov.fetch(bbox)
    total = len(prov.load())
    return len(items), f"{len(files)} fichier(s), {total} espaces au total"


async def _check_biodiv(s: Settings, client: httpx.AsyncClient, bbox) -> tuple[int, str]:
    prov = BiodivSports(client, s.biodivsports_url)
    areas = await prov.fetch(bbox)
    kinds: dict[str, int] = {}
    for a in areas:
        kinds[a.kind] = kinds.get(a.kind, 0) + 1
    kinds_txt = ", ".join(f"{k} {v}" for k, v in sorted(kinds.items()))
    practices = await prov.practices()  # déjà en mémoire : pas de nouvel appel
    return len(areas), f"pratiques aériennes {practices} ; {kinds_txt or 'aucune zone'}"


CHECKS: dict[str, tuple[str, Callable[..., Awaitable[tuple[int, str]]]]] = {
    "open-meteo": ("Open-Meteo prévision", _check_open_meteo),
    "open-meteo-elevation": ("Open-Meteo Elevation", _check_elevation),
    "paraglidingearth": ("ParaglidingEarth", _check_pge),
    "pioupiou": ("Pioupiou / OpenWindMap", _check_pioupiou),
    "openaip": ("OpenAIP", _check_openaip),
    "openair": ("OpenAir local", _check_openair),
    "biodivsports": ("Biodiv'Sports", _check_biodiv),
}


# ---------------------------------------------------------------------------------------------
# Garde-fou OpenAIP (Cloudflare) : horodatage du dernier appel partagé entre exécutions
# ---------------------------------------------------------------------------------------------
def default_guard_path() -> Path:
    return Path(tempfile.gettempdir()) / "paraglide-check-sources-openaip.ts"


def _openaip_wait(guard: Path | None) -> float:
    """Secondes restantes avant d'avoir le droit d'appeler OpenAIP (0 si autorisé)."""
    if guard is None or not guard.exists():
        return 0.0
    try:
        last = float(guard.read_text().strip())
    except (OSError, ValueError):
        return 0.0
    return max(0.0, OPENAIP_MIN_INTERVAL_S - (time.time() - last))


def _openaip_mark(guard: Path | None) -> None:
    if guard is None:
        return
    with contextlib.suppress(OSError):
        guard.write_text(f"{time.time():.0f}")


# ---------------------------------------------------------------------------------------------
def _secrets(s: Settings) -> list[str]:
    vals = [s.openaip_api_key, s.ffvl_api_key, s.open_meteo_api_key, s.spotair_api_key, s.meteo_parapente_api_key]
    return [v for v in vals if v]


def _sanitize(text: str, secrets: list[str]) -> str:
    for sec in secrets:
        text = text.replace(sec, "***")
    return redact(text)


def _truncate(body):
    """Réduit une réponse volumineuse : liste principale limitée à FIXTURE_KEEP_ITEMS éléments."""
    if isinstance(body, dict):
        for k in ("features", "items", "data", "results"):
            v = body.get(k)
            if isinstance(v, list) and len(v) > FIXTURE_KEEP_ITEMS:
                body = dict(body)
                body[k] = v[:FIXTURE_KEEP_ITEMS]
                body["_truncated"] = {"key": k, "kept": FIXTURE_KEEP_ITEMS, "total": len(v)}
                return body
    if isinstance(body, list) and len(body) > FIXTURE_KEEP_ITEMS:
        return body[:FIXTURE_KEEP_ITEMS]
    return body


def save_fixtures(results: list[CheckResult], directory: Path, secrets: list[str]) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for r in results:
        bodies = [resp for resp in r.responses if resp.status_code < 300 or resp.status_code >= 400]
        for i, resp in enumerate(bodies):
            suffix = "" if len(bodies) == 1 else f"_{i + 1}"
            path = directory / f"{r.key.replace('-', '_')}{suffix}.json"
            text = _sanitize(resp.text, secrets)
            try:
                body = json.loads(text)
            except ValueError:
                path = path.with_suffix(".txt")
                path.write_text(text[:MAX_FIXTURE_BYTES], encoding="utf-8")
                written.append(path)
                continue
            if len(text.encode()) > MAX_FIXTURE_BYTES:
                text = json.dumps(_truncate(body), ensure_ascii=False)
            path.write_text(text, encoding="utf-8")
            written.append(path)
    return written


async def run_checks(
    settings: Settings,
    client: httpx.AsyncClient,
    bbox: tuple[float, float, float, float] = ANNECY_BBOX,
    only: list[str] | None = None,
    skip: list[str] | None = None,
    openaip_guard: Path | None = None,
) -> list[CheckResult]:
    rec = _Recorder()
    client.event_hooks.setdefault("response", []).append(rec.hook)
    results: list[CheckResult] = []
    try:
        for key, (name, fn) in CHECKS.items():
            if (only and key not in only) or (skip and key in skip):
                continue
            expected = True
            if key == "openaip" and not settings.openaip_api_key:
                results.append(CheckResult(key, name, "DÉSACTIVÉ", False, detail="clé OPENAIP_API_KEY absente"))
                continue
            if key == "openaip":
                wait = _openaip_wait(openaip_guard)
                if wait > 0:
                    detail = (
                        f"clé configurée ; dernier appel trop récent (réessayer dans {wait:.0f} s, "
                        "limitation Cloudflare : 1 appel / 5 min)"
                    )
                    results.append(CheckResult(key, name, "IGNORÉ", False, detail=detail))
                    continue
                _openaip_mark(openaip_guard)
            rec.responses = []
            t0 = time.perf_counter()
            try:
                count, detail = await fn(settings, client, bbox)
                status = "OK"
            except ProviderDisabled as e:
                count, detail, status, expected = None, str(e), "DÉSACTIVÉ", False
            except ProviderError as e:
                count, detail, status = None, str(e), "ÉCHEC"
            except Exception as e:  # erreur de parseur : on la rapporte précisément
                count, detail, status = None, f"{type(e).__name__}: {e}", "ÉCHEC"
            dt = time.perf_counter() - t0
            http = "+".join(str(r.status_code) for r in rec.responses) or "-"
            results.append(
                CheckResult(
                    key,
                    name,
                    status,
                    expected,
                    http=http,
                    count=count,
                    duration_s=dt,
                    detail=_sanitize(detail, _secrets(settings)),
                    responses=list(rec.responses),
                )
            )
    finally:
        client.event_hooks["response"].remove(rec.hook)
    return results


def format_table(results: list[CheckResult]) -> str:
    headers = ("Source", "État", "HTTP", "Éléments", "Durée", "Détail / erreur")
    rows = [
        (
            r.name,
            r.status,
            r.http,
            "-" if r.count is None else str(r.count),
            f"{r.duration_s:.2f} s" if r.duration_s else "-",
            r.detail,
        )
        for r in results
    ]
    widths = [max(len(h), *(len(row[i]) for row in rows)) if rows else len(h) for i, h in enumerate(headers[:-1])]
    lines = []
    fmt = " | ".join(f"{{:<{w}}}" for w in widths) + " | {}"
    lines.append(fmt.format(*headers))
    lines.append("-+-".join("-" * w for w in widths) + "-+-" + "-" * 40)
    for row in rows:
        lines.append(fmt.format(*row))
    return "\n".join(lines)


def _parse_list(v: str | None) -> list[str] | None:
    if not v:
        return None
    out = [x.strip() for x in v.split(",") if x.strip()]
    bad = [x for x in out if x not in SOURCE_KEYS]
    if bad:
        raise SystemExit(f"source(s) inconnue(s) : {', '.join(bad)} (valeurs : {', '.join(SOURCE_KEYS)})")
    return out


async def _amain(args: argparse.Namespace) -> int:
    settings = get_settings()
    bbox = tuple(float(x) for x in args.bbox.split(",")) if args.bbox else ANNECY_BBOX
    client = make_client(max(settings.http_timeout_s, args.timeout))
    try:
        results = await run_checks(
            settings, client, bbox, _parse_list(args.only), _parse_list(args.skip), default_guard_path()
        )
    finally:
        await client.aclose()
    print(f"Vérification des sources — {datetime.now(UTC):%Y-%m-%d %H:%M} UTC — bbox {','.join(map(str, bbox))}")
    print(f"Clé OpenAIP : {'configurée' if settings.openaip_api_key else 'absente'}")
    print(format_table(results))
    if args.save_fixtures:
        written = save_fixtures(results, Path(args.save_fixtures), _secrets(settings))
        print(f"{len(written)} réponse(s) enregistrée(s) dans {args.save_fixtures}")
    failed = [r for r in results if r.failed]
    if failed:
        print("ÉCHEC : " + ", ".join(r.name for r in failed))
        return 1
    print("Toutes les sources attendues répondent.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.check_sources", description=__doc__.split("\n")[0])
    p.add_argument("--save-fixtures", metavar="DIR", help="enregistre les réponses brutes (JSON) dans DIR")
    p.add_argument("--only", help=f"sources à vérifier, séparées par des virgules ({', '.join(SOURCE_KEYS)})")
    p.add_argument("--skip", help="sources à ignorer, séparées par des virgules")
    p.add_argument("--bbox", help="min_lon,min_lat,max_lon,max_lat (défaut : Annecy)")
    p.add_argument("--timeout", type=float, default=20.0, help="délai HTTP en secondes (défaut 20)")
    args = p.parse_args(argv)
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    sys.exit(main())
