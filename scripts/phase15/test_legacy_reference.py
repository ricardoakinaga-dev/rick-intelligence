"""Regression tests for the pinned-source legacy differential reference."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.phase15 import legacy_reference


class LegacyReferenceTests(unittest.TestCase):
    def test_pinned_source_is_resolvable_and_contains_the_component(self) -> None:
        sha = legacy_reference.resolve_ref(legacy_reference.SOURCE_REF)
        self.assertIsNotNone(sha)
        self.assertTrue(legacy_reference.component_in_ref(sha))

    def test_component_is_retired_from_head(self) -> None:
        self.assertIsNotNone(legacy_reference.resolve_ref("HEAD"))
        self.assertFalse(legacy_reference.component_in_ref("HEAD"))

    def test_check_reports_not_ready_before_materialization(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aud07-legacy-check-") as temporary:
            destination = Path(temporary) / "legacy-reference"
            self.assertEqual(
                legacy_reference.main(["--destination", str(destination), "--check"]), 1
            )

    def test_extract_materializes_from_the_pinned_source_then_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aud07-legacy-extract-") as temporary:
            destination = Path(temporary) / "legacy-reference"
            self.assertEqual(legacy_reference.extract(destination), 0)
            self.assertTrue((destination / legacy_reference.LEGACY_COMPONENT / "src").is_dir())
            source = legacy_reference.resolve_ref(legacy_reference.SOURCE_REF)
            self.assertEqual(legacy_reference._read_marker(destination), source)
            self.assertEqual(
                legacy_reference.main(["--destination", str(destination), "--check"]), 0
            )
            self.assertEqual(legacy_reference.extract(destination), 0)

    def test_unresolvable_source_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aud07-legacy-broken-") as temporary:
            original = legacy_reference.SOURCE_REF
            try:
                legacy_reference.SOURCE_REF = "aud07-missing-source-ref"
                self.assertEqual(
                    legacy_reference.extract(Path(temporary) / "legacy-reference"), 1
                )
                legacy_reference.SOURCE_REF = "HEAD"
                self.assertEqual(
                    legacy_reference.extract(Path(temporary) / "legacy-reference"), 2
                )
            finally:
                legacy_reference.SOURCE_REF = original


if __name__ == "__main__":
    unittest.main()
