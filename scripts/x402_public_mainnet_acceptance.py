#!/usr/bin/env python3
"""Verify or accept bounded Base-mainnet x402 payments through normal public routes.

The default dry run only validates the live x402 challenge. Paid mode reads the
buyer recovery phrase from hidden terminal input, sends one payment per target,
then verifies result recovery with the same idempotency key. It never writes a
recovery phrase or raw payment signature to disk.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import secrets
from dataclasses import dataclass
from typing import Any

import httpx

from reachsocial.buyer_wallet import recover_buyer_account
from reachsocial.catalog import ServiceDefinition, load_catalog
from reachsocial.services import ExecutionService
from reachsocial.x402_smoke import BASE_MAINNET_NETWORK

USDC_BASE_MAINNET = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"


@dataclass(frozen=True)
class AcceptanceTarget:
    service_id: str
    value: str


def parse_target(value: str) -> AcceptanceTarget:
    service_id, separator, target = value.partition("=")
    if not separator or not service_id or not target:
        raise argparse.ArgumentTypeError("targets must use service_id=URL-or-name")
    return AcceptanceTarget(service_id=service_id, value=target)


def input_for(service: ServiceDefinition, target: AcceptanceTarget) -> dict[str, Any]:
    input_data: dict[str, Any]
    if service.id == "news.person":
        input_data = {"full_name": target.value, "max_items": 5}
    else:
        input_data = {"url": target.value}
        if any(field.name == "max_items" for field in service.input_fields):
            input_data["max_items"] = 5
    ExecutionService.validate_input(service, input_data)
    return input_data


def endpoint_for(service: ServiceDefinition, base_url: str) -> str:
    route = "jobs" if service.is_async else "execute"
    return f"{base_url.rstrip('/')}/v1/services/{service.id}/{route}"


def amount_atomic(service: ServiceDefinition) -> int:
    return service.price_cents * 10_000


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
            "payment challenge did not contain one exact native Base-USDC requirement"
        )
    return matches[0]


def idempotency_key(service_id: str) -> str:
    return f"mainnet-release-{service_id}-{secrets.token_urlsafe(24)}"


async def quote(
    http: httpx.AsyncClient,
    *,
    endpoint: str,
    service: ServiceDefinition,
    body: dict[str, Any],
    key: str,
    expected_pay_to: str,
) -> Any:
    from x402 import x402Client
    from x402.http import x402HTTPClient

    response = await http.post(
        endpoint,
        headers={"Accept": "application/json", "Idempotency-Key": key},
        json=body,
    )
    if response.status_code != 402:
        raise RuntimeError(f"{service.id} expected an unpaid 402 challenge, received HTTP {response.status_code}")
    payment_required = x402HTTPClient(x402Client()).get_payment_required_response(
        response.headers.get, response.json() if response.content else None
    )
    if payment_required.x402_version != 2:
        raise ValueError(f"{service.id} requires x402 v2")
    requirement = select_requirement(
        payment_required,
        expected_pay_to=expected_pay_to,
        amount=amount_atomic(service),
    )
    return payment_required.model_copy(update={"accepts": [requirement]})


async def pay_and_recover(
    http: httpx.AsyncClient,
    *,
    signer: Any,
    endpoint: str,
    service: ServiceDefinition,
    body: dict[str, Any],
    key: str,
    payment_required: Any,
    base_url: str,
) -> dict[str, Any]:
    from x402 import x402Client
    from x402.http import x402HTTPClient
    from x402.mechanisms.evm.exact import ExactEvmScheme

    payment_client = x402Client()
    payment_client.register(BASE_MAINNET_NETWORK, ExactEvmScheme(signer=signer))
    payment = await payment_client.create_payment_payload(payment_required)
    payment_http = x402HTTPClient(payment_client)
    try:
        response = await http.post(
            endpoint,
            headers={
                "Accept": "application/json",
                "Idempotency-Key": key,
                **payment_http.encode_payment_signature_header(payment),
            },
            json=body,
        )
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"{service.id} paid request has an unknown outcome; retain its local idempotency key: {key}"
        ) from exc
    expected_status = 202 if service.is_async else 200
    if response.status_code != expected_status:
        raise RuntimeError(
            f"{service.id} paid request returned HTTP {response.status_code}; "
            f"retain its local idempotency key: {key}"
        )
    settlement = payment_http.get_payment_settle_response(response.headers.get)
    if not settlement.success or settlement.network != BASE_MAINNET_NETWORK:
        raise RuntimeError(
            f"{service.id} settlement has an unknown outcome; retain its local idempotency key: {key}"
        )
    recovery = await http.post(
        f"{base_url.rstrip('/')}/v1/payments/recover/{service.id}",
        headers={"Accept": "application/json", "Idempotency-Key": key},
        json=body,
    )
    if recovery.status_code != 200:
        raise RuntimeError(f"{service.id} paid-result recovery failed with HTTP {recovery.status_code}")
    result: dict[str, Any] = {
        "amount_atomic": amount_atomic(service),
        "network": settlement.network,
        "recovery": "passed",
        "service": service.id,
        "settled": True,
        "transaction": str(settlement.transaction),
    }
    if service.is_async:
        paid_body = response.json() if response.content else {}
        result["job_status"] = await poll_job(http, paid_body)
    return result


async def poll_job(http: httpx.AsyncClient, response: dict[str, Any]) -> str:
    status_url = str(response.get("status_url") or "")
    job_token = str(response.get("job_token") or "")
    if not status_url or not job_token:
        raise RuntimeError("async acceptance did not return protected polling details")
    deadline = asyncio.get_running_loop().time() + 180
    while asyncio.get_running_loop().time() < deadline:
        polled = await http.get(status_url, headers={"X-Job-Token": job_token})
        if polled.status_code != 200:
            raise RuntimeError(f"protected job poll failed with HTTP {polled.status_code}")
        status = str(polled.json().get("status") or "")
        if status == "succeeded":
            return status
        if status in {"failed", "expired", "reconciliation_required"}:
            raise RuntimeError(f"async acceptance job ended as {status}")
        await asyncio.sleep(2)
    raise RuntimeError("async acceptance polling timed out")


async def run(args: argparse.Namespace) -> list[dict[str, Any]]:
    targets = args.target
    if len({target.service_id for target in targets}) != len(targets):
        raise ValueError("each service may have one target")
    catalog = load_catalog()
    planned: list[tuple[ServiceDefinition, dict[str, Any], str]] = []
    for target in targets:
        service = catalog.by_id(target.service_id)
        if service is None or not (service.enabled and service.public):
            raise ValueError(f"{target.service_id} is not an available public service")
        planned.append((service, {"input": input_for(service, target)}, idempotency_key(service.id)))
    total = sum(amount_atomic(service) for service, _body, _key in planned)
    if total > args.max_total_atomic:
        raise ValueError("planned payments exceed --max-total-atomic")

    timeout = httpx.Timeout(120.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as http:
        quotes = [
            await quote(
                http,
                endpoint=endpoint_for(service, args.base_url),
                service=service,
                body=body,
                key=key,
                expected_pay_to=args.expected_pay_to,
            )
            for service, body, key in planned
        ]
        if args.dry_run:
            return [
                {
                    "amount_atomic": amount_atomic(service),
                    "network": BASE_MAINNET_NETWORK,
                    "service": service.id,
                    "status": "challenge_verified",
                }
                for service, _body, _key in planned
            ]

        mnemonic = getpass.getpass("Paste the buyer recovery phrase (input is hidden): ")
        signer = recover_buyer_account(mnemonic)
        if signer.address.lower() != args.expected_buyer.lower():
            raise ValueError("recovery phrase does not produce the approved buyer address")
        return [
            await pay_and_recover(
                http,
                signer=signer,
                endpoint=endpoint_for(service, args.base_url),
                service=service,
                body=body,
                key=key,
                payment_required=payment_required,
                base_url=args.base_url,
            )
            for (service, body, key), payment_required in zip(planned, quotes, strict=True)
        ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://reachsocial.dev")
    parser.add_argument("--expected-pay-to", required=True)
    parser.add_argument("--expected-buyer")
    parser.add_argument("--target", action="append", type=parse_target, required=True)
    parser.add_argument("--max-total-atomic", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm-mainnet-payments", action="store_true")
    args = parser.parse_args()
    if args.max_total_atomic < 1:
        parser.error("--max-total-atomic must be positive")
    if not args.dry_run and not args.confirm_mainnet_payments:
        parser.error("--confirm-mainnet-payments is required to send real USDC")
    if not args.dry_run and not args.expected_buyer:
        parser.error("--expected-buyer is required to send real USDC")
    try:
        print(json.dumps(asyncio.run(run(args)), indent=2, sort_keys=True))
    except (ValueError, RuntimeError, httpx.HTTPError) as error:
        parser.error(str(error))
    except Exception as error:
        parser.error(f"{type(error).__name__}: public mainnet acceptance did not complete")


if __name__ == "__main__":
    main()
