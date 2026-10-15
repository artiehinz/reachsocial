"""Fresh MCP SDK client over real loopback HTTP; no payments or provider credentials."""

import asyncio
import base64
import hashlib
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import httpx2
import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


@pytest.fixture
def isolated_http_app(tmp_path):
    database = tmp_path / "client-check.db"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        base = f"http://127.0.0.1:{listener.getsockname()[1]}"
        # A clean environment and empty cwd prevent loading the checkout's .env.
        environment = {
            "APP_ENV": "client-verification",
            "PUBLIC_BASE_URL": base,
            "DATABASE_URL": f"sqlite:///{database}",
            "CATALOG_PATH": str(Path(__file__).resolve().parents[1] / "config/services.yaml"),
            "OAUTH_ENABLED": "true",
            "MCP_ENABLED": "true",
            "MCP_PAYMENT_APPROVAL_ENABLED": "true",
            "X402_ENABLED": "false",
        }
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "reachsocial.main:app",
                "--fd",
                str(listener.fileno()),
            ],
            cwd=tmp_path,
            env=environment,
            pass_fds=(listener.fileno(),),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            with httpx.Client(base_url=base, timeout=5, trust_env=False) as browser:
                for _ in range(100):
                    assert server.poll() is None, "Isolated application exited during startup"
                    try:
                        if browser.get("/healthz").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail("Isolated application did not become healthy")
                yield browser, base, database
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


def test_fresh_sdk_client_pkce_refresh_revocation_and_unpaid_recovery(isolated_http_app):
    browser, base, database = isolated_http_app
    resource = base + "/mcp/"
    metadata = browser.get("/.well-known/oauth-authorization-server").json()
    assert metadata["issuer"] == base
    assert "S256" in metadata["code_challenge_methods_supported"]
    wallet = Account.create()  # Unfunded test identity, only an in-memory SIWE signature.
    origin = {"Origin": base}
    challenge = browser.post("/auth/challenge", json={"address": wallet.address}, headers=origin)
    assert challenge.status_code == 200
    signed = wallet.sign_message(encode_defunct(text=challenge.json()["message"]))
    identity = browser.post(
        "/auth/verify", json={"signature": "0x" + signed.signature.hex()}, headers=origin
    )
    assert identity.status_code == 200
    csrf = {**origin, "X-ReachSocial-CSRF": identity.json()["csrf"]}
    redirect = "http://127.0.0.1:8765/callback"
    registration = browser.post(
        "/register",
        json={
            "client_name": "Fresh SDK unpaid verification",
            "redirect_uris": [redirect],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "scope": "reachsocial:requests",
        },
    )
    assert registration.status_code == 201
    client_id = registration.json()["client_id"]
    verifier, state = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    pkce = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    authorized = browser.get(
        "/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": "reachsocial:requests",
            "state": state,
            "resource": resource,
            "code_challenge": pkce,
            "code_challenge_method": "S256",
        },
    )
    assert authorized.status_code == 302
    flow = parse_qs(urlsplit(authorized.headers["location"]).query)["authorize"][0]
    assert browser.post("/auth/consent", json={"flow": flow, "approve": True}).status_code == 403
    consent = browser.post("/auth/consent", json={"flow": flow, "approve": True}, headers=csrf)
    assert consent.status_code == 200
    callback = parse_qs(urlsplit(consent.json()["redirect"]).query)
    assert callback["state"] == [state] and callback["iss"] == [base]
    form = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": callback["code"][0],
        "redirect_uri": redirect,
        "code_verifier": verifier,
        "resource": resource,
    }
    assert browser.post("/token", data={**form, "code_verifier": "wrong" * 10}).status_code == 400
    issued = browser.post("/token", data=form)
    assert issued.status_code == 200
    tokens = issued.json()
    assert browser.post("/token", data=form).status_code == 400
    key = secrets.token_urlsafe(32)

    async def mcp_request(access, request_id=None):
        async with httpx2.AsyncClient(
            headers={"Authorization": "Bearer " + access}, trust_env=False
        ) as transport:
            async with streamable_http_client(resource, http_client=transport) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    names = {tool.name for tool in tools.tools}
                    assert {"instagram_profile", "get_reachsocial_request"} <= names
                    assert "youtube_video" in names
                    assert "news_person" not in names
                    if request_id:
                        result = await session.call_tool(
                            "get_reachsocial_request", {"request_id": request_id}
                        )
                    else:
                        arguments = {
                            "url": "https://www.instagram.com/instagram/",
                            "idempotency_key": key,
                        }
                        result = await session.call_tool("instagram_profile", arguments)
                        repeated = await session.call_tool("instagram_profile", arguments)
                        assert repeated.structured_content == result.structured_content
                    assert not result.is_error
                    return result.structured_content

    request = asyncio.run(mcp_request(tokens["access_token"]))
    assert request["status"] == "payment_required"
    assert request["price_cents"] == 5
    assert request["payment_url"].startswith(base + "/pay/")
    refresh = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": tokens["refresh_token"],
        "resource": resource,
    }
    rotated = browser.post("/token", data=refresh)
    assert rotated.status_code == 200
    renewed = rotated.json()
    assert asyncio.run(mcp_request(renewed["access_token"], request["request_id"])) == request
    assert (
        browser.post(
            "/mcp/", headers={"Authorization": "Bearer " + tokens["access_token"]}, json={}
        ).status_code
        == 401
    )
    connection = browser.get("/auth/session").json()["connections"][0]
    assert (
        browser.post(
            "/auth/connections/revoke", json={"id": connection["id"]}, headers=csrf
        ).status_code
        == 200
    )
    assert (
        browser.post(
            "/mcp/", headers={"Authorization": "Bearer " + renewed["access_token"]}, json={}
        ).status_code
        == 401
    )
    assert (
        browser.post(
            "/token", data={**refresh, "refresh_token": renewed["refresh_token"]}
        ).status_code
        == 400
    )
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT count(*) FROM payment_receipts").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM provider_attempts").fetchone()[0] == 0
