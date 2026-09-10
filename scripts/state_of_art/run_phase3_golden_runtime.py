#!/usr/bin/env python3
"""Emit commit-bound Phase 3 evidence for the Golden Ingestion Runtime path.

The adapter only selects the underlying gate and binds its JSON to the clean
checkout.  Infrastructure construction remains in the explicit composition
selected by ``RICK_GOLDEN_RUNTIME_PATH``.
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
    from scripts.phase11 import golden_runtime_gate
    from scripts.state_of_art.phase3_runtime_adapter import run_gate_adapter
    from scripts.state_of_art.release_integrity import capture_checkout
except ImportError:  # pragma: no cover - direct script execution fallback.
    import golden_runtime_gate

    from phase3_runtime_adapter import run_gate_adapter
    from release_integrity import capture_checkout


DEFAULT_OUTPUT = ".runtime/phase-3/golden-ingestion-runtime-evidence.json"
RAW_OUTPUT = ".runtime/phase-3/raw/golden-ingestion-runtime-gate.json"
CAPABILITY_ID = "P0-08"


def run(root: Path = ROOT, *, output: str = DEFAULT_OUTPUT, argv: Sequence[str] = ()) -> dict[str, Any]:
    """Run the Golden Runtime gate through the shared evidence adapter."""

    return run_gate_adapter(
        root,
        golden_runtime_gate.main,
        capability_id=CAPABILITY_ID,
        output=output,
        raw_output=RAW_OUTPUT,
        environment="phase3-golden-ingestion-local-disposable",
        procedure="scripts/phase11/golden_runtime_gate.py with explicitly injected RICK_GOLDEN_RUNTIME_PATH dependencies",
        argv=argv,
        checkout_capture=capture_checkout,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--runtime-path", default=None)
    parser.add_argument("--timeout-seconds", type=float, default=None)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    gate_args: list[str] = []
    if args.runtime_path is not None:
        gate_args.extend(("--runtime-path", args.runtime_path))
    if args.timeout_seconds is not None:
        gate_args.extend(("--timeout-seconds", str(args.timeout_seconds)))
    envelope = run(ROOT, output=args.output, argv=gate_args)
    print(
        json.dumps(
            {"output": args.output, "status": envelope["status"], "capability_id": CAPABILITY_ID},
            sort_keys=True,
        )
    )
    return int(envelope["exit_status"])


if __name__ == "__main__":
    raise SystemExit(main())
