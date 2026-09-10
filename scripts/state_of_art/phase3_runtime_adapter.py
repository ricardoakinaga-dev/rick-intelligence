"""Shared adapter for commit-bound Phase 3 runtime evidence envelopes.

The Phase 11 gates own service-specific assertions.  This module owns the
stable Phase 3 evidence boundary: safe paths, normalized fail-closed status,
checkout identity, raw-artifact hashing, freshness and production-safety
metadata.  It deliberately never interprets a blocked or partial gate as a
runtime pass.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any

try:
    from scripts.state_of_art.release_integrity import capture_checkout
    from scripts.state_of_art.runtime_preflight import (
        DEFAULT_COMPOSE_FILE,
        DEFAULT_PATH,
        canonical_compose_project,
        load_preflight,
    )
except ImportError:  # pragma: no cover - direct script execution fallback.
    from release_integrity import capture_checkout
    from runtime_preflight import DEFAULT_COMPOSE_FILE, DEFAULT_PATH, canonical_compose_project, load_preflight


SCHEMA_VERSION = "state-of-art-runtime-evidence.v1"
def _safe_path(root: Path, raw: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("evidence path must be a non-empty string")
    path = (root / raw).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        raise ValueError("evidence path must remain inside the repository root") from None
    return path


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_SENSITIVE_KEY = re.compile(
    r"(?:password|passphrase|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|authorization|cookie|credential|dsn|url)",
    re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(
    r"(?:redis|rediss|postgres(?:ql)?|mysql|amqp|https?)://[^\s\"']+|bearer\s+[^\s\"']+",
    re.IGNORECASE,
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?<![A-Za-z0-9_-])([\"']?[A-Za-z0-9_-]*(?:password|passphrase|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|authorization|cookie|credential|dsn|url|bearer)[A-Za-z0-9_-]*[\"']?)"
    r"(\s*[:=]\s*)(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|\[REDACTED\]|[^\s,;}\]]+)",
    re.IGNORECASE,
)
_SENSITIVE_ARGUMENT = re.compile(
    r"(?<![A-Za-z0-9_-])"
    r"([/-]{0,2}[A-Za-z0-9_-]*(?:password|passphrase|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|authorization|cookie|credential|dsn|url|bearer)[A-Za-z0-9_-]*)"
    r"(\s+)"
    r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|\[REDACTED\]|[^\s,;}\]]+)",
    re.IGNORECASE,
)


def _redact_text(value: str) -> str:
    value = _SENSITIVE_VALUE.sub("[REDACTED]", value)
    value = _SENSITIVE_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
        value,
    )
    return _SENSITIVE_ARGUMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
        value,
    )


def _redact(value: Any, *, key: str = "") -> Any:
    """Return a JSON-safe gate projection with secret-bearing fields removed."""

    if _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(name): _redact(item, key=str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def redact_runtime_value(value: Any) -> Any:
    """Redact secret-bearing values before they are persisted as evidence."""

    return _redact(value)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


_CHECKOUT_SHA1 = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_CHECKOUT_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
_CHECKOUT_IDENTITY_FIELDS = ("head", "tree", "fingerprint", "status")


def _capture_checkout(root: Path, capture: Callable[[Path], dict[str, Any]]) -> dict[str, Any]:
    try:
        captured = capture(root)
    except Exception:
        return {
            "available": False,
            "head": None,
            "tree": None,
            "fingerprint": None,
            "status": "UNKNOWN",
            "errors": ["checkout capture failed"],
        }
    if not isinstance(captured, Mapping):
        return {
            "available": False,
            "head": None,
            "tree": None,
            "fingerprint": None,
            "status": "UNKNOWN",
            "errors": ["checkout capture returned a non-object"],
        }
    return dict(captured)


def _valid_checkout(checkout: Mapping[str, Any]) -> bool:
    errors = checkout.get("errors")
    return (
        checkout.get("available") is True
        and checkout.get("status") == "CLEAN"
        and isinstance(checkout.get("head"), str)
        and bool(_CHECKOUT_SHA1.fullmatch(checkout["head"]))
        and isinstance(checkout.get("tree"), str)
        and bool(_CHECKOUT_SHA1.fullmatch(checkout["tree"]))
        and isinstance(checkout.get("fingerprint"), str)
        and bool(_CHECKOUT_SHA256.fullmatch(checkout["fingerprint"]))
        and isinstance(errors, Sequence)
        and not isinstance(errors, (str, bytes, bytearray))
        and not errors
    )


def _same_checkout(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    return _valid_checkout(before) and _valid_checkout(after) and all(
        before.get(field) == after.get(field) for field in _CHECKOUT_IDENTITY_FIELDS
    )


def _checkout_snapshot(checkout: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "available": checkout.get("available") is True,
        "head": checkout.get("head"),
        "tree": checkout.get("tree"),
        "fingerprint": checkout.get("fingerprint"),
        "status": checkout.get("status"),
    }


def _normalize_status(raw: Mapping[str, Any], exit_status: int) -> str:
    raw_status = raw.get("status")
    if raw_status == "BLOCKED_EXTERNAL" or exit_status == 2:
        return "BLOCKED_EXTERNAL"
    if raw_status == "PASS" and exit_status == 0:
        return "PASS"
    return "FAILED"


def _fallback_payload(error_name: str) -> dict[str, Any]:
    return {
        "schema_version": "phase3-runtime-gate-adapter-error.v1",
        "status": "FAIL",
        "results": [
            {
                "name": "adapter",
                "result": "FAIL",
                "detail": f"runtime gate output unavailable ({error_name})",
            }
        ],
        "runtime_claim": False,
        "production_safe": False,
    }


def _expected_compose_target(root: Path) -> tuple[str | None, str | None]:
    raw = os.environ.get("RICK_COMPOSE_FILE", DEFAULT_COMPOSE_FILE).strip()
    candidate = Path(raw)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        return None, None
    normalized = candidate.as_posix()
    if normalized != raw.replace("\\", "/") or not (root / candidate).is_file():
        return None, None
    return normalized, canonical_compose_project(root, normalized)


def run_gate_adapter(
    root: Path,
    gate_main: Callable[[list[str]], int],
    *,
    capability_id: str,
    output: str,
    raw_output: str,
    environment: str,
    procedure: str,
    argv: Sequence[str] = (),
    checkout_capture: Callable[[Path], dict[str, Any]] = capture_checkout,
    preflight_path: str | None = None,
) -> dict[str, Any]:
    """Execute one gate and emit a typed, commit-bound evidence envelope."""

    root = root.resolve()
    output_path = _safe_path(root, output)
    raw_base_path = _safe_path(root, raw_output)
    if output_path == raw_base_path:
        raise ValueError("envelope and raw gate output must be different files")
    checkout_before = _capture_checkout(root, checkout_capture)
    selected_preflight = preflight_path or os.environ.get("RICK_PHASE3_PREFLIGHT") or DEFAULT_PATH
    try:
        selected_preflight = str(Path(selected_preflight).as_posix())
    except (TypeError, ValueError):
        selected_preflight = ""
    preflight_before_payload, preflight_before_errors, preflight_before_digest = load_preflight(
        root,
        selected_preflight,
        expected_checkout=checkout_before,
        expected_compose_file=_expected_compose_target(root)[0],
        expected_compose_project=_expected_compose_target(root)[1],
    )
    raw_path = raw_base_path.with_name(
        f"{raw_base_path.stem}-{uuid.uuid4().hex[:12]}{raw_base_path.suffix or '.json'}"
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)

    gate_args = [*argv, "--output", str(raw_path.relative_to(root))]
    try:
        exit_status = int(gate_main(gate_args))
        if exit_status < 0:
            raise ValueError("runtime gate returned a negative exit status")
    except Exception as exc:
        exit_status = 1
        raw_payload = _fallback_payload(type(exc).__name__)
        _write_json(raw_path, raw_payload)
    else:
        try:
            raw_payload_value = json.loads(raw_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raw_payload = _fallback_payload(type(exc).__name__)
            exit_status = 1
            _write_json(raw_path, raw_payload)
        else:
            raw_payload = _redact(raw_payload_value) if isinstance(raw_payload_value, dict) else _fallback_payload("non_object_json")
            if not isinstance(raw_payload_value, dict):
                exit_status = 1
            _write_json(raw_path, raw_payload)

    checkout_after = _capture_checkout(root, checkout_capture)
    checkout_unchanged = _same_checkout(checkout_before, checkout_after)
    checkout_clean = checkout_after.get("available") is True and checkout_after.get("status") == "CLEAN"
    observed_at = datetime.now(timezone.utc).isoformat()
    status = _normalize_status(raw_payload, exit_status)
    if not checkout_unchanged:
        status = "FAILED"
        exit_status = 1
    raw_digest_value = _sha256(raw_path)
    if raw_digest_value is None:
        status = "FAILED"
        exit_status = 1
    if status == "BLOCKED_EXTERNAL":
        exit_status = 2
    elif status == "FAILED" and exit_status == 0:
        exit_status = 1

    preflight_payload, preflight_after_errors, preflight_digest = load_preflight(
        root,
        selected_preflight,
        expected_checkout=checkout_after,
        expected_compose_file=_expected_compose_target(root)[0],
        expected_compose_project=_expected_compose_target(root)[1],
    )
    preflight_unchanged = preflight_before_digest == preflight_digest
    preflight_errors = [
        *(f"before: {error}" for error in preflight_before_errors),
        *(f"after: {error}" for error in preflight_after_errors),
    ]
    if not preflight_unchanged:
        preflight_errors.append("preflight artifact changed while the gate was running")
    preflight_before_valid = (
        preflight_before_payload is not None
        and not preflight_before_errors
        and preflight_before_digest is not None
    )
    preflight_after_valid = (
        preflight_payload is not None
        and not preflight_after_errors
        and preflight_digest is not None
    )
    preflight_is_valid = preflight_before_valid and preflight_after_valid and preflight_unchanged
    preflight_status = "PASS" if preflight_is_valid else (
        "MISSING"
        if preflight_before_payload is None
        and preflight_payload is None
        and preflight_before_digest is None
        and preflight_digest is None
        else "INVALID"
    )
    if status == "PASS" and not preflight_is_valid:
        # A service gate cannot upgrade a run into runtime evidence without the
        # same-run shared lab attestation.  Missing infrastructure is an
        # external block; a present but contradictory attestation is a failure.
        status = "BLOCKED_EXTERNAL" if preflight_status == "MISSING" else "FAILED"
        exit_status = 2 if status == "BLOCKED_EXTERNAL" else 1
    production_safe = (
        checkout_unchanged
        and raw_digest_value is not None
        and status in {"PASS", "VERIFIED_RUNTIME", "PROMOTABLE"}
        and raw_payload.get("production_safe") is True
        and preflight_is_valid
    )

    if status == "PASS":
        limitations = [
            "Automated runtime assertions passed; an independent Phase 3 review is still required.",
            "This envelope does not by itself prove full production promotion or unrelated capabilities.",
        ]
        next_action = "Attach this envelope to the complete capability matrix and obtain an independent review."
    elif status == "BLOCKED_EXTERNAL":
        limitations = [
            "The required disposable runtime or approved configuration was unavailable; no runtime claim is made.",
            "No blocked service assertion is upgraded to PASS or PROMOTABLE.",
        ]
        next_action = "Provide approved disposable runtime access and rerun this gate on the resulting clean commit."
    else:
        limitations = [
            "The underlying runtime gate failed or emitted an invalid result; raw output is retained for diagnosis.",
            "No runtime or promotion claim is made from this envelope.",
        ]
        next_action = "Repair the underlying gate, retain this failed record, and create a new run."

    envelope = {
        "schema_version": SCHEMA_VERSION,
        "record_id": f"PH3-{capability_id}-{observed_at.replace('-', '').replace(':', '').replace('.', '')}",
        "capability_id": capability_id,
        "status": status,
        "commit_sha": checkout_after.get("head"),
        "tree_sha": checkout_after.get("tree"),
        "checkout_fingerprint": checkout_after.get("fingerprint"),
        "checkout_available": checkout_after.get("available") is True,
        "clean_worktree": checkout_clean,
        "artifact_sha256": raw_digest_value,
        "environment": environment,
        "procedure": procedure,
        "exit_status": exit_status,
        "observed_at": observed_at,
        "freshness": "CURRENT" if checkout_unchanged else (
            "DIRTY_CHECKOUT" if checkout_after.get("status") != "CLEAN" else "INVALID_CHECKOUT"
        ),
        "production_safe": production_safe,
        "preflight_path": selected_preflight or None,
        "preflight_sha256": preflight_digest,
        "preflight": {
            "status": preflight_status,
            "path": selected_preflight or None,
            "sha256": preflight_digest,
            "before_sha256": preflight_before_digest,
            "unchanged": preflight_unchanged,
            "run_id": preflight_payload.get("run_id") if isinstance(preflight_payload, dict) else None,
            "target_id": preflight_payload.get("target_id") if isinstance(preflight_payload, dict) else None,
            "compose_file": preflight_payload.get("compose_file") if isinstance(preflight_payload, dict) else None,
            "compose_project": preflight_payload.get("compose_project") if isinstance(preflight_payload, dict) else None,
            "compose_config_sha256": preflight_payload.get("compose_config_sha256") if isinstance(preflight_payload, dict) else None,
            "compose_source_sha256": preflight_payload.get("compose_source_sha256") if isinstance(preflight_payload, dict) else None,
            "errors": preflight_errors,
        },
        "reviewer": {
            "id": f"automated-phase3-{capability_id.lower()}",
            "kind": "automated",
            "name": f"Phase 3 {capability_id} runtime adapter",
            "independent": False,
        },
        "limitations": limitations,
        "next_action": next_action,
        "checkout_sentinel": {
            "before": _checkout_snapshot(checkout_before),
            "after": _checkout_snapshot(checkout_after),
            "unchanged": checkout_unchanged,
        },
        "raw_artifacts": [
            {
                "path": str(raw_path.relative_to(root)),
                "sha256": raw_digest_value,
                "description": "underlying Phase 11 runtime gate result",
            }
        ],
        "gate": raw_payload,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return envelope
