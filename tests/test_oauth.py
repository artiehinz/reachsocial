from __future__ import annotations

import asyncio
import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from reachsocial import mcp_requests, oauth_provider, oauth_routes, payments
from reachsocial.config import get_settings
from reachsocial.db import Base, make_engine
from reachsocial.main import create_app
from reachsocial.oauth_provider import SCOPE, _metadata_document
from reachsocial.oauth_store import OAuthState, consume, digest, get, prune, put, rate_limit


@pytest.fixture
def oauth_app(monkeypatch, tmp_path):
    monkeypatch.setenv("OAUTH_ENABLED", "true")
    monkeypatch.setenv("MCP_PAYMENT_APPROVAL_ENABLED", "true")
    monkeypatch.setenv("MCP_ENABLED", "false")
    monkeypatch.setenv("X402_ENABLED", "false")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost:8000")
    get_settings.cache_clear()
    engine = make_engine(f"sqlite:///{tmp_path / 'oauth.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(oauth_provider, "SessionLocal", factory)
    monkeypatch.setattr(oauth_routes, "SessionLocal", factory)
    monkeypatch.setattr(mcp_requests, "SessionLocal", factory)
    monkeypatch.setattr(payments, "SessionLocal", factory)
    client = TestClient(create_app(), base_url="http://localhost:8000")
    yield client, factory
    client.close()
    get_settings.cache_clear()


def login(client):
    wallet = Account.create()
    headers = {"Origin": "http://localhost:8000"}
    challenge = client.post("/auth/challenge", json={"address": wallet.address}, headers=headers)
    assert challenge.status_code == 200
    message = challenge.json()["message"]
    assert "This does not authorize payments" in message
    signature = "0x" + wallet.sign_message(encode_defunct(text=message)).signature.hex()
    response = client.post("/auth/verify", json={"signature": signature}, headers=headers)
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    return wallet, response.json(), signature


def grant(client):
    wallet, identity, _ = login(client)
    registration = client.post(
        "/register",
        json={
            "client_name": "Test Agent",
            "redirect_uris": ["https://client.example/callback"],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "scope": SCOPE,
        },
    )
    assert registration.status_code == 201, registration.text
    client_id = registration.json()["client_id"]
    verifier = "a" * 64
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    response = client.get(
        "/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": "https://client.example/callback",
            "scope": SCOPE,
            "response_type": "code",
            "state": "test-state",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": "http://localhost:8000/mcp/",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302, response.text
    flow = parse_qs(urlsplit(response.headers["location"]).query)["authorize"][0]
    consent = client.post(
        "/auth/consent",
        json={"flow": flow, "approve": True},
        headers={
            "Origin": "http://localhost:8000",
            "X-ReachSocial-CSRF": identity["csrf"],
        },
    )
    assert consent.status_code == 200, consent.text
    query = parse_qs(urlsplit(consent.json()["redirect"]).query)
    assert query["state"] == ["test-state"]
    assert query["iss"] == ["http://localhost:8000"]
    return (
        {
            "grant_type": "authorization_code",
            "code": query["code"][0],
            "code_verifier": verifier,
            "client_id": client_id,
            "redirect_uri": "https://client.example/callback",
            "resource": "http://localhost:8000/mcp/",
        },
        wallet,
        identity,
    )


def test_login_replay_and_csrf(oauth_app):
    client, factory = oauth_app
    wallet, identity, signature = login(client)
    assert client.get("/auth/session").json()["address"] == wallet.address.lower()
    assert client.post("/auth/logout", json={}).status_code == 403
    assert (
        client.post(
            "/auth/verify",
            json={"signature": signature},
            headers={"Origin": "http://localhost:8000"},
        ).status_code
        == 400
    )
    with factory() as session:
        assert signature not in str([row.payload for row in session.scalars(select(OAuthState))])
    assert (
        client.post(
            "/auth/logout",
            json={},
            headers={"Origin": "http://localhost:8000", "X-ReachSocial-CSRF": identity["csrf"]},
        ).status_code
        == 200
    )
    assert client.get("/auth/session").status_code == 401


def test_oauth_exchange_rotation_reuse_and_hashes(oauth_app):
    client, factory = oauth_app
    form, wallet, _ = grant(client)
    wrong = {**form, "code_verifier": "b" * 64}
    assert client.post("/token", data=wrong).status_code == 400
    assert (
        client.post("/token", data={**form, "resource": "https://other.example/mcp"}).status_code
        == 400
    )
    response = client.post("/token", data=form)
    assert response.status_code == 200, response.text
    tokens = response.json()
    assert client.post("/token", data=form).status_code == 400
    token = asyncio.run(oauth_routes.provider.load_access_token(tokens["access_token"]))
    assert token.subject == wallet.address.lower()
    with factory() as session:
        rows = list(session.scalars(select(OAuthState)))
        stored = str([(r.key, r.payload) for r in rows])
        assert tokens["access_token"] not in stored
        assert tokens["refresh_token"] not in stored
        assert form["code"] not in stored
    refresh = {
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
        "client_id": form["client_id"],
        "resource": form["resource"],
    }
    rotated = client.post("/token", data=refresh)
    assert rotated.status_code == 200, rotated.text
    assert asyncio.run(oauth_routes.provider.load_access_token(tokens["access_token"])) is None
    assert client.post("/token", data=refresh).status_code == 400
    assert (
        asyncio.run(oauth_routes.provider.load_access_token(rotated.json()["access_token"])) is None
    )


def test_metadata_and_registration(oauth_app):
    client, _ = oauth_app
    for path in [
        "/.well-known/oauth-authorization-server",
        "/.well-known/oauth-protected-resource/mcp/",
    ]:
        assert client.get(path).headers["access-control-allow-origin"] == "*"
    metadata = client.get("/.well-known/oauth-protected-resource/mcp/").json()
    assert metadata["resource"] == "http://localhost:8000/mcp/"
    assert metadata["authorization_servers"] == ["http://localhost:8000"]
    response = client.post(
        "/register",
        json={
            "redirect_uris": ["https://client.example/cb"],
            "token_endpoint_auth_method": "client_secret_post",
        },
    )
    assert response.status_code == 400
    response = client.post(
        "/register",
        json={"redirect_uris": ["http://remote.example/cb"], "token_endpoint_auth_method": "none"},
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/meta",
        "https://user:pass@example.com/meta",
        "https://127.0.0.1/meta",
        "https://[::1]/meta",
        "https://example.com:8443/meta",
    ],
)
def test_metadata_blocks_unsafe_destinations(url):
    with pytest.raises(ValueError):
        _metadata_document(url)


def test_store_consumption_and_rate_limits(session):
    put(session, "code", "test-secret", {}, 120)
    session.commit()
    assert consume(session, "code", "test-secret")
    assert not consume(session, "code", "test-secret")
    assert get(session, "code", "test-secret") is None
    assert rate_limit(session, "client", "action", 2)
    assert rate_limit(session, "client", "action", 2)
    assert not rate_limit(session, "client", "action", 2)


def test_prune_removes_expired_unpaid_intents_but_keeps_ambiguous_attempts(session) -> None:
    put(session, "session", "expired-session", {}, 1)
    put(
        session,
        "mcp_request",
        "expired-unpaid",
        {"payment_key": "mcp_unpaid", "service": "instagram.profile"},
        1,
    )
    put(
        session,
        "mcp_request",
        "ambiguous-attempt",
        {
            "payment_key": "mcp_ambiguous",
            "service": "instagram.profile",
            "payment_attempted": True,
        },
        1,
    )
    session.commit()

    assert prune(session, now=10**12) == 2
    session.commit()
    assert get(session, "mcp_request", "expired-unpaid", used=True) is None
    # No request/result record exists, so a signed attempt stays for reconciliation.
    assert session.get(OAuthState, digest("ambiguous-attempt"))


def test_mcp_intent_is_owned_idempotent_and_requires_payment(oauth_app):
    from reachsocial.catalog import load_catalog
    from reachsocial.mcp_requests import create_request, current_principal, retrieve_request

    client, factory = oauth_app
    wallet, identity, _ = login(client)
    principal = {"subject": wallet.address.lower(), "client_id": "agent-one"}
    token = current_principal.set(principal)
    try:
        service = load_catalog().by_id("instagram.profile")
        result = create_request(service, {"url": "https://www.instagram.com/instagram/"}, "a" * 32)
        assert result["status"] == "payment_required"
        assert result["price_cents"] == 5
        assert (
            create_request(service, {"url": "https://www.instagram.com/instagram/"}, "a" * 32)
            == result
        )
        assert retrieve_request(result["request_id"]) == result
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as conflict:
            create_request(service, {"url": "https://www.instagram.com/example/"}, "a" * 32)
        assert conflict.value.status_code == 409
        current_principal.set({**principal, "client_id": "agent-two"})
        with pytest.raises(HTTPException) as denied:
            retrieve_request(result["request_id"])
        assert denied.value.status_code == 404
        path = "/account/requests/" + result["request_id"]
        assert client.get(path).status_code == 200
        headers = {"Origin": "http://localhost:8000", "X-ReachSocial-CSRF": identity["csrf"]}
        approval = client.post(path + "/approve", json={}, headers=headers)
        assert approval.status_code == 200, approval.text
        assert "payment_key" not in client.get(path).json()
        assert client.post(path + "/approve", json={}, headers=headers).status_code == 409
        assert client.get(path).json()["status"] == "awaiting_approval"
        from reachsocial.models import PaymentReceipt, ProviderAttempt

        with factory() as session:
            assert list(session.scalars(select(PaymentReceipt))) == []
            assert list(session.scalars(select(ProviderAttempt))) == []
    finally:
        current_principal.reset(token)


def test_private_mcp_validation_request_requires_the_owner_wallet(oauth_app, monkeypatch):
    from fastapi import HTTPException

    from reachsocial.catalog import load_catalog
    from reachsocial.mcp_requests import create_request, current_principal

    client, _ = oauth_app
    wallet, _, _ = login(client)
    monkeypatch.setenv("OAUTH_VALIDATION_WALLETS", wallet.address)
    monkeypatch.setenv("MAINNET_PRIVATE_ACCEPTANCE_ENABLED", "true")
    monkeypatch.setenv("MAINNET_PRIVATE_ACCEPTANCE_SERVICES", "instagram.feed")
    get_settings.cache_clear()
    owner = current_principal.set({"subject": wallet.address.lower(), "client_id": "owner-agent"})
    try:
        request = create_request(
            load_catalog().by_id("instagram.feed"),
            {"url": "https://www.instagram.com/instagram/", "max_items": 5},
            "p" * 32,
        )
        assert request["status"] == "payment_required"
        assert request["payment_endpoint"] == "/v1/acceptance/private/instagram.feed/execute"
    finally:
        current_principal.reset(owner)
    other = current_principal.set(
        {"subject": "0x0000000000000000000000000000000000000000", "client_id": "other-agent"}
    )
    try:
        with pytest.raises(HTTPException, match="limited validation") as denied:
            create_request(
                load_catalog().by_id("instagram.feed"),
                {"url": "https://www.instagram.com/instagram/", "max_items": 5},
                "q" * 32,
            )
        assert denied.value.status_code == 403
    finally:
        current_principal.reset(other)


def test_mcp_guard_rejects_changed_input_and_replayed_approval(oauth_app):
    import json

    from fastapi import HTTPException
    from starlette.requests import Request

    from reachsocial.catalog import load_catalog
    from reachsocial.mcp_requests import create_request, current_principal, guard_payment

    client, _ = oauth_app
    wallet, identity, _ = login(client)
    token = current_principal.set({"subject": wallet.address.lower(), "client_id": "test-agent"})
    try:
        result = create_request(
            load_catalog().by_id("instagram.profile"),
            {"url": "https://www.instagram.com/instagram/"},
            "b" * 32,
        )
    finally:
        current_principal.reset(token)
    approval = client.post(
        "/account/requests/" + result["request_id"] + "/approve",
        json={},
        headers={"Origin": "http://localhost:8000", "X-ReachSocial-CSRF": identity["csrf"]},
    ).json()

    def request(target, signed=True):
        body = json.dumps({"input": {"url": target}}).encode()

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        headers = [(b"x-reachsocial-approval", approval["authorization"].encode())]
        if signed:
            headers.append((b"payment-signature", b"opaque-test-payload"))
        return Request({"type": "http", "method": "POST", "path": "/", "headers": headers}, receive)

    with pytest.raises(HTTPException):
        asyncio.run(
            guard_payment(
                request("https://www.instagram.com/other/"),
                "instagram.profile",
                approval["payment_key"],
            )
        )
    correct = "https://www.instagram.com/instagram/"
    with pytest.raises(HTTPException) as invalid:
        asyncio.run(
            guard_payment(request("not-a-url"), "instagram.profile", approval["payment_key"])
        )
    assert invalid.value.status_code == 422
    assert (
        asyncio.run(
            guard_payment(request(correct, False), "instagram.profile", approval["payment_key"])
        )
        == wallet.address.lower()
    )
    assert (
        asyncio.run(
            guard_payment(
                request(correct), "instagram.profile", approval["payment_key"], dispatch=True
            )
        )
        == wallet.address.lower()
    )
    with pytest.raises(HTTPException):
        asyncio.run(
            guard_payment(
                request(correct), "instagram.profile", approval["payment_key"], dispatch=True
            )
        )
    assert (
        client.get("/account/requests/" + result["request_id"]).json()["status"]
        == "reconciliation_required"
    )


def test_wrong_payer_is_rejected_before_any_provider_balance_call(monkeypatch):
    from types import SimpleNamespace

    from reachsocial.mcp_requests import expected_mcp_payer

    monkeypatch.setattr(payments, "payment_id_from_payload", lambda _: "test-payment")
    monkeypatch.setattr(
        payments, "fetch_provider_balance", lambda *_: pytest.fail("No provider call permitted")
    )
    token = expected_mcp_payer.set("0x1111111111111111111111111111111111111111")
    try:
        result = payments.reserve_payment_receipt(
            SimpleNamespace(
                payment_payload={},
                result=SimpleNamespace(payer="0x2222222222222222222222222222222222222222"),
            )
        )
        assert result is not None
        assert result.reason == "mcp_payer_mismatch"
    finally:
        expected_mcp_payer.reset(token)


def test_expired_challenge_wrong_wallet_and_no_store_pages(oauth_app):
    client, factory = oauth_app
    wallet = Account.create()
    headers = {"Origin": "http://localhost:8000"}
    challenge = client.post("/auth/challenge", json={"address": wallet.address}, headers=headers)
    wrong = Account.create().sign_message(encode_defunct(text=challenge.json()["message"]))
    assert (
        client.post(
            "/auth/verify", json={"signature": "0x" + wrong.signature.hex()}, headers=headers
        ).status_code
        == 400
    )
    with factory() as session:
        row = session.scalar(select(OAuthState).where(OAuthState.kind == "challenge"))
        row.expires_at = 1
        session.commit()
    signed = wallet.sign_message(encode_defunct(text=challenge.json()["message"]))
    assert (
        client.post(
            "/auth/verify", json={"signature": "0x" + signed.signature.hex()}, headers=headers
        ).status_code
        == 400
    )
    for path in ["/account", "/pay/test"]:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-robots-tag"] == "noindex, nofollow"
        assert response.headers["referrer-policy"] == "no-referrer"


def test_real_mcp_transport_oauth_discovery_and_payment_intent(oauth_app, monkeypatch):
    client, _ = oauth_app
    form, _, _ = grant(client)
    access = client.post("/token", data=form).json()["access_token"]
    monkeypatch.setenv("MCP_ENABLED", "true")
    get_settings.cache_clear()
    with TestClient(create_app(), base_url="http://localhost:8000") as mcp_client:
        headers = {
            "Authorization": "Bearer " + access,
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        }
        initialize = mcp_client.post(
            "/mcp/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "isolated-test", "version": "1.0"},
                },
            },
        )
        assert initialize.status_code == 200, initialize.text
        tools = mcp_client.post(
            "/mcp/",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert tools.status_code == 200, tools.text
        names = {tool["name"] for tool in tools.json()["result"]["tools"]}
        assert "get_reachsocial_request" in names
        assert "youtube_video" not in names
        called = mcp_client.post(
            "/mcp/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "instagram_profile",
                    "arguments": {
                        "url": "https://www.instagram.com/instagram/",
                        "idempotency_key": "transport-test-" + "a" * 32,
                    },
                },
            },
        )
        assert called.status_code == 200, called.text
        result = called.json()["result"]
        assert not result.get("isError"), result
        structured = result["structuredContent"]
        assert structured["status"] == "payment_required"
        recovered = mcp_client.post(
            "/mcp/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "get_reachsocial_request",
                    "arguments": {"request_id": structured["request_id"]},
                },
            },
        )
        assert (
            recovered.json()["result"]["structuredContent"]["request_id"]
            == structured["request_id"]
        )
        assert mcp_client.post("/mcp/").status_code == 401
        assert "resource_metadata" in mcp_client.post("/mcp/").headers["www-authenticate"]


def test_paid_result_requires_settlement_and_recovers_without_provider(oauth_app, monkeypatch):
    from datetime import timedelta

    from reachsocial.catalog import load_catalog
    from reachsocial.mcp_requests import create_request, current_principal, retrieve_request
    from reachsocial.models import Client, IdempotencyRecord, PaymentReceipt
    from reachsocial.payments import PUBLIC_X402_CLIENT_NAME
    from reachsocial.services import utcnow_naive

    client, factory = oauth_app
    wallet, _, _ = login(client)
    token = current_principal.set(
        {"subject": wallet.address.lower(), "client_id": "recovery-agent"}
    )
    try:
        result = create_request(
            load_catalog().by_id("instagram.profile"),
            {"url": "https://www.instagram.com/instagram/"},
            "c" * 32,
        )
        with factory() as session:
            intent = get(session, "mcp_request", result["request_id"])
            public = Client(
                name=PUBLIC_X402_CLIENT_NAME, api_key_hash="not-a-real-key", billing_mode="external"
            )
            session.add(public)
            session.flush()
            saved = {
                "request_id": "req-recovered",
                "service": "instagram.profile",
                "status": "success",
                "data": {"example": True},
            }
            session.add(
                IdempotencyRecord(
                    client_id=public.id,
                    service_id="instagram.profile",
                    key=intent.payload["payment_key"],
                    input_hash=intent.payload["input_hash"],
                    response_json=saved,
                    expires_at=utcnow_naive() + timedelta(days=30),
                )
            )
            receipt = PaymentReceipt(
                payment_id="test-only",
                service_id="instagram.profile",
                amount_cents=5,
                network="eip155:8453",
                status="verified",
                request_id="req-recovered",
            )
            session.add(receipt)
            session.commit()
        monkeypatch.setattr(
            "reachsocial.services.adapter_for",
            lambda *_: pytest.fail("Recovery must not call provider"),
        )
        waiting = retrieve_request(result["request_id"])
        assert waiting["status"] == "reconciliation_required" and "result" not in waiting
        with factory() as session:
            receipt = session.scalar(select(PaymentReceipt))
            receipt.status = "settled"
            session.commit()
        assert retrieve_request(result["request_id"])["result"] == saved
        assert retrieve_request(result["request_id"])["result"] == saved
        assert (
            create_request(
                load_catalog().by_id("instagram.profile"),
                {"url": "https://www.instagram.com/instagram/"},
                "c" * 32,
            )["result"]
            == saved
        )
    finally:
        current_principal.reset(token)


def test_validation_wallet_gate(oauth_app, monkeypatch):
    client, _ = oauth_app
    monkeypatch.setenv("OAUTH_VALIDATION_WALLETS", "0x1111111111111111111111111111111111111111")
    get_settings.cache_clear()
    response = client.post(
        "/auth/challenge",
        json={"address": Account.create().address},
        headers={"Origin": "http://localhost:8000"},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("ttl", [0, 120])
def test_cimd_public_client_default_and_cache(oauth_app, monkeypatch, ttl):
    _, factory = oauth_app
    client_id = "https://client.example/oauth.json"
    calls = []

    def document(_):
        calls.append(True)
        return {
            "client_id": client_id,
            "client_name": "Document Client",
            "redirect_uris": ["https://client.example/callback"],
            "_reachsocial_cache_seconds": ttl,
        }

    monkeypatch.setattr(oauth_provider, "_metadata_document", document)
    for _ in range(2):
        client = asyncio.run(oauth_routes.provider.get_client(client_id))
        assert client.token_endpoint_auth_method == "none"
    assert len(calls) == (1 if ttl else 2)
    with factory() as session:
        assert bool(get(session, "client", client_id)) == bool(ttl)


def test_cimd_rejects_confidential_only_client(oauth_app, monkeypatch):
    client_id = "https://client.example/oauth.json"
    monkeypatch.setattr(
        oauth_provider,
        "_metadata_document",
        lambda _: {
            "client_id": client_id,
            "client_name": "Confidential client",
            "redirect_uris": ["https://client.example/callback"],
            "token_endpoint_auth_methods_supported": ["private_key_jwt"],
        },
    )
    assert asyncio.run(oauth_routes.provider.get_client(client_id)) is None
