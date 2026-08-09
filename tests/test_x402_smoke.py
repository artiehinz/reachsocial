from types import SimpleNamespace

import pytest

from reachsocial.x402_smoke import select_smoke_requirement


def requirement(*, network="eip155:84532", pay_to="0xReceiver", amount="50000"):
    return SimpleNamespace(scheme="exact", network=network, pay_to=pay_to, amount=amount)


def test_select_requirement_enforces_network_receiver_and_cap() -> None:
    selected = requirement()
    payment_required = SimpleNamespace(
        accepts=[
            requirement(network="eip155:8453"),
            requirement(pay_to="0xSomeoneElse"),
            requirement(amount="0"),
            requirement(amount="50001"),
            selected,
        ]
    )

    assert select_smoke_requirement(payment_required, expected_pay_to="0xreceiver") is selected


def test_select_requirement_rejects_ambiguous_challenge() -> None:
    payment_required = SimpleNamespace(accepts=[requirement(), requirement()])

    with pytest.raises(ValueError, match="exactly one"):
        select_smoke_requirement(payment_required, expected_pay_to="0xReceiver")
