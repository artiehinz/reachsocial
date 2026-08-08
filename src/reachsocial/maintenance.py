from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from .config import get_settings
from .db import SessionLocal
from .models import IdempotencyRecord, RequestLog


def prune_operational_records() -> tuple[int, int]:
    """Delete expired operational metadata; never delete payment receipts."""
    settings = get_settings()
    now = datetime.now(UTC).replace(tzinfo=None)
    cutoff = now - timedelta(days=settings.request_retention_days)
    with SessionLocal() as session:
        deleted_requests = session.execute(
            delete(RequestLog).where(RequestLog.created_at < cutoff)
        ).rowcount
        deleted_idempotency = session.execute(
            delete(IdempotencyRecord).where(IdempotencyRecord.expires_at < now)
        ).rowcount
        session.commit()
    return deleted_requests or 0, deleted_idempotency or 0
