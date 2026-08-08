from reachsocial.security import generate_api_key, hash_api_key, verify_api_key


def test_api_key_hash_verification() -> None:
    key = generate_api_key()
    assert key.startswith("rs_live_")
    encoded = hash_api_key(key)
    assert verify_api_key(key, encoded)
    assert not verify_api_key("rs_live_wrong", encoded)
