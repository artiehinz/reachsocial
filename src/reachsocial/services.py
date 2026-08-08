from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .catalog import Catalog, ServiceDefinition
from .config import get_settings
from .errors import (
    DisabledService,
    IdempotencyConflict,
    InvalidInput,
    LimitExceeded,
    ReachSocialError,
    UnknownService,
)
from .models import Client, IdempotencyRecord, RequestLog, ServiceRecord
from .providers import adapter_for
from .runtime import RuntimeState


def stable_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def utcnow_naive() -> datetime:
    """SQLite stores naive datetimes; consistently treat them as UTC."""
    return datetime.now(UTC).replace(tzinfo=None)


def sync_service_records(session: Session, catalog: Catalog) -> None:
    for definition in catalog.services:
        record = session.scalar(
            select(ServiceRecord).where(ServiceRecord.service_id == definition.id)
        )
        if record is None:
            record = ServiceRecord(service_id=definition.id, provider=definition.provider.name)
            session.add(record)
        record.enabled = definition.enabled
        record.public = definition.public
        record.provider = definition.provider.name
        record.price_cents = definition.price_cents
    session.commit()


class ExecutionService:
    def __init__(self, catalog: Catalog, runtime: RuntimeState) -> None:
        self.catalog = catalog
        self.runtime = runtime

    @staticmethod
    def _validate_input(service: ServiceDefinition, input_data: dict[str, Any]) -> None:
        if not isinstance(input_data, dict):
            raise InvalidInput("Input must be an object")
        for field in service.input_fields:
            value = input_data.get(field.name)
            if field.required and (value is None or str(value).strip() == ""):
                raise InvalidInput(f"{field.name} is required")
            if value is not None and field.format == "url":
                from .normalizer import canonicalize_url

                input_data[field.name] = canonicalize_url(value)

    def _idempotent_response(
        self, session: Session, client: Client, service_id: str, key: str, input_hash: str
    ) -> dict[str, Any] | None:
        record = session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.client_id == client.id,
                IdempotencyRecord.service_id == service_id,
                IdempotencyRecord.key == key,
            )
        )
        if record is None or record.expires_at <= utcnow_naive():
            return None
        if record.input_hash != input_hash:
            raise IdempotencyConflict("Idempotency key was already used with different input")
        return record.response_json

    @staticmethod
    def _record(
        session: Session,
        *,
        request_id: str,
        client: Client,
        service: ServiceDefinition,
        status: str,
        input_hash: str,
        latency_ms: int | None = None,
        upstream_cost_cents: int = 0,
        cache_hit: bool = False,
        error_code: str | None = None,
    ) -> None:
        session.add(
            RequestLog(
                request_id=request_id,
                client_id=client.id,
                service_id=service.id,
                provider=service.provider.name,
                status=status,
                latency_ms=latency_ms,
                upstream_cost_cents=upstream_cost_cents,
                charged_cents=(
                    0
                    if client.billing_mode == "internal" or status != "success"
                    else service.price_cents
                ),
                cache_hit=cache_hit,
                error_code=error_code,
                input_hash=input_hash,
            )
        )
        session.commit()

    @staticmethod
    def _enforce_daily_spend(session: Session, client: Client, service: ServiceDefinition) -> None:
        if client.billing_mode == "internal":
            return
        start_of_day = utcnow_naive().replace(hour=0, minute=0, second=0, microsecond=0)
        spent = session.scalar(
            select(func.coalesce(func.sum(RequestLog.charged_cents), 0)).where(
                RequestLog.client_id == client.id,
                RequestLog.created_at >= start_of_day,
            )
        )
        if int(spent or 0) + service.price_cents > client.daily_spend_cents:
            raise LimitExceeded("Client daily spend limit exceeded")

    @staticmethod
    def _enforce_upstream_cost_cap(session: Session, service: ServiceDefinition) -> None:
        settings = get_settings()
        start_of_day = utcnow_naive().replace(hour=0, minute=0, second=0, microsecond=0)
        spent = session.scalar(
            select(func.coalesce(func.sum(RequestLog.upstream_cost_cents), 0)).where(
                RequestLog.created_at >= start_of_day,
            )
        )
        if (
            int(spent or 0) + service.estimated_upstream_cost_cents
            > settings.max_daily_upstream_cost_cents
        ):
            raise LimitExceeded("Global upstream spend limit exceeded")

    async def execute(
        self,
        session: Session,
        *,
        client: Client,
        service_id: str,
        input_data: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        service = self.catalog.by_id(service_id)
        if service is None:
            raise UnknownService("Unknown service")
        if not service.enabled:
            raise DisabledService("This service is not enabled")
        self._validate_input(service, input_data)
        input_hash = stable_hash(input_data)
        if idempotency_key:
            prior = self._idempotent_response(
                session, client, service_id, idempotency_key, input_hash
            )
            if prior is not None:
                return prior

        settings = get_settings()
        await self.runtime.acquire(
            client.id,
            provider=service.provider.name,
            per_minute=client.rate_limit_per_minute,
            concurrency=client.concurrency_limit,
            provider_concurrency=settings.provider_concurrency_limit,
        )
        request_id = f"req_{uuid.uuid4().hex}"
        cache_key = f"{service.id}:{input_hash}"
        started = time.perf_counter()
        try:
            self._enforce_daily_spend(session, client, service)
            cached = self.runtime.get_cached(cache_key)
            if cached is not None:
                response = {
                    "request_id": request_id,
                    "service": service.id,
                    "status": "success",
                    "cached": True,
                    "data": cached,
                    "meta": {"latency_ms": 0},
                }
                self._record(
                    session,
                    request_id=request_id,
                    client=client,
                    service=service,
                    status="success",
                    input_hash=input_hash,
                    cache_hit=True,
                )
            else:
                self._enforce_upstream_cost_cap(session, service)
                result = await adapter_for(service).execute(service, input_data)
                latency_ms = round((time.perf_counter() - started) * 1000)
                response = {
                    "request_id": request_id,
                    "service": service.id,
                    "status": "success",
                    "cached": False,
                    "data": result.data,
                    "meta": {"latency_ms": latency_ms},
                }
                self.runtime.set_cached(cache_key, result.data, service.effective_cache_ttl)
                self._record(
                    session,
                    request_id=request_id,
                    client=client,
                    service=service,
                    status="success",
                    input_hash=input_hash,
                    latency_ms=latency_ms,
                    upstream_cost_cents=result.upstream_cost_cents,
                )
            if idempotency_key:
                session.add(
                    IdempotencyRecord(
                        client_id=client.id,
                        service_id=service.id,
                        key=idempotency_key,
                        input_hash=input_hash,
                        response_json=response,
                        expires_at=utcnow_naive() + timedelta(hours=24),
                    )
                )
                session.commit()
            return response
        except ReachSocialError as error:
            latency_ms = round((time.perf_counter() - started) * 1000)
            self._record(
                session,
                request_id=request_id,
                client=client,
                service=service,
                status="error",
                input_hash=input_hash,
                latency_ms=latency_ms,
                error_code=error.code,
            )
            raise
        finally:
            await self.runtime.release(client.id, service.provider.name)
