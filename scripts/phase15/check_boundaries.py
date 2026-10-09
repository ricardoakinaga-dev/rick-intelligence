#!/usr/bin/env python3
"""Validate the current root package boundary and retired-component policy.

This supersedes the Phase 1.1 skeleton check for the implemented root tree. It
uses Python's AST for imports, ignores tests and generated caches.

AUD07-02 retired `cvg-master-rag-v2`, `rick-professor` and `modulo-redis-locker`
from the checkout. The policy therefore inverts: those directories must stay
*absent* from the working tree (a restored copy would silently reintroduce the
superseded implementation), while their history must remain reachable so the
differential reference in `.runtime/legacy-reference/` can be rebuilt from a
commit SHA.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
LEGACY_PATHS = ("cvg-master-rag-v2", "rick-professor", "modulo-redis-locker")
ROOT_PACKAGES = ("contracts", "knowledge", "ingestion", "retrieval", "authorization", "identity", "providers", "locking", "professor")
FORBIDDEN_MODULE_PREFIXES = ("apps", "cvg_master_rag_v2", "modulo_redis_locker")


def _typescript_boundaries(root: Path) -> list[str]:
    sources = sorted(path for base in (root / "apps", root / "packages")
                     if base.is_dir() for path in base.rglob("*")
                     if path.suffix in {".ts", ".tsx", ".js", ".jsx"}
                     and not any(part in {"tests", "node_modules", ".next", "dist", "coverage"}
                                 or part.startswith(".next-") for part in path.parts))
    if not sources:
        return []
    if shutil.which("node") is None:
        return ["TypeScript boundary parser requires Node and npm ci in apps/web"]
    try:
        completed = subprocess.run(
            ["node", str(ROOT / "scripts/phase15/typescript_imports.cjs")],
            input=json.dumps([{"path": str(path.relative_to(root)), "source": path.read_text()}
                              for path in sources]),
            capture_output=True, text=True, timeout=30, check=False,
        )
        if completed.returncode:
            return ["TypeScript boundary parser failed; install the pinned apps/web dependencies"]
        results = json.loads(completed.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return ["TypeScript boundary parser did not produce valid evidence"]
    errors = []
    for result in results:
        relative = result["path"]
        errors.extend(f"{relative}: {error}" for error in result["errors"])
        allow_legacy = relative.startswith("apps/api/src/adapters/legacy/")
        for module in result["modules"]:
            parts = set(module.replace("\\", "/").split("/"))
            if not allow_legacy and (parts.intersection(LEGACY_PATHS)
                                     or module.replace("-", "_").startswith("legacy.")):
                errors.append(f"{relative}: legacy import {module}")
    return errors


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
    errors: list[str] = _typescript_boundaries(root)
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
    """The retired components must be absent from the tree, not absent from history."""
    errors: list[str] = []
    # The manifest is still a current consumer of the retirement decision.
    # Validate it as well as the tree so it cannot silently demand old snapshots.
    from scripts.phase11 import check_skeleton

    check_skeleton._check_preservation_manifest(errors)
    for component in LEGACY_PATHS:
        path = root / component
        if path.exists():
            errors.append(f"retired component restored into the working tree: {component}")
        code, commits, stderr = _git("log", "--oneline", "-1", "--", component)
        if code != 0:
            errors.append(f"cannot inspect history of retired component: {component} ({stderr})")
        elif not commits:
            errors.append(f"retired component has no recoverable history: {component}")
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


def main(argv: list[str] | None = None) -> int:
    """Run the full boundary policy, or only the retired-component policy.

    `--retired-only` is the CI hook used after long suites: a suite must not
    resurrect a retired component. It is the same predicate as the preservation
    half of this file, never a second implementation of the policy.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    unknown = [arg for arg in args if arg != "--retired-only"]
    if unknown:
        print(f"FAIL: unknown argument(s): {' '.join(unknown)}", file=sys.stderr)
        return 2
    if args == ["--retired-only"]:
        errors = check_preservation()
    else:
        errors = check_source_boundaries() + check_preservation() + check_root_package_layout()
    payload = {"status": "PASS" if not errors else "FAIL", "checked": str(ROOT), "errors": errors}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
