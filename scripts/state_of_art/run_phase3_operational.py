#!/usr/bin/env python3
"""Bind one performance/chaos/soak harness observation to the current commit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.state_of_art.phase3_runtime_adapter import run_gate_adapter
from scripts.state_of_art.release_integrity import capture_checkout
from scripts.state_of_art import phase3_lane


LANES = ("performance", "chaos", "soak")


def run(root: Path, *, lane: str, output: str) -> dict[str, Any]:
    if lane not in LANES:
        raise ValueError(f"unknown lane: {lane}")
    raw_output = f".runtime/phase-3/raw/{lane}-lane.json"
    return run_gate_adapter(
        root,
        phase3_lane.main,
        capability_id=f"P1-05-{lane}",
        output=output,
        raw_output=raw_output,
        environment=f"phase3-{lane}-approved-disposable-harness",
        procedure=f"scripts/state_of_art/phase3_lane.py --lane {lane} --strict with an explicitly supplied disposable harness",
        argv=("--lane", lane, "--strict"),
        checkout_capture=capture_checkout,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", choices=LANES, required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    output = args.output or f".runtime/phase-3/{args.lane}-runtime-evidence.json"
    envelope = run(ROOT, lane=args.lane, output=output)
    print(json.dumps({"output": output, "lane": args.lane, "status": envelope["status"]}, sort_keys=True))
    return int(envelope["exit_status"])


if __name__ == "__main__":
    raise SystemExit(main())
