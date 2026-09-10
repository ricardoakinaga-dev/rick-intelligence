#!/usr/bin/env python3
"""Run the two-process worker gate and emit a commit-bound envelope."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from scripts.phase11 import multi_worker_runtime_gate
    from scripts.state_of_art.phase3_runtime_adapter import run_gate_adapter
    from scripts.state_of_art.release_integrity import capture_checkout
except ImportError:  # pragma: no cover - direct script execution fallback.
    import multi_worker_runtime_gate

    from phase3_runtime_adapter import run_gate_adapter
    from release_integrity import capture_checkout


DEFAULT_OUTPUT = ".runtime/phase-3/multi-worker-runtime-evidence.json"
RAW_OUTPUT = ".runtime/phase-3/raw/multi-worker-runtime-gate.json"
CAPABILITY_ID = "P0-05"


def run(root: Path = ROOT, *, output: str = DEFAULT_OUTPUT, argv: Sequence[str] = ()) -> dict[str, Any]:
    return run_gate_adapter(
        root,
        multi_worker_runtime_gate.main,
        capability_id=CAPABILITY_ID,
        output=output,
        raw_output=RAW_OUTPUT,
        environment="phase3-two-process-worker-local-disposable",
        procedure="scripts/phase11/multi_worker_runtime_gate.py against an explicitly supplied disposable PostgreSQL DSN",
        argv=argv,
        checkout_capture=capture_checkout,
    )


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
