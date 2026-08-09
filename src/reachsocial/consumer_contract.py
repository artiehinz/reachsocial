"""Stable metadata for internal normalized-result consumers.

This describes the provider-neutral envelope, not an acceptance decision for a
provider or a public-service enablement signal.
"""

INTERNAL_CONTRACT_VERSION = "1.0"
NORMALIZATION_VERSION = "v1"


def response_meta(*, latency_ms: int, response_shape: str) -> dict[str, object]:
    return {
        "schema_version": INTERNAL_CONTRACT_VERSION,
        "normalization_version": NORMALIZATION_VERSION,
        "response_shape": response_shape,
        "latency_ms": max(0, int(latency_ms)),
    }
