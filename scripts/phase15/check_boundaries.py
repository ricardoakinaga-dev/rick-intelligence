#!/usr/bin/env python3
"""Validate the current root package boundary and legacy preservation policy.

This supersedes the Phase 1.1 skeleton check for the implemented root tree. It
uses Python's AST for imports, ignores tests and generated caches, and keeps
the preserved child repositories read-only.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LEGACY_PATHS = ("cvg-master-rag-v2", "rick-professor", "modulo-redis-locker")
ROOT_PACKAGES = ("contracts", "knowledge", "ingestion", "retrieval", "authorization", "identity", "providers", "locking", "professor")
FORBIDDEN_MODULE_PREFIXES = ("apps", "cvg_master_rag_v2", "modulo_redis_locker")


def _python_sources(root: Path) -> list[Path]:
    return sorted(
        path
        for base in (root / "apps", root / "packages")
        if base.is_dir()
        for path in base.rglob("*.py")
        if "tests" not in path.parts and "__pycache__" not in path.parts
    )


def _import_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def check_source_boundaries(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    for path in _python_sources(root):
        relative = path.relative_to(root).as_posix()
        allow_legacy = relative.startswith("apps/api/src/adapters/legacy/")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            errors.append(f"{relative}: cannot parse source ({type(exc).__name__})")
            continue
        for module in _import_modules(tree):
            normalized = module.replace("-", "_")
            if any(normalized == prefix or normalized.startswith(prefix + ".") for prefix in FORBIDDEN_MODULE_PREFIXES):
                errors.append(f"{relative}: forbidden import {module}")
            if normalized in {"rick_professor_legacy", "cvg", "modulo_redis_locker"}:
                errors.append(f"{relative}: legacy import {module}")
            if not allow_legacy and normalized.startswith("legacy."):
                errors.append(f"{relative}: legacy namespace import {module}")

        # Imports can be assembled through sys.path; reject only explicit
        # preserved filesystem paths outside the adapter boundary. This does
        # not substring-scan harmless prose or test fixtures.
        if not allow_legacy:
            text = path.read_text(encoding="utf-8")
            for marker in LEGACY_PATHS:
                if f"{marker}/" in text or f"{marker}\\" in text:
                    errors.append(f"{relative}: preserved path reference {marker}")
    return errors


def _git(*args: str) -> tuple[int, str, str]:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def check_preservation(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    for component in LEGACY_PATHS:
        path = root / component
        if not path.is_dir():
            errors.append(f"missing preserved component: {component}")
            continue
        code, snapshot, stderr = _git("ls-tree", "-d", "--name-only", "HEAD", "--", component)
        if code != 0 or component not in snapshot.splitlines():
            errors.append(f"preserved component absent from root snapshot: {component} ({stderr or snapshot})")
        code, changed, _ = _git("status", "--porcelain=v1", "--", component)
        if code != 0:
            errors.append(f"cannot inspect preserved component: {component}")
        elif changed:
            errors.append(f"preserved component has local changes: {component}")
    code, diff_check, stderr = _git("diff", "--check")
    if code != 0:
        errors.append(f"git diff --check failed: {stderr or diff_check}")
    return errors


def check_root_package_layout(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    for package in ROOT_PACKAGES:
        base = root / "packages" / package
        required = (base / "README.md", base / "pyproject.toml", base / "src")
        for path in required:
            if not path.exists():
                errors.append(f"missing root package artifact: {path.relative_to(root)}")
    return errors


def main() -> int:
    errors = check_source_boundaries() + check_preservation() + check_root_package_layout()
    payload = {"status": "PASS" if not errors else "FAIL", "checked": str(ROOT), "errors": errors}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
