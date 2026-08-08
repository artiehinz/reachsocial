"""Prune durable operational records older than the configured retention period."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from reachsocial.config import get_settings
from reachsocial.db import SessionLocal, init_db
from reachsocial.models import IdempotencyRecord, RequestLog


def main() -> None:
    settings = get_settings()
    now = datetime.now(UTC).replace(tzinfo=None)
    cutoff = now - timedelta(days=settings.request_retention_days)
    init_db()
    with SessionLocal() as session:
        deleted_requests = session.execute(
            delete(RequestLog).where(RequestLog.created_at < cutoff)
        ).rowcount
        deleted_idempotency = session.execute(
            delete(IdempotencyRecord).where(IdempotencyRecord.expires_at < now)
        ).rowcount
        session.commit()
    print(
        f"Deleted {deleted_requests or 0} requests and {deleted_idempotency or 0} expired idempotency records"
    )


if __name__ == "__main__":
    main()
