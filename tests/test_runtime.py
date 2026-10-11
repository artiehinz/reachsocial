import asyncio
import time

from reachsocial.runtime import RuntimeState


def test_runtime_cache_evicts_least_recently_used_entries() -> None:
    runtime = RuntimeState(cache_max_entries=2, cache_max_bytes=1_000)
    runtime.set_cached("first", {"value": 1}, 60)
    runtime.set_cached("second", {"value": 2}, 60)
    assert runtime.get_cached("first") == {"value": 1}
    runtime.set_cached("third", {"value": 3}, 60)

    assert runtime.get_cached("first") == {"value": 1}
    assert runtime.get_cached("second") is None
    assert runtime.get_cached("third") == {"value": 3}


def test_runtime_cache_rejects_values_larger_than_its_budget() -> None:
    runtime = RuntimeState(cache_max_entries=2, cache_max_bytes=16)
    runtime.set_cached("large", {"value": "too large"}, 60)
    assert runtime.get_cached("large") is None


def test_runtime_prunes_idle_idempotency_locks() -> None:
    async def run() -> None:
        runtime = RuntimeState(idle_seconds=60)
        lock = await runtime.acquire_idempotency("client:service:key")
        lock.release()
        runtime.idempotency_locks["client:service:key"].last_used_at = (
            time.monotonic() - runtime.idle_seconds - 1
        )
        await runtime.prune()
        assert runtime.idempotency_locks == {}

    asyncio.run(run())
