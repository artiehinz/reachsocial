import pytest
from sqlalchemy import select

from reachsocial.errors import DisabledService, IdempotencyConflict, LimitExceeded
from reachsocial.models import RequestLog
from reachsocial.runtime import RuntimeState
from reachsocial.services import ExecutionService


@pytest.mark.asyncio
async def test_execute_caches_and_replays_idempotent_response(session, client, catalog) -> None:
    service = ExecutionService(catalog, RuntimeState())
    first = await service.execute(
        session,
        client=client,
        service_id="instagram.profile",
        input_data={"url": "instagram.com/example/?fbclid=gone"},
        idempotency_key="request-1",
    )
    cached = await service.execute(
        session,
        client=client,
        service_id="instagram.profile",
        input_data={"url": "https://instagram.com/example"},
    )
    replay = await service.execute(
        session,
        client=client,
        service_id="instagram.profile",
        input_data={"url": "https://instagram.com/example"},
        idempotency_key="request-1",
    )
    assert first["cached"] is False
    assert cached["cached"] is True
    assert replay == first
    assert len(list(session.scalars(select(RequestLog)))) == 2


@pytest.mark.asyncio
async def test_rejects_disabled_service(session, client, catalog) -> None:
    service = ExecutionService(catalog, RuntimeState())
    with pytest.raises(DisabledService):
        await service.execute(
            session,
            client=client,
            service_id="instagram.post",
            input_data={"url": "https://instagram.com/p/example"},
        )


@pytest.mark.asyncio
async def test_rejects_conflicting_idempotency_key(session, client, catalog) -> None:
    service = ExecutionService(catalog, RuntimeState())
    await service.execute(
        session,
        client=client,
        service_id="instagram.profile",
        input_data={"url": "https://instagram.com/one"},
        idempotency_key="request-1",
    )
    with pytest.raises(IdempotencyConflict):
        await service.execute(
            session,
            client=client,
            service_id="instagram.profile",
            input_data={"url": "https://instagram.com/two"},
            idempotency_key="request-1",
        )


@pytest.mark.asyncio
async def test_enforces_daily_b2b_spend_limit(session, client, catalog) -> None:
    client.billing_mode = "metered"
    client.daily_spend_cents = 5
    session.commit()
    service = ExecutionService(catalog, RuntimeState())
    await service.execute(
        session,
        client=client,
        service_id="instagram.profile",
        input_data={"url": "https://instagram.com/one"},
    )
    with pytest.raises(LimitExceeded, match="daily spend"):
        await service.execute(
            session,
            client=client,
            service_id="instagram.profile",
            input_data={"url": "https://instagram.com/two"},
        )
