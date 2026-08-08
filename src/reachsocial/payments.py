from __future__ import annotations

from fastapi import HTTPException

from .catalog import ServiceDefinition
from .config import Settings


def require_x402_payment(service: ServiceDefinition, settings: Settings) -> None:
    """Fail closed until a real x402 verifier/facilitator is configured."""
    if not settings.x402_enabled:
        raise HTTPException(
            status_code=503,
            detail={"code": "payments_disabled", "message": "Public payments are not enabled"},
        )
    if not settings.x402_pay_to or not settings.x402_facilitator_url:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "payments_unconfigured",
                "message": "Payment verifier is not configured",
            },
        )
    price_usdc = f"{service.price_cents / 100:.2f}"
    raise HTTPException(
        status_code=402,
        detail={
            "code": "payment_required",
            "service": service.id,
            "amount_usdc": price_usdc,
            "network": settings.x402_network,
            "pay_to": settings.x402_pay_to,
        },
        headers={"PAYMENT-REQUIRED": "true"},
    )
