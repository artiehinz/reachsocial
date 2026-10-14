from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from cdp.x402 import create_facilitator_config
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from x402.http import HTTPFacilitatorClient
from x402.http.middleware.fastapi import payment_middleware
from x402.http.types import HTTPRequestContext, PaymentOption, RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.schemas import AbortResult
from x402.server import x402ResourceServer

from .catalog import Catalog
from .config import Settings, get_settings
from .credit_budget import ProviderBalanceUnavailable, fetch_provider_balance
from .credit_budget import finalize as finalize_credit_reservation
from .credit_budget import reserve as reserve_credit_reservation
from .db import SessionLocal
from .errors import ReachSocialError
from .models import (
    AsyncJob,
    Client,
    IdempotencyRecord,
    MainnetCanaryAttempt,
    PaymentReceipt,
    PublicTestUsage,
)

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
MAINNET_ACCEPTANCE_PATHS = {
    "instagram.profile": "/v1/acceptance/mainnet/instagram.profile/execute",
    "instagram.post": "/v1/acceptance/mainnet/instagram.post/execute",
    "linkedin.profile": "/v1/acceptance/mainnet/linkedin.profile/jobs",
}
MAINNET_ACCEPTANCE_ROUTES = {
    f"POST {path}": service_id for service_id, path in MAINNET_ACCEPTANCE_PATHS.items()
}
MAINNET_ACCEPTANCE_SYNC_SERVICE_IDS = frozenset({"instagram.profile", "instagram.post"})
MAINNET_ACCEPTANCE_ASYNC_SERVICE_IDS = frozenset({"linkedin.profile"})
MAINNET_ACCEPTANCE_KEY_PREFIX = "base-mainnet-acceptance-2026-10"


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
    has_public_scrapecreators = any(
        service.provider.name == "scrapecreators" for service in catalog.public_services()
    )
    if has_public_scrapecreators and (
        settings.scrapecreators_credit_balance <= settings.scrapecreators_credit_reserve
    ):
        errors.append("a checked ScrapeCreators balance above the internal reserve is required")
    if has_public_scrapecreators and not settings.scrapecreators_api_key:
        errors.append("SCRAPECREATORS_API_KEY is required for live balance checks")
    for service in catalog.public_services():
        if not service.cost_verified:
            errors.append(f"{service.id} needs a verified upstream cost")
        elif service.maximum_request_cost_microusd <= 0:
            if not service.verified_zero_upstream_cost:
                errors.append(f"{service.id} needs an explicit verified zero upstream cost")
        else:
            price_micros = service.price_cents * 10_000
            margin_micros = price_micros - service.maximum_request_cost_microusd
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


def mainnet_acceptance_safety_errors(settings: Settings, catalog: Catalog) -> list[str]:
    """Return fail-closed setup errors for the named three-route acceptance."""
    if not settings.mainnet_x402_acceptance_enabled:
        return []
    errors: list[str] = []
    if not settings.x402_enabled:
        errors.append("X402_ENABLED=true is required")
    if settings.x402_network != "eip155:84532":
        errors.append("the normal public x402 network must remain Base Sepolia")
    if not re.fullmatch(r"0x[a-fA-F0-9]{40}", settings.mainnet_x402_acceptance_buyer):
        errors.append("MAINNET_X402_ACCEPTANCE_BUYER must be an EVM address")
    for service_id in MAINNET_ACCEPTANCE_PATHS:
        service = catalog.by_id(service_id)
        if service is None or not (service.enabled and service.public):
            errors.append(f"{service_id} must remain publicly executable")
        elif not service.cost_verified or service.maximum_request_cost_microusd <= 0:
            errors.append(f"{service_id} needs a verified upstream cost")
        else:
            price_micros = service.price_cents * 10_000
            margin_micros = price_micros - service.estimated_upstream_cost_microusd
            if (
                margin_micros < settings.minimum_public_margin_cents * 10_000
                or margin_micros * 2 < price_micros
            ):
                errors.append(f"{service_id} does not meet the configured public margin")
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


def _payer_identity_hash(settings: Settings, payer: str) -> str:
    salt = settings.admin_api_token or "reachsocial-public-test"
    return hashlib.sha256(f"payer:{payer.lower()}:{salt}".encode()).hexdigest()


def _reserve_verified_payer_daily_limit(session: Any, *, settings: Settings, payer: str) -> bool:
    """Reserve a verified payer's daily quota before x402 can settle.

    An after-verify hook runs before the x402 middleware invokes its settlement
    endpoint.  Keeping this durable check here ensures capacity rejections
    never arrive after a transfer.
    """
    identity = _payer_identity_hash(settings, payer)
    day = datetime.now(UTC).date().isoformat()
    result = session.execute(
        update(PublicTestUsage)
        .where(
            PublicTestUsage.usage_day == day,
            PublicTestUsage.identity_kind == "payer",
            PublicTestUsage.identity_hash == identity,
            PublicTestUsage.request_count < settings.public_test_daily_requests_per_identity,
        )
        .values(request_count=PublicTestUsage.request_count + 1)
    )
    if result.rowcount:
        return True
    if session.scalar(
        select(PublicTestUsage.id).where(
            PublicTestUsage.usage_day == day,
            PublicTestUsage.identity_kind == "payer",
            PublicTestUsage.identity_hash == identity,
        )
    ):
        return False
    session.add(
        PublicTestUsage(
            usage_day=day,
            identity_kind="payer",
            identity_hash=identity,
            request_count=1,
        )
    )
    return True


def usdc_atomic_to_cents(amount: object) -> int:
    """Convert Base USDC's six-decimal atomic amount to whole cents."""
    try:
        return int(str(amount)) // 10_000
    except (TypeError, ValueError):
        return 0


def reserve_payment_receipt(
    context: Any,
    *,
    settings: Settings | None = None,
    catalog: Catalog | None = None,
) -> AbortResult | None:
    """Reserve a verified payment before provider execution to reject replay."""
    payment_id = payment_id_from_payload(context.payment_payload)
    from .mcp_requests import expected_mcp_payer
    expected_payer = expected_mcp_payer.get()
    if expected_payer and str(getattr(context.result, "payer", "")).lower() != expected_payer:
        return AbortResult("mcp_payer_mismatch", "Pay using the wallet that owns this request")
    settings = settings or get_settings()
    service_id = _context_service_id(context)
    service = catalog.by_id(service_id) if catalog else None
    reserves_scrapecreators = (
        settings.x402_network == MAINNET_CANARY_NETWORK
        and service is not None
        and service.provider.name == "scrapecreators"
    )
    observed_balance: int | None = None
    if reserves_scrapecreators:
        try:
            observed_balance = fetch_provider_balance(settings)
        except ProviderBalanceUnavailable:
            logging.getLogger("reachsocial").warning(
                "operational_alert kind=provider_credit_balance_unavailable service=%s",
                service_id,
            )
            return AbortResult(
                "provider_credit_balance_unavailable",
                "Public provider capacity could not be verified",
            )
    with SessionLocal() as session:
        if session.bind and session.bind.dialect.name == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        existing = session.scalar(
            select(PaymentReceipt).where(PaymentReceipt.payment_id == payment_id)
        )
        if existing is not None:
            logging.getLogger("reachsocial").warning(
                "operational_alert kind=payment_replay service=%s", existing.service_id
            )
            return AbortResult("payment_replayed", "This payment has already been used")
        payer = str(getattr(context.result, "payer", "")).strip()
        if not payer or not _reserve_verified_payer_daily_limit(
            session, settings=settings, payer=payer
        ):
            session.rollback()
            logging.getLogger("reachsocial").warning(
                "operational_alert kind=public_payment_daily_limit service=%s", service_id
            )
            return AbortResult(
                "public_payment_daily_limit_reached",
                "The public payment request limit has been reached for today",
            )
        if reserves_scrapecreators and not reserve_credit_reservation(
            session,
            payment_id=payment_id,
            service=service,
            settings=settings,
            observed_balance=observed_balance,
            lock=False,
        ):
            from .models import ProviderCreditReservation

            duplicate = session.scalar(
                select(ProviderCreditReservation).where(
                    ProviderCreditReservation.payment_id == payment_id
                )
            )
            if duplicate is not None:
                return AbortResult("payment_replayed", "This payment has already been used")
            logging.getLogger("reachsocial").warning(
                "operational_alert kind=provider_credit_capacity service=%s", service_id
            )
            return AbortResult(
                "provider_credit_capacity_reached",
                "Public provider credit capacity is currently reserved",
            )
        session.add(
            PaymentReceipt(
                payment_id=payment_id,
                service_id=service_id,
                amount_cents=usdc_atomic_to_cents(getattr(context.requirements, "amount", None)),
                network=str(context.requirements.network),
                status="verified",
                payer=payer,
                details=_details(
                    payer=payer,
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
        return AbortResult(
            "mainnet_canary_buyer_rejected", "This buyer is not approved for the canary"
        )
    if (
        path != MAINNET_CANARY_PATH
        or network != MAINNET_CANARY_NETWORK
        or asset.lower() != MAINNET_CANARY_USDC_ASSET.lower()
        or amount != str(MAINNET_CANARY_AMOUNT_ATOMIC)
    ):
        return AbortResult(
            "mainnet_canary_requirement_rejected", "The canary requirement is invalid"
        )

    payment_id = payment_id_from_payload(context.payment_payload)
    with SessionLocal() as session:
        if session.scalar(select(PaymentReceipt).where(PaymentReceipt.payment_id == payment_id)):
            return AbortResult("payment_replayed", "This payment has already been used")
        if session.scalar(
            select(MainnetCanaryAttempt).where(
                MainnetCanaryAttempt.canary_key == MAINNET_CANARY_KEY
            )
        ):
            return AbortResult(
                "mainnet_canary_already_used", "The mainnet canary has already been used"
            )
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
            return AbortResult(
                "mainnet_canary_already_used", "The mainnet canary has already been used"
            )
    return None


def reserve_mainnet_acceptance(
    context: Any, *, expected_payer: str, settings: Settings, catalog: Catalog
) -> AbortResult | None:
    """Reserve one exact mainnet payment per named route before settlement."""
    payer = str(getattr(context.result, "payer", ""))
    request = getattr(getattr(context, "transport_context", None), "request", None)
    path = getattr(request, "path", "")
    service_id = MAINNET_ACCEPTANCE_ROUTES.get(f"POST {path}")
    service = catalog.by_id(service_id) if service_id else None
    amount = str(getattr(context.requirements, "amount", ""))
    network = str(getattr(context.requirements, "network", ""))
    asset = str(getattr(context.requirements, "asset", ""))
    if payer.lower() != expected_payer.lower():
        return AbortResult(
            "mainnet_acceptance_buyer_rejected", "This buyer is not approved for acceptance"
        )
    if (
        service is None
        or network != MAINNET_CANARY_NETWORK
        or asset.lower() != MAINNET_CANARY_USDC_ASSET.lower()
        or amount != str(service.price_cents * 10_000)
    ):
        return AbortResult(
            "mainnet_acceptance_requirement_rejected", "The acceptance requirement is invalid"
        )

    payment_id = payment_id_from_payload(context.payment_payload)
    acceptance_key = f"{MAINNET_ACCEPTANCE_KEY_PREFIX}:{service_id}"
    with SessionLocal() as session:
        if session.bind and session.bind.dialect.name == "sqlite" and not session.in_transaction():
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        if session.scalar(select(PaymentReceipt).where(PaymentReceipt.payment_id == payment_id)):
            return AbortResult("payment_replayed", "This payment has already been used")
        if session.scalar(
            select(MainnetCanaryAttempt).where(MainnetCanaryAttempt.canary_key == acceptance_key)
        ):
            return AbortResult(
                "mainnet_acceptance_route_already_used",
                "This acceptance route has already been used",
            )
        if service.provider.name == "scrapecreators" and not reserve_credit_reservation(
            session,
            payment_id=payment_id,
            service=service,
            settings=settings,
            lock=False,
        ):
            return AbortResult(
                "provider_credit_capacity_reached",
                "Public provider credit capacity is currently reserved",
            )
        session.add(
            PaymentReceipt(
                payment_id=payment_id,
                service_id=service_id,
                amount_cents=service.price_cents,
                network=network,
                status="verified",
                payer=payer,
                details=_details(payer=payer, amount=amount, mainnet_acceptance=True),
            )
        )
        session.add(
            MainnetCanaryAttempt(
                canary_key=acceptance_key,
                payment_id=payment_id,
                payer=payer,
                status="verified",
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return AbortResult(
                "mainnet_acceptance_route_already_used",
                "This acceptance route has already been used",
            )
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
    with SessionLocal() as session:
        finalize_credit_reservation(session, payment_id)
    logging.getLogger("reachsocial").info(
        "payment_settled service=%s network=%s",
        _context_service_id(context),
        context.result.network,
    )


def mark_payment_canceled(context: Any) -> None:
    """Keep uncertain settlement durable for manual reconciliation.

    The facilitator callback does not prove that a submitted transfer was not
    broadcast.  A support operator can later reconcile the transaction; this
    callback must never call it canceled or trigger another charge.
    """
    payment_id = payment_id_from_payload(context.payment_payload)
    with SessionLocal() as session:
        receipt = session.scalar(
            select(PaymentReceipt).where(PaymentReceipt.payment_id == payment_id)
        )
        if receipt is not None:
            receipt.status = "reconciliation_required"
            receipt.details = _details(
                payer=receipt.payer,
                transaction=receipt.transaction,
                outcome="settlement_uncertain",
                reason=getattr(context, "reason", "settlement_failed"),
            )
            session.commit()
    with SessionLocal() as session:
        finalize_credit_reservation(session, payment_id)
    logging.getLogger("reachsocial").warning(
        "operational_alert kind=payment_reconciliation_required service=%s",
        _context_service_id(context),
    )


def mark_verified_payment_canceled(context: Any) -> None:
    """Record a handler rejection that occurred before settlement was attempted."""
    payment_id = payment_id_from_payload(context.payment_payload)
    with SessionLocal() as session:
        receipt = session.scalar(
            select(PaymentReceipt).where(PaymentReceipt.payment_id == payment_id)
        )
        if receipt is not None:
            receipt.status = "canceled_before_settlement"
            receipt.details = _details(
                payer=receipt.payer,
                transaction=None,
                outcome="verified_canceled_before_settlement",
                reason=getattr(context, "reason", "handler_failed"),
            )
            session.commit()
    from .credit_budget import release as release_credit_reservation

    with SessionLocal() as session:
        release_credit_reservation(session, payment_id)
    logging.getLogger("reachsocial").info(
        "payment_canceled_before_settlement service=%s", _context_service_id(context)
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


def mark_mainnet_acceptance_status(context: Any, status: str) -> None:
    payment_id = payment_id_from_payload(context.payment_payload)
    with SessionLocal() as session:
        attempt = session.scalar(
            select(MainnetCanaryAttempt).where(MainnetCanaryAttempt.payment_id == payment_id)
        )
        if attempt is not None and attempt.canary_key.startswith(MAINNET_ACCEPTANCE_KEY_PREFIX):
            attempt.status = status
            session.commit()


def mark_mainnet_acceptance_settled(context: Any) -> None:
    mark_payment_settled(context)
    mark_mainnet_acceptance_status(context, "settled")


def mark_mainnet_acceptance_canceled(context: Any) -> None:
    mark_payment_canceled(context)
    mark_mainnet_acceptance_status(context, "reconciliation_required")


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
    server.on_after_verify(
        lambda context: reserve_payment_receipt(context, settings=settings, catalog=catalog)
    )
    server.on_after_settle(mark_payment_settled)
    server.on_settle_failure(mark_payment_canceled)
    server.on_verified_payment_canceled(mark_verified_payment_canceled)
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


def create_mainnet_acceptance_payment_handler(settings: Settings, catalog: Catalog):
    """Build the hidden three-route handler for a bounded independent-buyer test."""
    if not x402_is_configured(settings):
        raise ValueError("Mainnet acceptance requires the configured CDP x402 facilitator")
    errors = mainnet_acceptance_safety_errors(settings, catalog)
    if errors:
        raise ValueError("Base mainnet acceptance is blocked: " + "; ".join(errors))
    facilitator_config = create_facilitator_config(
        api_key_id=settings.cdp_api_key_id,
        api_key_secret=settings.cdp_api_key_secret,
    )
    server = x402ResourceServer(HTTPFacilitatorClient(facilitator_config))
    server.register(MAINNET_CANARY_NETWORK, ExactEvmServerScheme())
    server.on_after_verify(
        lambda context: reserve_mainnet_acceptance(
            context,
            expected_payer=settings.mainnet_x402_acceptance_buyer,
            settings=settings,
            catalog=catalog,
        )
    )
    server.on_after_settle(mark_mainnet_acceptance_settled)
    server.on_settle_failure(mark_mainnet_acceptance_canceled)
    server.on_verified_payment_canceled(mark_mainnet_acceptance_canceled)
    routes = {}
    for route, service_id in MAINNET_ACCEPTANCE_ROUTES.items():
        service = catalog.by_id(service_id)
        assert service is not None
        routes[route] = RouteConfig(
            accepts=PaymentOption(
                scheme="exact",
                pay_to=settings.x402_pay_to,
                price=f"${service.price_cents / 100:.2f}",
                network=MAINNET_CANARY_NETWORK,
            ),
            description="Bounded ReachSocial Base-mainnet acceptance",
            mime_type="application/json",
        )
    return payment_middleware(routes=routes, server=server)


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
        idempotency_key = request.headers.get("idempotency-key")
        expected_payer = None
        if get_settings().oauth_enabled and service and idempotency_key and idempotency_key.startswith("mcp_"):
            from .mcp_requests import guard_payment
            try:
                expected_payer = await guard_payment(request, service, idempotency_key)
            except HTTPException as error:
                return JSONResponse({"error": {"code": "mcp_payment_rejected", "message": error.detail}}, status_code=error.status_code)
        if idempotency_key and service and _has_paid_idempotency_recovery(service, idempotency_key):
            return await call_next(request)
        if service:
            global_pause = (
                "operator_pause"
                if request.app.state.settings.public_payments_paused
                else request.app.state.runtime.public_payments_paused_reason
            )
            service_pause = request.app.state.runtime.public_service_payment_pause_reason(service)
            if global_pause or service_pause:
                service_scoped = global_pause is None
                return JSONResponse(
                    {
                        "error": {
                            "code": (
                                "service_temporarily_unavailable"
                                if service_scoped
                                else "payments_paused"
                            ),
                            "message": (
                                "This service is temporarily unavailable before payment"
                                if service_scoped
                                else "New public payments are temporarily paused"
                            ),
                            "retryable": True,
                        }
                    },
                    status_code=503,
                )
        if credit and service:
            from .jobs import credit_is_valid

            if definition and credit_is_valid(credit, service, definition.price_cents):
                return await call_next(request)
        if service and not idempotency_key:
            return JSONResponse(
                {
                    "error": {
                        "code": "idempotency_key_required",
                        "message": "Anonymous paid calls require an Idempotency-Key for result recovery",
                        "retryable": False,
                    }
                },
                status_code=400,
            )
        if service and (len(idempotency_key) < 32 or len(idempotency_key) > 255):
            return JSONResponse(
                {
                    "error": {
                        "code": "idempotency_key_too_weak",
                        "message": (
                            "New anonymous paid calls require a random Idempotency-Key "
                            "of 32 to 255 characters"
                        ),
                        "retryable": False,
                    }
                },
                status_code=400,
            )
        if service and _has_payment_signature(request):
            try:
                await reserve_pre_settlement_public_limit(request)
            except ReachSocialError as error:
                return JSONResponse(
                    {
                        "error": {
                            "code": error.code,
                            "message": error.message,
                            "retryable": error.retryable,
                        }
                    },
                    status_code=error.status_code,
                )
        if expected_payer and service and idempotency_key:
            try:
                await guard_payment(request, service, idempotency_key, dispatch=True)
            except HTTPException as error:
                return JSONResponse({"error": {"code": "mcp_payment_rejected", "message": error.detail}}, status_code=error.status_code)
        from .mcp_requests import expected_mcp_payer
        context_token = expected_mcp_payer.set(expected_payer)
        try:
            return await self._payment_handler(request, call_next)
        finally:
            expected_mcp_payer.reset(context_token)


def _has_payment_signature(request: Request) -> bool:
    return bool(request.headers.get("payment-signature") or request.headers.get("x-payment"))


async def reserve_pre_settlement_public_limit(request: Request) -> None:
    """Apply the IP rate and daily limits before a signed payment is verified."""
    # Import lazily to avoid the api -> payments import cycle during app startup.
    from .api import enforce_public_test_limits

    with SessionLocal() as session:
        await enforce_public_test_limits(request, session, None)


def _has_paid_idempotency_recovery(service_id: str, idempotency_key: str) -> bool:
    """Allow a lost-response retry to reach its already-paid result, never a new run."""
    if not idempotency_key or len(idempotency_key) > 255:
        return False
    with SessionLocal() as session:
        client = session.scalar(select(Client).where(Client.name == PUBLIC_X402_CLIENT_NAME))
        if client is None:
            return False
        request_id: str | None = None
        job_id: str | None = None
        job = session.scalar(
            select(AsyncJob).where(
                AsyncJob.client_id == client.id,
                AsyncJob.service_id == service_id,
                AsyncJob.idempotency_key == idempotency_key,
            )
        )
        if job is not None:
            job_id = job.job_id
        else:
            record = session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.client_id == client.id,
                    IdempotencyRecord.service_id == service_id,
                    IdempotencyRecord.key == idempotency_key,
                )
            )
            if record is None:
                return False
            request_id = str(record.response_json.get("request_id") or "") or None
        receipt = session.scalar(
            select(PaymentReceipt).where(
                PaymentReceipt.request_id == request_id
                if request_id
                else PaymentReceipt.job_id == job_id
            )
        )
        return bool(
            receipt and receipt.status in {"verified", "settled", "reconciliation_required"}
        )


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


class MainnetAcceptanceX402Middleware(BaseHTTPMiddleware):
    """Expose only the named mainnet acceptance routes to the x402 handler."""

    def __init__(self, app, *, settings: Settings, catalog: Catalog):  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._payment_handler = create_mainnet_acceptance_payment_handler(settings, catalog)

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        route = f"{request.method} {request.url.path}"
        if route not in MAINNET_ACCEPTANCE_ROUTES:
            return await call_next(request)
        if is_b2b_request(request) or request.headers.get("x-service-credit"):
            return Response(status_code=403)
        return await self._payment_handler(request, call_next)
