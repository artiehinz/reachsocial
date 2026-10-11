from __future__ import annotations

import importlib.util
from pathlib import Path


def load_script():
    path = Path(__file__).parents[1] / "scripts" / "mainnet_refund_rehearsal.py"
    spec = importlib.util.spec_from_file_location("mainnet_refund_rehearsal", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exact_transfer_receipt_validation() -> None:
    refund = load_script()
    sender = "0x76bCc44696A4c67579A6aF2F25CF953BE0931E38"
    recipient = "0xcf8fD9bd415C36326597E8079fCb3125FE2dB369"
    receipt = {
        "logs": [
            {
                "address": refund.BASE_USDC,
                "topics": [refund.TRANSFER_EVENT, refund.padded_topic(sender), refund.padded_topic(recipient)],
                "data": hex(50_000),
            }
        ]
    }
    assert refund.has_exact_usdc_transfer(
        receipt, sender=sender, recipient=recipient, amount_atomic=50_000
    )
    assert not refund.has_exact_usdc_transfer(
        receipt, sender=sender, recipient=recipient, amount_atomic=50_001
    )
