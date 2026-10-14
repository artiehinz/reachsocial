"""Wallet login and consent around the MCP SDK authorization server."""

from __future__ import annotations

import secrets
import time
from datetime import UTC, datetime
from urllib.parse import urlencode

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_keys.exceptions import BadSignature
from eth_utils import is_address, to_checksum_address
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from mcp.server.auth.provider import AuthorizationParams
from mcp.server.auth.routes import create_auth_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from pydantic import AnyHttpUrl
from sqlalchemy import select

from .db import SessionLocal
from .oauth_provider import SCOPE, ReachSocialOAuthProvider, origin, resource, wallet_allowed
from .oauth_store import OAuthState, consume, get, put, rate_limit, revoke_family, secret

router = APIRouter(include_in_schema=False)
provider = ReachSocialOAuthProvider()
SESSION_COOKIE = "reachsocial_session"


def require_origin(request: Request) -> None:
    if request.headers.get("origin") != origin():
        raise HTTPException(403, "A same-origin browser request is required")


def browser_session(request: Request, *, csrf: bool = False) -> dict:
    with SessionLocal() as session:
        row = get(session, "session", request.cookies.get(SESSION_COOKIE, ""))
        if not row:
            raise HTTPException(401, "Sign in with your wallet")
        payload = dict(row.payload)
        if not wallet_allowed(payload["address"]):
            raise HTTPException(403, "Self-service access is in limited validation")
    if csrf:
        require_origin(request)
        if not secrets.compare_digest(
            request.headers.get("x-reachsocial-csrf", ""), payload["csrf"]
        ):
            raise HTTPException(403, "Invalid session protection token")
    return payload


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat().replace("+00:00", "Z")


async def object_body(request: Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "Invalid JSON") from None
    if not isinstance(body, dict):
        raise HTTPException(400, "Expected a JSON object")
    return body


@router.post("/auth/challenge")
async def challenge(request: Request):
    require_origin(request)
    body = await object_body(request)
    address = body.get("address")
    if not isinstance(address, str) or not is_address(address):
        raise HTTPException(400, "Invalid wallet address")
    address = to_checksum_address(address)
    if not wallet_allowed(address):
        raise HTTPException(403, "Self-service access is in limited validation")
    nonce, flow = secrets.token_hex(16), secret()
    now = time.time()
    domain = origin().split("://", 1)[1]
    message = (
        f"{domain} wants you to sign in with your Ethereum account:\n{address}\n\n"
        "Sign in to ReachSocial. This does not authorize payments or transfers.\n\n"
        f"URI: {origin()}/account\nVersion: 1\nChain ID: 8453\nNonce: {nonce}\n"
        f"Issued At: {iso(now)}\nExpiration Time: {iso(now + 300)}"
    )
    with SessionLocal() as session:
        put(session, "challenge", flow, {"address": address.lower(), "message": message}, 300)
        session.commit()
    response = JSONResponse({"message": message})
    response.set_cookie(
        "reachsocial_login",
        flow,
        max_age=300,
        httponly=True,
        secure=origin().startswith("https:"),
        samesite="strict",
        path="/auth",
    )
    return response


@router.post("/auth/verify")
async def verify(request: Request):
    require_origin(request)
    body = await object_body(request)
    signature = body.get("signature")
    if not isinstance(signature, str) or len(signature) != 132:
        raise HTTPException(400, "An externally owned wallet signature is required")
    flow = request.cookies.get("reachsocial_login", "")
    with SessionLocal() as session:
        row = get(session, "challenge", flow)
        if not row:
            raise HTTPException(400, "Login challenge expired or already used")
        try:
            address = Account.recover_message(
                encode_defunct(text=row.payload["message"]), signature=signature
            )
        except (ValueError, TypeError, BadSignature):
            raise HTTPException(400, "Invalid wallet signature") from None
        if (
            not wallet_allowed(address)
            or address.lower() != row.payload["address"]
            or not consume(session, "challenge", flow)
        ):
            raise HTTPException(400, "Invalid or already used challenge")
        token, csrf = secret(), secret()
        put(
            session,
            "session",
            token,
            {"address": address.lower(), "csrf": csrf},
            86400,
            owner=address.lower(),
        )
        session.commit()
    response = JSONResponse({"address": address.lower(), "csrf": csrf})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=86400,
        httponly=True,
        secure=origin().startswith("https:"),
        samesite="lax",
        path="/",
    )
    response.delete_cookie("reachsocial_login", path="/auth")
    return response


@router.get("/auth/session")
async def session_info(request: Request):
    identity = browser_session(request)
    with SessionLocal() as session:
        rows = session.scalars(
            select(OAuthState).where(
                OAuthState.owner == identity["address"],
                OAuthState.kind == "refresh",
                OAuthState.consumed.is_(False),
                OAuthState.expires_at > time.time(),
            )
        ).all()
        grants = [{"id": row.family, "client_id": row.payload["client_id"]} for row in rows]
    return {**identity, "connections": grants}


@router.post("/auth/logout")
async def logout(request: Request):
    browser_session(request, csrf=True)
    with SessionLocal() as session:
        consume(session, "session", request.cookies.get(SESSION_COOKIE, ""))
        session.commit()
    response = JSONResponse({"status": "signed_out"})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.post("/auth/connections/revoke")
async def revoke_connection(request: Request):
    identity = browser_session(request, csrf=True)
    body = await object_body(request)
    with SessionLocal() as session:
        row = session.scalar(
            select(OAuthState).where(
                OAuthState.family == str(body.get("id", "")),
                OAuthState.owner == identity["address"],
                OAuthState.kind == "refresh",
            )
        )
        if not row:
            raise HTTPException(404, "Connection not found")
        revoke_family(session, row.family)
        session.commit()
    return {"status": "revoked"}


@router.get("/auth/consent")
async def consent_details(request: Request, flow: str):
    browser_session(request)
    with SessionLocal() as session:
        row = get(session, "authorization", flow)
        if not row:
            raise HTTPException(400, "Authorization expired")
        return {
            "client_name": row.payload["client_name"],
            "client_id": row.payload["client_id"],
            "redirect_uri": row.payload["params"]["redirect_uri"],
            "scope": SCOPE,
            "message": "Access public tools and your requests. Each payment needs separate approval.",
        }


@router.post("/auth/consent")
async def consent(request: Request):
    identity = browser_session(request, csrf=True)
    body = await object_body(request)
    with SessionLocal() as session:
        flow = str(body.get("flow", ""))
        row = get(session, "authorization", flow)
        if not row or not consume(session, "authorization", flow):
            raise HTTPException(400, "Authorization expired or already used")
        params = AuthorizationParams.model_validate(row.payload["params"])
        result = {"state": params.state, "iss": origin()}
        if body.get("approve") is True:
            code = secret()
            payload = params.model_dump(mode="json")
            payload.pop("state")
            payload.update(client_id=row.payload["client_id"], subject=identity["address"])
            put(session, "code", code, payload, 120, owner=identity["address"])
            result["code"] = code
        else:
            result["error"] = "access_denied"
        session.commit()
    separator = "&" if "?" in str(params.redirect_uri) else "?"
    return {
        "redirect": str(params.redirect_uri)
        + separator
        + urlencode({k: v for k, v in result.items() if v is not None})
    }


def install_oauth(app, settings):
    app.include_router(router)

    @app.get("/.well-known/oauth-authorization-server", include_in_schema=False)
    async def authorization_metadata():
        return {
            "issuer": origin(),
            "authorization_endpoint": origin() + "/authorize",
            "token_endpoint": origin() + "/token",
            "registration_endpoint": origin() + "/register",
            "revocation_endpoint": origin() + "/revoke",
            "scopes_supported": [SCOPE],
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "revocation_endpoint_auth_methods_supported": ["none"],
            "client_id_metadata_document_supported": True,
            "authorization_response_iss_parameter_supported": True,
        }

    routes = create_auth_routes(
        provider,
        AnyHttpUrl(origin()),
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]
        ),
        revocation_options=RevocationOptions(enabled=True),
    )
    app.router.routes.extend(
        route for route in routes if route.path != "/.well-known/oauth-authorization-server"
    )

    @app.get("/.well-known/oauth-protected-resource/mcp/", include_in_schema=False)
    @app.get("/.well-known/oauth-protected-resource/mcp", include_in_schema=False)
    async def protected_resource():
        return {
            "resource": resource(),
            "authorization_servers": [origin()],
            "scopes_supported": [SCOPE],
            "bearer_methods_supported": ["header"],
        }

    @app.middleware("http")
    async def auth_guard(request: Request, call_next):
        path = request.url.path
        if path in {
            "/.well-known/oauth-authorization-server",
            "/.well-known/oauth-protected-resource/mcp",
            "/.well-known/oauth-protected-resource/mcp/",
        } and request.method == "GET":
            response = await call_next(request)
            response.headers["Access-Control-Allow-Origin"] = "*"
            return response
        if path in {"/authorize", "/token", "/register", "/revoke"} or path.startswith("/auth/"):
            # Untrusted forwarded addresses are deliberately not used for quotas.
            identity = request.client.host if request.client else "unknown"
            with SessionLocal() as session:
                allowed = rate_limit(session, "global", "oauth_total", 600)
                if allowed:
                    allowed = rate_limit(session, identity, "oauth", 60)
                if path == "/register":
                    allowed = rate_limit(session, "global", "registration", 10) and allowed
                session.commit()
            if not allowed:
                return JSONResponse(
                    {"error": "temporarily_unavailable"},
                    status_code=429,
                    headers={"Retry-After": "60"},
                )
            if path == "/token":
                await request.body()
                form = await request.form()
                if form.get("resource") != resource():
                    return JSONResponse({"error": "invalid_target"}, status_code=400)
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            return response
        return await call_next(request)
