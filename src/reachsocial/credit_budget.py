"""Fail-closed public credit capacity accounting for ScrapeCreators.

The provider balance is an operator-observed value.  We do not infer it from
prices or silently buy more credits.  Every mainnet payment reserves the worst
case provider units before settlement, then records actual units after the
provider attempt is durable.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .catalog import ServiceDefinition
from .config import Settings
from .models import ProviderAttempt, ProviderCreditReservation


def reservation_units(service: ServiceDefinition) -> int:
    return max(1, service.retries + 1)


def configured_capacity(settings: Settings) -> int:
    return max(0, settings.scrapecreators_credit_balance - settings.scrapecreators_credit_reserve)


def _committed_units(session: Session) -> int:
    reservations = list(
        session.scalars(
            select(ProviderCreditReservation).where(
                ProviderCreditReservation.provider == "scrapecreators"
            )
        )
    )
    return sum(
        row.reserved_units if row.status == "reserved" else row.consumed_units
        for row in reservations
    )


def summary(session: Session, settings: Settings) -> dict[str, int]:
    capacity = configured_capacity(settings)
    committed = _committed_units(session)
    return {
        "observed_balance": settings.scrapecreators_credit_balance,
        "internal_reserve": settings.scrapecreators_credit_reserve,
        "public_capacity": capacity,
        "public_committed": committed,
        "public_available": max(0, capacity - committed),
    }


def reserve(
    session: Session,
    *,
    payment_id: str,
    service: ServiceDefinition,
    settings: Settings,
    lock: bool = True,
) -> bool:
    """Atomically reserve maximum possible provider units for one payment."""
    units = reservation_units(service)
    # SQLite's immediate writer transaction closes the check/insert race.  The
    # deployed service is SQLite today; other engines already serialize writes.
    if (
        lock
        and not session.in_transaction()
        and session.bind
        and session.bind.dialect.name == "sqlite"
    ):
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
    current = summary(session, settings)
    if current["public_available"] < units:
        session.rollback()
        return False
    session.add(
        ProviderCreditReservation(
            payment_id=payment_id,
            provider=service.provider.name,
            service_id=service.id,
            status="reserved",
            reserved_units=units,
            consumed_units=0,
        )
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return False
    return True


def finalize(session: Session, payment_id: str) -> None:
    """Replace a conservative hold with recorded actual provider consumption."""
    reservation = session.scalar(
        select(ProviderCreditReservation).where(
            ProviderCreditReservation.payment_id == payment_id
        )
    )
    if reservation is None or reservation.status != "reserved":
        return
    from .models import PaymentReceipt

    receipt = session.scalar(
        select(PaymentReceipt).where(PaymentReceipt.payment_id == payment_id)
    )
    if receipt is None:
        return
    request_filter = []
    if receipt.request_id:
        request_filter.append(ProviderAttempt.request_id == receipt.request_id)
    if receipt.job_id:
        request_filter.append(ProviderAttempt.job_id == receipt.job_id)
    if not request_filter:
        return
    attempts = session.scalar(
        select(func.coalesce(func.sum(ProviderAttempt.provider_units), 0)).where(
            ProviderAttempt.provider == reservation.provider,
            *request_filter,
        )
    )
    reservation.consumed_units = max(0, int(attempts or 0))
    reservation.reserved_units = 0
    reservation.status = "consumed"
    session.commit()
