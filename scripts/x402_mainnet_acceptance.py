#!/usr/bin/env python3
"""Run the three one-time Base-mainnet acceptance payments from a local buyer wallet."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import secrets
from typing import Any

import httpx

from reachsocial.buyer_wallet import recover_buyer_account
from reachsocial.x402_smoke import BASE_MAINNET_NETWORK

USDC_BASE_MAINNET = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
ACCEPTANCE_PATHS = {
    "instagram.profile": "/v1/acceptance/mainnet/instagram.profile/execute",
    "instagram.post": "/v1/acceptance/mainnet/instagram.post/execute",
    "linkedin.profile": "/v1/acceptance/mainnet/linkedin.profile/jobs",
}


def select_requirement(payment_required: Any, *, expected_pay_to: str, amount: int) -> Any:
    matches = [
        item
        for item in payment_required.accepts
        if item.network == BASE_MAINNET_NETWORK
        and item.asset.lower() == USDC_BASE_MAINNET.lower()
        and item.pay_to.lower() == expected_pay_to.lower()
        and str(item.amount) == str(amount)
    ]
    if len(matches) != 1:
        raise ValueError(
            "payment challenge did not contain one exact Base-mainnet USDC requirement"
        )
    return matches[0]


async def paid_request(
    http: httpx.AsyncClient,
    *,
    signer: Any,
    base_url: str,
    service_id: str,
    body: dict[str, Any],
    expected_pay_to: str,
    amount: int,
    expected_status: int,
) -> tuple[dict[str, Any], str, str]:
    from x402 import x402Client
    from x402.http import x402HTTPClient
    from x402.mechanisms.evm.exact import ExactEvmScheme

    endpoint = f"{base_url.rstrip('/')}{ACCEPTANCE_PATHS[service_id]}"
    idempotency_key = f"mainnet-acceptance-{service_id}-{secrets.token_hex(16)}"
    headers = {"Accept": "application/json", "Idempotency-Key": idempotency_key}
    challenge = await http.post(endpoint, headers=headers, json=body)
    if challenge.status_code != 402:
        raise RuntimeError(
            f"{service_id} expected an unpaid 402 challenge, received HTTP {challenge.status_code}"
        )
    parser = x402HTTPClient(x402Client())
    payment_required = parser.get_payment_required_response(
        challenge.headers.get, challenge.json() if challenge.content else None
    )
    if payment_required.x402_version != 2:
        raise ValueError(f"{service_id} requires x402 v2")
    requirement = select_requirement(
        payment_required, expected_pay_to=expected_pay_to, amount=amount
    )
    payment_client = x402Client()
    payment_client.register(BASE_MAINNET_NETWORK, ExactEvmScheme(signer=signer))
    payment = await payment_client.create_payment_payload(
        payment_required.model_copy(update={"accepts": [requirement]})
    )
    payment_http = x402HTTPClient(payment_client)
    paid = await http.post(
        endpoint,
        headers={**headers, **payment_http.encode_payment_signature_header(payment)},
        json=body,
    )
    paid_body = paid.json() if paid.content else {}
    if paid.status_code != expected_status:
        raise RuntimeError(f"{service_id} paid retry failed with HTTP {paid.status_code}")
    settlement = payment_http.get_payment_settle_response(paid.headers.get)
    if not settlement.success or settlement.network != BASE_MAINNET_NETWORK:
        raise RuntimeError(f"{service_id} did not receive a successful Base-mainnet settlement")

    recovery = await http.post(
        f"{base_url.rstrip('/')}/v1/payments/recover/{service_id}",
        headers={"Idempotency-Key": idempotency_key},
        json=body,
    )
    if recovery.status_code != 200:
        raise RuntimeError(
            f"{service_id} paid-result recovery failed with HTTP {recovery.status_code}"
        )
    return paid_body, idempotency_key, str(settlement.transaction)


async def poll_linkedin(
    http: httpx.AsyncClient, *, response: dict[str, Any], timeout_seconds: int
) -> str:
    status_url = str(response.get("status_url") or "")
    job_token = str(response.get("job_token") or "")
    if not status_url or not job_token:
        raise RuntimeError("LinkedIn acceptance did not return protected polling details")
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        polled = await http.get(status_url, headers={"X-Job-Token": job_token})
        if polled.status_code != 200:
            raise RuntimeError(f"LinkedIn protected poll failed with HTTP {polled.status_code}")
        status = str(polled.json().get("status") or "")
        if status == "succeeded":
            return status
        if status in {"failed", "expired"}:
            raise RuntimeError(f"LinkedIn acceptance job ended as {status}")
        await asyncio.sleep(2)
    raise RuntimeError("LinkedIn acceptance polling timed out without another paid request")


async def run(args: argparse.Namespace) -> list[dict[str, Any]]:
    mnemonic = getpass.getpass("Paste the independent buyer recovery phrase (input is hidden): ")
    if not mnemonic.strip():
        raise ValueError("a recovery phrase is required")
    signer = recover_buyer_account(mnemonic)
    if signer.address.lower() != args.expected_buyer.lower():
        raise ValueError("recovery phrase does not produce the approved independent buyer address")

    requests = (
        ("instagram.profile", {"input": {"url": args.instagram_profile_url}}, 50_000, 200),
        ("instagram.post", {"input": {"url": args.instagram_post_url}}, 50_000, 200),
        ("linkedin.profile", {"input": {"url": args.linkedin_profile_url}}, 100_000, 202),
    )
    results = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0), follow_redirects=False) as http:
        for service_id, body, amount, expected_status in requests:
            response, _key, transaction = await paid_request(
                http,
                signer=signer,
                base_url=args.base_url,
                service_id=service_id,
                body=body,
                expected_pay_to=args.expected_pay_to,
                amount=amount,
                expected_status=expected_status,
            )
            result = {
                "service": service_id,
                "amount_atomic": amount,
                "network": BASE_MAINNET_NETWORK,
                "settled": True,
                "transaction": transaction,
                "recovery": "passed",
            }
            if service_id == "linkedin.profile":
                result["job_status"] = await poll_linkedin(
                    http, response=response, timeout_seconds=args.linkedin_timeout_seconds
                )
            else:
                result["status"] = response.get("status")
            results.append(result)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://reachsocial.dev")
    parser.add_argument("--expected-buyer", required=True)
    parser.add_argument("--expected-pay-to", required=True)
    parser.add_argument("--instagram-profile-url", default="https://www.instagram.com/instagram/")
    parser.add_argument("--instagram-post-url", required=True)
    parser.add_argument(
        "--linkedin-profile-url", default="https://www.linkedin.com/in/satyanadella/"
    )
    parser.add_argument("--linkedin-timeout-seconds", type=int, default=180)
    parser.add_argument("--confirm-mainnet-acceptance", action="store_true")
    args = parser.parse_args()
    if not args.confirm_mainnet_acceptance:
        parser.error("--confirm-mainnet-acceptance is required; this sends $0.20 of real USDC")
    try:
        results = asyncio.run(run(args))
    except (ValueError, RuntimeError, httpx.HTTPError) as error:
        parser.error(str(error))
    except Exception as error:
        parser.error(f"{type(error).__name__}: mainnet acceptance did not complete")
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
