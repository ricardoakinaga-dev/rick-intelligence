#!/usr/bin/env python3
"""Authentic, content-addressed seals for promotion packets.

The packet is signed with Ed25519 by an external release authority.  The
verifier accepts only a key explicitly present in the caller's trust store;
``signer_id`` and ``authorized`` fields are claims, not credentials.  The
canonical digest and signature cover the packet body *and* every seal
attribute, so changing an immutable reference, key id or reviewer metadata is
detectable.
"""

from __future__ import annotations

from base64 import b64decode, b64encode
from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
except ImportError:  # pragma: no cover - exercised only in dependency-free environments.
    serialization = None  # type: ignore[assignment]
    Ed25519PrivateKey = None  # type: ignore[assignment,misc]
    Ed25519PublicKey = None  # type: ignore[assignment,misc]


SEAL_SCHEMA = "state-of-art-packet-seal.v2"
SEAL_ALGORITHM = "ed25519-sha256-canonical-json"
KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_B64_RE = re.compile(r"^[A-Za-z0-9+/=_-]+$")
# Kept as a private alias for callers from the first implementation revision.
_REFERENCE_RE = REFERENCE_RE
_PRIVATE_KEY_BYTES = 32
_PUBLIC_KEY_BYTES = 32
_SIGNATURE_BYTES = 64
MAX_SEAL_AGE_SECONDS = 24 * 60 * 60
MAX_SEAL_FUTURE_SKEW_SECONDS = 5 * 60
_SEAL_KEYS = frozenset(
    {
        "schema",
        "algorithm",
        "digest",
        "sealed_at",
        "immutable_reference",
        "signer_id",
        "key_id",
        "immutable",
        "signature",
    }
)


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _body(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in payload.items() if key != "seal"}


def _key_material(value: object, *, expected_length: int, label: str) -> bytes:
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
    elif isinstance(value, str) and _B64_RE.fullmatch(value) is not None:
        encoded = value.encode("ascii")
        padding = b"=" * (-len(encoded) % 4)
        try:
            raw = b64decode(encoded + padding, altchars=b"-_", validate=True)
        except (ValueError, UnicodeEncodeError):
            raw = b""
    else:
        raw = b""
    if len(raw) != expected_length:
        raise ValueError(f"{label} must be {expected_length} raw bytes or base64")
    return raw


def _require_crypto() -> None:
    if Ed25519PrivateKey is None or Ed25519PublicKey is None or serialization is None:
        raise ValueError("Ed25519 packet signing requires the cryptography package")


def _private_key(value: object):
    _require_crypto()
    if isinstance(value, Ed25519PrivateKey):
        return value
    return Ed25519PrivateKey.from_private_bytes(
        _key_material(value, expected_length=_PRIVATE_KEY_BYTES, label="signing_key")
    )


def _public_key(value: object):
    _require_crypto()
    if isinstance(value, Ed25519PublicKey):
        return value
    return Ed25519PublicKey.from_public_bytes(
        _key_material(value, expected_length=_PUBLIC_KEY_BYTES, label="public_key")
    )


def public_key_bytes(value: object) -> bytes:
    """Return the raw 32-byte public key for a trust-store entry."""

    _require_crypto()
    key = value if isinstance(value, Ed25519PublicKey) else _public_key(value)
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def encode_public_key(value: object) -> str:
    """Encode a raw public key for a JSON trust store."""

    return b64encode(public_key_bytes(value)).decode("ascii")


def load_trust_store(path: str | Path) -> dict[str, bytes]:
    """Load ``{key_id: base64_raw_ed25519_public_key}`` from a JSON file."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("promotion trust store is unreadable JSON") from exc
    if isinstance(payload, Mapping) and isinstance(payload.get("keys"), Mapping):
        payload = payload["keys"]
    if not isinstance(payload, Mapping) or not payload:
        raise ValueError("promotion trust store must contain a non-empty object")
    result: dict[str, bytes] = {}
    for raw_key_id, raw_key in payload.items():
        if not isinstance(raw_key_id, str) or KEY_ID_RE.fullmatch(raw_key_id) is None:
            raise ValueError("promotion trust store contains an invalid key id")
        if isinstance(raw_key, Mapping):
            raw_key = raw_key.get("public_key")
        result[raw_key_id] = public_key_bytes(raw_key)
    return result


def _unsigned_seal(*, sealed_at: str, immutable_reference: str, signer_id: str, key_id: str) -> dict[str, Any]:
    return {
        "schema": SEAL_SCHEMA,
        "algorithm": SEAL_ALGORITHM,
        "sealed_at": sealed_at,
        "immutable_reference": immutable_reference,
        "signer_id": signer_id,
        "key_id": key_id,
        "immutable": True,
    }


def _envelope(body: Mapping[str, Any], seal: Mapping[str, Any], *, include_digest: bool) -> dict[str, Any]:
    selected = dict(seal)
    if not include_digest:
        selected.pop("digest", None)
    selected.pop("signature", None)
    return {"body": dict(body), "seal": selected}


def _digest(body: Mapping[str, Any], seal: Mapping[str, Any]) -> str:
    return sha256(_canonical(_envelope(body, seal, include_digest=False))).hexdigest()


def seal_payload(
    payload: Mapping[str, Any],
    *,
    immutable_reference: str,
    signer_id: str,
    key_id: str,
    signing_key: object,
    sealed_at: str | None = None,
) -> dict[str, Any]:
    """Return a copy signed by the external release authority."""

    if not isinstance(immutable_reference, str) or REFERENCE_RE.fullmatch(immutable_reference) is None:
        raise ValueError("immutable_reference is invalid")
    if not isinstance(signer_id, str) or not signer_id.strip() or len(signer_id) > 128:
        raise ValueError("signer_id is invalid")
    if not isinstance(key_id, str) or KEY_ID_RE.fullmatch(key_id) is None:
        raise ValueError("key_id is invalid")
    private_key = _private_key(signing_key)
    timestamp = sealed_at or datetime.now(timezone.utc).isoformat()
    if not isinstance(timestamp, str) or not timestamp.strip():
        raise ValueError("sealed_at is invalid")
    body = _body(payload)
    body["sealed"] = True
    seal = _unsigned_seal(
        sealed_at=timestamp,
        immutable_reference=immutable_reference,
        signer_id=signer_id.strip(),
        key_id=key_id,
    )
    seal["digest"] = _digest(body, seal)
    seal["signature"] = b64encode(private_key.sign(_canonical(_envelope(body, seal, include_digest=True)))).decode("ascii")
    body["seal"] = seal
    return body


def verify_seal(
    payload: Mapping[str, Any],
    *,
    trusted_public_keys: Mapping[str, object] | None,
    now: datetime | None = None,
) -> tuple[bool, tuple[str, ...]]:
    """Verify packet bytes, seal metadata and an explicitly trusted signature."""

    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return False, ("payload must be an object",)
    seal = payload.get("seal")
    if not isinstance(seal, Mapping):
        return False, ("seal is absent",)
    unexpected = sorted(set(seal) - _SEAL_KEYS)
    if unexpected:
        errors.append("seal contains unsupported fields")
    if seal.get("schema") != SEAL_SCHEMA:
        errors.append("seal.schema")
    if seal.get("algorithm") != SEAL_ALGORITHM:
        errors.append("seal.algorithm")
    sealed_at = seal.get("sealed_at")
    if not isinstance(sealed_at, str) or not sealed_at.strip():
        errors.append("seal.sealed_at")
    else:
        try:
            sealed_at_value = datetime.fromisoformat(sealed_at)
            if sealed_at_value.tzinfo is None:
                raise ValueError("sealed_at must include a timezone")
            current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
            age_seconds = (current_time - sealed_at_value.astimezone(timezone.utc)).total_seconds()
            if age_seconds > MAX_SEAL_AGE_SECONDS:
                errors.append("seal.sealed_at is stale")
            elif age_seconds < -MAX_SEAL_FUTURE_SKEW_SECONDS:
                errors.append("seal.sealed_at is in the future")
        except (TypeError, ValueError, OverflowError):
            errors.append("seal.sealed_at is invalid")
    reference = seal.get("immutable_reference")
    if not isinstance(reference, str) or REFERENCE_RE.fullmatch(reference) is None:
        errors.append("seal.immutable_reference")
    if not isinstance(seal.get("signer_id"), str) or not seal["signer_id"].strip():
        errors.append("seal.signer_id")
    key_id = seal.get("key_id")
    if not isinstance(key_id, str) or KEY_ID_RE.fullmatch(key_id) is None:
        errors.append("seal.key_id")
    if seal.get("immutable") is not True:
        errors.append("seal.immutable")
    if payload.get("sealed") is not True:
        errors.append("payload.sealed")

    digest = seal.get("digest")
    if not isinstance(digest, str) or _DIGEST_RE.fullmatch(digest) is None:
        errors.append("seal.digest")
    elif _digest(_body(payload), seal) != digest:
        errors.append("seal.digest does not match packet bytes")

    signature_text = seal.get("signature")
    signature = b""
    if not isinstance(signature_text, str) or _B64_RE.fullmatch(signature_text) is None:
        errors.append("seal.signature")
    else:
        try:
            signature = _key_material(signature_text, expected_length=_SIGNATURE_BYTES, label="signature")
        except ValueError:
            errors.append("seal.signature")

    if not isinstance(trusted_public_keys, Mapping) or not trusted_public_keys:
        errors.append("seal.trust_store is required")
    elif isinstance(key_id, str) and KEY_ID_RE.fullmatch(key_id) is not None:
        if key_id not in trusted_public_keys:
            errors.append("seal.key_id is not trusted")
        elif not any(error.startswith("seal.key_id") for error in errors):
            try:
                public_key = _public_key(trusted_public_keys[key_id])
                public_key.verify(signature, _canonical(_envelope(_body(payload), seal, include_digest=True)))
            except Exception:
                errors.append("seal.signature does not verify")
    if Ed25519PublicKey is None and "seal.trust_store is required" not in errors:
        errors.append("seal.crypto support is unavailable")
    return not errors, tuple(dict.fromkeys(errors))
