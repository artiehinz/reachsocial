from __future__ import annotations

from cdp.x402 import create_facilitator_config
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from x402.http import HTTPFacilitatorClient
from x402.http.middleware.fastapi import payment_middleware
from x402.http.types import HTTPRequestContext, PaymentOption, RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.server import x402ResourceServer

from .catalog import Catalog
from .config import Settings

PUBLIC_EXECUTE_ROUTE = "POST /v1/services/*/execute"
PUBLIC_X402_CLIENT_NAME = "x402-public"


def service_id_from_path(path: str) -> str | None:
    """Return the service ID from the canonical public execute path."""
    prefix = "/v1/services/"
    suffix = "/execute"
    if not path.startswith(prefix) or not path.endswith(suffix):
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

    facilitator_config = create_facilitator_config(
        api_key_id=settings.cdp_api_key_id,
        api_key_secret=settings.cdp_api_key_secret,
    )
    facilitator = HTTPFacilitatorClient(facilitator_config)
    server = x402ResourceServer(facilitator)
    server.register(settings.x402_network, ExactEvmServerScheme())
    return payment_middleware(
        routes={
            PUBLIC_EXECUTE_ROUTE: RouteConfig(
                accepts=PaymentOption(
                    scheme="exact",
                    pay_to=settings.x402_pay_to,
                    price=lambda context: price_for_public_execution(context, catalog),
                    network=settings.x402_network,
                ),
                description="ReachSocial public social-data API call",
                mime_type="application/json",
            )
        },
        server=server,
    )


class ReachSocialX402Middleware(BaseHTTPMiddleware):
    """Apply x402 to anonymous public calls while preserving B2B API-key access."""

    def __init__(self, app, *, settings: Settings, catalog: Catalog):  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._payment_handler = create_x402_payment_handler(settings, catalog)

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        if is_b2b_request(request):
            return await call_next(request)
        return await self._payment_handler(request, call_next)
