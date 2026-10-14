from __future__ import annotations

from typing import Any

from .config import Settings

X402_VERSION = 2

NETWORK_ASSETS: dict[str, dict[str, Any]] = {
    "eip155:8453": {
        "chain_id": 8453,
        "name": "Base mainnet",
        "asset": {
            "symbol": "USDC",
            "address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "decimals": 6,
        },
    },
    "eip155:84532": {
        "chain_id": 84532,
        "name": "Base Sepolia",
        "asset": {
            "symbol": "USDC",
            "address": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
            "decimals": 6,
        },
    },
}


def public_payment_metadata(settings: Settings) -> dict[str, Any]:
    """Return the non-secret payment facts browser clients must verify."""
    network = NETWORK_ASSETS.get(settings.x402_network)
    return {
        "enabled": settings.x402_enabled,
        "protocol": "x402",
        "version": X402_VERSION,
        "network": settings.x402_network,
        "chain_id": network["chain_id"] if network else None,
        "network_name": network["name"] if network else settings.x402_network,
        "asset": network["asset"] if network else None,
        "receiver": settings.x402_pay_to if settings.x402_enabled else None,
    }
