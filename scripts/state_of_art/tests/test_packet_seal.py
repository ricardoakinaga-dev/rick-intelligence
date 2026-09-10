from __future__ import annotations

import json
from datetime import datetime, timezone

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.state_of_art.packet_seal import (
    encode_public_key,
    load_trust_store,
    seal_payload,
    verify_seal,
)


PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
TRUST_STORE = {"release-key-2026": PRIVATE_KEY.public_key()}


def _seal(
    payload: dict[str, object],
    *,
    sealed_at: str | None = None,
) -> dict[str, object]:
    return seal_payload(
        payload,
        immutable_reference="artifact://release/abc123",
        signer_id="release-authority",
        key_id="release-key-2026",
        signing_key=PRIVATE_KEY,
        sealed_at=sealed_at or datetime.now(timezone.utc).isoformat(),
    )


def test_seal_round_trip_and_mutation_detection() -> None:
    sealed = _seal({"classification": "TRIPLE_AAA", "promotion_allowed": True, "results": []})

    assert verify_seal(sealed, trusted_public_keys=TRUST_STORE) == (True, ())
    sealed["classification"] = "AAA"
    valid, errors = verify_seal(sealed, trusted_public_keys=TRUST_STORE)
    assert valid is False
    assert "seal.digest does not match packet bytes" in errors


def test_seal_rejects_missing_or_untrusted_authority() -> None:
    sealed = _seal({"classification": "TRIPLE_AAA"})

    valid, errors = verify_seal(sealed, trusted_public_keys=None)
    assert valid is False
    assert "seal.trust_store is required" in errors

    valid, errors = verify_seal(sealed, trusted_public_keys={"other-key": PRIVATE_KEY.public_key()})
    assert valid is False
    assert "seal.key_id is not trusted" in errors


def test_seal_covers_immutable_reference_and_signer_metadata() -> None:
    sealed = _seal({"classification": "TRIPLE_AAA"})
    sealed["seal"]["immutable_reference"] = "artifact://release/attacker"  # type: ignore[index]

    valid, errors = verify_seal(sealed, trusted_public_keys=TRUST_STORE)

    assert valid is False
    assert "seal.digest does not match packet bytes" in errors
    assert "seal.signature does not verify" in errors


def test_seal_rejects_stale_timestamp_even_when_signature_is_valid() -> None:
    sealed = _seal({"classification": "TRIPLE_AAA"}, sealed_at="1900-01-01T00:00:00+00:00")

    valid, errors = verify_seal(
        sealed,
        trusted_public_keys=TRUST_STORE,
        now=datetime(2026, 9, 10, tzinfo=timezone.utc),
    )

    assert valid is False
    assert "seal.sealed_at is stale" in errors


def test_seal_rejects_signature_from_unknown_key_even_when_claims_are_authorized() -> None:
    attacker = Ed25519PrivateKey.from_private_bytes(bytes(reversed(range(32))))
    forged = seal_payload(
        {"classification": "TRIPLE_AAA", "decision_authority": {"authorized": True, "independent": True}},
        immutable_reference="artifact://release/abc123",
        signer_id="release-authority",
        key_id="attacker-key",
        signing_key=attacker,
    )

    valid, errors = verify_seal(forged, trusted_public_keys=TRUST_STORE)

    assert valid is False
    assert "seal.key_id is not trusted" in errors


def test_json_trust_store_round_trip(tmp_path) -> None:
    path = tmp_path / "trust-store.json"
    path.write_text(json.dumps({"keys": {"release-key-2026": encode_public_key(PRIVATE_KEY.public_key())}}), encoding="utf-8")

    loaded = load_trust_store(path)

    assert set(loaded) == {"release-key-2026"}
    assert verify_seal(_seal({"classification": "TRIPLE_AAA"}), trusted_public_keys=loaded) == (True, ())


def test_json_trust_store_rejects_duplicate_key_ids(tmp_path) -> None:
    encoded_key = encode_public_key(PRIVATE_KEY.public_key())
    path = tmp_path / "trust-store.json"
    path.write_text(
        '{"keys":{"release-key-2026":"%s","release-key-2026":"%s"}}' % (encoded_key, encoded_key),
        encoding="utf-8",
    )

    try:
        load_trust_store(path)
    except ValueError as error:
        assert "unreadable JSON" in str(error)
    else:  # pragma: no cover - assertion makes the expected failure explicit.
        raise AssertionError("duplicate trust-store key was accepted")


def test_seal_does_not_accept_unbounded_reference() -> None:
    try:
        seal_payload(
            {},
            immutable_reference="secret value",
            signer_id="reviewer",
            key_id="release-key-2026",
            signing_key=PRIVATE_KEY,
        )
    except ValueError as error:
        assert str(error) == "immutable_reference is invalid"
    else:  # pragma: no cover - assertion makes the expected failure explicit.
        raise AssertionError("unsafe seal reference was accepted")
