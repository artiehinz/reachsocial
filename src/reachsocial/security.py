from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


def generate_api_key() -> str:
    return f"rs_live_{secrets.token_urlsafe(32)}"


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
