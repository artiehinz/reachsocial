from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from .errors import LimitExceeded


@dataclass
class CacheEntry:
    expires_at: float
    value: dict[str, Any]


class RuntimeState:
    """Intentionally disposable MVP cache, rate, and concurrency state."""

    def __init__(self) -> None:
        self.cache: dict[str, CacheEntry] = {}
        self.request_times: dict[int, deque[float]] = defaultdict(deque)
        self.in_flight: dict[int, int] = defaultdict(int)
        self.provider_in_flight: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def acquire(
        self,
        client_id: int,
        *,
        provider: str,
        per_minute: int,
        concurrency: int,
        provider_concurrency: int,
    ) -> None:
        async with self._lock:
            now = time.monotonic()
            window = self.request_times[client_id]
            while window and window[0] <= now - 60:
                window.popleft()
            if len(window) >= per_minute:
                raise LimitExceeded("Client request rate limit exceeded")
            if self.in_flight[client_id] >= concurrency:
                raise LimitExceeded("Client concurrency limit exceeded")
            if self.provider_in_flight[provider] >= provider_concurrency:
                raise LimitExceeded("Provider concurrency limit exceeded")
            window.append(now)
            self.in_flight[client_id] += 1
            self.provider_in_flight[provider] += 1

    async def release(self, client_id: int, provider: str) -> None:
        async with self._lock:
            self.in_flight[client_id] = max(0, self.in_flight[client_id] - 1)
            self.provider_in_flight[provider] = max(0, self.provider_in_flight[provider] - 1)

    def get_cached(self, key: str) -> dict[str, Any] | None:
        entry = self.cache.get(key)
        if not entry or entry.expires_at <= time.monotonic():
            self.cache.pop(key, None)
            return None
        return entry.value

    def set_cached(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        if ttl_seconds > 0:
            self.cache[key] = CacheEntry(expires_at=time.monotonic() + ttl_seconds, value=value)
