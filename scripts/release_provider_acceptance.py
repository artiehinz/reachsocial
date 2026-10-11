#!/usr/bin/env python3
"""Run one bounded, recorded provider-contract stage without retaining source URLs.

This is a release tool, not a public endpoint. It makes at most one provider
request per selected service, stops before the configured cumulative credit
budget, and stores only sanitized accounting evidence in its local ledger.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reachsocial.catalog import ServiceDefinition, load_catalog
from reachsocial.errors import ReachSocialError
from reachsocial.providers import adapter_for
from reachsocial.services import ExecutionService

STAGES: dict[int, tuple[str, ...]] = {
    1: ("linkedin.profile",),
    2: ("x.profile", "x.post", "tiktok.profile", "tiktok.video", "news.person"),
    3: (
        "instagram.feed",
        "x.feed",
        "tiktok.feed",
        "youtube.channel",
        "youtube.video",
        "youtube.feed",
    ),
    4: ("facebook.profile", "reddit.post", "instagram.highlight"),
}


def stable_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _read_ledger(path: Path, credit_budget: int) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "credit_budget": credit_budget, "events": []}
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("acceptance ledger is unreadable") from exc
    if not isinstance(ledger, dict) or ledger.get("schema_version") != 1:
        raise ValueError("acceptance ledger has an unsupported schema")
    if ledger.get("credit_budget") != credit_budget:
        raise ValueError("credit budget does not match the existing acceptance ledger")
    if not isinstance(ledger.get("events"), list):
        raise ValueError("acceptance ledger events are invalid")
    return ledger


def _credited_units(ledger: dict[str, Any]) -> int:
    return sum(
        max(0, int(event.get("provider_units") or 0))
        for event in ledger["events"]
        if isinstance(event, dict) and event.get("provider") == "scrapecreators"
    )


def _already_passed(ledger: dict[str, Any], service_id: str) -> bool:
    return any(
        isinstance(event, dict)
        and event.get("service") == service_id
        and event.get("outcome") == "passed"
        for event in ledger["events"]
    )


def _write_ledger(path: Path, ledger: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def _input_for(service: ServiceDefinition, target: str, *, max_items: int) -> dict[str, Any]:
    if service.id == "news.person":
        input_data: dict[str, Any] = {"full_name": target}
    else:
        input_data = {"url": target}
    if any(field.name == "max_items" for field in service.input_fields):
        input_data["max_items"] = max_items
    ExecutionService.validate_input(service, input_data)
    return input_data


def _event(
    *,
    stage: int,
    service: ServiceDefinition,
    input_data: dict[str, Any],
    outcome: str,
    provider_units: int,
    upstream_cost_microusd: int,
    provider_reference: str | None,
    error_code: str | None = None,
) -> dict[str, Any]:
    return {
        "at": datetime.now(UTC).isoformat(),
        "error_code": error_code,
        "input_hash": stable_hash(input_data),
        "outcome": outcome,
        "provider": service.provider.name,
        "provider_reference_hash": stable_hash(provider_reference) if provider_reference else None,
        "provider_units": max(0, provider_units),
        "response_shape": service.response_shape,
        "service": service.id,
        "stage": stage,
        "upstream_cost_microusd": max(0, upstream_cost_microusd),
    }


async def run(args: argparse.Namespace) -> list[dict[str, Any]]:
    expected = STAGES[args.stage]
    targets = dict(args.target)
    if set(targets) != set(expected):
        missing = sorted(set(expected) - set(targets))
        unexpected = sorted(set(targets) - set(expected))
        details = []
        if missing:
            details.append(f"missing targets for {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected targets for {', '.join(unexpected)}")
        raise ValueError("; ".join(details))

    ledger = _read_ledger(args.ledger, args.credit_budget)
    catalog = load_catalog()
    new_events: list[dict[str, Any]] = []
    for service_id in expected:
        if _already_passed(ledger, service_id):
            continue
        service = catalog.by_id(service_id)
        if service is None:
            raise ValueError(f"catalog does not contain {service_id}")
        input_data = _input_for(service, targets[service_id], max_items=args.max_items)
        reserved_units = service.max_provider_units_per_attempt
        if (
            _credited_units(ledger) + _credited_units({"events": new_events}) + reserved_units
            > args.credit_budget
        ):
            raise ValueError("the provider-credit acceptance budget would be exceeded")
        try:
            result = await adapter_for(service).execute(service, input_data)
        except ReachSocialError as error:
            event = _event(
                stage=args.stage,
                service=service,
                input_data=input_data,
                outcome="failed",
                provider_units=int(getattr(error, "provider_units", reserved_units)),
                upstream_cost_microusd=int(
                    getattr(
                        error,
                        "upstream_cost_microusd",
                        reserved_units * service.provider_unit_cost_microusd,
                    )
                ),
                provider_reference=getattr(error, "provider_reference", None),
                error_code=error.code,
            )
            ledger["events"].append(event)
            _write_ledger(args.ledger, ledger)
            raise RuntimeError(f"{service_id} provider contract failed: {error.code}") from error
        event = _event(
            stage=args.stage,
            service=service,
            input_data=input_data,
            outcome="passed",
            provider_units=result.provider_units,
            upstream_cost_microusd=result.upstream_cost_microusd,
            provider_reference=result.provider_reference,
        )
        ledger["events"].append(event)
        new_events.append(event)
        _write_ledger(args.ledger, ledger)
    return new_events


def parse_target(value: str) -> tuple[str, str]:
    service_id, separator, target = value.partition("=")
    if not separator or not service_id or not target:
        raise argparse.ArgumentTypeError("targets must use service_id=value")
    return service_id, target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=int, choices=sorted(STAGES), required=True)
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        type=parse_target,
        help="One source URL per social service, or the full name for news.person.",
    )
    parser.add_argument("--max-items", type=int, default=5, choices=range(1, 51))
    parser.add_argument("--credit-budget", type=int, default=100, choices=range(1, 101))
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path("data/release-provider-acceptance-ledger.json"),
    )
    parser.add_argument("--confirm-paid-provider-calls", action="store_true")
    args = parser.parse_args()
    if not args.confirm_paid_provider_calls:
        parser.error("--confirm-paid-provider-calls is required; this can spend provider credits")
    if len({service_id for service_id, _target in args.target}) != len(args.target):
        parser.error("each service may have one target")
    try:
        events = asyncio.run(run(args))
    except (RuntimeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(events, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
