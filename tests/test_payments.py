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
from reachsocial.models import MainnetCanaryAttempt, PaymentReceipt
from reachsocial.payments import (
    MAINNET_ACCEPTANCE_PATHS,
    MAINNET_CANARY_PATH,
    MainnetAcceptanceX402Middleware,
    MainnetCanaryX402Middleware,
    ReachSocialX402Middleware,
    create_x402_payment_handler,
    is_b2b_request,
    mainnet_acceptance_safety_errors,
    mainnet_canary_safety_errors,
    mainnet_x402_safety_errors,
    payment_id_from_payload,
    price_for_public_execution,
    reserve_mainnet_acceptance,
    reserve_mainnet_canary,
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


def test_mainnet_is_allowed_when_all_launch_checks_pass() -> None:
    settings = Settings(
        x402_enabled=True,
        x402_network="eip155:8453",
        allow_mainnet_x402=True,
        external_backup_enabled=True,
        scrapecreators_credit_balance=6825,
        scrapecreators_credit_reserve=1000,
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
                price_cents=5,
                cost_verified=True,
                estimated_upstream_cost_microusd=1_880,
            )
        ]
    )

    assert mainnet_x402_safety_errors(settings, catalog) == []


def test_mainnet_canary_requires_a_testnet_public_route_and_named_buyer(catalog) -> None:
    settings = Settings(
        x402_enabled=True,
        x402_network="eip155:84532",
        mainnet_x402_canary_enabled=True,
        mainnet_x402_canary_buyer="0x93846388d538a82023B391ae0698851E2c43c9Af",
    )

    assert mainnet_canary_safety_errors(settings, catalog) == []

    settings.x402_network = "eip155:8453"
    assert (
        "the normal public x402 network must remain Base Sepolia"
        in mainnet_canary_safety_errors(settings, catalog)
    )


def test_mainnet_acceptance_requires_testnet_public_routes_and_named_buyer(catalog) -> None:
    settings = Settings(
        x402_enabled=True,
        x402_network="eip155:84532",
        mainnet_x402_acceptance_enabled=True,
        mainnet_x402_acceptance_buyer="0xcf8fD9bd415C36326597E8079fCb3125FE2dB369",
    )

    assert "instagram.profile needs a verified upstream cost" in mainnet_acceptance_safety_errors(
        settings, catalog
    )

    settings.x402_network = "eip155:8453"
    assert (
        "the normal public x402 network must remain Base Sepolia"
        in mainnet_acceptance_safety_errors(settings, catalog)
    )


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


def test_mainnet_canary_reservation_allows_only_one_named_buyer(session, monkeypatch) -> None:
    @contextmanager
    def session_factory():
        yield session

    monkeypatch.setattr("reachsocial.payments.SessionLocal", session_factory)
    expected_payer = "0x93846388d538a82023B391ae0698851E2c43c9Af"

    def context(payload, payer=expected_payer):
        return SimpleNamespace(
            payment_payload=payload,
            requirements=SimpleNamespace(
                network="eip155:8453",
                asset="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                amount="50000",
            ),
            result=SimpleNamespace(payer=payer),
            transport_context=SimpleNamespace(request=SimpleNamespace(path=MAINNET_CANARY_PATH)),
        )

    assert reserve_mainnet_canary(context({"signature": "one"}), expected_payer) is None
    rejected = reserve_mainnet_canary(context({"signature": "two"}), expected_payer)
    wrong_buyer = reserve_mainnet_canary(
        context({"signature": "three"}, payer="0x0000000000000000000000000000000000000000"),
        expected_payer,
    )

    assert rejected is not None and rejected.reason == "mainnet_canary_already_used"
    assert wrong_buyer is not None and wrong_buyer.reason == "mainnet_canary_buyer_rejected"
    assert session.scalar(select(MainnetCanaryAttempt)) is not None
    assert session.scalar(select(PaymentReceipt)).status == "verified"


def test_mainnet_acceptance_reserves_each_route_once_for_the_named_buyer(
    session, monkeypatch, catalog
) -> None:
    @contextmanager
    def session_factory():
        yield session

    monkeypatch.setattr("reachsocial.payments.SessionLocal", session_factory)
    expected_payer = "0xcf8fD9bd415C36326597E8079fCb3125FE2dB369"
    path = MAINNET_ACCEPTANCE_PATHS["instagram.post"]
    context = SimpleNamespace(
        payment_payload={"signature": "acceptance-one"},
        requirements=SimpleNamespace(
            network="eip155:8453",
            asset="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            amount="50000",
        ),
        result=SimpleNamespace(payer=expected_payer),
        transport_context=SimpleNamespace(request=SimpleNamespace(path=path)),
    )
    settings = Settings(
        scrapecreators_credit_balance=10,
        scrapecreators_credit_reserve=0,
    )

    assert (
        reserve_mainnet_acceptance(
            context, expected_payer=expected_payer, settings=settings, catalog=catalog
        )
        is None
    )
    repeated = reserve_mainnet_acceptance(
        context, expected_payer=expected_payer, settings=settings, catalog=catalog
    )
    route_reused = reserve_mainnet_acceptance(
        SimpleNamespace(
            payment_payload={"signature": "acceptance-two"},
            requirements=context.requirements,
            result=SimpleNamespace(payer=expected_payer),
            transport_context=context.transport_context,
        ),
        expected_payer=expected_payer,
        settings=settings,
        catalog=catalog,
    )
    wrong_buyer = reserve_mainnet_acceptance(
        SimpleNamespace(
            payment_payload={"signature": "acceptance-three"},
            requirements=context.requirements,
            result=SimpleNamespace(payer="0x0000000000000000000000000000000000000000"),
            transport_context=context.transport_context,
        ),
        expected_payer=expected_payer,
        settings=settings,
        catalog=catalog,
    )

    assert repeated is not None and repeated.reason == "payment_replayed"
    assert (
        route_reused is not None and route_reused.reason == "mainnet_acceptance_route_already_used"
    )
    assert wrong_buyer is not None and wrong_buyer.reason == "mainnet_acceptance_buyer_rejected"
    assert session.scalar(select(MainnetCanaryAttempt)).canary_key.endswith("instagram.post")


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


@pytest.mark.asyncio
async def test_mainnet_canary_rejects_b2b_and_service_credit_bypasses() -> None:
    middleware = object.__new__(MainnetCanaryX402Middleware)
    payment_calls = []

    async def payment_handler(request, call_next):
        del request, call_next
        payment_calls.append(True)
        return JSONResponse({"payment": "required"}, status_code=402)

    async def route_handler(request):
        del request
        return JSONResponse({"unexpected": True})

    middleware._payment_handler = payment_handler
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": MAINNET_CANARY_PATH,
            "headers": [(b"authorization", b"Bearer private-key")],
            "query_string": b"",
            "scheme": "https",
            "server": ("reachsocial.test", 443),
        }
    )

    response = await middleware.dispatch(request, route_handler)

    assert response.status_code == 403
    assert payment_calls == []


@pytest.mark.asyncio
async def test_mainnet_acceptance_rejects_b2b_and_service_credit_bypasses() -> None:
    middleware = object.__new__(MainnetAcceptanceX402Middleware)
    payment_calls = []

    async def payment_handler(request, call_next):
        del request, call_next
        payment_calls.append(True)
        return JSONResponse({"payment": "required"}, status_code=402)

    async def route_handler(request):
        del request
        return JSONResponse({"unexpected": True})

    middleware._payment_handler = payment_handler
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": MAINNET_ACCEPTANCE_PATHS["instagram.profile"],
            "headers": [(b"x-service-credit", b"private-credit")],
            "query_string": b"",
            "scheme": "https",
            "server": ("reachsocial.test", 443),
        }
    )

    response = await middleware.dispatch(request, route_handler)

    assert response.status_code == 403
    assert payment_calls == []
