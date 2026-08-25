from datetime import timedelta

import pytest
from sqlalchemy import select

from reachsocial.catalog import Catalog, InputField, ProviderConfig, ServiceDefinition
from reachsocial.errors import (
    DisabledService,
    IdempotencyConflict,
    InvalidInput,
    LimitExceeded,
    ProviderUnavailable,
    UnknownService,
)
from reachsocial.errors import TestCapacityReached as CapacityReached
from reachsocial.models import (
    ClientService,
    IdempotencyRecord,
    ProviderAttempt,
    RequestLog,
)
from reachsocial.providers import ProviderResult
from reachsocial.runtime import RuntimeState
from reachsocial.services import ExecutionService, utcnow_naive


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
async def test_expired_idempotency_record_is_replaced_without_a_duplicate_key(
    session, client, catalog
) -> None:
    executor = ExecutionService(catalog, RuntimeState())
    first = await executor.execute(
        session,
        client=client,
        service_id="instagram.profile",
        input_data={"url": "https://instagram.com/example"},
        idempotency_key="replace-expired",
    )
    record = session.scalar(
        select(IdempotencyRecord).where(IdempotencyRecord.key == "replace-expired")
    )
    assert record is not None
    record.expires_at = utcnow_naive() - timedelta(seconds=1)
    session.commit()

    replacement = await executor.execute(
        session,
        client=client,
        service_id="instagram.profile",
        input_data={"url": "https://instagram.com/example"},
        idempotency_key="replace-expired",
    )

    records = list(
        session.scalars(
            select(IdempotencyRecord).where(
                IdempotencyRecord.key == "replace-expired"
            )
        )
    )
    assert first["request_id"] != replacement["request_id"]
    assert replacement["cached"] is True
    assert len(records) == 1


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


def test_strict_input_defaults_and_ranges(catalog) -> None:
    definition = ServiceDefinition(
        id="x.feed",
        title="X Feed",
        platform="X",
        description="Test",
        response_shape="feed",
        input_fields=[
            InputField(name="url", description="URL", format="url"),
            InputField(
                name="max_items",
                description="Limit",
                required=False,
                format="integer",
                default=20,
                minimum=1,
                maximum=100,
            ),
        ],
        provider=ProviderConfig(name="mock"),
        enabled=True,
    )
    payload = {"url": "twitter.com/example"}
    ExecutionService.validate_input(definition, payload)
    assert payload == {"url": "https://x.com/example", "max_items": 20}
    with pytest.raises(InvalidInput, match="Unknown input"):
        ExecutionService.validate_input(definition, {"url": "x.com/example", "extra": True})
    with pytest.raises(InvalidInput, match="at most 100"):
        ExecutionService.validate_input(
            definition, {"url": "x.com/example", "max_items": 101}
        )
    with pytest.raises(InvalidInput, match="must be an integer"):
        ExecutionService.validate_input(
            definition, {"url": "x.com/example", "max_items": 1.5}
        )


@pytest.mark.asyncio
async def test_private_service_requires_explicit_entitlement(session, client) -> None:
    definition = ServiceDefinition(
        id="x.profile",
        title="X Profile",
        platform="X",
        description="Private test",
        input_fields=[InputField(name="url", description="URL", format="url")],
        provider=ProviderConfig(name="mock"),
        enabled=True,
        public=False,
    )
    executor = ExecutionService(Catalog(services=[definition]), RuntimeState())
    with pytest.raises(UnknownService):
        await executor.execute(
            session,
            client=client,
            service_id="x.profile",
            input_data={"url": "https://x.com/example"},
        )
    session.add(ClientService(client_id=client.id, service_id="x.profile", enabled=True))
    session.commit()
    response = await executor.execute(
        session,
        client=client,
        service_id="x.profile",
        input_data={"url": "https://x.com/example"},
    )
    assert response["data"]["profile"]["handle"] == "example"


@pytest.mark.asyncio
async def test_retries_only_retryable_provider_failures(session, client, catalog, monkeypatch) -> None:
    definition = catalog.by_id("instagram.profile").model_copy(update={"retries": 1})
    attempts = 0

    class FlakyAdapter:
        async def execute(self, service, input_data):  # type: ignore[no-untyped-def]
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ProviderUnavailable("temporary")
            return ProviderResult(
                data={"profile": {"handle": "example"}},
                upstream_cost_microusd=1880,
                provider_units=1,
                provider_unit_cost_microusd=1880,
            )

    monkeypatch.setattr("reachsocial.services.adapter_for", lambda _service: FlakyAdapter())
    executor = ExecutionService(Catalog(services=[definition]), RuntimeState())
    response = await executor.execute(
        session,
        client=client,
        service_id=definition.id,
        input_data={"url": "https://instagram.com/example"},
    )
    recorded = list(session.scalars(select(ProviderAttempt).order_by(ProviderAttempt.id)))
    assert response["status"] == "success"
    assert attempts == 2
    assert [row.status for row in recorded] == ["failed", "succeeded"]
    assert recorded[-1].upstream_cost_microusd == 1880


@pytest.mark.asyncio
async def test_public_cost_cap_counts_actual_provider_cost(session, client, catalog) -> None:
    client.billing_mode = "external"
    session.add(
        ProviderAttempt(
            request_id="req_existing",
            service_id="instagram.profile",
            provider="mock",
            status="succeeded",
            upstream_cost_microusd=4_999_000,
            public_test=True,
        )
    )
    session.commit()
    definition = catalog.by_id("instagram.profile").model_copy(
        update={"estimated_upstream_cost_microusd": 2000, "retries": 0}
    )
    executor = ExecutionService(Catalog(services=[definition]), RuntimeState())
    with pytest.raises(CapacityReached):
        await executor.execute(
            session,
            client=client,
            service_id=definition.id,
            input_data={"url": "https://instagram.com/example"},
        )


@pytest.mark.asyncio
async def test_concurrent_idempotent_calls_execute_provider_once(
    session, client, catalog, monkeypatch
) -> None:
    import asyncio

    from sqlalchemy.orm import sessionmaker

    calls = 0

    class SlowAdapter:
        async def execute(self, service, input_data):  # type: ignore[no-untyped-def]
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.02)
            return ProviderResult(
                data={"profile": {"handle": "example"}}, upstream_cost_microusd=0
            )

    monkeypatch.setattr("reachsocial.services.adapter_for", lambda _service: SlowAdapter())
    executor = ExecutionService(catalog, RuntimeState())
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)

    async def execute_once():
        with factory() as task_session:
            task_client = task_session.get(type(client), client.id)
            return await executor.execute(
                task_session,
                client=task_client,
                service_id="instagram.profile",
                input_data={"url": "https://instagram.com/example"},
                idempotency_key="concurrent-one",
            )

    first, second = await asyncio.gather(execute_once(), execute_once())
    assert calls == 1
    assert first == second
