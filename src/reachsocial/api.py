from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .catalog import Catalog, ServiceDefinition
from .db import get_session
from .errors import CreditUnavailable, ReachSocialError, TestCapacityReached
from .jobs import (
    authorize_job,
    claim_credit,
    consume_credit,
    credit_is_valid,
    job_payload,
    submit_job,
)
from .models import (
    AsyncJob,
    Client,
    PaymentReceipt,
    ProviderAttempt,
    PublicTestUsage,
    RequestLog,
    ServiceCredit,
)
from .normalizer import resolve_url
from .payments import (
    PUBLIC_X402_CLIENT_NAME,
    payment_id_from_payload,
    x402_is_configured,
)
from .security import api_key_id, generate_api_key, hash_api_key, verify_api_key
from .services import ExecutionService, stable_hash, utcnow_naive

router = APIRouter(prefix="/v1", tags=["API"])


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: dict[str, Any] = Field(default_factory=dict)


def service_summary(
    service: ServiceDefinition, *, include_internal: bool = False
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "id": service.id,
        "title": service.title,
        "platform": service.platform,
        "description": service.description,
        "execution": service.execution,
        "response_shape": service.response_shape,
        "schema_version": "1.0",
        "inputs": [field.model_dump() for field in service.input_fields],
        "price_cents": service.price_cents,
        "docs": service.docs,
    }
    if include_internal:
        value.update(
            {
                "enabled": service.enabled,
                "public": service.public,
                "provider": service.provider.name,
                "timeout_seconds": service.timeout_seconds,
                "cost_verified": service.cost_verified,
                "estimated_upstream_cost_microusd": service.estimated_upstream_cost_microusd,
            }
        )
    return value


def _api_key_from_header(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    key = value.strip()
    return key if scheme.lower() == "bearer" and key else None


def _validate_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.strip() or len(value) > 255:
        from .errors import InvalidInput

        raise InvalidInput("Idempotency-Key must contain 1 to 255 characters")
    return value


def _expired(value: datetime | None) -> bool:
    if value is None:
        return False
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value <= utcnow_naive()


def optional_client(
    authorization: Annotated[str | None, Header()] = None,
    session: Session = Depends(get_session),
) -> Client | None:
    api_key = _api_key_from_header(authorization)
    if not api_key:
        return None
    if len(api_key) > 512:
        raise HTTPException(
            status_code=401, detail={"code": "unauthenticated", "message": "Invalid API key"}
        )
    key_id = api_key_id(api_key)
    candidates: list[Client]
    if key_id:
        row = session.scalar(
            select(Client).where(Client.key_id == key_id, Client.status == "active")
        )
        candidates = [row] if row else []
    else:
        candidates = list(
            session.scalars(
                select(Client).where(Client.status == "active", Client.key_id.is_(None))
            )
        )
    for client in candidates:
        if not _expired(client.api_key_expires_at) and verify_api_key(api_key, client.api_key_hash):
            return client
    raise HTTPException(
        status_code=401, detail={"code": "unauthenticated", "message": "Invalid API key"}
    )


def require_client(client: Client | None = Depends(optional_client)) -> Client:
    if client is None:
        raise HTTPException(
            status_code=401, detail={"code": "unauthenticated", "message": "API key required"}
        )
    return client


def get_x402_public_client(session: Session, request: Request) -> Client:
    existing = session.scalar(select(Client).where(Client.name == PUBLIC_X402_CLIENT_NAME))
    if existing is not None:
        return existing
    settings = request.app.state.settings
    raw_key = generate_api_key()
    client = Client(
        name=PUBLIC_X402_CLIENT_NAME,
        key_id=api_key_id(raw_key),
        api_key_hash=hash_api_key(raw_key),
        billing_mode="external",
        rate_limit_per_minute=settings.default_rate_limit_per_minute,
        concurrency_limit=settings.default_concurrency_limit,
        daily_spend_cents=2_147_483_647,
    )
    session.add(client)
    session.commit()
    return client


def require_admin(
    request: Request,
    admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
) -> None:
    expected = request.app.state.settings.admin_api_token
    if not expected or not admin_token or not hmac.compare_digest(admin_token, expected):
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Not found"})


def get_catalog(request: Request) -> Catalog:
    return request.app.state.catalog


def get_executor(request: Request) -> ExecutionService:
    return request.app.state.executor


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    position = max(0, min(len(values) - 1, round((len(values) - 1) * percentile)))
    return sorted(values)[position]


def _current_payment_id(request: Request) -> str | None:
    payload = getattr(request.state, "payment_payload", None)
    return payment_id_from_payload(payload) if payload is not None else None


def _identity_hash(request: Request, kind: str, value: str) -> str:
    settings = request.app.state.settings
    salt = settings.admin_api_token or "reachsocial-public-test"
    return hashlib.sha256(f"{kind}:{value}:{salt}".encode()).hexdigest()


async def enforce_public_test_limits(
    request: Request, session: Session, payment_id: str | None
) -> None:
    settings = request.app.state.settings
    ip = request.client.host if request.client else "unknown"
    identities = [("ip", _identity_hash(request, "ip", ip))]
    if payment_id:
        receipt = session.scalar(
            select(PaymentReceipt).where(PaymentReceipt.payment_id == payment_id)
        )
        if receipt and receipt.payer:
            identities.append(("payer", _identity_hash(request, "payer", receipt.payer.lower())))
    await request.app.state.runtime.record_public_request(
        [f"{kind}:{identity}" for kind, identity in identities],
        settings.public_test_rate_limit_per_minute,
    )
    day = datetime.now(UTC).date().isoformat()
    for attempt in range(3):
        try:
            for kind, identity in identities:
                result = session.execute(
                    update(PublicTestUsage)
                    .where(
                        PublicTestUsage.usage_day == day,
                        PublicTestUsage.identity_kind == kind,
                        PublicTestUsage.identity_hash == identity,
                        PublicTestUsage.request_count
                        < settings.public_test_daily_requests_per_identity,
                    )
                    .values(request_count=PublicTestUsage.request_count + 1)
                )
                if result.rowcount:
                    continue
                exists = session.scalar(
                    select(PublicTestUsage.id).where(
                        PublicTestUsage.usage_day == day,
                        PublicTestUsage.identity_kind == kind,
                        PublicTestUsage.identity_hash == identity,
                    )
                )
                if exists is not None:
                    session.rollback()
                    raise TestCapacityReached(
                        "The public test request limit has been reached for today"
                    )
                session.add(
                    PublicTestUsage(
                        usage_day=day,
                        identity_kind=kind,
                        identity_hash=identity,
                        request_count=1,
                    )
                )
                session.flush()
            session.commit()
            return
        except IntegrityError:
            session.rollback()
            if attempt == 2:
                raise TestCapacityReached(
                    "The public test request limit could not be reserved"
                ) from None


def _ensure_public_payment(request: Request) -> None:
    settings = request.app.state.settings
    if not settings.x402_enabled:
        raise HTTPException(
            status_code=503,
            detail={"code": "payments_disabled", "message": "Public payments are not enabled"},
        )
    if not x402_is_configured(settings):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "payments_unconfigured",
                "message": "Payment verifier is not configured",
            },
        )
    if not hasattr(request.state, "payment_requirements"):
        raise HTTPException(
            status_code=402,
            detail={"code": "payment_required", "message": "x402 payment required"},
        )


def _link_receipt(
    session: Session,
    payment_id: str | None,
    *,
    request_id: str | None = None,
    job_id: str | None = None,
) -> None:
    if not payment_id:
        return
    receipt = session.scalar(
        select(PaymentReceipt).where(PaymentReceipt.payment_id == payment_id)
    )
    if receipt:
        receipt.request_id = request_id or receipt.request_id
        receipt.job_id = job_id or receipt.job_id
        session.commit()


async def _enforce_and_record_public_limits(
    request: Request,
    session: Session,
    executor: ExecutionService,
    client: Client,
    service: ServiceDefinition,
    input_data: dict[str, Any],
    payment_id: str | None,
) -> None:
    try:
        await enforce_public_test_limits(request, session, payment_id)
    except ReachSocialError as error:
        executor._record(
            session,
            request_id=f"req_{uuid.uuid4().hex}",
            client=client,
            service=service,
            status="error",
            input_hash=stable_hash(input_data),
            latency_ms=0,
            error_code=error.code,
            charge_client=False,
        )
        raise


@router.get("/services")
def list_services(catalog: Catalog = Depends(get_catalog)) -> dict[str, list[dict[str, Any]]]:
    return {"services": [service_summary(service) for service in catalog.public_services()]}


@router.get("/services/{service_id}")
def get_service(service_id: str, catalog: Catalog = Depends(get_catalog)) -> dict[str, Any]:
    service = catalog.by_id(service_id)
    if service is None or not (service.enabled and service.public):
        raise HTTPException(
            status_code=404, detail={"code": "unknown_service", "message": "Unknown service"}
        )
    return service_summary(service)


@router.post("/resolve")
def resolve(request: ExecuteRequest, _client: Client = Depends(require_client)) -> dict[str, str]:
    return resolve_url(request.input.get("url"))


@router.post("/services/{service_id}/execute")
async def execute_service(
    service_id: str,
    body: ExecuteRequest,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    service_credit: Annotated[str | None, Header(alias="X-Service-Credit")] = None,
    client: Client | None = Depends(optional_client),
    session: Session = Depends(get_session),
    catalog: Catalog = Depends(get_catalog),
    executor: ExecutionService = Depends(get_executor),
) -> dict[str, Any]:
    idempotency_key = _validate_idempotency_key(idempotency_key)
    service = catalog.by_id(service_id)
    if service is None:
        raise HTTPException(
            status_code=404, detail={"code": "unknown_service", "message": "Unknown service"}
        )
    anonymous = client is None
    if service.is_async:
        raise HTTPException(
            status_code=409,
            detail={"code": "async_required", "message": "Use the jobs endpoint"},
        )
    executor.validate_input(service, body.input)
    credit_used = False
    payment_id = _current_payment_id(request)
    if anonymous:
        if not service.public:
            raise HTTPException(
                status_code=401,
                detail={"code": "unauthenticated", "message": "API key required"},
            )
        if service_credit:
            if not credit_is_valid(service_credit, service.id, service.price_cents):
                raise CreditUnavailable("The service credit is invalid or unavailable")
        else:
            _ensure_public_payment(request)
        client = get_x402_public_client(session, request)
        await _enforce_and_record_public_limits(
            request, session, executor, client, service, body.input, payment_id
        )
        if service_credit:
            credit_used = consume_credit(session, service_credit, service)
            if not credit_used:
                raise CreditUnavailable("The service credit was already consumed")
    response = await executor.execute(
        session,
        client=client,
        service_id=service_id,
        input_data=body.input,
        idempotency_key=idempotency_key,
        charge_client=not credit_used and not anonymous,
    )
    _link_receipt(session, payment_id, request_id=response["request_id"])
    return response


@router.post("/services/{service_id}/jobs", status_code=202)
async def create_job(
    service_id: str,
    body: ExecuteRequest,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    service_credit: Annotated[str | None, Header(alias="X-Service-Credit")] = None,
    client: Client | None = Depends(optional_client),
    session: Session = Depends(get_session),
    catalog: Catalog = Depends(get_catalog),
    executor: ExecutionService = Depends(get_executor),
) -> dict[str, Any]:
    idempotency_key = _validate_idempotency_key(idempotency_key)
    service = catalog.by_id(service_id)
    if service is None:
        raise HTTPException(
            status_code=404, detail={"code": "unknown_service", "message": "Unknown service"}
        )
    anonymous = client is None
    if not service.is_async:
        raise HTTPException(
            status_code=409,
            detail={"code": "sync_required", "message": "Use the execute endpoint"},
        )
    executor.validate_input(service, body.input)
    payment_id = _current_payment_id(request)
    if anonymous:
        if not service.public:
            raise HTTPException(
                status_code=401,
                detail={"code": "unauthenticated", "message": "API key required"},
            )
        if service_credit:
            if not credit_is_valid(service_credit, service.id, service.price_cents):
                raise CreditUnavailable("The service credit is invalid or unavailable")
        else:
            _ensure_public_payment(request)
        client = get_x402_public_client(session, request)
        await _enforce_and_record_public_limits(
            request, session, executor, client, service, body.input, payment_id
        )
        if service_credit and not consume_credit(session, service_credit, service):
            raise CreditUnavailable("The service credit was already consumed")
    job, token = submit_job(
        session,
        executor=executor,
        client=client,
        service_id=service_id,
        input_data=body.input,
        anonymous=anonymous,
        payment_id=payment_id,
        idempotency_key=idempotency_key,
    )
    _link_receipt(session, payment_id, job_id=job.job_id)
    base = str(request.app.state.settings.public_base_url).rstrip("/")
    response: dict[str, Any] = {
        "job_id": job.job_id,
        "service": service.id,
        "status": job.status,
        "status_url": f"{base}/v1/jobs/{job.job_id}",
        "expires_at": job.expires_at.isoformat(),
    }
    if token:
        response["job_token"] = token
    return response


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    job_token: Annotated[str | None, Header(alias="X-Job-Token")] = None,
    client: Client | None = Depends(optional_client),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    job = session.scalar(select(AsyncJob).where(AsyncJob.job_id == job_id))
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "Job not found"})
    authorize_job(job, client=client, job_token=job_token)
    payload = job_payload(job)
    session.commit()
    return payload


@router.post("/jobs/{job_id}/credit")
def claim_job_credit(
    job_id: str,
    job_token: Annotated[str | None, Header(alias="X-Job-Token")] = None,
    client: Client | None = Depends(optional_client),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    job = session.scalar(select(AsyncJob).where(AsyncJob.job_id == job_id))
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "Job not found"})
    authorize_job(job, client=client, job_token=job_token)
    token = claim_credit(session, job)
    return {
        "service": job.service_id,
        "amount_cents": job.price_snapshot_cents,
        "service_credit": token,
        "expires_in_days": request_settings_credit_days(session),
    }


def request_settings_credit_days(_session: Session) -> int:
    from .config import get_settings

    return get_settings().service_credit_expiry_days


@router.get("/owner/overview")
def owner_overview(
    session: Session = Depends(get_session),
    catalog: Catalog = Depends(get_catalog),
    _admin: None = Depends(require_admin),
) -> dict[str, Any]:
    request_rows = list(session.scalars(select(RequestLog)))
    payment_rows = list(session.scalars(select(PaymentReceipt)))
    jobs = list(session.scalars(select(AsyncJob)))
    credits = list(session.scalars(select(ServiceCredit)))
    attempts = list(session.scalars(select(ProviderAttempt)))
    requests = len(request_rows)
    errors = sum(row.status == "error" for row in request_rows)
    latencies = [row.latency_ms for row in request_rows if row.latency_ms is not None]
    cache_hits = sum(row.cache_hit for row in request_rows)
    settled = [row for row in payment_rows if row.status == "settled"]
    b2b_revenue_cents = sum(
        row.charged_cents
        for row in request_rows
        if row.client is None or row.client.name != PUBLIC_X402_CLIENT_NAME
    )
    revenue_cents = b2b_revenue_cents + sum(
        row.amount_cents for row in settled
    )
    cost_micros = sum(row.upstream_cost_microusd for row in attempts)
    now = utcnow_naive()
    queued = [job for job in jobs if job.status == "queued"]
    per_service: dict[str, dict[str, Any]] = {}
    for definition in catalog.services:
        rows = [row for row in request_rows if row.service_id == definition.id]
        service_attempts = [row for row in attempts if row.service_id == definition.id]
        service_payments = [
            row for row in settled if row.service_id == definition.id
        ]
        service_latencies = [row.latency_ms for row in rows if row.latency_ms is not None]
        per_service[definition.id] = {
            "requests": len(rows),
            "successes": sum(row.status == "success" for row in rows),
            "errors": sum(row.status == "error" for row in rows),
            "p50_latency_ms": _percentile(service_latencies, 0.5),
            "p95_latency_ms": _percentile(service_latencies, 0.95),
            "cache_hits": sum(row.cache_hit for row in rows),
            "provider_units": sum(row.provider_units for row in service_attempts),
            "upstream_cost_microusd": sum(
                row.upstream_cost_microusd for row in service_attempts
            ),
            "revenue_cents": sum(
                row.charged_cents
                for row in rows
                if row.client is None or row.client.name != PUBLIC_X402_CLIENT_NAME
            )
            + sum(row.amount_cents for row in service_payments),
        }
    return {
        "clients": session.scalar(select(func.count(Client.id))) or 0,
        "requests": requests,
        "errors": errors,
        "successes": sum(row.status == "success" for row in request_rows),
        "error_rate": round(errors / requests, 4) if requests else 0,
        "latency_ms": {"p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95)},
        "cache_hits": cache_hits,
        "cache_hit_rate": round(cache_hits / requests, 4) if requests else 0,
        "upstream_cost_microusd": cost_micros,
        "revenue_cents": revenue_cents,
        "margin_microusd": revenue_cents * 10_000 - cost_micros,
        "payment_receipts": {
            "total": len(payment_rows),
            "settled": len(settled),
            "failed_or_canceled": sum(
                row.status in {"canceled", "settlement_failed"} for row in payment_rows
            ),
            "public_revenue_cents": sum(row.amount_cents for row in settled),
        },
        "jobs": {
            "queued": len(queued),
            "running": sum(job.status == "running" for job in jobs),
            "succeeded": sum(job.status == "succeeded" for job in jobs),
            "failed": sum(job.status == "failed" for job in jobs),
            "oldest_queue_age_seconds": max(
                [round((now - job.created_at).total_seconds()) for job in queued if job.created_at]
                or [0]
            ),
        },
        "service_credits": {
            "issued": len(credits),
            "active": sum(row.status == "active" for row in credits),
            "consumed": sum(row.status == "consumed" for row in credits),
            "liability_cents": sum(
                row.amount_cents for row in credits if row.status == "active" and row.expires_at > now
            ),
        },
        "rate_limit_events": sum(
            row.error_code in {"rate_limit", "limit_exceeded"} for row in request_rows
        ),
        "spend_limit_events": sum(row.error_code == "spend_limit" for row in request_rows),
        "upstream_spend_cap_events": sum(
            row.error_code == "test_capacity_reached" for row in request_rows
        ),
        "enabled_services": len([service for service in catalog.services if service.enabled]),
        "services": per_service,
    }
