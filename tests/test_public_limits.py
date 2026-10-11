from types import SimpleNamespace

import pytest

from reachsocial.api import enforce_public_test_limits, public_client_ip
from reachsocial.config import Settings
from reachsocial.errors import TestCapacityReached as CapacityReached
from reachsocial.runtime import RuntimeState


@pytest.mark.asyncio
async def test_public_daily_identity_limit_is_persistent(session) -> None:
    request = SimpleNamespace(
        client=SimpleNamespace(host="203.0.113.10"),
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=Settings(
                    admin_api_token="test-salt",
                    public_test_rate_limit_per_minute=10,
                    public_test_daily_requests_per_identity=1,
                ),
                runtime=RuntimeState(),
            )
        ),
    )
    await enforce_public_test_limits(request, session, None)
    with pytest.raises(CapacityReached):
        await enforce_public_test_limits(request, session, None)


def test_public_limit_uses_caddy_forwarded_visitor_ip() -> None:
    request = SimpleNamespace(
        client=SimpleNamespace(host="172.18.0.3"),
        headers={"x-forwarded-for": "203.0.113.10"},
    )

    assert public_client_ip(request) == "203.0.113.10"
