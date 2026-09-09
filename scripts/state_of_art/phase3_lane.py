#!/usr/bin/env python3
"""Run a named Phase 3 operational lane without allowing a false green.

The initial Phase 3.1 implementation makes performance, chaos and soak lanes
explicit. They remain blocked until their real disposable runtime harnesses are
implemented and supplied with an owned environment. The command writes a
truthful ignored diagnostic artifact and returns non-zero in strict mode.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
LANES = {
    "performance": "Phase 3.12 performance budget harness is not available in the current local environment",
    "chaos": "Phase 3.12 chaos/fault-injection authority and disposable runtime are not available",
    "soak": "Phase 3.12 soak harness and sustained runtime are not available",
}


def _checkout(root: Path) -> dict[str, object]:
    def run(*args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    status = run("status", "--porcelain", "--untracked-files=all")
    return {
        "commit_sha": run("rev-parse", "HEAD"),
        "status": "CLEAN" if not status else "DIRTY",
        "status_entries": status.splitlines(),
    }


def run_lane(root: Path, lane: str, *, output: Path) -> dict[str, object]:
    checkout = _checkout(root)
    artifact: dict[str, object] = {
        "schema_version": "state-of-art-phase-3-lane.v1",
        "lane": lane,
        "status": "BLOCKED_EXTERNAL",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit_sha": checkout["commit_sha"],
        "environment": "local-hermetic",
        "checkout": checkout,
        "reason": LANES[lane],
        "limitations": [
            "This lane does not claim runtime execution or production readiness.",
            "A future implementation must bind raw measurements, budgets, environment and reviewer to this commit.",
        ],
        "next_action": "Provide an approved disposable runtime and implement the lane-specific executable harness.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", choices=sorted(LANES), required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true", help="fail when the lane is not runtime-verified")
    args = parser.parse_args(argv)
    output = args.output or ROOT / ".runtime" / "phase-3" / f"{args.lane}.json"
    artifact = run_lane(ROOT, args.lane, output=output)
    print(json.dumps({"output": str(output), "lane": args.lane, "status": artifact["status"]}, sort_keys=True))
    return 1 if args.strict and artifact["status"] != "VERIFIED_RUNTIME" else 0


if __name__ == "__main__":
    raise SystemExit(main())
