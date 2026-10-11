#!/usr/bin/env python3
"""Locally rehearse one exact Base-USDC refund from the merchant wallet.

The recovery phrase is read only through hidden terminal input, is never
written to disk, and is never sent to ReachSocial. Without --confirm-refund,
this command is a dry run and broadcasts no transaction.
"""

from __future__ import annotations

import argparse
import getpass
import time
from typing import Any

from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3

BASE_MAINNET_CHAIN_ID = 8453
BASE_MAINNET_RPC = "https://mainnet.base.org"
BASE_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
TRANSFER_EVENT = Web3.keccak(text="Transfer(address,address,uint256)").hex()
MIN_GAS_LIMIT = 70_000

USDC_ABI = [
    {
        "type": "function",
        "name": "balanceOf",
        "stateMutability": "view",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "transfer",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
]


def padded_topic(address: str) -> str:
    return "0x" + "0" * 24 + address.lower().removeprefix("0x")


def has_exact_usdc_transfer(
    receipt: dict[str, Any], *, sender: str, recipient: str, amount_atomic: int
) -> bool:
    return any(
        str(log.get("address", "")).lower() == BASE_USDC.lower()
        and [str(topic).lower() for topic in log.get("topics", [])]
        == [TRANSFER_EVENT.lower(), padded_topic(sender), padded_topic(recipient)]
        and int(str(log.get("data", "0x0")), 16) == amount_atomic
        for log in receipt.get("logs", [])
    )


def recover_merchant(mnemonic: str, expected_merchant: str) -> LocalAccount:
    Account.enable_unaudited_hdwallet_features()
    account = Account.from_mnemonic(mnemonic.strip(), account_path="m/44'/60'/0'/0/0")
    if account.address.lower() != expected_merchant.lower():
        raise ValueError("recovery phrase does not produce the expected merchant address")
    return account


def fee_fields(web3: Web3) -> dict[str, int]:
    block = web3.eth.get_block("latest")
    base_fee = int(block.get("baseFeePerGas") or web3.eth.gas_price)
    try:
        priority_fee = int(web3.eth.max_priority_fee)
    except Exception:
        priority_fee = 1_000_000
    priority_fee = max(priority_fee, 1_000_000)
    return {
        "maxPriorityFeePerGas": priority_fee,
        "maxFeePerGas": base_fee * 2 + priority_fee,
    }


def wait_for_receipt(web3: Web3, transaction_hash: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        receipt = web3.eth.get_transaction_receipt(transaction_hash)
        if receipt is not None:
            return dict(receipt)
        time.sleep(2)
    raise RuntimeError("refund transaction was broadcast but did not confirm before the timeout")


def run(args: argparse.Namespace) -> None:
    if not Web3.is_address(args.expected_merchant) or not Web3.is_address(args.expected_buyer):
        raise ValueError("merchant and buyer addresses must be valid EVM addresses")
    if args.expected_merchant.lower() == args.expected_buyer.lower():
        raise ValueError("merchant and buyer addresses must differ")
    if args.amount_atomic <= 0:
        raise ValueError("--amount-atomic must be positive")

    mnemonic = getpass.getpass("Paste the merchant recovery phrase (input is hidden): ")
    if not mnemonic.strip():
        raise ValueError("a recovery phrase is required")
    account = recover_merchant(mnemonic, args.expected_merchant)
    web3 = Web3(Web3.HTTPProvider(args.rpc_url, request_kwargs={"timeout": 20}))
    if not web3.is_connected():
        raise RuntimeError("could not connect to the Base RPC endpoint")
    if web3.eth.chain_id != BASE_MAINNET_CHAIN_ID:
        raise RuntimeError("RPC endpoint is not Base mainnet")

    merchant = Web3.to_checksum_address(account.address)
    buyer = Web3.to_checksum_address(args.expected_buyer)
    usdc = web3.eth.contract(address=Web3.to_checksum_address(BASE_USDC), abi=USDC_ABI)
    if int(usdc.functions.balanceOf(merchant).call()) < args.amount_atomic:
        raise RuntimeError("merchant USDC balance is below the requested refund amount")
    fees = fee_fields(web3)
    maximum_gas_cost = MIN_GAS_LIMIT * fees["maxFeePerGas"]
    if web3.eth.get_balance(merchant) < maximum_gas_cost:
        raise RuntimeError("merchant needs Base ETH for the refund transaction fee")

    transaction = usdc.functions.transfer(buyer, args.amount_atomic).build_transaction(
        {
            "chainId": BASE_MAINNET_CHAIN_ID,
            "from": merchant,
            "nonce": web3.eth.get_transaction_count(merchant, "pending"),
            "gas": MIN_GAS_LIMIT,
            **fees,
        }
    )
    estimated_gas = int(web3.eth.estimate_gas(transaction))
    transaction["gas"] = max(MIN_GAS_LIMIT, (estimated_gas * 6 + 4) // 5)

    if not args.confirm_refund:
        print(
            f"Dry run passed: {args.amount_atomic} native Base-USDC atomic units are ready for "
            f"refund from {merchant} to {buyer}. No transaction was signed or sent."
        )
        return

    signed = account.sign_transaction(transaction)
    raw_transaction = getattr(signed, "raw_transaction", getattr(signed, "rawTransaction", None))
    if raw_transaction is None:
        raise RuntimeError("wallet library did not return a signed transaction")
    transaction_hash = web3.eth.send_raw_transaction(raw_transaction).hex()
    receipt = wait_for_receipt(web3, transaction_hash, args.timeout_seconds)
    if int(receipt.get("status", 0)) != 1:
        raise RuntimeError("refund transaction reverted")
    if not has_exact_usdc_transfer(
        receipt, sender=merchant, recipient=buyer, amount_atomic=args.amount_atomic
    ):
        raise RuntimeError("confirmed transaction did not contain the expected native Base-USDC refund")
    print(f"Refund settled and verified: {transaction_hash}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-merchant", required=True)
    parser.add_argument("--expected-buyer", required=True)
    parser.add_argument("--amount-atomic", type=int, default=50_000)
    parser.add_argument("--rpc-url", default=BASE_MAINNET_RPC)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--confirm-refund", action="store_true")
    args = parser.parse_args()
    if not 10 <= args.timeout_seconds <= 600:
        parser.error("--timeout-seconds must be between 10 and 600")
    try:
        run(args)
    except (ValueError, RuntimeError) as error:
        parser.error(str(error))
    except Exception as error:
        parser.error(f"{type(error).__name__}: refund rehearsal did not complete")


if __name__ == "__main__":
    main()
