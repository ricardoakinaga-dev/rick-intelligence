#!/usr/bin/env python3
"""Content-addressed seal primitives for promotion packets.

The seal detects byte mutation in a packet without pretending that a local
file is write-once storage.  Promotion still requires the immutable reference
to be retained by an authorized artifact system.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any


SEAL_SCHEMA = "state-of-art-packet-seal.v1"
SEAL_ALGORITHM = "sha256-canonical-json-without-seal"
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
# Kept as a private alias for callers from the first implementation revision.
_REFERENCE_RE = REFERENCE_RE


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _body(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in payload.items() if key != "seal"}


def _digest(payload: Mapping[str, Any]) -> str:
    return sha256(_canonical(_body(payload))).hexdigest()


def seal_payload(
    payload: Mapping[str, Any],
    *,
    immutable_reference: str,
    signer_id: str,
    sealed_at: str | None = None,
) -> dict[str, Any]:
    """Return a copy with a deterministic, mutation-detecting seal."""

    if not isinstance(immutable_reference, str) or REFERENCE_RE.fullmatch(immutable_reference) is None:
        raise ValueError("immutable_reference is invalid")
    if not isinstance(signer_id, str) or not signer_id.strip() or len(signer_id) > 128:
        raise ValueError("signer_id is invalid")
    timestamp = sealed_at or datetime.now(timezone.utc).isoformat()
    body = _body(payload)
    # The marker is part of the signed body.  A seal object copied onto an
    # otherwise unsigned payload therefore cannot masquerade as a sealed one.
    body["sealed"] = True
    body["seal"] = {
        "schema": SEAL_SCHEMA,
        "algorithm": SEAL_ALGORITHM,
        "digest": _digest(body),
        "sealed_at": timestamp,
        "immutable_reference": immutable_reference,
        "signer_id": signer_id.strip(),
        "immutable": True,
    }
    return body


def verify_seal(payload: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Verify packet seal fields and the content digest."""

    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return False, ("payload must be an object",)
    seal = payload.get("seal")
    if not isinstance(seal, Mapping):
        return False, ("seal is absent",)
    if seal.get("schema") != SEAL_SCHEMA:
        errors.append("seal.schema")
    if seal.get("algorithm") != SEAL_ALGORITHM:
        errors.append("seal.algorithm")
    digest = seal.get("digest")
    if not isinstance(digest, str) or _DIGEST_RE.fullmatch(digest) is None:
        errors.append("seal.digest")
    elif digest != _digest(payload):
        errors.append("seal.digest does not match packet bytes")
    if not isinstance(seal.get("sealed_at"), str) or not seal["sealed_at"].strip():
        errors.append("seal.sealed_at")
    reference = seal.get("immutable_reference")
    if not isinstance(reference, str) or REFERENCE_RE.fullmatch(reference) is None:
        errors.append("seal.immutable_reference")
    if not isinstance(seal.get("signer_id"), str) or not seal["signer_id"].strip():
        errors.append("seal.signer_id")
    if seal.get("immutable") is not True:
        errors.append("seal.immutable")
    if payload.get("sealed") is not True:
        errors.append("payload.sealed")
    return not errors, tuple(errors)
