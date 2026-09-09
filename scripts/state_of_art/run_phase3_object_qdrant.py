#!/usr/bin/env python3
"""Run the object/vector gate and emit a commit-bound Phase 3 envelope.

Endpoint and bucket selectors may be supplied explicitly.  Access keys and
API keys remain environment/secret-manager inputs and are never echoed by this
adapter.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import json
import sys
from typing import Any, Sequence

try:
    from scripts.phase11 import object_qdrant_runtime_gate
    from scripts.state_of_art.phase3_runtime_adapter import run_gate_adapter
    from scripts.state_of_art.release_integrity import capture_checkout
except ImportError:  # pragma: no cover - direct script execution fallback.
    import object_qdrant_runtime_gate

    from phase3_runtime_adapter import run_gate_adapter
    from release_integrity import capture_checkout


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ".runtime/phase-3/object-qdrant-runtime-evidence.json"
RAW_OUTPUT = ".runtime/phase-3/raw/object-qdrant-runtime-gate.json"
CAPABILITY_ID = "P0-07"


def run(root: Path = ROOT, *, output: str = DEFAULT_OUTPUT, argv: Sequence[str] = ()) -> dict[str, Any]:
    return run_gate_adapter(
        root,
        object_qdrant_runtime_gate.main,
        capability_id=CAPABILITY_ID,
        output=output,
        raw_output=RAW_OUTPUT,
        environment="phase3-object-qdrant-local-disposable",
        procedure="scripts/phase11/object_qdrant_runtime_gate.py against explicitly supplied disposable object/vector endpoints",
        argv=argv,
        checkout_capture=capture_checkout,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--qdrant-url", default=None)
    parser.add_argument("--object-endpoint", default=None)
    parser.add_argument("--object-bucket", default=None)
    parser.add_argument("--object-region", default=None)
    parser.add_argument("--require-tls", action="store_true")
    parser.add_argument("--allow-nonlocal", action="store_true")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    gate_args: list[str] = []
    for name, value in (
        ("--qdrant-url", args.qdrant_url),
        ("--object-endpoint", args.object_endpoint),
        ("--object-bucket", args.object_bucket),
        ("--object-region", args.object_region),
    ):
        if value is not None:
            gate_args.extend((name, value))
    if args.require_tls:
        gate_args.append("--require-tls")
    if args.allow_nonlocal:
        gate_args.append("--allow-nonlocal")

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
