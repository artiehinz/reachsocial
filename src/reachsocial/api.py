from __future__ import annotations

import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .catalog import Catalog, ServiceDefinition
from .db import get_session
from .models import Client, PaymentReceipt, RequestLog
from .normalizer import resolve_url
from .payments import PUBLIC_X402_CLIENT_NAME, x402_is_configured
from .security import generate_api_key, hash_api_key, verify_api_key
from .services import ExecutionService

router = APIRouter(prefix="/v1", tags=["API"])


class ExecuteRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)


def service_summary(
    service: ServiceDefinition, *, include_internal: bool = False
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "id": service.id,
        "title": service.title,
        "platform": service.platform,
        "description": service.description,
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
            }
        )
    return value


def _api_key_from_header(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


def optional_client(
    authorization: Annotated[str | None, Header()] = None,
    session: Session = Depends(get_session),
) -> Client | None:
    api_key = _api_key_from_header(authorization)
    if not api_key:
        return None
    for client in session.scalars(select(Client).where(Client.status == "active")):
        if verify_api_key(api_key, client.api_key_hash):
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
    """Return the non-secret internal client used to account for settled x402 calls."""
    existing = session.scalar(select(Client).where(Client.name == PUBLIC_X402_CLIENT_NAME))
    if existing is not None:
        return existing
    settings = request.app.state.settings
    client = Client(
        name=PUBLIC_X402_CLIENT_NAME,
        api_key_hash=hash_api_key(generate_api_key()),
        billing_mode="external",
        rate_limit_per_minute=settings.default_rate_limit_per_minute,
        concurrency_limit=settings.default_concurrency_limit,
        # Per-call x402 is prepaid. Do not impose the B2B daily-credit ceiling.
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
    client: Client | None = Depends(optional_client),
    session: Session = Depends(get_session),
    catalog: Catalog = Depends(get_catalog),
    executor: ExecutionService = Depends(get_executor),
) -> dict[str, Any]:
    service = catalog.by_id(service_id)
    if service is None:
        raise HTTPException(
            status_code=404, detail={"code": "unknown_service", "message": "Unknown service"}
        )
    if client is None:
        if not service.public:
            raise HTTPException(
                status_code=401, detail={"code": "unauthenticated", "message": "API key required"}
            )
        settings = request.app.state.settings
        if not settings.x402_enabled:
            raise HTTPException(
                status_code=503,
                detail={"code": "payments_disabled", "message": "Public payments are not enabled"},
            )
        if not x402_is_configured(settings):
            raise HTTPException(
                status_code=503,
                detail={"code": "payments_unconfigured", "message": "Payment verifier is not configured"},
            )
        if not hasattr(request.state, "payment_requirements"):
            raise HTTPException(
                status_code=402,
                detail={"code": "payment_required", "message": "x402 payment required"},
            )
        client = get_x402_public_client(session, request)
    return await executor.execute(
        session,
        client=client,
        service_id=service_id,
        input_data=body.input,
        idempotency_key=idempotency_key,
    )


@router.get("/owner/overview")
def owner_overview(
    session: Session = Depends(get_session),
    catalog: Catalog = Depends(get_catalog),
    _admin: None = Depends(require_admin),
) -> dict[str, Any]:
    """This route is additionally protected by Caddy Basic Auth in production."""
    request_rows = list(session.scalars(select(RequestLog)))
    payment_rows = list(session.scalars(select(PaymentReceipt)))
    requests = len(request_rows)
    errors = sum(row.status == "error" for row in request_rows)
    successes = sum(row.status == "success" for row in request_rows)
    latencies = [row.latency_ms for row in request_rows if row.latency_ms is not None]
    cache_hits = sum(row.cache_hit for row in request_rows)
    settled_payments = [row for row in payment_rows if row.status == "settled"]
    return {
        "clients": session.scalar(select(func.count(Client.id))) or 0,
        "requests": requests,
        "errors": errors,
        "successes": successes,
        "error_rate": round(errors / requests, 4) if requests else 0,
        "latency_ms": {"p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95)},
        "cache_hits": cache_hits,
        "cache_hit_rate": round(cache_hits / requests, 4) if requests else 0,
        "upstream_cost_cents": sum(row.upstream_cost_cents for row in request_rows),
        "b2b_revenue_cents": sum(row.charged_cents for row in request_rows),
        "payment_receipts": {
            "total": len(payment_rows),
            "settled": len(settled_payments),
            "failed_or_canceled": sum(
                row.status in {"canceled", "settlement_failed"} for row in payment_rows
            ),
            "public_revenue_cents": sum(row.amount_cents for row in settled_payments),
        },
        "spend_limit_events": sum(row.error_code == "limit_exceeded" for row in request_rows),
        "enabled_services": len([service for service in catalog.services if service.enabled]),
    }
