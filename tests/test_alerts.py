from datetime import datetime, timedelta

from reachsocial.alerts import OperationalAlert, _provider_failure_alerts
from reachsocial.models import ProviderAttempt


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
