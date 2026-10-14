"""ReachSocial persistence behind the MCP SDK's OAuth protocol handlers."""

from __future__ import annotations

import asyncio
import http.client
import ipaddress
import json
import socket
import ssl
import time
from urllib.parse import urlsplit

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from .config import get_settings
from .db import SessionLocal
from .oauth_store import consume, get, put, rate_limit, revoke_family, secret

SCOPE = "reachsocial:requests"


def origin() -> str:
    return str(get_settings().public_base_url).rstrip("/")


def resource() -> str:
    return origin() + "/mcp/"


def wallet_allowed(address: str) -> bool:
    allowed = {
        item.strip().lower()
        for item in get_settings().oauth_validation_wallets.split(",")
        if item.strip()
    }
    return not allowed or address.lower() in allowed


def _metadata_document(client_id: str) -> dict:
    """Fetch a bounded HTTPS document with DNS pinned before connecting."""
    if len(client_id) > 2048:
        raise ValueError("Client metadata URL too long")
    url = urlsplit(client_id)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.fragment
        or url.query
        or url.port not in (None, 443)
        or url.path in ("", "/")
    ):
        raise ValueError("Invalid client metadata URL")
    addresses = socket.getaddrinfo(url.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Client metadata must resolve to public addresses")
    host = url.hostname
    address = addresses[0][4][0]

    class PinnedHTTPS(http.client.HTTPSConnection):
        def connect(self):
            sock = socket.create_connection((address, 443), timeout=4)
            try:
                self.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
            except BaseException:
                sock.close()
                raise

    conn = PinnedHTTPS(host, timeout=4)
    try:
        conn.request("GET", url.path, headers={"Accept": "application/json"})
        response = conn.getresponse()
        if response.status != 200:
            raise ValueError("Client metadata unavailable; redirects are not followed")
        raw = response.read(16_385)
        if len(raw) > 16_384:
            raise ValueError("Client metadata too large")
        document = json.loads(raw)
        if not isinstance(document, dict) or document.get("client_id") != client_id:
            raise ValueError("Client metadata identifier mismatch")
        return document
    finally:
        conn.close()


def validate_client(client: OAuthClientInformationFull) -> None:
    if len(client.model_dump_json()) > 16_384:
        raise RegistrationError("invalid_client_metadata", "Client metadata is too large")
    if client.token_endpoint_auth_method != "none" or client.client_secret:
        raise RegistrationError(
            "invalid_client_metadata", "Use a public PKCE client (auth method none)"
        )
    if not client.redirect_uris or len(client.redirect_uris) > 10:
        raise RegistrationError("invalid_redirect_uri", "Provide 1–10 redirect URIs")
    if client.client_name and len(client.client_name) > 200:
        raise RegistrationError("invalid_client_metadata", "Client name is too long")
    for uri in client.redirect_uris:
        if len(str(uri)) > 2048:
            raise RegistrationError("invalid_redirect_uri", "Redirect URI is too long")
        u = urlsplit(str(uri))
        if (
            u.username
            or u.password
            or u.fragment
            or not u.hostname
            or (
                u.scheme != "https"
                and not (
                    u.scheme == "http" and u.hostname in {"127.0.0.1", "[::1]", "::1", "localhost"}
                )
            )
        ):
            raise RegistrationError("invalid_redirect_uri", "HTTPS or loopback redirect required")
    if set(client.grant_types) - {"authorization_code", "refresh_token"}:
        raise RegistrationError("invalid_client_metadata", "Unsupported grant type")
    if set((client.scope or SCOPE).split()) - {SCOPE}:
        raise RegistrationError("invalid_client_metadata", "Unsupported scope")


class ReachSocialOAuthProvider:
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with SessionLocal() as session:
            row = get(session, "client", client_id)
            if row:
                return OAuthClientInformationFull.model_validate(row.payload)
        if not client_id.startswith("https://"):
            return None
        with SessionLocal() as session:
            allowed = rate_limit(session, "global", "client_metadata", 20)
            session.commit()
        if not allowed:
            return None
        try:
            document = await asyncio.wait_for(
                asyncio.to_thread(_metadata_document, client_id), timeout=6
            )
            client = OAuthClientInformationFull.model_validate(document)
            validate_client(client)
            # Cache only public metadata. Clients cannot use secrets or remote keys.
            with SessionLocal() as session:
                existing = get(session, "client", client_id, used=True)
                if existing:
                    existing.payload = client.model_dump(mode="json")
                    existing.expires_at = time.time() + 300
                else:
                    from .oauth_store import OAuthState, digest

                    expired = session.get(OAuthState, digest(client_id))
                    if expired:
                        session.delete(expired)
                        session.flush()
                    put(session, "client", client_id, client.model_dump(mode="json"), 300)
                session.commit()
            return client
        except (ValueError, OSError, TimeoutError, RegistrationError, http.client.HTTPException):
            return None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        validate_client(client_info)
        with SessionLocal() as session:
            put(
                session,
                "client",
                client_info.client_id,
                client_info.model_dump(mode="json"),
                86400 * 90,
            )
            session.commit()

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        if params.resource != resource():
            raise AuthorizeError("invalid_target", "Use the canonical ReachSocial MCP resource")
        if not params.scopes or set(params.scopes) != {SCOPE}:
            raise AuthorizeError("invalid_scope", "Request reachsocial:requests")
        # SDK permits loopback matching rules; this service requires the registered URI exactly.
        if str(params.redirect_uri) not in {str(uri) for uri in client.redirect_uris}:
            raise AuthorizeError("invalid_request", "Redirect URI must match exactly")
        flow = secret()
        with SessionLocal() as session:
            put(
                session,
                "authorization",
                flow,
                {
                    "client_id": client.client_id,
                    "client_name": client.client_name or client.client_id,
                    "params": params.model_dump(mode="json"),
                },
                600,
            )
            session.commit()
        return origin() + "/account?authorize=" + flow

    async def load_authorization_code(self, client, authorization_code):
        with SessionLocal() as session:
            row = get(session, "code", authorization_code)
            if not row or row.payload["client_id"] != client.client_id:
                return None
            return AuthorizationCode(
                code=authorization_code, expires_at=row.expires_at, **row.payload
            )

    def _issue(self, session, client_id, subject, scopes, family):
        access, refresh = secret(), secret()
        payload = {
            "client_id": client_id,
            "subject": subject,
            "scopes": scopes,
            "resource": resource(),
        }
        put(session, "access", access, payload, 900, owner=subject, family=family)
        put(session, "refresh", refresh, payload, 86400 * 30, owner=subject, family=family)
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=900,
            refresh_token=refresh,
            scope=" ".join(scopes),
        )

    async def exchange_authorization_code(self, client, authorization_code):
        with SessionLocal() as session:
            row = get(session, "code", authorization_code.code)
            if (
                not row
                or row.payload["client_id"] != client.client_id
                or not consume(session, "code", authorization_code.code)
            ):
                raise TokenError("invalid_grant", "Code expired or already used")
            family = secret()
            token = self._issue(
                session, client.client_id, row.payload["subject"], row.payload["scopes"], family
            )
            session.commit()
            return token

    async def load_refresh_token(self, client, refresh_token):
        with SessionLocal() as session:
            row = get(session, "refresh", refresh_token, used=True)
            if not row or row.payload["client_id"] != client.client_id:
                return None
            if row.consumed:
                revoke_family(session, row.family)
                session.commit()
                return None
            return RefreshToken(
                token=refresh_token,
                client_id=client.client_id,
                scopes=row.payload["scopes"],
                subject=row.owner,
                expires_at=int(row.expires_at),
            )

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        with SessionLocal() as session:
            row = get(session, "refresh", refresh_token.token, used=True)
            if not row or row.payload["client_id"] != client.client_id:
                raise TokenError("invalid_grant", "Invalid refresh token")
            if not set(scopes).issubset(row.payload["scopes"]):
                raise TokenError("invalid_scope", "Scope escalation denied")
            if not consume(session, "refresh", refresh_token.token):
                revoke_family(session, row.family)
                session.commit()
                raise TokenError("invalid_grant", "Refresh token already used")
            # Retire prior access tokens as well as the old refresh token.
            from sqlalchemy import update

            from .oauth_store import OAuthState

            session.execute(
                update(OAuthState)
                .where(
                    OAuthState.family == row.family,
                    OAuthState.kind == "access",
                )
                .values(consumed=True)
            )
            token = self._issue(session, client.client_id, row.owner, scopes, row.family)
            session.commit()
            return token

    async def load_access_token(self, token):
        with SessionLocal() as session:
            row = get(session, "access", token)
            if not row or row.payload["resource"] != resource() or not wallet_allowed(row.owner):
                return None
            return AccessToken(token=token, expires_at=int(row.expires_at), **row.payload)

    async def revoke_token(self, token):
        with SessionLocal() as session:
            kind = "refresh" if isinstance(token, RefreshToken) else "access"
            row = get(session, kind, token.token, used=True)
            if row:
                revoke_family(session, row.family)
                session.commit()
