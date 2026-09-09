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
from pathlib import Path
from collections.abc import Callable, Mapping, Sequence
from typing import Any

try:
    from scripts.state_of_art.release_integrity import capture_checkout
except ImportError:  # pragma: no cover - direct script execution fallback.
    from release_integrity import capture_checkout


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
) -> dict[str, Any]:
    """Execute one gate and emit a typed, commit-bound evidence envelope."""

    root = root.resolve()
    output_path = _safe_path(root, output)
    raw_path = _safe_path(root, raw_output)
    if output_path == raw_path:
        raise ValueError("envelope and raw gate output must be different files")
    raw_path.parent.mkdir(parents=True, exist_ok=True)

    gate_args = [*argv, "--output", str(raw_path.relative_to(root))]
    try:
        exit_status = int(gate_main(gate_args))
        if exit_status < 0:
            raise ValueError("runtime gate returned a negative exit status")
    except Exception as exc:
        exit_status = 1
        raw_payload = _fallback_payload(type(exc).__name__)
        if not raw_path.is_file():
            raw_path.write_text(json.dumps(raw_payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    else:
        try:
            raw_payload_value = json.loads(raw_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raw_payload = _fallback_payload(type(exc).__name__)
            exit_status = 1
            if not raw_path.is_file():
                raw_path.write_text(json.dumps(raw_payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        else:
            raw_payload = raw_payload_value if isinstance(raw_payload_value, dict) else _fallback_payload("non_object_json")
            if not isinstance(raw_payload_value, dict):
                exit_status = 1

    checkout = checkout_capture(root)
    observed_at = datetime.now(timezone.utc).isoformat()
    status = _normalize_status(raw_payload, exit_status)
    if status == "BLOCKED_EXTERNAL":
        exit_status = 2
    elif status == "FAILED" and exit_status == 0:
        exit_status = 1
    production_safe = (
        status in {"PASS", "VERIFIED_RUNTIME", "PROMOTABLE"}
        and raw_payload.get("production_safe") is True
    )
    raw_digest = _sha256(raw_path)

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
        "commit_sha": checkout.get("head"),
        "tree_sha": checkout.get("tree"),
        "checkout_fingerprint": checkout.get("fingerprint"),
        "clean_worktree": checkout.get("status") == "CLEAN",
        "artifact_sha256": raw_digest,
        "environment": environment,
        "procedure": procedure,
        "exit_status": exit_status,
        "observed_at": observed_at,
        "freshness": "CURRENT" if checkout.get("status") == "CLEAN" else "DIRTY_CHECKOUT",
        "production_safe": production_safe,
        "reviewer": {
            "id": f"automated-phase3-{capability_id.lower()}",
            "kind": "automated",
            "name": f"Phase 3 {capability_id} runtime adapter",
            "independent": False,
        },
        "limitations": limitations,
        "next_action": next_action,
        "raw_artifacts": [
            {
                "path": str(raw_path.relative_to(root)),
                "sha256": raw_digest,
                "description": "underlying Phase 11 runtime gate result",
            }
        ],
        "gate": raw_payload,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return envelope
