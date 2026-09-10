#!/usr/bin/env python3
"""Run the Phase 3.9/3.10 observability gate and bind its evidence envelope."""

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
    from scripts.phase11 import observability_runtime_gate
    from scripts.state_of_art.phase3_runtime_adapter import run_gate_adapter
    from scripts.state_of_art.release_integrity import capture_checkout
except ImportError:  # pragma: no cover - direct script execution fallback.
    import observability_runtime_gate

    from phase3_runtime_adapter import run_gate_adapter
    from release_integrity import capture_checkout


DEFAULT_OUTPUT = ".runtime/phase-3/observability-runtime-evidence.json"
RAW_OUTPUT = ".runtime/phase-3/raw/observability-runtime-gate.json"
CAPABILITY_ID = "P1-04"


def run(root: Path = ROOT, *, output: str = DEFAULT_OUTPUT, argv: Sequence[str] = ()) -> dict[str, Any]:
    """Execute the service gate through the canonical Phase 3 adapter."""

    return run_gate_adapter(
        root,
        observability_runtime_gate.main,
        capability_id=CAPABILITY_ID,
        output=output,
        raw_output=RAW_OUTPUT,
        environment="phase3-observability-local-or-external-bounded",
        procedure=(
            "scripts/phase11/observability_runtime_gate.py in local contract mode "
            "or against explicitly supplied OTLP collector, trace backend, "
            "Prometheus backend and full API pipeline probe"
        ),
        argv=argv,
        checkout_capture=capture_checkout,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--mode", choices=("local", "external"), default="external")
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--collector-url", default=None)
    parser.add_argument("--backend-url", default=None)
    parser.add_argument("--trace-backend-url", default=None)
    parser.add_argument("--metrics-backend-url", default=None)
    parser.add_argument("--alerts-url", default=None)
    parser.add_argument("--api-url", default=None)
    parser.add_argument("--probe-url", default=None)
    parser.add_argument("--probe-method", choices=("GET", "POST", "PUT", "PATCH"), default="GET")
    parser.add_argument("--probe-body")
    parser.add_argument("--probe-body-file")
    parser.add_argument("--probe-header", action="append", default=[])
    parser.add_argument("--allow-nonlocal", action="store_true")
    parser.add_argument("--require-tls", action="store_true")
    parser.add_argument("--run-harness-contracts", action="store_true")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--poll-timeout", type=float, default=15.0)
    parser.add_argument("--poll-interval", type=float, default=0.25)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    gate_args: list[str] = ["--mode", "local" if args.local else args.mode]
    for option in (
        "collector_url", "backend_url", "trace_backend_url", "metrics_backend_url",
        "alerts_url", "api_url", "probe_url", "probe_body", "probe_body_file",
    ):
        value = getattr(args, option)
        if value is not None:
            gate_args.extend(("--" + option.replace("_", "-"), value))
    gate_args.extend(("--probe-method", args.probe_method))
    for value in args.probe_header:
        gate_args.extend(("--probe-header", value))
    for flag in ("allow_nonlocal", "require_tls", "run_harness_contracts"):
        if getattr(args, flag):
            gate_args.append("--" + flag.replace("_", "-"))
    gate_args.extend(("--timeout", str(args.timeout), "--poll-timeout", str(args.poll_timeout), "--poll-interval", str(args.poll_interval)))

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
