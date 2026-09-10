#!/usr/bin/env python3
"""Validate the current prompt's canonical Triple AAA capability matrix."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys
from typing import Any

try:
    from scripts.state_of_art.json_boundary import load_json
except ImportError:  # pragma: no cover
    from json_boundary import load_json


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / "docs/reports/triple-aaa-runtime-capability-matrix.json"
EXPECTED_PROMPT = "docs/prompts/triple-aaa-runtime-closure-2026-09-10.txt"
EXPECTED_PROMPT_SHA256 = "064be5e04ed483d5d95ef803a66faf6675f7c1f00633cdea83d5abfdd5370d5f"
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
    if document.get("prompt") != EXPECTED_PROMPT:
        errors.append("prompt binding mismatch")
    if document.get("prompt_sha256") != EXPECTED_PROMPT_SHA256:
        errors.append("prompt hash mismatch")
    prompt_path = ROOT / EXPECTED_PROMPT
    try:
        observed_prompt_hash = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
    except OSError:
        observed_prompt_hash = None
    if observed_prompt_hash != EXPECTED_PROMPT_SHA256:
        errors.append("archived prompt bytes do not match the expected hash")
    binding = document.get("candidate_binding")
    if not isinstance(binding, dict) or binding.get("packet") != ".runtime/phase-3/triple-aaa-verify.json":
        errors.append("candidate binding must point to the same-run verifier packet")
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
