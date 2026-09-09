#!/usr/bin/env python3
"""Run the PostgreSQL gate and emit a commit-bound Phase 3 evidence envelope.

The underlying gate owns the database assertions.  This adapter owns only the
Phase 3 evidence contract: it never discovers credentials, widens a DSN, or
turns a missing database into a passing runtime result.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Sequence

try:
    from scripts.phase11 import postgres_runtime_gate
    from scripts.state_of_art.release_integrity import capture_checkout
except ImportError:  # pragma: no cover - direct script execution fallback.
    import postgres_runtime_gate

    from release_integrity import capture_checkout


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ".runtime/phase-3/postgres-runtime-evidence.json"
RAW_OUTPUT = ".runtime/phase-3/raw/postgres-runtime-gate.json"
SCHEMA_VERSION = "state-of-art-runtime-evidence.v1"
CAPABILITY_ID = "P0-04"


def _safe_output(root: Path, raw: str) -> Path:
    path = (root / raw).resolve()
    path.relative_to(root.resolve())
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _status(raw: dict[str, Any], exit_status: int) -> str:
    if exit_status == 0 and raw.get("status") == "PASS":
        return "PASS"
    if raw.get("status") == "BLOCKED_EXTERNAL" or exit_status == 2:
        return "BLOCKED_EXTERNAL"
    return "FAILED"


def run(root: Path = ROOT, *, output: str = DEFAULT_OUTPUT, argv: Sequence[str] = ()) -> dict[str, Any]:
    root = root.resolve()
    output_path = _safe_output(root, output)
    raw_path = _safe_output(root, RAW_OUTPUT)
    raw_path.parent.mkdir(parents=True, exist_ok=True)

    gate_args = [*argv, "--output", str(raw_path.relative_to(root))]
    try:
        exit_status = int(postgres_runtime_gate.main(gate_args))
        raw_payload = json.loads(raw_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        exit_status = 1
        raw_payload = {
            "schema_version": "phase-2-postgres-runtime-gate.v1",
            "status": "FAIL",
            "results": [{"name": "adapter", "result": "FAIL", "detail": type(exc).__name__}],
            "runtime_claim": False,
        }

    checkout = capture_checkout(root)
    observed_at = datetime.now(timezone.utc).isoformat()
    status = _status(raw_payload, exit_status)
    if status == "PASS":
        limitations = [
            "Automated PostgreSQL runtime assertions passed; independent Phase 3 review is still required.",
            "This record does not prove worker process crash/restart or production promotion.",
        ]
        next_action = "Bind this record to the complete Phase 3 matrix and obtain an independent review."
    elif status == "BLOCKED_EXTERNAL":
        limitations = [
            "The disposable PostgreSQL runtime, driver or loopback DSN was unavailable; no runtime claim is made.",
            "No migration, lock, concurrency, crash or retention assertion is upgraded to PASS.",
        ]
        next_action = "Provide approved disposable PostgreSQL access and rerun the gate."
    else:
        limitations = [
            "The PostgreSQL runtime gate returned a failure; raw results are retained for diagnosis.",
            "No runtime or promotion claim is made from this record.",
        ]
        next_action = "Repair the failing PostgreSQL gate, retain this record, and create a new run."

    envelope = {
        "schema_version": SCHEMA_VERSION,
        "record_id": f"PH3-{CAPABILITY_ID}-{observed_at.replace('-', '').replace(':', '').replace('.', '')}",
        "capability_id": CAPABILITY_ID,
        "status": status,
        "commit_sha": checkout.get("head"),
        "tree_sha": checkout.get("tree"),
        "checkout_fingerprint": checkout.get("fingerprint"),
        "clean_worktree": checkout.get("status") == "CLEAN",
        "artifact_sha256": _sha256(raw_path) if raw_path.is_file() else None,
        "environment": "phase3-postgres-local-disposable",
        "procedure": "scripts/phase11/postgres_runtime_gate.py against an explicitly supplied disposable PostgreSQL DSN",
        "exit_status": exit_status,
        "observed_at": observed_at,
        "reviewer": {
            "id": "automated-phase3-postgres-runner",
            "kind": "automated",
            "name": "Phase 3 PostgreSQL runtime adapter",
            "independent": False,
        },
        "limitations": limitations,
        "next_action": next_action,
        "raw_artifacts": [
            {
                "path": str(raw_path.relative_to(root)),
                "sha256": _sha256(raw_path) if raw_path.is_file() else None,
                "description": "underlying PostgreSQL runtime gate result",
            }
        ],
        "gate": raw_payload,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return envelope


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--allow-nonlocal", action="store_true")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    gate_args: list[str] = []
    if args.database_url is not None:
        gate_args.extend(("--database-url", args.database_url))
    if args.allow_nonlocal:
        gate_args.append("--allow-nonlocal")
    envelope = run(ROOT, output=args.output, argv=gate_args)
    print(json.dumps({"output": args.output, "status": envelope["status"], "capability_id": CAPABILITY_ID}, sort_keys=True))
    return int(envelope["exit_status"])


if __name__ == "__main__":
    raise SystemExit(main())
