#!/usr/bin/env python3
"""Verify control of an x402 receiving wallet with a local message signature."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from eth_account import Account
from eth_account.messages import encode_defunct


def custody_message(address: str, expires_at: datetime) -> str:
    issued_at = datetime.now(UTC).replace(microsecond=0)
    return "\n".join(
        (
            "ReachSocial merchant wallet custody verification",
            f"Address: {address}",
            f"Issued at: {issued_at.isoformat()}",
            f"Expires at: {expires_at.isoformat()}",
            f"Nonce: {secrets.token_urlsafe(24)}",
            "Purpose: prove control of the receiving wallet.",
            "This does not authorize a transfer, allowance, or transaction.",
        )
    )


def write_evidence(address: str, message: str) -> Path:
    verified_at = datetime.now(UTC).replace(microsecond=0)
    directory = Path.home() / ".local" / "state" / "reachsocial" / "merchant-wallet-custody"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = directory / f"{verified_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "kind": "reachsocial_merchant_wallet_custody",
                "address": address,
                "verified_at": verified_at.isoformat(),
                "challenge_sha256": hashlib.sha256(message.encode()).hexdigest(),
            },
            indent=2,
        )
        + "\n"
    )
    os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(temporary, destination)
    return destination


def console(address: str, port: int, expires_in_minutes: int) -> None:
    expires_at = datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=expires_in_minutes)
    message = custody_message(address, expires_at)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def send_json(self, status: int, payload: dict[str, object]) -> None:
            content = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/":
                self.send_error(404)
                return
            page = f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ReachSocial merchant custody check</title>
<style>body{{font:16px system-ui,sans-serif;max-width:720px;margin:3rem auto;padding:0 1rem;line-height:1.5}}code,pre{{overflow-wrap:anywhere}}button{{font:inherit;padding:.7rem 1rem}}#status{{font-weight:600}}</style>
<h1>Merchant wallet custody check</h1>
<p>Expected receiving address: <code>{address}</code></p>
<p>This signs a message only. It cannot transfer funds or set an allowance.</p>
<pre id="message"></pre><button id="sign">Connect and sign custody message</button>
<p id="status" role="status"></p>
<script>
const expected = {json.dumps(address.lower())};
const message = {json.dumps(message)};
document.querySelector('#message').textContent = message;
const status = document.querySelector('#status');
document.querySelector('#sign').addEventListener('click', async () => {{
  try {{
    if (!window.ethereum) throw new Error('No browser wallet was found. Open this page in the wallet browser/profile.');
    const accounts = await window.ethereum.request({{method: 'eth_requestAccounts'}});
    const walletAddress = accounts[0];
    if (!walletAddress || walletAddress.toLowerCase() !== expected) throw new Error('Selected wallet address does not match the configured receiving address.');
    status.textContent = 'Check the wallet prompt, then approve the message signature.';
    const signature = await window.ethereum.request({{method: 'personal_sign', params: [message, walletAddress]}});
    const response = await fetch('/verify', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{address: walletAddress, signature}})}});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Verification failed.');
    status.textContent = 'Verified. This page will close automatically.';
    document.querySelector('#sign').disabled = true;
  }} catch (error) {{ status.textContent = error.message || String(error); }}
}});
</script></html>""".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/verify":
                self.send_json(404, {"error": "not found"})
                return
            if datetime.now(UTC) >= expires_at:
                self.send_json(410, {"error": "challenge expired"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 10_000:
                self.send_json(400, {"error": "invalid request"})
                return
            try:
                request = json.loads(self.rfile.read(length))
                submitted_address = str(request["address"])
                signature = str(request["signature"])
                signer = Account.recover_message(encode_defunct(text=message), signature=signature)
            except Exception:
                self.send_json(400, {"error": "invalid signature"})
                return
            if submitted_address.lower() != address.lower() or signer.lower() != address.lower():
                self.send_json(403, {"error": "signature does not match the configured receiving address"})
                return
            evidence = write_evidence(address, message)
            self.send_json(200, {"verified": True, "evidence": str(evidence)})
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    expiration = threading.Timer(expires_in_minutes * 60, server.shutdown)
    expiration.daemon = True
    expiration.start()
    print(f"Open http://127.0.0.1:{port}/ in the local wallet browser/profile.")
    print(f"The challenge expires at {expires_at.isoformat()}.")
    server.serve_forever()
    server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-address", required=True)
    parser.add_argument("--port", type=int, default=38473)
    parser.add_argument("--expires-in-minutes", type=int, default=10)
    args = parser.parse_args()
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", args.expected_address):
        parser.error("--expected-address must be an EVM address")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if not 1 <= args.expires_in_minutes <= 60:
        parser.error("--expires-in-minutes must be between 1 and 60")
    console(args.expected_address, args.port, args.expires_in_minutes)


if __name__ == "__main__":
    main()
