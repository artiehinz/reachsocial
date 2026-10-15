"""Payment intents for OAuth MCP users; execution stays in the public x402 pipeline."""

from __future__ import annotations

import contextvars
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .catalog import ServiceDefinition, get_catalog
from .config import get_settings
from .db import SessionLocal
from .errors import ReachSocialError
from .oauth_provider import origin, wallet_allowed
from .oauth_routes import browser_session
from .oauth_store import OAuthState, consume, digest, get, put, rate_limit, secret
from .payments import (
    PRIVATE_ACCEPTANCE_SCOPE_KEY,
    private_acceptance_path,
    private_acceptance_service_ids,
)
from .services import ExecutionService, stable_hash

current_principal: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "oauth_mcp_principal", default=None
)
expected_mcp_payer: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "expected_mcp_payer", default=None
)
router = APIRouter(include_in_schema=False)


def require_enabled():
    settings = get_settings()
    if not (settings.oauth_enabled and settings.mcp_payment_approval_enabled):
        raise HTTPException(503, "MCP payment approval is not enabled")


def private_mcp_validation_service(service: ServiceDefinition) -> bool:
    """Allow a configured private service only during owner-gated MCP validation."""
    settings = get_settings()
    return bool(
        settings.mainnet_private_acceptance_enabled
        and settings.oauth_validation_wallets.strip()
        and service.enabled
        and not service.public
        and not service.is_async
        and service.price_cents == 5
        and service.id in private_acceptance_service_ids(settings)
    )


def create_request(service: ServiceDefinition, input_data: dict, key: str) -> dict:
    require_enabled()
    principal = current_principal.get()
    if not principal:
        raise HTTPException(401, "OAuth authorization required")
    # Access tokens issued before an owner-only validation gate was enabled
    # must not retain access to temporary private validation tools.
    if not wallet_allowed(str(principal["subject"])):
        raise HTTPException(403, "Self-service access is in limited validation")
    private_validation = private_mcp_validation_service(service)
    if (
        not service.enabled
        or (not service.public and not private_validation)
        or service.is_async
        or service.price_cents != 5
    ):
        raise HTTPException(403, "Service is not available for public MCP payment")
    if not isinstance(key, str) or not 32 <= len(key) <= 255:
        raise HTTPException(400, "Use a random 32–255 character idempotency key")
    normalized = dict(input_data)
    ExecutionService.validate_input(service, normalized)
    request_id = digest(principal["subject"] + "\0" + principal["client_id"] + "\0" + key)
    with SessionLocal() as session:
        row = get(session, "mcp_request", request_id)
        if row:
            if row.payload["service"] != service.id or row.payload["input_hash"] != stable_hash(
                normalized
            ):
                raise HTTPException(409, "Request key already used with different input")
            return request_payload(session, row)
        if not rate_limit(session, principal["subject"], "mcp_request", 30):
            session.commit()
            raise HTTPException(429, "Too many requests; try again later")
        pending = (
            session.scalar(
                select(func.count())
                .select_from(OAuthState)
                .where(
                    OAuthState.kind == "mcp_request",
                    OAuthState.owner == principal["subject"],
                    OAuthState.payload["unpaid_expires_at"].as_float() > time.time(),
                )
            )
            or 0
        )
        if pending >= 20:
            session.commit()
            raise HTTPException(429, "Too many open requests; finish or let them expire")
        payload = {
            "id": request_id,
            "client_id": principal["client_id"],
            "service": service.id,
            "input": normalized,
            "input_hash": stable_hash(normalized),
            "price_cents": service.price_cents,
            "payment_key": "mcp_" + secret(),
            "unpaid_expires_at": time.time() + 1800,
            "private_acceptance": private_validation,
        }
        try:
            row = put(
                session, "mcp_request", request_id, payload, 86400 * 30, owner=principal["subject"]
            )
            session.commit()
        except IntegrityError:
            session.rollback()
            row = get(session, "mcp_request", request_id)
            if (
                not row
                or row.payload["input_hash"] != stable_hash(normalized)
                or row.payload["service"] != service.id
            ):
                raise HTTPException(409, "Request conflict") from None
        return request_payload(session, row)


def request_payload(session, row) -> dict:
    from .api import _recover_sync_payment

    payload = row.payload
    recovered = _recover_sync_payment(
        session,
        service_id=payload["service"],
        idempotency_key=payload["payment_key"],
        input_data=payload["input"],
    )
    base = {
        "request_id": payload["id"],
        "service": payload["service"],
        "price_cents": payload["price_cents"],
    }
    if payload.get("private_acceptance"):
        base["payment_endpoint"] = private_acceptance_path(payload["service"])
    if recovered:
        result, receipt = recovered
        if receipt.status != "settled":
            return {**base, "status": "reconciliation_required", "payment_status": receipt.status}
        return {
            **base,
            "status": "succeeded" if result.get("status") == "success" else "failed",
            "result": result,
            "payment_status": receipt.status,
            "transaction": receipt.transaction,
        }
    # Existing durable receipt/recovery detection takes precedence over unpaid expiry.
    from .payments import _has_paid_idempotency_recovery

    if _has_paid_idempotency_recovery(payload["service"], payload["payment_key"]):
        return {
            **base,
            "status": "reconciliation_required",
            "message": "Payment or execution is pending. Retrieve this request again; do not pay again.",
        }
    if payload.get("payment_attempted"):
        return {
            **base,
            "status": "reconciliation_required",
            "message": "An approval was attempted. Recover this request; do not create another payment.",
        }
    if payload.get("approval_until", 0) > time.time():
        return {
            **base,
            "status": "awaiting_approval",
            "message": "An approval window is open. Complete it or wait five minutes before trying again.",
        }
    if payload["unpaid_expires_at"] <= time.time():
        return {**base, "status": "expired"}
    return {**base, "status": "payment_required", "payment_url": origin() + "/pay/" + payload["id"]}


def retrieve_request(request_id: str) -> dict[str, Any]:
    principal = current_principal.get()
    if not principal:
        raise HTTPException(401, "OAuth authorization required")
    with SessionLocal() as session:
        row = get(session, "mcp_request", request_id)
        if (
            not row
            or row.owner != principal["subject"]
            or row.payload["client_id"] != principal["client_id"]
        ):
            raise HTTPException(404, "Request not found")
        return request_payload(session, row)


@router.get("/account/requests")
async def account_requests(request: Request):
    identity = browser_session(request)
    with SessionLocal() as session:
        rows = session.scalars(
            select(OAuthState)
            .where(
                OAuthState.kind == "mcp_request",
                OAuthState.owner == identity["address"],
                OAuthState.expires_at > time.time(),
            )
            .order_by(OAuthState.expires_at.desc())
            .limit(50)
        ).all()
        return {"requests": [request_payload(session, row) for row in rows]}


@router.get("/account/requests/{request_id}")
async def account_request(request_id: str, request: Request):
    identity = browser_session(request)
    with SessionLocal() as session:
        row = get(session, "mcp_request", request_id)
        if not row or row.owner != identity["address"]:
            raise HTTPException(404, "Request not found")
        return {**request_payload(session, row), "input": row.payload["input"], "owner": row.owner}


@router.post("/account/requests/{request_id}/approve")
async def approve_request(request_id: str, request: Request):
    require_enabled()
    identity = browser_session(request, csrf=True)
    with SessionLocal() as session:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        row = get(session, "mcp_request", request_id)
        if not row or row.owner != identity["address"]:
            raise HTTPException(404, "Request not found")
        if request_payload(session, row)["status"] != "payment_required":
            raise HTTPException(409, "Request cannot accept another payment; recover it")
        authorization = secret()
        # The capability is short-lived and bound to this exact intent, never a B2B key.
        put(
            session,
            "payment_approval",
            authorization,
            {"request_id": request_id},
            300,
            owner=row.owner,
        )
        row.payload = {**row.payload, "approval_until": time.time() + 300}
        session.commit()
        return {
            "payment_key": row.payload["payment_key"],
            "authorization": authorization,
            "service": row.payload["service"],
            "input": row.payload["input"],
            "owner": row.owner,
            **(
                {"payment_endpoint": private_acceptance_path(row.payload["service"])}
                if row.payload.get("private_acceptance")
                else {}
            ),
        }


async def guard_payment(
    request: Request, service_id: str, key: str, *, dispatch: bool = False
) -> str | None:
    if not key.startswith("mcp_"):
        return None
    require_enabled()
    from .api import _recover_sync_payment

    with SessionLocal() as session:
        row = session.scalar(
            select(OAuthState).where(
                OAuthState.kind == "mcp_request",
                OAuthState.payload["payment_key"].as_string() == key,
            )
        )
        if not row or row.expires_at <= time.time():
            raise HTTPException(403, "Unknown MCP payment request")
        if service_id != row.payload["service"]:
            raise HTTPException(403, "MCP request service mismatch")
        private_route = request.scope.get(PRIVATE_ACCEPTANCE_SCOPE_KEY) == service_id
        if bool(row.payload.get("private_acceptance")) != private_route:
            raise HTTPException(403, "MCP request payment route mismatch")
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(400, "Invalid JSON") from None
        if not isinstance(body, dict) or not isinstance(body.get("input"), dict):
            raise HTTPException(400, "Input must be an object")
        normalized = dict(body["input"])
        service = get_catalog().by_id(service_id)
        if not service:
            raise HTTPException(404, "Unknown service")
        try:
            ExecutionService.validate_input(service, normalized)
        except ReachSocialError as error:
            raise HTTPException(error.status_code, error.message) from None
        if (
            stable_hash(normalized) != row.payload["input_hash"]
            or service.price_cents != row.payload["price_cents"]
        ):
            raise HTTPException(409, "MCP request input or price changed")
        approval = get(
            session, "payment_approval", request.headers.get("x-reachsocial-approval", "")
        )
        if (
            not approval
            or approval.payload["request_id"] != row.payload["id"]
            or approval.owner != row.owner
        ):
            raise HTTPException(403, "MCP payment approval required")
        if not _recover_sync_payment(
            session, service_id=service_id, idempotency_key=key, input_data=normalized
        ):
            if row.payload["unpaid_expires_at"] <= time.time():
                raise HTTPException(409, "Unpaid request expired")
        if dispatch and (
            request.headers.get("payment-signature") or request.headers.get("x-payment")
        ):
            if not consume(
                session, "payment_approval", request.headers.get("x-reachsocial-approval", "")
            ):
                raise HTTPException(409, "Payment was already attempted; recover this request")
            row.payload = {
                **row.payload,
                "payment_attempted": True,
                "payment_attempted_at": time.time(),
            }
            session.commit()
        return row.owner
