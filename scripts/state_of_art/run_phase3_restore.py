#!/usr/bin/env python3
"""Bind the external Phase 3.10 restore gate to a Phase 3 evidence envelope.

The adapter only selects the Phase 11 gate and records the commit-bound
envelope.  It never supplies a local backup/restore implementation or turns a
missing external runtime into a pass.
"""

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
    from scripts.phase11 import restore_runtime_gate
    from scripts.state_of_art.phase3_runtime_adapter import run_gate_adapter
    from scripts.state_of_art.release_integrity import capture_checkout
except ImportError:  # pragma: no cover - direct script execution fallback.
    import restore_runtime_gate

    from phase3_runtime_adapter import run_gate_adapter
    from release_integrity import capture_checkout


DEFAULT_OUTPUT = ".runtime/phase-3/restore-runtime-evidence.json"
RAW_OUTPUT = ".runtime/phase-3/raw/restore-runtime-gate.json"
CAPABILITY_ID = "P1-05"


def run(
    root: Path = ROOT,
    *,
    output: str = DEFAULT_OUTPUT,
    argv: Sequence[str] = (),
) -> dict[str, Any]:
    """Run the restore gate through the shared Phase 3 evidence adapter."""

    return run_gate_adapter(
        root,
        restore_runtime_gate.main,
        capability_id=CAPABILITY_ID,
        output=output,
        raw_output=RAW_OUTPUT,
        environment="phase3-restore-external-disposable-runtime",
        procedure=(
            "scripts/phase11/restore_runtime_gate.py against an explicitly "
            "authorized external disposable DR composition"
        ),
        argv=argv,
        checkout_capture=capture_checkout,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--runtime-path", default=None)
    parser.add_argument("--timeout-seconds", default=None)
    parser.add_argument("--rpo-seconds", default=None)
    parser.add_argument("--rto-seconds", default=None)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    gate_args: list[str] = []
    for name, value in (
        ("--runtime-path", args.runtime_path),
        ("--timeout-seconds", args.timeout_seconds),
        ("--rpo-seconds", args.rpo_seconds),
        ("--rto-seconds", args.rto_seconds),
    ):
        if value is not None:
            gate_args.extend((name, value))
    envelope = run(ROOT, output=args.output, argv=gate_args)
    print(
        json.dumps(
            {
                "output": args.output,
                "status": envelope["status"],
                "capability_id": CAPABILITY_ID,
            },
            sort_keys=True,
        )
    )
    return int(envelope["exit_status"])


if __name__ == "__main__":
    raise SystemExit(main())
