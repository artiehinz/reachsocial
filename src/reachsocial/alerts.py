from __future__ import annotations

import asyncio
import logging
import shutil
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .credit_budget import (
    ProviderBalanceUnavailable,
    fetch_provider_balance,
)
from .credit_budget import (
    summary as credit_budget_summary,
)
from .db import SessionLocal
from .models import AsyncJob, PaymentReceipt, ProviderAttempt
from .runtime import RuntimeState
from .services import utcnow_naive

PROVIDER_CIRCUIT_ERROR_CODES = frozenset(
    {"internal_error", "provider_timeout", "provider_unavailable", "rate_limit"}
)


@dataclass(frozen=True)
class OperationalAlert:
    kind: str
    detail: str
    service_id: str | None = None


def _memory_available_percent() -> float | None:
    try:
        values: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, raw = line.partition(":")
            if key in {"MemTotal", "MemAvailable"}:
                values[key] = int(raw.strip().split()[0])
        if values.get("MemTotal"):
            return values.get("MemAvailable", 0) / values["MemTotal"] * 100
    except (OSError, ValueError):
        return None
    return None


def _provider_failure_alerts(session: Session, now) -> list[OperationalAlert]:  # type: ignore[no-untyped-def]
    attempts = session.execute(
        select(
            ProviderAttempt.id,
            ProviderAttempt.request_id,
            ProviderAttempt.job_id,
            ProviderAttempt.service_id,
            ProviderAttempt.status,
            ProviderAttempt.error_code,
        )
        .where(ProviderAttempt.created_at >= now - timedelta(minutes=10))
        .order_by(ProviderAttempt.created_at, ProviderAttempt.id)
    ).all()
    failures: dict[str, set[str]] = defaultdict(set)
    for attempt_id, request_id, job_id, service_id, status, error_code in attempts:
        if status == "succeeded":
            failures.pop(service_id, None)
        elif status == "failed" and error_code in PROVIDER_CIRCUIT_ERROR_CODES:
            logical_request = request_id or job_id or f"attempt:{attempt_id}"
            failures[service_id].add(logical_request)
    return [
        OperationalAlert(
            kind="provider_failures",
            detail=f"count_10m={len(requests)} service={service_id}",
            service_id=service_id,
        )
        for service_id, requests in sorted(failures.items())
        if len(requests) >= 3
    ]


def collect_alerts() -> list[OperationalAlert]:
    settings = get_settings()
    now = utcnow_naive()
    alerts: list[OperationalAlert] = []
    available = _memory_available_percent()
    if available is not None and available < 15:
        alerts.append(OperationalAlert("memory_pressure", f"available_percent={available:.1f}"))
    database_path = (
        Path(settings.database_url.removeprefix("sqlite:///"))
        if settings.database_url.startswith("sqlite:///")
        else Path("/")
    )
    try:
        disk = shutil.disk_usage(database_path.parent)
        free_percent = disk.free / disk.total * 100
        if free_percent < 15:
            alerts.append(OperationalAlert("disk_pressure", f"free_percent={free_percent:.1f}"))
    except OSError:
        pass
    with SessionLocal() as session:
        stuck = session.scalar(
            select(func.count(AsyncJob.id)).where(
                AsyncJob.status.in_(["queued", "running"]),
                AsyncJob.created_at < now - timedelta(minutes=5),
            )
        )
        if stuck:
            alerts.append(OperationalAlert("stuck_jobs", f"count={stuck}"))
        alerts.extend(_provider_failure_alerts(session, now))
        payment_failures = session.scalar(
            select(func.count(PaymentReceipt.id)).where(
                PaymentReceipt.status.in_(
                    ["canceled", "settlement_failed", "reconciliation_required"]
                ),
                PaymentReceipt.updated_at >= now - timedelta(minutes=10),
            )
        )
        if payment_failures:
            alerts.append(OperationalAlert("payment_failures", f"count_10m={payment_failures}"))
        if settings.x402_network == "eip155:8453" and settings.allow_mainnet_x402:
            try:
                observed_balance = fetch_provider_balance(settings)
            except ProviderBalanceUnavailable:
                alerts.append(
                    OperationalAlert("provider_credit_balance_unavailable", "live_check_failed")
                )
            else:
                credits = credit_budget_summary(
                    session, settings, observed_balance=observed_balance
                )
                if credits["public_available"] <= 10:
                    alerts.append(
                        OperationalAlert(
                            "provider_credit_capacity",
                            f"public_available={credits['public_available']}",
                        )
                    )
    return alerts


def apply_payment_pause(
    runtime: RuntimeState,
    alerts: list[OperationalAlert],
    public_service_ids: frozenset[str] | None = None,
) -> None:
    """Apply global safety pauses and isolate provider failures by service."""
    service_pauses = {
        alert.service_id: alert.kind
        for alert in alerts
        if alert.service_id is not None
        and (public_service_ids is None or alert.service_id in public_service_ids)
    }
    runtime.replace_public_service_payment_pauses(service_pauses)
    global_alerts = [alert for alert in alerts if alert.service_id is None]
    if global_alerts:
        runtime.pause_public_payments(global_alerts[0].kind)
    else:
        runtime.resume_public_payments()


async def alert_loop(
    runtime: RuntimeState, public_service_ids: frozenset[str] | None = None
) -> None:
    logger = logging.getLogger("reachsocial")
    settings = get_settings()
    while True:
        try:
            alerts = collect_alerts()
            apply_payment_pause(runtime, alerts, public_service_ids)
            for alert in alerts:
                logger.warning(
                    "operational_alert kind=%s detail=%s contact=%s",
                    alert.kind,
                    alert.detail,
                    settings.support_email,
                )
        except Exception:
            logger.exception("operational_alert_check_failed contact=%s", settings.support_email)
        await asyncio.sleep(60)
