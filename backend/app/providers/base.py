"""Socle commun des fournisseurs de données : erreurs, état de santé, client HTTP."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

USER_AGENT = "ParaglideManager/0.1 (+https://github.com/; outil d'aide à la décision vol libre)"


class ProviderError(Exception):
    """Erreur d'un fournisseur (réseau, HTTP, format)."""


class ProviderDisabled(ProviderError):
    """Fournisseur désactivé (clé absente, pas d'accord…)."""


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

    def record_success(self) -> None:
        self.last_success = time.monotonic()
        self.last_error = None
        self.last_mode = "live"

    def record_failure(self, err: str) -> None:
        self.last_failure = time.monotonic()
        self.last_error = err[:300]

    def recently_failed(self, retry_after_s: float) -> bool:
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


async def get_json(client: httpx.AsyncClient, url: str, params: dict | None = None, headers: dict | None = None):
    try:
        r = await client.get(url, params=params, headers=headers)
    except httpx.HTTPError as e:  # réseau, timeout, proxy…
        raise ProviderError(f"{type(e).__name__}: {e}") from e
    if r.status_code != 200:
        detail = r.text[:200].replace("\n", " ")
        raise ProviderError(f"HTTP {r.status_code} : {detail}")
    try:
        return r.json()
    except ValueError as e:
        raise ProviderError(f"réponse non JSON : {r.text[:120]!r}") from e


async def get_text(client: httpx.AsyncClient, url: str, params: dict | None = None) -> str:
    try:
        r = await client.get(url, params=params)
    except httpx.HTTPError as e:
        raise ProviderError(f"{type(e).__name__}: {e}") from e
    if r.status_code != 200:
        raise ProviderError(f"HTTP {r.status_code}")
    return r.text


def now_utc() -> datetime:
    return datetime.now(UTC)
