import json
from pathlib import Path
import shutil

from scripts.state_of_art.triple_aaa_capability_matrix import (
    ALLOWED_STATES,
    EXPECTED_CAPABILITIES,
    EXPECTED_PROMPT,
    EXPECTED_PROMPT_SHA256,
    validate,
)
from scripts.state_of_art import triple_aaa_capability_matrix


ROOT = Path(__file__).resolve().parents[3]


def test_current_matrix_has_only_prompt_states_and_required_columns():
    path = ROOT / "docs/reports/triple-aaa-runtime-capability-matrix.json"
    result = validate(path)
    assert result["status"] == "PASS", result
    assert result["rows"] == len(EXPECTED_CAPABILITIES)
    assert "MISSING" not in ALLOWED_STATES

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["prompt"] == EXPECTED_PROMPT
    assert document["prompt_sha256"] == EXPECTED_PROMPT_SHA256
    assert document["candidate_binding"]["packet"] == ".runtime/phase-3/triple-aaa-verify.json"


def test_current_matrix_can_be_bound_to_an_exact_verifier_packet(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(triple_aaa_capability_matrix, "ROOT", tmp_path)
    source = tmp_path / "matrix.json"
    source.write_text(
        (ROOT / "docs/reports/triple-aaa-runtime-capability-matrix.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    prompt = tmp_path / EXPECTED_PROMPT
    prompt.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / EXPECTED_PROMPT, prompt)
    packet = tmp_path / ".runtime/phase-3/triple-aaa-verify.json"
    packet.parent.mkdir(parents=True, exist_ok=True)
    packet.write_text(
        json.dumps(
            {
                "schema_version": "state-of-art-triple-aaa-verify.v2",
                "classification": "STATE_OF_ART_CANDIDATE",
                "exit_code": 2,
                "candidate": {
                    "commit_sha": "a" * 40,
                    "tree_sha": "b" * 40,
                    "checkout_fingerprint": "c" * 64,
                    "artifact_set_sha256": "d" * 64,
                },
            }
        ),
        encoding="utf-8",
    )

    output = tmp_path / ".runtime/phase-3/current-matrix.json"
    result = triple_aaa_capability_matrix.bind_to_packet(source, packet, output)

    assert result["status"] == "PASS"
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["candidate_binding"]["commit_sha"] == "a" * 40
    assert validate(output, packet=packet)["status"] == "PASS"


def test_bound_matrix_rejects_packet_identity_drift(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(triple_aaa_capability_matrix, "ROOT", tmp_path)
    source = tmp_path / "matrix.json"
    source.write_text(
        (ROOT / "docs/reports/triple-aaa-runtime-capability-matrix.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    prompt = tmp_path / EXPECTED_PROMPT
    prompt.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / EXPECTED_PROMPT, prompt)
    packet = tmp_path / ".runtime/phase-3/triple-aaa-verify.json"
    packet.parent.mkdir(parents=True, exist_ok=True)
    packet.write_text(
        json.dumps(
            {
                "schema_version": "state-of-art-triple-aaa-verify.v2",
                "classification": "STATE_OF_ART_CANDIDATE",
                "exit_code": 2,
                "candidate": {
                    "commit_sha": "a" * 40,
                    "tree_sha": "b" * 40,
                    "checkout_fingerprint": "c" * 64,
                    "artifact_set_sha256": "d" * 64,
                },
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / ".runtime/phase-3/current-matrix.json"
    triple_aaa_capability_matrix.bind_to_packet(source, packet, output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["candidate_binding"]["tree_sha"] = "e" * 40
    output.write_text(json.dumps(payload), encoding="utf-8")

    result = validate(output, packet=packet)

    assert result["status"] == "FAIL"
    assert any("tree_sha" in error for error in result["errors"])


def test_bound_matrix_rejects_packet_hash_drift(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(triple_aaa_capability_matrix, "ROOT", tmp_path)
    source = tmp_path / "matrix.json"
    source.write_text(
        (ROOT / "docs/reports/triple-aaa-runtime-capability-matrix.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    prompt = tmp_path / EXPECTED_PROMPT
    prompt.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / EXPECTED_PROMPT, prompt)
    packet = tmp_path / ".runtime/phase-3/triple-aaa-verify.json"
    packet.parent.mkdir(parents=True, exist_ok=True)
    packet.write_text(
        json.dumps(
            {
                "schema_version": "state-of-art-triple-aaa-verify.v2",
                "classification": "STATE_OF_ART_CANDIDATE",
                "exit_code": 2,
                "candidate": {
                    "commit_sha": "a" * 40,
                    "tree_sha": "b" * 40,
                    "checkout_fingerprint": "c" * 64,
                    "artifact_set_sha256": "d" * 64,
                },
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / ".runtime/phase-3/current-matrix.json"
    triple_aaa_capability_matrix.bind_to_packet(source, packet, output)
    bound = json.loads(output.read_text(encoding="utf-8"))
    packet_payload = json.loads(packet.read_text(encoding="utf-8"))
    packet_payload["current_capability_matrix"] = {
        "path": output.relative_to(tmp_path).as_posix(),
        "sha256": "0" * 64,
    }
    packet.write_text(json.dumps(packet_payload), encoding="utf-8")
    assert bound["rows"]

    result = validate(output, packet=packet)

    assert result["status"] == "FAIL"
    assert any("current_capability_matrix.sha256" in error for error in result["errors"])


def test_matrix_rejects_truncated_capability_set(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(triple_aaa_capability_matrix, "ROOT", tmp_path)
    source_payload = json.loads((ROOT / "docs/reports/triple-aaa-runtime-capability-matrix.json").read_text(encoding="utf-8"))
    source_payload["rows"] = source_payload["rows"][:1]
    source = tmp_path / "matrix.json"
    source.write_text(json.dumps(source_payload), encoding="utf-8")
    prompt = tmp_path / EXPECTED_PROMPT
    prompt.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / EXPECTED_PROMPT, prompt)

    result = validate(source)

    assert result["status"] == "FAIL"
    assert any("exactly" in error for error in result["errors"])


def test_matrix_rejects_promotable_row_without_runtime_and_independent_evidence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(triple_aaa_capability_matrix, "ROOT", tmp_path)
    source_payload = json.loads((ROOT / "docs/reports/triple-aaa-runtime-capability-matrix.json").read_text(encoding="utf-8"))
    source_payload["rows"][0]["STATE"] = "PROMOTABLE"
    source_payload["rows"][0]["RUNTIME_EVIDENCE"] = []
    source_payload["rows"][0]["INDEPENDENT_REVIEW"] = []
    source = tmp_path / "matrix.json"
    source.write_text(json.dumps(source_payload), encoding="utf-8")
    prompt = tmp_path / EXPECTED_PROMPT
    prompt.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / EXPECTED_PROMPT, prompt)

    result = validate(source)

    assert result["status"] == "FAIL"
    assert any("requires non-empty RUNTIME_EVIDENCE" in error for error in result["errors"])
