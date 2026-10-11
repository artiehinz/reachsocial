from __future__ import annotations

import hashlib
import json
import logging
import re
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
from .models import MainnetCanaryAttempt, PaymentReceipt

PUBLIC_EXECUTE_ROUTE = "POST /v1/services/*/execute"
PUBLIC_JOB_ROUTE = "POST /v1/services/*/jobs"
PUBLIC_X402_CLIENT_NAME = "x402-public"
MAINNET_CANARY_NETWORK = "eip155:8453"
MAINNET_CANARY_SERVICE_ID = "instagram.profile"
MAINNET_CANARY_ROUTE = "POST /v1/canary/mainnet/instagram.profile/execute"
MAINNET_CANARY_PATH = "/v1/canary/mainnet/instagram.profile/execute"
MAINNET_CANARY_KEY = "base-mainnet-instagram-profile-2026-10"
MAINNET_CANARY_PRICE = "$0.05"
MAINNET_CANARY_AMOUNT_ATOMIC = 50_000
MAINNET_CANARY_USDC_ASSET = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"


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


def mainnet_canary_safety_errors(settings: Settings, catalog: Catalog) -> list[str]:
    """Return fail-closed setup errors for the isolated single-payment canary."""
    if not settings.mainnet_x402_canary_enabled:
        return []
    errors: list[str] = []
    if not settings.x402_enabled:
        errors.append("X402_ENABLED=true is required")
    if settings.x402_network != "eip155:84532":
        errors.append("the normal public x402 network must remain Base Sepolia")
    if not re.fullmatch(r"0x[a-fA-F0-9]{40}", settings.mainnet_x402_canary_buyer):
        errors.append("MAINNET_X402_CANARY_BUYER must be an EVM address")
    service = catalog.by_id(MAINNET_CANARY_SERVICE_ID)
    if service is None or not (service.enabled and service.public):
        errors.append(f"{MAINNET_CANARY_SERVICE_ID} must remain publicly executable")
    elif service.price_cents != 5:
        errors.append(f"{MAINNET_CANARY_SERVICE_ID} must remain priced at five cents")
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


def reserve_mainnet_canary(context: Any, expected_payer: str) -> AbortResult | None:
    """Reserve the sole verified mainnet canary before it can reach settlement."""
    payer = str(getattr(context.result, "payer", ""))
    amount = str(getattr(context.requirements, "amount", ""))
    network = str(getattr(context.requirements, "network", ""))
    asset = str(getattr(context.requirements, "asset", ""))
    request = getattr(getattr(context, "transport_context", None), "request", None)
    path = getattr(request, "path", "")
    if payer.lower() != expected_payer.lower():
        return AbortResult("mainnet_canary_buyer_rejected", "This buyer is not approved for the canary")
    if (
        path != MAINNET_CANARY_PATH
        or network != MAINNET_CANARY_NETWORK
        or asset.lower() != MAINNET_CANARY_USDC_ASSET.lower()
        or amount != str(MAINNET_CANARY_AMOUNT_ATOMIC)
    ):
        return AbortResult("mainnet_canary_requirement_rejected", "The canary requirement is invalid")

    payment_id = payment_id_from_payload(context.payment_payload)
    with SessionLocal() as session:
        if session.scalar(select(PaymentReceipt).where(PaymentReceipt.payment_id == payment_id)):
            return AbortResult("payment_replayed", "This payment has already been used")
        if session.scalar(
            select(MainnetCanaryAttempt).where(MainnetCanaryAttempt.canary_key == MAINNET_CANARY_KEY)
        ):
            return AbortResult("mainnet_canary_already_used", "The mainnet canary has already been used")
        session.add(
            PaymentReceipt(
                payment_id=payment_id,
                service_id=MAINNET_CANARY_SERVICE_ID,
                amount_cents=5,
                network=MAINNET_CANARY_NETWORK,
                status="verified",
                payer=payer,
                details=_details(payer=payer, amount=amount, canary=True),
            )
        )
        session.add(
            MainnetCanaryAttempt(
                canary_key=MAINNET_CANARY_KEY,
                payment_id=payment_id,
                payer=payer,
                status="verified",
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return AbortResult("mainnet_canary_already_used", "The mainnet canary has already been used")
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


def mark_mainnet_canary_status(context: Any, status: str) -> None:
    payment_id = payment_id_from_payload(context.payment_payload)
    with SessionLocal() as session:
        attempt = session.scalar(
            select(MainnetCanaryAttempt).where(MainnetCanaryAttempt.payment_id == payment_id)
        )
        if attempt is not None:
            attempt.status = status
            session.commit()


def mark_mainnet_canary_settled(context: Any) -> None:
    mark_payment_settled(context)
    mark_mainnet_canary_status(context, "settled")


def mark_mainnet_canary_canceled(context: Any) -> None:
    mark_payment_canceled(context)
    mark_mainnet_canary_status(context, "canceled")


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


def create_mainnet_canary_payment_handler(settings: Settings, catalog: Catalog):
    """Build the separate handler for one named buyer and one five-cent payment."""
    if not x402_is_configured(settings):
        raise ValueError("Mainnet canary requires the configured CDP x402 facilitator")
    errors = mainnet_canary_safety_errors(settings, catalog)
    if errors:
        raise ValueError("Base mainnet canary is blocked: " + "; ".join(errors))
    facilitator_config = create_facilitator_config(
        api_key_id=settings.cdp_api_key_id,
        api_key_secret=settings.cdp_api_key_secret,
    )
    facilitator = HTTPFacilitatorClient(facilitator_config)
    server = x402ResourceServer(facilitator)
    server.register(MAINNET_CANARY_NETWORK, ExactEvmServerScheme())
    server.on_after_verify(
        lambda context: reserve_mainnet_canary(context, settings.mainnet_x402_canary_buyer)
    )
    server.on_after_settle(mark_mainnet_canary_settled)
    server.on_settle_failure(mark_mainnet_canary_canceled)
    server.on_verified_payment_canceled(mark_mainnet_canary_canceled)
    route = RouteConfig(
        accepts=PaymentOption(
            scheme="exact",
            pay_to=settings.x402_pay_to,
            price=MAINNET_CANARY_PRICE,
            network=MAINNET_CANARY_NETWORK,
        ),
        description="One-time ReachSocial Base-mainnet payment canary",
        mime_type="application/json",
    )
    return payment_middleware(routes={MAINNET_CANARY_ROUTE: route}, server=server)


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
        if service:
            definition = self._catalog.by_id(service)
            if definition is None or not (definition.enabled and definition.public):
                return await call_next(request)
        if credit and service:
            from .jobs import credit_is_valid

            if definition and credit_is_valid(credit, service, definition.price_cents):
                return await call_next(request)
        return await self._payment_handler(request, call_next)


class MainnetCanaryX402Middleware(BaseHTTPMiddleware):
    """Expose the canary only to its payment middleware; no B2B or credit bypass exists."""

    def __init__(self, app, *, settings: Settings, catalog: Catalog):  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._payment_handler = create_mainnet_canary_payment_handler(settings, catalog)

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        if request.method != "POST" or request.url.path != MAINNET_CANARY_PATH:
            return await call_next(request)
        if is_b2b_request(request) or request.headers.get("x-service-credit"):
            return Response(status_code=403)
        return await self._payment_handler(request, call_next)
