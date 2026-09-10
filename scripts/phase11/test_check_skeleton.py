#!/usr/bin/env python3
"""Regression tests for the Phase 1.1 structural and boundary validator."""

from __future__ import annotations

import tempfile
import unittest
from unittest import mock
from pathlib import Path

from scripts.phase11 import check_skeleton


class SkeletonValidatorTests(unittest.TestCase):
    def test_preservation_policy_allows_clean_root_checkouts(self) -> None:
        manifest = check_skeleton._load_json(check_skeleton.PRESERVATION_MANIFEST, [])

        self.assertEqual(manifest["schema_version"], "phase-1.1-preserved-components.v1")
        self.assertEqual(
            manifest["policy"]["independent_git_metadata"],
            "validated_when_present",
        )
        self.assertTrue(manifest["policy"]["root_snapshot_required"])

    def test_strict_json_rejects_duplicate_manifest_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase11-json-boundary-") as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_text('{"schema_version":1,"schema_version":2}', encoding="utf-8")
            errors: list[str] = []

            with mock.patch.object(check_skeleton, "ROOT", path.parent):
                self.assertEqual(check_skeleton._load_json(path, errors), {})
            self.assertTrue(any("invalid JSON" in error for error in errors))

    def test_root_snapshot_is_required_even_with_nested_git_metadata(self) -> None:
        with mock.patch.object(
            check_skeleton,
            "_git",
            return_value=(0, "rick-professor\n", ""),
        ):
            self.assertTrue(check_skeleton._root_snapshot_contains("rick-professor"))
            self.assertFalse(check_skeleton._root_snapshot_contains("cvg-master-rag-v2"))

    def test_rejects_package_source_that_reaches_a_legacy_component(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase11-boundary-") as temporary:
            root = Path(temporary)
            source = root / "packages" / "retrieval" / "bad.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'legacy_adapter = "rick-professor/compat"\n',
                encoding="utf-8",
            )

            errors: list[str] = []
            scanned = check_skeleton._check_source_boundaries(
                {
                    "forbidden_imports": [
                        {
                            "rule_id": "PKG-NO-LEGACY",
                            "scope": "packages/**",
                            "patterns": ["rick-professor/"],
                        }
                    ]
                },
                errors,
                root=root,
            )

            self.assertEqual(scanned, 1)
            self.assertTrue(any("PKG-NO-LEGACY" in error for error in errors))

    def test_allows_non_source_placeholders_to_remain_unscanned(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase11-placeholder-") as temporary:
            root = Path(temporary)
            readme = root / "packages" / "retrieval" / "README.md"
            readme.parent.mkdir(parents=True)
            readme.write_text("Placeholder\n", encoding="utf-8")

            errors: list[str] = []
            scanned = check_skeleton._check_source_boundaries(
                {"forbidden_imports": []},
                errors,
                root=root,
            )

            self.assertEqual(scanned, 0)
            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
