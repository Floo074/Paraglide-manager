"""Cache mémoire à durée de vie (TTL), sûr pour asyncio (pas de dépendance externe)."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from typing import Any


class TTLCache:
    def __init__(self, ttl_s: float, max_items: int = 2048) -> None:
        self.ttl_s = ttl_s
        self.max_items = max_items
        self._data: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._locks: dict[Hashable, asyncio.Lock] = {}

    def get(self, key: Hashable) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires, value = item
        if expires < time.monotonic():
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: Hashable, value: Any, ttl_s: float | None = None) -> None:
        self._data[key] = (time.monotonic() + (self.ttl_s if ttl_s is None else ttl_s), value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_items:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)

    async def get_or_set(
        self, key: Hashable, factory: Callable[[], Awaitable[Any]], ttl_s: float | None = None
    ) -> Any:
        """Renvoie la valeur en cache ou l'obtient via `factory` (un seul appel concurrent par clé)."""
        value = self.get(key)
        if value is not None:
            return value
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            value = self.get(key)
            if value is None:
                value = await factory()
                if value is not None:
                    self.set(key, value, ttl_s)
        self._locks.pop(key, None)
        return value
