from datetime import datetime, timedelta

from reachsocial.alerts import (
    OperationalAlert,
    _backup_alert,
    _provider_failure_alerts,
    apply_payment_pause,
)
from reachsocial.config import Settings
from reachsocial.models import ProviderAttempt
from reachsocial.runtime import RuntimeState


def test_provider_circuit_counts_logical_retryable_failures_and_resets_on_success(
    session,
) -> None:
    now = datetime(2026, 10, 13, 21, 0)

    def add_attempt(
        seconds: int, request_id: str, status: str, error_code: str | None
    ) -> None:
        session.add(
            ProviderAttempt(
                request_id=request_id,
                service_id="instagram.profile",
                provider="scrapecreators",
                status=status,
                error_code=error_code,
                created_at=now - timedelta(seconds=seconds),
            )
        )

    add_attempt(50, "request-one", "failed", "provider_unavailable")
    add_attempt(49, "request-one", "failed", "provider_unavailable")
    add_attempt(40, "request-two", "failed", "provider_timeout")
    add_attempt(30, "terminal-result", "failed", "not_found")
    session.commit()

    assert _provider_failure_alerts(session, now) == []

    add_attempt(20, "request-three", "failed", "provider_unavailable")
    session.commit()
    assert _provider_failure_alerts(session, now) == [
        OperationalAlert(
            "provider_failures",
            "count_10m=3 service=instagram.profile",
            service_id="instagram.profile",
        )
    ]

    add_attempt(10, "successful-request", "succeeded", None)
    session.commit()
    assert _provider_failure_alerts(session, now) == []


def test_monitoring_only_alerts_do_not_pause_new_payments(tmp_path) -> None:
    runtime = RuntimeState()
    apply_payment_pause(
        runtime,
        [OperationalAlert("authentication_failures", "count_10m=10", pauses_payments=False)],
    )
    assert runtime.public_payments_paused_reason is None

    marker = tmp_path / "backup-status.json"
    settings = Settings(
        external_backup_enabled=True,
        backup_status_path=marker,
        backup_max_age_hours=30,
    )
    alert = _backup_alert(settings, datetime(2026, 10, 15, 12, 0))
    assert alert == OperationalAlert(
        "backup_status_unavailable", "latest_success_marker_missing", pauses_payments=False
    )
