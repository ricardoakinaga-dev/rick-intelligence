#!/usr/bin/env python3
"""Run the two-process Redis gate and emit a commit-bound Phase 3 envelope."""

from __future__ import annotations

import argparse
from pathlib import Path
import json
import sys
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from scripts.phase11 import redis_multi_replica_runtime_gate
    from scripts.state_of_art.phase3_runtime_adapter import run_gate_adapter
    from scripts.state_of_art.release_integrity import capture_checkout
except ImportError:  # pragma: no cover - direct script execution fallback.
    import redis_multi_replica_runtime_gate

    from phase3_runtime_adapter import run_gate_adapter
    from release_integrity import capture_checkout


DEFAULT_OUTPUT = ".runtime/phase-3/redis-multi-replica-runtime-evidence.json"
RAW_OUTPUT = ".runtime/phase-3/raw/redis-multi-replica-runtime-gate.json"
CAPABILITY_ID = "P0-06"


def run(root: Path = ROOT, *, output: str = DEFAULT_OUTPUT, argv: Sequence[str] = ()) -> dict[str, Any]:
    return run_gate_adapter(
        root,
        redis_multi_replica_runtime_gate.main,
        capability_id=CAPABILITY_ID,
        output=output,
        raw_output=RAW_OUTPUT,
        environment="phase3-redis-multi-replica-local-disposable",
        procedure="scripts/phase11/redis_multi_replica_runtime_gate.py against an explicitly supplied disposable Redis URL",
        argv=argv,
        checkout_capture=capture_checkout,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--redis-url", default=None, help="loopback URL; credentials should normally come from the environment")
    parser.add_argument("--require-tls", action="store_true")
    parser.add_argument("--allow-nonlocal", action="store_true")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    gate_args: list[str] = []
    if args.redis_url is not None:
        gate_args.extend(("--redis-url", args.redis_url))
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
