"""Durable, hashed OAuth state. No wallet signatures or bearer tokens are stored."""

from __future__ import annotations

import hashlib
import secrets
import time
from typing import Any

from sqlalchemy import JSON, Boolean, Float, String, select, update
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def secret() -> str:
    return secrets.token_urlsafe(32)


class OAuthState(Base):
    __tablename__ = "oauth_states"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    owner: Mapped[str] = mapped_column(String(255), default="", index=True)
    family: Mapped[str] = mapped_column(String(64), default="", index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    expires_at: Mapped[float] = mapped_column(Float, index=True)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


def put(
    session: Session,
    kind: str,
    value: str,
    payload: dict,
    ttl: int,
    *,
    owner: str = "",
    family: str = "",
) -> OAuthState:
    row = OAuthState(
        key=digest(value),
        kind=kind,
        owner=owner,
        family=family,
        payload=payload,
        expires_at=time.time() + ttl,
        consumed=False,
    )
    session.add(row)
    session.flush()
    return row


def get(session: Session, kind: str, value: str, *, used: bool = False) -> OAuthState | None:
    row = session.get(OAuthState, digest(value))
    if (
        row is None
        or row.kind != kind
        or row.expires_at <= time.time()
        or (row.consumed and not used)
    ):
        return None
    return row


def consume(session: Session, kind: str, value: str) -> bool:
    result = session.execute(
        update(OAuthState)
        .where(
            OAuthState.key == digest(value),
            OAuthState.kind == kind,
            OAuthState.consumed.is_(False),
            OAuthState.expires_at > time.time(),
        )
        .values(consumed=True)
    )
    return result.rowcount == 1


def revoke_family(session: Session, family: str) -> None:
    if family:
        session.execute(update(OAuthState).where(OAuthState.family == family).values(consumed=True))


def record_auth_failure(session: Session, category: str) -> None:
    """Record a short-lived, non-identifying signal for operational monitoring."""
    put(
        session,
        "auth_failure",
        f"{category}:{secret()}",
        {"category": category},
        600,
    )


def _mcp_request_needs_reconciliation(session: Session, row: OAuthState) -> bool:
    """Keep an expired intent when a signed payment may still need a human review."""
    payload = row.payload
    if not payload.get("payment_attempted"):
        return False
    # Import locally to keep OAuth state independent during schema startup.
    from sqlalchemy import select

    from .models import Client, IdempotencyRecord, PaymentReceipt
    from .payments import PUBLIC_X402_CLIENT_NAME

    client = session.scalar(select(Client).where(Client.name == PUBLIC_X402_CLIENT_NAME))
    if client is None:
        return True
    record = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.client_id == client.id,
            IdempotencyRecord.service_id == payload.get("service", ""),
            IdempotencyRecord.key == payload.get("payment_key", ""),
        )
    )
    if record is None:
        # A dispatched request can fail before its result record is persisted.
        return True
    request_id = str(record.response_json.get("request_id") or "")
    receipt = session.scalar(
        select(PaymentReceipt).where(PaymentReceipt.request_id == request_id)
    )
    return receipt is None or receipt.status in {"verified", "reconciliation_required"}


def prune(session: Session, *, now: float | None = None) -> int:
    """Prune expired OAuth state without deleting possible payment evidence."""
    cutoff = time.time() if now is None else now
    expired = list(
        session.scalars(select(OAuthState).where(OAuthState.expires_at < cutoff))
    )
    deleted = 0
    for row in expired:
        if row.kind == "mcp_request" and _mcp_request_needs_reconciliation(session, row):
            continue
        session.delete(row)
        deleted += 1
    return deleted


def rate_limit(session: Session, identity: str, action: str, maximum: int) -> bool:
    """Bound auth attempts durably, including across single-process restarts."""
    from sqlalchemy.dialects.sqlite import insert

    bucket = f"{action}:{identity}:{int(time.time()) // 60}"
    key = digest(bucket)
    # The write acquires SQLite's writer lock before the counter is read.
    session.execute(
        insert(OAuthState)
        .values(
            key=key,
            kind="rate",
            owner="",
            family="",
            payload={"count": 0},
            expires_at=time.time() + 120,
            consumed=False,
        )
        .on_conflict_do_nothing()
    )
    row = session.scalar(
        select(OAuthState).where(OAuthState.key == key).execution_options(populate_existing=True)
    )
    assert row is not None
    count = int(row.payload["count"])
    row.payload = {"count": count + 1}
    session.flush()
    return count < maximum
