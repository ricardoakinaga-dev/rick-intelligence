#!/usr/bin/env python3
"""Sanitized Phase 1.6 verification matrix."""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHILDREN = ("cvg-master-rag-v2", "rick-professor", "modulo-redis-locker")


def _run(command: list[str], timeout: int = 300) -> dict[str, object]:
    environment = os.environ.copy()
    environment.update({
        "PYTHONDONTWRITEBYTECODE": "1",
        "RAG_SKIP_QDRANT_BOOTSTRAP": "1",
        "OPENAI_API_KEY": "",
        "RICK_ENV": "local",
        "SESSION_COOKIE_SECURE": "false",
    })
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        output = f"{completed.stdout}\n{completed.stderr}"
        passed_match = re.findall(r"(\d+) passed", output)
        return {
            "command": command,
            "exit_code": completed.returncode,
            "passed": completed.returncode == 0,
            "test_pass_count": sum(int(value) for value in passed_match),
        }
    except subprocess.TimeoutExpired:
        return {"command": command, "exit_code": 124, "passed": False, "timed_out": True}


def _git_status(path: str) -> list[str]:
    completed = subprocess.run(
        ["git", "status", "--porcelain=v1", "--", path],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return [line for line in completed.stdout.splitlines() if line.strip()]


def main() -> int:
    commands = [
        ["make", "api16-full"],
        ["make", "api15-full"],
        ["make", "api14-full"],
        ["make", "api-security"],
        ["make", "api-contract"],
        ["git", "diff", "--check"],
    ]
    checks = [_run(command) for command in commands]
    child_status = {child: _git_status(child) for child in CHILDREN}
    benchmark_path = ROOT / "docs" / "progress" / "phase-1.6-perf.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8")) if benchmark_path.is_file() else None
    artifact = {
        "schema_version": 1,
        "phase": "1.6",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "checks": checks,
        "children_clean": all(not values for values in child_status.values()),
        "child_status": child_status,
        "benchmark_present": benchmark is not None,
        "benchmark_bounds": benchmark.get("bounds") if isinstance(benchmark, dict) else None,
        "live_dependencies": {"provider": "NOT_RUN", "qdrant": "NOT_RUN", "redis_locker": "NOT_RUN"},
        "note": "Sanitized local evidence; no live external dependency or production latency claim.",
    }
    output = ROOT / "docs" / "progress" / "phase-1.6-verification.json"
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "phase": artifact["phase"],
        "checks_passed": all(check.get("passed") for check in checks),
        "children_clean": artifact["children_clean"],
        "benchmark_present": artifact["benchmark_present"],
        "artifact": str(output.relative_to(ROOT)),
    }, ensure_ascii=False, indent=2))
    return 0 if all(check.get("passed") for check in checks) and artifact["children_clean"] and artifact["benchmark_present"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
