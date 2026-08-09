from __future__ import annotations

import contextvars
from typing import Any, Awaitable, Callable

from mcp.server import MCPServer
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .api import _api_key_from_header, client_for_api_key
from .catalog import Catalog, ServiceDefinition
from .db import SessionLocal
from .jobs import authorize_job, job_payload, submit_job
from .models import AsyncJob, Client
from .runtime import RuntimeState
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
            client = client_for_api_key(session, api_key)
            if client is None:
                return JSONResponse({"error": {"code": "unauthenticated"}}, status_code=401)
            token = current_mcp_client_id.set(client.id)
        try:
            return await call_next(request)
        finally:
            current_mcp_client_id.reset(token)


def _current_client(session: Session) -> Client:
    client_id = current_mcp_client_id.get()
    if client_id is None:
        raise RuntimeError("A B2B API key is required")
    client = session.get(Client, client_id)
    if client is None or client.status != "active":
        raise RuntimeError("Client no longer exists")
    return client


def _input_data(
    service: ServiceDefinition,
    *,
    url: str,
    max_items: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    field_names = {field.name for field in service.input_fields}
    value: dict[str, Any] = {"url": url}
    if "max_items" in field_names and max_items is not None:
        value["max_items"] = max_items
    if "cursor" in field_names and cursor is not None:
        value["cursor"] = cursor
    return value


async def _execute_sync(
    service: ServiceDefinition,
    executor: ExecutionService,
    *,
    url: str,
    idempotency_key: str,
    max_items: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    with SessionLocal() as session:
        return await executor.execute(
            session,
            client=_current_client(session),
            service_id=service.id,
            input_data=_input_data(
                service, url=url, max_items=max_items, cursor=cursor
            ),
            idempotency_key=idempotency_key,
        )


def _submit_async(
    service: ServiceDefinition,
    executor: ExecutionService,
    *,
    url: str,
    idempotency_key: str,
    max_items: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    with SessionLocal() as session:
        job, _token = submit_job(
            session,
            executor=executor,
            client=_current_client(session),
            service_id=service.id,
            input_data=_input_data(
                service, url=url, max_items=max_items, cursor=cursor
            ),
            anonymous=False,
            idempotency_key=idempotency_key,
        )
        payload = job_payload(job)
        payload["status_url"] = f"/v1/jobs/{job.job_id}"
        return payload


ToolCallable = Callable[..., Awaitable[dict[str, Any]]]


def _sync_tool_for(service: ServiceDefinition, executor: ExecutionService) -> ToolCallable:
    fields = {field.name for field in service.input_fields}
    if "cursor" in fields:

        async def execute(
            url: str,
            idempotency_key: str,
            max_items: int = 20,
            cursor: str | None = None,
        ) -> dict[str, Any]:
            return await _execute_sync(
                service,
                executor,
                url=url,
                idempotency_key=idempotency_key,
                max_items=max_items,
                cursor=cursor,
            )

    elif "max_items" in fields:

        async def execute(  # type: ignore[no-redef]
            url: str, idempotency_key: str, max_items: int = 20
        ) -> dict[str, Any]:
            return await _execute_sync(
                service,
                executor,
                url=url,
                idempotency_key=idempotency_key,
                max_items=max_items,
            )

    else:

        async def execute(  # type: ignore[no-redef]
            url: str, idempotency_key: str
        ) -> dict[str, Any]:
            return await _execute_sync(
                service, executor, url=url, idempotency_key=idempotency_key
            )

    execute.__name__ = service.id.replace(".", "_").replace("-", "_")
    execute.__doc__ = (
        f"{service.description} Requires an approved B2B entitlement and a stable "
        "idempotency key for safe retries."
    )
    return execute


def _async_tool_for(service: ServiceDefinition, executor: ExecutionService) -> ToolCallable:
    fields = {field.name for field in service.input_fields}
    if "cursor" in fields:

        async def start(
            url: str,
            idempotency_key: str,
            max_items: int = 20,
            cursor: str | None = None,
        ) -> dict[str, Any]:
            return _submit_async(
                service,
                executor,
                url=url,
                idempotency_key=idempotency_key,
                max_items=max_items,
                cursor=cursor,
            )

    elif "max_items" in fields:

        async def start(  # type: ignore[no-redef]
            url: str, idempotency_key: str, max_items: int = 20
        ) -> dict[str, Any]:
            return _submit_async(
                service,
                executor,
                url=url,
                idempotency_key=idempotency_key,
                max_items=max_items,
            )

    else:

        async def start(  # type: ignore[no-redef]
            url: str, idempotency_key: str
        ) -> dict[str, Any]:
            return _submit_async(
                service, executor, url=url, idempotency_key=idempotency_key
            )

    start.__name__ = "start_" + service.id.replace(".", "_").replace("-", "_")
    start.__doc__ = (
        f"Start {service.description.lower()} Return a durable job ID and poll it with "
        "get_reachsocial_job; never repeat a pending submission."
    )
    return start


async def get_reachsocial_job(job_id: str) -> dict[str, Any]:
    """Get a B2B job owned by the authenticated client until it reaches a terminal state."""
    with SessionLocal() as session:
        client = _current_client(session)
        job = session.scalar(select(AsyncJob).where(AsyncJob.job_id == job_id))
        if job is None:
            raise RuntimeError("Job not found")
        authorize_job(job, client=client, job_token=None)
        payload = job_payload(job)
        session.commit()
        return payload


def make_mcp_server(catalog: Catalog, executor: ExecutionService | None = None) -> MCPServer:
    server = MCPServer(
        name="ReachSocial",
        title="ReachSocial social data",
        description="Provider-neutral social data tools for authenticated B2B clients.",
        instructions=(
            "Choose the smallest available service. Supply a canonical public URL and a stable "
            "idempotency key. Poll asynchronous jobs; never recreate pending work."
        ),
        website_url="https://reachsocial.dev",
        version="0.2.0",
    )
    active_executor = executor or ExecutionService(catalog, RuntimeState())
    has_async = False
    for service in catalog.public_services():
        if service.is_async:
            has_async = True
            server.add_tool(
                _async_tool_for(service, active_executor),
                name="start_" + service.id.replace(".", "_"),
                description=service.description,
                structured_output=True,
            )
        else:
            server.add_tool(
                _sync_tool_for(service, active_executor),
                name=service.id.replace(".", "_"),
                description=service.description,
                structured_output=True,
            )
    if has_async:
        server.add_tool(
            get_reachsocial_job,
            name="get_reachsocial_job",
            description="Poll an authenticated ReachSocial asynchronous job.",
            structured_output=True,
        )
    return server


def make_mcp_app(catalog: Catalog):
    app = make_mcp_server(catalog).streamable_http_app(
        streamable_http_path="/", json_response=True, stateless_http=True
    )
    app.add_middleware(MCPB2BAuthMiddleware)
    return app
