from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, update

from .config import get_settings
from .db import SessionLocal
from .models import (
    AsyncJob,
    IdempotencyRecord,
    ProviderAttempt,
    PublicTestUsage,
    RequestLog,
    ServiceCredit,
)


def prune_operational_records() -> dict[str, int]:
    """Prune expiring operational metadata; payment receipts remain immutable."""
    settings = get_settings()
    now = datetime.now(UTC).replace(tzinfo=None)
    cutoff = now - timedelta(days=settings.request_retention_days)
    usage_cutoff = (now.date() - timedelta(days=2)).isoformat()
    with SessionLocal() as session:
        from .oauth_store import prune as prune_oauth
        prune_oauth(session)
        expired_jobs = session.execute(
            update(AsyncJob)
            .where(AsyncJob.expires_at <= now, AsyncJob.status != "expired")
            .values(
                status="expired",
                result_json=None,
                input_json={},
                lease_expires_at=None,
                reserved_upstream_cost_microusd=0,
            )
        ).rowcount or 0
        session.execute(
            update(ServiceCredit)
            .where(ServiceCredit.status == "active", ServiceCredit.expires_at <= now)
            .values(status="expired")
        )
        results = {
            "requests": session.execute(
                delete(RequestLog).where(RequestLog.created_at < cutoff)
            ).rowcount
            or 0,
            "provider_attempts": session.execute(
                delete(ProviderAttempt).where(ProviderAttempt.created_at < cutoff)
            ).rowcount
            or 0,
            "idempotency": session.execute(
                delete(IdempotencyRecord).where(IdempotencyRecord.expires_at < now)
            ).rowcount
            or 0,
            "jobs_expired": expired_jobs,
            "jobs_deleted": session.execute(
                delete(AsyncJob).where(
                    AsyncJob.status == "expired", AsyncJob.created_at < cutoff
                )
            ).rowcount
            or 0,
            "public_test_usage": session.execute(
                delete(PublicTestUsage).where(PublicTestUsage.usage_day < usage_cutoff)
            ).rowcount
            or 0,
        }
        session.commit()
    return results
