from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

API_KEY_PREFIX = "rs_live_"


def generate_api_key() -> str:
    key_id = secrets.token_hex(6)
    return f"{API_KEY_PREFIX}{key_id}_{secrets.token_urlsafe(32)}"


def api_key_id(api_key: str) -> str | None:
    if not api_key.startswith(API_KEY_PREFIX):
        return None
    remainder = api_key.removeprefix(API_KEY_PREFIX)
    key_id, separator, secret = remainder.partition("_")
    if not separator or len(key_id) != 12 or not secret:
        return None
    try:
        int(key_id, 16)
    except ValueError:
        return None
    return key_id


def hash_api_key(api_key: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(api_key.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return "scrypt$" + base64.urlsafe_b64encode(salt + digest).decode("ascii")


def verify_api_key(api_key: str, encoded_hash: str) -> bool:
    try:
        kind, encoded = encoded_hash.split("$", 1)
        if kind != "scrypt":
            return False
        raw = base64.urlsafe_b64decode(encoded.encode("ascii"))
        salt, expected = raw[:16], raw[16:]
        actual = hashlib.scrypt(api_key.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False
