#!/usr/bin/env python3
"""Run the fail-closed local and runtime verification packet.

The packet is an observation orchestrator.  The promotion engine derives the
classification from the lane results; no score, prose field or prior result
can promote an incomplete candidate.  Raw command output is intentionally
discarded so the packet cannot persist secrets or document content.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

try:
    from scripts.state_of_art.json_boundary import load_json
    from scripts.state_of_art import packet_seal
    from scripts.state_of_art import promotion_engine
    from scripts.state_of_art import triple_aaa_capability_matrix
    from scripts.state_of_art.release_integrity import capture_checkout
except ImportError:  # pragma: no cover - direct script execution fallback.
    from json_boundary import load_json
    import packet_seal
    import promotion_engine
    import triple_aaa_capability_matrix
    from release_integrity import capture_checkout


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ".runtime/phase-3/triple-aaa-verify.json"
SOURCE_PROMPT = "docs/prompts/triple-aaa-runtime-closure-2026-09-10.txt"
QUALITY_BAR = "docs/reports/current-triple-aaa-quality-bar-v1.json"
PACKET_SCHEMA = "state-of-art-triple-aaa-verify.v2"
PHASE3_EVIDENCE_ARTIFACT = ".runtime/phase-3/capability-matrix.json"
RELEASE_EVIDENCE_ARTIFACT = "docs/progress/release-evidence.json"
FRONTEND_RUNTIME_ARTIFACT = ".runtime/phase-3/frontend-supply-runtime-evidence.json"
FRONTEND_RUNTIME_COMMAND = ("make", "phase3-frontend-supply-runtime")

_FRONTEND_LANE_IDS = frozenset({"frontend-e2e", "frontend-accessibility", "supply-chain"})
_FRONTEND_BROWSER_CHECKS = (
    "browser-api-backed-states",
    "viewport-matrix",
    "keyboard",
    "focus",
    "axe",
    "reduced-motion",
    "contrast",
    "touch",
)
_FRONTEND_ACCESSIBILITY_CHECKS = (
    "viewport-matrix",
    "keyboard",
    "focus",
    "axe",
    "reduced-motion",
    "contrast",
    "touch",
)
_FRONTEND_SUPPLY_CHECKS = ("container-digests", "container-sbom")


_ARTIFACT_LANE_PATHS = {
    "phase3-evidence": PHASE3_EVIDENCE_ARTIFACT,
    "release-evidence-generation": RELEASE_EVIDENCE_ARTIFACT,
}


@dataclass(frozen=True)
class Lane:
    lane_id: str
    command: tuple[str, ...] | None
    required: bool = True
    external: bool = False
    detail: str = ""
    blocked_return_codes: frozenset[int] = frozenset()
    blocked_if_not_run: bool = False


def _sha256_file(path: Path) -> str | None:
    try:
        digest = sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _manifest_artifact_hash() -> str | None:
    try:
        payload = load_json(ROOT / "docs/progress/release-evidence.json")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    binding = payload.get("commit_binding") if isinstance(payload, dict) else None
    value = binding.get("artifact_set_sha256") if isinstance(binding, dict) else None
    return value if isinstance(value, str) and value else None


def _phase3_matrix_classification(payload: dict[str, object]) -> str | None:
    """Derive the matrix classification without inspecting command output."""

    capabilities = payload.get("capabilities")
    if isinstance(capabilities, list):
        statuses: list[str] = []
        for capability in capabilities:
            if not isinstance(capability, dict) or not isinstance(capability.get("status"), str):
                return "FAILED"
            statuses.append(capability["status"].upper())
        if not statuses:
            return "FAILED"
        if any(status == "FAILED" for status in statuses):
            return "FAILED"
        if any(status == "BLOCKED_EXTERNAL" for status in statuses):
            return "BLOCKED_EXTERNAL"
        if any(status == "MISSING" for status in statuses):
            return "MISSING"
        if any(status == "NOT_RUN" for status in statuses):
            return "NOT_RUN"
        if any(status in {"PARTIAL", "DONE_LOCAL_SCOPE", "LOCAL_VERIFIED"} for status in statuses):
            return "PARTIAL"
        if all(status == "PROMOTABLE" for status in statuses):
            return "PROMOTABLE"
        if all(status in {"VERIFIED_RUNTIME", "PROMOTABLE"} for status in statuses):
            return "PARTIAL"
        return "FAILED"

    classification = payload.get("classification")
    return classification.upper() if isinstance(classification, str) and classification.strip() else None


def _read_lane_artifact(lane_id: str) -> tuple[str, str, str] | None:
    """Read a known lane artifact and return (lane status, artifact class, detail)."""

    relative_path = _ARTIFACT_LANE_PATHS.get(lane_id)
    if relative_path is None:
        return None

    path = ROOT / relative_path
    if not path.is_file():
        return "NOT_RUN", "NOT_RUN", f"{relative_path} is absent"
    try:
        payload = load_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "FAIL", "FAIL", f"{relative_path} is not readable JSON"
    if not isinstance(payload, dict):
        return "FAIL", "FAIL", f"{relative_path} does not contain a JSON object"

    if lane_id == "phase3-evidence":
        if payload.get("schema_version") != "state-of-art-phase-3-evidence.v1":
            return "FAIL", "FAIL", f"{relative_path} has no approved Phase 3 matrix schema"
        if not isinstance(payload.get("candidate"), dict) or not isinstance(payload.get("capabilities"), list):
            return "FAIL", "FAIL", f"{relative_path} has no complete candidate/capability binding"
        classification = _phase3_matrix_classification(payload)
        promotable = "PROMOTABLE"
    else:
        if payload.get("schema_version") != "state-of-art-release-evidence.v2":
            return "FAIL", "FAIL", f"{relative_path} has no approved release manifest schema"
        if not isinstance(payload.get("commit_binding"), dict) or not isinstance(payload.get("gates"), list):
            return "FAIL", "FAIL", f"{relative_path} has no complete release binding"
        raw_status = payload.get("status", payload.get("classification"))
        classification = raw_status.upper() if isinstance(raw_status, str) and raw_status.strip() else None
        promotable = "PASS"

    if classification is None:
        return "FAIL", "FAIL", f"{relative_path} has no artifact classification"
    if classification == promotable:
        return "PASS", classification, f"{relative_path} reports {classification}"
    if classification == "BLOCKED_EXTERNAL":
        return "BLOCKED_EXTERNAL", classification, f"{relative_path} reports {classification}"
    if classification == "NOT_RUN":
        return "NOT_RUN", classification, f"{relative_path} reports {classification}"
    return "FAIL", classification, f"{relative_path} reports {classification}"


def _read_frontend_runtime_artifact(
    *,
    expected_checkout: dict[str, object] | None = None,
) -> tuple[dict[str, object] | None, dict[str, str] | None, str, str]:
    """Read the combined frontend envelope without collapsing its lanes."""

    relative_path = FRONTEND_RUNTIME_ARTIFACT
    path = ROOT / relative_path
    if not path.is_file():
        return None, None, "NOT_RUN", f"{relative_path} is absent"
    try:
        payload = load_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, None, "FAIL", f"{relative_path} is not readable JSON"
    if not isinstance(payload, dict):
        return None, None, "FAIL", f"{relative_path} does not contain a JSON object"
    if payload.get("schema_version") != "state-of-art-runtime-evidence.v1":
        return None, None, "FAIL", f"{relative_path} has no approved runtime evidence schema"
    if expected_checkout is not None:
        if (
            expected_checkout.get("available") is not True
            or expected_checkout.get("status") != "CLEAN"
            or not isinstance(expected_checkout.get("head"), str)
            or not isinstance(expected_checkout.get("tree"), str)
            or not isinstance(expected_checkout.get("fingerprint"), str)
        ):
            return None, None, "FAIL", "the verifier checkout is unavailable or not clean"
        for artifact_field, checkout_field in (
            ("commit_sha", "head"),
            ("tree_sha", "tree"),
            ("checkout_fingerprint", "fingerprint"),
        ):
            if payload.get(artifact_field) != expected_checkout.get(checkout_field):
                return None, None, "FAIL", f"{relative_path} is not bound to the verifier checkout ({artifact_field})"
        if payload.get("checkout_available") is not True or payload.get("clean_worktree") is not True:
            return None, None, "FAIL", f"{relative_path} does not attest to a clean checkout"
        if payload.get("freshness") != "CURRENT":
            return None, None, "FAIL", f"{relative_path} is not marked CURRENT"
    gate = payload.get("gate")
    if not isinstance(gate, dict):
        return None, None, "FAIL", f"{relative_path} has no gate envelope"
    raw_checks = gate.get("checks")
    if not isinstance(raw_checks, list):
        return None, None, "FAIL", f"{relative_path} has no gate checks"
    checks: dict[str, str] = {}
    for item in raw_checks:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not isinstance(item.get("status"), str):
            return None, None, "FAIL", f"{relative_path} contains a malformed gate check"
        name = item["name"]
        if name in checks:
            return None, None, "FAIL", f"{relative_path} contains a duplicate gate check: {name}"
        checks[name] = item["status"].upper()
    return payload, checks, "READY", f"{relative_path} is current and structurally readable"


def _frontend_requirements_status(
    checks: dict[str, str],
    required_checks: tuple[str, ...],
) -> tuple[str, str]:
    missing = [name for name in required_checks if name not in checks]
    if missing:
        return "FAIL", f"frontend runtime evidence is missing scoped checks: {', '.join(missing)}"
    statuses = [checks[name] for name in required_checks]
    if any(status == "FAIL" for status in statuses):
        return "FAIL", "one or more scoped frontend checks failed"
    if any(status in {"BLOCKED_EXTERNAL", "NOT_RUN", "WARN"} for status in statuses):
        return "BLOCKED_EXTERNAL", "one or more scoped frontend checks are externally blocked or not run"
    if all(status == "PASS" for status in statuses):
        return "PASS", "all scoped frontend checks passed"
    return "FAIL", "one or more scoped frontend checks has an unsupported status"


def _frontend_browser_claim_status(payload: dict[str, object]) -> tuple[str, str]:
    gate = payload.get("gate")
    browser = gate.get("browser_evidence") if isinstance(gate, dict) else None
    if not isinstance(browser, dict):
        return "FAIL", "frontend runtime evidence has no browser evidence object"
    browser_status = browser.get("status")
    if not isinstance(browser_status, str):
        return "FAIL", "browser evidence has no typed status"
    browser_status = browser_status.upper()
    if browser_status in {"BLOCKED_EXTERNAL", "NOT_RUN"}:
        return "BLOCKED_EXTERNAL", "browser evidence is externally blocked or not run"
    if browser_status != "PASS":
        return "FAIL", "browser evidence did not report PASS"
    if browser.get("runtime_claim") is not True or browser.get("fixture_interception") is not False:
        return "FAIL", "browser evidence does not prove a real non-intercepted runtime"
    return "PASS", "real non-intercepted browser evidence passed"


def _apply_frontend_lane_observation(
    lane: Lane,
    command_result: dict[str, object],
    *,
    expected_checkout: dict[str, object] | None = None,
) -> dict[str, object]:
    """Project one scoped lane from the combined frontend/supply envelope."""

    result = dict(command_result)
    source_return_code = command_result.get("return_code")
    source_status = command_result.get("status")
    source_detail = command_result.get("detail")
    result["source_return_code"] = source_return_code
    result["source_status"] = source_status
    result["source_detail"] = source_detail
    payload, checks, artifact_state, artifact_detail = _read_frontend_runtime_artifact(
        expected_checkout=expected_checkout,
    )
    result["artifact_path"] = FRONTEND_RUNTIME_ARTIFACT
    result["artifact_classification"] = artifact_state if artifact_state != "READY" else (payload or {}).get("status", "UNKNOWN")

    if artifact_state != "READY" or payload is None or checks is None:
        if artifact_state == "FAIL":
            scoped_status = "FAIL"
        elif source_status in {"BLOCKED_EXTERNAL", "FAIL"}:
            scoped_status = str(source_status)
        else:
            scoped_status = "NOT_RUN"
        result["status"] = scoped_status
        result["detail"] = artifact_detail
        return result

    if lane.lane_id in {"frontend-e2e", "frontend-accessibility"}:
        browser_status, browser_detail = _frontend_browser_claim_status(payload)
        if browser_status != "PASS":
            result["status"] = browser_status
            result["detail"] = browser_detail
            return result
        required_checks = _FRONTEND_BROWSER_CHECKS if lane.lane_id == "frontend-e2e" else _FRONTEND_ACCESSIBILITY_CHECKS
    else:
        required_checks = _FRONTEND_SUPPLY_CHECKS

    scoped_status, scoped_detail = _frontend_requirements_status(checks, required_checks)
    result["status"] = scoped_status
    result["detail"] = f"{scoped_detail}; {artifact_detail}"
    if scoped_status == "PASS":
        # The combined adapter may return 2 because a different scoped lane is
        # blocked.  The projected lane has its own return contract.
        result["return_code"] = 0
    return result


def _reuse_frontend_command_result(
    lane: Lane,
    source_result: dict[str, object],
    *,
    expected_checkout: dict[str, object] | None = None,
) -> dict[str, object]:
    """Project a second lane without executing the shared adapter again."""

    source = dict(source_result)
    source["id"] = lane.lane_id
    source["required"] = lane.required
    source["external"] = lane.external
    source["return_code"] = source_result.get("source_return_code", source_result.get("return_code"))
    source["status"] = source_result.get("source_status", source_result.get("status"))
    source["detail"] = source_result.get("source_detail", source_result.get("detail"))
    return _apply_frontend_lane_observation(lane, source, expected_checkout=expected_checkout)


def _run(
    lane: Lane,
    *,
    timeout_seconds: int,
    expected_checkout: dict[str, object] | None = None,
) -> dict[str, object]:
    if lane.command is None:
        status = "BLOCKED_EXTERNAL" if lane.blocked_if_not_run else "NOT_RUN"
        return {
            "id": lane.lane_id,
            "status": status,
            "required": lane.required,
            "external": lane.external,
            "return_code": None,
            "detail": lane.detail or ("external dependency gate is blocked" if status == "BLOCKED_EXTERNAL" else "lane was not executed"),
        }
    try:
        process = subprocess.Popen(
            list(lane.command),
            cwd=ROOT,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            return_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            return {
                "id": lane.lane_id,
                "status": "FAIL",
                "required": lane.required,
                "external": lane.external,
                "return_code": None,
                "detail": "lane exceeded its bounded timeout; its process group was terminated",
            }
    except OSError:
        return {
            "id": lane.lane_id,
            "status": "FAIL",
            "required": lane.required,
            "external": lane.external,
            "return_code": None,
            "detail": "lane could not be started",
        }
    if return_code == 0:
        status = "PASS"
        detail = lane.detail or "command returned zero"
    elif return_code in lane.blocked_return_codes:
        status = "BLOCKED_EXTERNAL"
        detail = lane.detail or "external dependency gate is blocked"
    else:
        status = "FAIL"
        detail = lane.detail or "command returned non-zero"
    result: dict[str, object] = {
        "id": lane.lane_id,
        "status": status,
        "required": lane.required,
        "external": lane.external,
        "return_code": return_code,
        "detail": detail,
    }
    artifact = _read_lane_artifact(lane.lane_id)
    if artifact is not None:
        artifact_status, artifact_classification, artifact_detail = artifact
        result["artifact_classification"] = artifact_classification
        if return_code == 0:
            result["status"] = artifact_status
            result["detail"] = artifact_detail
    if lane.lane_id in _FRONTEND_LANE_IDS:
        return _apply_frontend_lane_observation(lane, result, expected_checkout=expected_checkout)
    return result


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
                "scripts/state_of_art/tests/test_promotion_engine.py",
                "scripts/state_of_art/tests/test_packet_seal.py",
                "scripts/state_of_art/tests/test_phase3_lane.py",
                "scripts/state_of_art/tests/test_object_qdrant_runtime.py",
                "scripts/state_of_art/tests/test_provider_runtime.py",
                "scripts/state_of_art/tests/test_golden_runtime.py",
                "scripts/state_of_art/tests/test_tenant_evidence_runtime.py",
                "scripts/state_of_art/tests/test_observability_runtime.py",
                "scripts/state_of_art/tests/test_frontend_supply_runtime.py",
                "scripts/state_of_art/tests/test_restore_runtime.py",
                "scripts/state_of_art/tests/test_file_security_runtime.py",
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
    # The Phase 3 adapter owns the blocked/not-run classification and always
    # refreshes the shared frontend/supply envelope. Skipping it when a browser
    # is absent would leave a previous commit's envelope in the release packet.
    frontend_command = FRONTEND_RUNTIME_COMMAND
    return (
        Lane("release-integrity", None, external=True, detail="clean checkout and current mandatory evidence are required", blocked_if_not_run=True),
        Lane("lab-readiness", None, external=True, detail="approved disposable Docker daemon is unavailable", blocked_if_not_run=True),
        Lane("postgresql-runtime", ("make", "phase3-postgres-runtime"), external=True, blocked_return_codes=frozenset({2})),
        Lane("multi-worker-runtime", ("make", "phase3-multi-worker-runtime"), external=True, detail="two-process worker fencing requires an approved disposable PostgreSQL runtime", blocked_return_codes=frozenset({2})),
        Lane("redis-runtime", ("make", "phase3-redis-runtime"), external=True, blocked_return_codes=frozenset({2})),
        Lane(
            "redis-multi-replica",
            ("make", "phase3-redis-multi-replica-runtime"),
            external=True,
            detail="two-process Redis bucket fencing requires an approved disposable Redis runtime",
            blocked_return_codes=frozenset({2}),
        ),
        Lane("object-qdrant-runtime", ("make", "phase3-object-qdrant-runtime"), external=True, detail="object/vector lifecycle requires approved disposable object and Qdrant services", blocked_return_codes=frozenset({2})),
        Lane("ingestion-e2e", ("make", "phase3-golden-runtime"), external=True, detail="golden API→queue→worker→object→vector lifecycle requires RICK_GOLDEN_RUNTIME_PATH", blocked_return_codes=frozenset({2})),
        Lane("tenant-evidence-runtime", ("make", "phase3-tenant-evidence-runtime"), external=True, detail="live tenant/evidence negative matrix requires RICK_TENANT_EVIDENCE_RUNTIME_PATH", blocked_return_codes=frozenset({2})),
        Lane("provider-rag-runtime", ("make", "phase3-provider-runtime"), external=True, detail="approved provider and RICK_GOLDEN_RUNTIME_PATH corpus/budget authority are required", blocked_return_codes=frozenset({2})),
        Lane("observability-runtime", ("make", "phase3-observability-runtime"), external=True, detail="collector/backend export and alert authority are required", blocked_return_codes=frozenset({2})),
        Lane(
            "frontend-e2e",
            frontend_command,
            external=True,
            detail="browser/runtime/API authority is unavailable or the adapter returned a negative observation",
            blocked_return_codes=frozenset({2}),
        ),
        Lane("frontend-accessibility", frontend_command, external=True, detail="fresh browser accessibility evidence is unavailable or blocked", blocked_return_codes=frozenset({2})),
        Lane("supply-chain", frontend_command, external=True, detail="current SBOM, image, provenance and signature evidence is unavailable or blocked", blocked_return_codes=frozenset({2})),
        Lane("restore-drill", ("make", "phase3-restore-runtime"), external=True, detail="restore authority and disposable backups are unavailable", blocked_return_codes=frozenset({2})),
        Lane("file-security-runtime", ("make", "phase3-file-security-runtime"), external=True, detail="hostile file corpus requires an approved isolated worker runtime", blocked_return_codes=frozenset({2})),
        Lane("performance", ("make", "phase3-performance"), external=True, detail="performance requires an approved RICK_PHASE3_PERFORMANCE_COMMAND harness", blocked_return_codes=frozenset({2})),
        Lane("independent-reviews", None, external=True, detail="fresh independent reviewers are not executable in this process", blocked_if_not_run=True),
        Lane("chaos", ("make", "phase3-chaos"), external=True, detail="chaos requires an approved RICK_PHASE3_CHAOS_COMMAND harness", blocked_return_codes=frozenset({2})),
        Lane("soak", ("make", "phase3-soak"), external=True, detail="soak requires an approved RICK_PHASE3_SOAK_COMMAND harness", blocked_return_codes=frozenset({2})),
        Lane("production-runtime", None, external=True, detail="production-like runtime authority is unavailable", blocked_if_not_run=True),
        Lane("sealed-packet", None, external=True, detail="packet sealing must follow current evidence and independent review", blocked_if_not_run=True),
        Lane("final-go-no-go", None, external=True, detail="authorized human Go/No-Go is unavailable", blocked_if_not_run=True),
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
        blocked_return_codes=frozenset({2}),
    )


def _safe_packet_path(raw_path: str) -> tuple[Path | None, str | None]:
    candidate = Path(raw_path)
    lexical = candidate if candidate.is_absolute() else ROOT / candidate
    try:
        relative = lexical.relative_to(ROOT)
    except ValueError:
        return None, "sealed packet path must remain inside the checkout"
    cursor = ROOT
    for component in relative.parts:
        cursor /= component
        if cursor.is_symlink():
            return None, "sealed packet path must not traverse a symlink"
    resolved = lexical.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        return None, "sealed packet path must remain inside the checkout"
    return resolved, None


def _load_packet(
    raw_path: str | None,
    *,
    trusted_public_keys: dict[str, bytes] | None,
) -> tuple[dict[str, object] | None, dict[str, object]]:
    if raw_path is None:
        return None, {"supplied": False, "status": "NOT_SUPPLIED"}
    path, path_error = _safe_packet_path(raw_path)
    if path_error or path is None:
        return None, {"supplied": True, "path": raw_path, "status": "INVALID_PATH", "error": path_error}
    try:
        value = load_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, {"supplied": True, "path": str(path.relative_to(ROOT)), "status": "UNREADABLE", "error": type(exc).__name__}
    if not isinstance(value, dict):
        return None, {"supplied": True, "path": str(path.relative_to(ROOT)), "status": "INVALID_JSON"}
    valid, errors = packet_seal.verify_seal(
        value,
        trusted_public_keys=trusted_public_keys,
        expected_payload_schema=PACKET_SCHEMA,
    )
    seal = value.get("seal")
    return value, {
        "supplied": True,
        "path": str(path.relative_to(ROOT)),
        "status": "VERIFIED" if valid else "INVALID",
        "seal_verified": valid,
        "seal_errors": list(errors),
        "seal_digest": seal.get("digest") if isinstance(seal, dict) else None,
        "immutable_reference": seal.get("immutable_reference") if isinstance(seal, dict) else None,
    }


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _without_packet_lanes(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return [
        item
        for item in value
        if not isinstance(item, dict) or item.get("id") not in {"sealed-packet", "final-go-no-go"}
    ]


def _packet_matches_current(
    packet: dict[str, object] | None,
    results: list[dict[str, object]],
    checkout: dict[str, object],
    requested_reference: str | None,
    trusted_public_keys: dict[str, bytes] | None,
) -> bool:
    if packet is None:
        return False
    valid, _errors = packet_seal.verify_seal(
        packet,
        trusted_public_keys=trusted_public_keys,
        expected_payload_schema=PACKET_SCHEMA,
    )
    if not valid or packet.get("sealed") is not True:
        return False
    try:
        # These two observations are the packet's own attestation lanes.  The
        # external packet carries them as PASS; the verifier starts with their
        # unavailable placeholders and fills them only after this comparison.
        if _canonical(_without_packet_lanes(packet.get("results"))) != _canonical(
            _without_packet_lanes(results)
        ):
            return False
    except (TypeError, ValueError):
        return False
    candidate = packet.get("candidate")
    if not isinstance(candidate, dict):
        return False
    if (
        candidate.get("commit_sha") != checkout.get("head")
        or candidate.get("tree_sha") != checkout.get("tree")
        or candidate.get("checkout_fingerprint") != checkout.get("fingerprint")
        or candidate.get("artifact_set_sha256") != checkout.get("artifact_set_sha256")
        or candidate.get("clean_worktree") is not True
        or checkout.get("status") != "CLEAN"
    ):
        return False
    seal = packet.get("seal")
    if requested_reference is not None and (
        not isinstance(seal, dict) or seal.get("immutable_reference") != requested_reference
    ):
        return False
    return True


def _apply_packet_lanes(
    results: list[dict[str, object]],
    packet: dict[str, object] | None,
    checkout: dict[str, object],
    requested_reference: str | None,
    trusted_public_keys: dict[str, bytes] | None,
) -> None:
    """Turn only independently verified packet lanes into observations."""

    if not _packet_matches_current(packet, results, checkout, requested_reference, trusted_public_keys):
        return
    assert packet is not None
    authority = packet.get("decision_authority")
    seal = packet.get("seal")
    signer_id = seal.get("signer_id") if isinstance(seal, dict) else None
    authority_valid = (
        isinstance(authority, dict)
        and authority.get("independent") is True
        and authority.get("authorized") is True
        and authority.get("reviewer_id") == signer_id
        and packet.get("final_decision") in {"GO", "APPROVE"}
        and type(packet.get("critical_high_findings")) is int
        and packet.get("critical_high_findings") == 0
    )
    for item in results:
        lane_id = item.get("id")
        if lane_id == "sealed-packet":
            item.update(
                {
                    "status": "PASS",
                    "return_code": 0,
                    "detail": "external packet seal verified against the current checkout and lane observations",
                }
            )
        elif lane_id == "final-go-no-go" and authority_valid:
            item.update(
                {
                    "status": "PASS",
                    "return_code": 0,
                    "independent": True,
                    "detail": "authorized independent final decision verified from the sealed packet",
                }
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--lane-timeout", type=int, default=300)
    parser.add_argument(
        "--seal-reference",
        help="require the supplied sealed packet to use this immutable artifact reference",
    )
    parser.add_argument(
        "--sealed-packet",
        help="path to an externally sealed packet containing this exact run's observations",
    )
    parser.add_argument(
        "--trust-store",
        help="JSON trust store mapping Ed25519 key ids to base64 public keys; may also use RICK_PROMOTION_TRUST_STORE",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.lane_timeout < 10 or args.lane_timeout > 3_600:
        parser.error("--lane-timeout must be between 10 and 3600 seconds")
    if args.seal_reference is not None and args.sealed_packet is None:
        parser.error("--seal-reference requires --sealed-packet; the verifier cannot self-seal a promotion packet")

    results: list[dict[str, object]] = []
    verifier_checkout = capture_checkout(ROOT)
    for lane in _local_lanes():
        results.append(_run(lane, timeout_seconds=args.lane_timeout))

    # Runtime lanes produce the commit-bound envelopes consumed by both the
    # Phase 3 matrix and the typed release manifest.  They must run first;
    # otherwise release-integrity observes the previous run's envelopes and
    # correctly rejects an internally inconsistent packet as stale.
    frontend_command_result: dict[str, object] | None = None
    for lane in _external_lanes():
        if lane.lane_id == "release-integrity":
            continue
        if lane.command == FRONTEND_RUNTIME_COMMAND:
            if frontend_command_result is None:
                frontend_command_result = _run(
                    lane,
                    timeout_seconds=args.lane_timeout,
                    expected_checkout=verifier_checkout,
                )
                results.append(frontend_command_result)
            else:
                results.append(
                    _reuse_frontend_command_result(
                        lane,
                        frontend_command_result,
                        expected_checkout=verifier_checkout,
                    )
                )
            continue
        results.append(_run(lane, timeout_seconds=args.lane_timeout))

    results.append(_run(Lane("phase3-evidence", ("make", "phase3-evidence")), timeout_seconds=args.lane_timeout))
    results.append(
        _run(
            Lane(
                "phase3-evidence-verify",
                (sys.executable, "scripts/state_of_art/generate_phase3_evidence.py", "--verify", "--require-promotable"),
                external=True,
                detail="the complete capability matrix is not promotable until every required row has current evidence",
                blocked_return_codes=frozenset({2}),
            ),
            timeout_seconds=args.lane_timeout,
        )
    )
    results.append(_run(Lane("release-evidence-generation", ("make", "release-evidence")), timeout_seconds=args.lane_timeout))
    results.append(_run(_release_gate(), timeout_seconds=args.lane_timeout))

    if args.seal_reference is not None and packet_seal.REFERENCE_RE.fullmatch(args.seal_reference) is None:
        parser.error("--seal-reference contains unsupported characters")
    trust_store_path = args.trust_store or os.environ.get("RICK_PROMOTION_TRUST_STORE")
    trusted_public_keys: dict[str, bytes] | None = None
    trust_store_info: dict[str, object] = {
        "supplied": bool(trust_store_path),
        "status": "NOT_SUPPLIED" if not trust_store_path else "INVALID",
        "key_count": 0,
    }
    if trust_store_path:
        try:
            trusted_public_keys = packet_seal.load_trust_store(trust_store_path)
        except ValueError as exc:
            trust_store_info["error"] = str(exc)
        else:
            trust_store_info.update({"status": "LOADED", "key_count": len(trusted_public_keys)})
    packet, packet_info = _load_packet(
        args.sealed_packet,
        trusted_public_keys=trusted_public_keys,
    )
    packet_info["trust_store"] = trust_store_info
    if packet is not None and args.seal_reference is not None:
        seal = packet.get("seal")
        if not isinstance(seal, dict) or seal.get("immutable_reference") != args.seal_reference:
            packet = dict(packet)
            packet["seal_reference_mismatch"] = True
            packet_info["status"] = "INVALID_REFERENCE"
            packet_info["seal_verified"] = False
    checkout = capture_checkout(ROOT)
    # The release manifest is the authoritative artifact-set binding for the
    # sealed packet.  Keep it alongside the checkout identity so the
    # promotion engine can reject a packet from a different manifest.
    checkout["artifact_set_sha256"] = _manifest_artifact_hash()
    checkout["quality_bar_sha256"] = _sha256_file(ROOT / QUALITY_BAR)
    _apply_packet_lanes(
        results,
        packet,
        checkout,
        args.seal_reference,
        trusted_public_keys,
    )
    derived = promotion_engine.evaluate(
        results,
        packet=packet,
        checkout=checkout,
        trusted_public_keys=trusted_public_keys,
        evidence_root=ROOT,
    )
    payload: dict[str, object] = {
        "schema_version": PACKET_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verdict": derived["classification"],
        "classification": derived["classification"],
        "promotion_allowed": derived["promotion_allowed"],
        "exit_code": derived["exit_code"],
        "rejection_codes": derived["rejection_codes"],
        "candidate": {
            "commit_sha": checkout.get("head"),
            "tree_sha": checkout.get("tree"),
            "checkout_fingerprint": checkout.get("fingerprint"),
            "artifact_set_sha256": _manifest_artifact_hash(),
            "branch": checkout.get("branch"),
            "worktree_status": checkout.get("status"),
            "clean_worktree": checkout.get("status") == "CLEAN",
        },
        "source_prompt": SOURCE_PROMPT,
        "source_prompt_sha256": _sha256_file(ROOT / SOURCE_PROMPT),
        "quality_bar": {"path": QUALITY_BAR, "sha256": _sha256_file(ROOT / QUALITY_BAR)},
        "stage_results": derived["stage_results"],
        "blocking_lanes": derived["blocking_lanes"],
        "required_lanes": derived["required_lanes"],
        "results": results,
        "promotion_packet": packet_info,
        "limitations": [
            "This packet is only current for the exact checkout and environment that produced it.",
            "A blocked, stale, invalid or not-run required lane prevents promotion; no score averaging is performed.",
            "Raw command output is intentionally omitted; detailed evidence belongs in redacted, separately hashed artifacts.",
        ],
    }
    if not packet_info.get("seal_verified"):
        payload["seal"] = {
            "status": "NOT_SEALED",
            "reason": "an externally authorized sealed packet is required; the verifier never self-seals",
        }
    else:
        payload["seal"] = {
            "status": "EXTERNAL_PACKET_VERIFIED",
            "digest": packet_info.get("seal_digest"),
            "immutable_reference": packet_info.get("immutable_reference"),
        }
    output = (ROOT / args.output).resolve()
    output.relative_to(ROOT.resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    try:
        triple_aaa_capability_matrix.bind_to_packet(
            packet=output,
            output=ROOT / ".runtime/phase-3/current-triple-aaa-runtime-capability-matrix.json",
        )
    except (OSError, ValueError, TypeError, RecursionError):
        # The verifier packet remains authoritative; a missing current-matrix
        # projection is intentionally not upgraded to PASS by this best-effort
        # diagnostic export.
        pass
    current_matrix = ROOT / ".runtime/phase-3/current-triple-aaa-runtime-capability-matrix.json"
    if current_matrix.is_file():
        payload["current_capability_matrix"] = {
            "path": str(current_matrix.relative_to(ROOT)),
            "sha256": _sha256_file(current_matrix),
        }
        output.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": args.output, "classification": derived["classification"], "exit_code": derived["exit_code"]}, sort_keys=True))
    return int(derived["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
