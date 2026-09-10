#!/usr/bin/env python3
"""Validate the current prompt's canonical Triple AAA capability matrix."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

try:
    from scripts.state_of_art.json_boundary import load_json
except ImportError:  # pragma: no cover
    from json_boundary import load_json


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / "docs/reports/triple-aaa-runtime-capability-matrix.json"
ALLOWED_STATES = frozenset({
    "DONE_LOCAL_SCOPE", "LOCAL_VERIFIED", "VERIFIED_RUNTIME", "PARTIAL",
    "NOT_RUN", "BLOCKED_EXTERNAL", "FAILED", "PROMOTABLE",
})
REQUIRED_COLUMNS = (
    "CAPABILITY", "STATE", "SOURCE_EVIDENCE", "TEST_EVIDENCE",
    "RUNTIME_EVIDENCE", "INDEPENDENT_REVIEW", "BLOCKER", "OWNER",
    "PRIORITY", "PROMOTION_CONDITION",
)


def validate(path: Path = DEFAULT_PATH) -> dict[str, Any]:
    errors: list[str] = []
    try:
        document = load_json(path)
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        return {"status": "FAIL", "errors": [f"matrix unreadable: {type(exc).__name__}"]}
    if not isinstance(document, dict):
        return {"status": "FAIL", "errors": ["matrix root must be an object"]}
    if document.get("schema") != "rick-triple-aaa-runtime-capability-matrix.v1":
        errors.append("schema mismatch")
    rows = document.get("rows")
    if not isinstance(rows, list) or not rows:
        errors.append("rows must be a non-empty array")
        rows = []
    names: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"row {index} must be an object")
            continue
        missing = [column for column in REQUIRED_COLUMNS if column not in row]
        if missing:
            errors.append(f"row {index} missing columns: {','.join(missing)}")
        capability = row.get("CAPABILITY")
        if not isinstance(capability, str) or not capability.strip() or capability in names:
            errors.append(f"row {index} has an invalid or duplicate CAPABILITY")
        else:
            names.add(capability)
        state = row.get("STATE")
        if state not in ALLOWED_STATES:
            errors.append(f"row {index} has forbidden STATE")
        if row.get("PRIORITY") not in {"P0", "P1", "P2"}:
            errors.append(f"row {index} has invalid PRIORITY")
        for column in ("SOURCE_EVIDENCE", "TEST_EVIDENCE", "RUNTIME_EVIDENCE"):
            if not isinstance(row.get(column), list):
                errors.append(f"row {index} {column} must be an array")
        for column in ("BLOCKER", "OWNER", "PROMOTION_CONDITION"):
            if not isinstance(row.get(column), str) or not row[column].strip():
                errors.append(f"row {index} {column} must be non-empty text")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "rows": len(rows)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default=str(DEFAULT_PATH))
    args = parser.parse_args(argv)
    result = validate(Path(args.path))
    print(result)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
