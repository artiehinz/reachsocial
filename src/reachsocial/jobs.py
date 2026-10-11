from __future__ import annotations

import asyncio
import logging
import secrets
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .catalog import Catalog, ServiceDefinition
from .config import get_settings
from .consumer_contract import response_meta
from .credit_budget import finalize as finalize_credit_reservation
from .db import SessionLocal
from .errors import (
    CreditUnavailable,
    DisabledService,
    IdempotencyConflict,
    JobExpired,
    JobNotFailed,
    ReachSocialError,
    SpendLimitExceeded,
    UnauthorizedJob,
    UnknownService,
)
from .models import AsyncJob, Client, PaymentReceipt, ServiceCredit
from .providers import ProviderExecutionContext
from .security import hash_api_key, verify_api_key
from .services import (
    ExecutionService,
    client_can_access_service,
    stable_hash,
    utcnow_naive,
)

JOB_TOKEN_PREFIX = "rs_job_"
CREDIT_TOKEN_PREFIX = "rs_credit_"


def _new_job_token() -> str:
    return f"{JOB_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def _new_credit_token() -> tuple[str, str]:
    credit_id = secrets.token_hex(6)
    return credit_id, f"{CREDIT_TOKEN_PREFIX}{credit_id}_{secrets.token_urlsafe(32)}"


def _credit_id(token: str) -> str | None:
    if len(token) > 512 or not token.startswith(CREDIT_TOKEN_PREFIX):
        return None
    credit_id, separator, secret = token.removeprefix(CREDIT_TOKEN_PREFIX).partition("_")
    return credit_id if separator and len(credit_id) == 12 and secret else None


def submit_job(
    session: Session,
    *,
    executor: ExecutionService,
    client: Client,
    service_id: str,
    input_data: dict[str, Any],
    anonymous: bool,
    payment_id: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[AsyncJob, str | None]:
    service = executor.catalog.by_id(service_id)
    if service is None:
        raise UnknownService("Unknown service")
    if not service.enabled:
        raise DisabledService("This service is not enabled")
    if not service.is_async:
        raise UnknownService("This service uses the synchronous execute endpoint")
    if not client_can_access_service(session, client, service):
        raise UnknownService("Unknown service")
    executor.validate_input(service, input_data)
    input_hash = stable_hash(input_data)
    if idempotency_key:
        prior = session.scalar(
            select(AsyncJob).where(
                AsyncJob.client_id == client.id,
                AsyncJob.service_id == service.id,
                AsyncJob.idempotency_key == idempotency_key,
            )
        )
        if prior is not None:
            if prior.input_hash != input_hash:
                raise IdempotencyConflict("Idempotency key was already used with different input")
            return prior, None
    executor._enforce_daily_spend(session, client, service)
    if client.billing_mode != "internal":
        start = utcnow_naive().replace(hour=0, minute=0, second=0, microsecond=0)
        reserved = session.scalar(
            select(func.coalesce(func.sum(AsyncJob.price_snapshot_cents), 0)).where(
                AsyncJob.client_id == client.id,
                AsyncJob.status.in_(["queued", "running"]),
                AsyncJob.created_at >= start,
            )
        )
        if int(reserved or 0) + service.price_cents > client.daily_spend_cents:
            raise SpendLimitExceeded("Client daily spend limit exceeded")
    reserved_upstream_microusd = executor._enforce_upstream_cost_cap(session, client, service)
    token = _new_job_token() if anonymous else None
    now = utcnow_naive()
    settings = get_settings()
    job = AsyncJob(
        job_id=f"job_{uuid.uuid4().hex}",
        client_id=client.id,
        service_id=service.id,
        provider=service.provider.name,
        status="queued",
        input_json=input_data,
        input_hash=input_hash,
        idempotency_key=idempotency_key,
        access_token_hash=hash_api_key(token) if token else None,
        payment_id=payment_id,
        price_snapshot_cents=service.price_cents,
        reserved_upstream_cost_microusd=reserved_upstream_microusd,
        expires_at=now
        + timedelta(
            hours=(
                settings.paid_result_retention_hours
                if anonymous and payment_id
                else settings.async_job_retention_hours
            )
        ),
    )
    session.add(job)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if not idempotency_key or anonymous:
            raise
        prior = session.scalar(
            select(AsyncJob).where(
                AsyncJob.client_id == client.id,
                AsyncJob.service_id == service.id,
                AsyncJob.idempotency_key == idempotency_key,
            )
        )
        if prior is None:
            raise
        if prior.input_hash != input_hash:
            raise IdempotencyConflict(
                "Idempotency key was already used with different input"
            ) from None
        return prior, None
    return job, token


def authorize_job(
    job: AsyncJob,
    *,
    client: Client | None,
    job_token: str | None,
) -> None:
    if job_token and len(job_token) > 512:
        raise UnauthorizedJob("Job not found")
    if client is not None and job.client_id == client.id and job.access_token_hash is None:
        return
    if job.access_token_hash and job_token and verify_api_key(job_token, job.access_token_hash):
        return
    raise UnauthorizedJob("Job not found")


def job_payload(job: AsyncJob) -> dict[str, Any]:
    now = utcnow_naive()
    if job.expires_at <= now and job.status not in {"expired"}:
        job.status = "expired"
    payload: dict[str, Any] = {
        "job_id": job.job_id,
        "service": job.service_id,
        "status": job.status,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "expires_at": job.expires_at.isoformat(),
    }
    if job.status == "succeeded":
        payload["result"] = job.result_json
    elif job.status == "failed":
        payload["error"] = {
            "code": job.error_code or "job_failed",
            "message": job.error_message or "The job failed",
            "retryable": bool(job.error_retryable),
            "credit_available": bool(
                job.payment_id
                and job.error_code in {"provider_unavailable", "provider_timeout", "internal_error"}
                and job.credit_claimed_at is None
            ),
        }
    return payload


def claim_credit(session: Session, job: AsyncJob) -> str:
    now = utcnow_naive()
    if job.expires_at <= now:
        raise JobExpired("The job has expired")
    if job.status != "failed":
        raise JobNotFailed("A replacement credit is available only for a failed job")
    if not job.payment_id or job.error_code not in {
        "provider_unavailable",
        "provider_timeout",
        "internal_error",
    }:
        raise CreditUnavailable("This failure is not eligible for a replacement credit")
    if job.credit_claimed_at is not None:
        raise CreditUnavailable("The replacement credit has already been claimed")
    credit_id, raw_token = _new_credit_token()
    settings = get_settings()
    session.add(
        ServiceCredit(
            credit_id=credit_id,
            token_hash=hash_api_key(raw_token),
            job_id=job.job_id,
            service_id=job.service_id,
            amount_cents=job.price_snapshot_cents,
            expires_at=now + timedelta(days=settings.service_credit_expiry_days),
        )
    )
    job.credit_claimed_at = now
    receipt = session.scalar(
        select(PaymentReceipt).where(PaymentReceipt.payment_id == job.payment_id)
    )
    if receipt is not None:
        receipt.replacement_credit_cents = job.price_snapshot_cents
    session.commit()
    return raw_token


def consume_credit(session: Session, raw_token: str, service: ServiceDefinition) -> bool:
    credit_id = _credit_id(raw_token)
    if credit_id is None:
        return False
    credit = session.scalar(
        select(ServiceCredit).where(
            ServiceCredit.credit_id == credit_id,
            ServiceCredit.status == "active",
        )
    )
    now = utcnow_naive()
    if (
        credit is None
        or credit.service_id != service.id
        or credit.amount_cents < service.price_cents
        or credit.expires_at <= now
        or not verify_api_key(raw_token, credit.token_hash)
    ):
        return False
    result = session.execute(
        update(ServiceCredit)
        .where(ServiceCredit.id == credit.id, ServiceCredit.status == "active")
        .values(status="consumed", consumed_at=now)
    )
    session.commit()
    return bool(result.rowcount)


def credit_is_valid(raw_token: str, service_id: str, price_cents: int) -> bool:
    credit_id = _credit_id(raw_token)
    if credit_id is None:
        return False
    now = utcnow_naive()
    with SessionLocal() as session:
        credit = session.scalar(
            select(ServiceCredit).where(
                ServiceCredit.credit_id == credit_id,
                ServiceCredit.status == "active",
                ServiceCredit.service_id == service_id,
                ServiceCredit.amount_cents >= price_cents,
                ServiceCredit.expires_at > now,
            )
        )
        return bool(credit and verify_api_key(raw_token, credit.token_hash))


class JobWorker:
    def __init__(self, catalog: Catalog, executor: ExecutionService) -> None:
        self.catalog = catalog
        self.executor = executor
        self.logger = logging.getLogger("reachsocial")

    def recover_abandoned(self) -> int:
        now = utcnow_naive()
        with SessionLocal() as session:
            result = session.execute(
                update(AsyncJob)
                .where(
                    AsyncJob.status == "running",
                    AsyncJob.lease_expires_at.is_not(None),
                    AsyncJob.lease_expires_at <= now,
                )
                .values(status="queued", lease_expires_at=None)
            )
            session.commit()
            return result.rowcount or 0

    def _claim(self) -> str | None:
        now = utcnow_naive()
        settings = get_settings()
        with SessionLocal() as session:
            job = session.scalar(
                select(AsyncJob)
                .where(AsyncJob.status == "queued", AsyncJob.expires_at > now)
                .order_by(AsyncJob.created_at.asc(), AsyncJob.id.asc())
                .limit(1)
            )
            if job is None:
                session.execute(
                    update(AsyncJob)
                    .where(AsyncJob.status.in_(["queued", "running"]), AsyncJob.expires_at <= now)
                    .values(status="expired", lease_expires_at=None)
                )
                session.commit()
                return None
            job.status = "running"
            job.attempts += 1
            job.started_at = job.started_at or now
            job.lease_expires_at = now + timedelta(seconds=settings.async_job_lease_seconds)
            session.commit()
            return job.job_id

    async def _execute(self, job_id: str) -> None:
        with SessionLocal() as session:
            job = session.scalar(select(AsyncJob).where(AsyncJob.job_id == job_id))
            if job is None:
                return
            service = self.catalog.by_id(job.service_id)
            client = session.get(Client, job.client_id) if job.client_id else None
            if service is None or client is None:
                job.status = "failed"
                job.error_code = "internal_error"
                job.error_message = "The service or client no longer exists"
                job.error_retryable = False
                job.completed_at = utcnow_naive()
                job.lease_expires_at = None
                session.commit()
                return
            if job.provider != service.provider.name:
                job.status = "failed"
                job.error_code = "reconciliation_required"
                job.error_message = "Job provider changed before completion"
                job.error_retryable = False
                job.completed_at = utcnow_naive()
                job.lease_expires_at = None
                session.commit()
                return
            if service.provider.name == "scrapecreators" and job.provider_reference:
                job.status = "failed"
                job.error_code = "reconciliation_required"
                job.error_message = "Provider dispatch is unresolved after worker recovery"
                job.error_retryable = False
                job.completed_at = utcnow_naive()
                job.lease_expires_at = None
                session.commit()
                return
            try:
                if service.provider.name == "scrapecreators":
                    job.provider_reference = f"dispatch:{uuid.uuid4().hex}"
                    session.commit()

                def persist_provider_reference(reference: str) -> None:
                    job.provider_reference = reference
                    job.lease_expires_at = utcnow_naive() + timedelta(
                        seconds=get_settings().async_job_lease_seconds
                    )
                    session.commit()

                result = await self.executor._provider_call(
                    session,
                    request_id=job.job_id,
                    service=service,
                    input_data=dict(job.input_json),
                    public_test=client.billing_mode != "internal",
                    provider_context=ProviderExecutionContext(
                        existing_reference=job.provider_reference,
                        persist_reference=persist_provider_reference,
                    ),
                )
                latency_ms = round(
                    (utcnow_naive() - (job.started_at or utcnow_naive())).total_seconds() * 1000
                )
                response = {
                    "request_id": job.job_id,
                    "service": service.id,
                    "status": "success",
                    "cached": False,
                    "data": result.data,
                    "meta": response_meta(
                        latency_ms=max(0, latency_ms),
                        response_shape=service.response_shape,
                    ),
                }
                job.status = "succeeded"
                job.result_json = response
                job.provider_units = result.provider_units
                job.provider_unit_cost_microusd = result.provider_unit_cost_microusd
                job.upstream_cost_microusd = result.upstream_cost_microusd
                job.provider_reference = result.provider_reference
                job.completed_at = utcnow_naive()
                job.lease_expires_at = None
                job.reserved_upstream_cost_microusd = 0
                self.executor._record(
                    session,
                    request_id=job.job_id,
                    client=client,
                    service=service,
                    status="success",
                    input_hash=job.input_hash,
                    latency_ms=max(0, latency_ms),
                    result=result,
                    charge_client=job.access_token_hash is None,
                )
                session.commit()
            except ReachSocialError as error:
                job.status = "failed"
                job.error_code = error.code
                job.error_message = error.message
                job.error_retryable = error.retryable
                job.provider_reference = (
                    getattr(error, "provider_reference", None) or job.provider_reference
                )
                job.provider_units = int(getattr(error, "provider_units", 0) or 0)
                job.provider_unit_cost_microusd = int(
                    getattr(error, "provider_unit_cost_microusd", 0) or 0
                )
                job.upstream_cost_microusd = int(getattr(error, "upstream_cost_microusd", 0) or 0)
                job.completed_at = utcnow_naive()
                job.lease_expires_at = None
                job.reserved_upstream_cost_microusd = 0
                session.commit()
            except Exception:
                self.logger.exception(
                    "async_job_failed job_id=%s service=%s", job.job_id, job.service_id
                )
                job.status = "failed"
                job.error_code = "internal_error"
                job.error_message = "The job failed unexpectedly"
                job.error_retryable = True
                job.completed_at = utcnow_naive()
                job.lease_expires_at = None
                job.reserved_upstream_cost_microusd = 0
                session.commit()
            finally:
                if job.payment_id:
                    finalize_credit_reservation(session, job.payment_id)

    async def run(self) -> None:
        recovered = self.recover_abandoned()
        if recovered:
            self.logger.warning("async_jobs_recovered count=%s", recovered)
        settings = get_settings()
        while True:
            job_id = self._claim()
            if job_id is None:
                await asyncio.sleep(settings.async_worker_poll_seconds)
                continue
            await self._execute(job_id)
