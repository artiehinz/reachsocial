#!/usr/bin/env python3
"""Make exactly one intentional five-cent Base-mainnet ReachSocial payment.

The recovery phrase is read from hidden terminal input. It is never written to
disk, sent to CDP, or printed. This script makes one paid retry only after it
validates the challenge's exact network, receiver, and amount.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import secrets
from typing import Any

import httpx

from reachsocial.buyer_wallet import recover_buyer_account
from reachsocial.payments import MAINNET_CANARY_PATH
from reachsocial.x402_smoke import BASE_MAINNET_NETWORK, select_mainnet_canary_requirement


async def run(args: argparse.Namespace) -> dict[str, Any]:
    from x402 import x402Client
    from x402.http import x402HTTPClient
    from x402.mechanisms.evm.exact import ExactEvmScheme

    mnemonic = getpass.getpass("Paste the buyer recovery phrase (input is hidden): ")
    if not mnemonic.strip():
        raise ValueError("a recovery phrase is required")
    signer = recover_buyer_account(mnemonic)
    if signer.address.lower() != args.expected_buyer.lower():
        raise ValueError("recovery phrase does not produce the approved buyer address")

    endpoint = f"{args.base_url.rstrip('/')}{MAINNET_CANARY_PATH}"
    body = {"input": {"url": args.profile_url}}
    headers = {
        "Accept": "application/json",
        "Idempotency-Key": "mainnet-canary-" + secrets.token_hex(12),
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0), follow_redirects=False) as http:
        challenge = await http.post(endpoint, headers=headers, json=body)
        if challenge.status_code != 402:
            raise RuntimeError(f"expected unpaid 402 challenge, received HTTP {challenge.status_code}")
        parser = x402HTTPClient(x402Client())
        payment_required = parser.get_payment_required_response(
            challenge.headers.get,
            challenge.json() if challenge.content else None,
        )
        if payment_required.x402_version != 2:
            raise ValueError("only x402 v2 is approved for this canary")
        requirement = select_mainnet_canary_requirement(
            payment_required, expected_pay_to=args.expected_pay_to
        )
        exact_challenge = payment_required.model_copy(update={"accepts": [requirement]})
        payment_client = x402Client()
        payment_client.register(BASE_MAINNET_NETWORK, ExactEvmScheme(signer=signer))
        payload = await payment_client.create_payment_payload(exact_challenge)
        payment_http = x402HTTPClient(payment_client)
        paid = await http.post(
            endpoint,
            headers={**headers, **payment_http.encode_payment_signature_header(payload)},
            json=body,
        )
        paid_body = paid.json() if paid.content else {}
        if paid.status_code != 200:
            raise RuntimeError(f"paid retry failed with HTTP {paid.status_code}")
        settlement = payment_http.get_payment_settle_response(paid.headers.get)
        if not settlement.success or settlement.network != BASE_MAINNET_NETWORK:
            raise RuntimeError("facilitator did not report a successful Base mainnet settlement")

    meta = paid_body.get("meta") if isinstance(paid_body, dict) else {}
    return {
        "service": paid_body.get("service"),
        "status": paid_body.get("status"),
        "request_id": paid_body.get("request_id"),
        "schema_version": meta.get("schema_version") if isinstance(meta, dict) else None,
        "buyer_address": signer.address,
        "pay_to": requirement.pay_to,
        "amount_atomic": int(requirement.amount),
        "network": settlement.network,
        "transaction": settlement.transaction,
        "settled": settlement.success,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://reachsocial.dev")
    parser.add_argument("--profile-url", required=True)
    parser.add_argument("--expected-buyer", required=True)
    parser.add_argument("--expected-pay-to", required=True)
    parser.add_argument("--confirm-mainnet-canary", action="store_true")
    args = parser.parse_args()
    if not args.confirm_mainnet_canary:
        parser.error("--confirm-mainnet-canary is required; this sends five cents of real USDC")
    try:
        result = asyncio.run(run(args))
    except (ValueError, RuntimeError, httpx.HTTPError) as error:
        parser.error(str(error))
    except Exception as error:
        parser.error(f"{type(error).__name__}: canary did not complete")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
