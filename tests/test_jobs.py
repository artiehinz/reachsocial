from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from reachsocial.catalog import Catalog, InputField, ProviderConfig, ServiceDefinition
from reachsocial.errors import CreditUnavailable, IdempotencyConflict, UnauthorizedJob
from reachsocial.jobs import (
    JobWorker,
    authorize_job,
    claim_credit,
    consume_credit,
    submit_job,
)
from reachsocial.models import AsyncJob, PaymentReceipt, ProviderAttempt, ServiceCredit
from reachsocial.providers import ProviderResult
from reachsocial.runtime import RuntimeState
from reachsocial.security import verify_api_key
from reachsocial.services import ExecutionService, utcnow_naive


def async_catalog() -> Catalog:
    return Catalog(
        services=[
            ServiceDefinition(
                id="x.feed",
                title="X Feed",
                platform="X",
                description="Latest posts",
                execution="async",
                response_shape="feed",
                input_fields=[InputField(name="url", description="URL", format="url")],
                provider=ProviderConfig(name="mock"),
                enabled=True,
                public=True,
                price_cents=10,
                estimated_upstream_cost_microusd=2000,
            )
        ]
    )


def test_anonymous_job_token_is_hashed_and_authorizes(session, client) -> None:
    executor = ExecutionService(async_catalog(), RuntimeState())
    job, token = submit_job(
        session,
        executor=executor,
        client=client,
        service_id="x.feed",
        input_data={"url": "https://x.com/example"},
        anonymous=True,
        payment_id="payment-one",
    )
    assert token is not None and token.startswith("rs_job_")
    assert token not in str(job.access_token_hash)
    assert verify_api_key(token, job.access_token_hash or "")
    with pytest.raises(UnauthorizedJob):
        authorize_job(job, client=None, job_token="wrong")
    authorize_job(job, client=None, job_token=token)


def test_b2b_job_idempotency_replays_only_matching_input(session, client) -> None:
    executor = ExecutionService(async_catalog(), RuntimeState())
    first, _ = submit_job(
        session,
        executor=executor,
        client=client,
        service_id="x.feed",
        input_data={"url": "https://x.com/example"},
        anonymous=False,
        idempotency_key="job-request-one",
    )
    replay, token = submit_job(
        session,
        executor=executor,
        client=client,
        service_id="x.feed",
        input_data={"url": "https://x.com/example"},
        anonymous=False,
        idempotency_key="job-request-one",
    )
    assert replay.job_id == first.job_id
    assert token is None
    with pytest.raises(IdempotencyConflict):
        submit_job(
            session,
            executor=executor,
            client=client,
            service_id="x.feed",
            input_data={"url": "https://x.com/different"},
            anonymous=False,
            idempotency_key="job-request-one",
        )


def test_paid_provider_failure_issues_one_atomic_service_credit(session, client) -> None:
    executor = ExecutionService(async_catalog(), RuntimeState())
    job, token = submit_job(
        session,
        executor=executor,
        client=client,
        service_id="x.feed",
        input_data={"url": "https://x.com/example"},
        anonymous=True,
        payment_id="payment-two",
    )
    session.add(
        PaymentReceipt(
            payment_id="payment-two",
            service_id="x.feed",
            amount_cents=10,
            network="eip155:84532",
            status="settled",
            job_id=job.job_id,
        )
    )
    job.status = "failed"
    job.error_code = "provider_timeout"
    job.error_message = "Provider timed out"
    job.error_retryable = True
    session.commit()
    authorize_job(job, client=None, job_token=token)
    raw_credit = claim_credit(session, job)
    stored = session.scalar(select(ServiceCredit).where(ServiceCredit.job_id == job.job_id))
    receipt = session.scalar(
        select(PaymentReceipt).where(PaymentReceipt.payment_id == "payment-two")
    )
    assert raw_credit.startswith("rs_credit_")
    assert stored is not None and raw_credit not in stored.token_hash
    assert receipt is not None and receipt.replacement_credit_cents == 10
    with pytest.raises(CreditUnavailable):
        claim_credit(session, job)
    service = async_catalog().by_id("x.feed")
    assert service is not None
    assert consume_credit(session, raw_credit, service) is True
    assert consume_credit(session, raw_credit, service) is False


@pytest.mark.asyncio
async def test_worker_recovers_and_completes_a_durable_job(session, client, monkeypatch) -> None:
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr("reachsocial.jobs.SessionLocal", factory)
    catalog = async_catalog()
    executor = ExecutionService(catalog, RuntimeState())
    job, _ = submit_job(
        session,
        executor=executor,
        client=client,
        service_id="x.feed",
        input_data={"url": "https://x.com/example"},
        anonymous=False,
    )
    job.status = "running"
    job.lease_expires_at = utcnow_naive() - timedelta(seconds=1)
    session.commit()
    worker = JobWorker(catalog, executor)
    assert worker.recover_abandoned() == 1
    claimed = worker._claim()
    assert claimed == job.job_id
    await worker._execute(claimed)
    session.expire_all()
    completed = session.scalar(select(AsyncJob).where(AsyncJob.job_id == job.job_id))
    attempt = session.scalar(select(ProviderAttempt).where(ProviderAttempt.job_id == job.job_id))
    assert completed is not None and completed.status == "succeeded"
    assert completed.result_json["meta"]["schema_version"] == "1.0"
    assert attempt is not None and attempt.status == "succeeded"


@pytest.mark.asyncio
async def test_worker_resumes_the_persisted_provider_run(session, client, monkeypatch) -> None:
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr("reachsocial.jobs.SessionLocal", factory)
    seen_references: list[str | None] = []

    class ResumingAdapter:
        async def execute(self, service, input_data, *, context=None):
            del service, input_data
            seen_references.append(context.existing_reference)
            return ProviderResult(
                data={"profile": None, "items": [], "next_cursor": None, "has_more": False},
                upstream_cost_microusd=2_000,
                provider_reference="run-existing",
            )

    monkeypatch.setattr("reachsocial.services.adapter_for", lambda _service: ResumingAdapter())
    catalog = async_catalog()
    executor = ExecutionService(catalog, RuntimeState())
    job, _ = submit_job(
        session,
        executor=executor,
        client=client,
        service_id="x.feed",
        input_data={"url": "https://x.com/example"},
        anonymous=False,
    )
    job.status = "running"
    job.provider_reference = "run-existing"
    job.lease_expires_at = utcnow_naive() - timedelta(seconds=1)
    session.commit()

    worker = JobWorker(catalog, executor)
    assert worker.recover_abandoned() == 1
    claimed = worker._claim()
    assert claimed == job.job_id
    await worker._execute(claimed)

    session.expire_all()
    completed = session.scalar(select(AsyncJob).where(AsyncJob.job_id == job.job_id))
    assert seen_references == ["run-existing"]
    assert completed is not None and completed.status == "succeeded"
    assert completed.provider_reference == "run-existing"


@pytest.mark.asyncio
async def test_scrapecreators_job_marks_dispatch_before_execution(
    session, client, monkeypatch
) -> None:
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr("reachsocial.jobs.SessionLocal", factory)
    seen_references: list[str | None] = []

    class Adapter:
        async def execute(self, service, input_data, *, context=None):
            del service, input_data
            seen_references.append(context.existing_reference)
            return ProviderResult(
                data={
                    "profile": {
                        "platform": "LinkedIn",
                        "canonical_url": "https://linkedin.com/in/example",
                        "platform_id": "1",
                        "handle": "example",
                        "display_name": "Example",
                        "biography": None,
                        "avatar_url": None,
                        "verified": None,
                        "private": None,
                        "counts": {},
                        "links": [],
                        "fields": {},
                    }
                },
                upstream_cost_microusd=1_880,
                provider_reference="provider-request",
                provider_units=1,
                provider_unit_cost_microusd=1_880,
            )

    monkeypatch.setattr("reachsocial.services.adapter_for", lambda _service: Adapter())
    catalog = Catalog(
        services=[
            ServiceDefinition(
                id="linkedin.profile",
                title="LinkedIn Public Profile",
                platform="LinkedIn",
                description="Profile",
                execution="async",
                input_fields=[InputField(name="url", description="URL", format="url")],
                provider=ProviderConfig(name="scrapecreators"),
                enabled=True,
                public=True,
                cost_verified=True,
                estimated_upstream_cost_microusd=1_880,
                provider_unit_cost_microusd=1_880,
            )
        ]
    )
    executor = ExecutionService(catalog, RuntimeState())
    job, _ = submit_job(
        session,
        executor=executor,
        client=client,
        service_id="linkedin.profile",
        input_data={"url": "https://linkedin.com/in/example"},
        anonymous=False,
    )
    worker = JobWorker(catalog, executor)
    claimed = worker._claim()
    assert claimed == job.job_id
    await worker._execute(claimed)

    assert len(seen_references) == 1
    assert seen_references[0] and seen_references[0].startswith("dispatch:")
    session.expire_all()
    completed = session.scalar(select(AsyncJob).where(AsyncJob.job_id == job.job_id))
    assert completed is not None and completed.status == "succeeded"
    assert completed.provider_reference == "provider-request"


@pytest.mark.asyncio
async def test_worker_never_replays_a_job_after_its_provider_changes(
    session, client, monkeypatch
) -> None:
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr("reachsocial.jobs.SessionLocal", factory)
    calls = 0

    class Adapter:
        async def execute(self, service, input_data, *, context=None):
            nonlocal calls
            del service, input_data, context
            calls += 1
            raise AssertionError("the migrated provider must not execute an old job")

    monkeypatch.setattr("reachsocial.services.adapter_for", lambda _service: Adapter())
    catalog = Catalog(
        services=[
            ServiceDefinition(
                id="linkedin.profile",
                title="LinkedIn Public Profile",
                platform="LinkedIn",
                description="Profile",
                execution="async",
                input_fields=[InputField(name="url", description="URL", format="url")],
                provider=ProviderConfig(name="scrapecreators"),
                enabled=True,
                public=True,
            )
        ]
    )
    executor = ExecutionService(catalog, RuntimeState())
    job, _ = submit_job(
        session,
        executor=executor,
        client=client,
        service_id="linkedin.profile",
        input_data={"url": "https://linkedin.com/in/example"},
        anonymous=False,
    )
    job.provider = "retired_provider"
    session.commit()

    worker = JobWorker(catalog, executor)
    claimed = worker._claim()
    assert claimed == job.job_id
    await worker._execute(claimed)

    session.expire_all()
    completed = session.scalar(select(AsyncJob).where(AsyncJob.job_id == job.job_id))
    assert calls == 0
    assert completed is not None and completed.error_code == "reconciliation_required"


@pytest.mark.asyncio
async def test_worker_persists_run_reference_before_provider_completion(
    session, client, monkeypatch
) -> None:
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr("reachsocial.jobs.SessionLocal", factory)

    class StartingAdapter:
        async def execute(self, service, input_data, *, context=None):
            del service, input_data
            context.persist_reference("run-started")
            from reachsocial.errors import ProviderTimeout

            raise ProviderTimeout("Provider timed out")

    monkeypatch.setattr("reachsocial.services.adapter_for", lambda _service: StartingAdapter())
    catalog = async_catalog()
    executor = ExecutionService(catalog, RuntimeState())
    job, _ = submit_job(
        session,
        executor=executor,
        client=client,
        service_id="x.feed",
        input_data={"url": "https://x.com/example"},
        anonymous=False,
    )

    await JobWorker(catalog, executor)._execute(job.job_id)

    session.expire_all()
    failed = session.scalar(select(AsyncJob).where(AsyncJob.job_id == job.job_id))
    assert failed is not None and failed.status == "failed"
    assert failed.provider_reference == "run-started"
