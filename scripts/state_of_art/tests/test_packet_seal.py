from __future__ import annotations

from scripts.state_of_art.packet_seal import seal_payload, verify_seal


def test_seal_round_trip_and_mutation_detection() -> None:
    payload = {"classification": "TRIPLE_AAA", "promotion_allowed": True, "results": []}
    sealed = seal_payload(
        payload,
        immutable_reference="artifact://release/abc123",
        signer_id="release-authority",
        sealed_at="2026-09-10T00:00:00+00:00",
    )

    assert verify_seal(sealed) == (True, ())
    sealed["classification"] = "AAA"
    valid, errors = verify_seal(sealed)
    assert valid is False
    assert "seal.digest does not match packet bytes" in errors


def test_seal_does_not_accept_unbounded_reference() -> None:
    try:
        seal_payload({}, immutable_reference="secret value", signer_id="reviewer")
    except ValueError as error:
        assert str(error) == "immutable_reference is invalid"
    else:  # pragma: no cover - assertion makes the expected failure explicit.
        raise AssertionError("unsafe seal reference was accepted")
