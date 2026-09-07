#!/usr/bin/env python3
"""Fail-closed state, fingerprint, and recovery helper for Gauntlet runs."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Any, Iterator
import uuid

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised only on non-POSIX hosts
    fcntl = None


STATE_SCHEMA_VERSION = 2
BAR_SCHEMA_VERSION = 1
PHASES = {
    "DISCOVER",
    "DEFINE_GOAL",
    "DEFINE_BAR",
    "DECOMPOSE",
    "BUILD_RUN",
    "CRITIQUE",
    "FIX_RETEST",
    "INTEGRATE",
    "FINAL_GAUNTLET",
    "STOP",
}
STATE_FIELDS = {
    "schema_version", "run_id", "status", "mode", "phase", "goal", "bar", "repository",
    "artifact_fingerprint", "capabilities", "budget", "usage", "round_count",
    "evidence_freshness", "current_gap", "latest_verification", "blocker", "next_action",
    "created_at", "updated_at", "stop",
}
ALLOWED_TRANSITIONS = {
    "DECOMPOSE": {"DECOMPOSE", "BUILD_RUN", "CRITIQUE"},
    "BUILD_RUN": {"BUILD_RUN", "CRITIQUE"},
    "CRITIQUE": {"CRITIQUE", "FIX_RETEST", "FINAL_GAUNTLET"},
    "FIX_RETEST": {"FIX_RETEST", "BUILD_RUN", "CRITIQUE", "INTEGRATE"},
    "INTEGRATE": {"INTEGRATE", "CRITIQUE", "FINAL_GAUNTLET"},
    "FINAL_GAUNTLET": {"FINAL_GAUNTLET", "BUILD_RUN", "CRITIQUE", "FIX_RETEST", "INTEGRATE"},
}
EVIDENCE_STATUSES = {"PASS", "FAIL", "NOT_RUN", "BLOCKED", "INVALID", "STALE"}
DECISIONS = {"APPROVE", "REJECT", "BLOCKED", "INVALID"}
INDEPENDENCE = {"I0", "I1", "I2", "I3"}
VERDICTS = {"PASS", "CONDITIONAL_PASS", "FAIL"}


class StateError(RuntimeError):
    """Raised when state cannot be trusted."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise StateError(f"refusing symlink JSON file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise StateError(f"missing JSON file: {path}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise StateError(f"invalid JSON file {path}: {error}") from error
    if not isinstance(value, dict):
        raise StateError(f"JSON root must be an object: {path}")
    return value


def canonical_repo(raw: str) -> Path:
    try:
        repo = Path(raw).expanduser().resolve(strict=True)
    except OSError as error:
        raise StateError(f"repository cannot be resolved: {raw}: {error}") from error
    if not repo.is_dir():
        raise StateError(f"repository is not a directory: {repo}")
    return repo


def is_within(root: Path, candidate: Path) -> bool:
    try:
        return os.path.commonpath((str(root), str(candidate))) == str(root)
    except ValueError:
        return False


def gauntlet_dir(repo: Path, *, create: bool = False) -> Path:
    target = repo / ".gauntlet"
    if target.is_symlink():
        raise StateError(f"refusing symlink state directory: {target}")
    if target.exists() and not target.is_dir():
        raise StateError(f"state path exists and is not a directory: {target}")
    if create and not target.exists():
        target.mkdir(mode=0o700, exist_ok=True)
    if target.is_symlink():
        raise StateError(f"refusing symlink state directory: {target}")
    if target.exists():
        resolved = target.resolve(strict=True)
        if not is_within(repo, resolved) or resolved.parent != repo:
            raise StateError(f"state directory escapes repository root: {target}")
    return target


def atomic_write(path: Path, text: str, *, mode: int = 0o600) -> None:
    if path.is_symlink():
        raise StateError(f"refusing to replace symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temp_path.unlink()


@contextlib.contextmanager
def writer_lock(directory: Path) -> Iterator[None]:
    lock = directory / ".writer.lock"
    if lock.is_symlink():
        raise StateError(f"refusing symlink writer lock: {lock}")
    payload = canonical_json({"pid": os.getpid(), "created_at": utc_now()}) + "\n"
    if fcntl is not None:
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(lock, flags, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise StateError(f"another state writer is active: {lock}") from error
            os.ftruncate(fd, 0)
            os.write(fd, payload.encode("utf-8"))
            os.fsync(fd)
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        return
    try:  # Portable fail-closed fallback. A crash requires operator inspection.
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:  # pragma: no cover - non-POSIX only
        raise StateError(f"another writer may be active; inspect without deleting: {lock}") from error
    try:  # pragma: no cover - non-POSIX only
        os.write(fd, payload.encode("utf-8"))
        os.fsync(fd)
        yield
    finally:
        os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            lock.unlink()


def fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def transaction_path(directory: Path) -> Path:
    return directory / ".transaction.json"


def validate_transaction(directory: Path, transaction: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if transaction.get("schema_version") != 1:
        errors.append("transaction.schema_version must be 1")
    writes = transaction.get("writes")
    if not isinstance(writes, list) or not writes:
        return errors + ["transaction.writes must be a non-empty array"]
    allowed = {"bar.json", "history.jsonl", "artifacts.jsonl", "state.json", "progress.md"}
    seen: set[str] = set()
    for index, item in enumerate(writes):
        if not isinstance(item, dict):
            errors.append(f"transaction.writes[{index}] must be an object")
            continue
        name = item.get("name")
        content = item.get("content")
        if name not in allowed or name in seen:
            errors.append(f"transaction.writes[{index}].name is invalid or duplicated")
        else:
            seen.add(name)
        if not isinstance(content, str):
            errors.append(f"transaction.writes[{index}].content must be text")
        elif sha256_bytes(content.encode("utf-8")) != item.get("sha256"):
            errors.append(f"transaction.writes[{index}] hash differs")
        if item.get("mode") not in {0o600, 0o644}:
            errors.append(f"transaction.writes[{index}].mode is invalid")
    return errors


def transactional_write(directory: Path, writes: dict[str, tuple[str, int]]) -> None:
    journal = transaction_path(directory)
    if journal.exists() or journal.is_symlink():
        raise StateError(f"pending or unsafe transaction exists; run recover after inspection: {journal}")
    transaction = {
        "schema_version": 1,
        "created_at": utc_now(),
        "writes": [
            {
                "name": name,
                "content": content,
                "sha256": sha256_bytes(content.encode("utf-8")),
                "mode": mode,
            }
            for name, (content, mode) in sorted(writes.items())
        ],
    }
    errors = validate_transaction(directory, transaction)
    if errors:
        raise StateError("invalid internal transaction: " + "; ".join(errors))
    atomic_write(journal, json.dumps(transaction, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    for item in transaction["writes"]:
        atomic_write(directory / item["name"], item["content"], mode=item["mode"])
    journal.unlink()
    fsync_directory(directory)


def replay_transaction(directory: Path) -> list[str]:
    journal = transaction_path(directory)
    if not journal.exists():
        raise StateError("no pending transaction to recover")
    transaction = read_json(journal)
    errors = validate_transaction(directory, transaction)
    if errors:
        raise StateError("unsafe pending transaction: " + "; ".join(errors))
    recovered: list[str] = []
    for item in transaction["writes"]:
        atomic_write(directory / item["name"], item["content"], mode=item["mode"])
        recovered.append(item["name"])
    journal.unlink()
    fsync_directory(directory)
    return recovered


def git_bytes(repo: Path, args: list[str]) -> bytes | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def path_record(repo: Path, relative: str) -> dict[str, Any]:
    candidate = repo / relative
    try:
        info = candidate.lstat()
    except OSError as error:
        return {"path": relative, "type": "unreadable", "error": type(error).__name__}
    if stat.S_ISLNK(info.st_mode):
        return {
            "path": relative,
            "type": "symlink",
            "target_sha256": sha256_bytes(os.readlink(candidate).encode("utf-8")),
        }
    if stat.S_ISREG(info.st_mode):
        return {
            "path": relative,
            "type": "file",
            "size": info.st_size,
            "sha256": sha256_file(candidate),
        }
    return {"path": relative, "type": "other", "mode": stat.S_IFMT(info.st_mode)}


def git_fingerprint(repo: Path, *, include_state: bool) -> dict[str, Any] | None:
    root_raw = git_bytes(repo, ["rev-parse", "--show-toplevel"])
    head_raw = git_bytes(repo, ["rev-parse", "--verify", "HEAD"])
    if root_raw is None or head_raw is None:
        return None
    git_root = Path(root_raw.decode("utf-8", errors="replace").strip()).resolve()
    if not is_within(git_root, repo):
        raise StateError(f"repository path is outside detected git root: {git_root}")
    pathspec = ["--", "."] + ([] if include_state else [":(exclude).gauntlet/**"])
    index_diff = git_bytes(repo, ["diff", "--cached", "--binary", *pathspec])
    worktree_diff = git_bytes(repo, ["diff", "--binary", *pathspec])
    if index_diff is None or worktree_diff is None:
        raise StateError("git fingerprint commands failed")
    return {
        "kind": "git",
        "git_root": str(git_root),
        "head": head_raw.decode("ascii", errors="replace").strip(),
        "index_diff_sha256": sha256_bytes(index_diff),
        "worktree_diff_sha256": sha256_bytes(worktree_diff),
        "tree": repository_records(repo, include_state=include_state),
    }


def repository_records(repo: Path, *, include_state: bool) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for root, directories, files in os.walk(repo, topdown=True, followlinks=False):
        root_path = Path(root)
        kept: list[str] = []
        for name in sorted(directories):
            if name == ".git" or (name == ".gauntlet" and not include_state):
                continue
            candidate = root_path / name
            if candidate.is_symlink():
                records.append(path_record(repo, str(candidate.relative_to(repo))))
            else:
                kept.append(name)
        directories[:] = kept
        for name in sorted(files):
            relative = str((root_path / name).relative_to(repo))
            records.append(path_record(repo, relative))
    return sorted(records, key=lambda item: item["path"])


def filesystem_fingerprint(repo: Path) -> dict[str, Any]:
    records = repository_records(repo, include_state=False)
    return {"kind": "filesystem", "files": records}


def fingerprint(repo: Path, *, include_state: bool = False) -> dict[str, Any]:
    payload = git_fingerprint(repo, include_state=include_state) or (
        {"kind": "filesystem", "files": repository_records(repo, include_state=include_state)}
    )
    return {
        "algorithm": "sha256-v1",
        "scope": "repository+state" if include_state else "artifact",
        "digest": sha256_bytes(canonical_json(payload).encode("utf-8")),
        "details": payload,
        "captured_at": utc_now(),
    }


def validate_bar(bar: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if bar.get("schema_version") != BAR_SCHEMA_VERSION:
        errors.append(f"bar.schema_version must be {BAR_SCHEMA_VERSION}")
    for key in ("version", "frozen_at", "goal"):
        if not isinstance(bar.get(key), str) or not bar[key].strip():
            errors.append(f"bar.{key} must be a non-empty string")
    sources = bar.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("bar.sources must be a non-empty array")
    else:
        for index, source in enumerate(sources):
            prefix = f"bar.sources[{index}]"
            if not isinstance(source, dict):
                errors.append(f"{prefix} must be an object")
                continue
            for key in ("type", "location", "version", "snapshot_sha256", "license_notes"):
                if key not in source:
                    errors.append(f"{prefix} missing {key}")
            if source.get("type") not in {"USER", "REPO", "STANDARD", "REFERENCE", "DERIVED"}:
                errors.append(f"{prefix}.type is invalid")
            for key in ("location", "version", "license_notes"):
                if not isinstance(source.get(key), str) or not source[key].strip():
                    errors.append(f"{prefix}.{key} must be non-empty")
            snapshot = source.get("snapshot_sha256")
            if snapshot is not None and (not isinstance(snapshot, str) or len(snapshot) != 64 or any(c not in "0123456789abcdef" for c in snapshot)):
                errors.append(f"{prefix}.snapshot_sha256 must be null or a SHA-256 digest")
    criteria = bar.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        errors.append("bar.criteria must be a non-empty array")
        return errors
    ids: set[str] = set()
    required_fields = {
        "id",
        "source_type",
        "source",
        "dimension",
        "target",
        "evidence_method",
        "required",
        "priority",
        "baseline",
        "conditions",
        "version",
        "snapshot_sha256",
        "license_notes",
        "validity_notes",
    }
    for index, criterion in enumerate(criteria):
        prefix = f"bar.criteria[{index}]"
        if not isinstance(criterion, dict):
            errors.append(f"{prefix} must be an object")
            continue
        missing = sorted(required_fields - set(criterion))
        if missing:
            errors.append(f"{prefix} missing fields: {', '.join(missing)}")
        criterion_id = criterion.get("id")
        if not isinstance(criterion_id, str) or not criterion_id.strip():
            errors.append(f"{prefix}.id must be non-empty")
        elif criterion_id in ids:
            errors.append(f"duplicate criterion id: {criterion_id}")
        else:
            ids.add(criterion_id)
        if criterion.get("source_type") not in {"USER", "REPO", "STANDARD", "REFERENCE", "DERIVED"}:
            errors.append(f"{prefix}.source_type is invalid")
        if not isinstance(criterion.get("required"), bool):
            errors.append(f"{prefix}.required must be boolean")
        if criterion.get("priority") not in {"critical", "high", "medium", "low"}:
            errors.append(f"{prefix}.priority is invalid")
        baseline = criterion.get("baseline")
        if not isinstance(baseline, dict) or baseline.get("status") not in EVIDENCE_STATUSES or "actual" not in baseline:
            errors.append(f"{prefix}.baseline must contain a valid status and actual value")
        snapshot = criterion.get("snapshot_sha256")
        if snapshot is not None and (not isinstance(snapshot, str) or len(snapshot) != 64 or any(c not in "0123456789abcdef" for c in snapshot)):
            errors.append(f"{prefix}.snapshot_sha256 must be null or a SHA-256 digest")
    if not isinstance(bar.get("revision_log", []), list):
        errors.append("bar.revision_log must be an array")
    return errors


def validate_capabilities(capabilities: Any) -> list[str]:
    if not isinstance(capabilities, dict):
        return ["capabilities must be an object"]
    errors: list[str] = []
    expected = {"fresh_context", "filesystem_isolation", "max_concurrency", "wait_supported", "notes"}
    if extras := sorted(set(capabilities) - expected):
        errors.append("capabilities has unknown fields: " + ", ".join(extras))
    for key in ("fresh_context", "wait_supported"):
        if not isinstance(capabilities.get(key), bool):
            errors.append(f"capabilities.{key} must be boolean")
    if not isinstance(capabilities.get("filesystem_isolation"), str) or not capabilities["filesystem_isolation"].strip():
        errors.append("capabilities.filesystem_isolation must be non-empty")
    if not isinstance(capabilities.get("max_concurrency"), int) or capabilities["max_concurrency"] < 1:
        errors.append("capabilities.max_concurrency must be a positive integer")
    if not isinstance(capabilities.get("notes"), str):
        errors.append("capabilities.notes must be a string")
    return errors


def validate_budget(budget: Any) -> list[str]:
    if not isinstance(budget, dict):
        return ["budget must be an object"]
    errors: list[str] = []
    expected = {"max_agent_depth", "max_concurrency", "time", "tokens", "retry_policy"}
    if extras := sorted(set(budget) - expected):
        errors.append("budget has unknown fields: " + ", ".join(extras))
    if not isinstance(budget.get("max_agent_depth"), int) or budget["max_agent_depth"] < 0:
        errors.append("budget.max_agent_depth must be a non-negative integer")
    if not isinstance(budget.get("max_concurrency"), int) or budget["max_concurrency"] < 1:
        errors.append("budget.max_concurrency must be a positive integer")
    retries = budget.get("retry_policy")
    if not isinstance(retries, dict):
        errors.append("budget.retry_policy must be an object")
    else:
        if extras := sorted(set(retries) - {"deterministic", "flaky", "network", "preserve_first_failure"}):
            errors.append("budget.retry_policy has unknown fields: " + ", ".join(extras))
        for key in ("deterministic", "flaky", "network"):
            if not isinstance(retries.get(key), int) or retries[key] < 0:
                errors.append(f"budget.retry_policy.{key} must be a non-negative integer")
        if retries.get("preserve_first_failure") is not True:
            errors.append("budget.retry_policy.preserve_first_failure must be true")
    for key in ("time", "tokens"):
        value = budget.get(key)
        if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool)):
            errors.append(f"budget.{key} must be null or a non-negative number")
        elif isinstance(value, (int, float)) and value < 0:
            errors.append(f"budget.{key} must not be negative")
    return errors


def validate_usage(usage: Any, budget: dict[str, Any], capabilities: dict[str, Any]) -> list[str]:
    if not isinstance(usage, dict):
        return ["usage must be an object"]
    errors: list[str] = []
    expected = {"agent_peak", "agent_depth_peak", "tool_calls", "retries", "tokens", "elapsed_seconds"}
    if extras := sorted(set(usage) - expected):
        errors.append("usage has unknown fields: " + ", ".join(extras))
    for key in ("agent_peak", "agent_depth_peak", "tool_calls", "retries", "tokens", "elapsed_seconds"):
        if not isinstance(usage.get(key), (int, float)) or isinstance(usage.get(key), bool) or usage[key] < 0:
            errors.append(f"usage.{key} must be a non-negative number")
    if not errors:
        if usage["agent_peak"] > min(budget["max_concurrency"], capabilities["max_concurrency"]):
            errors.append("usage.agent_peak exceeds the frozen concurrency envelope")
        if usage["agent_depth_peak"] > budget["max_agent_depth"]:
            errors.append("usage.agent_depth_peak exceeds the frozen delegation depth")
        if isinstance(budget.get("tokens"), (int, float)) and usage["tokens"] > budget["tokens"]:
            errors.append("usage.tokens exceeds budget")
        if isinstance(budget.get("time"), (int, float)) and usage["elapsed_seconds"] > budget["time"]:
            errors.append("usage.elapsed_seconds exceeds budget")
    return errors


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink():
        raise StateError(f"refusing symlink JSONL file: {path}")
    if not path.exists():
        raise StateError(f"missing JSONL file: {path}")
    values: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise StateError(f"invalid JSONL at {path}:{number}: {error}") from error
        if not isinstance(value, dict):
            raise StateError(f"JSONL item must be an object at {path}:{number}")
        values.append(value)
    return values


def jsonl_text(values: list[dict[str, Any]]) -> str:
    return "".join(canonical_json(value) + "\n" for value in values)


def append_history(history: list[dict[str, Any]], event: dict[str, Any]) -> None:
    chained = dict(event)
    chained["previous_event_sha256"] = history[-1].get("event_sha256") if history else None
    chained["event_sha256"] = sha256_bytes(canonical_json(chained).encode("utf-8"))
    history.append(chained)


def validate_history(history: list[dict[str, Any]], bar_ids: set[str]) -> list[str]:
    errors: list[str] = []
    previous: str | None = None
    expected_round = 1
    for index, item in enumerate(history):
        prefix = f"history[{index}]"
        recorded_hash = item.get("event_sha256")
        unhashed = dict(item)
        unhashed.pop("event_sha256", None)
        if item.get("previous_event_sha256") != previous:
            errors.append(f"{prefix} breaks the event chain")
        calculated = sha256_bytes(canonical_json(unhashed).encode("utf-8"))
        if recorded_hash != calculated:
            errors.append(f"{prefix} hash differs")
        if item.get("event") == "round":
            if item.get("round") != expected_round:
                errors.append(f"{prefix} round sequence is invalid")
            errors.extend(f"{prefix}.{error}" for error in validate_round(item, bar_ids))
            if not isinstance(item.get("post_fingerprint"), str):
                errors.append(f"{prefix}.post_fingerprint is invalid")
            expected_round += 1
        elif item.get("event") == "rebaseline":
            for key in ("recorded_at", "reason", "previous_fingerprint", "new_fingerprint", "effect"):
                if not isinstance(item.get(key), str) or not item[key].strip():
                    errors.append(f"{prefix}.{key} must be non-empty")
        elif item.get("event") == "finish":
            if item.get("verdict") not in VERDICTS or not isinstance(item.get("verification"), dict):
                errors.append(f"{prefix} finish event is invalid")
        else:
            errors.append(f"{prefix}.event is invalid")
        previous = recorded_hash if isinstance(recorded_hash, str) else None
    return errors


def validate_state(repo: Path, state: dict[str, Any], *, check_drift: bool) -> list[str]:
    errors: list[str] = []
    directory = gauntlet_dir(repo)
    journal = transaction_path(directory)
    if journal.exists() or journal.is_symlink():
        errors.append("pending state transaction detected; run the recover command before continuing")
    missing = sorted(STATE_FIELDS - set(state))
    if missing:
        errors.append(f"state missing fields: {', '.join(missing)}")
        return errors
    if extras := sorted(set(state) - STATE_FIELDS):
        errors.append(f"state contains unknown fields: {', '.join(extras)}")
    schema_version = state.get("schema_version")
    if schema_version != STATE_SCHEMA_VERSION:
        if schema_version == 1:
            errors.append(
                "state schema v1 cannot be migrated safely because it lacks the frozen bar and "
                "artifact identity; preserve it, then initialize a v2 run and re-run required gates"
            )
        else:
            errors.append(f"state.schema_version must be {STATE_SCHEMA_VERSION}")
    if state.get("status") not in {"ACTIVE", "FINISHED"}:
        errors.append("state.status is invalid")
    if state.get("mode") not in {"audit", "execute"}:
        errors.append("state.mode is invalid")
    if state.get("phase") not in PHASES:
        errors.append("state.phase is invalid")
    if state.get("status") == "FINISHED" and (state.get("phase") != "STOP" or not isinstance(state.get("stop"), dict)):
        errors.append("finished state requires STOP phase and stop record")
    if state.get("status") == "ACTIVE" and state.get("stop") is not None:
        errors.append("active state cannot contain a stop record")
    if state.get("evidence_freshness") not in {"CURRENT", "STALE", "INVALID", "MISSING"}:
        errors.append("state.evidence_freshness is invalid")
    repository = state.get("repository")
    if not isinstance(repository, dict) or repository.get("root") != str(repo):
        errors.append("state repository root does not match resolved repository")
    elif set(repository) != {"root", "head_at_init"}:
        errors.append("state repository fields differ from schema")
    artifact_fingerprint = state.get("artifact_fingerprint")
    if (
        not isinstance(artifact_fingerprint, dict)
        or artifact_fingerprint.get("algorithm") != "sha256-v1"
        or artifact_fingerprint.get("scope") != "artifact"
        or not isinstance(artifact_fingerprint.get("digest"), str)
        or len(artifact_fingerprint.get("digest", "")) != 64
        or any(character not in "0123456789abcdef" for character in artifact_fingerprint.get("digest", ""))
    ):
        errors.append("state artifact_fingerprint is invalid")
    elif set(artifact_fingerprint) != {"algorithm", "scope", "digest", "details", "captured_at"}:
        errors.append("state artifact_fingerprint fields differ from schema")
    errors.extend(f"state.{error}" for error in validate_capabilities(state.get("capabilities")))
    errors.extend(f"state.{error}" for error in validate_budget(state.get("budget")))
    if isinstance(state.get("budget"), dict) and isinstance(state.get("capabilities"), dict):
        errors.extend(f"state.{error}" for error in validate_usage(state.get("usage"), state["budget"], state["capabilities"]))
    if not isinstance(state.get("run_id"), str) or not state["run_id"].strip():
        errors.append("state.run_id must be a non-empty string")
    if not isinstance(state.get("round_count"), int) or state["round_count"] < 0:
        errors.append("state.round_count must be a non-negative integer")
    for key in ("created_at", "updated_at"):
        if not isinstance(state.get(key), str) or not state[key].strip():
            errors.append(f"state.{key} must be a non-empty timestamp")
    goal = state.get("goal")
    if not isinstance(goal, dict) or sha256_bytes(str(goal.get("text", "")).encode("utf-8")) != goal.get("sha256"):
        errors.append("state goal hash is invalid")
    elif set(goal) != {"text", "sha256"}:
        errors.append("state goal fields differ from schema")
    bar_path = directory / "bar.json"
    try:
        bar = read_json(bar_path)
        errors.extend(validate_bar(bar))
        state_bar = state.get("bar")
        if not isinstance(state_bar, dict):
            errors.append("state.bar must be an object")
        elif set(state_bar) != {"version", "path", "sha256"}:
            errors.append("state bar fields differ from schema")
        elif sha256_bytes(canonical_json(bar).encode("utf-8")) != state_bar.get("sha256"):
            errors.append("frozen bar hash differs from state")
        elif state_bar.get("version") != bar.get("version") or state_bar.get("path") != ".gauntlet/bar.json":
            errors.append("state bar identity differs from frozen bar")
    except StateError as error:
        errors.append(str(error))
    try:
        history = load_jsonl(directory / "history.jsonl")
        round_events = [item for item in history if item.get("event") == "round"]
        bar_ids = {item.get("id") for item in bar.get("criteria", []) if isinstance(item, dict)} if "bar" in locals() else set()
        errors.extend(validate_history(history, bar_ids))
        if isinstance(state.get("round_count"), int) and len(round_events) != state.get("round_count"):
            errors.append("state.round_count does not match history")
        finish_events = [item for item in history if item.get("event") == "finish"]
        if state.get("status") == "FINISHED" and len(finish_events) != 1:
            errors.append("finished state requires exactly one finish event")
        elif state.get("status") == "FINISHED" and finish_events:
            event_stop = {
                key: value for key, value in finish_events[0].items()
                if key not in {"event", "previous_event_sha256", "event_sha256"}
            }
            if canonical_json(event_stop) != canonical_json(state.get("stop")):
                errors.append("state stop record differs from the authenticated finish event")
            elif "bar" in locals() and isinstance(bar, dict) and isinstance(state.get("capabilities"), dict):
                prior_critic_ids = {
                    str(item.get("critic", {}).get("critic_id"))
                    for item in history
                    if item.get("event") == "round"
                    and isinstance(item.get("critic"), dict)
                    and item["critic"].get("critic_id")
                }
                errors.extend(
                    "finish." + error
                    for error in validate_final(
                        event_stop.get("verification", {}),
                        bar,
                        artifact_fingerprint.get("digest", "") if isinstance(artifact_fingerprint, dict) else "",
                        event_stop.get("verdict", ""),
                        prior_critic_ids,
                        state["capabilities"],
                        state.get("mode", ""),
                        run_id=state["run_id"],
                        evidence_not_before=evidence_epoch(state, history),
                        validated_at=event_stop.get("finished_at"),
                    )
                )
        if state.get("status") == "ACTIVE" and finish_events:
            errors.append("active state cannot contain a finish event")
    except StateError as error:
        errors.append(str(error))
    try:
        artifacts = load_jsonl(directory / "artifacts.jsonl")
        for index, artifact in enumerate(artifacts):
            if artifact.get("event") != "artifact" or not isinstance(artifact.get("path"), str):
                errors.append(f"artifact manifest item {index} is invalid")
            recorded_hash = artifact.get("sha256")
            recorded_path = Path(str(artifact.get("path", "")))
            try:
                resolved_path = recorded_path.resolve(strict=True)
            except OSError:
                resolved_path = recorded_path
            if not is_within(repo, resolved_path):
                errors.append(f"artifact manifest item {index} escapes repository root")
            if recorded_hash is not None and (not recorded_path.is_file() or recorded_path.is_symlink()):
                errors.append(f"artifact manifest item {index} no longer resolves to a regular file")
            elif recorded_hash is not None and sha256_file(recorded_path) != recorded_hash:
                errors.append(f"artifact manifest item {index} hash differs")
    except StateError as error:
        errors.append(str(error))
    if check_drift and not errors:
        current = fingerprint(repo)
        expected = artifact_fingerprint.get("digest") if isinstance(artifact_fingerprint, dict) else None
        if current["digest"] != expected:
            errors.append("artifact drift detected; resume is fail-closed")
    return errors


def render_progress(state: dict[str, Any]) -> str:
    stop = state.get("stop") or {}
    lines = [
        "# Gauntlet progress",
        "",
        f"- Run: `{state['run_id']}`",
        f"- Mode: `{state['mode']}`",
        f"- Status: `{state['status']}`",
        f"- Phase: `{state['phase']}`",
        f"- Current round: {state['round_count']}",
        f"- Resource usage: `{canonical_json(state['usage'])}`",
        f"- Evidence freshness: `{state['evidence_freshness']}`",
        f"- Largest current gap: {state.get('current_gap') or 'not assessed'}",
        f"- Latest verification: {state.get('latest_verification') or 'not run'}",
        f"- Blockers: {state.get('blocker') or 'none recorded'}",
        f"- Next action: {state.get('next_action') or stop.get('next_gap') or 'select the next material gap'}",
        "",
        "This file is generated. Durable decisions are in `state.json` and `history.jsonl`.",
        "",
    ]
    return "\n".join(lines)


def load_option_json(path: str | None, default: dict[str, Any]) -> dict[str, Any]:
    if path is None:
        return default
    return read_json(Path(path).expanduser().resolve(strict=True))


def get_goal(args: argparse.Namespace) -> str:
    if args.goal is not None:
        goal = args.goal.strip()
    else:
        goal = Path(args.goal_file).expanduser().resolve(strict=True).read_text(encoding="utf-8").strip()
    if not goal:
        raise StateError("goal must not be empty")
    return goal


def cmd_fingerprint(args: argparse.Namespace) -> int:
    repo = canonical_repo(args.repo)
    result = fingerprint(repo, include_state=args.include_state)
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output).expanduser().resolve()
        if is_within(repo, output):
            raise StateError("fingerprint snapshot must be stored outside the inspected repository")
        atomic_write(output, text)
    print(text, end="")
    return 0


def cmd_verify_fingerprint(args: argparse.Namespace) -> int:
    repo = canonical_repo(args.repo)
    snapshot = read_json(Path(args.snapshot).expanduser().resolve(strict=True))
    current = fingerprint(repo, include_state=snapshot.get("scope") == "repository+state")
    match = snapshot.get("digest") == current["digest"]
    print(json.dumps({"match": match, "expected": snapshot.get("digest"), "actual": current["digest"]}, indent=2))
    return 0 if match else 3


def cmd_init(args: argparse.Namespace) -> int:
    repo = canonical_repo(args.repo)
    directory = gauntlet_dir(repo, create=True)
    state_path = directory / "state.json"
    goal = get_goal(args)
    bar = read_json(Path(args.bar_manifest).expanduser().resolve(strict=True))
    errors = validate_bar(bar)
    if errors:
        raise StateError("invalid bar manifest: " + "; ".join(errors))
    now = utc_now()
    capabilities = load_option_json(
        args.capabilities,
        {
            "fresh_context": False,
            "filesystem_isolation": "none",
            "max_concurrency": 1,
            "wait_supported": False,
            "notes": "Declare live host capabilities before delegation.",
        },
    )
    budget = load_option_json(
        args.budget,
        {
            "max_agent_depth": 1,
            "max_concurrency": 1,
            "time": None,
            "tokens": None,
            "retry_policy": {"deterministic": 1, "flaky": 3, "network": 3, "preserve_first_failure": True},
        },
    )
    envelope_errors = validate_capabilities(capabilities) + validate_budget(budget)
    if envelope_errors:
        raise StateError("invalid resource envelope: " + "; ".join(envelope_errors))
    frozen_bar = json.loads(canonical_json(bar))
    artifact = fingerprint(repo)
    state = {
        "schema_version": STATE_SCHEMA_VERSION,
        "run_id": args.run_id or str(uuid.uuid4()),
        "status": "ACTIVE",
        "mode": args.mode,
        "phase": "DECOMPOSE",
        "goal": {"text": goal, "sha256": sha256_bytes(goal.encode("utf-8"))},
        "bar": {
            "version": frozen_bar["version"],
            "path": ".gauntlet/bar.json",
            "sha256": sha256_bytes(canonical_json(frozen_bar).encode("utf-8")),
        },
        "repository": {"root": str(repo), "head_at_init": artifact["details"].get("head")},
        "artifact_fingerprint": artifact,
        "capabilities": capabilities,
        "budget": budget,
        "usage": {"agent_peak": 0, "agent_depth_peak": 0, "tool_calls": 0, "retries": 0, "tokens": 0, "elapsed_seconds": 0},
        "round_count": 0,
        "evidence_freshness": "MISSING",
        "current_gap": None,
        "latest_verification": None,
        "blocker": None,
        "next_action": "decompose the Goal against the frozen bar",
        "created_at": now,
        "updated_at": now,
        "stop": None,
    }
    with writer_lock(directory):
        if state_path.exists():
            raise StateError(f"run already exists; use resume or a separate workspace: {state_path}")
        unexpected = [path for path in directory.iterdir() if path.name != ".writer.lock"]
        if unexpected:
            raise StateError(f"state directory is not empty; inspect it before initialization: {directory}")
        transactional_write(
            directory,
            {
                "bar.json": (json.dumps(frozen_bar, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o600),
                "history.jsonl": ("", 0o600),
                "artifacts.jsonl": ("", 0o600),
                "state.json": (json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o600),
                "progress.md": (render_progress(state), 0o644),
            },
        )
    print(json.dumps({"initialized": True, "run_id": state["run_id"], "state": str(state_path)}, indent=2))
    return 0


def require_active_unlocked(repo: Path, directory: Path) -> dict[str, Any]:
    state = read_json(directory / "state.json")
    errors = validate_state(repo, state, check_drift=False)
    if errors:
        raise StateError("invalid state: " + "; ".join(errors))
    if state["status"] != "ACTIVE":
        raise StateError("run is already finished")
    return state


def require_active(repo: Path) -> tuple[Path, dict[str, Any]]:
    directory = gauntlet_dir(repo)
    return directory, require_active_unlocked(repo, directory)


def validate_round(record: dict[str, Any], bar_ids: set[str]) -> list[str]:
    errors: list[str] = []
    required = {
        "base_fingerprint",
        "workstream",
        "bar_ids",
        "gap",
        "hypothesis",
        "expected_value",
        "estimated_cost",
        "change",
        "evidence",
        "retest",
        "critic",
        "resource_usage",
        "next_gap",
    }
    missing = sorted(required - set(record))
    if missing:
        errors.append(f"round missing fields: {', '.join(missing)}")
        return errors
    if not isinstance(record["bar_ids"], list) or not record["bar_ids"]:
        errors.append("round.bar_ids must be a non-empty array")
    elif unknown := sorted(set(record["bar_ids"]) - bar_ids):
        errors.append(f"round references unknown bar IDs: {', '.join(unknown)}")
    for key in ("workstream", "gap", "hypothesis", "expected_value", "estimated_cost", "retest", "next_gap"):
        if not isinstance(record.get(key), str) or not record[key].strip():
            errors.append(f"round.{key} must be non-empty")
    change = record.get("change")
    if not isinstance(change, dict) or not isinstance(change.get("files"), list) or not isinstance(change.get("summary"), str):
        errors.append("round.change must contain summary and files")
    evidence = record.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        errors.append("round.evidence must be a non-empty array")
    else:
        for index, item in enumerate(evidence):
            if not isinstance(item, dict):
                errors.append(f"round.evidence[{index}] must be an object")
                continue
            for key in (
                "criterion_ids",
                "command",
                "environment",
                "status",
                "exit_code",
                "outcome",
                "started_at",
                "ended_at",
                "artifact_fingerprint",
                "executed",
                "producer",
                "independence",
                "raw_result_sha256",
            ):
                if key not in item:
                    errors.append(f"round.evidence[{index}] missing {key}")
            criterion_ids = item.get("criterion_ids")
            if not isinstance(criterion_ids, list) or not criterion_ids:
                errors.append(f"round.evidence[{index}].criterion_ids must be a non-empty array")
            elif unknown := sorted(set(criterion_ids) - bar_ids):
                errors.append(f"round.evidence[{index}] references unknown bar IDs: {', '.join(unknown)}")
            if item.get("status") not in EVIDENCE_STATUSES:
                errors.append(f"round.evidence[{index}].status is invalid")
            if item.get("status") == "PASS" and item.get("executed") is not True:
                errors.append(f"round.evidence[{index}] cannot PASS without executed=true")
            if item.get("status") == "NOT_RUN" and item.get("executed") is not False:
                errors.append(f"round.evidence[{index}] NOT_RUN requires executed=false")
            if item.get("independence") not in INDEPENDENCE:
                errors.append(f"round.evidence[{index}].independence is invalid")
            raw_hash = item.get("raw_result_sha256")
            if not isinstance(raw_hash, str) or len(raw_hash) != 64 or any(c not in "0123456789abcdef" for c in raw_hash):
                errors.append(f"round.evidence[{index}].raw_result_sha256 is invalid")
            if item.get("executed") is True and not isinstance(item.get("exit_code"), int):
                errors.append(f"round.evidence[{index}].exit_code must be an integer when executed")
            for key in ("command", "environment", "outcome", "started_at", "ended_at", "producer"):
                if not isinstance(item.get(key), str) or not item[key].strip():
                    errors.append(f"round.evidence[{index}].{key} must be non-empty")
    critic = record.get("critic")
    if not isinstance(critic, dict):
        errors.append("round.critic must be an object")
    else:
        errors.extend(validate_critic(critic, "round.critic"))
    usage = record.get("resource_usage")
    if not isinstance(usage, dict):
        errors.append("round.resource_usage must be an object")
    else:
        for key in ("agent_peak", "agent_depth_peak", "tool_calls", "retries", "tokens", "elapsed_seconds"):
            if not isinstance(usage.get(key), (int, float)) or isinstance(usage.get(key), bool) or usage[key] < 0:
                errors.append(f"round.resource_usage.{key} must be a non-negative number")
        retry_attempts = usage.get("retry_attempts")
        if not isinstance(retry_attempts, dict):
            errors.append("round.resource_usage.retry_attempts must be an object")
        else:
            for key in ("deterministic", "flaky", "network"):
                if not isinstance(retry_attempts.get(key), int) or retry_attempts[key] < 0:
                    errors.append(f"round.resource_usage.retry_attempts.{key} must be a non-negative integer")
            if all(isinstance(retry_attempts.get(key), int) for key in ("deterministic", "flaky", "network")):
                if usage.get("retries") != sum(retry_attempts.values()):
                    errors.append("round.resource_usage.retries must equal retry_attempts total")
    return errors


def validate_critic(critic: dict[str, Any], prefix: str) -> list[str]:
    errors: list[str] = []
    for key in ("critic_id", "mechanism", "largest_gap", "pre_fingerprint", "post_fingerprint"):
        if not isinstance(critic.get(key), str) or not critic[key].strip():
            errors.append(f"{prefix}.{key} must be non-empty")
    if critic.get("decision") not in DECISIONS:
        errors.append(f"{prefix}.decision is invalid")
    independence = critic.get("independence")
    if independence not in INDEPENDENCE:
        errors.append(f"{prefix}.independence is invalid")
    if not isinstance(critic.get("mutation_clean"), bool):
        errors.append(f"{prefix}.mutation_clean must be boolean")
    if critic.get("sealed_packet") is not True and independence in {"I1", "I2", "I3"}:
        errors.append(f"{prefix}.sealed_packet must be true for independent criticism")
    context_fork = critic.get("fork_turns")
    if independence == "I1" and context_fork != "none":
        errors.append(f"{prefix}.fork_turns must be none for I1 Codex criticism")
    if independence == "I2" and context_fork not in {"none", "not-applicable"}:
        errors.append(f"{prefix}.fork_turns must be none or not-applicable for I2 criticism")
    if independence == "I3" and context_fork != "not-applicable":
        errors.append(f"{prefix}.fork_turns must be not-applicable for I3 human criticism")
    if critic.get("mutation_clean") is True and critic.get("pre_fingerprint") != critic.get("post_fingerprint"):
        errors.append(f"{prefix} mutation fingerprints differ")
    if critic.get("mutation_clean") is False and critic.get("decision") != "INVALID":
        errors.append(f"{prefix} must be INVALID after mutation")
    return errors


def collect_artifacts(repo: Path, record: dict[str, Any], round_number: int) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for evidence in record.get("evidence", []):
        for item in evidence.get("artifacts", []):
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise StateError("artifact entries require a path string")
            raw_path = Path(item["path"])
            candidate = (repo / raw_path).resolve() if not raw_path.is_absolute() else raw_path.resolve()
            if not is_within(repo, candidate):
                raise StateError(f"artifact path escapes repository root: {item['path']}")
            entry = {
                "event": "artifact",
                "round": round_number,
                "path": str(candidate),
                "type": item.get("type", "file"),
                "producer": item.get("producer", "unknown"),
                "recorded_at": utc_now(),
            }
            if candidate.is_file() and not candidate.is_symlink():
                entry["sha256"] = sha256_file(candidate)
                entry["size"] = candidate.stat().st_size
            else:
                entry["sha256"] = None
                entry["missing_or_unsupported"] = True
            artifacts.append(entry)
    return artifacts


def cmd_record_round(args: argparse.Namespace) -> int:
    repo = canonical_repo(args.repo)
    directory = gauntlet_dir(repo)
    record = read_json(Path(args.record).expanduser().resolve(strict=True))
    with writer_lock(directory):
        state = require_active_unlocked(repo, directory)
        bar = read_json(directory / "bar.json")
        errors = validate_round(record, {criterion["id"] for criterion in bar["criteria"]})
        if errors:
            raise StateError("invalid round record: " + "; ".join(errors))
        if record["base_fingerprint"] != state["artifact_fingerprint"]["digest"]:
            raise StateError("round base fingerprint does not match current recorded state")
        current = fingerprint(repo)
        changed = current["digest"] != state["artifact_fingerprint"]["digest"]
        if state["mode"] == "audit" and changed:
            raise StateError("audit-mode artifact drift detected; refusing to record a round")
        if changed and not record["change"]["files"]:
            raise StateError("artifact changed but round.change.files is empty")
        for item in record["evidence"]:
            if item.get("status") == "PASS" and item.get("artifact_fingerprint") != current["digest"]:
                raise StateError("PASS evidence is not bound to the current artifact fingerprint")
        critic = record["critic"]
        critic_needs_host_fork = critic.get("independence") == "I1" or (
            critic.get("independence") == "I2" and critic.get("fork_turns") == "none"
        )
        if critic_needs_host_fork and state["capabilities"]["fresh_context"] is not True:
            raise StateError("independent Critic claimed but fresh_context capability is unavailable")
        if critic.get("mutation_clean") is True and (
            critic.get("pre_fingerprint") != current["digest"] or critic.get("post_fingerprint") != current["digest"]
        ):
            raise StateError("Critic mutation sentinel is not bound to the current artifact fingerprint")
        round_usage = record["resource_usage"]
        for retry_class, count in round_usage["retry_attempts"].items():
            if count > state["budget"]["retry_policy"][retry_class]:
                raise StateError(f"{retry_class} retries exceed the frozen retry policy")
        usage = dict(state["usage"])
        usage["agent_peak"] = max(usage["agent_peak"], round_usage["agent_peak"])
        usage["agent_depth_peak"] = max(usage["agent_depth_peak"], round_usage["agent_depth_peak"])
        for key in ("tool_calls", "retries", "tokens", "elapsed_seconds"):
            usage[key] += round_usage[key]
        usage_errors = validate_usage(usage, state["budget"], state["capabilities"])
        if usage_errors:
            raise StateError("resource envelope exceeded: " + "; ".join(usage_errors))
        round_number = state["round_count"] + 1
        event = {"event": "round", "round": round_number, "recorded_at": utc_now(), **record}
        event["post_fingerprint"] = current["digest"]
        history = load_jsonl(directory / "history.jsonl")
        artifacts = load_jsonl(directory / "artifacts.jsonl")
        artifacts.extend(collect_artifacts(repo, record, round_number))
        append_history(history, event)
        statuses = {item["status"] for item in record["evidence"]}
        freshness = "CURRENT" if statuses == {"PASS"} else "INVALID" if "INVALID" in statuses else "MISSING"
        state.update(
            {
                "round_count": round_number,
                "artifact_fingerprint": current,
                "usage": usage,
                "evidence_freshness": freshness,
                "current_gap": record["next_gap"],
                "latest_verification": record["retest"],
                "next_action": f"assess next gap: {record['next_gap']}",
                "phase": "CRITIQUE" if state["mode"] == "audit" else "FIX_RETEST",
                "updated_at": utc_now(),
            }
        )
        transactional_write(
            directory,
            {
                "history.jsonl": (jsonl_text(history), 0o600),
                "artifacts.jsonl": (jsonl_text(artifacts), 0o600),
                "state.json": (json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o600),
                "progress.md": (render_progress(state), 0o644),
            },
        )
    print(json.dumps({"recorded": True, "round": round_number, "fingerprint": current["digest"]}, indent=2))
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    repo = canonical_repo(args.repo)
    directory = gauntlet_dir(repo)
    state = read_json(directory / "state.json")
    errors = validate_state(repo, state, check_drift=False)
    current = fingerprint(repo)
    artifact = state.get("artifact_fingerprint")
    expected = artifact.get("digest") if isinstance(artifact, dict) else None
    drift = current["digest"] != expected
    current_goal = get_goal(args)
    current_bar = read_json(Path(args.bar_manifest).expanduser().resolve(strict=True))
    goal_match = sha256_bytes(current_goal.encode("utf-8")) == state.get("goal", {}).get("sha256")
    bar_match = sha256_bytes(canonical_json(current_bar).encode("utf-8")) == state.get("bar", {}).get("sha256")
    result = {
        "resumable": not errors and not drift and goal_match and bar_match and state.get("status") == "ACTIVE",
        "run_id": state.get("run_id"),
        "errors": errors,
        "drift": drift,
        "goal_match": goal_match,
        "bar_match": bar_match,
        "expected_fingerprint": expected,
        "actual_fingerprint": current["digest"],
        "next_action": state.get("next_action"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["resumable"] else 3


def cmd_recover(args: argparse.Namespace) -> int:
    repo = canonical_repo(args.repo)
    directory = gauntlet_dir(repo)
    with writer_lock(directory):
        recovered = replay_transaction(directory)
    state = read_json(directory / "state.json")
    errors = validate_state(repo, state, check_drift=True)
    if errors:
        raise StateError("transaction replayed but recovered state is invalid: " + "; ".join(errors))
    print(json.dumps({"recovered": True, "files": recovered, "run_id": state.get("run_id")}, indent=2))
    return 0


def cmd_rebaseline(args: argparse.Namespace) -> int:
    repo = canonical_repo(args.repo)
    directory = gauntlet_dir(repo)
    reason = args.reason.strip()
    if not reason:
        raise StateError("rebaseline reason must not be empty")
    with writer_lock(directory):
        state = require_active_unlocked(repo, directory)
        previous = state["artifact_fingerprint"]["digest"]
        current = fingerprint(repo)
        history = load_jsonl(directory / "history.jsonl")
        append_history(
            history,
            {
                "event": "rebaseline",
                "recorded_at": utc_now(),
                "reason": reason,
                "previous_fingerprint": previous,
                "new_fingerprint": current["digest"],
                "effect": "all prior evidence marked STALE",
            },
        )
        state.update(
            {
                "artifact_fingerprint": current,
                "evidence_freshness": "STALE",
                "latest_verification": "Prior evidence is stale after explicit rebaseline.",
                "next_action": "rerun affected required gates before continuing",
                "updated_at": utc_now(),
            }
        )
        transactional_write(
            directory,
            {
                "history.jsonl": (jsonl_text(history), 0o600),
                "state.json": (json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o600),
                "progress.md": (render_progress(state), 0o644),
            },
        )
    print(json.dumps({"rebaselined": True, "previous": previous, "current": current["digest"]}, indent=2))
    return 0


def cmd_progress(args: argparse.Namespace) -> int:
    repo = canonical_repo(args.repo)
    directory = gauntlet_dir(repo)
    if args.phase not in PHASES:
        raise StateError(f"invalid phase: {args.phase}")
    with writer_lock(directory):
        state = require_active_unlocked(repo, directory)
        if args.phase not in ALLOWED_TRANSITIONS.get(state["phase"], set()):
            raise StateError(f"illegal phase transition: {state['phase']} -> {args.phase}")
        if state["mode"] == "audit" and args.phase in {"BUILD_RUN", "FIX_RETEST", "INTEGRATE"}:
            raise StateError(f"audit mode cannot enter mutating phase {args.phase}")
        state.update(
            {
                "phase": args.phase,
                "current_gap": args.current_gap,
                "next_action": args.next_action,
                "blocker": args.blocker,
                "updated_at": utc_now(),
            }
        )
        transactional_write(
            directory,
            {
                "state.json": (json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o600),
                "progress.md": (render_progress(state), 0o644),
            },
        )
    print(json.dumps({"updated": True, "phase": args.phase}, indent=2))
    return 0


def zoned_time(value: object) -> dt.datetime:
    """Local hardening: acceptance timestamps must be parseable and zoned."""
    if not isinstance(value, str):
        raise StateError("evidence timestamp must be a zoned ISO datetime")
    try:
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise StateError("evidence timestamp must be a zoned ISO datetime") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise StateError("evidence timestamp must include a timezone")
    return result


def evidence_epoch(state: dict[str, Any], history: list[dict[str, Any]]) -> str:
    """A rebaseline invalidates earlier evidence even if bytes later recur."""
    candidates = [state.get("created_at")]
    candidates.extend(item.get("recorded_at") for item in history if item.get("event") == "rebaseline")
    return max(candidates, key=zoned_time)


def validate_run_binding(verification: dict[str, Any], *, run_id: str,
                         evidence_not_before: str, validated_at: str) -> list[str]:
    errors: list[str] = []
    try:
        lower, upper = zoned_time(evidence_not_before), zoned_time(validated_at)
        if lower > upper or upper > dt.datetime.now(dt.timezone.utc):
            raise StateError("invalid or future acceptance time boundary")
    except StateError as error:
        return [str(error)]
    if not isinstance(run_id, str) or not run_id.strip() or verification.get("run_id") != run_id:
        errors.append("verification.run_id differs from the active run")
    parts = [("criterion", item) for item in verification.get("criteria_results", [])
             if isinstance(item, dict) and item.get("status") == "PASS"] if isinstance(verification.get("criteria_results"), list) else []
    integrated = verification.get("integrated_verification")
    if isinstance(integrated, dict) and integrated.get("status") == "PASS":
        parts.append(("integrated_verification", integrated))
    ends: list[dt.datetime] = []
    critic = verification.get("final_critic")
    if isinstance(critic, dict):
        parts.append(("final_critic", critic))
    for name, item in parts:
        if item.get("run_id") != run_id:
            errors.append(f"{name}.run_id differs from the active run")
        try:
            start, end = zoned_time(item.get("started_at")), zoned_time(item.get("ended_at"))
            if not lower <= start <= end <= upper:
                errors.append(f"{name} evidence is outside the current run epoch or has reversed timestamps")
            if name == "final_critic":
                if ends and start < max(ends):
                    errors.append("final_critic predates the evidence it must review")
            else:
                ends.append(end)
        except StateError as error:
            errors.append(f"{name}: {error}")
    return errors


def validate_final(
    verification: dict[str, Any],
    bar: dict[str, Any],
    fingerprint_digest: str,
    verdict: str,
    prior_critic_ids: set[str],
    capabilities: dict[str, Any],
    mode: str,
    *,
    run_id: str,
    evidence_not_before: str,
    validated_at: str,
) -> list[str]:
    if not isinstance(verification, dict):
        return ["verification must be an object"]
    errors = validate_run_binding(verification, run_id=run_id,
                                  evidence_not_before=evidence_not_before, validated_at=validated_at)
    results = verification.get("criteria_results")
    result_map: dict[str, dict[str, Any]] = {}
    bar_ids = {criterion["id"] for criterion in bar["criteria"]}
    if not isinstance(results, list) or not results:
        errors.append("verification.criteria_results must be a non-empty array")
    else:
        for index, item in enumerate(results):
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                errors.append(f"criteria_results[{index}] is invalid")
                continue
            if item["id"] in result_map:
                errors.append(f"duplicate criterion result: {item['id']}")
            result_map[item["id"]] = item
            if item["id"] not in bar_ids:
                errors.append(f"unknown criterion result: {item['id']}")
            if item.get("status") not in EVIDENCE_STATUSES:
                errors.append(f"criterion status is invalid: {item['id']}")
            if not isinstance(item.get("executed"), bool):
                errors.append(f"criterion executed flag is missing: {item['id']}")
            if item.get("status") == "PASS":
                if item.get("executed") is not True:
                    errors.append(f"PASS criterion was not executed: {item['id']}")
                if item.get("artifact_fingerprint") != fingerprint_digest:
                    errors.append(f"PASS criterion is not current: {item['id']}")
                for key in ("command", "environment", "outcome", "started_at", "ended_at", "producer", "raw_result_sha256"):
                    if not isinstance(item.get(key), str) or not item[key].strip():
                        errors.append(f"PASS criterion lacks {key}: {item['id']}")
                raw_hash = item.get("raw_result_sha256")
                if isinstance(raw_hash, str) and (len(raw_hash) != 64 or any(c not in "0123456789abcdef" for c in raw_hash)):
                    errors.append(f"PASS criterion raw_result_sha256 is invalid: {item['id']}")
        for missing_id in sorted(bar_ids - set(result_map)):
            errors.append(f"criterion result is missing: {missing_id}")

    integrated = verification.get("integrated_verification")
    if mode == "execute" and not isinstance(integrated, dict):
        errors.append("integrated_verification must be an object in execute mode")
    elif integrated is not None and not isinstance(integrated, dict):
        errors.append("integrated_verification must be an object when supplied")
    elif isinstance(integrated, dict):
        if integrated.get("status") not in EVIDENCE_STATUSES:
            errors.append("integrated_verification status is invalid")
        if not isinstance(integrated.get("executed"), bool):
            errors.append("integrated_verification executed flag is missing")
        if integrated.get("status") == "PASS":
            if integrated.get("artifact_fingerprint") != fingerprint_digest:
                errors.append("integrated_verification is not bound to the current artifact")
            if integrated.get("executed") is not True:
                errors.append("integrated_verification must be executed")
            for key in ("command", "environment", "outcome", "started_at", "ended_at", "producer", "raw_result_sha256"):
                if not isinstance(integrated.get(key), str) or not integrated[key].strip():
                    errors.append(f"integrated_verification lacks {key}")
            raw_hash = integrated.get("raw_result_sha256")
            if isinstance(raw_hash, str) and (len(raw_hash) != 64 or any(c not in "0123456789abcdef" for c in raw_hash)):
                errors.append("integrated_verification raw_result_sha256 is invalid")

    critic = verification.get("final_critic")
    if not isinstance(critic, dict):
        errors.append("final_critic must be an object")
    else:
        errors.extend(validate_critic(critic, "final_critic"))
        critic_needs_host_fork = critic.get("independence") == "I1" or (
            critic.get("independence") == "I2" and critic.get("fork_turns") == "none"
        )
        if critic_needs_host_fork and capabilities.get("fresh_context") is not True:
            errors.append("final_critic independence exceeds available fresh_context capability")
        if critic.get("critic_id") in prior_critic_ids:
            errors.append("final_critic identity was already used in an earlier round")
        if critic.get("mutation_clean") is True and (
            critic.get("pre_fingerprint") != fingerprint_digest or critic.get("post_fingerprint") != fingerprint_digest
        ):
            errors.append("final_critic sentinel is not bound to the current artifact")
    if not isinstance(verification.get("limitations"), list):
        errors.append("verification.limitations must be an array")
    if not isinstance(verification.get("resource_stop"), bool):
        errors.append("verification.resource_stop must be boolean")

    if verdict == "PASS":
        for criterion in bar["criteria"]:
            if not criterion["required"]:
                continue
            item = result_map.get(criterion["id"])
            if item is None or item.get("status") != "PASS":
                errors.append(f"required criterion does not PASS: {criterion['id']}")
            elif item.get("artifact_fingerprint") != fingerprint_digest:
                errors.append(f"required criterion is not current: {criterion['id']}")
            elif item.get("executed") is not True:
                errors.append(f"required criterion was not executed: {criterion['id']}")
        if mode == "execute" and (not isinstance(integrated, dict) or integrated.get("status") != "PASS"):
            errors.append("integrated_verification must PASS")
        if not isinstance(critic, dict) or critic.get("decision") != "APPROVE":
            errors.append("final_critic must APPROVE")
        else:
            if critic.get("independence") not in {"I1", "I2", "I3"}:
                errors.append("final_critic must have fresh-context or stronger independence")
            if critic.get("mutation_clean") is not True:
                errors.append("final_critic mutation sentinel must be clean")
            if critic.get("pre_fingerprint") != fingerprint_digest or critic.get("post_fingerprint") != fingerprint_digest:
                errors.append("final_critic sentinel is not bound to the current artifact")
        if verification.get("resource_stop") is not False:
            errors.append("PASS is forbidden after a resource stop")
    return errors


def cmd_finish(args: argparse.Namespace) -> int:
    repo = canonical_repo(args.repo)
    directory = gauntlet_dir(repo)
    verification = read_json(Path(args.verification).expanduser().resolve(strict=True))
    reason = args.reason.strip()
    next_gap = args.next_gap.strip()
    if not reason or not next_gap:
        raise StateError("finish reason and next gap must not be empty")
    with writer_lock(directory):
        state = require_active_unlocked(repo, directory)
        if state["phase"] != "FINAL_GAUNTLET":
            raise StateError("finish requires the FINAL_GAUNTLET phase")
        bar = read_json(directory / "bar.json")
        current = fingerprint(repo)
        if current["digest"] != state["artifact_fingerprint"]["digest"]:
            raise StateError("artifact drift detected before finish")
        history = load_jsonl(directory / "history.jsonl")
        prior_critic_ids = {
            str(item.get("critic", {}).get("critic_id"))
            for item in history
            if isinstance(item.get("critic"), dict) and item["critic"].get("critic_id")
        }
        errors = validate_final(
            verification,
            bar,
            current["digest"],
            args.verdict,
            prior_critic_ids,
            state["capabilities"],
            state["mode"],
            run_id=state["run_id"],
            evidence_not_before=evidence_epoch(state, history),
            validated_at=utc_now(),
        )
        if errors:
            raise StateError("cannot finish: " + "; ".join(errors))
        stop = {
            "verdict": args.verdict,
            "reason": reason,
            "next_gap": next_gap,
            "verification": verification,
            "finished_at": utc_now(),
        }
        append_history(history, {"event": "finish", **stop})
        state.update(
            {
                "status": "FINISHED",
                "phase": "STOP",
                "evidence_freshness": "CURRENT" if args.verdict == "PASS" else state["evidence_freshness"],
                "stop": stop,
                "next_action": next_gap,
                "updated_at": utc_now(),
            }
        )
        transactional_write(
            directory,
            {
                "history.jsonl": (jsonl_text(history), 0o600),
                "state.json": (json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", 0o600),
                "progress.md": (render_progress(state), 0o644),
            },
        )
    print(json.dumps({"finished": True, "verdict": args.verdict, "run_id": state["run_id"]}, indent=2))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    repo = canonical_repo(args.repo)
    directory = gauntlet_dir(repo)
    state = read_json(directory / "state.json")
    errors = validate_state(repo, state, check_drift=args.check_drift)
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    fingerprint_parser = subparsers.add_parser("fingerprint", help="capture an artifact fingerprint")
    fingerprint_parser.add_argument("--repo", required=True)
    fingerprint_parser.add_argument("--output")
    fingerprint_parser.add_argument("--include-state", action="store_true", help="include .gauntlet for read-only mutation sentinels")
    fingerprint_parser.set_defaults(handler=cmd_fingerprint)

    verify_parser = subparsers.add_parser("verify-fingerprint", help="compare with a saved fingerprint")
    verify_parser.add_argument("--repo", required=True)
    verify_parser.add_argument("--snapshot", required=True)
    verify_parser.set_defaults(handler=cmd_verify_fingerprint)

    init_parser = subparsers.add_parser("init", help="initialize a multi-round run")
    init_parser.add_argument("--repo", required=True)
    goal_group = init_parser.add_mutually_exclusive_group(required=True)
    goal_group.add_argument("--goal")
    goal_group.add_argument("--goal-file")
    init_parser.add_argument("--bar-manifest", required=True)
    init_parser.add_argument("--mode", choices=("audit", "execute"), default="execute")
    init_parser.add_argument("--run-id")
    init_parser.add_argument("--capabilities")
    init_parser.add_argument("--budget")
    init_parser.set_defaults(handler=cmd_init)

    validate_parser = subparsers.add_parser("validate", help="validate run structure and optional drift")
    validate_parser.add_argument("--repo", required=True)
    validate_parser.add_argument("--check-drift", action="store_true")
    validate_parser.set_defaults(handler=cmd_validate)

    resume_parser = subparsers.add_parser("resume", help="check whether a run can safely resume")
    resume_parser.add_argument("--repo", required=True)
    resume_goal = resume_parser.add_mutually_exclusive_group(required=True)
    resume_goal.add_argument("--goal")
    resume_goal.add_argument("--goal-file")
    resume_parser.add_argument("--bar-manifest", required=True)
    resume_parser.set_defaults(handler=cmd_resume)

    recover_parser = subparsers.add_parser("recover", help="replay an interrupted transactional state update")
    recover_parser.add_argument("--repo", required=True)
    recover_parser.set_defaults(handler=cmd_recover)

    rebaseline_parser = subparsers.add_parser("rebaseline", help="accept detected drift and stale prior evidence")
    rebaseline_parser.add_argument("--repo", required=True)
    rebaseline_parser.add_argument("--reason", required=True)
    rebaseline_parser.set_defaults(handler=cmd_rebaseline)

    progress_parser = subparsers.add_parser("progress", help="update the generated progress view")
    progress_parser.add_argument("--repo", required=True)
    progress_parser.add_argument("--phase", required=True)
    progress_parser.add_argument("--current-gap", required=True)
    progress_parser.add_argument("--next-action", required=True)
    progress_parser.add_argument("--blocker")
    progress_parser.set_defaults(handler=cmd_progress)

    round_parser = subparsers.add_parser("record-round", help="append a validated round record")
    round_parser.add_argument("--repo", required=True)
    round_parser.add_argument("--record", required=True)
    round_parser.set_defaults(handler=cmd_record_round)

    finish_parser = subparsers.add_parser("finish", help="finish with fail-closed verdict validation")
    finish_parser.add_argument("--repo", required=True)
    finish_parser.add_argument("--verdict", choices=sorted(VERDICTS), required=True)
    finish_parser.add_argument("--reason", required=True)
    finish_parser.add_argument("--next-gap", required=True)
    finish_parser.add_argument("--verification", required=True)
    finish_parser.set_defaults(handler=cmd_finish)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.handler(args))
    except StateError as error:
        print(f"gauntlet-state: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("gauntlet-state: interrupted; existing state was not cleaned up", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
