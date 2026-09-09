"""Tests for the strict typed release-evidence manifest."""

from __future__ import annotations

from hashlib import sha256
import json
import tempfile
import unittest
from pathlib import Path

from scripts.state_of_art import release_integrity
from scripts.state_of_art.release_manifest import (
    ArtifactFingerprint,
    CommitBinding,
    EvidenceRef,
    GateResult,
    ReleaseEvidenceManifest,
    ReviewerRef,
    artifact_set_digest,
)


class ReleaseManifestTests(unittest.TestCase):
    HEAD = "a" * 40
    TREE = "c" * 40
    CHECKOUT = "b" * 64

    def _fixture(self, directory: str, *, gate_result: str = "PASS", status: str = "PASS") -> tuple[Path, dict[str, object]]:
        root = Path(directory)
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
        evidence = EvidenceRef(
            path="evidence.md",
            sha256=sha256(evidence_path.read_bytes()).hexdigest(),
            description="fixture evidence",
        )
        gate = GateResult(
            gate_id="fixture-gate",
            commit_sha=self.HEAD,
            artifact_hash=artifact_set_digest((artifact,)),
            command=("fixture", "gate"),
            environment="test",
            timestamp="2026-09-09T12:00:00+00:00",
            result=gate_result,  # type: ignore[arg-type]
            limitations=("fixture is not a production run",) if gate_result != "PASS" else (),
            reviewer=reviewer,
            evidence_paths=(evidence,),
        )
        manifest = ReleaseEvidenceManifest(
            schema_version="state-of-art-release-evidence.v2",
            manifest_id="fixture-manifest",
            generated_at="2026-09-09T12:00:00+00:00",
            status=status,  # type: ignore[arg-type]
            commit_binding=CommitBinding(
                commit_sha=self.HEAD,
                tree_sha=self.TREE,
                checkout_fingerprint=self.CHECKOUT,
                artifact_set_sha256=artifact_set_digest((artifact,)),
                clean_worktree=True,
            ),
            artifacts=(artifact,),
            gates=(gate,),
            reviewers=(reviewer,),
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
            path, checkout = self._fixture(directory, gate_result="STALE")
            result = release_integrity.evaluate_evidence(path, checkout, root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("fixture-gate=STALE", result["reason"])
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

        self.assertEqual(result["classification"], release_integrity.FAIL)
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


if __name__ == "__main__":
    unittest.main()
