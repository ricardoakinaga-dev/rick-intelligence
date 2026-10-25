from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from scripts.phase11.local_product_probe import ProbeBlocked, check_authority, local_target, trace_observation
from scripts.phase11 import local_product_probe
from scripts.phase11 import check_compose
from scripts.phase11.local_lab_environment import replace_url_host
from scripts.state_of_art import prepare_phase3_handoff as handoff


def settings(**overrides):
    return SimpleNamespace(**{
        "environment": "dev", "external_database_dsn": "postgresql://u:p@127.0.0.1/db",
        "redis_url": "redis://127.0.0.1:6379", "qdrant_url": "http://127.0.0.1:6333",
        "object_store_endpoint": "http://127.0.0.1:9000", "provider_base_url": "http://127.0.0.1:58000",
        "embedding_base_url": "", **overrides,
    })


@pytest.mark.parametrize("target", ["http://example.com", "http://0.0.0.0:80", "file:///tmp/data",
                                    "http://169.254.169.254", "http://224.0.0.1", "http://[::]"])
def test_local_probe_rejects_remote_or_ambiguous_targets(target):
    assert not local_target(target)
    assert not local_target(target, allow_private=True)


def test_private_container_target_needs_explicit_opt_in():
    assert not local_target("http://172.21.0.4:9000")
    assert local_target("http://172.21.0.4:9000", allow_private=True)
    assert local_target("https://[::1]:9000")


def test_container_host_rewrite_preserves_credentials_and_parameters():
    assert replace_url_host("redis://default:redis-password@redis:6379/0?name=redis", "172.21.0.2") == (
        "redis://default:redis-password@172.21.0.2:6379/0?name=redis")
    assert replace_url_host("http://qdrant:6333", "::1") == "http://[::1]:6333"


def test_local_authority_does_not_authorize_production_or_paid_provider(monkeypatch):
    monkeypatch.delenv("RICK_LOCAL_PROBES_AUTHORIZED", raising=False)
    with pytest.raises(ProbeBlocked, match="authority_missing"):
        check_authority(settings())
    monkeypatch.setenv("RICK_LOCAL_PROBES_AUTHORIZED", "1")
    with pytest.raises(ProbeBlocked, match="refuses_production"):
        check_authority(settings(environment="production"))
    monkeypatch.delenv("RICK_LOCAL_PROVIDER_FIXTURE", raising=False)
    with pytest.raises(ProbeBlocked, match="fixture_required"):
        check_authority(settings())
    monkeypatch.setenv("RICK_LOCAL_PROVIDER_FIXTURE", "1")
    check_authority(settings())
    with pytest.raises(ProbeBlocked, match="local_service_targets"):
        check_authority(settings(embedding_base_url="https://provider.example/v1"))


@pytest.fixture
def envelope(tmp_path):
    now = datetime.now(timezone.utc)
    checkout = {"head": "a" * 40, "tree": "b" * 40, "fingerprint": "c" * 64, "status": "CLEAN"}
    raw = tmp_path / "raw.json"
    raw.write_text('{"status":"PASS"}')
    preflight = tmp_path / "preflight.json"
    preflight.write_text('{"status":"PASS"}')
    payload = {
        "schema_version": "state-of-art-runtime-evidence.v1", "status": "PASS", "exit_status": 0,
        "commit_sha": checkout["head"], "tree_sha": checkout["tree"],
        "checkout_fingerprint": checkout["fingerprint"], "clean_worktree": True,
        "observed_at": now.isoformat(), "production_safe": False,
        "reviewer": {"independent": False},
        "raw_artifacts": [{"path": "raw.json", "sha256": handoff.sha256(raw)}],
        "preflight": {"status": "PASS"}, "preflight_path": "preflight.json",
        "preflight_sha256": handoff.sha256(preflight),
    }
    return tmp_path, checkout, payload, now


def inspect_fixture(envelope):
    root, checkout, payload, now = envelope
    (root / "evidence.json").write_text(json.dumps(payload))
    return handoff.inspect_evidence(root, "evidence.json", checkout, now=now)


def test_local_pass_keeps_production_and_review_pending(envelope):
    row = inspect_fixture(envelope)
    assert row["observed_status"] == "PASS"
    assert row["issues"] == ["independent_review_required", "production_profile_required"]


@pytest.mark.parametrize("mutation,issue", [
    ({"commit_sha": "d" * 40}, "commit_sha_mismatch"),
    ({"tree_sha": "d" * 40}, "tree_sha_mismatch"),
    ({"checkout_fingerprint": "d" * 64}, "checkout_fingerprint_mismatch"),
    ({"clean_worktree": False}, "clean_candidate_required"),
    ({"raw_artifacts": []}, "raw_artifacts_missing"),
    ({"exit_status": False}, "runtime_not_pass"),
    ({"status": "BLOCKED_EXTERNAL"}, "runtime_not_pass"),
    ({"preflight": {"status": "FAIL"}}, "preflight_not_pass"),
])
def test_diagnostic_flags_invalid_release_evidence(envelope, mutation, issue):
    envelope[2].update(mutation)
    assert issue in inspect_fixture(envelope)["issues"]


@pytest.mark.parametrize("delta", [timedelta(days=-2), timedelta(hours=1)])
def test_stale_and_future_evidence_remain_blocking(envelope, delta):
    envelope[2]["observed_at"] = (envelope[3] + delta).isoformat()
    assert "stale_evidence" in inspect_fixture(envelope)["issues"]


def test_raw_and_preflight_tampering_are_visible(envelope):
    (envelope[0] / "raw.json").write_text('{"changed":true}')
    (envelope[0] / "preflight.json").write_text('{"changed":true}')
    issues = inspect_fixture(envelope)["issues"]
    assert "raw_artifact_hash_mismatch" in issues
    assert "preflight_hash_mismatch" in issues


@pytest.mark.parametrize("raw", ["../outside", "/tmp/outside", None, True, []])
def test_handoff_refuses_outside_paths(tmp_path, raw):
    with pytest.raises(ValueError):
        handoff.safe_file(tmp_path, raw)


def test_handoff_refuses_parent_symlink(tmp_path):
    (tmp_path / "link").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        handoff.safe_file(tmp_path, "link/missing.json")


def test_source_manifest_binds_untracked_file_bytes(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source = tmp_path / "new.py"
    source.write_text("first")
    first = handoff.source_manifest(tmp_path)
    source.write_text("second")
    second = handoff.source_manifest(tmp_path)
    assert first[0]["path"] == second[0]["path"] == "new.py"
    assert first[0]["sha256"] != second[0]["sha256"]


def test_preparation_cannot_create_release_approval(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    payload = handoff.prepare(tmp_path, evidence={})
    assert payload["status"] == "PREPARED_NO_GO"
    assert payload["promotable"] is False
    assert payload["signed"] is False
    assert payload["human_decision"] == "PENDING"
    assert payload["independent_review"] == "PENDING"


def test_handoff_binds_formal_runtime_and_raw_observations_without_promotion(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    base = tmp_path / ".runtime/phase-3/formal-local"
    base.mkdir(parents=True)
    report = base / "tenant-current.json"
    report.write_text(json.dumps({"status": "PASS", "run_id": "abc123"}))
    raw = base / "abc123/tenant-observations.json"
    raw.parent.mkdir()
    raw.write_text('{"closed":true}')
    payload = handoff.prepare(tmp_path, evidence={})
    observation, = payload["local_observations"]
    assert observation["observed_status"] == "PASS"
    assert observation["sha256"] == handoff.sha256(report)
    assert observation["raw_observations"] == [{"path": str(raw.relative_to(tmp_path)), "sha256": handoff.sha256(raw)}]
    assert observation["release_acceptance"] is False
    assert payload["promotable"] is False
    assert {row["id"] for row in payload["remaining_work"]} == {"tenant-timing", "golden-evaluation", "observability", "frontend"}


def test_handoff_exposes_tampered_trace_and_binds_verification_log(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    base = tmp_path / ".runtime/phase-3/formal-local"
    base.mkdir(parents=True)
    trace = base / "trace.json"
    trace.write_text('{"spans":[]}')
    ref = {"path": str(trace.relative_to(tmp_path)), "sha256": handoff.sha256(trace)}
    (base / "distributed.json").write_text(json.dumps({"status": "PASS", "raw_artifacts": [ref]}))
    log = base / "validate-final.log"
    log.write_text("PASS\n")
    trace.write_text('{"tampered":true}')
    payload = handoff.prepare(tmp_path, evidence={})
    row, = payload["local_observations"]
    assert row["raw_artifacts"][0]["hash_matches"] is False
    import hashlib
    expected = hashlib.sha256(json.dumps(payload["source_manifest"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert payload["source_manifest_sha256"] == expected
    assert payload["verification_artifacts"] == [{"path": str(log.relative_to(tmp_path)), "sha256": handoff.sha256(log)}]
    (base / "distributed.json").write_text(json.dumps({"raw_artifacts": [{"path": None}]}))
    invalid, = handoff.prepare(tmp_path, evidence={})["local_observations"]
    assert invalid["observed_status"] == "INVALID"


def test_embedding_dimensions_must_match_across_all_four_containers():
    payload = {"services": {name: {"environment": {"EMBEDDING_DIMENSION": "2"}}
                            for name in ("api", "worker", "worker-b", "qdrant-init")}}
    assert check_compose._validate_embedding_dimensions("fixture", payload) == []
    payload["services"]["api"]["environment"].pop("EMBEDDING_DIMENSION")
    assert "api: explicit EMBEDDING_DIMENSION" in check_compose._validate_embedding_dimensions("fixture", payload)[0]
    payload["services"]["api"]["environment"]["EMBEDDING_DIMENSION"] = "1536"
    assert "dimensions differ" in check_compose._validate_embedding_dimensions("fixture", payload)[0]


def test_trace_delivery_requires_same_trace_and_observed_parent_relationship():
    trace = "a" * 32
    root = {"traceID": trace, "spanID": "root", "operationName": "lab.product_probe"}
    child = {"traceID": trace, "spanID": "child", "operationName": "queue.enqueue",
             "references": [{"traceID": trace, "spanID": "root"}]}
    assert trace_observation({"data": [{"spans": [root, child]}]}, trace)["status"] == "PASS"
    assert trace_observation({"data": [{"spans": [root]}]}, trace)["status"] == "FAIL"
    assert trace_observation({"data": [{"spans": [root, child]}]}, "b" * 32)["status"] == "FAIL"


def test_local_probe_output_cannot_overwrite_source(tmp_path, monkeypatch):
    monkeypatch.setattr(local_product_probe, "ROOT", tmp_path)
    source = tmp_path / "Makefile"
    source.write_text("preserve source\n")
    with pytest.raises(SystemExit) as error:
        local_product_probe.main(["--output", "Makefile"])
    assert error.value.code == 2
    assert source.read_text() == "preserve source\n"
