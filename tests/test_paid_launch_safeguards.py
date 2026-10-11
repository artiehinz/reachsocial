from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from reachsocial.api import _recover_async_payment, _recover_sync_payment
from reachsocial.catalog import ProviderConfig
from reachsocial.config import Settings
from reachsocial.credit_budget import finalize, reserve, summary
from reachsocial.models import (
    AsyncJob,
    IdempotencyRecord,
    PaymentReceipt,
    ProviderAttempt,
    ProviderCreditReservation,
)
from reachsocial.payments import PUBLIC_X402_CLIENT_NAME
from reachsocial.services import utcnow_naive


def test_credit_reservation_holds_retries_then_records_actual_use(session, client, catalog) -> None:
    service = catalog.by_id("instagram.profile").model_copy(
        update={"provider": ProviderConfig(name="scrapecreators"), "retries": 1}
    )
    settings = Settings(scrapecreators_credit_balance=5, scrapecreators_credit_reserve=1)

    assert reserve(session, payment_id="payment-one", service=service, settings=settings)
    assert summary(session, settings)["public_available"] == 2
    session.add(
        PaymentReceipt(
            payment_id="payment-one",
            service_id=service.id,
            amount_cents=5,
            network="eip155:8453",
            status="settled",
            request_id="req_paid",
        )
    )
    session.add(
        ProviderAttempt(
            request_id="req_paid",
            service_id=service.id,
            provider="scrapecreators",
            status="succeeded",
            provider_units=1,
            provider_unit_cost_microusd=1880,
            upstream_cost_microusd=1880,
            public_test=True,
        )
    )
    session.commit()

    finalize(session, "payment-one")
    reservation = session.scalar(
        select(ProviderCreditReservation).where(
            ProviderCreditReservation.payment_id == "payment-one"
        )
    )
    assert reservation.status == "consumed"
    assert reservation.reserved_units == 0
    assert reservation.consumed_units == 1
    assert summary(session, settings)["public_available"] == 3


def test_credit_reservation_refuses_capacity_below_internal_reserve(session, catalog) -> None:
    service = catalog.by_id("instagram.profile").model_copy(
        update={"provider": ProviderConfig(name="scrapecreators")}
    )
    settings = Settings(scrapecreators_credit_balance=10, scrapecreators_credit_reserve=10)

    assert not reserve(session, payment_id="payment-full", service=service, settings=settings)
    assert session.scalar(select(ProviderCreditReservation)) is None


def _public_client(session, client):
    client.name = PUBLIC_X402_CLIENT_NAME
    client.billing_mode = "external"
    session.commit()
    return client


def test_paid_sync_recovery_returns_only_matching_input(session, client) -> None:
    client = _public_client(session, client)
    response = {"request_id": "req_paid", "service": "instagram.profile", "status": "success"}
    session.add(
        IdempotencyRecord(
            client_id=client.id,
            service_id="instagram.profile",
            key="retry-key",
            input_hash="098333e7e8c1f4f52748cb1c68b3e4fd8376de47e9f10d7f19a3fbb7e83758f6",
            response_json=response,
            expires_at=utcnow_naive() + timedelta(hours=1),
        )
    )
    session.add(
        PaymentReceipt(
            payment_id="payment-sync",
            service_id="instagram.profile",
            amount_cents=5,
            network="eip155:8453",
            status="settled",
            request_id="req_paid",
        )
    )
    session.commit()

    matching_input = {"url": "https://instagram.com/openai"}
    # Stable hashes are deliberate: the recovery key never authorizes changed input.
    from reachsocial.services import stable_hash

    row = session.scalar(select(IdempotencyRecord).where(IdempotencyRecord.key == "retry-key"))
    row.input_hash = stable_hash(matching_input)
    session.commit()
    recovered = _recover_sync_payment(
        session,
        service_id="instagram.profile",
        idempotency_key="retry-key",
        input_data=matching_input,
    )
    assert recovered and recovered[0] == response
    with pytest.raises(HTTPException, match="Idempotency key"):
        _recover_sync_payment(
            session,
            service_id="instagram.profile",
            idempotency_key="retry-key",
            input_data={"url": "https://instagram.com/other"},
        )


def test_paid_async_recovery_survives_a_lost_job_token(session, client) -> None:
    client = _public_client(session, client)
    from reachsocial.services import stable_hash

    input_data = {"url": "https://linkedin.com/in/example"}
    job = AsyncJob(
        job_id="job_paid",
        client_id=client.id,
        service_id="linkedin.profile",
        provider="apify",
        status="queued",
        input_json=input_data,
        input_hash=stable_hash(input_data),
        idempotency_key="job-retry-key",
        expires_at=utcnow_naive() + timedelta(days=30),
    )
    session.add(job)
    session.add(
        PaymentReceipt(
            payment_id="payment-async",
            service_id="linkedin.profile",
            amount_cents=10,
            network="eip155:8453",
            status="settled",
            job_id="job_paid",
        )
    )
    session.commit()

    recovered = _recover_async_payment(
        session,
        service_id="linkedin.profile",
        idempotency_key="job-retry-key",
        input_data=input_data,
    )
    assert recovered and recovered[0].job_id == "job_paid"
