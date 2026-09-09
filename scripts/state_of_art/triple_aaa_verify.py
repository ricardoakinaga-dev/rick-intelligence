#!/usr/bin/env python3
"""Run the fail-closed local and runtime verification packet.

This is an orchestrator, not a score generator.  A mandatory blocked, stale,
not-run or failed lane keeps the result out of promotion.  Output is redacted
and written below the ignored runtime directory so it cannot become a
self-referential release artifact.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ".runtime/phase-2/triple-aaa-verify.json"


@dataclass(frozen=True)
class Lane:
    lane_id: str
    command: tuple[str, ...] | None
    required: bool = True
    external: bool = False
    detail: str = ""


def _run(lane: Lane, *, timeout_seconds: int) -> dict[str, object]:
    if lane.command is None:
        return {
            "id": lane.lane_id,
            "status": "NOT_RUN",
            "required": lane.required,
            "external": lane.external,
            "detail": lane.detail or "lane was not executed",
        }
    try:
        completed = subprocess.run(
            list(lane.command),
            cwd=ROOT,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return {
            "id": lane.lane_id,
            "status": "FAIL",
            "required": lane.required,
            "external": lane.external,
            "detail": "lane exceeded its bounded timeout",
        }
    except OSError:
        return {
            "id": lane.lane_id,
            "status": "FAIL",
            "required": lane.required,
            "external": lane.external,
            "detail": "lane could not be started",
        }
    if completed.returncode == 0:
        status = "PASS"
        detail = lane.detail or "command returned zero"
    elif completed.returncode == 2 and lane.external:
        status = "BLOCKED_EXTERNAL"
        detail = lane.detail or "external dependency gate is blocked"
    else:
        status = "FAIL"
        detail = lane.detail or "command returned non-zero"
    return {
        "id": lane.lane_id,
        "status": status,
        "required": lane.required,
        "external": lane.external,
        "detail": detail,
    }


def _local_lanes() -> tuple[Lane, ...]:
    return (
        Lane("control-plane", ("make", "validate")),
        Lane("ops-static", ("make", "ops-static")),
        Lane("compose-static", ("make", "compose-static")),
        Lane("adversarial-corpus", ("make", "security-adversarial")),
        Lane(
            "release-contract-tests",
            (
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "scripts/state_of_art/tests/test_release_integrity.py",
                "scripts/state_of_art/tests/test_release_manifest.py",
            ),
        ),
        Lane("locking", ("make", "api15-lock")),
        Lane("professor", ("make", "api15-professor")),
        Lane("provider", ("make", "api15-provider")),
        Lane("domain", ("make", "api16-domain")),
        Lane("worker", ("make", "api16-worker")),
        Lane("api-root", ("make", "api16-root")),
        Lane("api-contract", ("make", "api-contract")),
        Lane("web-lint", ("make", "web-lint")),
        Lane("web-typecheck", ("make", "web-typecheck")),
        Lane("web-build", ("make", "web-build")),
    )


def _external_lanes() -> tuple[Lane, ...]:
    browser_available = any(
        shutil.which(name)
        for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")
    )
    return (
        Lane("postgresql-runtime", ("make", "postgres-runtime"), external=True),
        Lane("redis-runtime", ("make", "redis-runtime"), external=True),
        Lane("object-qdrant-runtime", ("make", "object-qdrant-runtime"), external=True),
        Lane(
            "frontend-e2e",
            ("make", "web-e2e") if browser_available else None,
            external=True,
            detail="browser/runtime/API authority is unavailable" if not browser_available else "browser E2E command returned",
        ),
        Lane(
            "ingestion-e2e",
            None,
            external=True,
            detail="full API→queue→worker→object→vector lifecycle requires disposable services",
        ),
        Lane("restore-drill", None, external=True, detail="restore authority and disposable backups are unavailable"),
        Lane("chaos", None, external=True, detail="fault-injection authority and isolated runtime are unavailable"),
        Lane("soak", None, external=True, detail="bounded load environment is unavailable"),
        Lane("performance", None, external=True, detail="production-shaped workload environment is unavailable"),
        Lane("independent-reviews", None, external=True, detail="fresh independent reviewers are not executable in this process"),
    )


def _release_gate() -> Lane:
    return Lane(
        "release-integrity",
        (
            sys.executable,
            "scripts/state_of_art/release_integrity.py",
            "--require-clean",
            "--evidence",
            "docs/progress/release-evidence.json",
        ),
        external=True,
        detail="typed release evidence is not promotable until the checkout is clean and all mandatory gates pass",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--lane-timeout", type=int, default=300)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.lane_timeout < 10 or args.lane_timeout > 3_600:
        parser.error("--lane-timeout must be between 10 and 3600 seconds")

    results: list[dict[str, object]] = []
    for lane in _local_lanes():
        results.append(_run(lane, timeout_seconds=args.lane_timeout))
    # Generation is intentionally separate from validation: a truthful FAIL or
    # BLOCKED manifest must exist before the release-integrity verifier runs.
    results.append(_run(Lane("release-evidence-generation", ("make", "release-evidence")), timeout_seconds=args.lane_timeout))
    results.append(_run(_release_gate(), timeout_seconds=args.lane_timeout))
    for lane in _external_lanes():
        results.append(_run(lane, timeout_seconds=args.lane_timeout))

    required = [item for item in results if item["required"] is True]
    if any(item["status"] == "FAIL" and item["external"] is not True for item in required):
        verdict = "FAIL"
        exit_code = 1
    elif any(item["status"] != "PASS" for item in required):
        verdict = "STATE_OF_ART_CANDIDATE"
        exit_code = 2
    else:
        verdict = "TRIPLE_AAA"
        exit_code = 0

    payload = {
        "schema_version": "state-of-art-triple-aaa-verify.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "promotion_allowed": verdict == "TRIPLE_AAA",
        "results": results,
        "limitations": [
            "This packet is only current for the exact checkout and environment that produced it.",
            "A blocked or not-run required lane prevents promotion; no score averaging is performed.",
        ],
    }
    output = (ROOT / args.output).resolve()
    output.relative_to(ROOT.resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": args.output, "verdict": verdict}, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
