#!/usr/bin/env python3
"""Check the root control-plane pointers without mutating repository state.

This is a structural/control check, not a promotion decision.  It validates
the active plan, machine-readable ledgers, required Phase 0.6 artifacts, and
the Git observation available in the current checkout.  A pull-request merge
checkout is allowed to differ from origin/main; main-sync is enforced only
when the caller requests it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PHASE06_ACTIVE_PLAN = ".agent/plans/phase-0.6-promotion-closure.md"
PHASE11_ACTIVE_PLAN = ".agent/plans/phase-1.1-monorepo-skeleton.md"
PUBLISHED_SHA_RE = re.compile(r"Published root commit:\s*`?([0-9a-f]{40})", re.IGNORECASE)

REQUIRED_FILES = (
    PHASE06_ACTIVE_PLAN,
    ".agent/PLANS.md",
    ".agent/state.json",
    ".agent/backlog.json",
    ".agent/execution-log.jsonl",
    ".agent/verification.jsonl",
    ".agent/gates/phase-0.5-verified-blocked-final.json",
    ".agent/gates/phase-0.6-promotion-final.json",
    ".gauntlet/state.md",
    ".github/workflows/phase-0.6.yml",
    "docs/baselines/phase-0.6-legacy-test-classification.md",
    "docs/baselines/phase-0.6-provider-contract.json",
    "docs/architecture/security/locker-boundary.md",
    "docs/progress/phase-0.6-report.md",
    "docs/progress/phase-0.6-independent-review.md",
    "scripts/phase06/check_locker_boundary.py",
    "scripts/phase06/check_provider_artifact.py",
)

PHASE11_REQUIRED_FILES = (
    PHASE11_ACTIVE_PLAN,
    ".agent/PLANS.md",
    ".agent/state.json",
    ".agent/backlog.json",
    ".agent/execution-log.jsonl",
    ".agent/verification.jsonl",
    ".agent/gates/phase-0.6-promotion-final.json",
    ".agent/gates/phase-1.1-implementation-ready.json",
    ".gauntlet/state.md",
    ".github/workflows/phase-1.1.yml",
    "Makefile",
    "README.md",
    ".env.example",
    "toolchain.json",
    "docs/architecture/dependency-boundaries.json",
    "docs/architecture/dependency-boundaries.md",
    "docs/architecture/preserved-components.json",
    "docs/architecture/migration-map.md",
    "docs/architecture/target-system.md",
    "docs/architecture/toolchain.md",
    "docs/plans/phase-1.1-monorepo-skeleton.md",
    "docs/progress/phase-1.1-report.md",
    "scripts/phase11/check_skeleton.py",
    "scripts/phase11/runner.py",
)


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _git(*args: str) -> tuple[int, str, str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def _load_json(relative: str, errors: list[str]) -> Any | None:
    try:
        return json.loads(_read(relative))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{relative}: invalid JSON ({exc})")
        return None


def _check_jsonl(relative: str, errors: list[str]) -> int:
    try:
        lines = _read(relative).splitlines()
    except OSError as exc:
        errors.append(f"{relative}: unreadable ({exc})")
        return 0

    records = 0
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{relative}:{line_number}: invalid JSONL ({exc})")
        else:
            records += 1
    if records == 0:
        errors.append(f"{relative}: contains no records")
    return records


def _check_phase06_structure(errors: list[str], warnings: list[str]) -> None:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    errors.extend(f"missing required control artifact: {relative}" for relative in missing)
    if missing:
        return

    plan = _read(PHASE06_ACTIVE_PLAN)
    if not PUBLISHED_SHA_RE.search(plan):
        errors.append(f"{PHASE06_ACTIVE_PLAN}: published root commit marker is missing or malformed")
    for marker in ("PH06-CI", "PH06-LOCKER", "PH06-CONTROL"):
        if marker not in plan:
            errors.append(f"{PHASE06_ACTIVE_PLAN}: required marker {marker} is missing")

    state = _load_json(".agent/state.json", errors)
    backlog = _load_json(".agent/backlog.json", errors)
    gate = _load_json(".agent/gates/phase-0.5-verified-blocked-final.json", errors)
    final_gate = _load_json(".agent/gates/phase-0.6-promotion-final.json", errors)
    if isinstance(state, dict):
        if state.get("active_execplan") != PHASE06_ACTIVE_PLAN:
            errors.append(".agent/state.json: active_execplan does not point to the Phase 0.6 plan")
        published = state.get("published_phase_0_5_commit")
        if not isinstance(published, dict) or not re.fullmatch(r"[0-9a-f]{40}", str(published.get("sha", "")), re.IGNORECASE):
            errors.append(".agent/state.json: published_phase_0_5_commit.sha is missing or malformed")
        if state.get("status") not in {"IN_PROGRESS", "READY_FOR_NEXT_STEP", "COMPLETED", "BLOCKED"}:
            errors.append(".agent/state.json: status is not a recognized control-plane state")
    if isinstance(backlog, dict):
        items = backlog.get("items")
        locker_ci = [item for item in items if isinstance(item, dict) and item.get("id") == "PH06-LOCKER-CI"] if isinstance(items, list) else []
        if not locker_ci:
            errors.append(".agent/backlog.json: PH06-LOCKER-CI item is missing")
        elif not locker_ci[0].get("evidence_refs"):
            errors.append(".agent/backlog.json: PH06-LOCKER-CI has no evidence references")
    if isinstance(gate, dict) and gate.get("decision") != "BLOCKED":
        warnings.append("last Phase 0.5 gate is no longer BLOCKED; verify that a superseding gate is present")
    if isinstance(final_gate, dict) and final_gate.get("decision") not in {
        "BLOCKED",
        "INCOMPLETE",
        "FUNCTIONALLY_COMPLETE",
        "VERIFIED_CANDIDATE",
        "PROMOTED",
    }:
        errors.append(".agent/gates/phase-0.6-promotion-final.json: decision is not an allowed final classification")

    execution_records = _check_jsonl(".agent/execution-log.jsonl", errors)
    verification_records = _check_jsonl(".agent/verification.jsonl", errors)
    if execution_records and verification_records:
        print(f"Ledger records: execution={execution_records}, verification={verification_records}")


def _check_phase11_structure(
    errors: list[str],
    warnings: list[str],
    state: dict[str, Any],
) -> None:
    required_files = list(PHASE11_REQUIRED_FILES)
    final_gate_ref = state.get("last_gate_record")
    if final_gate_ref == ".agent/gates/phase-1.1-verified.json":
        required_files.extend(
            [
                ".agent/gates/phase-1.1-verified.json",
                "docs/progress/phase-1.1-independent-review.md",
            ]
        )
    missing = [relative for relative in required_files if not (ROOT / relative).is_file()]
    errors.extend(f"missing required Phase 1.1 control artifact: {relative}" for relative in missing)
    if missing:
        return

    plan = _read(PHASE11_ACTIVE_PLAN)
    for marker in (
        "PH11-REPO",
        "PH11-TOOLCHAIN",
        "PH11-COMMANDS",
        "PH11-BOUNDARIES",
        "PH11-REGRESSION",
        "PH11-DOCS",
        "PH11-REVIEW",
    ):
        if marker not in plan:
            errors.append(f"{PHASE11_ACTIVE_PLAN}: required marker {marker} is missing")

    if state.get("active_execplan") != PHASE11_ACTIVE_PLAN:
        errors.append(".agent/state.json: active_execplan does not point to the Phase 1.1 plan")
    if state.get("status") != "DONE" and not str(state.get("active_task", "")).startswith("PH11-"):
        errors.append(".agent/state.json: active_task does not belong to Phase 1.1")
    if state.get("status") not in {
        "IN_PROGRESS",
        "READY_FOR_NEXT_STEP",
        "COMPLETED",
        "DONE",
        "BLOCKED",
    }:
        errors.append(".agent/state.json: status is not a recognized control-plane state")

    implementation_gate = _load_json(".agent/gates/phase-1.1-implementation-ready.json", errors)
    if isinstance(implementation_gate, dict) and (
        implementation_gate.get("gate_id") != "IMPLEMENTATION_READY"
        or implementation_gate.get("decision") != "PASS"
    ):
        errors.append(".agent/gates/phase-1.1-implementation-ready.json: gate_id/decision is not IMPLEMENTATION_READY/PASS")

    historical_gate = _load_json(".agent/gates/phase-0.6-promotion-final.json", errors)
    if isinstance(historical_gate, dict) and historical_gate.get("decision") != "BLOCKED":
        errors.append(".agent/gates/phase-0.6-promotion-final.json: historical Phase 0.6 decision changed")

    toolchain = _load_json("toolchain.json", errors)
    if isinstance(toolchain, dict) and toolchain.get("schema_version") != "phase-1.1-toolchain.v1":
        errors.append("toolchain.json: schema_version is not phase-1.1-toolchain.v1")
    boundaries = _load_json("docs/architecture/dependency-boundaries.json", errors)
    if isinstance(boundaries, dict) and boundaries.get("schema_version") != "phase-1.1-dependency-boundaries.v1":
        errors.append("docs/architecture/dependency-boundaries.json: schema_version is not phase-1.1-dependency-boundaries.v1")

    backlog = _load_json(".agent/backlog.json", errors)
    if isinstance(backlog, dict):
        items = backlog.get("items")
        ids = {
            item.get("id")
            for item in items
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        } if isinstance(items, list) else set()
        for task_id in ("PH11-SKELETON", "PH11-REVIEW", "PH11-FINAL"):
            if task_id not in ids:
                errors.append(f".agent/backlog.json: {task_id} item is missing")

    if final_gate_ref == ".agent/gates/phase-1.1-verified.json":
        final_gate = _load_json(final_gate_ref, errors)
        if isinstance(final_gate, dict) and (
            final_gate.get("gate_id") != "VERIFIED"
            or final_gate.get("decision") != "PASS"
        ):
            errors.append(f"{final_gate_ref}: gate_id/decision is not VERIFIED/PASS")
    else:
        warnings.append("Phase 1.1 final gate is not recorded yet; control-plane check is pre-final")

    execution_records = _check_jsonl(".agent/execution-log.jsonl", errors)
    verification_records = _check_jsonl(".agent/verification.jsonl", errors)
    if execution_records and verification_records:
        print(f"Ledger records: execution={execution_records}, verification={verification_records}")


def _check_structure(errors: list[str], warnings: list[str]) -> None:
    state = _load_json(".agent/state.json", errors) if (ROOT / ".agent/state.json").is_file() else None
    if isinstance(state, dict) and state.get("active_execplan") == PHASE11_ACTIVE_PLAN:
        _check_phase11_structure(errors, warnings, state)
        return
    _check_phase06_structure(errors, warnings)


def _check_git(args: argparse.Namespace, errors: list[str], warnings: list[str]) -> None:
    head_code, head, head_err = _git("rev-parse", "HEAD^{commit}")
    if head_code != 0 or not re.fullmatch(r"[0-9a-f]{40}", head, re.IGNORECASE):
        errors.append(f"Git HEAD is unavailable or malformed: {head_err or head}")
        return

    branch_code, branch, _ = _git("branch", "--show-current")
    if branch_code != 0 or not branch:
        branch = f"DETACHED ({os.environ.get('GITHUB_REF_NAME', 'CI ref')})"

    status_code, status, status_err = _git("status", "--porcelain", "--untracked-files=all")
    if status_code != 0:
        errors.append(f"Git worktree status failed: {status_err or status}")
        worktree = "UNKNOWN"
    else:
        worktree = "CLEAN" if not status else f"DIRTY ({len(status.splitlines())} entries)"
        if status and args.require_clean:
            errors.append(f"Git worktree is dirty: {len(status.splitlines())} entries")
        elif status:
            warnings.append(f"Git worktree is {worktree}; local dirty state is reported but not rejected")

    remote_code, remote, remote_err = _git("rev-parse", "--verify", "origin/main^{commit}")
    if remote_code != 0 or not re.fullmatch(r"[0-9a-f]{40}", remote, re.IGNORECASE):
        remote = "UNAVAILABLE"
        message = "origin/main is unavailable; remote sync is UNKNOWN"
        if args.require_remote:
            errors.append(message)
        else:
            warnings.append(message)

    if remote != "UNAVAILABLE":
        if head == remote:
            sync = "HEAD_EQ_ORIGIN_MAIN"
        else:
            ancestor_code, _, _ = _git("merge-base", "--is-ancestor", remote, head)
            sync = "HEAD_AHEAD_OF_ORIGIN_MAIN" if ancestor_code == 0 else "DIVERGED"
    else:
        sync = "REMOTE_UNAVAILABLE"

    if args.require_main_sync and (remote == "UNAVAILABLE" or head != remote):
        errors.append("main sync required but HEAD does not equal origin/main")

    print(f"Git: head={head} branch={branch} worktree={worktree} remote_main={remote} sync={sync}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-clean", action="store_true", help="fail when the worktree has changes")
    parser.add_argument("--require-remote", action="store_true", help="fail when origin/main cannot be observed")
    parser.add_argument("--require-main-sync", action="store_true", help="fail unless HEAD equals origin/main")
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []
    _check_structure(errors, warnings)
    _check_git(args, errors, warnings)

    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    if errors:
        print("Control-plane check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("Control-plane check OK: required pointers and current Git observations are structurally consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
