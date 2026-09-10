#!/usr/bin/env python3
"""Emit a commit-bound Phase 3 frontend/accessibility/supply-chain envelope."""

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
    from scripts.phase11 import frontend_supply_runtime_gate
    from scripts.state_of_art.phase3_runtime_adapter import run_gate_adapter
    from scripts.state_of_art.release_integrity import capture_checkout
except ImportError:  # pragma: no cover - direct script execution fallback.
    import frontend_supply_runtime_gate

    from phase3_runtime_adapter import run_gate_adapter
    from release_integrity import capture_checkout


DEFAULT_OUTPUT = ".runtime/phase-3/frontend-supply-runtime-evidence.json"
RAW_OUTPUT = ".runtime/phase-3/raw/frontend-supply-runtime-gate.json"
# The envelope has one primary capability ID for compatibility with the
# existing Phase 3 adapter contract, while the underlying gate covers both
# current P1 rows.
CAPABILITY_ID = "P1-06"
COVERED_CAPABILITY_IDS = ("P1-06", "P1-07")
SUPPLY_OUTPUT = ".runtime/phase-3/supply-chain-runtime-evidence.json"


def run(
    root: Path = ROOT,
    *,
    output: str = DEFAULT_OUTPUT,
    argv: Sequence[str] = (),
) -> dict[str, Any]:
    gate_argv = ["--root", str(root), *argv]
    envelope = run_gate_adapter(
        root,
        frontend_supply_runtime_gate.main,
        capability_id=CAPABILITY_ID,
        output=output,
        raw_output=RAW_OUTPUT,
        environment="phase3-frontend-accessibility-supply-local-or-approved-runtime",
        procedure="scripts/phase11/frontend_supply_runtime_gate.py against the canonical web/API boundary plus available supply-chain/container tools",
        argv=gate_argv,
        checkout_capture=capture_checkout,
    )
    envelope["covered_capability_ids"] = list(COVERED_CAPABILITY_IDS)
    # Keep the adapter's envelope on disk authoritative after adding the
    # mapping; this does not change the underlying raw gate artifact.
    output_path = (root / output).resolve() if not Path(output).is_absolute() else Path(output).resolve()
    output_path.write_text(json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    supply_envelope = dict(envelope)
    supply_envelope["capability_id"] = "P1-07"
    supply_envelope["gate_id"] = "P1-07"
    supply_envelope["lane"] = "P1-07"
    supply_envelope["record_id"] = envelope["record_id"].replace("P1-06", "P1-07", 1)
    supply_envelope["reviewer"] = {
        **dict(envelope.get("reviewer", {})),
        "id": "automated-phase3-p1-07",
        "name": "Phase 3 P1-07 runtime adapter",
    }
    supply_path = (root / SUPPLY_OUTPUT).resolve()
    supply_path.parent.mkdir(parents=True, exist_ok=True)
    supply_path.write_text(json.dumps(supply_envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return envelope


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--web-url", default=None)
    parser.add_argument("--api-url", default=None)
    parser.add_argument("--browser-executable", default=None)
    parser.add_argument("--no-managed-runtime", action="store_true")
    parser.add_argument("--production-runtime", action="store_true")
    parser.add_argument("--require-production", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    gate_args: list[str] = []
    for flag, value in (("--web-url", args.web_url), ("--api-url", args.api_url), ("--browser-executable", args.browser_executable)):
        if value is not None:
            gate_args.extend((flag, value))
    for flag, enabled in (("--no-managed-runtime", args.no_managed_runtime), ("--production-runtime", args.production_runtime), ("--require-production", args.require_production)):
        if enabled:
            gate_args.append(flag)
    gate_args.extend(("--timeout-seconds", str(args.timeout_seconds)))
    envelope = run(ROOT, output=args.output, argv=gate_args)
    print(
        json.dumps(
            {
                "output": args.output,
                "status": envelope["status"],
                "capability_id": CAPABILITY_ID,
                "covered_capability_ids": list(COVERED_CAPABILITY_IDS),
                "runtime_claim": envelope.get("gate", {}).get("runtime_claim", False),
                "production_safe": envelope.get("production_safe", False),
            },
            sort_keys=True,
        )
    )
    return int(envelope["exit_status"])


if __name__ == "__main__":
    raise SystemExit(main())
