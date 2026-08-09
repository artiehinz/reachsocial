from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

PRICE_TIERS_CENTS = (5, 10, 15, 25, 50)
PENDING_SCRAPECREATORS_SERVICE_IDS = (
    "x.profile",
    "x.post",
    "tiktok.profile",
    "tiktok.feed",
    "tiktok.video",
)


def cost_per_credit_microusd(pack_price_usd: Decimal, credits: int) -> int:
    if pack_price_usd <= 0:
        raise ValueError("pack price must be positive")
    if credits <= 0:
        raise ValueError("credits must be positive")
    value = (pack_price_usd * Decimal(1_000_000)) / Decimal(credits)
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def minimum_price_tier(unit_cost_microusd: int) -> int:
    if unit_cost_microusd <= 0:
        raise ValueError("unit cost must be positive")
    for price_cents in PRICE_TIERS_CENTS:
        price_microusd = price_cents * 10_000
        absolute_margin = price_microusd - unit_cost_microusd
        if absolute_margin >= 10_000 and absolute_margin * 2 >= price_microusd:
            return price_cents
    raise ValueError("no configured price tier satisfies the launch margin")


def scrapecreators_cost_report(pack_price_usd: Decimal, credits: int) -> dict[str, object]:
    unit_cost = cost_per_credit_microusd(pack_price_usd, credits)
    tier = minimum_price_tier(unit_cost)
    return {
        "source_values": {
            "pack_price_usd": format(pack_price_usd, "f"),
            "credits": credits,
        },
        "catalog_values": {
            "estimated_upstream_cost_microusd": unit_cost,
            "provider_unit_cost_microusd": unit_cost,
            "minimum_margin_safe_price_cents": tier,
        },
        "services_unblocked_after_live_contract_evidence": list(
            PENDING_SCRAPECREATORS_SERVICE_IDS
        ),
        "note": (
            "Record the plan/pack name, source URL or invoice reference, and UTC verification "
            "date before setting cost_verified=true. This command does not edit the catalog."
        ),
    }
