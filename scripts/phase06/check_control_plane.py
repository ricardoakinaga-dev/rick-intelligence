#!/usr/bin/env python3
"""Validate the cross-repository Phase 0.6 control-plane binding.

This check is intentionally local and deterministic. It proves that the
runtime pointer, published Phase 0.5 commit, active plan/task, backlog, and
append-only ledgers are structurally aligned. It does not claim that tests or
external providers passed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def load_json(relative: str) -> dict:
    path = ROOT / relative
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{relative} must contain a JSON object")
    return value


def load_jsonl(relative: str) -> list[dict]:
    path = ROOT / relative
    records: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError(f"{relative}:{line_number} must be an object")
            records.append(value)
    return records


def main() -> int:
    errors: list[str] = []
    state = load_json(".agent/state.json")
    backlog = load_json(".agent/backlog.json")
    plan_path = state.get("active_execplan")

    if plan_path != ".agent/plans/phase-0.6-promotion-closure.md":
        errors.append(f"active_execplan is {plan_path!r}")
    elif not (ROOT / plan_path).is_file():
        errors.append(f"missing active plan: {plan_path}")

    active_task = state.get("active_task")
    if not isinstance(active_task, str) or not active_task.startswith("PH06-"):
        errors.append(f"active_task is not Phase 0.6: {active_task!r}")

    items = backlog.get("items")
    if not isinstance(items, list):
        errors.append("backlog.items is not a list")
        items = []
    item_ids = {item.get("id") for item in items if isinstance(item, dict)}
    required_tasks = {"PH06-RECON", "PH06-RBAC", "PH06-LEGACY", "PH06-PROVIDER", "PH06-LOCKER-CI", "PH06-INTEGRATE", "PH06-REVIEW"}
    missing_tasks = sorted(required_tasks - item_ids)
    if missing_tasks:
        errors.append(f"missing backlog tasks: {', '.join(missing_tasks)}")

    head = git("rev-parse", "HEAD")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    try:
        remote_sha = git("rev-parse", "origin/main")
    except subprocess.CalledProcessError:
        remote_sha = ""
        errors.append("origin/main is unavailable")
    status_lines = git("status", "--porcelain=v1").splitlines()

    published = state.get("published_phase_0_5_commit")
    if not isinstance(published, dict):
        errors.append("published_phase_0_5_commit is missing")
    else:
        published_sha = published.get("sha")
        if not isinstance(published_sha, str) or len(published_sha) != 40:
            errors.append("published_phase_0_5_commit.sha is not a full SHA")
        else:
            try:
                git("cat-file", "-e", f"{published_sha}^{{commit}}")
            except subprocess.CalledProcessError:
                errors.append("published Phase 0.5 SHA is not present locally")
        if published.get("sha") != published.get("remote_sha"):
            errors.append("published Phase 0.5 SHA and recorded remote SHA differ")

    current = state.get("current_git")
    if not isinstance(current, dict):
        errors.append("current_git is missing")
    else:
        if current.get("head") != head:
            errors.append("state.current_git.head does not match HEAD")
        if current.get("branch") != branch:
            errors.append("state.current_git.branch does not match current branch")
        if remote_sha and current.get("remote_sha") != remote_sha:
            errors.append("state.current_git.remote_sha does not match origin/main")
        expected_worktree = current.get("worktree")
        if expected_worktree == "CLEAN" and status_lines:
            errors.append("state expects a clean worktree but Git reports changes")
        if expected_worktree == "DIRTY_PHASE_0_6" and not status_lines:
            errors.append("state expects Phase 0.6 worktree changes but Git is clean")

    execution = load_jsonl(".agent/execution-log.jsonl")
    verification = load_jsonl(".agent/verification.jsonl")
    if not execution:
        errors.append("execution log is empty")
    if not verification:
        errors.append("verification log is empty")
    if state.get("last_event_id") and execution[-1].get("event_id") != state.get("last_event_id"):
        errors.append("state.last_event_id does not point to the log tail")

    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1

    print("PASS: Phase 0.6 control plane is structurally consistent")
    print(f"HEAD={head}")
    print(f"BRANCH={branch}")
    print(f"ORIGIN_MAIN={remote_sha}")
    print(f"WORKTREE={'DIRTY_PHASE_0_6' if status_lines else 'CLEAN'}")
    print(f"ACTIVE_TASK={active_task}")
    print(f"EXECUTION_EVENTS={len(execution)}")
    print(f"VERIFICATION_RECORDS={len(verification)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"FAIL: {exc}")
        raise SystemExit(1)
