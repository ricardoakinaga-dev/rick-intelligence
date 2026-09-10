#!/usr/bin/env python3
"""Validate the additive Phase 1.1 root skeleton and dependency contract.

This validator is deliberately independent of the Phase 0.6 promotion
checker. It proves structure and migration safety; it does not claim that the
future apps/packages or external services already exist.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

try:
    from scripts.state_of_art.json_boundary import load_json
except ModuleNotFoundError:  # Direct execution from the scripts/phase11 directory.
    sys.path.insert(0, str(ROOT))
    from scripts.state_of_art.json_boundary import load_json
BOUNDARIES = ROOT / "docs/architecture/dependency-boundaries.json"
PRESERVATION_MANIFEST = ROOT / "docs/architecture/preserved-components.json"

ROOT_FILES = (
    ".editorconfig",
    ".env.example",
    "CONTRIBUTING.md",
    "Makefile",
    "README.md",
    "toolchain.json",
    "docs/architecture/dependency-boundaries.json",
    "docs/architecture/dependency-boundaries.md",
    "docs/architecture/preserved-components.json",
    "docs/architecture/migration-map.md",
    "docs/architecture/target-system.md",
    "docs/architecture/toolchain.md",
    "docs/plans/phase-1.1-monorepo-skeleton.md",
    "docs/progress/phase-1.1-report.md",
    "docs/progress/phase-1.1-independent-review.md",
    ".agent/plans/phase-1.1-monorepo-skeleton.md",
    ".agent/legacy-v1/gates/phase-1.1-implementation-ready.json",
    "scripts/phase11/runner.py",
    "scripts/phase11/test_check_skeleton.py",
)

SKELETON_DIRS = (
    "apps/web",
    "apps/api",
    "apps/worker",
    "packages/identity",
    "packages/authorization",
    "packages/knowledge",
    "packages/ingestion",
    "packages/retrieval",
    "packages/professor",
    "packages/providers",
    "packages/storage",
    "packages/locking",
    "packages/audit",
    "packages/observability",
    "packages/contracts",
    "packages/shared",
    "infrastructure/docker",
    "infrastructure/compose",
    "infrastructure/migrations",
    "infrastructure/monitoring",
    "infrastructure/scripts",
    "tests/contract",
    "tests/integration",
    "tests/e2e",
    "tests/security",
    "tests/regression",
    "tests/concurrency",
    "tests/performance",
)

LEGACY_DIRS = (
    "cvg-master-rag-v2",
    "rick-professor",
    "modulo-redis-locker",
)

CODE_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}
REQUIRED_TARGETS = {
    "help",
    "bootstrap",
    "validate",
    "dev",
    "test",
    "test-fast",
    "test-integration",
    "lint",
    "typecheck",
    "build",
    "up",
    "down",
    "logs",
    "ci",
    "eval",
}


def _git(*args: str) -> tuple[int, str, str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def _child_git(component: str, *args: str) -> tuple[int, str, str]:
    completed = subprocess.run(
        ["git", "-C", component, *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def _root_snapshot_contains(component: str) -> bool:
    code, snapshot, _ = _git("ls-tree", "-d", "--name-only", "HEAD", "--", component)
    return code == 0 and component in snapshot.splitlines()


def _load_json(path: Path, errors: list[str]) -> dict:
    try:
        value = load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{path.relative_to(ROOT)}: invalid JSON ({exc})")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path.relative_to(ROOT)}: expected a JSON object")
        return {}
    return value


def _check_preservation_manifest(errors: list[str]) -> None:
    manifest = _load_json(PRESERVATION_MANIFEST, errors)
    if not manifest:
        return
    if manifest.get("schema_version") != "phase-1.1-preserved-components.v1":
        errors.append("preserved component manifest has an unexpected schema_version")

    policy = manifest.get("policy")
    if not isinstance(policy, dict):
        errors.append("preserved component manifest policy is not an object")
    else:
        if policy.get("root_snapshot_required") is not True:
            errors.append("preserved component manifest must require the root snapshot")
        if policy.get("independent_git_metadata") != "validated_when_present":
            errors.append(
                "preserved component manifest must validate independent Git metadata when present"
            )

    components = manifest.get("components")
    if not isinstance(components, list):
        errors.append("preserved component manifest components is not a list")
        return

    paths: list[str] = []
    for component in components:
        if not isinstance(component, dict):
            errors.append("preserved component manifest contains a non-object component")
            continue
        path = component.get("path")
        if not isinstance(path, str) or not path:
            errors.append("preserved component manifest contains a component without a path")
            continue
        paths.append(path)
        if component.get("root_snapshot_required") is not True:
            errors.append(f"preserved component does not require root snapshot: {path}")
    if sorted(paths) != sorted(LEGACY_DIRS):
        errors.append("preserved component manifest does not enumerate exactly the legacy paths")


def _status_paths() -> list[str]:
    code, output, _ = _git("status", "--porcelain=v1", "--untracked-files=all")
    if code != 0:
        return []
    paths: list[str] = []
    for line in output.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[-1]
        paths.append(path)
    return paths


def _check_skeleton_directories(errors: list[str]) -> int:
    file_count = 0
    for relative in SKELETON_DIRS:
        directory = ROOT / relative
        if not directory.is_dir():
            errors.append(f"missing skeleton directory: {relative}")
            continue
        readme = directory / "README.md"
        if not readme.is_file():
            errors.append(f"skeleton directory lacks README.md: {relative}")
        files = [path for path in directory.rglob("*") if path.is_file()]
        file_count += len(files)
        unexpected = [
            path.relative_to(ROOT).as_posix()
            for path in files
            if path.name not in {"README.md", ".gitkeep"}
        ]
        errors.extend(
            f"Phase 1.1 skeleton contains non-placeholder file: {path}"
            for path in unexpected
        )
    return file_count


def _check_source_boundaries(contract: dict, errors: list[str], *, root: Path = ROOT) -> int:
    rules = contract.get("forbidden_imports", [])
    if not isinstance(rules, list):
        errors.append("dependency boundary contract forbidden_imports is not a list")
        return 0

    scanned = 0
    for base in (root / "apps", root / "packages"):
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in CODE_SUFFIXES:
                continue
            scanned += 1
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                errors.append(f"{path.relative_to(ROOT)}: unreadable source ({exc})")
                continue
            relative = path.relative_to(root).as_posix()
            scope = "packages/**" if relative.startswith("packages/") else "apps/**"
            for rule in rules:
                if not isinstance(rule, dict) or scope not in str(rule.get("scope", "")):
                    continue
                patterns = rule.get("patterns", [])
                if not isinstance(patterns, list):
                    continue
                for pattern in patterns:
                    if isinstance(pattern, str) and pattern and pattern in content:
                        errors.append(
                            f"{rule.get('rule_id', 'BOUNDARY')}: {relative} contains forbidden pattern {pattern!r}"
                        )
    return scanned


def _check_make_targets(errors: list[str]) -> list[str]:
    try:
        content = (ROOT / "Makefile").read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"Makefile unreadable: {exc}")
        return []
    targets = set(re.findall(r"(?m)^([A-Za-z0-9_.-]+):(?:\s|$)", content))
    missing = sorted(REQUIRED_TARGETS - targets)
    errors.extend(f"Makefile missing target: {target}" for target in missing)
    return sorted(targets)


def main() -> int:
    errors: list[str] = []
    missing = [relative for relative in ROOT_FILES if not (ROOT / relative).is_file()]
    errors.extend(f"missing root Phase 1.1 artifact: {relative}" for relative in missing)

    contract = _load_json(BOUNDARIES, errors) if BOUNDARIES.is_file() else {}
    _check_preservation_manifest(errors)
    if contract.get("schema_version") != "phase-1.1-dependency-boundaries.v1":
        errors.append("dependency boundary contract has an unexpected schema_version")
    if contract.get("protected_legacy_paths") != [f"{item}/" for item in LEGACY_DIRS]:
        errors.append("dependency boundary contract does not protect all legacy paths")

    skeleton_files = _check_skeleton_directories(errors)
    targets = _check_make_targets(errors)

    for component in LEGACY_DIRS:
        path = ROOT / component
        if not path.is_dir():
            errors.append(f"missing preserved component directory: {component}")
            continue
        if not _root_snapshot_contains(component):
            errors.append(f"preserved component is missing from the root Git snapshot: {component}")
        if (path / ".git").exists():
            code, head, stderr = _child_git(component, "rev-parse", "HEAD")
            if code != 0 or not re.fullmatch(r"[0-9a-f]{40}", head, re.IGNORECASE):
                errors.append(f"cannot resolve independent child HEAD for {component}: {stderr or head}")
        else:
            if not _root_snapshot_contains(component):
                code, _, stderr = _git("ls-tree", "-d", "--name-only", "HEAD", "--", component)
                errors.append(
                    "preserved component has neither independent Git metadata nor a root snapshot: "
                    f"{component} ({stderr or 'snapshot missing'})"
                )

    status_paths = _status_paths()
    for component in LEGACY_DIRS:
        touched = [path for path in status_paths if path == component or path.startswith(f"{component}/")]
        if touched:
            errors.append(
                f"root worktree touches protected child path {component}: {', '.join(touched)}"
            )

    scanned_sources = _check_source_boundaries(contract, errors)

    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1

    child_heads = []
    snapshot_only = []
    for component in LEGACY_DIRS:
        if (ROOT / component / ".git").exists():
            _, head, _ = _child_git(component, "rev-parse", "HEAD")
            child_heads.append(f"{component}={head}")
        else:
            snapshot_only.append(component)
    print("PASS: Phase 1.1 additive monorepo skeleton is structurally safe")
    print(f"SKELETON_PLACEHOLDER_FILES={skeleton_files}")
    print(f"SOURCE_FILES_SCANNED={scanned_sources}")
    print(f"ROOT_TARGETS={','.join(targets)}")
    print(f"PROTECTED_CHILD_HEADS={' '.join(child_heads)}")
    print(f"PROTECTED_CHILD_SNAPSHOT_ONLY={' '.join(snapshot_only)}")
    print(f"ROOT_WORKTREE_ENTRIES={len(status_paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
