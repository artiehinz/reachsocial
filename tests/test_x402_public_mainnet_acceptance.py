from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from reachsocial.catalog import load_catalog

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "x402_public_mainnet_acceptance.py"
_SPEC = importlib.util.spec_from_file_location("x402_public_mainnet_acceptance", _SCRIPT)
assert _SPEC and _SPEC.loader
acceptance = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = acceptance
_SPEC.loader.exec_module(acceptance)


def test_parse_target_and_build_person_news_input() -> None:
    target = acceptance.parse_target("news.person=Artie Hinz")
    service = load_catalog().by_id(target.service_id)

    assert service is not None
    assert acceptance.input_for(service, target) == {"full_name": "Artie Hinz", "max_items": 5}


def test_select_requirement_requires_the_exact_base_usdc_quote() -> None:
    required = SimpleNamespace(
        accepts=[
            SimpleNamespace(
                network=acceptance.BASE_MAINNET_NETWORK,
                asset=acceptance.USDC_BASE_MAINNET,
                pay_to="0xmerchant",
                amount="50000",
            )
        ]
    )

    assert acceptance.select_requirement(required, expected_pay_to="0xMERCHANT", amount=50_000).amount == "50000"
    with pytest.raises(ValueError, match="exact native Base-USDC"):
        acceptance.select_requirement(required, expected_pay_to="0xmerchant", amount=100_000)


def test_public_endpoint_and_price_follow_the_service_contract() -> None:
    service = load_catalog().by_id("instagram.profile")

    assert service is not None
    assert acceptance.endpoint_for(service, "https://reachsocial.dev") == (
        "https://reachsocial.dev/v1/services/instagram.profile/execute"
    )
    assert acceptance.amount_atomic(service) == 50_000
