#!/usr/bin/env python3
"""Execute a bounded CI lane and emit commit-bound local-gate evidence.

The workflow invokes this helper once for each local gate.  Commands are
parsed with :mod:`shlex` and launched without a shell; stdout/stderr are
captured into a bounded, redacted artifact.  A successful process is not
enough for PASS: the GitHub run identity, exact checkout and raw command
artifact must also be present and unchanged.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import time
from typing import Any

try:
    from scripts.state_of_art.phase3_runtime_adapter import redact_runtime_value
    from scripts.state_of_art.release_integrity import capture_checkout
except ImportError:  # pragma: no cover - direct script execution fallback.
    from phase3_runtime_adapter import redact_runtime_value
    from release_integrity import capture_checkout


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "state-of-art-ci-evidence.v1"
DEFAULT_OUTPUT = ".runtime/ci/lane-evidence.json"
MAX_COMMAND_OUTPUT_BYTES = 128 * 1024
MAX_LOG_BYTES = 512 * 1024
DEFAULT_TIMEOUT_SECONDS = 900
MAX_TIMEOUT_SECONDS = 86_400
SHA1_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
SENSITIVE_ENV_NAME = re.compile(
    r"(?:password|passphrase|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|authorization|cookie|credential|dsn)",
    re.IGNORECASE,
)
SENSITIVE_ARGUMENT = re.compile(
    r"(?:password|passphrase|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|authorization|cookie|credential|dsn|url)",
    re.IGNORECASE,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(root: Path, raw: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("evidence output path must be non-empty")
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("evidence output path must remain inside the repository")
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        raise ValueError("evidence output path must remain inside the repository") from None
    return resolved


def _redacted_text(value: str, environment: Mapping[str, str]) -> str:
    redacted = value
    for name, secret in environment.items():
        if SENSITIVE_ENV_NAME.search(name) and secret and len(secret) >= 4:
            redacted = redacted.replace(secret, "[REDACTED]")
    projected = redact_runtime_value(redacted)
    return projected if isinstance(projected, str) else str(projected)


def _redacted_argv(argv: Sequence[str]) -> list[str]:
    result: list[str] = []
    redact_next = False
    for raw in argv:
        value = str(raw)
        if redact_next:
            result.append("[REDACTED]")
            redact_next = False
            continue
        if "=" in value:
            key, _separator, _secret = value.partition("=")
            if SENSITIVE_ARGUMENT.search(key):
                result.append(f"{key}=[REDACTED]")
                continue
        result.append(value)
        if SENSITIVE_ARGUMENT.search(value) and not value.startswith("-"):
            redact_next = True
        elif SENSITIVE_ARGUMENT.search(value.lstrip("-")):
            redact_next = True
    return result


def _command_from_text(value: str) -> tuple[str, ...]:
    try:
        command = tuple(shlex.split(value))
    except ValueError as exc:
        raise ValueError(f"command is not valid shell-free argv: {exc}") from exc
    if not command or any(not part for part in command):
        raise ValueError("command must contain at least one non-empty argv item")
    return command


def _metadata(environment: Mapping[str, str]) -> dict[str, Any]:
    return {
        "actions": environment.get("GITHUB_ACTIONS", "").lower() == "true",
        "event_name": environment.get("GITHUB_EVENT_NAME"),
        "job": environment.get("GITHUB_JOB"),
        "provider": "github-actions",
        "repository": environment.get("GITHUB_REPOSITORY"),
        "ref": environment.get("GITHUB_REF"),
        "run_attempt": environment.get("GITHUB_RUN_ATTEMPT"),
        "run_id": environment.get("GITHUB_RUN_ID"),
        "server_url": environment.get("GITHUB_SERVER_URL"),
        "sha": environment.get("GITHUB_SHA"),
        "workflow": environment.get("GITHUB_WORKFLOW"),
        "workflow_ref": environment.get("GITHUB_WORKFLOW_REF"),
    }


def _metadata_errors(metadata: Mapping[str, Any], checkout: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if metadata.get("actions") is not True:
        errors.append("GitHub Actions provenance is unavailable")
    for field in (
        "workflow",
        "workflow_ref",
        "job",
        "run_id",
        "run_attempt",
        "repository",
        "event_name",
        "ref",
        "sha",
    ):
        if not isinstance(metadata.get(field), str) or not metadata[field].strip():
            errors.append(f"CI provenance field {field} is missing")
    sha = metadata.get("sha")
    head = checkout.get("head")
    if sha and head and (not isinstance(sha, str) or sha.lower() != str(head).lower()):
        errors.append("GITHUB_SHA does not match the observed checkout HEAD")
    return errors


def _checkout_snapshot(checkout: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "available": checkout.get("available") is True,
        "head": checkout.get("head"),
        "tree": checkout.get("tree"),
        "fingerprint": checkout.get("fingerprint"),
        "status": checkout.get("status"),
    }


def _same_checkout(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    return (
        before.get("available") is True
        and after.get("available") is True
        and before.get("status") == "CLEAN"
        and after.get("status") == "CLEAN"
        and all(
            before.get(field) == after.get(field)
            for field in ("head", "tree", "fingerprint", "status")
        )
    )


def _run_commands(
    root: Path,
    commands: Sequence[Sequence[str]],
    *,
    environment: Mapping[str, str],
    log_path: Path,
    timeout_seconds: int,
) -> tuple[list[dict[str, Any]], bool, list[str]]:
    log_parts: list[str] = []
    command_results: list[dict[str, Any]] = []
    limitations: list[str] = []
    all_passed = True
    for index, command in enumerate(commands, start=1):
        started = time.monotonic()
        safe_argv = _redacted_argv(command)
        log_parts.append(f"== command {index}: {shlex.join(safe_argv)}\n")
        try:
            timed_out = False
            process = subprocess.Popen(
                list(command),
                cwd=root,
                env=dict(environment),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                output, _ = process.communicate(timeout=timeout_seconds)
                return_code = process.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except OSError:
                    process.kill()
                try:
                    output, _ = process.communicate(timeout=5)
                except subprocess.TimeoutExpired as timeout_error:
                    output = timeout_error.output or b""
                    try:
                        process.kill()
                    except OSError:
                        pass
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
                    limitations.append(f"command {index} output pipe did not close after termination")
                return_code = None
                output = (output or b"") + b"\ncommand exceeded its bounded timeout and was terminated\n"
            output_truncated = len(output) > MAX_COMMAND_OUTPUT_BYTES
            if output_truncated:
                output = output[:MAX_COMMAND_OUTPUT_BYTES]
                limitations.append(f"command {index} output was truncated at the evidence bound")
            rendered = _redacted_text(output.decode("utf-8", errors="replace"), environment)
            log_parts.append(rendered)
            if not rendered.endswith("\n"):
                log_parts.append("\n")
            exit_status: int | None = return_code
            status = "PASS" if return_code == 0 else "FAIL"
            if timed_out:
                limitations.append(f"command {index} exceeded {timeout_seconds}s")
        except FileNotFoundError as exc:
            exit_status = None
            status = "NOT_RUN"
            output_truncated = False
            log_parts.append(f"command unavailable: {type(exc).__name__}\n")
            limitations.append(f"command {index} could not be started")
        duration_ms = round((time.monotonic() - started) * 1000, 3)
        command_results.append(
            {
                "argv": safe_argv,
                "duration_ms": duration_ms,
                "exit_status": exit_status,
                "index": index,
                "output_truncated": output_truncated,
                "status": status,
            }
        )
        if status != "PASS":
            all_passed = False

    rendered_log = "".join(log_parts).encode("utf-8")
    if len(rendered_log) > MAX_LOG_BYTES:
        rendered_log = rendered_log[:MAX_LOG_BYTES] + b"\n[TRUNCATED_LOG]\n"
        limitations.append("combined command output was truncated at the evidence bound")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_bytes(rendered_log)
    return command_results, all_passed, limitations


def run_lane(
    root: Path,
    lane: str,
    gate_ids: Sequence[str],
    commands: Sequence[Sequence[str]],
    *,
    output: Path,
    log_output: Path | None = None,
    environment: Mapping[str, str] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    root = root.resolve()
    env = dict(os.environ if environment is None else environment)
    output = output.resolve()
    log_path = (log_output or output.with_suffix(".log")).resolve()
    output.relative_to(root)
    log_path.relative_to(root)
    if output == log_path:
        raise ValueError("CI evidence JSON and raw log must be different files")
    normalized_gates = tuple(gate.strip() for gate in gate_ids if isinstance(gate, str) and gate.strip())
    if not normalized_gates or len(set(normalized_gates)) != len(normalized_gates):
        raise ValueError("gate_ids must contain unique non-empty values")
    if not lane.strip():
        raise ValueError("lane must be non-empty")
    if not commands:
        raise ValueError("at least one command is required")
    if timeout_seconds < 1 or timeout_seconds > MAX_TIMEOUT_SECONDS:
        raise ValueError(f"timeout must be between 1 and {MAX_TIMEOUT_SECONDS} seconds")

    # Keep explicit lifecycle timestamps in the envelope.  ``observed_at`` is
    # retained as the historical completion marker, while the start/end pair
    # makes the section 9 contract machine-readable and auditable.
    started_at = _now()
    checkout_before = capture_checkout(root)
    metadata = _metadata(env)
    command_results, commands_passed, limitations = _run_commands(
        root,
        commands,
        environment=env,
        log_path=log_path,
        timeout_seconds=timeout_seconds,
    )
    checkout_after = capture_checkout(root)
    checkout_unchanged = _same_checkout(checkout_before, checkout_after)
    metadata_failures = _metadata_errors(metadata, checkout_before)
    limitations.extend(metadata_failures)
    if not checkout_unchanged:
        limitations.append("checkout identity or clean-worktree sentinel changed during the lane")

    if metadata_failures:
        status = "NOT_RUN"
        exit_status: int | None = None
    elif not commands_passed or not checkout_unchanged:
        status = "FAIL"
        exit_status = 1
    else:
        status = "PASS"
        exit_status = 0

    if not log_path.is_file():
        status = "FAIL"
        exit_status = 1
        limitations.append("raw command artifact could not be written")
    raw_artifacts: list[dict[str, str]] = []
    if log_path.is_file():
        raw_artifacts.append(
            {
                "description": f"bounded redacted command output for CI lane {lane}",
                "path": log_path.relative_to(root).as_posix(),
                "sha256": _sha256(log_path),
            }
        )
    finished_at = _now()
    observed_at = finished_at

    envelope: dict[str, Any] = {
        "artifact_sha256": raw_artifacts[0]["sha256"] if raw_artifacts else None,
        "checkout_available": checkout_after.get("available") is True,
        "checkout_fingerprint": checkout_after.get("fingerprint"),
        "checkout_sentinel": {
            "after": _checkout_snapshot(checkout_after),
            "before": _checkout_snapshot(checkout_before),
            "unchanged": checkout_unchanged,
        },
        "clean_worktree": checkout_after.get("status") == "CLEAN",
        "commands": command_results,
        "commit_sha": checkout_after.get("head"),
        "environment": "github-actions-local-ci",
        "exit_code": exit_status,
        "gate_ids": list(normalized_gates),
        "lane": lane,
        "limitations": limitations
        or ["This envelope proves only the declared local CI commands for its gate IDs."],
        "next_action": (
            "Bind this local CI result to the complete release packet; it does not replace live runtime evidence."
            if status == "PASS"
            else "Repair the CI lane or restore its provenance, then create a new evidence record."
        ),
        "observed_at": observed_at,
        "procedure": f"Execute the declared shell-free commands for CI lane {lane} and gates {', '.join(normalized_gates)}",
        "production_safe": False,
        "promotion_scope": "LOCAL_CI_ONLY",
        "raw_artifacts": raw_artifacts,
        "record_id": f"CI-{lane}-{observed_at.replace('-', '').replace(':', '').replace('.', '')}",
        "run": metadata,
        "schema_version": SCHEMA_VERSION,
        "started_at": started_at,
        "status": status,
        "tree_sha": checkout_after.get("tree"),
        "exit_status": exit_status,
        "finished_at": finished_at,
        "freshness": "CURRENT" if checkout_unchanged else "INVALID_CHECKOUT",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return envelope


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", required=True)
    parser.add_argument("--gate", action="append", dest="gate_ids", required=True)
    parser.add_argument(
        "--command",
        action="append",
        dest="command_texts",
        required=True,
        help="one shell-free command expressed as a shlex-compatible string; repeatable",
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--log-output")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        commands = tuple(_command_from_text(value) for value in args.command_texts)
        root = args.root.resolve()
        output = _safe_relative(root, args.output)
        log_output = _safe_relative(root, args.log_output) if args.log_output else None
        envelope = run_lane(
            root,
            args.lane,
            args.gate_ids,
            commands,
            output=output,
            log_output=log_output,
            timeout_seconds=args.timeout_seconds,
        )
    except (OSError, ValueError) as exc:
        print(f"ci lane evidence failed before envelope creation: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "lane": envelope["lane"],
                "output": str(output),
                "status": envelope["status"],
            },
            sort_keys=True,
        )
    )
    if envelope["status"] == "PASS":
        return 0
    if envelope["status"] == "NOT_RUN":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
