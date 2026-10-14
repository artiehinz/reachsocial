import pytest
from fastapi import HTTPException

from reachsocial.api import optional_client
from reachsocial.models import Client
from reachsocial.security import api_key_id, generate_api_key, hash_api_key, verify_api_key


def test_api_key_hash_verification() -> None:
    key = generate_api_key()
    assert key.startswith("rs_live_")
    assert len(api_key_id(key) or "") == 12
    encoded = hash_api_key(key)
    assert verify_api_key(key, encoded)
    assert not verify_api_key("rs_live_wrong", encoded)
    assert api_key_id("rs_live_legacy-token") is None


def test_only_indexed_api_keys_authenticate(session) -> None:
    indexed_key = generate_api_key()
    indexed = Client(
        name="indexed",
        key_id=api_key_id(indexed_key),
        api_key_hash=hash_api_key(indexed_key),
    )
    legacy_key = "rs_legacy_existing_secret"
    legacy = Client(name="legacy", key_id=None, api_key_hash=hash_api_key(legacy_key))
    session.add_all([indexed, legacy])
    session.commit()
    assert optional_client(f"Bearer {indexed_key}", session).id == indexed.id
    with pytest.raises(HTTPException) as error:
        optional_client(f"Bearer {legacy_key}", session)
    assert error.value.status_code == 401
