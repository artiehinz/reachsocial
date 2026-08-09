from __future__ import annotations

from typing import Any

BASE_SEPOLIA_NETWORK = "eip155:84532"
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
