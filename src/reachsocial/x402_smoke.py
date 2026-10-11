from __future__ import annotations

from typing import Any

BASE_SEPOLIA_NETWORK = "eip155:84532"
BASE_MAINNET_NETWORK = "eip155:8453"
BASE_MAINNET_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
MAX_SMOKE_AMOUNT_ATOMIC = 50_000


def select_smoke_requirement(
    payment_required: Any,
    *,
    expected_pay_to: str,
    max_amount_atomic: int = MAX_SMOKE_AMOUNT_ATOMIC,
) -> Any:
    candidates = [
        requirement
        for requirement in payment_required.accepts
        if requirement.scheme == "exact"
        and requirement.network == BASE_SEPOLIA_NETWORK
        and requirement.pay_to.lower() == expected_pay_to.lower()
        and 0 < int(requirement.amount) <= max_amount_atomic
    ]
    if len(candidates) != 1:
        raise ValueError("challenge does not contain exactly one approved payment requirement")
    return candidates[0]


def select_mainnet_canary_requirement(payment_required: Any, *, expected_pay_to: str) -> Any:
    """Accept only the single five-cent Base-mainnet requirement for the canary."""
    candidates = [
        requirement
        for requirement in payment_required.accepts
        if requirement.scheme == "exact"
        and requirement.network == BASE_MAINNET_NETWORK
        and requirement.pay_to.lower() == expected_pay_to.lower()
        and requirement.asset.lower() == BASE_MAINNET_USDC.lower()
        and int(requirement.amount) == MAX_SMOKE_AMOUNT_ATOMIC
    ]
    if len(candidates) != 1:
        raise ValueError("challenge does not contain the approved five-cent mainnet requirement")
    return candidates[0]
