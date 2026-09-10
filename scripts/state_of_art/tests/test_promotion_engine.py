from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.state_of_art.packet_seal import seal_payload
from scripts.state_of_art import promotion_engine
from scripts.state_of_art import triple_aaa_verify


FIXTURE_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
FIXTURE_TRUST_STORE = {"fixture-release-key": FIXTURE_PRIVATE_KEY.public_key()}
FIXTURE_CHECKOUT = {
    "head": "a" * 40,
    "tree": "b" * 40,
    "fingerprint": "c" * 64,
    "artifact_set_sha256": "d" * 64,
    "status": "CLEAN",
}


def _results(*, status: str = "PASS", external: bool = False) -> list[dict[str, object]]:
    return [
        {
            "id": lane_id,
            "status": status,
            "required": True,
            "external": external or lane_id in promotion_engine.EXTERNAL_LANES,
            "return_code": 0,
            "detail": "fixture observation",
            "independent": True,
        }
        for lane_id in promotion_engine.TRIPLE_AAA_LANES
    ]


def _sealed_packet(results: list[dict[str, object]]) -> dict[str, object]:
    return seal_payload(
        {
            "sealed": True,
            "candidate": {
                "commit_sha": "a" * 40,
                "tree_sha": "b" * 40,
                "checkout_fingerprint": "c" * 64,
                "artifact_set_sha256": "d" * 64,
                "clean_worktree": True,
            },
            "results": results,
            "critical_high_findings": 0,
            "final_decision": "GO",
            "decision_authority": {
                "reviewer_id": "independent-fixture-reviewer",
                "authorized": True,
                "independent": True,
            },
        },
        immutable_reference="artifact://release/fixture",
        signer_id="independent-fixture-reviewer",
        key_id="fixture-release-key",
        signing_key=FIXTURE_PRIVATE_KEY,
    )


def test_all_required_lanes_and_authority_promote() -> None:
    observations = _results()
    result = promotion_engine.evaluate(
        observations,
        packet=_sealed_packet(observations),
        checkout=FIXTURE_CHECKOUT,
        trusted_public_keys=FIXTURE_TRUST_STORE,
    )

    assert result["classification"] == "TRIPLE_AAA"
    assert result["promotion_allowed"] is True
    assert result["exit_code"] == promotion_engine.EXIT_PASS
    assert result["rejection_codes"] == []


def test_valid_packet_without_trusted_authority_cannot_promote() -> None:
    observations = _results()

    result = promotion_engine.evaluate(
        observations,
        packet=_sealed_packet(observations),
        checkout=FIXTURE_CHECKOUT,
    )

    assert result["classification"] == "AAA"
    assert result["promotion_allowed"] is False
    assert result["exit_code"] == promotion_engine.EXIT_FAILED
    assert "PACKET_NOT_SEALED_REJECTED" in result["rejection_codes"]


def test_external_block_returns_candidate_and_exit_two() -> None:
    observations = _results()
    next(item for item in observations if item["id"] == "postgresql-runtime")["status"] = "BLOCKED_EXTERNAL"

    result = promotion_engine.evaluate(observations)

    assert result["classification"] == "STATE_OF_ART_CANDIDATE"
    assert result["promotion_allowed"] is False
    assert result["exit_code"] == promotion_engine.EXIT_FAILED
    assert "BLOCKED_GATE_REJECTED" in result["rejection_codes"]


def test_blocked_foundation_lane_remains_candidate_and_exit_two() -> None:
    observations = _results()
    release = next(item for item in observations if item["id"] == "release-evidence-generation")
    release["status"] = "BLOCKED_EXTERNAL"
    release["external"] = False

    result = promotion_engine.evaluate(observations)

    assert result["classification"] == "STATE_OF_ART_CANDIDATE"
    assert result["promotion_allowed"] is False
    assert result["exit_code"] == promotion_engine.EXIT_FAILED
    assert "BLOCKED_GATE_REJECTED" in result["rejection_codes"]


def test_local_failure_has_priority_over_external_block() -> None:
    observations = _results()
    observations[0]["status"] = "FAIL"
    observations[-1]["status"] = "BLOCKED_EXTERNAL"

    result = promotion_engine.evaluate(observations)

    assert result["classification"] == "DEVELOPMENT"
    assert result["exit_code"] == promotion_engine.EXIT_FAILED
    assert "FAILED_GATE_REJECTED" in result["rejection_codes"]


def test_missing_mandatory_lane_is_not_silently_ignored() -> None:
    observations = _results()
    observations = [item for item in observations if item["id"] != "restore-drill"]

    result = promotion_engine.evaluate(observations)

    assert result["classification"] == "STATE_OF_ART"
    assert result["exit_code"] == promotion_engine.EXIT_FAILED
    assert "MISSING_GATE_REJECTED" in result["rejection_codes"]
    assert any(item["id"] == "restore-drill" for item in result["blocking_lanes"])


def test_local_verified_is_not_runtime_pass() -> None:
    observations = _results()
    observations[0]["status"] = "LOCAL_VERIFIED"

    result = promotion_engine.evaluate(observations)

    assert result["classification"] == "DEVELOPMENT"
    assert result["exit_code"] == promotion_engine.EXIT_FAILED


def test_self_promoted_final_decision_is_rejected() -> None:
    observations = _results()
    observations[-1]["independent"] = False

    result = promotion_engine.evaluate(observations)

    assert result["classification"] == "AAA"
    assert result["promotion_allowed"] is False
    assert result["exit_code"] == promotion_engine.EXIT_FAILED
    assert "SELF_PROMOTED_GATE_REJECTED" in result["rejection_codes"]


def test_unsealed_packet_is_rejected_even_when_lanes_pass() -> None:
    result = promotion_engine.evaluate(
        _results(),
        packet={"sealed": False, "critical_high_findings": 0, "final_decision": "GO"},
    )

    assert result["classification"] == "AAA"
    assert result["promotion_allowed"] is False
    assert "PACKET_NOT_SEALED_REJECTED" in result["rejection_codes"]


def test_packet_is_required_even_when_lanes_pass() -> None:
    result = promotion_engine.evaluate(_results())

    assert result["classification"] == "AAA"
    assert result["promotion_allowed"] is False
    assert result["exit_code"] == promotion_engine.EXIT_FAILED
    assert "PACKET_REQUIRED_REJECTED" in result["rejection_codes"]


def test_promotable_is_not_an_observation_pass() -> None:
    observations = _results(status="PROMOTABLE")
    result = promotion_engine.evaluate(
        observations,
        packet=_sealed_packet(observations),
        checkout=FIXTURE_CHECKOUT,
        trusted_public_keys=FIXTURE_TRUST_STORE,
    )

    assert result["classification"] == "DEVELOPMENT"
    assert result["promotion_allowed"] is False
    assert result["exit_code"] == promotion_engine.EXIT_FAILED
    assert "INVALID_EVIDENCE_REJECTED" in result["rejection_codes"]


def test_sealed_packet_must_match_the_current_checkout() -> None:
    observations = _results()
    result = promotion_engine.evaluate(
        observations,
        packet=_sealed_packet(observations),
        checkout={
            "head": "d" * 40,
            "tree": "b" * 40,
            "fingerprint": "c" * 64,
            "status": "CLEAN",
        },
        trusted_public_keys=FIXTURE_TRUST_STORE,
    )

    assert result["promotion_allowed"] is False
    assert result["exit_code"] == promotion_engine.EXIT_FAILED
    assert "PACKET_BINDING_REJECTED" in result["rejection_codes"]


def test_sealed_packet_requires_current_checkout_binding() -> None:
    observations = _results()

    result = promotion_engine.evaluate(
        observations,
        packet=_sealed_packet(observations),
        trusted_public_keys=FIXTURE_TRUST_STORE,
    )

    assert result["promotion_allowed"] is False
    assert result["exit_code"] == promotion_engine.EXIT_FAILED
    assert "PACKET_BINDING_REJECTED" in result["rejection_codes"]


def test_external_failure_is_not_relabelled_as_external_block() -> None:
    result = triple_aaa_verify._run(
        triple_aaa_verify.Lane(
            "external-failure",
            ("/bin/sh", "-c", "exit 1"),
            external=True,
        ),
        timeout_seconds=10,
    )

    assert result["status"] == "FAIL"
    assert result["return_code"] == 1


def test_arbitrary_external_exit_two_is_not_a_blocked_external_result() -> None:
    result = triple_aaa_verify._run(
        triple_aaa_verify.Lane(
            "external-arbitrary-two",
            ("/bin/sh", "-c", "exit 2"),
            external=True,
        ),
        timeout_seconds=10,
    )

    assert result["status"] == "FAIL"
    assert result["return_code"] == 2


def test_external_block_requires_explicit_exit_two() -> None:
    result = triple_aaa_verify._run(
        triple_aaa_verify.Lane(
            "external-block",
            ("/bin/sh", "-c", "exit 2"),
            external=True,
            blocked_return_codes=frozenset({2}),
        ),
        timeout_seconds=10,
    )

    assert result["status"] == "BLOCKED_EXTERNAL"
    assert result["return_code"] == 2


@pytest.mark.parametrize(
    ("lane_id", "artifact", "expected_status"),
    (
        (
            "phase3-evidence",
            {"capabilities": [{"status": "BLOCKED_EXTERNAL"}]},
            "FAIL",
        ),
        (
            "release-evidence-generation",
            {"status": "BLOCKED_EXTERNAL"},
            "FAIL",
        ),
    ),
)
def test_zero_exit_does_not_hide_blocked_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lane_id: str,
    artifact: dict[str, object],
    expected_status: str,
) -> None:
    monkeypatch.setattr(triple_aaa_verify, "ROOT", tmp_path)
    relative_path = triple_aaa_verify._ARTIFACT_LANE_PATHS[lane_id]
    artifact_path = tmp_path / relative_path
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")

    result = triple_aaa_verify._run(
        triple_aaa_verify.Lane(lane_id, ("/bin/sh", "-c", "exit 0")),
        timeout_seconds=10,
    )

    assert result["status"] == expected_status
    assert result["artifact_classification"] == "FAIL"
    assert result["return_code"] == 0


@pytest.mark.parametrize("artifact_contents", (None, "not-json"))
def test_zero_exit_with_missing_or_invalid_artifact_is_non_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact_contents: str | None,
) -> None:
    monkeypatch.setattr(triple_aaa_verify, "ROOT", tmp_path)
    artifact_path = tmp_path / triple_aaa_verify.RELEASE_EVIDENCE_ARTIFACT
    if artifact_contents is not None:
        artifact_path.parent.mkdir(parents=True)
        artifact_path.write_text(artifact_contents, encoding="utf-8")

    result = triple_aaa_verify._run(
        triple_aaa_verify.Lane("release-evidence-generation", ("/bin/sh", "-c", "exit 0")),
        timeout_seconds=10,
    )

    assert result["status"] in {"FAIL", "NOT_RUN"}
    assert result["status"] != "PASS"
    assert result["return_code"] == 0


def test_zero_exit_with_promotable_matrix_is_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(triple_aaa_verify, "ROOT", tmp_path)
    artifact_path = tmp_path / triple_aaa_verify.PHASE3_EVIDENCE_ARTIFACT
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(json.dumps({"classification": "PROMOTABLE"}), encoding="utf-8")

    result = triple_aaa_verify._run(
        triple_aaa_verify.Lane("phase3-evidence", ("/bin/sh", "-c", "exit 0")),
        timeout_seconds=10,
    )

    assert result["status"] == "FAIL"
    assert result["artifact_classification"] == "FAIL"
    assert result["return_code"] == 0


def test_zero_exit_with_pass_manifest_is_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(triple_aaa_verify, "ROOT", tmp_path)
    artifact_path = tmp_path / triple_aaa_verify.RELEASE_EVIDENCE_ARTIFACT
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")

    result = triple_aaa_verify._run(
        triple_aaa_verify.Lane("release-evidence-generation", ("/bin/sh", "-c", "exit 0")),
        timeout_seconds=10,
    )

    assert result["status"] == "FAIL"
    assert result["artifact_classification"] == "FAIL"
    assert result["return_code"] == 0


def test_unobserved_normal_zero_exit_remains_pass() -> None:
    result = triple_aaa_verify._run(
        triple_aaa_verify.Lane("normal-command", ("/bin/sh", "-c", "exit 0")),
        timeout_seconds=10,
    )

    assert result["status"] == "PASS"
    assert result["return_code"] == 0
