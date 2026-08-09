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
    AsyncRequired,
    DisabledService,
    IdempotencyConflict,
    InvalidInput,
    ReachSocialError,
    SpendLimitExceeded,
    TestCapacityReached,
    UnknownService,
)
from .models import (
    Client,
    ClientService,
    IdempotencyRecord,
    ProviderAttempt,
    RequestLog,
    ServiceRecord,
)
from .normalizer import validate_service_url
from .providers import ProviderResult, adapter_for
from .runtime import RuntimeState


def stable_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def utcnow_naive() -> datetime:
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


def client_can_access_service(session: Session, client: Client, service: ServiceDefinition) -> bool:
    entitlements = list(
        session.scalars(select(ClientService).where(ClientService.client_id == client.id))
    )
    if not entitlements:
        return service.public
    entitlement = next((item for item in entitlements if item.service_id == service.id), None)
    return bool(entitlement and entitlement.enabled)


class ExecutionService:
    def __init__(self, catalog: Catalog, runtime: RuntimeState) -> None:
        self.catalog = catalog
        self.runtime = runtime

    @staticmethod
    def validate_input(service: ServiceDefinition, input_data: dict[str, Any]) -> None:
        if not isinstance(input_data, dict):
            raise InvalidInput("Input must be an object")
        allowed = {field.name for field in service.input_fields}
        unknown = sorted(set(input_data) - allowed)
        if unknown:
            raise InvalidInput(f"Unknown input field(s): {', '.join(unknown)}")
        for field in service.input_fields:
            value = input_data.get(field.name)
            if value is None and field.default is not None:
                input_data[field.name] = field.default
                value = field.default
            if field.required and (value is None or str(value).strip() == ""):
                raise InvalidInput(f"{field.name} is required")
            if value is None:
                continue
            if (
                isinstance(value, str)
                and field.max_length is not None
                and len(value) > field.max_length
            ):
                raise InvalidInput(
                    f"{field.name} must be at most {field.max_length} characters"
                )
            if field.format == "url":
                input_data[field.name] = validate_service_url(service.id, value)
            elif field.format == "integer":
                if isinstance(value, bool):
                    raise InvalidInput(f"{field.name} must be an integer")
                if isinstance(value, float) and not value.is_integer():
                    raise InvalidInput(f"{field.name} must be an integer")
                try:
                    integer = int(value)
                except (TypeError, ValueError) as exc:
                    raise InvalidInput(f"{field.name} must be an integer") from exc
                if field.minimum is not None and integer < field.minimum:
                    raise InvalidInput(f"{field.name} must be at least {field.minimum}")
                if field.maximum is not None and integer > field.maximum:
                    raise InvalidInput(f"{field.name} must be at most {field.maximum}")
                input_data[field.name] = integer
            else:
                if not isinstance(value, str):
                    raise InvalidInput(f"{field.name} must be a string")

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
        result: ProviderResult | None = None,
        cache_hit: bool = False,
        error_code: str | None = None,
        charge_client: bool = True,
    ) -> None:
        upstream_micros = result.upstream_cost_microusd if result else 0
        session.add(
            RequestLog(
                request_id=request_id,
                client_id=client.id,
                service_id=service.id,
                provider=service.provider.name,
                status=status,
                latency_ms=latency_ms,
                upstream_cost_cents=round(upstream_micros / 10_000),
                upstream_cost_microusd=upstream_micros,
                provider_units=result.provider_units if result else 0,
                provider_unit_cost_microusd=result.provider_unit_cost_microusd if result else 0,
                provider_reference=result.provider_reference if result else None,
                price_snapshot_cents=service.price_cents,
                charged_cents=(
                    service.price_cents
                    if charge_client and client.billing_mode != "internal" and status == "success"
                    else 0
                ),
                cache_hit=cache_hit,
                error_code=error_code,
                input_hash=input_hash,
            )
        )
        session.commit()

    @staticmethod
    def _record_attempt(
        session: Session,
        *,
        request_id: str,
        service: ServiceDefinition,
        status: str,
        latency_ms: int,
        result: ProviderResult | None = None,
        error: ReachSocialError | None = None,
        public_test: bool = False,
    ) -> None:
        session.add(
            ProviderAttempt(
                request_id=request_id if request_id.startswith("req_") else None,
                job_id=request_id if request_id.startswith("job_") else None,
                service_id=service.id,
                provider=service.provider.name,
                provider_reference=(
                    result.provider_reference
                    if result
                    else getattr(error, "provider_reference", None)
                ),
                status=status,
                provider_units=(
                    result.provider_units if result else getattr(error, "provider_units", 0)
                ),
                provider_unit_cost_microusd=(
                    result.provider_unit_cost_microusd
                    if result
                    else getattr(error, "provider_unit_cost_microusd", 0)
                ),
                upstream_cost_microusd=(
                    result.upstream_cost_microusd
                    if result
                    else getattr(error, "upstream_cost_microusd", 0)
                ),
                public_test=public_test,
                error_code=error.code if error else None,
                latency_ms=latency_ms,
            )
        )
        session.commit()

    @staticmethod
    def _enforce_daily_spend(session: Session, client: Client, service: ServiceDefinition) -> None:
        if client.billing_mode == "internal":
            return
        start = utcnow_naive().replace(hour=0, minute=0, second=0, microsecond=0)
        spent = session.scalar(
            select(func.coalesce(func.sum(RequestLog.charged_cents), 0)).where(
                RequestLog.client_id == client.id,
                RequestLog.created_at >= start,
            )
        )
        if int(spent or 0) + service.price_cents > client.daily_spend_cents:
            raise SpendLimitExceeded("Client daily spend limit exceeded")

    @staticmethod
    def _public_upstream_commitment(
        session: Session,
    ) -> int:
        start = utcnow_naive().replace(hour=0, minute=0, second=0, microsecond=0)
        spent = session.scalar(
            select(func.coalesce(func.sum(ProviderAttempt.upstream_cost_microusd), 0)).where(
                ProviderAttempt.created_at >= start,
                ProviderAttempt.public_test.is_(True),
            )
        )
        from .models import AsyncJob

        queued = session.scalar(
            select(func.coalesce(func.sum(AsyncJob.reserved_upstream_cost_microusd), 0)).where(
                AsyncJob.status.in_(["queued", "running"]),
                AsyncJob.created_at >= start,
            )
        )
        return int(spent or 0) + int(queued or 0)

    @classmethod
    def _enforce_upstream_cost_cap(
        cls,
        session: Session, client: Client, service: ServiceDefinition
    ) -> int:
        if client.billing_mode == "internal":
            return 0
        settings = get_settings()
        estimate = max(
            service.estimated_upstream_cost_microusd,
            service.provider_unit_cost_microusd,
        ) * (service.retries + 1)
        if (
            cls._public_upstream_commitment(session) + estimate
            > settings.max_daily_upstream_cost_microusd
        ):
            raise TestCapacityReached("The public test capacity has been reached for today")
        return estimate

    async def _provider_call(
        self,
        session: Session,
        *,
        request_id: str,
        service: ServiceDefinition,
        input_data: dict[str, Any],
        public_test: bool = False,
    ) -> ProviderResult:
        adapter = adapter_for(service)
        last_error: ReachSocialError | None = None
        for attempt_number in range(service.retries + 1):
            started = time.perf_counter()
            try:
                result = await adapter.execute(service, input_data)
                self._record_attempt(
                    session,
                    request_id=request_id,
                    service=service,
                    status="succeeded",
                    latency_ms=round((time.perf_counter() - started) * 1000),
                    result=result,
                    public_test=public_test,
                )
                return result
            except ReachSocialError as error:
                last_error = error
                self._record_attempt(
                    session,
                    request_id=request_id,
                    service=service,
                    status="failed",
                    latency_ms=round((time.perf_counter() - started) * 1000),
                    error=error,
                    public_test=public_test,
                )
                if not error.retryable or attempt_number >= service.retries:
                    raise
        assert last_error is not None
        raise last_error

    async def execute(
        self,
        session: Session,
        *,
        client: Client,
        service_id: str,
        input_data: dict[str, Any],
        idempotency_key: str | None = None,
        charge_client: bool = True,
    ) -> dict[str, Any]:
        service = self.catalog.by_id(service_id)
        if service is None:
            raise UnknownService("Unknown service")
        if not service.enabled:
            raise DisabledService("This service is not enabled")
        if service.is_async:
            raise AsyncRequired("This service must be submitted through the jobs endpoint")
        if not client_can_access_service(session, client, service):
            raise UnknownService("Unknown service")
        self.validate_input(service, input_data)
        input_hash = stable_hash(input_data)
        idempotency_lock = None
        if idempotency_key:
            idempotency_lock = await self.runtime.acquire_idempotency(
                f"{client.id}:{service_id}:{idempotency_key}"
            )
            try:
                prior = self._idempotent_response(
                    session, client, service_id, idempotency_key, input_hash
                )
            except Exception:
                idempotency_lock.release()
                raise
            if prior is not None:
                idempotency_lock.release()
                return prior

        settings = get_settings()
        try:
            await self.runtime.acquire(
                client.id,
                provider=service.provider.name,
                per_minute=client.rate_limit_per_minute,
                concurrency=client.concurrency_limit,
                provider_concurrency=settings.provider_concurrency_limit,
            )
        except ReachSocialError as error:
            request_id = f"req_{uuid.uuid4().hex}"
            self._record(
                session,
                request_id=request_id,
                client=client,
                service=service,
                status="error",
                input_hash=input_hash,
                latency_ms=0,
                error_code=error.code,
                charge_client=False,
            )
            if idempotency_lock and idempotency_lock.locked():
                idempotency_lock.release()
            raise
        except BaseException:
            if idempotency_lock and idempotency_lock.locked():
                idempotency_lock.release()
            raise
        request_id = f"req_{uuid.uuid4().hex}"
        cache_key = f"{service.id}:{input_hash}"
        started = time.perf_counter()
        reserved_upstream_microusd = 0
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
                    "meta": {"schema_version": "1.0", "latency_ms": 0},
                }
                self._record(
                    session,
                    request_id=request_id,
                    client=client,
                    service=service,
                    status="success",
                    input_hash=input_hash,
                    cache_hit=True,
                    charge_client=charge_client,
                )
            else:
                if client.billing_mode != "internal":
                    settings = get_settings()
                    reserved_upstream_microusd = max(
                        service.estimated_upstream_cost_microusd,
                        service.provider_unit_cost_microusd,
                    ) * (service.retries + 1)
                    await self.runtime.reserve_public_upstream_cost(
                        self._public_upstream_commitment(session),
                        reserved_upstream_microusd,
                        settings.max_daily_upstream_cost_microusd,
                    )
                result = await self._provider_call(
                    session,
                    request_id=request_id,
                    service=service,
                    input_data=input_data,
                    public_test=client.billing_mode != "internal",
                )
                latency_ms = round((time.perf_counter() - started) * 1000)
                response = {
                    "request_id": request_id,
                    "service": service.id,
                    "status": "success",
                    "cached": False,
                    "data": result.data,
                    "meta": {"schema_version": "1.0", "latency_ms": latency_ms},
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
                    result=result,
                    charge_client=charge_client,
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
                charge_client=False,
            )
            raise
        finally:
            if reserved_upstream_microusd:
                await self.runtime.release_public_upstream_cost(reserved_upstream_microusd)
            await self.runtime.release(client.id, service.provider.name)
            if idempotency_lock and idempotency_lock.locked():
                idempotency_lock.release()
