from __future__ import annotations

import re

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .catalog import Catalog

_SERVICE_PATH = re.compile(r"^/v1/services/([a-z0-9._-]+)/execute$")
_RECOVERY_PATH = re.compile(r"^/v1/payments/recover/([a-z0-9._-]+)$")

_ALLOWED_REQUEST_HEADERS = frozenset(
    {
        "content-type",
        "idempotency-key",
        "payment-signature",
        "x-payment",
        # @x402/fetch currently adds this request header on its paid retry.
        "access-control-expose-headers",
    }
)
_EXPOSED_HEADERS = ", ".join(
    (
        "PAYMENT-REQUIRED",
        "PAYMENT-RESPONSE",
        "X-PAYMENT-REQUIRED",
        "X-PAYMENT-RESPONSE",
        "Retry-After",
        "X-Request-ID",
    )
)


class PublicApiCorsMiddleware:
    """Allow browser use only for public discovery, sync execution, and recovery."""

    def __init__(self, app: ASGIApp, *, catalog: Catalog) -> None:
        self.app = app
        self.public_sync_services = frozenset(
            service.id for service in catalog.public_services() if not service.is_async
        )

    def _allowed_method(self, path: str) -> str | None:
        if path in {"/status.json", "/v1/services"}:
            return "GET"
        match = _SERVICE_PATH.fullmatch(path) or _RECOVERY_PATH.fullmatch(path)
        if match and match.group(1) in self.public_sync_services:
            return "POST"
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        origin = headers.get("origin")
        allowed_method = self._allowed_method(scope["path"])
        if not origin or allowed_method is None:
            await self.app(scope, receive, send)
            return

        if scope["method"] == "OPTIONS":
            requested_method = headers.get("access-control-request-method", "").upper()
            requested_headers = {
                item.strip().lower()
                for item in headers.get("access-control-request-headers", "").split(",")
                if item.strip()
            }
            if requested_method != allowed_method or not requested_headers.issubset(
                _ALLOWED_REQUEST_HEADERS
            ):
                await Response(status_code=403)(scope, receive, send)
                return
            response = Response(status_code=204)
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = allowed_method
            response.headers["Access-Control-Allow-Headers"] = ", ".join(
                sorted(_ALLOWED_REQUEST_HEADERS)
            )
            response.headers["Access-Control-Max-Age"] = "600"
            await response(scope, receive, send)
            return

        if scope["method"] != allowed_method:
            await self.app(scope, receive, send)
            return

        async def send_with_cors(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers["Access-Control-Allow-Origin"] = "*"
                response_headers["Access-Control-Expose-Headers"] = _EXPOSED_HEADERS
            await send(message)

        await self.app(scope, receive, send_with_cors)
