from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from .errors import RateLimitExceeded


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
        self.public_request_times: dict[str, deque[float]] = defaultdict(deque)
        self.public_upstream_reserved_microusd = 0
        self.idempotency_locks: dict[str, asyncio.Lock] = {}
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
                raise RateLimitExceeded("Client request rate limit exceeded")
            if self.in_flight[client_id] >= concurrency:
                raise RateLimitExceeded("Client concurrency limit exceeded")
            if self.provider_in_flight[provider] >= provider_concurrency:
                raise RateLimitExceeded("Provider concurrency limit exceeded")
            window.append(now)
            self.in_flight[client_id] += 1
            self.provider_in_flight[provider] += 1

    async def release(self, client_id: int, provider: str) -> None:
        async with self._lock:
            self.in_flight[client_id] = max(0, self.in_flight[client_id] - 1)
            self.provider_in_flight[provider] = max(0, self.provider_in_flight[provider] - 1)

    async def record_public_request(self, identities: list[str], per_minute: int) -> None:
        async with self._lock:
            now = time.monotonic()
            for identity in identities:
                window = self.public_request_times[identity]
                while window and window[0] <= now - 60:
                    window.popleft()
                if len(window) >= per_minute:
                    raise RateLimitExceeded("Public test request rate limit exceeded")
            for identity in identities:
                self.public_request_times[identity].append(now)

    async def reserve_public_upstream_cost(
        self, committed_microusd: int, estimate_microusd: int, cap_microusd: int
    ) -> None:
        async with self._lock:
            if (
                committed_microusd
                + self.public_upstream_reserved_microusd
                + estimate_microusd
                > cap_microusd
            ):
                from .errors import TestCapacityReached

                raise TestCapacityReached("The public test capacity has been reached for today")
            self.public_upstream_reserved_microusd += estimate_microusd

    async def release_public_upstream_cost(self, estimate_microusd: int) -> None:
        async with self._lock:
            self.public_upstream_reserved_microusd = max(
                0, self.public_upstream_reserved_microusd - estimate_microusd
            )

    async def acquire_idempotency(self, identity: str) -> asyncio.Lock:
        async with self._lock:
            lock = self.idempotency_locks.setdefault(identity, asyncio.Lock())
        await lock.acquire()
        return lock

    def get_cached(self, key: str) -> dict[str, Any] | None:
        entry = self.cache.get(key)
        if not entry or entry.expires_at <= time.monotonic():
            self.cache.pop(key, None)
            return None
        return entry.value

    def set_cached(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        if ttl_seconds > 0:
            self.cache[key] = CacheEntry(expires_at=time.monotonic() + ttl_seconds, value=value)
