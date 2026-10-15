"""Owner-run OAuth/MCP acceptance. Wallet signing happens only in the browser.

Checkpoint contains public client metadata and request identifiers, not OAuth
bearer tokens, wallet secrets, signatures, or provider responses. Restarting with
the same checkpoint retrieves the original request instead of starting a new one.
"""

from __future__ import annotations

import argparse
import base64
import errno
import hashlib
import json
import os
import secrets
import tempfile
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

BASE = "https://reachsocial.dev"
ASSET = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
STAGED_SERVICES = frozenset({
    "instagram.feed", "instagram.highlight", "youtube.channel", "youtube.video",
    "youtube.feed", "facebook.profile", "reddit.post",
})


def acceptance_service(services: list[dict], service_id: str, private: bool) -> bool:
    return any(
        service.get("id") == service_id
        # Public discovery hides private prices; the MCP intent checks five cents below.
        and (service.get("price_cents") in (None, 5) if private else service.get("price_cents") == 5)
        and service.get("execution") == "sync"
        and (
            service_id in STAGED_SERVICES and service.get("status") == "private"
            if private else service.get("available") is True
        )
        for service in services
    )


def failure_message(exc: Exception) -> str:
    # Do not echo exception text: HTTP errors may contain tokens or callback URLs.
    hint = ""
    if isinstance(exc, OSError):
        if exc.errno == errno.EADDRINUSE:
            hint = " The saved callback port is busy. Close the earlier acceptance run before retrying."
        elif exc.errno in {errno.EACCES, errno.EPERM}:
            hint = " Check checkpoint ownership and local network permissions; run as your desktop user."
        elif exc.errno is not None:
            hint = f" OS error number: {exc.errno}."
    return (
        f"Acceptance stopped ({type(exc).__name__}).{hint} "
        "Keep the checkpoint; no automatic payment retry was made."
    )


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump(value, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def checked(response: httpx.Response) -> dict:
    if response.status_code >= 300:
        raise RuntimeError(
            f"HTTP {response.status_code}; keep the checkpoint and recover, never use a fresh request key"
        )
    value = response.json()
    if not isinstance(value, dict):
        raise RuntimeError("Unexpected server response")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-pay-to", required=True)
    parser.add_argument("--service", default="instagram.profile")
    parser.add_argument("--target", default="https://www.instagram.com/instagram/")
    parser.add_argument("--state-file", type=Path, default=Path("data/mcp-browser-acceptance.json"))
    parser.add_argument("--max-total-atomic", type=int, default=50000)
    parser.add_argument("--confirm-mainnet-payments", action="store_true")
    parser.add_argument("--private-acceptance", action="store_true")
    parser.add_argument("--max-items", type=int, choices=range(1, 6))
    args = parser.parse_args()
    if not args.confirm_mainnet_payments or args.max_total_atomic != 50000:
        parser.error("One request requires --confirm-mainnet-payments and --max-total-atomic 50000")
    request_input = {"url": args.target}
    if args.max_items is not None:
        request_input["max_items"] = args.max_items
    checkpoint = (
        json.loads(args.state_file.read_text())
        if args.state_file.exists()
        else {
            "service": args.service,
            "input": request_input,
            "key": secrets.token_urlsafe(32),
            "expected_pay_to": args.expected_pay_to.lower(),
            "private_acceptance": args.private_acceptance,
        }
    )
    if any(
        checkpoint.get(k) != v
        for k, v in {
            "service": args.service,
            "input": request_input,
            "expected_pay_to": args.expected_pay_to.lower(),
        }.items()
    ):
        parser.error("Checkpoint belongs to another request; do not overwrite it")
    if checkpoint.get("private_acceptance", False) != args.private_acceptance:
        parser.error("Checkpoint belongs to another acceptance lane; do not overwrite it")
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        payment = checked(client.get(BASE + "/status.json")).get("payment", {})
        if not (
            payment.get("enabled")
            and payment.get("network") == "eip155:8453"
            and payment.get("version") == 2
            and payment.get("chain_id") == 8453
            and str(payment.get("receiver", "")).lower() == args.expected_pay_to.lower()
            and str(payment.get("asset", {}).get("address", "")).lower() == ASSET
        ):
            parser.error("Live payment metadata does not match the expected Base-USDC receiver")
        discovery = "/v1/catalog" if args.private_acceptance else "/v1/services"
        services = checked(client.get(BASE + discovery)).get("services", [])
        if not acceptance_service(services, args.service, args.private_acceptance):
            parser.error("Service is not a five-cent synchronous service in the selected lane")
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        answer = {}

        class Callback(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # Never log authorization codes in callback URLs.

            def do_GET(self):
                query = parse_qs(urlsplit(self.path).query)
                valid = urlsplit(self.path).path == "/callback" and secrets.compare_digest(
                    query.get("state", [""])[0], state
                )
                if not valid:
                    self.send_response(400)
                    self.end_headers()
                    return
                answer.update(code=query.get("code", [""])[0], issuer=query.get("iss", [""])[0])
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(
                    b"Connection authorized. Return to your terminal for the payment link."
                )

        port = checkpoint.get("callback_port", 0)
        with HTTPServer(("127.0.0.1", port), Callback) as callback:
            callback.timeout = 1
            redirect = f"http://127.0.0.1:{callback.server_port}/callback"
            if "client_id" not in checkpoint:
                registered = checked(
                    client.post(
                        BASE + "/register",
                        json={
                            "client_name": "ReachSocial owner acceptance",
                            "redirect_uris": [redirect],
                            "token_endpoint_auth_method": "none",
                            "grant_types": ["authorization_code", "refresh_token"],
                            "scope": "reachsocial:requests",
                        },
                    )
                )
                checkpoint.update(
                    client_id=registered["client_id"], callback_port=callback.server_port
                )
                save(args.state_file, checkpoint)
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .decode()
                .rstrip("=")
            )
            authorize = (
                BASE
                + "/authorize?"
                + urlencode(
                    {
                        "client_id": checkpoint["client_id"],
                        "redirect_uri": redirect,
                        "response_type": "code",
                        "scope": "reachsocial:requests",
                        "resource": BASE + "/mcp/",
                        "state": state,
                        "code_challenge": challenge,
                        "code_challenge_method": "S256",
                    }
                )
            )
            print(
                "Open this on the computer running this script; sign the non-payment login and allow the connection:"
            )
            print(authorize, flush=True)
            webbrowser.open(authorize)
            deadline = time.monotonic() + 600
            while not answer and time.monotonic() < deadline:
                callback.handle_request()
            if not answer.get("code") or answer.get("issuer") != BASE:
                raise RuntimeError("Authorization did not complete; checkpoint preserved")
        token = checked(
            client.post(
                BASE + "/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": checkpoint["client_id"],
                    "code": answer["code"],
                    "redirect_uri": redirect,
                    "code_verifier": verifier,
                    "resource": BASE + "/mcp/",
                },
            )
        )["access_token"]
        headers = {
            "Authorization": "Bearer " + token,
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        }

        initialized = checked(
            client.post(
                BASE + "/mcp/",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "reachsocial-owner-acceptance", "version": "1.0"},
                    },
                },
            )
        )
        if "result" not in initialized:
            raise RuntimeError("MCP initialization failed; checkpoint preserved")

        def tool(name, arguments):
            result = checked(
                client.post(
                    BASE + "/mcp/",
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": secrets.randbelow(1000000),
                        "method": "tools/call",
                        "params": {"name": name, "arguments": arguments},
                    },
                )
            ).get("result", {})
            if result.get("isError") or not isinstance(result.get("structuredContent"), dict):
                raise RuntimeError(
                    "Tool failed; checkpoint preserved. Do not start another paid request."
                )
            return result["structuredContent"]

        if "request_id" not in checkpoint:
            result = tool(
                args.service.replace(".", "_"),
                {**request_input, "idempotency_key": checkpoint["key"]},
            )
            checkpoint["request_id"] = result["request_id"]
            save(args.state_file, checkpoint)
        result = tool("get_reachsocial_request", {"request_id": checkpoint["request_id"]})
        if result["status"] == "payment_required":
            if result.get("price_cents") != 5:
                raise RuntimeError("Unexpected price; no payment approval opened")
            if args.private_acceptance and result.get("payment_endpoint") != (
                f"/v1/acceptance/private/{args.service}/execute"
            ):
                raise RuntimeError("Unexpected private payment endpoint; no approval opened")
            print("Approve at most one $0.05 request in your browser, then return here:")
            print(result["payment_url"], flush=True)
            webbrowser.open(result["payment_url"])
        deadline = time.monotonic() + 600
        while (
            result["status"] in {"payment_required", "awaiting_approval", "reconciliation_required"}
            and time.monotonic() < deadline
        ):
            time.sleep(10)
            result = tool("get_reachsocial_request", {"request_id": checkpoint["request_id"]})
        if result["status"] != "succeeded" or result.get("payment_status") != "settled":
            print(
                json.dumps(
                    {
                        "status": result["status"],
                        "request_id": checkpoint["request_id"],
                        "checkpoint_retained": True,
                    }
                )
            )
            return
        recovered = tool("get_reachsocial_request", {"request_id": checkpoint["request_id"]})
        assert recovered.get("result") == result.get("result")
        checkpoint.update(
            status="passed", transaction=result.get("transaction"),
            result_hash=hashlib.sha256(
                json.dumps(result.get("result"), sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        )
        save(args.state_file, checkpoint)
        print(
            json.dumps(
                {
                    "service": args.service,
                    "status": "success",
                    "amount_atomic": 50000,
                    "transaction": result.get("transaction"),
                    "recovery": "passed",
                    "request_id": checkpoint["request_id"],
                }
            )
        )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, httpx.HTTPError) as exc:
        raise SystemExit(failure_message(exc)) from None
