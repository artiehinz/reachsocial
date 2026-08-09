from reachsocial.consumer_contract import (
    INTERNAL_CONTRACT_VERSION,
    NORMALIZATION_VERSION,
    response_meta,
)


def test_internal_consumer_contract_metadata_is_versioned_and_provider_neutral() -> None:
    meta = response_meta(latency_ms=12, response_shape="profile")

    assert meta == {
        "schema_version": INTERNAL_CONTRACT_VERSION,
        "normalization_version": NORMALIZATION_VERSION,
        "response_shape": "profile",
        "latency_ms": 12,
    }
    assert "provider" not in meta
