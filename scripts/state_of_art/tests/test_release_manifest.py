"""Tests for the strict typed release-evidence manifest."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.state_of_art import release_integrity
from scripts.state_of_art.release_manifest import (
    ArtifactFingerprint,
    CommitBinding,
    EvidenceRef,
    GateResult,
    REQUIRED_GATES,
    ReleaseEvidenceManifest,
    ReviewerRef,
    artifact_set_digest,
)
from scripts.state_of_art.runtime_preflight import (
    REQUIRED_SERVICES,
    build_preflight,
    canonical_compose_project,
    write_preflight,
)


class ReleaseManifestTests(unittest.TestCase):
    HEAD = "a" * 40
    TREE = "c" * 40
    CHECKOUT = "b" * 64

    def _fixture(self, directory: str, *, gate_result: str = "PASS", status: str = "PASS") -> tuple[Path, dict[str, object]]:
        root = Path(directory)
        observed_at = datetime.now(timezone.utc).isoformat()
        artifact_path = root / "artifact.txt"
        evidence_path = root / "evidence.md"
        artifact_path.write_text("artifact-v1\n", encoding="utf-8")
        evidence_path.write_text("evidence-v1\n", encoding="utf-8")
        artifact = ArtifactFingerprint(
            path="artifact.txt",
            sha256=sha256(artifact_path.read_bytes()).hexdigest(),
            role="candidate-source",
        )
        reviewer = ReviewerRef(
            reviewer_id="automated-release-integrity",
            kind="automated",
            name="release-integrity-generator",
            independent=False,
        )
        independent_reviewer = ReviewerRef(
            reviewer_id="independent-fixture-reviewer",
            kind="independent",
            name="Independent fixture reviewer",
            independent=True,
        )
        evidence = EvidenceRef(
            path="evidence.md",
            sha256=sha256(evidence_path.read_bytes()).hexdigest(),
            description="fixture evidence",
        )
        runtime_refs: dict[str, EvidenceRef] = {}
        runtime_dir = root / ".runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        checkout_snapshot = {
            "available": True,
            "head": self.HEAD,
            "tree": self.TREE,
            "fingerprint": self.CHECKOUT,
            "status": "CLEAN",
        }
        compose_path = root / "docker-compose.dev.yml"
        compose_path.write_text("services:\n", encoding="utf-8")
        compose_project = canonical_compose_project(root, "docker-compose.dev.yml")
        preflight = build_preflight(
            run_id="run-release-fixture-12345678",
            target_id=f"phase3-compose:{compose_project}:docker-compose.dev.yml",
            compose_file="docker-compose.dev.yml",
            compose_project=compose_project,
            compose_config_sha256="d" * 64,
            compose_source_sha256=sha256(compose_path.read_bytes()).hexdigest(),
            required_services=[
                {"name": name, "state": "running", "health": "healthy", "ready": True}
                for name in REQUIRED_SERVICES
            ],
            required_service_names=REQUIRED_SERVICES,
            endpoints=[
                {
                    "name": "api-readiness",
                    "url": "http://127.0.0.1:18000/health/ready",
                    "status": "PASS",
                    "reachable": True,
                    "http_status": 200,
                    "verified_at": observed_at,
                },
                {
                    "name": "web-readiness",
                    "url": "http://127.0.0.1:13000/login",
                    "status": "PASS",
                    "reachable": True,
                    "http_status": 200,
                    "verified_at": observed_at,
                },
            ],
            checkout=checkout_snapshot,
            generated_at=datetime.fromisoformat(observed_at),
        )
        preflight_hash = write_preflight(root, ".runtime/phase-3/preflight.json", preflight)
        for runtime_gate_id in REQUIRED_GATES:
            if runtime_gate_id == "release-integrity":
                continue
            runtime_relative = f".runtime/{runtime_gate_id}.json"
            runtime_target = root / runtime_relative
            raw_relative = f".runtime/raw-{runtime_gate_id}.json"
            raw_target = root / raw_relative
            raw_exit_status = (
                0
                if gate_result == "PASS"
                else 1
                if gate_result in {"FAIL", "STALE", "INVALID"}
                else 2
                if gate_result == "BLOCKED_EXTERNAL"
                else None
            )
            raw_target.write_text(
                json.dumps(
                    {
                        "schema_version": "fixture-runtime-gate.v1",
                        "gate_id": runtime_gate_id,
                        "status": gate_result,
                        "exit_status": raw_exit_status,
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            raw_hash = sha256(raw_target.read_bytes()).hexdigest()
            runtime_target.write_text(
                json.dumps(
                    {
                        "schema_version": "state-of-art-runtime-evidence.v1",
                        "record_id": f"fixture-{runtime_gate_id}",
                        "capability_id": runtime_gate_id,
                        "status": gate_result,
                        "exit_status": (
                            0
                            if gate_result == "PASS"
                            else 1
                            if gate_result in {"FAIL", "STALE", "INVALID"}
                            else 2
                            if gate_result == "BLOCKED_EXTERNAL"
                            else None
                        ),
                        "commit_sha": self.HEAD,
                        "tree_sha": self.TREE,
                        "checkout_fingerprint": self.CHECKOUT,
                        "checkout_available": True,
                        "checkout_sentinel": {
                            "before": checkout_snapshot,
                            "after": checkout_snapshot,
                            "unchanged": True,
                        },
                        "clean_worktree": True,
                        "production_safe": gate_result == "PASS",
                        "preflight_path": ".runtime/phase-3/preflight.json",
                        "preflight_sha256": preflight_hash,
                        "preflight": {
                            "status": "PASS",
                            "path": ".runtime/phase-3/preflight.json",
                            "sha256": preflight_hash,
                            "run_id": preflight["run_id"],
                            "target_id": preflight["target_id"],
                            "compose_file": preflight["compose_file"],
                            "compose_project": preflight["compose_project"],
                            "compose_config_sha256": preflight["compose_config_sha256"],
                            "compose_source_sha256": preflight["compose_source_sha256"],
                            "unchanged": True,
                        },
                        "procedure": f"fixture runtime procedure for {runtime_gate_id}",
                        "environment": "fixture",
                        "limitations": ["fixture is not a production run"],
                        "next_action": "replace fixture with an approved runtime observation",
                        "observed_at": observed_at,
                        "freshness": "CURRENT",
                        "artifact_sha256": raw_hash,
                        "raw_artifacts": [
                            {
                                "description": "fixture raw gate result",
                                "path": raw_relative,
                                "sha256": raw_hash,
                            }
                        ],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            runtime_refs[runtime_gate_id] = EvidenceRef(
                path=runtime_relative,
                sha256=sha256(runtime_target.read_bytes()).hexdigest(),
                description=f"fixture runtime envelope for {runtime_gate_id}",
            )
        gate_exit_status = {
            "PASS": 0,
            "BLOCKED_EXTERNAL": 2,
            "FAIL": 1,
            "STALE": 1,
            "INVALID": 1,
            "NOT_RUN": None,
        }[gate_result]
        gates = tuple(
            GateResult(
                gate_id=gate_id,
                commit_sha=self.HEAD,
                tree_sha=self.TREE,
                artifact_hash=artifact_set_digest((artifact,)),
                command=(
                    ("git", "diff", "--check", "&&", "make", "validate")
                    if gate_id == "release-integrity"
                    else ("runtime-envelope", f".runtime/{gate_id}.json")
                ),
                procedure=(
                    "run git diff --check and make validate against the exact checkout"
                    if gate_id == "release-integrity"
                    else f"validate runtime envelope for {gate_id} against the fixture checkout"
                ),
                environment="test",
                timestamp=observed_at,
                exit_status=gate_exit_status,
                result=gate_result,  # type: ignore[arg-type]
                limitations=("fixture is not a production run",) if gate_result != "PASS" else (),
                reviewer=independent_reviewer if gate_id == "independent-reviews" else reviewer,
                evidence_paths=(evidence,) if gate_id == "release-integrity" else (runtime_refs[gate_id],),
            )
            for gate_id in REQUIRED_GATES
        )
        manifest = ReleaseEvidenceManifest(
            schema_version="state-of-art-release-evidence.v2",
            manifest_id="fixture-manifest",
            generated_at=observed_at,
            status=status,  # type: ignore[arg-type]
            commit_binding=CommitBinding(
                commit_sha=self.HEAD,
                tree_sha=self.TREE,
                checkout_fingerprint=self.CHECKOUT,
                artifact_set_sha256=artifact_set_digest((artifact,)),
                clean_worktree=True,
            ),
            artifacts=(artifact,),
            gates=gates,
            reviewers=(reviewer, independent_reviewer),
            limitations=("fixture only",),
        )
        path = root / "release-evidence.json"
        path.write_text(json.dumps(manifest.to_dict()), encoding="utf-8")
        checkout = {
            "available": True,
            "head": self.HEAD,
            "tree": self.TREE,
            "fingerprint": self.CHECKOUT,
            "status": "CLEAN",
            "errors": [],
        }
        return path, checkout

    def test_typed_manifest_validates_artifact_and_evidence_hashes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(directory)
            result = release_integrity.evaluate_evidence(path, checkout, root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.PASS)

    def test_wrong_artifact_bytes_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(directory)
            (Path(directory) / "artifact.txt").write_text("tampered\n", encoding="utf-8")
            result = release_integrity.evaluate_evidence(path, checkout, root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("artifact hash does not match", result["reason"])

    def test_missing_checkout_tree_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(directory)
            checkout.pop("tree")
            result = release_integrity.evaluate_evidence(path, checkout, root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("checkout tree", result["reason"])

    def test_unavailable_checkout_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(directory)
            checkout["available"] = False
            checkout["errors"] = ["git status unavailable"]
            result = release_integrity.evaluate_evidence(path, checkout, root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("checkout identity is unavailable", result["reason"])

    def test_stale_manifest_timestamps_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(directory)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["generated_at"] = "2000-01-01T00:00:00+00:00"
            payload["gates"][0]["timestamp"] = "2000-01-01T00:00:00+00:00"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = release_integrity.evaluate_evidence(path, checkout, root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("current evidence window", result["reason"])

    def test_missing_mandatory_gate_set_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(directory)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["gates"] = payload["gates"][:-1]
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = release_integrity.evaluate_evidence(path, checkout, root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("missing mandatory gate results", result["reason"])

    def test_conflicting_evidence_aliases_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(directory)
            payload = json.loads(path.read_text(encoding="utf-8"))
            architecture = next(
                gate for gate in payload["gates"] if gate["gate_id"] == "architecture"
            )
            architecture["evidence_path"] = []
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = release_integrity.evaluate_evidence(path, checkout, root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("evidence_path and", result["reason"])

    def test_manifest_status_must_match_gate_aggregate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(
                directory,
                gate_result="BLOCKED_EXTERNAL",
                status="PASS",
            )
            result = release_integrity.evaluate_evidence(path, checkout, root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn(
            "manifest status PASS does not match mandatory gate aggregate BLOCKED_EXTERNAL",
            result["reason"],
        )

    def test_gate_reviewer_must_match_declared_reviewer(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(directory)
            payload = json.loads(path.read_text(encoding="utf-8"))
            architecture = next(
                gate for gate in payload["gates"] if gate["gate_id"] == "architecture"
            )
            architecture["reviewer"]["name"] = "spoofed reviewer identity"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = release_integrity.evaluate_evidence(path, checkout, root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("reviewer identity does not match", result["reason"])

    def test_WRONG_HASH_REJECTED(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(directory)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["gates"][0]["artifact_hash"] = "d" * 64
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = release_integrity.evaluate_evidence(path, checkout, root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("bound to the wrong artifact hash", result["reason"])
        self.assertIn("WRONG_HASH_REJECTED", result["rejection_codes"])

    def test_STALE_RELEASE_EVIDENCE_REJECTED(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(directory, gate_result="STALE", status="FAIL")
            result = release_integrity.evaluate_evidence(path, checkout, root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("architecture=STALE", result["reason"])
        self.assertIn("STALE_RELEASE_EVIDENCE_REJECTED", result["rejection_codes"])

    def test_missing_referenced_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(directory)
            (Path(directory) / "evidence.md").unlink()
            result = release_integrity.evaluate_evidence(path, checkout, root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("referenced file is absent", result["reason"])

    def test_blocked_gate_cannot_be_reported_as_pass(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(directory, gate_result="BLOCKED_EXTERNAL", status="BLOCKED_EXTERNAL")
            result = release_integrity.evaluate_evidence(path, checkout, root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.BLOCKED_EXTERNAL)
        self.assertIn("manifest status is BLOCKED_EXTERNAL", result["reason"])
        self.assertIn("BLOCKED_RUNTIME_REJECTED", result["rejection_codes"])

    def test_wrong_commit_binding_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(directory)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["commit_binding"]["commit_sha"] = "d" * 40
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = release_integrity.evaluate_evidence(path, checkout, root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("commit binding does not match", result["reason"])

    def test_wrong_gate_tree_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(directory)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["gates"][0]["tree_sha"] = "d" * 40
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = release_integrity.evaluate_evidence(path, checkout, root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("wrong tree", result["reason"])
        self.assertIn("WRONG_TREE_REJECTED", result["rejection_codes"])

    def test_missing_gate_exit_status_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(directory)
            payload = json.loads(path.read_text(encoding="utf-8"))
            del payload["gates"][0]["exit_status"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = release_integrity.evaluate_evidence(path, checkout, root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("exit_status is required", result["reason"])

    def test_independent_review_cannot_self_promote(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(directory)
            payload = json.loads(path.read_text(encoding="utf-8"))
            for gate in payload["gates"]:
                if gate["gate_id"] == "independent-reviews":
                    gate["reviewer"] = {
                        "reviewer_id": "automated-release-integrity",
                        "kind": "automated",
                        "name": "release-integrity-generator",
                        "independent": False,
                    }
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = release_integrity.evaluate_evidence(path, checkout, root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("SELF_PROMOTED_GATE_REJECTED", result["rejection_codes"])

    def test_WRONG_COMMIT_EVIDENCE_REJECTED(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(directory)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["gates"][0]["commit_sha"] = "d" * 40
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = release_integrity.evaluate_evidence(path, checkout, root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("bound to the wrong commit", result["reason"])
        self.assertIn("WRONG_COMMIT_EVIDENCE_REJECTED", result["rejection_codes"])

    def test_unapproved_command_procedure_cannot_claim_pass(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(directory)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["gates"][0]["command"] = ["false"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = release_integrity.evaluate_evidence(path, checkout, root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("not an approved", result["reason"])

    def test_runtime_pass_requires_a_bound_envelope(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(directory)
            payload = json.loads(path.read_text(encoding="utf-8"))
            architecture = next(
                gate for gate in payload["gates"] if gate["gate_id"] == "architecture"
            )
            architecture["command"] = ["runtime-envelope", "architecture"]
            architecture["evidence_paths"] = [
                {
                    "path": "evidence.md",
                    "sha256": sha256((Path(directory) / "evidence.md").read_bytes()).hexdigest(),
                    "description": "unbound plain-text evidence",
                }
            ]
            architecture["evidence_path"] = architecture["evidence_paths"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = release_integrity.evaluate_evidence(path, checkout, root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("PASS requires a safe .runtime", result["reason"])

    def test_runtime_pass_requires_production_safe_envelope(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(directory)
            runtime_path = Path(directory) / ".runtime/architecture.json"
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime["production_safe"] = False
            runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
            payload = json.loads(path.read_text(encoding="utf-8"))
            architecture = next(
                gate for gate in payload["gates"] if gate["gate_id"] == "architecture"
            )
            architecture["evidence_paths"][0]["sha256"] = sha256(
                runtime_path.read_bytes()
            ).hexdigest()
            architecture["evidence_path"] = architecture["evidence_paths"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = release_integrity.evaluate_evidence(path, checkout, root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("not production-safe", result["reason"])

    def test_runtime_pass_rejects_missing_shared_preflight(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(directory)
            (Path(directory) / ".runtime/phase-3/preflight.json").unlink()
            result = release_integrity.evaluate_evidence(path, checkout, root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("runtime preflight", result["reason"])

    def test_runtime_pass_rejects_mutated_shared_preflight_hash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(directory)
            runtime_path = Path(directory) / ".runtime/architecture.json"
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime["preflight_sha256"] = "e" * 64
            runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
            payload = json.loads(path.read_text(encoding="utf-8"))
            architecture = next(
                gate for gate in payload["gates"] if gate["gate_id"] == "architecture"
            )
            architecture["evidence_paths"][0]["sha256"] = sha256(
                runtime_path.read_bytes()
            ).hexdigest()
            architecture["evidence_path"] = architecture["evidence_paths"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = release_integrity.evaluate_evidence(path, checkout, root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("preflight hash", result["reason"])

    def test_ci_pass_requires_same_run_bound_raw_artifact(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(directory)
            root = Path(directory)
            ci_log = root / ".runtime/ci/architecture.log"
            ci_log.parent.mkdir(parents=True)
            ci_log.write_text("make validate: PASS\n", encoding="utf-8")
            ci_path = root / ".runtime/ci/architecture.json"
            ci_path.write_text(
                json.dumps(
                    {
                        "schema_version": "state-of-art-ci-evidence.v1",
                        "record_id": "CI-architecture-fixture",
                        "lane": "fast",
                        "gate_ids": ["architecture"],
                        "status": "PASS",
                        "exit_status": 0,
                        "exit_code": 0,
                        "commit_sha": self.HEAD,
                        "tree_sha": self.TREE,
                        "checkout_fingerprint": self.CHECKOUT,
                        "checkout_available": True,
                        "clean_worktree": True,
                        "freshness": "CURRENT",
                        "promotion_scope": "LOCAL_CI_ONLY",
                        "production_safe": False,
                        "procedure": "Execute the declared shell-free commands for CI lane fast and gates architecture",
                        "environment": "github-actions-local-ci",
                        "started_at": datetime.now(timezone.utc).isoformat(),
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "observed_at": datetime.now(timezone.utc).isoformat(),
                        "next_action": "Bind this local CI result to the complete release packet",
                        "limitations": ["local CI only"],
                        "run": {
                            "actions": True,
                            "event_name": "push",
                            "job": "fast",
                            "provider": "github-actions",
                            "repository": "example/rick-intelligence",
                            "ref": "refs/heads/main",
                            "run_attempt": "1",
                            "run_id": "12345",
                            "server_url": "https://github.com",
                            "sha": self.HEAD,
                            "workflow": "RICK canonical quality lanes",
                            "workflow_ref": "example/rick-intelligence/.github/workflows/quality.yml@refs/heads/main",
                        },
                        "commands": [
                            {
                                "argv": ["make", "validate"],
                                "duration_ms": 10,
                                "exit_status": 0,
                                "index": 1,
                                "output_truncated": False,
                                "status": "PASS",
                            }
                        ],
                        "raw_artifacts": [
                            {
                                "description": "bounded command output",
                                "path": ".runtime/ci/architecture.log",
                                "sha256": sha256(ci_log.read_bytes()).hexdigest(),
                            }
                        ],
                        "artifact_sha256": sha256(ci_log.read_bytes()).hexdigest(),
                        "checkout_sentinel": {
                            "before": {
                                "available": True,
                                "head": self.HEAD,
                                "tree": self.TREE,
                                "fingerprint": self.CHECKOUT,
                                "status": "CLEAN",
                            },
                            "after": {
                                "available": True,
                                "head": self.HEAD,
                                "tree": self.TREE,
                                "fingerprint": self.CHECKOUT,
                                "status": "CLEAN",
                            },
                            "unchanged": True,
                        },
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            ci_hash = sha256(ci_path.read_bytes()).hexdigest()
            payload = json.loads(path.read_text(encoding="utf-8"))
            architecture = next(
                gate for gate in payload["gates"]
                if gate["gate_id"] == "architecture"
            )
            architecture["command"] = ["ci-envelope", ".runtime/ci/architecture.json"]
            architecture["procedure"] = "validate the supplied same-run CI envelope for architecture against this checkout"
            architecture["evidence_paths"] = [
                {
                    "description": "same-run CI envelope for architecture",
                    "path": ".runtime/ci/architecture.json",
                    "sha256": ci_hash,
                }
            ]
            architecture["evidence_path"] = architecture["evidence_paths"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "GITHUB_RUN_ID": "12345",
                    "GITHUB_RUN_ATTEMPT": "1",
                    "GITHUB_REPOSITORY": "example/rick-intelligence",
                    "GITHUB_WORKFLOW": "RICK canonical quality lanes",
                    "GITHUB_WORKFLOW_REF": "example/rick-intelligence/.github/workflows/quality.yml@refs/heads/main",
                    "GITHUB_EVENT_NAME": "push",
                    "GITHUB_REF": "refs/heads/main",
                    "GITHUB_SHA": self.HEAD,
                },
            ):
                result = release_integrity.evaluate_evidence(path, checkout, root=root)

        self.assertEqual(result["classification"], release_integrity.PASS)

    def test_ci_pass_rejects_production_safe_claim(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-manifest-") as directory:
            path, checkout = self._fixture(directory)
            root = Path(directory)
            ci_log = root / ".runtime/ci/architecture.log"
            ci_log.parent.mkdir(parents=True)
            ci_log.write_text("pass\n", encoding="utf-8")
            ci_path = root / ".runtime/ci/architecture.json"
            envelope = {
                "schema_version": "state-of-art-ci-evidence.v1",
                "status": "PASS",
                "exit_status": 0,
                "exit_code": 0,
                "gate_ids": ["architecture"],
                "commit_sha": self.HEAD,
                "tree_sha": self.TREE,
                "checkout_fingerprint": self.CHECKOUT,
                "checkout_available": True,
                "clean_worktree": True,
                "freshness": "CURRENT",
                "promotion_scope": "LOCAL_CI_ONLY",
                "production_safe": True,
                "procedure": "validate architecture CI envelope",
                "environment": "github-actions-local-ci",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "run": {
                    "actions": True,
                    "workflow": "workflow",
                    "job": "architecture",
                    "run_id": "12345",
                    "repository": "example/rick-intelligence",
                    "event_name": "push",
                    "sha": self.HEAD,
                },
                "commands": [{"argv": ["make", "validate"], "status": "PASS", "exit_status": 0}],
                "raw_artifacts": [
                    {
                        "path": ".runtime/ci/architecture.log",
                        "sha256": sha256(ci_log.read_bytes()).hexdigest(),
                    }
                ],
                "artifact_sha256": sha256(ci_log.read_bytes()).hexdigest(),
                "limitations": ["fixture"],
                "next_action": "review",
                "checkout_sentinel": {"unchanged": True},
            }
            ci_path.write_text(json.dumps(envelope), encoding="utf-8")
            payload = json.loads(path.read_text(encoding="utf-8"))
            architecture = next(gate for gate in payload["gates"] if gate["gate_id"] == "architecture")
            architecture["command"] = ["ci-envelope", ".runtime/ci/architecture.json"]
            architecture["procedure"] = "validate architecture CI envelope"
            architecture["evidence_paths"] = [
                {
                    "description": "CI envelope",
                    "path": ".runtime/ci/architecture.json",
                    "sha256": sha256(ci_path.read_bytes()).hexdigest(),
                }
            ]
            architecture["evidence_path"] = architecture["evidence_paths"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = release_integrity.evaluate_evidence(path, checkout, root=root)

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("must not claim production safety", result["reason"])


if __name__ == "__main__":
    unittest.main()
