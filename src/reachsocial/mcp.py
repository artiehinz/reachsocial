from __future__ import annotations

import contextvars
from typing import Any

from mcp.server import MCPServer
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .api import _api_key_from_header
from .catalog import Catalog, ServiceDefinition
from .db import SessionLocal
from .models import Client
from .runtime import RuntimeState
from .security import verify_api_key
from .services import ExecutionService

current_mcp_client_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "current_mcp_client_id", default=None
)


class MCPB2BAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        api_key = _api_key_from_header(request.headers.get("authorization"))
        if not api_key:
            return JSONResponse({"error": {"code": "unauthenticated"}}, status_code=401)
        with SessionLocal() as session:
            client = next(
                (
                    row
                    for row in session.scalars(select(Client).where(Client.status == "active"))
                    if verify_api_key(api_key, row.api_key_hash)
                ),
                None,
            )
            if client is None:
                return JSONResponse({"error": {"code": "unauthenticated"}}, status_code=401)
            token = current_mcp_client_id.set(client.id)
        try:
            return await call_next(request)
        finally:
            current_mcp_client_id.reset(token)


def _tool_for(service: ServiceDefinition, executor: ExecutionService):
    async def execute(url: str) -> dict[str, Any]:
        client_id = current_mcp_client_id.get()
        if client_id is None:
            raise RuntimeError("A B2B API key is required")
        with SessionLocal() as session:
            client = session.get(Client, client_id)
            if client is None:
                raise RuntimeError("Client no longer exists")
            return await executor.execute(
                session,
                client=client,
                service_id=service.id,
                input_data={"url": url},
            )

    execute.__name__ = service.id.replace(".", "_").replace("-", "_")
    execute.__doc__ = service.description
    return execute


def make_mcp_app(catalog: Catalog):
    server = MCPServer(
        name="ReachSocial",
        title="ReachSocial social data",
        description="Provider-neutral social data tools for authenticated B2B clients.",
        instructions="Use a listed service tool with a canonical public social URL.",
    )
    executor = ExecutionService(catalog, RuntimeState())
    for service in catalog.public_services():
        server.add_tool(_tool_for(service, executor), name=service.id.replace(".", "_"))
    app = server.streamable_http_app(
        streamable_http_path="/", json_response=True, stateless_http=True
    )
    app.add_middleware(MCPB2BAuthMiddleware)
    return app
