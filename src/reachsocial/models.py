from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    key_id: Mapped[str | None] = mapped_column(String(32), unique=True, index=True, nullable=True)
    api_key_hash: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    billing_mode: Mapped[str] = mapped_column(String(30), default="internal")
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=30)
    concurrency_limit: Mapped[int] = mapped_column(Integer, default=2)
    daily_spend_cents: Mapped[int] = mapped_column(Integer, default=5000)
    api_key_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    requests: Mapped[list["RequestLog"]] = relationship(back_populates="client")
    entitlements: Mapped[list["ClientService"]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )


class ClientService(Base):
    __tablename__ = "client_services"
    __table_args__ = (UniqueConstraint("client_id", "service_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    service_id: Mapped[str] = mapped_column(String(120), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    client: Mapped[Client] = relationship(back_populates="entitlements")


class ServiceRecord(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    service_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    public: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[str] = mapped_column(String(40))
    price_cents: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RequestLog(Base):
    __tablename__ = "requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    client_id: Mapped[int | None] = mapped_column(
        ForeignKey("clients.id"), nullable=True, index=True
    )
    service_id: Mapped[str] = mapped_column(String(120), index=True)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    upstream_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    upstream_cost_microusd: Mapped[int] = mapped_column(Integer, default=0)
    provider_units: Mapped[int] = mapped_column(Integer, default=0)
    provider_unit_cost_microusd: Mapped[int] = mapped_column(Integer, default=0)
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    price_snapshot_cents: Mapped[int] = mapped_column(Integer, default=0)
    charged_cents: Mapped[int] = mapped_column(Integer, default=0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    input_hash: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    client: Mapped[Client | None] = relationship(back_populates="requests")


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        Index(
            "uq_idempotency_records_client_service_key",
            "client_id",
            "service_id",
            "key",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    service_id: Mapped[str] = mapped_column(String(120), index=True)
    key: Mapped[str] = mapped_column(String(255))
    input_hash: Mapped[str] = mapped_column(String(128))
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PaymentReceipt(Base):
    __tablename__ = "payment_receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    service_id: Mapped[str] = mapped_column(String(120), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    network: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), index=True)
    payer: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    transaction: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    job_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    replacement_credit_cents: Mapped[int] = mapped_column(Integer, default=0)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AsyncJob(Base):
    __tablename__ = "async_jobs"
    __table_args__ = (UniqueConstraint("client_id", "service_id", "idempotency_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), nullable=True, index=True)
    service_id: Mapped[str] = mapped_column(String(120), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    input_hash: Mapped[str] = mapped_column(String(128), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    access_token_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    price_snapshot_cents: Mapped[int] = mapped_column(Integer, default=0)
    provider_units: Mapped[int] = mapped_column(Integer, default=0)
    provider_unit_cost_microusd: Mapped[int] = mapped_column(Integer, default=0)
    upstream_cost_microusd: Mapped[int] = mapped_column(Integer, default=0)
    reserved_upstream_cost_microusd: Mapped[int] = mapped_column(Integer, default=0)
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    credit_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ServiceCredit(Base):
    __tablename__ = "service_credits"

    id: Mapped[int] = mapped_column(primary_key=True)
    credit_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    job_id: Mapped[str] = mapped_column(String(40), index=True)
    service_id: Mapped[str] = mapped_column(String(120), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProviderAttempt(Base):
    __tablename__ = "provider_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    job_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    service_id: Mapped[str] = mapped_column(String(120), index=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    provider_units: Mapped[int] = mapped_column(Integer, default=0)
    provider_unit_cost_microusd: Mapped[int] = mapped_column(Integer, default=0)
    upstream_cost_microusd: Mapped[int] = mapped_column(Integer, default=0)
    public_test: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PublicTestUsage(Base):
    __tablename__ = "public_test_usage"
    __table_args__ = (UniqueConstraint("usage_day", "identity_kind", "identity_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    usage_day: Mapped[str] = mapped_column(String(10), index=True)
    identity_kind: Mapped[str] = mapped_column(String(20), index=True)
    identity_hash: Mapped[str] = mapped_column(String(128), index=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
