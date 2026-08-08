from __future__ import annotations

import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .catalog import Catalog, ServiceDefinition
from .db import get_session
from .models import Client, RequestLog
from .normalizer import resolve_url
from .payments import require_x402_payment
from .security import verify_api_key
from .services import ExecutionService

router = APIRouter(prefix="/v1", tags=["API"])


class ExecuteRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)


def service_summary(
    service: ServiceDefinition, *, include_internal: bool = False
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "id": service.id,
        "title": service.title,
        "platform": service.platform,
        "description": service.description,
        "inputs": [field.model_dump() for field in service.input_fields],
        "price_cents": service.price_cents,
        "docs": service.docs,
    }
    if include_internal:
        value.update(
            {
                "enabled": service.enabled,
                "public": service.public,
                "provider": service.provider.name,
                "timeout_seconds": service.timeout_seconds,
            }
        )
    return value


def _api_key_from_header(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


def optional_client(
    authorization: Annotated[str | None, Header()] = None,
    session: Session = Depends(get_session),
) -> Client | None:
    api_key = _api_key_from_header(authorization)
    if not api_key:
        return None
    for client in session.scalars(select(Client).where(Client.status == "active")):
        if verify_api_key(api_key, client.api_key_hash):
            return client
    raise HTTPException(
        status_code=401, detail={"code": "unauthenticated", "message": "Invalid API key"}
    )


def require_client(client: Client | None = Depends(optional_client)) -> Client:
    if client is None:
        raise HTTPException(
            status_code=401, detail={"code": "unauthenticated", "message": "API key required"}
        )
    return client


def require_admin(
    request: Request,
    admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
) -> None:
    expected = request.app.state.settings.admin_api_token
    if not expected or not admin_token or not hmac.compare_digest(admin_token, expected):
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Not found"})


def get_catalog(request: Request) -> Catalog:
    return request.app.state.catalog


def get_executor(request: Request) -> ExecutionService:
    return request.app.state.executor


@router.get("/services")
def list_services(catalog: Catalog = Depends(get_catalog)) -> dict[str, list[dict[str, Any]]]:
    return {"services": [service_summary(service) for service in catalog.public_services()]}


@router.get("/services/{service_id}")
def get_service(service_id: str, catalog: Catalog = Depends(get_catalog)) -> dict[str, Any]:
    service = catalog.by_id(service_id)
    if service is None or not (service.enabled and service.public):
        raise HTTPException(
            status_code=404, detail={"code": "unknown_service", "message": "Unknown service"}
        )
    return service_summary(service)


@router.post("/resolve")
def resolve(request: ExecuteRequest, _client: Client = Depends(require_client)) -> dict[str, str]:
    return resolve_url(request.input.get("url"))


@router.post("/services/{service_id}/execute")
async def execute_service(
    service_id: str,
    body: ExecuteRequest,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    client: Client | None = Depends(optional_client),
    session: Session = Depends(get_session),
    catalog: Catalog = Depends(get_catalog),
    executor: ExecutionService = Depends(get_executor),
) -> dict[str, Any]:
    service = catalog.by_id(service_id)
    if service is None:
        raise HTTPException(
            status_code=404, detail={"code": "unknown_service", "message": "Unknown service"}
        )
    if client is None:
        if not service.public:
            raise HTTPException(
                status_code=401, detail={"code": "unauthenticated", "message": "API key required"}
            )
        require_x402_payment(service, request.app.state.settings)
    return await executor.execute(
        session,
        client=client,
        service_id=service_id,
        input_data=body.input,
        idempotency_key=idempotency_key,
    )


@router.get("/owner/overview")
def owner_overview(
    session: Session = Depends(get_session),
    catalog: Catalog = Depends(get_catalog),
    _admin: None = Depends(require_admin),
) -> dict[str, Any]:
    """This route is additionally protected by Caddy Basic Auth in production."""
    requests = session.scalar(select(func.count(RequestLog.id))) or 0
    errors = (
        session.scalar(select(func.count(RequestLog.id)).where(RequestLog.status == "error")) or 0
    )
    return {
        "clients": session.scalar(select(func.count(Client.id))) or 0,
        "requests": requests,
        "errors": errors,
        "enabled_services": len([service for service in catalog.services if service.enabled]),
    }
