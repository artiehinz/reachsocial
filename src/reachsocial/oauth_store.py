"""Durable, hashed OAuth state. No wallet signatures or bearer tokens are stored."""

from __future__ import annotations

import hashlib
import secrets
import time
from typing import Any

from sqlalchemy import JSON, Boolean, Float, String, delete, select, update
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


def prune(session: Session) -> None:
    session.execute(
        delete(OAuthState).where(
            OAuthState.expires_at < time.time(),
            OAuthState.kind != "mcp_request",
        )
    )


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
