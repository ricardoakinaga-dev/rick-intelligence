"""Unit tests for the current root boundary validator."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.phase15 import check_boundaries


class BoundaryValidatorTests(unittest.TestCase):
    def test_typescript_imports_reject_legacy_but_ignore_comments_and_copy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aud03-ts-boundary-") as temporary:
            root = Path(temporary)
            source = root / "apps/web/components/bad.tsx"
            source.parent.mkdir(parents=True)
            source.write_text("import type { X } from '../../../rick-professor/src/x';\n")
            self.assertTrue(any("legacy" in e for e in check_boundaries.check_source_boundaries(root)))
            source.write_text("// import x from 'rick-professor';\nconst text = 'rick-professor/src';\nexport const X = () => <div>{text}</div>;\n")
            self.assertEqual(check_boundaries.check_source_boundaries(root), [])

    def test_typescript_export_and_dynamic_import_are_checked(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aud03-ts-export-") as temporary:
            root = Path(temporary)
            source = root / "packages/sample/src/bad.ts"
            source.parent.mkdir(parents=True)
            for statement in ("export * from 'cvg-master-rag-v2';", "const x = import('modulo-redis-locker');", "const x = require('rick-professor');"):
                source.write_text(statement)
                self.assertTrue(any("legacy" in e for e in check_boundaries.check_source_boundaries(root)), statement)

    def test_typescript_import_type_nodes_are_checked(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aud03-ts-type-") as temporary:
            root = Path(temporary)
            source = root / "packages/sample/src/types.ts"
            source.parent.mkdir(parents=True)
            for statement in (
                "type X = import('rick-professor').X;",
                "type X = typeof import('cvg-master-rag-v2');",
                "type X<T> = Promise<import('modulo-redis-locker').X<T>>;",
            ):
                source.write_text(statement)
                self.assertTrue(any("legacy" in e for e in check_boundaries.check_source_boundaries(root)), statement)
            source.write_text("type X = import('typescript').CompilerOptions;\nconst text = \"import('rick-professor')\";")
            self.assertEqual(check_boundaries.check_source_boundaries(root), [])

    def test_ast_rejects_forbidden_app_imports_but_allows_canonical_professor(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase15-boundary-") as temporary:
            root = Path(temporary)
            source = root / "packages" / "sample" / "src" / "bad.py"
            source.parent.mkdir(parents=True)
            source.write_text("from apps.api import app\nfrom rick_professor import orchestrate\n", encoding="utf-8")
            errors = check_boundaries.check_source_boundaries(root)
            self.assertTrue(any("forbidden import apps.api" in error for error in errors))
            self.assertFalse(any("rick_professor" in error for error in errors))

    def test_preserved_path_reference_is_rejected_only_in_production_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase15-legacy-") as temporary:
            root = Path(temporary)
            source = root / "apps" / "api" / "src" / "services" / "bad.py"
            source.parent.mkdir(parents=True)
            source.write_text('path = "rick-professor/src"\n', encoding="utf-8")
            errors = check_boundaries.check_source_boundaries(root)
            self.assertTrue(any("preserved path reference rick-professor" in error for error in errors))

    def test_tests_are_not_treated_as_production_imports(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase15-tests-") as temporary:
            root = Path(temporary)
            source = root / "packages" / "sample" / "tests" / "test_boundary.py"
            source.parent.mkdir(parents=True)
            source.write_text("from apps.api import app\n", encoding="utf-8")
            self.assertEqual(check_boundaries.check_source_boundaries(root), [])


if __name__ == "__main__":
    unittest.main()
