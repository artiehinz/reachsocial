"""Local-only recovery helpers for the one-time Base mainnet buyer wallet."""

from eth_account import Account
from eth_account.signers.local import LocalAccount

DERIVATION_PATH = "m/44'/60'/0'/0/0"


def create_buyer_wallet() -> tuple[str, str]:
    """Return a new EVM address and its BIP-39 recovery phrase without persisting either."""
    Account.enable_unaudited_hdwallet_features()
    account, mnemonic = Account.create_with_mnemonic(account_path=DERIVATION_PATH)
    return account.address, mnemonic


def recover_buyer_wallet(mnemonic: str) -> str:
    """Derive the Base-compatible EVM address from a BIP-39 recovery phrase."""
    return recover_buyer_account(mnemonic).address


def recover_buyer_account(mnemonic: str) -> LocalAccount:
    """Recover the local signing account without persisting its private key."""
    Account.enable_unaudited_hdwallet_features()
    return Account.from_mnemonic(mnemonic.strip(), account_path=DERIVATION_PATH)
