from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, datetime

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestBodyTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    """Reject oversized request bodies before payment middleware parses them."""

    payment_headers = {b"payment-signature", b"payment-required"}

    def __init__(self, app: ASGIApp, *, max_body_bytes: int, max_payment_header_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.max_payment_header_bytes = max_payment_header_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name.lower() in self.payment_headers and len(value) > self.max_payment_header_bytes:
                await JSONResponse(
                    {
                        "error": {
                            "code": "header_too_large",
                            "message": "Payment header is too large",
                        }
                    },
                    status_code=431,
                )(scope, receive, send)
                return
            if name.lower() == b"content-length":
                try:
                    if int(value) > self.max_body_bytes:
                        await JSONResponse(
                            {
                                "error": {
                                    "code": "request_too_large",
                                    "message": "Request body is too large",
                                }
                            },
                            status_code=413,
                        )(scope, receive, send)
                        return
                except ValueError:
                    await JSONResponse(
                        {"error": {"code": "invalid_input", "message": "Invalid Content-Length"}},
                        status_code=400,
                    )(scope, receive, send)
                    return

        received_bytes = 0

        async def limited_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_body_bytes:
                    raise RequestBodyTooLarge
            return message

        await self.app(scope, limited_receive, send)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("request_id", "method", "path", "status_code", "latency_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, separators=(",", ":"))


def configure_logging() -> None:
    logger = logging.getLogger("reachsocial")
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("X-Request-ID") or f"http_{uuid.uuid4().hex}"
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        latency_ms = round((time.perf_counter() - started) * 1000)
        response.headers["X-Request-ID"] = request_id
        logging.getLogger("reachsocial").info(
            "request_complete",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "latency_ms": latency_ms,
            },
        )
        return response
