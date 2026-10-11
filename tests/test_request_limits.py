import asyncio

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

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
    app = RequestBodyLimitMiddleware(limited_app(), max_body_bytes=8, max_payment_header_bytes=8)
    client = TestClient(app)

    assert client.post("/", content=b"012345678").status_code == 413
    assert client.post("/", headers={"PAYMENT-SIGNATURE": "x" * 9}).status_code == 431


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
