from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from cdp.x402 import create_facilitator_config
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from x402.http import HTTPFacilitatorClient
from x402.http.middleware.fastapi import payment_middleware
from x402.http.types import HTTPRequestContext, PaymentOption, RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.schemas import AbortResult
from x402.server import x402ResourceServer

from .catalog import Catalog
from .config import Settings
from .db import SessionLocal
from .models import PaymentReceipt

PUBLIC_EXECUTE_ROUTE = "POST /v1/services/*/execute"
PUBLIC_JOB_ROUTE = "POST /v1/services/*/jobs"
PUBLIC_X402_CLIENT_NAME = "x402-public"


def service_id_from_path(path: str) -> str | None:
    """Return the service ID from the canonical public execute path."""
    prefix = "/v1/services/"
    suffix = next((value for value in ("/execute", "/jobs") if path.endswith(value)), None)
    if not path.startswith(prefix) or suffix is None:
        return None
    service_id = path.removeprefix(prefix).removesuffix(suffix)
    return service_id or None


def x402_is_configured(settings: Settings) -> bool:
    return bool(
        settings.x402_pay_to
        and settings.x402_facilitator_url
        and settings.cdp_api_key_id
        and settings.cdp_api_key_secret
    )


def mainnet_x402_safety_errors(settings: Settings, catalog: Catalog) -> list[str]:
    """Return launch blockers when real Base payments are selected."""
    if settings.x402_network != "eip155:8453":
        return []
    errors: list[str] = []
    if not settings.allow_mainnet_x402:
        errors.append("ALLOW_MAINNET_X402=true is required")
    if not settings.external_backup_enabled:
        errors.append("EXTERNAL_BACKUP_ENABLED=true is required")
    for service in catalog.public_services():
        if not service.cost_verified or service.estimated_upstream_cost_microusd <= 0:
            errors.append(f"{service.id} needs a verified upstream cost")
        else:
            price_micros = service.price_cents * 10_000
            margin_micros = price_micros - service.estimated_upstream_cost_microusd
            if (
                margin_micros < settings.minimum_public_margin_cents * 10_000
                or margin_micros * 2 < price_micros
            ):
                errors.append(f"{service.id} does not meet the configured public margin")
    return errors


def payment_id_from_payload(payload: Any) -> str:
    """Create a deterministic replay key without retaining a raw signed payload."""
    if hasattr(payload, "model_dump"):
        value = payload.model_dump(mode="json", by_alias=True)
    else:
        value = payload
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _context_service_id(context: Any) -> str:
    path = getattr(getattr(context, "transport_context", None), "request", None)
    return service_id_from_path(getattr(path, "path", "")) or "unknown"


def _details(**values: Any) -> str:
    return json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)


def usdc_atomic_to_cents(amount: object) -> int:
    """Convert Base USDC's six-decimal atomic amount to whole cents."""
    try:
        return int(str(amount)) // 10_000
    except (TypeError, ValueError):
        return 0


def reserve_payment_receipt(context: Any) -> AbortResult | None:
    """Reserve a verified payment before provider execution to reject replay."""
    payment_id = payment_id_from_payload(context.payment_payload)
    with SessionLocal() as session:
        existing = session.scalar(
            select(PaymentReceipt).where(PaymentReceipt.payment_id == payment_id)
        )
        if existing is not None:
            logging.getLogger("reachsocial").warning(
                "operational_alert kind=payment_replay service=%s", existing.service_id
            )
            return AbortResult("payment_replayed", "This payment has already been used")
        session.add(
            PaymentReceipt(
                payment_id=payment_id,
                service_id=_context_service_id(context),
                amount_cents=usdc_atomic_to_cents(getattr(context.requirements, "amount", None)),
                network=str(context.requirements.network),
                status="verified",
                payer=getattr(context.result, "payer", None),
                details=_details(
                    payer=getattr(context.result, "payer", None),
                    amount=getattr(context.requirements, "amount", None),
                ),
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            logging.getLogger("reachsocial").warning(
                "operational_alert kind=payment_replay service=%s",
                _context_service_id(context),
            )
            return AbortResult("payment_replayed", "This payment has already been used")
    return None


def mark_payment_settled(context: Any) -> None:
    payment_id = payment_id_from_payload(context.payment_payload)
    with SessionLocal() as session:
        receipt = session.scalar(
            select(PaymentReceipt).where(PaymentReceipt.payment_id == payment_id)
        )
        if receipt is None:
            return
        receipt.status = "settled"
        receipt.network = str(context.result.network)
        receipt.payer = getattr(context.result, "payer", None)
        receipt.transaction = context.result.transaction
        receipt.details = _details(
            payer=getattr(context.result, "payer", None),
            transaction=context.result.transaction,
            amount=context.result.amount,
        )
        session.commit()
    logging.getLogger("reachsocial").info(
        "payment_settled service=%s network=%s", _context_service_id(context), context.result.network
    )


def mark_payment_canceled(context: Any) -> None:
    payment_id = payment_id_from_payload(context.payment_payload)
    with SessionLocal() as session:
        receipt = session.scalar(
            select(PaymentReceipt).where(PaymentReceipt.payment_id == payment_id)
        )
        if receipt is not None:
            receipt.status = "canceled"
            receipt.details = _details(reason=getattr(context, "reason", "settlement_failed"))
            session.commit()
    logging.getLogger("reachsocial").warning(
        "operational_alert kind=payment_settlement_failed service=%s",
        _context_service_id(context),
    )


def price_for_public_execution(context: HTTPRequestContext, catalog: Catalog) -> str:
    """Resolve the catalog price immediately before issuing a payment challenge."""
    service = catalog.by_id(service_id_from_path(context.path) or "")
    # The route handler returns the authoritative 404/401/503 response.  A fallback
    # price prevents malformed paths from leaking an unprotected middleware route.
    price_cents = service.price_cents if service is not None else 5
    return f"${price_cents / 100:.2f}"


def is_b2b_request(request: Request) -> bool:
    """Let Bearer-key requests reach normal B2B authentication first."""
    authorization = request.headers.get("authorization") or ""
    scheme, _, value = authorization.partition(" ")
    return scheme.lower() == "bearer" and bool(value.strip())


def create_x402_payment_handler(settings: Settings, catalog: Catalog):
    """Build the CDP-backed x402 handler for public service execution."""
    if not x402_is_configured(settings):
        raise ValueError(
            "X402_ENABLED requires CDP_API_KEY_ID, CDP_API_KEY_SECRET, "
            "X402_PAY_TO, and X402_FACILITATOR_URL"
        )

    mainnet_errors = mainnet_x402_safety_errors(settings, catalog)
    if mainnet_errors:
        raise ValueError("Base mainnet x402 is blocked: " + "; ".join(mainnet_errors))

    facilitator_config = create_facilitator_config(
        api_key_id=settings.cdp_api_key_id,
        api_key_secret=settings.cdp_api_key_secret,
    )
    facilitator = HTTPFacilitatorClient(facilitator_config)
    server = x402ResourceServer(facilitator)
    server.register(settings.x402_network, ExactEvmServerScheme())
    server.on_after_verify(reserve_payment_receipt)
    server.on_after_settle(mark_payment_settled)
    server.on_settle_failure(mark_payment_canceled)
    server.on_verified_payment_canceled(mark_payment_canceled)
    route = RouteConfig(
        accepts=PaymentOption(
            scheme="exact",
            pay_to=settings.x402_pay_to,
            price=lambda context: price_for_public_execution(context, catalog),
            network=settings.x402_network,
        ),
        description="ReachSocial public social-data API call",
        mime_type="application/json",
    )
    return payment_middleware(
        routes={PUBLIC_EXECUTE_ROUTE: route, PUBLIC_JOB_ROUTE: route},
        server=server,
    )


class ReachSocialX402Middleware(BaseHTTPMiddleware):
    """Apply x402 to anonymous public calls while preserving B2B API-key access."""

    def __init__(self, app, *, settings: Settings, catalog: Catalog):  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._catalog = catalog
        self._payment_handler = create_x402_payment_handler(settings, catalog)

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        if is_b2b_request(request):
            return await call_next(request)
        credit = request.headers.get("x-service-credit") or ""
        service = service_id_from_path(request.url.path)
        if credit and service:
            from .jobs import credit_is_valid

            definition = self._catalog.by_id(service)
            if definition and credit_is_valid(credit, service, definition.price_cents):
                return await call_next(request)
        return await self._payment_handler(request, call_next)
