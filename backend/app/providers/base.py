"""Socle commun des fournisseurs de données : erreurs, état de santé, client HTTP."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

USER_AGENT = "ParaglideManager/0.1 (flight planning decision aid; contact: see repository)"

# paramètres d'URL / champs pouvant porter un secret : jamais recopiés dans un message d'erreur
_SECRET_RE = re.compile(r"(?i)((?:api[_-]?key|apikey|key|token|x-openaip-api-key)[\"']?\s*[=:]\s*[\"']?)[^&\s\"',;]+")


class ProviderError(Exception):
    """Erreur d'un fournisseur (réseau, HTTP, format).

    `http_status` : code HTTP de la réponse en échec (None pour une erreur réseau ou de format).
    """

    http_status: int | None = None


class ProviderDisabled(ProviderError):
    """Fournisseur désactivé (clé absente, pas d'accord…)."""


def redact(text: str) -> str:
    """Masque les valeurs de clés / jetons éventuellement présentes dans un texte (URL, corps d'erreur)."""
    return _SECRET_RE.sub(r"\1***", text)


@dataclass
class SourceState:
    name: str
    kind: str  # forecast | sites | beacons | airspaces | elevation | sensitive_areas
    url: str | None
    requires_api_key: bool = False
    api_key_configured: bool = False
    disabled_message: str | None = None  # non None = fournisseur désactivé
    last_success: float | None = None
    last_failure: float | None = None
    last_error: str | None = None
    last_mode: str | None = None  # live | mock
    extra: dict = field(default_factory=dict)
    # quota / limitation de débit (HTTP 429) : aucun appel avant cette échéance (time.monotonic())
    blocked_until: float | None = None
    blocked_reason: str | None = None

    def record_success(self) -> None:
        self.last_success = time.monotonic()
        self.last_error = None
        self.last_mode = "live"

    def record_failure(self, err: str) -> None:
        self.last_failure = time.monotonic()
        self.last_error = redact(err)[:300]

    def block(self, seconds: float, reason: str) -> None:
        """Suspend la source `seconds` secondes (quota atteint) : pas de nouvel appel avant l'échéance."""
        until = time.monotonic() + max(0.0, seconds)
        if self.blocked_until is None or until > self.blocked_until:
            self.blocked_until = until
            self.blocked_reason = redact(reason)[:300]

    def blocked(self) -> bool:
        return self.blocked_until is not None and time.monotonic() < self.blocked_until

    def recently_failed(self, retry_after_s: float) -> bool:
        if self.blocked():
            return True
        return (
            self.last_failure is not None
            and (self.last_success is None or self.last_failure > self.last_success)
            and time.monotonic() - self.last_failure < retry_after_s
        )


def make_client(timeout_s: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s, connect=min(timeout_s, 5.0)),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        follow_redirects=True,
    )


def _http_error(r: httpx.Response) -> ProviderError:
    """Message d'erreur précis : code HTTP + motif renvoyé par l'API (`reason`, `message`…) si JSON."""
    detail = ""
    try:
        body = r.json()
    except (ValueError, json.JSONDecodeError):
        body = None
    if isinstance(body, dict):
        for k in ("reason", "message", "detail", "error"):
            v = body.get(k)
            if isinstance(v, str) and v:
                detail = v
                break
    if not detail:
        detail = r.text[:200].replace("\n", " ").strip()
    msg = f"HTTP {r.status_code}"
    if r.status_code == 429:
        msg += " (quota / limitation de débit)"
        ra = r.headers.get("retry-after")
        if ra:
            msg += f", réessayer dans {ra} s"
    if detail:
        msg += f" : {detail}"
    err = ProviderError(redact(msg))
    err.http_status = r.status_code
    return err


async def get_json(client: httpx.AsyncClient, url: str, params: dict | None = None, headers: dict | None = None):
    try:
        r = await client.get(url, params=params, headers=headers)
    except httpx.HTTPError as e:  # réseau, timeout, proxy…
        raise ProviderError(redact(f"{type(e).__name__}: {e}")) from e
    if r.status_code != 200:
        raise _http_error(r)
    try:
        return r.json()
    except ValueError as e:
        err = ProviderError(f"réponse non JSON : {redact(r.text[:120])!r}")
        err.http_status = r.status_code
        raise err from e


async def get_text(client: httpx.AsyncClient, url: str, params: dict | None = None) -> str:
    try:
        r = await client.get(url, params=params)
    except httpx.HTTPError as e:
        raise ProviderError(redact(f"{type(e).__name__}: {e}")) from e
    if r.status_code != 200:
        raise _http_error(r)
    return r.text


def now_utc() -> datetime:
    return datetime.now(UTC)
