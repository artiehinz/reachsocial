from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from reachsocial.config import Settings
from reachsocial.main import app
from reachsocial.normalized import normalized_result_is_complete
from reachsocial.payment_metadata import public_payment_metadata

ROOT = Path(__file__).resolve().parents[1]


def test_stored_homepage_example_is_sanitized_and_schema_complete() -> None:
    example = json.loads((ROOT / "examples" / "instagram-profile.json").read_text())

    assert example["service"] == "instagram.profile"
    assert example["meta"]["schema_version"] == "1.0"
    assert normalized_result_is_complete(example["service"], example["data"])
    serialized = json.dumps(example)
    assert "https://www.instagram.com/instagram/" in serialized
    assert "artie_hinz" not in serialized
    assert "provider_payload" not in serialized


def test_home_and_docs_publish_static_example_copy_controls_and_reduced_motion() -> None:
    with TestClient(app) as client:
        home = client.get("/").text
        docs = client.get("/docs/api").text
        styles = client.get("/static/site.css").text
        script = client.get("/static/site.js").text

    assert "FROM URL TO USEFUL JSON" in home
    assert "Example response — live values may differ." in home
    assert "View complete response" in home
    assert 'id="home-example-response"' in home
    assert "@media (prefers-reduced-motion: reduce)" in styles
    assert ".flow-step { animation: none; }" in styles
    assert "browser-client-source" in docs
    assert "@x402/core@2.28.0" in docs
    assert "This check does not authorize a payment." in docs
    assert "document.createElement(\"textarea\")" in script
    assert "artie_hinz" not in home + docs
    assert "\\nconst account" not in docs
    assert "sessionStorage.setItem" in docs


def test_payment_metadata_has_only_public_protocol_facts() -> None:
    settings = Settings(
        x402_enabled=True,
        x402_network="eip155:8453",
        x402_pay_to="0x76bCc44696A4c67579A6aF2F25CF953BE0931E38",
    )

    assert public_payment_metadata(settings) == {
        "enabled": True,
        "protocol": "x402",
        "version": 2,
        "network": "eip155:8453",
        "chain_id": 8453,
        "network_name": "Base mainnet",
        "asset": {
            "symbol": "USDC",
            "address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "decimals": 6,
        },
        "receiver": "0x76bCc44696A4c67579A6aF2F25CF953BE0931E38",
    }


def test_public_browser_cors_is_narrow_and_exposes_payment_headers() -> None:
    with TestClient(app) as client:
        status = client.get("/status.json", headers={"Origin": "https://example.dev"})
        assert status.headers["access-control-allow-origin"] == "*"
        assert "PAYMENT-REQUIRED" in status.headers["access-control-expose-headers"]
        payment = status.json()["payment"]
        assert payment["protocol"] == "x402"
        assert payment["version"] == 2
        assert payment["network"] == "eip155:84532"
        assert payment["receiver"] is None

        preflight = client.options(
            "/v1/services/instagram.profile/execute",
            headers={
                "Origin": "https://app.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": (
                    "content-type,idempotency-key,payment-signature,access-control-expose-headers"
                ),
            },
        )
        assert preflight.status_code == 204
        assert "authorization" not in preflight.headers["access-control-allow-headers"]

        forbidden = client.options(
            "/v1/services/instagram.profile/execute",
            headers={
                "Origin": "https://app.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert forbidden.status_code == 403
        assert "access-control-allow-origin" not in forbidden.headers

        private_route = client.options(
            "/v1/jobs/job_123",
            headers={
                "Origin": "https://app.example",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-job-token",
            },
        )
        assert private_route.status_code != 204
        assert "access-control-allow-origin" not in private_route.headers

        execute = client.post(
            "/v1/services/instagram.profile/execute",
            headers={
                "Origin": "https://app.example",
                "Idempotency-Key": "5d714f31-41f6-4bbb-a692-f54e0a2babdc",
            },
            json={"input": {"url": "https://www.instagram.com/instagram/"}},
        )
        assert execute.headers["access-control-allow-origin"] == "*"


def test_bearer_catalog_and_admin_routes_do_not_get_cors() -> None:
    with TestClient(app) as client:
        for path in ("/v1/catalog", "/v1/admin/clients", "/v1/jobs/unknown"):
            response = client.get(path, headers={"Origin": "https://example.dev"})
            assert "access-control-allow-origin" not in response.headers


def test_recovery_cors_survives_a_private_service_and_discovery_cache_has_cors() -> None:
    with TestClient(app) as client:
        # A response first requested without Origin must still be browser-readable
        # if the public cache serves it to a later cross-origin consumer.
        assert client.get("/v1/services").headers["access-control-allow-origin"] == "*"
        headers = {
            "Origin": "https://client.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,idempotency-key",
        }
        recovery = client.options("/v1/payments/recover/instagram.feed", headers=headers)
        assert recovery.status_code == 204
        assert recovery.headers["access-control-allow-origin"] == "*"
        execution = client.options("/v1/services/instagram.feed/execute", headers=headers)
        assert "access-control-allow-origin" not in execution.headers
