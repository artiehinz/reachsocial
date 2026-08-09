"""Run one explicit paid provider contract sample without printing provider payloads."""

from __future__ import annotations

import argparse
import asyncio

from reachsocial.catalog import load_catalog
from reachsocial.providers import adapter_for
from reachsocial.services import ExecutionService


async def run(args: argparse.Namespace) -> None:
    catalog = load_catalog()
    service = catalog.by_id(args.service_id)
    if service is None or not service.enabled:
        raise SystemExit("The requested service is not enabled in the catalog")
    if service.provider.name == "scrapecreators" and args.credit_cost_microusd is not None:
        service = service.model_copy(
            update={"provider_unit_cost_microusd": args.credit_cost_microusd}
        )
    input_data: dict[str, object] = {"url": args.url}
    if any(field.name == "max_items" for field in service.input_fields):
        input_data["max_items"] = args.max_items
    ExecutionService.validate_input(service, input_data)
    result = await adapter_for(service).execute(service, input_data)
    price_microusd = service.price_cents * 10_000
    margin_microusd = price_microusd - result.upstream_cost_microusd
    print(f"service={service.id}")
    print(f"provider={service.provider.name}")
    print(f"provider_units={result.provider_units}")
    print(f"provider_unit_cost_microusd={result.provider_unit_cost_microusd}")
    print(f"upstream_cost_microusd={result.upstream_cost_microusd}")
    print(f"catalog_price_cents={service.price_cents}")
    print(f"sample_margin_microusd={margin_microusd}")
    print(f"normalized_top_level={','.join(sorted(result.data))}")
    print(f"normalized_items={len(result.data.get('items', []))}")
    print(f"provider_reference={result.provider_reference or 'unavailable'}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a credentialed provider sample. This can spend real provider credits."
    )
    parser.add_argument("service_id")
    parser.add_argument("url")
    parser.add_argument("--max-items", type=int, default=5)
    parser.add_argument("--credit-cost-microusd", type=int)
    parser.add_argument("--confirm-paid-provider-call", action="store_true")
    args = parser.parse_args()
    if not args.confirm_paid_provider_call:
        raise SystemExit("Re-run with --confirm-paid-provider-call to acknowledge provider cost")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
