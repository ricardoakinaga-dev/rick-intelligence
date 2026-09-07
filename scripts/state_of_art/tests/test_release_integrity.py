"""Focused tests for the dependency-free release-integrity gate."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.state_of_art import release_integrity


class ReleaseIntegrityTests(unittest.TestCase):
    HEAD = "a" * 40
    FINGERPRINT = "b" * 64

    def _checkout(self) -> dict[str, object]:
        return {
            "available": True,
            "head": self.HEAD,
            "fingerprint": self.FINGERPRINT,
            "status": "CLEAN",
        }

    def _write_evidence(self, directory: str, payload: dict[str, object]) -> Path:
        path = Path(directory) / "release-evidence.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _valid_payload(self) -> dict[str, object]:
        return {
            "schema_version": "release-evidence.v1",
            "HEAD": self.HEAD,
            "fingerprint": {"checkout": f"sha256:{self.FINGERPRINT}"},
            "status": "PASS",
            "checks": [
                {
                    "id": "hermetic",
                    "required": True,
                    "classification": "PASS",
                    "command": ["python3", "-m", "unittest"],
                }
            ],
            "live_production": {
                "required": False,
                "classification": "NOT_RUN",
                "claim": False,
            },
        }

    def test_current_evidence_passes_while_optional_live_evidence_is_not_run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-integrity-") as directory:
            path = self._write_evidence(directory, self._valid_payload())
            result = release_integrity.evaluate_evidence(path, self._checkout(), root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.PASS)
        self.assertTrue(any("optional evidence was not run" in warning for warning in result["warnings"]))

    def test_missing_evidence_is_not_run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-integrity-") as directory:
            path = Path(directory) / "missing.json"
            result = release_integrity.evaluate_evidence(path, self._checkout(), root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.NOT_RUN)

    def test_required_not_run_is_not_run(self) -> None:
        payload = self._valid_payload()
        payload["checks"] = [
            {
                "id": "required-runtime",
                "required": True,
                "classification": "NOT_RUN",
            }
        ]
        with tempfile.TemporaryDirectory(prefix="release-integrity-") as directory:
            path = self._write_evidence(directory, payload)
            result = release_integrity.evaluate_evidence(path, self._checkout(), root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.NOT_RUN)

    def test_head_mismatch_rejects_evidence_as_fail(self) -> None:
        payload = self._valid_payload()
        payload["HEAD"] = "c" * 40
        with tempfile.TemporaryDirectory(prefix="release-integrity-") as directory:
            path = self._write_evidence(directory, payload)
            result = release_integrity.evaluate_evidence(path, self._checkout(), root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("HEAD does not match", result["reason"])

    def test_fingerprint_mismatch_rejects_evidence_as_fail(self) -> None:
        payload = self._valid_payload()
        payload["fingerprint"] = {"checkout": "sha256:" + "c" * 64}
        with tempfile.TemporaryDirectory(prefix="release-integrity-") as directory:
            path = self._write_evidence(directory, payload)
            result = release_integrity.evaluate_evidence(path, self._checkout(), root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("fingerprint does not match", result["reason"])

    def test_stale_classification_rejects_evidence_as_fail(self) -> None:
        payload = self._valid_payload()
        payload["checks"] = [
            {
                "id": "old-check",
                "required": True,
                "classification": "STALE",
            }
        ]
        with tempfile.TemporaryDirectory(prefix="release-integrity-") as directory:
            path = self._write_evidence(directory, payload)
            result = release_integrity.evaluate_evidence(path, self._checkout(), root=Path(directory))

        self.assertEqual(result["classification"], release_integrity.FAIL)
        self.assertIn("stale", result["reason"])

    def test_worktree_sentinel_rejects_mutation_and_dirty_release_checkout(self) -> None:
        before = {
            "available": True,
            "fingerprint": "1" * 64,
            "status": "CLEAN",
        }
        after = {**before, "fingerprint": "2" * 64}
        mutated = release_integrity.classify_worktree_sentinel(before, after, require_clean=True)
        self.assertEqual(mutated["classification"], release_integrity.FAIL)
        self.assertTrue(mutated["mutated"])

        dirty = {**before, "status": "DIRTY"}
        dirty_result = release_integrity.classify_worktree_sentinel(dirty, dirty, require_clean=True)
        self.assertEqual(dirty_result["classification"], release_integrity.FAIL)
        self.assertFalse(dirty_result["mutated"])

    def test_overall_not_run_is_blocking_only_for_required_criteria(self) -> None:
        self.assertEqual(
            release_integrity._overall_classification(
                [
                    {"classification": release_integrity.PASS, "required": True},
                    {"classification": release_integrity.NOT_RUN, "required": False},
                ]
            ),
            release_integrity.PASS,
        )
        self.assertEqual(
            release_integrity._overall_classification(
                [
                    {"classification": release_integrity.PASS, "required": True},
                    {"classification": release_integrity.NOT_RUN, "required": True},
                ]
            ),
            release_integrity.NOT_RUN,
        )


if __name__ == "__main__":
    unittest.main()
