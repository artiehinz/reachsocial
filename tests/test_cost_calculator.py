from decimal import Decimal

import pytest

from reachsocial.economics import (
    cost_per_credit_microusd,
    minimum_price_tier,
    scrapecreators_cost_report,
)


def test_cost_per_credit_rounds_up_to_one_microusd() -> None:
    assert cost_per_credit_microusd(Decimal("19"), 10_101) == 1882


def test_report_selects_first_tier_with_both_margin_guards() -> None:
    report = scrapecreators_cost_report(Decimal("19"), 10_000)

    assert report["catalog_values"] == {
        "estimated_upstream_cost_microusd": 1900,
        "provider_unit_cost_microusd": 1900,
        "minimum_margin_safe_price_cents": 5,
    }


def test_price_tier_rejects_cost_beyond_configured_tiers() -> None:
    with pytest.raises(ValueError, match="no configured price tier"):
        minimum_price_tier(490_001)
