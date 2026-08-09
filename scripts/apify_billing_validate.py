"""Run the two explicitly approved, capped Apify production samples."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from reachsocial.catalog import ProviderConfig, ServiceDefinition, load_catalog
from reachsocial.config import get_settings
from reachsocial.errors import ProviderAccessDenied, ReachSocialError
from reachsocial.providers import ApifyAdapter
from reachsocial.services import ExecutionService


@dataclass(frozen=True)
class ValidationCase:
    service_id: str
    url: str
    max_items: int
    actor_id: str
    charge_cap_microusd: int


CASES = (
    ValidationCase(
        service_id="x.feed",
        url="https://x.com/NASA",
        max_items=5,
        actor_id="apidojo~tweet-scraper",
        charge_cap_microusd=10_000,
    ),
    ValidationCase(
        service_id="linkedin.profile",
        url="https://www.linkedin.com/in/satyanadella/",
        max_items=1,
        actor_id="automation-lab~linkedin-profile-scraper",
        charge_cap_microusd=50_000,
    ),
)


def _service_for(case: ValidationCase) -> ServiceDefinition:
    service = load_catalog().by_id(case.service_id)
    if service is None:
        raise RuntimeError(f"Missing validation service: {case.service_id}")
    return service.model_copy(
        update={
            "provider": ProviderConfig(
                name="apify",
                actor_id=case.actor_id,
                max_total_charge_microusd=case.charge_cap_microusd,
            ),
            "retries": 0,
        }
    )


def _input_for(case: ValidationCase, service: ServiceDefinition) -> dict[str, Any]:
    value: dict[str, Any] = {"url": case.url}
    if any(field.name == "max_items" for field in service.input_fields):
        value["max_items"] = case.max_items
    ExecutionService.validate_input(service, value)
    return value


def _contract_error(service_id: str, data: dict[str, Any], max_items: int) -> str | None:
    forbidden = {"provider", "credits_charged", "actor_id", "api_token", "raw_payload"}
    stack: list[Any] = [data]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if forbidden.intersection(value):
                return "provider_contract_failed"
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    if service_id == "x.feed":
        items = data.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= max_items:
            return "provider_contract_failed"
        for item in items:
            if not isinstance(item, dict):
                return "provider_contract_failed"
            if item.get("platform") != "X" or not item.get("platform_id"):
                return "provider_contract_failed"
            author = item.get("author")
            if not isinstance(author, dict) or not author.get("handle"):
                return "provider_contract_failed"
            if not item.get("canonical_url") or not (item.get("text") or item.get("media")):
                return "provider_contract_failed"
        return None
    profile = data.get("profile")
    if not isinstance(profile, dict):
        return "provider_contract_failed"
    fields = profile.get("fields")
    experience = fields.get("experience") if isinstance(fields, dict) else None
    if not profile.get("display_name") or not profile.get("canonical_url"):
        return "provider_contract_failed"
    if not isinstance(experience, list) or not experience:
        return "provider_contract_failed"
    if not any(row.get("title") and row.get("organization") for row in experience):
        return "provider_contract_failed"
    return None


def _usd(microusd: int) -> str:
    return format(Decimal(microusd) / Decimal(1_000_000), "f")


def _report(
    *,
    service: str,
    status: str,
    error_type: str,
    run_reference: str,
    item_count: int,
    shape: str,
    actual_microusd: int,
) -> None:
    print(f"service={service}")
    print(f"terminal_status={status}")
    print(f"sanitized_error_type={error_type}")
    print(f"run_reference={run_reference}")
    print(f"item_count={item_count}")
    print(f"normalized_shape={shape}")
    print(f"actual_usd={_usd(actual_microusd)}")


async def validate() -> int:
    settings = get_settings()
    if not settings.is_production:
        raise SystemExit("This paid validation command runs only in production")
    adapter = ApifyAdapter(settings.apify_api_token)
    exit_code = 0
    for case in CASES:
        service = _service_for(case)
        input_data = _input_for(case, service)
        try:
            result = await adapter.execute(service, input_data)
        except ReachSocialError as error:
            _report(
                service=case.service_id,
                status="FAILED",
                error_type=(
                    "provider_access_denied"
                    if isinstance(error, ProviderAccessDenied)
                    else error.code
                ),
                run_reference=str(getattr(error, "provider_reference", None) or "unavailable"),
                item_count=0,
                shape="none",
                actual_microusd=int(getattr(error, "upstream_cost_microusd", 0) or 0),
            )
            return 1
        error_type = _contract_error(case.service_id, result.data, case.max_items)
        _report(
            service=case.service_id,
            status="SUCCEEDED",
            error_type=error_type or "none",
            run_reference=result.provider_reference or "unavailable",
            item_count=len(result.data.get("items", [])) or int(bool(result.data.get("profile"))),
            shape=",".join(sorted(result.data)),
            actual_microusd=result.upstream_cost_microusd,
        )
        if error_type:
            exit_code = 1
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the approved Apify billing tests with a total new exposure of $0.06."
    )
    parser.add_argument("--confirm-paid-provider-call", action="store_true")
    args = parser.parse_args()
    if not args.confirm_paid_provider_call:
        raise SystemExit("Re-run with --confirm-paid-provider-call to acknowledge provider cost")
    raise SystemExit(asyncio.run(validate()))


if __name__ == "__main__":
    main()
