from __future__ import annotations

from fastapi import Request
from x402.http.middleware.fastapi import FastAPIAdapter
from x402.http.types import HTTPRequestContext

from reachsocial.catalog import Catalog, InputField, ProviderConfig, ServiceDefinition
from reachsocial.config import Settings
from reachsocial.payments import (
    create_x402_payment_handler,
    is_b2b_request,
    price_for_public_execution,
    service_id_from_path,
)


def test_x402_uses_the_official_cdp_facilitator_helper(monkeypatch) -> None:
    captured = []

    def fake_facilitator_config(**kwargs):  # type: ignore[no-untyped-def]
        captured.append(kwargs)
        return {"url": "https://api.cdp.coinbase.com/platform/v2/x402"}

    monkeypatch.setattr("reachsocial.payments.create_facilitator_config", fake_facilitator_config)
    settings = Settings(
        x402_enabled=True,
        x402_network="eip155:84532",
        x402_pay_to="0x457d76fb1a0ce5414df9261179bf8547d58d3f86",
        x402_facilitator_url="https://api.cdp.coinbase.com/platform/v2/x402",
        cdp_api_key_id="key-id",
        cdp_api_key_secret="secret",
    )

    handler = create_x402_payment_handler(settings, Catalog(services=[]))

    assert callable(handler)
    assert captured == [{"api_key_id": "key-id", "api_key_secret": "secret"}]


def test_price_is_resolved_from_the_requested_service() -> None:
    catalog = Catalog(
        services=[
            ServiceDefinition(
                id="linkedin.profile",
                title="LinkedIn Profile",
                platform="LinkedIn",
                description="Test service",
                input_fields=[InputField(name="url", description="URL", format="url")],
                provider=ProviderConfig(name="mock"),
                price_cents=15,
            )
        ]
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/services/linkedin.profile/execute",
            "headers": [],
            "query_string": b"",
            "scheme": "https",
            "server": ("reachsocial.test", 443),
        }
    )
    context = HTTPRequestContext(
        adapter=FastAPIAdapter(request), path=request.url.path, method="POST"
    )

    assert service_id_from_path(context.path) == "linkedin.profile"
    assert price_for_public_execution(context, catalog) == "$0.15"


def test_bearer_requests_bypass_the_public_payment_middleware() -> None:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/services/instagram.profile/execute",
            "headers": [(b"authorization", b"Bearer private-key")],
            "query_string": b"",
            "scheme": "https",
            "server": ("reachsocial.test", 443),
        }
    )

    assert is_b2b_request(request)


def test_x402_handler_builds_without_contacting_the_facilitator() -> None:
    settings = Settings(
        x402_enabled=True,
        x402_network="eip155:84532",
        x402_pay_to="0x457d76fb1a0ce5414df9261179bf8547d58d3f86",
        x402_facilitator_url="https://api.cdp.coinbase.com/platform/v2/x402",
        cdp_api_key_id="test-key-id",
        cdp_api_key_secret="test-key-secret",
    )

    handler = create_x402_payment_handler(settings, Catalog(services=[]))

    assert callable(handler)
