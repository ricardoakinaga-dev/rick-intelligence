"""Password handling: PBKDF2-HMAC-SHA256 100k, per-user salt, legacy-format verify.

Portable format: $pbkdf2$<salt_hex>$<hash_hex> (mirrors preserved CVG format so
migrated records verify). Test-only plaintext verifier exists but is REFUSED in
production mode (fail-closed startup).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

ITERATIONS = 100_000


def hash_password(password: str, salt_hex: str | None = None) -> str:
    salt_hex = salt_hex or secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), ITERATIONS)
    return f"$pbkdf2${salt_hex}${key.hex()}"


def verify_password_hash(stored: str, password: str) -> bool:
    try:
        if not stored.startswith("$pbkdf2$"):
            return False
        parts = stored.split("$")
        # ["", "pbkdf2", salt, hash]
        if len(parts) != 4 or not parts[2] or not parts[3]:
            return False
        _, _, salt_hex, expected_hex = parts
        key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), ITERATIONS)
        return hmac.compare_digest(key.hex(), expected_hex)
    except Exception:
        return False
