from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select

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


def collect_alerts() -> list[tuple[str, str]]:
    settings = get_settings()
    now = utcnow_naive()
    alerts: list[tuple[str, str]] = []
    available = _memory_available_percent()
    if available is not None and available < 15:
        alerts.append(("memory_pressure", f"available_percent={available:.1f}"))
    database_path = (
        Path(settings.database_url.removeprefix("sqlite:///"))
        if settings.database_url.startswith("sqlite:///")
        else Path("/")
    )
    try:
        disk = shutil.disk_usage(database_path.parent)
        free_percent = disk.free / disk.total * 100
        if free_percent < 15:
            alerts.append(("disk_pressure", f"free_percent={free_percent:.1f}"))
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
            alerts.append(("stuck_jobs", f"count={stuck}"))
        recent_failures = session.scalar(
            select(func.count(ProviderAttempt.id)).where(
                ProviderAttempt.status == "failed",
                ProviderAttempt.created_at >= now - timedelta(minutes=10),
            )
        )
        if int(recent_failures or 0) >= 3:
            alerts.append(("provider_failures", f"count_10m={recent_failures}"))
        payment_failures = session.scalar(
            select(func.count(PaymentReceipt.id)).where(
                PaymentReceipt.status.in_(
                    ["canceled", "settlement_failed", "reconciliation_required"]
                ),
                PaymentReceipt.updated_at >= now - timedelta(minutes=10),
            )
        )
        if payment_failures:
            alerts.append(("payment_failures", f"count_10m={payment_failures}"))
        if settings.x402_network == "eip155:8453" and settings.allow_mainnet_x402:
            try:
                observed_balance = fetch_provider_balance(settings)
            except ProviderBalanceUnavailable:
                alerts.append(("provider_credit_balance_unavailable", "live_check_failed"))
            else:
                credits = credit_budget_summary(
                    session, settings, observed_balance=observed_balance
                )
                if credits["public_available"] <= 10:
                    alerts.append(
                        (
                            "provider_credit_capacity",
                            f"public_available={credits['public_available']}",
                        )
                    )
    return alerts


async def alert_loop(runtime: RuntimeState) -> None:
    logger = logging.getLogger("reachsocial")
    settings = get_settings()
    while True:
        try:
            alerts = collect_alerts()
            if alerts:
                runtime.pause_public_payments(alerts[0][0])
            for kind, detail in alerts:
                logger.warning(
                    "operational_alert kind=%s detail=%s contact=%s",
                    kind,
                    detail,
                    settings.support_email,
                )
        except Exception:
            logger.exception("operational_alert_check_failed contact=%s", settings.support_email)
        await asyncio.sleep(60)
