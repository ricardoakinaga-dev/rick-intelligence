#!/usr/bin/env python3
"""Bind the file-security/process-isolation gate to Phase 3 evidence."""

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
    from scripts.phase11 import file_security_runtime_gate
    from scripts.state_of_art.phase3_runtime_adapter import run_gate_adapter
    from scripts.state_of_art.release_integrity import capture_checkout
except ImportError:  # pragma: no cover - direct script execution fallback
    import file_security_runtime_gate

    from phase3_runtime_adapter import run_gate_adapter
    from release_integrity import capture_checkout


DEFAULT_OUTPUT = ".runtime/phase-3/file-security-runtime-evidence.json"
RAW_OUTPUT = ".runtime/phase-3/raw/file-security-runtime-gate.json"
CAPABILITY_ID = "P1-09"


def run(
    root: Path = ROOT,
    *,
    output: str = DEFAULT_OUTPUT,
    argv: Sequence[str] = (),
) -> dict[str, Any]:
    """Execute the gate through the canonical commit-bound adapter."""

    gate_argv = ["--root", str(root), *argv]
    return run_gate_adapter(
        root,
        file_security_runtime_gate.main,
        capability_id=CAPABILITY_ID,
        output=output,
        raw_output=RAW_OUTPUT,
        environment="phase3-file-security-external-disposable-or-approved-runtime",
        procedure=(
            "scripts/phase11/file_security_runtime_gate.py against an explicitly supplied "
            "authorized external file-ingestion/process-isolation composition"
        ),
        argv=gate_argv,
        checkout_capture=capture_checkout,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-path", default=None)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--memory-mb", type=int, default=512)
    parser.add_argument("--cpu-seconds", type=int, default=12)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    gate_args: list[str] = []
    if args.runtime_path is not None:
        gate_args.extend(("--runtime-path", args.runtime_path))
    gate_args.extend(
        (
            "--timeout-seconds",
            str(args.timeout_seconds),
            "--memory-mb",
            str(args.memory_mb),
            "--cpu-seconds",
            str(args.cpu_seconds),
        )
    )
    envelope = run(ROOT, output=args.output, argv=gate_args)
    print(
        json.dumps(
            {
                "output": args.output,
                "status": envelope["status"],
                "capability_id": CAPABILITY_ID,
                "runtime_claim": envelope.get("gate", {}).get("runtime_claim", False),
                "production_safe": envelope.get("production_safe", False),
            },
            sort_keys=True,
        )
    )
    return int(envelope["exit_status"])


if __name__ == "__main__":
    raise SystemExit(main())
