import asyncio

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from reachsocial.observability import RequestBodyLimitMiddleware, RequestBodyTooLarge


def limited_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(RequestBodyTooLarge)
    async def too_large(_request: Request, _error: RequestBodyTooLarge) -> JSONResponse:
        return JSONResponse({"error": {"code": "request_too_large"}}, status_code=413)

    @app.post("/")
    async def consume(request: Request) -> dict[str, int]:
        return {"bytes": len(await request.body())}

    return app


def test_request_limit_rejects_content_length_and_oversized_payment_headers() -> None:
    async def status_for(headers: list[tuple[bytes, bytes]]) -> int:
        app = RequestBodyLimitMiddleware(
            limited_app(), max_body_bytes=8, max_payment_header_bytes=8
        )
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/",
                "raw_path": b"/",
                "query_string": b"",
                "headers": headers,
                "client": ("127.0.0.1", 1),
                "server": ("testserver", 80),
            },
            receive,
            send,
        )
        return sent[0]["status"]

    assert asyncio.run(status_for([(b"content-length", b"9")])) == 413
    for name in (b"payment-signature", b"x-payment", b"payment-required"):
        assert asyncio.run(status_for([(name, b"x" * 9)])) == 431


def test_request_limit_counts_chunked_bodies_without_content_length() -> None:
    async def run() -> None:
        app = RequestBodyLimitMiddleware(
            limited_app(), max_body_bytes=8, max_payment_header_bytes=8
        )
        messages = iter(
            [
                {"type": "http.request", "body": b"01234", "more_body": True},
                {"type": "http.request", "body": b"56789", "more_body": False},
            ]
        )
        sent = []

        async def receive():
            return next(messages)

        async def send(message):
            sent.append(message)

        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/",
                "raw_path": b"/",
                "query_string": b"",
                "headers": [(b"content-type", b"application/octet-stream")],
                "client": ("127.0.0.1", 1),
                "server": ("testserver", 80),
            },
            receive,
            send,
        )
        assert sent[0]["status"] == 413

    asyncio.run(run())
