#!/usr/bin/env python3
"""Run the live provider gate and emit commit-bound Phase 3 evidence."""

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
    from scripts.phase11 import provider_runtime_gate
    from scripts.state_of_art.phase3_runtime_adapter import run_gate_adapter
    from scripts.state_of_art.release_integrity import capture_checkout
except ImportError:  # pragma: no cover - direct script execution fallback.
    import provider_runtime_gate

    from phase3_runtime_adapter import run_gate_adapter
    from release_integrity import capture_checkout


DEFAULT_OUTPUT = ".runtime/phase-3/provider-runtime-evidence.json"
RAW_OUTPUT = ".runtime/phase-3/raw/provider-runtime-gate.json"
CAPABILITY_ID = "P1-02"


def run(root: Path = ROOT, *, output: str = DEFAULT_OUTPUT, argv: Sequence[str] = ()) -> dict[str, Any]:
    return run_gate_adapter(
        root,
        provider_runtime_gate.main,
        capability_id=CAPABILITY_ID,
        output=output,
        raw_output=RAW_OUTPUT,
        environment="phase3-provider-local-disposable",
        procedure="scripts/phase11/provider_runtime_gate.py against an explicitly supplied OpenAI-compatible disposable endpoint",
        argv=argv,
        checkout_capture=capture_checkout,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--provider-url", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--chat-model", default=None)
    parser.add_argument("--embedding-model", default=None)
    parser.add_argument("--embedding-dimensions", type=int, default=None)
    parser.add_argument("--require-tls", action="store_true")
    parser.add_argument("--require-auth", action="store_true")
    parser.add_argument("--allow-nonlocal", action="store_true")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    gate_args: list[str] = []
    for name, value in (
        ("--provider-url", args.provider_url),
        ("--api-key", args.api_key),
        ("--chat-model", args.chat_model),
        ("--embedding-model", args.embedding_model),
        ("--embedding-dimensions", args.embedding_dimensions),
    ):
        if value is not None:
            gate_args.extend((name, str(value)))
    for flag in ("--require-tls", "--require-auth", "--allow-nonlocal"):
        if getattr(args, flag[2:].replace("-", "_")):
            gate_args.append(flag)
    envelope = run(ROOT, output=args.output, argv=gate_args)
    print(json.dumps({"output": args.output, "status": envelope["status"], "capability_id": CAPABILITY_ID}, sort_keys=True))
    return int(envelope["exit_status"])


if __name__ == "__main__":
    raise SystemExit(main())
