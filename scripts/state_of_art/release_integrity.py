#!/usr/bin/env python3
"""Run the dependency-free release-integrity gate.

The gate is intentionally offline and read-only.  It proves the checkout
identity, runs the two root checks that are safe without installed services,
and validates that release evidence belongs to this exact checkout.  It never
turns an unavailable Docker/service/provider path into production evidence.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

try:  # Package import for tests; script-directory fallback for direct execution.
    from scripts.state_of_art.release_manifest import (
        MANIFEST_SCHEMA,
        ManifestValidationError,
        REQUIRED_GATES,
        ReleaseEvidenceManifest,
    )
except ImportError:  # pragma: no cover - exercised by the workflow's direct script call.
    from release_manifest import MANIFEST_SCHEMA, ManifestValidationError, REQUIRED_GATES, ReleaseEvidenceManifest


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE = ("docs/progress/release-evidence.json",)
DEFAULT_TIMEOUT_SECONDS = 120
SHA1_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
MAX_EVIDENCE_AGE_SECONDS = 24 * 60 * 60
MAX_EVIDENCE_FUTURE_SKEW_SECONDS = 5 * 60
RELEASE_INTEGRITY_COMMAND = ("git", "diff", "--check", "&&", "make", "validate")
RELEASE_INTEGRITY_PROCEDURE = "run git diff --check and make validate against the exact checkout"

PASS = "PASS"
FAIL = "FAIL"
BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"
NOT_RUN = "NOT_RUN"
CLASSIFICATIONS = {PASS, FAIL, BLOCKED_EXTERNAL, NOT_RUN}

def _rejection_codes(
    reason: str,
    *,
    classification: str,
) -> list[str]:
    """Map fail-closed reasons to stable Phase 3 rejection identifiers."""

    lowered = reason.lower()
    codes: set[str] = set()
    if any(token in lowered for token in ("stale", "old-check")):
        codes.add("STALE_EVIDENCE_REJECTED")
        codes.add("STALE_RELEASE_EVIDENCE_REJECTED")
    if "commit" in lowered and any(token in lowered for token in ("match", "wrong", "head")):
        codes.add("WRONG_COMMIT_REJECTED")
        codes.add("WRONG_COMMIT_EVIDENCE_REJECTED")
    if "tree" in lowered and any(token in lowered for token in ("match", "wrong", "bound")):
        codes.add("WRONG_TREE_REJECTED")
    if "hash" in lowered or "fingerprint" in lowered:
        codes.add("WRONG_HASH_REJECTED")
    if any(token in lowered for token in ("absent", "not run", "no mandatory", "missing")):
        codes.add("MISSING_GATE_REJECTED")
        codes.add("MISSING_EVIDENCE_REJECTED")
    if any(token in lowered for token in ("blocked", "external", "unavailable")):
        codes.add("BLOCKED_GATE_REJECTED")
        codes.add("BLOCKED_RUNTIME_REJECTED")
    if "independent" in lowered and any(token in lowered for token in ("self", "required", "review")):
        codes.add("SELF_PROMOTED_GATE_REJECTED")
    if "not clean" in lowered or "not bound to a clean" in lowered or "dirty" in lowered:
        codes.add("DIRTY_RELEASE_EVIDENCE_REJECTED")
    if classification == NOT_RUN and not codes:
        codes.add("MISSING_EVIDENCE_REJECTED")
    return sorted(codes)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _capture(
    argv: Sequence[str],
    root: Path,
    *,
    timeout: int,
) -> tuple[int | None, bytes, bytes, str | None]:
    """Capture a command without exposing its output in the gate artifact."""

    try:
        process = subprocess.Popen(
            list(argv),
            cwd=root,
            env=_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        return None, b"", b"", f"executable unavailable: {exc.filename or argv[0]}"
    except OSError as exc:
        return None, b"", b"", f"could not execute command: {exc}"
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        return None, b"", b"", f"timed out after {timeout}s; process group was terminated"
    return process.returncode, stdout, stderr, None


def _decode(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


def _git_output(root: Path, args: Sequence[str], *, timeout: int) -> tuple[int | None, bytes, bytes, str | None]:
    return _capture(("git", *args), root, timeout=timeout)


def _hash_git_diff(root: Path, *, timeout: int) -> tuple[str | None, str | None]:
    code, stdout, stderr, reason = _git_output(
        root,
        ("diff", "--no-ext-diff", "--binary", "HEAD", "--"),
        timeout=timeout,
    )
    if reason:
        return None, reason
    if code != 0:
        return None, f"git diff returned exit code {code}: {_decode(stderr).strip() or 'unknown error'}"
    return _sha256_bytes(stdout), None


def _hash_untracked_files(root: Path, *, timeout: int) -> tuple[str | None, str | None]:
    code, stdout, stderr, reason = _git_output(
        root,
        ("ls-files", "--others", "--exclude-standard", "-z"),
        timeout=timeout,
    )
    if reason:
        return None, reason
    if code != 0:
        return None, f"git ls-files returned exit code {code}: {_decode(stderr).strip() or 'unknown error'}"

    digest = hashlib.sha256()
    for raw_path in stdout.split(b"\0"):
        if not raw_path:
            continue
        digest.update(b"path\0")
        digest.update(raw_path)
        digest.update(b"\0")
        relative = raw_path.decode("utf-8", errors="surrogateescape")
        path = root / relative
        try:
            if path.is_symlink():
                digest.update(b"symlink\0")
                digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
            elif path.is_file():
                digest.update(b"file\0")
                digest.update(_sha256_bytes(path.read_bytes()).encode("ascii"))
            else:
                digest.update(b"other\0")
        except OSError as exc:
            return None, f"could not fingerprint untracked path {relative!r}: {exc}"
        digest.update(b"\0")
    return digest.hexdigest(), None


def capture_checkout(root: Path = ROOT, *, timeout: int = 15) -> dict[str, Any]:
    """Capture a sanitized, reproducible identity for the root checkout."""

    root = root.resolve()
    errors: list[str] = []

    head_code, head_bytes, head_stderr, head_reason = _git_output(
        root,
        ("rev-parse", "HEAD^{commit}"),
        timeout=timeout,
    )
    head = _decode(head_bytes).strip() if head_code == 0 else None
    if not head or not SHA1_RE.fullmatch(head):
        errors.append(f"Git HEAD unavailable or malformed: {head_reason or _decode(head_stderr).strip() or head or 'unknown'}")
        head = None

    tree_code, tree_bytes, tree_stderr, tree_reason = _git_output(
        root,
        ("rev-parse", "HEAD^{tree}"),
        timeout=timeout,
    )
    tree = _decode(tree_bytes).strip() if tree_code == 0 else None
    if not tree or not SHA1_RE.fullmatch(tree):
        errors.append(f"Git tree unavailable or malformed: {tree_reason or _decode(tree_stderr).strip() or tree or 'unknown'}")
        tree = None

    branch_code, branch_bytes, _, _ = _git_output(
        root,
        ("branch", "--show-current"),
        timeout=timeout,
    )
    branch = _decode(branch_bytes).strip() if branch_code == 0 else ""
    branch = branch or "DETACHED"

    status_code, status_bytes, status_stderr, status_reason = _git_output(
        root,
        ("status", "--porcelain=v1", "--untracked-files=all"),
        timeout=timeout,
    )
    status_available = status_code == 0
    status_text = _decode(status_bytes)
    if not status_available:
        errors.append(
            f"Git worktree status unavailable: {status_reason or _decode(status_stderr).strip() or 'unknown error'}"
        )
    worktree_status = "UNKNOWN" if not status_available else ("CLEAN" if not status_text else "DIRTY")
    status_fingerprint = _sha256_bytes(status_bytes) if status_available else None

    index_code, index_bytes, index_stderr, index_reason = _git_output(
        root,
        ("ls-files", "--stage", "-z"),
        timeout=timeout,
    )
    index_fingerprint = _sha256_bytes(index_bytes) if index_code == 0 else None
    if index_code != 0:
        errors.append(
            f"Git index unavailable: {index_reason or _decode(index_stderr).strip() or 'unknown error'}"
        )

    diff_fingerprint, diff_error = _hash_git_diff(root, timeout=timeout)
    if diff_error:
        errors.append(f"Tracked worktree diff unavailable: {diff_error}")

    untracked_fingerprint, untracked_error = _hash_untracked_files(root, timeout=timeout)
    if untracked_error:
        errors.append(f"Untracked worktree fingerprint unavailable: {untracked_error}")

    fingerprint_parts = {
        "HEAD": head or "UNAVAILABLE",
        "branch": branch,
        "tree": tree or "UNAVAILABLE",
        "status_fingerprint": status_fingerprint or "UNAVAILABLE",
        "index_fingerprint": index_fingerprint or "UNAVAILABLE",
        "tracked_diff_fingerprint": diff_fingerprint or "UNAVAILABLE",
        "untracked_fingerprint": untracked_fingerprint or "UNAVAILABLE",
    }
    checkout_fingerprint = _sha256_bytes(_canonical_json(fingerprint_parts))
    available = not errors and head is not None and tree is not None and status_available

    return {
        "available": available,
        "HEAD": head,
        "head": head,
        "tree": tree,
        "branch": branch,
        "status": worktree_status,
        "status_entries": len(status_text.splitlines()) if status_available else None,
        "status_fingerprint": status_fingerprint,
        "fingerprint": checkout_fingerprint,
        "errors": errors,
    }


def _command_result(
    name: str,
    argv: Sequence[str],
    root: Path,
    *,
    timeout: int,
) -> dict[str, Any]:
    code, _, _, reason = _capture(argv, root, timeout=timeout)
    if reason:
        return {
            "name": name,
            "command": list(argv),
            "classification": NOT_RUN,
            "exit_code": None,
            "reason": reason,
        }
    if code == 0:
        return {
            "name": name,
            "command": list(argv),
            "classification": PASS,
            "exit_code": 0,
        }
    return {
        "name": name,
        "command": list(argv),
        "classification": FAIL,
        "exit_code": code,
        "reason": f"command exited with code {code}",
    }


def classify_worktree_sentinel(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    require_clean: bool,
) -> dict[str, Any]:
    """Ensure the gate did not mutate the checkout and optionally require clean state."""

    if not before.get("available") or not after.get("available"):
        return {
            "name": "worktree_sentinel",
            "classification": NOT_RUN,
            "required": True,
            "mutated": None,
            "require_clean": require_clean,
            "reason": "could not capture a complete Git checkout identity",
        }

    mutated = before.get("fingerprint") != after.get("fingerprint")
    if mutated:
        return {
            "name": "worktree_sentinel",
            "classification": FAIL,
            "required": True,
            "mutated": True,
            "require_clean": require_clean,
            "reason": "the gate changed the checkout while it was running",
        }
    if require_clean and before.get("status") != "CLEAN":
        return {
            "name": "worktree_sentinel",
            "classification": FAIL,
            "required": True,
            "mutated": False,
            "require_clean": True,
            "reason": "release checkout is not clean",
        }
    return {
        "name": "worktree_sentinel",
        "classification": PASS,
        "required": True,
        "mutated": False,
        "require_clean": require_clean,
        "reason": "checkout identity is unchanged",
    }


def _safe_evidence_path(root: Path, raw_path: str) -> tuple[Path | None, str | None]:
    candidate = Path(raw_path)
    lexical = candidate if candidate.is_absolute() else root / candidate
    try:
        lexical_relative = lexical.relative_to(root)
    except ValueError:
        lexical_relative = None
    if lexical_relative is not None:
        cursor = root
        for component in lexical_relative.parts:
            cursor /= component
            if cursor.is_symlink():
                return None, "evidence path must not traverse a symlink"
    resolved = lexical.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None, "evidence path must remain inside the checkout"
    return resolved, None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_timestamp(value: str, field: str, failures: list[str]) -> None:
    try:
        parsed = value.replace("Z", "+00:00")
        timestamp = datetime.fromisoformat(parsed)
    except ValueError:
        failures.append(f"{field} is not an ISO-8601 timestamp")
        return
    if timestamp.tzinfo is None:
        failures.append(f"{field} must include a timezone")


def _validate_current_timestamp(value: str, field: str, failures: list[str]) -> None:
    before = len(failures)
    _validate_timestamp(value, field, failures)
    if len(failures) != before:
        return
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    age_seconds = (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds()
    if age_seconds > MAX_EVIDENCE_AGE_SECONDS or age_seconds < -MAX_EVIDENCE_FUTURE_SKEW_SECONDS:
        failures.append(f"{field} is outside the current evidence window")


def _validate_gate_procedure(gate: Any, failures: list[str]) -> None:
    """Allow only procedures whose command contract is machine-recognizable.

    The integrity checker is not a shell runner for arbitrary manifest input.
    It accepts the local gate procedure or the explicit runtime-envelope
    procedure, then validates the referenced envelope separately.  A free-form
    command such as ``false`` cannot be paired with a claimed PASS.
    """

    command = tuple(gate.command)
    if gate.gate_id == "release-integrity":
        if command != RELEASE_INTEGRITY_COMMAND:
            failures.append("gate release-integrity command is not the approved procedure")
        if gate.procedure != RELEASE_INTEGRITY_PROCEDURE:
            failures.append("gate release-integrity procedure is not the approved procedure")
        return
    if len(command) != 2 or command[0] != "runtime-envelope" or not command[1].strip():
        failures.append(f"gate {gate.gate_id} command is not an approved runtime-envelope procedure")
        return
    target = command[1]
    target_path = Path(target)
    if target.startswith(".runtime/"):
        if target_path.is_absolute() or ".." in target_path.parts:
            failures.append(
                f"gate {gate.gate_id} runtime-envelope target must be a safe .runtime path"
            )
    elif gate.result == PASS:
        failures.append(
            f"gate {gate.gate_id} PASS requires a safe .runtime runtime-envelope target"
        )
    elif target != gate.gate_id:
        failures.append(
            f"gate {gate.gate_id} non-PASS runtime-envelope target is invalid"
        )
    evidence_paths = {item.path for item in gate.evidence_paths}
    if target.startswith(".runtime/") and target not in evidence_paths:
        failures.append(
            f"gate {gate.gate_id} runtime-envelope target must be listed in evidence_paths"
        )
    if gate.result == PASS and target not in evidence_paths:
        failures.append(
            f"gate {gate.gate_id} PASS requires its runtime envelope in evidence_paths"
        )
    if gate.gate_id not in gate.procedure:
        failures.append(f"gate {gate.gate_id} procedure does not identify its gate")


def _evaluate_typed_manifest(
    path: Path,
    payload: Mapping[str, Any],
    checkout: Mapping[str, Any],
    *,
    root: Path,
) -> dict[str, Any]:
    """Validate the strict v2 manifest and its referenced bytes."""

    result: dict[str, Any] = {
        "path": str(path.relative_to(root) if path.is_relative_to(root) else path),
        "required": True,
        "schema_version": MANIFEST_SCHEMA,
    }
    try:
        manifest = ReleaseEvidenceManifest.from_mapping(payload)
    except ManifestValidationError as exc:
        result.update({"classification": FAIL, "reason": "; ".join(exc.errors)})
        return result

    failures = manifest.structural_errors()
    binding = manifest.commit_binding
    expected_head = str(checkout.get("head") or "").lower()
    expected_tree = str(checkout.get("tree") or "").lower()
    expected_fingerprint = str(checkout.get("fingerprint") or "").lower()
    checkout_errors = checkout.get("errors")
    if (
        checkout.get("available") is not True
        or not isinstance(checkout_errors, Sequence)
        or isinstance(checkout_errors, (str, bytes, bytearray))
        or bool(checkout_errors)
    ):
        failures.append("current checkout identity is unavailable or has capture errors")
    if not expected_head or binding.commit_sha != expected_head:
        failures.append("manifest commit binding does not match this checkout HEAD")
    if not expected_tree or binding.tree_sha != expected_tree:
        failures.append("manifest commit binding does not match this checkout tree")
    if not expected_fingerprint or binding.checkout_fingerprint != expected_fingerprint:
        failures.append("manifest commit binding does not match this checkout fingerprint")
    if checkout.get("status") != "CLEAN" or not binding.clean_worktree:
        failures.append("manifest is not bound to a clean release checkout")
    _validate_current_timestamp(manifest.generated_at, "manifest.generated_at", failures)

    manifest_relative = path.relative_to(root).as_posix() if path.is_relative_to(root) else ""

    def check_file(raw_path: str, expected_hash: str, field: str) -> None:
        if raw_path == manifest_relative:
            failures.append(f"{field} cannot self-reference the release manifest")
            return
        safe_path, path_error = _safe_evidence_path(root, raw_path)
        if path_error or safe_path is None:
            failures.append(f"{field}: {path_error or 'invalid path'}")
            return
        if not safe_path.is_file():
            failures.append(f"{field}: referenced file is absent")
            return
        try:
            actual_hash = _sha256_file(safe_path)
        except OSError as exc:
            failures.append(f"{field}: could not hash referenced file: {exc}")
            return
        if actual_hash != expected_hash:
            failures.append(f"{field}: referenced artifact hash does not match")

    def check_runtime_envelope(gate: Any, evidence_path: str) -> None:
        """Validate the executable observation behind a runtime-envelope gate."""

        target = gate.command[1] if len(gate.command) == 2 else ""
        if not target.startswith(".runtime/") or evidence_path != target:
            return
        safe_path, path_error = _safe_evidence_path(root, evidence_path)
        if path_error or safe_path is None or not safe_path.is_file():
            return  # check_file already emits the authoritative path error.
        try:
            envelope = json.loads(safe_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            failures.append(f"gate {gate.gate_id} runtime envelope is not readable JSON")
            return
        if not isinstance(envelope, Mapping) or envelope.get("schema_version") != "state-of-art-runtime-evidence.v1":
            failures.append(f"gate {gate.gate_id} runtime envelope has an unsupported schema")
            return
        if envelope.get("status") != gate.result:
            failures.append(f"gate {gate.gate_id} runtime envelope status does not match the manifest")
        expected_exit = {
            "PASS": 0,
            "BLOCKED_EXTERNAL": 2,
            "FAIL": 1,
            "STALE": 1,
            "INVALID": 1,
            "NOT_RUN": None,
        }.get(gate.result)
        if envelope.get("exit_status") != expected_exit:
            failures.append(f"gate {gate.gate_id} runtime envelope exit_status does not match the manifest")
        for field, expected in (
            ("commit_sha", binding.commit_sha),
            ("tree_sha", binding.tree_sha),
            ("checkout_fingerprint", binding.checkout_fingerprint),
        ):
            if envelope.get(field) != expected:
                failures.append(f"gate {gate.gate_id} runtime envelope {field} is not bound to the manifest")
        if envelope.get("clean_worktree") is not True:
            failures.append(f"gate {gate.gate_id} runtime envelope is not clean")
        if gate.result == PASS and envelope.get("production_safe") is not True:
            failures.append(
                f"gate {gate.gate_id} PASS runtime envelope is not production-safe"
            )
        if not isinstance(envelope.get("procedure"), str) or not envelope["procedure"].strip():
            failures.append(f"gate {gate.gate_id} runtime envelope has no procedure")
        observed_at = envelope.get("observed_at")
        if isinstance(observed_at, str):
            _validate_current_timestamp(observed_at, f"gate {gate.gate_id}.runtime.observed_at", failures)
        else:
            failures.append(f"gate {gate.gate_id} runtime envelope has no observed_at")
        sentinel = envelope.get("checkout_sentinel")
        if not isinstance(sentinel, Mapping) or sentinel.get("unchanged") is not True:
            failures.append(f"gate {gate.gate_id} runtime envelope sentinel is not unchanged")
        raw_artifacts = envelope.get("raw_artifacts")
        if not isinstance(raw_artifacts, Sequence) or isinstance(raw_artifacts, (str, bytes, bytearray)) or not raw_artifacts:
            failures.append(f"gate {gate.gate_id} runtime envelope has no raw artifact")
            return
        for index, raw_ref in enumerate(raw_artifacts):
            if not isinstance(raw_ref, Mapping):
                failures.append(f"gate {gate.gate_id} runtime raw_artifacts[{index}] is invalid")
                continue
            raw_path = raw_ref.get("path")
            raw_hash = raw_ref.get("sha256")
            if not isinstance(raw_path, str) or not isinstance(raw_hash, str):
                failures.append(f"gate {gate.gate_id} runtime raw_artifacts[{index}] is incomplete")
                continue
            check_file(raw_path, raw_hash, f"gate {gate.gate_id}.runtime.raw_artifacts[{index}]")

    for index, artifact in enumerate(manifest.artifacts):
        check_file(artifact.path, artifact.sha256, f"artifacts[{index}]")
    for gate in manifest.gates:
        _validate_gate_procedure(gate, failures)
        _validate_current_timestamp(gate.timestamp, f"gate {gate.gate_id}.timestamp", failures)
        for index, evidence in enumerate(gate.evidence_paths):
            check_file(evidence.path, evidence.sha256, f"gate {gate.gate_id}.evidence_paths[{index}]")
            check_runtime_envelope(gate, evidence.path)

    blocking_gates = [gate for gate in manifest.gates if gate.result != "PASS"]
    if failures:
        result["classification"] = FAIL
        result["reason"] = "; ".join(failures)
    elif blocking_gates:
        blocking_ids = ", ".join(f"{gate.gate_id}={gate.result}" for gate in blocking_gates)
        if any(gate.result == "BLOCKED_EXTERNAL" for gate in blocking_gates):
            result["classification"] = BLOCKED_EXTERNAL
        elif any(gate.result in {"FAIL", "STALE", "INVALID"} for gate in blocking_gates):
            result["classification"] = FAIL
        else:
            result["classification"] = NOT_RUN
        result["reason"] = (
            f"manifest status is {manifest.status}; mandatory gates are not PASS: {blocking_ids}"
        )
    else:
        result["classification"] = PASS
        result["reason"] = "typed manifest, artifact hashes and mandatory gates are valid"
    rejection_codes = set(_rejection_codes(
        str(result.get("reason", "")),
        classification=str(result["classification"]),
    ))
    for gate in manifest.gates:
        if gate.result == "BLOCKED_EXTERNAL":
            rejection_codes.add("BLOCKED_GATE_REJECTED")
            rejection_codes.add("BLOCKED_RUNTIME_REJECTED")
        elif gate.result == "NOT_RUN":
            rejection_codes.add("MISSING_GATE_REJECTED")
            rejection_codes.add("MISSING_EVIDENCE_REJECTED")
        elif gate.result == "STALE":
            rejection_codes.add("STALE_EVIDENCE_REJECTED")
            rejection_codes.add("STALE_RELEASE_EVIDENCE_REJECTED")
        elif gate.result == "INVALID":
            rejection_codes.add("WRONG_HASH_REJECTED")
        elif gate.result == "FAIL":
            rejection_codes.add("FAILED_RUNTIME_REJECTED")
    result["rejection_codes"] = sorted(rejection_codes)
    result["gate_results"] = [
        {"gate_id": gate.gate_id, "result": gate.result} for gate in manifest.gates
    ]
    return result


def evaluate_evidence(
    path: Path,
    checkout: Mapping[str, Any],
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Classify one evidence JSON file against the observed checkout."""

    result: dict[str, Any] = {
        "path": str(path.relative_to(root) if path.is_relative_to(root) else path),
        "required": True,
    }
    if not path.is_file():
        result.update(
            {
                "classification": NOT_RUN,
                "reason": "required release evidence file is absent",
                "rejection_codes": ["MISSING_EVIDENCE_REJECTED"],
            }
        )
        return result

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result.update(
            {
                "classification": FAIL,
                "reason": f"evidence is not readable JSON: {exc}",
                "rejection_codes": [],
            }
        )
        return result
    if not isinstance(payload, Mapping):
        result.update(
            {
                "classification": FAIL,
                "reason": "evidence root must be a JSON object",
                "rejection_codes": [],
            }
        )
        return result

    if payload.get("schema_version") == MANIFEST_SCHEMA:
        return _evaluate_typed_manifest(path, payload, checkout, root=root)

    result.update(
        {
            "classification": NOT_RUN,
            "reason": "legacy release evidence schema is not promotion eligible; regenerate state-of-art-release-evidence.v2",
            "rejection_codes": ["MISSING_EVIDENCE_REJECTED"],
        }
    )
    return result

def _overall_classification(criteria: Sequence[Mapping[str, Any]]) -> str:
    if any(item.get("classification") == FAIL for item in criteria):
        return FAIL
    if any(item.get("required") and item.get("classification") == BLOCKED_EXTERNAL for item in criteria):
        return BLOCKED_EXTERNAL
    if any(item.get("required") and item.get("classification") == NOT_RUN for item in criteria):
        return NOT_RUN
    return PASS


def run_gate(
    root: Path = ROOT,
    *,
    evidence_paths: Sequence[str] = DEFAULT_EVIDENCE,
    require_clean: bool = False,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run all release-integrity criteria and return the JSON-ready artifact."""

    root = root.resolve()
    before = capture_checkout(root, timeout=min(timeout, 15))
    command_results = [
        _command_result("diff_check", ("git", "diff", "--check"), root, timeout=timeout),
        _command_result("make_validate", ("make", "validate"), root, timeout=timeout),
    ]
    after = capture_checkout(root, timeout=min(timeout, 15))

    sentinel = classify_worktree_sentinel(before, after, require_clean=require_clean)
    criteria: list[dict[str, Any]] = [
        {
            "id": item["name"],
            "classification": item["classification"],
            "required": True,
            **{
                key: value
                for key, value in item.items()
                if key not in {"name", "classification", "required"}
            },
        }
        for item in command_results
    ]
    criteria.append(
        {
            "id": "worktree_sentinel",
            **{key: value for key, value in sentinel.items() if key != "name"},
            "rejection_codes": _rejection_codes(
                str(sentinel.get("reason", "")),
                classification=str(sentinel.get("classification", "")),
            ),
        }
    )

    evidence_results: list[dict[str, Any]] = []
    if not evidence_paths:
        evidence_results.append(
            {
                "path": "<none>",
                "required": True,
                "classification": NOT_RUN,
                "reason": "required release evidence paths are not configured",
                "rejection_codes": ["MISSING_EVIDENCE_REJECTED"],
            }
        )
    else:
        for raw_path in evidence_paths:
            safe_path, path_error = _safe_evidence_path(root, raw_path)
            if path_error:
                evidence_result = {
                    "path": raw_path,
                    "required": True,
                    "classification": FAIL,
                    "reason": path_error,
                }
            else:
                evidence_result = evaluate_evidence(safe_path, after, root=root)  # type: ignore[arg-type]
            evidence_results.append(evidence_result)
    for evidence_result in evidence_results:
        criteria.append(
            {
                "id": f"evidence:{evidence_result['path']}",
                **evidence_result,
            }
        )

    live_production = {
        "id": "live_production",
        "classification": NOT_RUN,
        "required": False,
        "claim": False,
        "reason": "offline gate does not probe Docker, providers, databases, or production services",
    }
    criteria.append(live_production)
    classification = _overall_classification(criteria)

    errors = [
        f"{item['id']}: {item.get('reason', item['classification'])}"
        for item in criteria
        if item.get("classification") in {FAIL, BLOCKED_EXTERNAL}
        or (item.get("required") and item.get("classification") == NOT_RUN)
    ]
    warnings = [
        f"{item['id']}: {item.get('reason', item['classification'])}"
        for item in criteria
        if not item.get("required") and item.get("classification") == NOT_RUN
    ]
    for evidence in evidence_results:
        warnings.extend(evidence.get("warnings", []))

    rejection_codes = sorted(
        {
            code
            for criterion in criteria
            for code in criterion.get("rejection_codes", [])
            if isinstance(code, str)
        }
    )

    return {
        "schema_version": "state-of-art-release-integrity.v1",
        "gate": "release-integrity",
        "classification": classification,
        "status": classification,
        "HEAD": after.get("HEAD"),
        "head": after.get("head"),
        "worktree_status": after.get("status"),
        "status_fingerprint": after.get("status_fingerprint"),
        "checkout_fingerprint": after.get("fingerprint"),
        "fingerprint": {
            "checkout": after.get("fingerprint"),
            "status": after.get("status_fingerprint"),
            "before": before.get("fingerprint"),
            "after": after.get("fingerprint"),
        },
        "checkout": {
            "HEAD": after.get("HEAD"),
            "tree": after.get("tree"),
            "branch": after.get("branch"),
            "status": after.get("status"),
            "status_entries": after.get("status_entries"),
            "status_fingerprint": after.get("status_fingerprint"),
            "fingerprint": after.get("fingerprint"),
        },
        "worktree": {
            "before": {
                "status": before.get("status"),
                "fingerprint": before.get("fingerprint"),
            },
            "after": {
                "status": after.get("status"),
                "fingerprint": after.get("fingerprint"),
            },
            "sentinel": sentinel,
        },
        "commands": command_results,
        "evidence": evidence_results,
        "live_production": live_production,
        "criteria": criteria,
        "errors": errors,
        "warnings": warnings,
        "rejection_codes": rejection_codes,
    }


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence",
        action="append",
        dest="evidence_paths",
        help="required release evidence JSON path inside the checkout (repeatable)",
    )
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="fail when the checkout is already dirty; the release workflow enables this",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="per-command timeout (default: 120)",
    )
    args = parser.parse_args(argv)
    if args.timeout_seconds < 1:
        parser.error("--timeout-seconds must be positive")
    if not args.evidence_paths:
        args.evidence_paths = list(DEFAULT_EVIDENCE)
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    artifact = run_gate(
        args.root,
        evidence_paths=args.evidence_paths,
        require_clean=args.require_clean,
        timeout=args.timeout_seconds,
    )
    print(json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2))
    if artifact["classification"] == PASS:
        return 0
    if artifact["classification"] == BLOCKED_EXTERNAL:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
