#!/usr/bin/env python3
"""Run an explicit, bounded Phase 3 performance/chaos/soak harness.

The lane is executable when an approved external harness is supplied through
``RICK_PHASE3_<LANE>_COMMAND`` (or ``--command``).  The command is launched
without a shell and must emit one JSON observation on stdout.  Missing
authority, missing output, malformed output, timeouts and contradictory exit
codes remain non-passing; no local stub is promoted as runtime evidence.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shlex
import signal
import subprocess
from typing import Any

try:
    from scripts.state_of_art.json_boundary import loads_json
    from scripts.state_of_art.phase3_runtime_adapter import redact_runtime_value
except ImportError:  # pragma: no cover - direct script execution fallback.
    from json_boundary import loads_json
    from phase3_runtime_adapter import redact_runtime_value


ROOT = Path(__file__).resolve().parents[2]
LANES = frozenset({"performance", "chaos", "soak"})
MAX_OUTPUT_BYTES = 128 * 1024
DEFAULT_TIMEOUT_SECONDS = {
    "performance": 300,
    "chaos": 600,
    "soak": 3_600,
}

# These are part of the observation contract rather than suggestions for a
# harness author.  A zero-exit command with only one happy-path measurement is
# not enough evidence for the prompt's performance, chaos or soak gates.
PERFORMANCE_CONCURRENCY_LEVELS = (1, 10, 50, 100)
PERFORMANCE_WORKLOADS = (
    "api-only",
    "retrieval",
    "chat",
    "ingestion",
    "worker-throughput",
)
PERFORMANCE_METRICS = (
    "p50_ms",
    "p95_ms",
    "p99_ms",
    "throughput",
    "error_rate",
    "cpu_percent",
    "ram_bytes",
    "queue_depth",
)
CHAOS_FAULTS = (
    "kill-worker",
    "kill-worker-a-only",
    "kill-redis",
    "restart-redis",
    "kill-qdrant",
    "restart-qdrant",
    "postgres-outage",
    "s3-outage",
    "provider-timeout",
    "provider-429",
    "provider-500",
    "network-delay",
    "connection-reset",
)
CHAOS_ASSERTIONS = (
    "no_silent_corruption",
    "no_duplicate_publish",
    "bounded_retries",
    "circuit_breaker_correct",
    "eventual_recovery",
)
SOAK_PROFILES = ("short", "extended")
SOAK_METRICS = (
    "memory_bytes",
    "threads",
    "processes",
    "connections",
    "queue_growth",
    "latency_drift_ms",
    "retry_storms",
    "worker_starvation",
    "file_descriptor_leaks",
)
PERFORMANCE_BASELINE_FIELDS = (
    "hardware",
    "container_limits",
    "dataset",
    "provider",
    "model",
    "versions",
)


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
        "tree_sha": run("rev-parse", "HEAD^{tree}"),
        "status": "CLEAN" if not status else "DIRTY",
        "status_entries_count": len(status.splitlines()) if status else 0,
    }


def _command_from_environment(lane: str) -> tuple[str, ...] | None:
    raw = os.environ.get(f"RICK_PHASE3_{lane.upper()}_COMMAND", "").strip()
    if not raw:
        return None
    try:
        command = tuple(shlex.split(raw))
    except ValueError:
        return None
    return command or None


def _safe_number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)):
        return None
    return value


def _require_nonempty(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return bool(value)
    return value is not None


def _validate_performance_observation(
    runtime: Mapping[str, object], measurements: Mapping[str, object]
) -> str | None:
    baseline = runtime.get("baseline")
    if not isinstance(baseline, Mapping):
        return "performance observation has no baseline metadata"
    missing_baseline = [field for field in PERFORMANCE_BASELINE_FIELDS if not _require_nonempty(baseline.get(field))]
    if missing_baseline:
        return "performance baseline metadata is incomplete: " + ", ".join(missing_baseline)
    rows = measurements.get("results")
    if not isinstance(rows, list):
        return "performance observation has no workload/concurrency results"
    expected = {(workload, concurrency) for workload in PERFORMANCE_WORKLOADS for concurrency in PERFORMANCE_CONCURRENCY_LEVELS}
    observed: set[tuple[str, int]] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            return "performance result is not an object"
        workload = row.get("workload")
        concurrency = row.get("concurrency")
        key = (workload, concurrency)
        if workload not in PERFORMANCE_WORKLOADS or type(concurrency) is not int or concurrency not in PERFORMANCE_CONCURRENCY_LEVELS:
            return "performance result has an unsupported workload or concurrency"
        if key in observed:
            return "performance result has duplicate workload/concurrency coverage"
        observed.add(key)
        for metric in PERFORMANCE_METRICS:
            if _safe_number(row.get(metric)) is None:
                return f"performance result is missing finite {metric}"
    missing = sorted(expected - observed, key=lambda item: (item[0], item[1]))
    if missing:
        return "performance result matrix is incomplete"
    return None


def _validate_chaos_observation(measurements: Mapping[str, object]) -> str | None:
    rows = measurements.get("faults")
    if not isinstance(rows, list):
        return "chaos observation has no fault matrix"
    observed: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            return "chaos fault result is not an object"
        fault = row.get("fault")
        if fault not in CHAOS_FAULTS:
            return "chaos fault matrix contains an unsupported fault"
        if fault in observed:
            return "chaos fault matrix contains a duplicate fault"
        observed.add(fault)
        if any(row.get(assertion) is not True for assertion in CHAOS_ASSERTIONS):
            return "chaos fault result does not prove every recovery assertion"
    if observed != set(CHAOS_FAULTS):
        return "chaos fault matrix is incomplete"
    return None


def _validate_soak_observation(measurements: Mapping[str, object]) -> str | None:
    rows = measurements.get("profiles")
    if not isinstance(rows, list):
        return "soak observation has no short/extended profiles"
    observed: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            return "soak profile is not an object"
        profile = row.get("profile")
        if profile not in SOAK_PROFILES:
            return "soak profile has an unsupported name"
        if profile in observed:
            return "soak observation contains a duplicate profile"
        observed.add(profile)
        for metric in SOAK_METRICS:
            value = row.get(metric)
            if metric in {"retry_storms", "worker_starvation", "file_descriptor_leaks"}:
                if value is not False:
                    return f"soak profile does not prove absence of {metric}"
            elif _safe_number(value) is None:
                return f"soak profile is missing finite {metric}"
    if observed != set(SOAK_PROFILES):
        return "soak observation does not include both short and extended profiles"
    return None


def _bounded_projection(value: object, *, depth: int = 0) -> object:
    """Persist only small JSON-safe observation facts, never raw command text."""
    if depth > 2:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        return {
            str(key)[:80]: _bounded_projection(item, depth=depth + 1)
            for key, item in list(value.items())[:32]
            if isinstance(key, (str, int, float, bool))
        }
    if isinstance(value, list):
        return [_bounded_projection(item, depth=depth + 1) for item in value[:32]]
    if isinstance(value, str):
        return value[:512]
    if value is None or isinstance(value, bool):
        return value
    number = _safe_number(value)
    return number if number is not None else "[UNSUPPORTED]"


def _parse_observation(raw: bytes, lane: str) -> tuple[str, dict[str, object], str]:
    if not raw or len(raw) > MAX_OUTPUT_BYTES:
        return "FAIL", {}, "harness output is absent or exceeds the bounded output limit"
    try:
        payload = loads_json(raw, maximum_bytes=MAX_OUTPUT_BYTES)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return "FAIL", {}, "harness output is not one valid JSON object"
    if not isinstance(payload, dict):
        return "FAIL", {}, "harness output is not a JSON object"
    if payload.get("schema_version") != "rick-phase3-operational-observation.v1":
        return "FAIL", {}, "harness output schema is not approved"
    if payload.get("lane") != lane:
        return "FAIL", {}, "harness output lane does not match the requested lane"
    status = payload.get("status")
    if status not in {"PASS", "BLOCKED_EXTERNAL", "FAIL"}:
        return "FAIL", {}, "harness output status is invalid"
    runtime = payload.get("runtime")
    budgets = payload.get("budgets")
    measurements = payload.get("measurements")
    if not isinstance(runtime, dict) or runtime.get("disposable") is not True:
        return "FAIL", {}, "runtime observation is not marked disposable"
    if not isinstance(budgets, dict) or not budgets:
        return "FAIL", {}, "runtime observation has no explicit budgets"
    if not isinstance(measurements, dict):
        return "FAIL", {}, "runtime observation has no measurements"
    # A blocked authority may emit an empty measurement object; only a PASS
    # claim must prove the complete lane-specific matrix. This preserves the
    # distinction between an unavailable harness and an under-specified pass.
    if status == "PASS":
        if lane == "performance":
            validation_error = _validate_performance_observation(runtime, measurements)
            if validation_error:
                return "FAIL", {}, validation_error
        elif lane == "chaos":
            validation_error = _validate_chaos_observation(measurements)
            if validation_error:
                return "FAIL", {}, validation_error
        elif lane == "soak":
            validation_error = _validate_soak_observation(measurements)
            if validation_error:
                return "FAIL", {}, validation_error
    projected = {
        "schema_version": payload["schema_version"],
        "lane": lane,
        "status": status,
        "runtime": redact_runtime_value(_bounded_projection(runtime)),
        "budgets": redact_runtime_value(_bounded_projection(budgets)),
        "measurements": redact_runtime_value(_bounded_projection(measurements)),
        "checks": redact_runtime_value(_bounded_projection(payload.get("checks", {}))),
    }
    return str(status), projected, "approved structured runtime observation received"


def _run_harness(
    command: Sequence[str],
    *,
    root: Path,
    timeout_seconds: int,
    lane: str,
) -> tuple[str, int | None, dict[str, object], str]:
    if not command or any(not isinstance(part, str) or not part for part in command):
        return "BLOCKED_EXTERNAL", None, {}, "approved harness command is not configured"
    try:
        process = subprocess.Popen(
            list(command),
            cwd=root,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return "FAIL", None, {}, "approved harness could not be started"
    try:
        stdout, _ = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        return "FAIL", None, {}, "harness exceeded its bounded timeout and was terminated"
    if process.returncode == 2:
        status, observation, detail = _parse_observation(stdout, lane)
        if status == "BLOCKED_EXTERNAL":
            return status, process.returncode, observation, detail
        return "FAIL", process.returncode, {}, "harness returned blocked code without a matching blocked observation"
    status, observation, detail = _parse_observation(stdout, lane)
    if process.returncode != 0:
        return "FAIL", process.returncode, observation if status != "FAIL" else {}, "harness returned a failure code"
    if status != "PASS":
        return "FAIL", process.returncode, observation, "zero exit code did not produce a PASS observation"
    return status, process.returncode, observation, detail


def run_lane(
    root: Path,
    lane: str,
    *,
    output: Path,
    command: Sequence[str] | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, object]:
    if lane not in LANES:
        raise ValueError(f"unknown lane: {lane}")
    checkout = _checkout(root)
    selected_command = tuple(command) if command is not None else _command_from_environment(lane)
    if selected_command is None:
        status, return_code, observation, detail = (
            "BLOCKED_EXTERNAL",
            2,
            {},
            "approved disposable runtime harness is not configured",
        )
    else:
        status, return_code, observation, detail = _run_harness(
            selected_command,
            root=root,
            timeout_seconds=timeout_seconds or DEFAULT_TIMEOUT_SECONDS[lane],
            lane=lane,
        )
    artifact: dict[str, object] = {
        "schema_version": "state-of-art-phase-3-lane.v2",
        "lane": lane,
        "status": status,
        "exit_status": 0 if status == "PASS" else 2 if status == "BLOCKED_EXTERNAL" else 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit_sha": checkout["commit_sha"],
        "tree_sha": checkout["tree_sha"],
        "environment": "approved-disposable-runtime-harness" if selected_command else "unavailable-external-runtime",
        "checkout": checkout,
        "harness": {
            "configured": selected_command is not None,
            "executable": Path(selected_command[0]).name if selected_command else None,
            "timeout_seconds": timeout_seconds or DEFAULT_TIMEOUT_SECONDS[lane],
            "return_code": return_code,
        },
        "observation": observation,
        "detail": detail,
        "limitations": [
            "The lane proves only the structured assertions emitted by the explicitly supplied harness.",
            "No blocked, malformed or incomplete observation is upgraded to PASS.",
        ],
        "next_action": "Provide an approved disposable harness and rerun this lane on a clean checkout." if not selected_command else "Review the structured measurements and bind them to the complete promotion packet.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", choices=sorted(LANES), required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--command", nargs="+", help="approved harness argv; launched without a shell")
    parser.add_argument("--timeout-seconds", type=int)
    parser.add_argument("--strict", action="store_true", help="return non-zero unless the harness proves PASS")
    args = parser.parse_args(argv)
    timeout = args.timeout_seconds or DEFAULT_TIMEOUT_SECONDS[args.lane]
    if timeout < 1 or timeout > 86_400:
        parser.error("--timeout-seconds must be between 1 and 86400")
    output = args.output or ROOT / ".runtime" / "phase-3" / f"{args.lane}.json"
    artifact = run_lane(ROOT, args.lane, output=output, command=args.command, timeout_seconds=timeout)
    print(json.dumps({"output": str(output), "lane": args.lane, "status": artifact["status"]}, sort_keys=True))
    if not args.strict:
        return 0
    return int(artifact["exit_status"])


if __name__ == "__main__":
    raise SystemExit(main())
