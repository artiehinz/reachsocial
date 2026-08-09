#!/usr/bin/env python3
"""Perform exactly one guarded Base Sepolia x402 API purchase.

Secrets are read only from the process environment. The command first obtains
and validates the unpaid challenge, then signs that exact requirement and sends
one paid retry. It never performs automatic recovery or another paid attempt.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
from typing import Any

import httpx

from reachsocial.x402_smoke import BASE_SEPOLIA_NETWORK, select_smoke_requirement

DEFAULT_ACCOUNT = "reachsocial-sepolia-buyer-test"


def require_secret_environment() -> None:
    missing = [
        name
        for name in ("CDP_API_KEY_ID", "CDP_API_KEY_SECRET", "CDP_WALLET_SECRET")
        if not os.getenv(name)
    ]
    if missing:
        raise ValueError("missing protected environment values: " + ", ".join(missing))


async def run(args: argparse.Namespace) -> dict[str, Any]:
    from cdp import CdpClient, EvmLocalAccount
    from x402 import x402Client
    from x402.http import x402HTTPClient
    from x402.mechanisms.evm.exact import ExactEvmScheme

    endpoint = f"{args.base_url.rstrip('/')}/v1/services/instagram.profile/execute"
    body = {"input": {"url": args.profile_url}}
    headers = {
        "Accept": "application/json",
        "Idempotency-Key": "sepolia-smoke-" + secrets.token_hex(12),
    }
    timeout = httpx.Timeout(45.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as http:
        challenge = await http.post(endpoint, headers=headers, json=body)
        if challenge.status_code != 402:
            raise RuntimeError(
                f"expected unpaid 402 challenge, received HTTP {challenge.status_code}"
            )

        parser = x402HTTPClient(x402Client())
        payment_required = parser.get_payment_required_response(
            challenge.headers.get,
            challenge.json() if challenge.content else None,
        )
        if payment_required.x402_version != 2:
            raise ValueError("only x402 v2 is approved for this smoke test")
        requirement = select_smoke_requirement(
            payment_required,
            expected_pay_to=args.expected_pay_to,
        )
        exact_challenge = payment_required.model_copy(update={"accepts": [requirement]})

        async with CdpClient() as cdp:
            server_account = await cdp.evm.get_account(name=args.account_name)
            signer = EvmLocalAccount(server_account)
            buyer_address = signer.address
            payment_client = x402Client()
            payment_client.register(BASE_SEPOLIA_NETWORK, ExactEvmScheme(signer=signer))
            payload = await payment_client.create_payment_payload(exact_challenge)
            payment_http = x402HTTPClient(payment_client)
            paid_headers = {**headers, **payment_http.encode_payment_signature_header(payload)}
            paid = await http.post(endpoint, headers=paid_headers, json=body)
            paid_body = paid.json() if paid.content else {}
            if paid.status_code != 200:
                code = None
                if isinstance(paid_body, dict):
                    error = paid_body.get("error") or paid_body.get("detail")
                    if isinstance(error, dict):
                        code = error.get("code")
                raise RuntimeError(
                    f"paid retry failed with HTTP {paid.status_code} ({code or 'unknown_error'})"
                )
            settlement = payment_http.get_payment_settle_response(paid.headers.get)
            if not settlement.success or settlement.network != BASE_SEPOLIA_NETWORK:
                raise RuntimeError(
                    "facilitator did not report a successful Base Sepolia settlement"
                )

    meta = paid_body.get("meta") if isinstance(paid_body, dict) else {}
    return {
        "service": paid_body.get("service"),
        "status": paid_body.get("status"),
        "request_id": paid_body.get("request_id"),
        "schema_version": meta.get("schema_version") if isinstance(meta, dict) else None,
        "buyer_address": buyer_address,
        "pay_to": requirement.pay_to,
        "amount_atomic": int(requirement.amount),
        "network": settlement.network,
        "transaction": settlement.transaction,
        "settled": settlement.success,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://reachsocial.dev")
    parser.add_argument("--account-name", default=DEFAULT_ACCOUNT)
    parser.add_argument("--profile-url", required=True)
    parser.add_argument("--expected-pay-to", required=True)
    parser.add_argument("--confirm-testnet-payment", action="store_true")
    args = parser.parse_args()
    if not args.confirm_testnet_payment:
        parser.error("--confirm-testnet-payment is required; this spends Base Sepolia test USDC")
    try:
        require_secret_environment()
        result = asyncio.run(run(args))
    except (ValueError, RuntimeError, httpx.HTTPError) as error:
        parser.error(str(error))
    except Exception as error:  # Provider SDK errors must not print protected context.
        parser.error(f"{type(error).__name__}: test did not complete")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
