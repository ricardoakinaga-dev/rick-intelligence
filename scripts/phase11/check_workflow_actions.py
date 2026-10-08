#!/usr/bin/env python3
"""Static rules for the checked-in GitHub workflows.

Two independent rules, both fail-closed:

1. every external ``uses:`` reference is pinned to an exact 40-character commit
   SHA (a SHA that appears only in a trailing comment does not pin anything);
2. no step mentions a component retired by AUD07-02 -- an active step that still
   points at ``cvg-master-rag-v2``, ``rick-professor`` or
   ``modulo-redis-locker`` would fail at runtime, while a YAML comment about
   them is harmless documentation.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
try:
    from scripts.phase15.check_boundaries import LEGACY_PATHS
except ModuleNotFoundError:  # Direct execution from the scripts/phase11 directory.
    sys.path.insert(0, str(ROOT))
    from scripts.phase15.check_boundaries import LEGACY_PATHS

USES_PATTERN = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)", re.MULTILINE)
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def check_workflow(source: str, text: str) -> list[str]:
    """Report floating action references and retired component paths with their line."""
    errors: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        errors.extend(_retired_path_errors(source, number, line))
        match = USES_PATTERN.match(line)
        if match is None:
            continue
        reference = match.group(1)
        if reference.startswith("./"):
            continue
        name, separator, revision = reference.rpartition("@")
        if not separator or not name or SHA_PATTERN.fullmatch(revision) is None:
            errors.append(f"{source}:{number}: {reference} must use an exact 40-character commit SHA")
    return errors


def _retired_path_errors(source: str, number: int, line: str) -> list[str]:
    """Report a retired component path in active workflow content only."""
    stripped = line.lstrip()
    if stripped.startswith("#"):
        return []
    active = line.split(" #", 1)[0]
    return [
        f"{source}:{number}: active step references retired component {path}"
        for path in LEGACY_PATHS
        if path in active
    ]


def check_actions(root: Path = ROOT) -> list[str]:
    """Inspect every checked-in workflow, including non-phase lanes."""
    directory = root / ".github/workflows"
    errors = []
    for path in sorted((*directory.glob("*.yml"), *directory.glob("*.yaml"))):
        errors.extend(check_workflow(str(path.relative_to(root)), path.read_text()))
    return errors


def main() -> int:
    errors = check_actions()
    for error in errors:
        print(f"FAIL: {error}")
    if errors:
        return 1
    print("PASS: workflow Actions use exact commit SHAs and no active step references a retired component")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
