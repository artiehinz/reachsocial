from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from x402.http.middleware.fastapi import FastAPIAdapter
from x402.http.types import HTTPRequestContext

from reachsocial.catalog import Catalog, InputField, ProviderConfig, ServiceDefinition
from reachsocial.config import Settings
from reachsocial.models import PaymentReceipt
from reachsocial.payments import (
    ReachSocialX402Middleware,
    create_x402_payment_handler,
    is_b2b_request,
    mainnet_x402_safety_errors,
    payment_id_from_payload,
    price_for_public_execution,
    reserve_payment_receipt,
    service_id_from_path,
    usdc_atomic_to_cents,
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
    assert service_id_from_path("/v1/services/linkedin.profile/jobs") == "linkedin.profile"


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


def test_mainnet_is_blocked_until_backup_and_costs_are_verified() -> None:
    settings = Settings(
        x402_enabled=True,
        x402_network="eip155:8453",
        x402_pay_to="0x457d76fb1a0ce5414df9261179bf8547d58d3f86",
        x402_facilitator_url="https://api.cdp.coinbase.com/platform/v2/x402",
        cdp_api_key_id="test-key-id",
        cdp_api_key_secret="test-key-secret",
    )
    catalog = Catalog(
        services=[
            ServiceDefinition(
                id="instagram.profile",
                title="Instagram Profile",
                platform="Instagram",
                description="Test service",
                input_fields=[InputField(name="url", description="URL", format="url")],
                provider=ProviderConfig(name="mock"),
                enabled=True,
                public=True,
            )
        ]
    )

    errors = mainnet_x402_safety_errors(settings, catalog)

    assert "ALLOW_MAINNET_X402=true is required" in errors
    assert "EXTERNAL_BACKUP_ENABLED=true is required" in errors
    assert "instagram.profile needs a verified upstream cost" in errors


def test_payment_receipt_reservation_rejects_a_replayed_payload(session, monkeypatch) -> None:
    @contextmanager
    def session_factory():
        yield session

    monkeypatch.setattr("reachsocial.payments.SessionLocal", session_factory)
    payload = {"x402Version": 2, "payload": {"signature": "signature"}}
    context = SimpleNamespace(
        payment_payload=payload,
        requirements=SimpleNamespace(network="eip155:84532", amount="50000"),
        result=SimpleNamespace(payer="0xbuyer"),
        transport_context=SimpleNamespace(
            request=SimpleNamespace(path="/v1/services/instagram.profile/execute")
        ),
    )

    assert reserve_payment_receipt(context) is None
    replay = reserve_payment_receipt(context)

    assert replay is not None
    receipt = session.scalar(select(PaymentReceipt))
    assert receipt is not None
    assert receipt.payment_id == payment_id_from_payload(payload)
    assert receipt.status == "verified"
    assert receipt.amount_cents == 5


def test_usdc_atomic_amount_is_reported_as_cents() -> None:
    assert usdc_atomic_to_cents("50000") == 5


@pytest.mark.asyncio
async def test_disabled_service_bypasses_payment_challenge() -> None:
    catalog = Catalog(
        services=[
            ServiceDefinition(
                id="x.feed",
                title="X Feed",
                platform="X",
                description="Disabled service",
                input_fields=[InputField(name="url", description="URL", format="url")],
                provider=ProviderConfig(name="mock"),
                execution="async",
                response_shape="feed",
                enabled=False,
                public=False,
                price_cents=10,
            )
        ]
    )
    middleware = object.__new__(ReachSocialX402Middleware)
    middleware._catalog = catalog
    payment_calls = []

    async def payment_handler(request, call_next):
        del request, call_next
        payment_calls.append(True)
        return JSONResponse({"payment": "required"}, status_code=402)

    async def route_handler(request):
        del request
        return JSONResponse({"error": "disabled"}, status_code=404)

    middleware._payment_handler = payment_handler
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/services/x.feed/jobs",
            "headers": [],
            "query_string": b"",
            "scheme": "https",
            "server": ("reachsocial.test", 443),
        }
    )

    response = await middleware.dispatch(request, route_handler)

    assert response.status_code == 404
    assert payment_calls == []
