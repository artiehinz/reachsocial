from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict, defaultdict, deque
from dataclasses import dataclass
from typing import Any

from .errors import RateLimitExceeded


@dataclass
class CacheEntry:
    expires_at: float
    value: dict[str, Any]
    size_bytes: int


@dataclass
class IdempotencyLock:
    lock: asyncio.Lock
    waiters: int = 0
    last_used_at: float = 0


class RuntimeState:
    """Intentionally disposable MVP cache, rate, and concurrency state."""

    def __init__(
        self,
        *,
        cache_max_entries: int = 512,
        cache_max_bytes: int = 33_554_432,
        idle_seconds: int = 900,
    ) -> None:
        self.cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.cache_bytes = 0
        self.cache_max_entries = cache_max_entries
        self.cache_max_bytes = cache_max_bytes
        self.idle_seconds = idle_seconds
        self.request_times: dict[int, deque[float]] = defaultdict(deque)
        self.in_flight: dict[int, int] = defaultdict(int)
        self.provider_in_flight: dict[str, int] = defaultdict(int)
        self.public_request_times: dict[str, deque[float]] = defaultdict(deque)
        self.public_upstream_reserved_microusd = 0
        self.idempotency_locks: dict[str, IdempotencyLock] = {}
        self.public_payments_paused_reason: str | None = None
        self.public_service_payment_pauses: dict[str, str] = {}
        self._lock = asyncio.Lock()

    def pause_public_payments(self, reason: str) -> None:
        self.public_payments_paused_reason = reason

    def resume_public_payments(self) -> None:
        """Clear an automatic pause after every launch guard has passed again."""
        self.public_payments_paused_reason = None

    def replace_public_service_payment_pauses(self, pauses: dict[str, str]) -> None:
        """Replace service-level circuit breakers after a fresh alert check."""
        self.public_service_payment_pauses = dict(pauses)

    def public_service_payment_pause_reason(self, service_id: str) -> str | None:
        return self.public_service_payment_pauses.get(service_id)

    def degraded_public_services(self) -> list[str]:
        return sorted(self.public_service_payment_pauses)

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
            self._prune_locked(now)
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
            self._prune_locked(now)
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
                committed_microusd + self.public_upstream_reserved_microusd + estimate_microusd
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
            now = time.monotonic()
            self._prune_locked(now)
            entry = self.idempotency_locks.setdefault(
                identity, IdempotencyLock(lock=asyncio.Lock(), last_used_at=now)
            )
            entry.waiters += 1
            entry.last_used_at = now
        try:
            await entry.lock.acquire()
        except BaseException:
            async with self._lock:
                entry.waiters = max(0, entry.waiters - 1)
                entry.last_used_at = time.monotonic()
            raise
        async with self._lock:
            entry.waiters = max(0, entry.waiters - 1)
            entry.last_used_at = time.monotonic()
        return entry.lock

    def get_cached(self, key: str) -> dict[str, Any] | None:
        entry = self.cache.get(key)
        if not entry or entry.expires_at <= time.monotonic():
            self._drop_cache_entry(key)
            return None
        self.cache.move_to_end(key)
        return entry.value

    def set_cached(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        if ttl_seconds > 0:
            try:
                size_bytes = len(json.dumps(value, separators=(",", ":"), default=str).encode())
            except (TypeError, ValueError):
                return
            if size_bytes > self.cache_max_bytes:
                return
            self._drop_cache_entry(key)
            self.cache[key] = CacheEntry(
                expires_at=time.monotonic() + ttl_seconds,
                value=value,
                size_bytes=size_bytes,
            )
            self.cache_bytes += size_bytes
            self._prune_cache()

    def _drop_cache_entry(self, key: str) -> None:
        entry = self.cache.pop(key, None)
        if entry is not None:
            self.cache_bytes = max(0, self.cache_bytes - entry.size_bytes)

    def _prune_cache(self) -> None:
        now = time.monotonic()
        for key, entry in list(self.cache.items()):
            if entry.expires_at <= now:
                self._drop_cache_entry(key)
        while self.cache and (
            len(self.cache) > self.cache_max_entries or self.cache_bytes > self.cache_max_bytes
        ):
            self._drop_cache_entry(next(iter(self.cache)))

    def _prune_locked(self, now: float) -> None:
        for identity, window in list(self.request_times.items()):
            while window and window[0] <= now - 60:
                window.popleft()
            if not window and self.in_flight[identity] == 0:
                self.request_times.pop(identity, None)
                self.in_flight.pop(identity, None)
        for identity, window in list(self.public_request_times.items()):
            while window and window[0] <= now - 60:
                window.popleft()
            if not window:
                self.public_request_times.pop(identity, None)
        for provider, count in list(self.provider_in_flight.items()):
            if count == 0:
                self.provider_in_flight.pop(provider, None)
        for identity, entry in list(self.idempotency_locks.items()):
            if (
                not entry.lock.locked()
                and entry.waiters == 0
                and entry.last_used_at <= now - self.idle_seconds
            ):
                self.idempotency_locks.pop(identity, None)

    async def prune(self) -> None:
        self._prune_cache()
        async with self._lock:
            self._prune_locked(time.monotonic())
