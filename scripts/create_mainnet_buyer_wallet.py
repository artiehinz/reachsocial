#!/usr/bin/env python3
"""Create or verify the local recovery phrase for the one-time Base USDC buyer wallet.

The script makes no network calls and never writes a wallet secret to disk. Run
it only in the owner's local terminal, never on the Droplet or through CI.
"""

from __future__ import annotations

import argparse
import getpass

from reachsocial.buyer_wallet import create_buyer_wallet, recover_buyer_wallet


def create() -> None:
    address, mnemonic = create_buyer_wallet()
    print("Save this 12-word recovery phrase in the owner's password manager now:")
    print()
    print(mnemonic)
    print()
    print(f"Base buyer wallet address: {address}")
    print("No wallet secret was written to disk or sent to a server.")


def verify(expected_address: str) -> None:
    mnemonic = getpass.getpass("Paste the recovery phrase (input is hidden): ")
    if not mnemonic.strip():
        raise ValueError("a recovery phrase is required")
    address = recover_buyer_wallet(mnemonic)
    if address.lower() != expected_address.lower():
        raise ValueError("recovery phrase does not produce the expected wallet address")
    print(f"Recovery verified for {address}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create_parser = commands.add_parser("create")
    create_parser.add_argument("--confirm-create-mainnet-buyer-wallet", action="store_true")
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--expected-address", required=True)
    args = parser.parse_args()

    try:
        if args.command == "create":
            if not args.confirm_create_mainnet_buyer_wallet:
                parser.error("--confirm-create-mainnet-buyer-wallet is required")
            create()
        else:
            verify(args.expected_address)
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
