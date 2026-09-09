"""Typed Phase 3 capability evidence and fail-closed matrix validation.

The matrix is intentionally separate from the older release manifest.  The
release manifest answers whether a candidate can be released; this module
records the richer Phase 3 capability status without upgrading local or
unavailable evidence into runtime proof.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from collections.abc import Mapping, Sequence
from typing import Any


MATRIX_SCHEMA = "state-of-art-phase-3-evidence.v1"
STATUSES = frozenset(
    {
        "DONE_LOCAL_SCOPE",
        "LOCAL_VERIFIED",
        "VERIFIED_RUNTIME",
        "PARTIAL",
        "MISSING",
        "BLOCKED_EXTERNAL",
        "FAILED",
        "PROMOTABLE",
        "NOT_RUN",
    }
)
PRIORITIES = frozenset({"P0", "P1", "P2"})
SHA1_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
REQUIRED_CAPABILITY_IDS = frozenset(
    {f"P0-{index:02d}" for index in range(1, 9)}
    | {f"P1-{index:02d}" for index in range(1, 9)}
    | {"P2-01"}
)
RUNTIME_EVIDENCE_SCHEMA = "state-of-art-runtime-evidence.v1"


class MatrixValidationError(ValueError):
    """Raised when a Phase 3 matrix is not representable or is unsafe."""

    def __init__(self, errors: Sequence[str]):
        self.errors = tuple(errors)
        super().__init__("; ".join(self.errors))


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MatrixValidationError((f"{field} must be a non-empty string",))
    return value.strip()


def _sha(value: Any, field: str, pattern: re.Pattern[str]) -> str:
    candidate = _text(value, field).lower()
    if candidate.startswith("sha256:"):
        candidate = candidate[7:]
    if not pattern.fullmatch(candidate):
        raise MatrixValidationError((f"{field} has an invalid digest",))
    return candidate


def _string_list(value: Any, field: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise MatrixValidationError((f"{field} must be a list of strings",))
    values: list[str] = []
    errors: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{field}[{index}] must be a non-empty string")
        else:
            values.append(item.strip())
    if errors or (not allow_empty and not values):
        if not errors:
            errors.append(f"{field} must not be empty")
        raise MatrixValidationError(errors)
    return tuple(values)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _safe_path(root: Path, raw_path: str) -> tuple[Path | None, str | None]:
    candidate = Path(raw_path)
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None, "path must remain inside the repository root"
    return resolved, None


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_set_digest(artifact_refs: Sequence[Mapping[str, str]]) -> str:
    """Return the deterministic digest for a capability's artifact refs."""

    canonical = [
        {
            "description": _text(item.get("description"), "artifact.description"),
            "path": _text(item.get("path"), "artifact.path"),
            "sha256": _sha(item.get("sha256"), "artifact.sha256", SHA256_RE),
        }
        for item in artifact_refs
    ]
    canonical.sort(key=lambda item: item["path"])
    return hashlib.sha256(_canonical(canonical)).hexdigest()


def _parse_ref(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise MatrixValidationError((f"{field} must be an object",))
    return {
        "path": _text(value.get("path"), f"{field}.path"),
        "sha256": _sha(value.get("sha256"), f"{field}.sha256", SHA256_RE),
        "description": _text(value.get("description"), f"{field}.description"),
    }


def _parse_reviewer(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MatrixValidationError((f"{field} must be an object",))
    independent = value.get("independent")
    if not isinstance(independent, bool):
        raise MatrixValidationError((f"{field}.independent must be boolean",))
    return {
        "id": _text(value.get("id"), f"{field}.id"),
        "kind": _text(value.get("kind"), f"{field}.kind"),
        "name": _text(value.get("name"), f"{field}.name"),
        "independent": independent,
    }


def _validate_timestamp(value: str, field: str, errors: list[str]) -> None:
    try:
        parsed = value.replace("Z", "+00:00")
        timestamp = datetime.fromisoformat(parsed)
    except ValueError:
        errors.append(f"{field} is not an ISO-8601 timestamp")
        return
    if timestamp.tzinfo is None:
        errors.append(f"{field} must include a timezone")


def _parse_capability(value: Any, index: int) -> dict[str, Any]:
    field = f"capabilities[{index}]"
    if not isinstance(value, Mapping):
        raise MatrixValidationError((f"{field} must be an object",))
    capability_id = _text(value.get("capability_id"), f"{field}.capability_id")
    priority = _text(value.get("priority"), f"{field}.priority")
    status = _text(value.get("status"), f"{field}.status")
    if priority not in PRIORITIES:
        raise MatrixValidationError((f"{field}.priority is invalid: {priority!r}",))
    if status not in STATUSES:
        raise MatrixValidationError((f"{field}.status is invalid: {status!r}",))
    code_tests = _string_list(value.get("code_tests"), f"{field}.code_tests", allow_empty=False)
    artifact_refs_raw = value.get("artifact_refs")
    if not isinstance(artifact_refs_raw, Sequence) or isinstance(artifact_refs_raw, (str, bytes, bytearray)):
        raise MatrixValidationError((f"{field}.artifact_refs must be a list",))
    artifact_refs = tuple(
        _parse_ref(item, f"{field}.artifact_refs[{ref_index}]")
        for ref_index, item in enumerate(artifact_refs_raw)
    )
    if not artifact_refs:
        raise MatrixValidationError((f"{field}.artifact_refs must not be empty",))
    runtime_raw = value.get("runtime_evidence")
    if not isinstance(runtime_raw, Sequence) or isinstance(runtime_raw, (str, bytes, bytearray)):
        raise MatrixValidationError((f"{field}.runtime_evidence must be a list",))
    runtime_evidence = tuple(
        _parse_ref(item, f"{field}.runtime_evidence[{ref_index}]")
        for ref_index, item in enumerate(runtime_raw)
    )
    reviewer = _parse_reviewer(value.get("reviewer"), f"{field}.reviewer")
    artifact_sha256 = _sha(value.get("artifact_sha256"), f"{field}.artifact_sha256", SHA256_RE)
    procedure = _text(value.get("procedure"), f"{field}.procedure")
    observed_at = _text(value.get("observed_at"), f"{field}.observed_at")
    timestamp_errors: list[str] = []
    _validate_timestamp(observed_at, f"{field}.observed_at", timestamp_errors)
    if timestamp_errors:
        raise MatrixValidationError(timestamp_errors)
    exit_status = value.get("exit_status")
    if exit_status is not None and (type(exit_status) is not int or exit_status < 0):
        raise MatrixValidationError((f"{field}.exit_status must be a non-negative integer or null",))
    parsed = {
        "capability_id": capability_id,
        "title": _text(value.get("title"), f"{field}.title"),
        "priority": priority,
        "status": status,
        "code_tests": list(code_tests),
        "runtime_evidence": list(runtime_evidence),
        "commit_sha": _sha(value.get("commit_sha"), f"{field}.commit_sha", SHA1_RE),
        "artifact_sha256": artifact_sha256,
        "artifact_refs": list(artifact_refs),
        "environment": _text(value.get("environment"), f"{field}.environment"),
        "reviewer": reviewer,
        "procedure": procedure,
        "exit_status": exit_status,
        "observed_at": observed_at,
        "limitations": _text(value.get("limitations"), f"{field}.limitations"),
        "next_action": _text(value.get("next_action"), f"{field}.next_action"),
    }
    if artifact_set_digest(parsed["artifact_refs"]) != artifact_sha256:
        raise MatrixValidationError((f"{field}.artifact_sha256 does not match artifact_refs",))
    if status in {"VERIFIED_RUNTIME", "PROMOTABLE"} and not runtime_evidence:
        raise MatrixValidationError((f"{field}.status={status} requires runtime_evidence",))
    if status in {"VERIFIED_RUNTIME", "PROMOTABLE"} and reviewer["independent"] is not True:
        raise MatrixValidationError((f"{field}.status={status} requires an independent reviewer",))
    if status in {"VERIFIED_RUNTIME", "PROMOTABLE"} and exit_status != 0:
        raise MatrixValidationError((f"{field}.status={status} requires exit_status=0",))
    artifact_paths = {item["path"] for item in artifact_refs}
    runtime_paths = {item["path"] for item in runtime_evidence}
    if artifact_paths & runtime_paths:
        raise MatrixValidationError((f"{field}.runtime_evidence must not reuse artifact_refs",))
    if status in {"MISSING", "BLOCKED_EXTERNAL", "FAILED", "NOT_RUN", "PARTIAL"} and not parsed["limitations"]:
        raise MatrixValidationError((f"{field}.status={status} requires limitations",))
    return parsed


def parse_matrix(value: Any, *, require_complete: bool = False) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MatrixValidationError(("matrix must be an object",))
    errors: list[str] = []
    if value.get("schema_version") != MATRIX_SCHEMA:
        errors.append(f"matrix.schema_version must be {MATRIX_SCHEMA!r}")
    try:
        generated_at = _text(value.get("generated_at"), "matrix.generated_at")
    except MatrixValidationError as exc:
        errors.extend(exc.errors)
        generated_at = ""
    capabilities_raw = value.get("capabilities")
    capabilities: list[dict[str, Any]] = []
    if not isinstance(capabilities_raw, Sequence) or isinstance(capabilities_raw, (str, bytes, bytearray)):
        errors.append("matrix.capabilities must be a list")
    else:
        for index, item in enumerate(capabilities_raw):
            try:
                capabilities.append(_parse_capability(item, index))
            except MatrixValidationError as exc:
                errors.extend(exc.errors)
    candidate_raw = value.get("candidate")
    if not isinstance(candidate_raw, Mapping):
        errors.append("matrix.candidate must be an object")
        candidate: dict[str, Any] = {}
    else:
        try:
            candidate = {
                "commit_sha": _sha(candidate_raw.get("commit_sha"), "matrix.candidate.commit_sha", SHA1_RE),
                "tree_sha": _sha(candidate_raw.get("tree_sha"), "matrix.candidate.tree_sha", SHA1_RE),
                "checkout_fingerprint": _sha(candidate_raw.get("checkout_fingerprint"), "matrix.candidate.checkout_fingerprint", SHA256_RE),
                "clean_worktree": candidate_raw.get("clean_worktree"),
            }
            if not isinstance(candidate["clean_worktree"], bool):
                errors.append("matrix.candidate.clean_worktree must be boolean")
        except MatrixValidationError as exc:
            errors.extend(exc.errors)
            candidate = {}
    try:
        environment = _text(value.get("environment"), "matrix.environment")
        source_prompt = _text(value.get("source_prompt"), "matrix.source_prompt")
        source_prompt_sha256 = _sha(value.get("source_prompt_sha256"), "matrix.source_prompt_sha256", SHA256_RE)
    except MatrixValidationError as exc:
        errors.extend(exc.errors)
        environment = source_prompt = source_prompt_sha256 = ""
    identifiers = [item["capability_id"] for item in capabilities]
    duplicates = sorted({item for item in identifiers if identifiers.count(item) > 1})
    if duplicates:
        errors.append(f"matrix.capabilities has duplicate IDs: {duplicates}")
    if not capabilities:
        errors.append("matrix.capabilities must not be empty")
    if require_complete:
        observed = set(identifiers)
        missing = sorted(REQUIRED_CAPABILITY_IDS - observed)
        unexpected = sorted(observed - REQUIRED_CAPABILITY_IDS)
        if missing:
            errors.append(f"matrix.capabilities is missing required capability IDs: {', '.join(missing)}")
        if unexpected:
            errors.append(f"matrix.capabilities contains unsupported capability IDs: {', '.join(unexpected)}")
    if errors:
        raise MatrixValidationError(errors)
    return {
        "schema_version": MATRIX_SCHEMA,
        "generated_at": generated_at,
        "environment": environment,
        "source_prompt": source_prompt,
        "source_prompt_sha256": source_prompt_sha256,
        "candidate": candidate,
        "capabilities": capabilities,
    }


def _classify_capabilities(capabilities: Sequence[Mapping[str, Any]]) -> tuple[str, str]:
    statuses = [str(item["status"]) for item in capabilities]
    if any(status == "FAILED" for status in statuses):
        return "FAILED", "one or more capabilities failed"
    if any(status == "BLOCKED_EXTERNAL" for status in statuses):
        return "BLOCKED_EXTERNAL", "one or more required capabilities are blocked on external runtime"
    if any(status == "MISSING" for status in statuses):
        return "MISSING", "one or more capabilities are missing"
    if any(status == "NOT_RUN" for status in statuses):
        return "NOT_RUN", "one or more capabilities were not run"
    if any(status in {"PARTIAL", "DONE_LOCAL_SCOPE", "LOCAL_VERIFIED"} for status in statuses):
        return "PARTIAL", "capability evidence is local or partial and is not runtime-promotable"
    if all(status in {"VERIFIED_RUNTIME", "PROMOTABLE"} for status in statuses):
        return "PROMOTABLE", "all capability rows have current runtime evidence"
    return "FAILED", "matrix contains an unsupported promotion state"


def evaluate_matrix(
    path: Path,
    checkout: Mapping[str, Any],
    *,
    root: Path,
    require_complete: bool = True,
) -> dict[str, Any]:
    """Validate a matrix against the observed checkout and classify it."""

    result: dict[str, Any] = {
        "path": str(path.relative_to(root) if path.is_relative_to(root) else path),
        "required": True,
        "schema_version": MATRIX_SCHEMA,
        "rejection_codes": [],
    }
    if not path.is_file():
        result.update(
            {
                "classification": "NOT_RUN",
                "reason": "required Phase 3 capability evidence file is absent",
                "rejection_codes": ["MISSING_EVIDENCE_REJECTED"],
            }
        )
        return result
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        matrix = parse_matrix(payload, require_complete=require_complete)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result.update({"classification": "FAILED", "reason": f"matrix is not readable JSON: {exc}"})
        return result
    except MatrixValidationError as exc:
        codes = []
        if any(
            "required capability IDs" in error
            or "must not reuse artifact_refs" in error
            for error in exc.errors
        ):
            codes.append("MISSING_EVIDENCE_REJECTED")
        result.update(
            {
                "classification": "FAILED",
                "reason": "; ".join(exc.errors),
                "rejection_codes": codes,
            }
        )
        return result

    failures: list[str] = []
    rejection_codes: set[str] = set()
    candidate = matrix["candidate"]
    expected_head = str(checkout.get("head") or "").lower()
    expected_tree = str(checkout.get("tree") or "").lower()
    expected_fingerprint = str(checkout.get("fingerprint") or "").lower()
    if candidate["commit_sha"] != expected_head:
        failures.append("candidate commit does not match this checkout HEAD")
        rejection_codes.add("WRONG_COMMIT_EVIDENCE_REJECTED")
    if expected_tree and candidate["tree_sha"] != expected_tree:
        failures.append("candidate tree does not match this checkout tree")
        rejection_codes.add("WRONG_COMMIT_EVIDENCE_REJECTED")
    if candidate["checkout_fingerprint"] != expected_fingerprint:
        failures.append("candidate checkout fingerprint does not match this checkout")
        rejection_codes.add("WRONG_COMMIT_EVIDENCE_REJECTED")
    if candidate["clean_worktree"] is not True or checkout.get("status") != "CLEAN":
        failures.append("candidate is not bound to a clean checkout")
        rejection_codes.add("DIRTY_RELEASE_EVIDENCE_REJECTED")

    prompt_path, prompt_error = _safe_path(root, matrix["source_prompt"])
    if prompt_error or prompt_path is None or not prompt_path.is_file():
        failures.append("source prompt evidence is absent or outside the checkout")
        rejection_codes.add("MISSING_EVIDENCE_REJECTED")
    else:
        if _hash_file(prompt_path) != matrix["source_prompt_sha256"]:
            failures.append("source prompt evidence hash does not match")
            rejection_codes.add("WRONG_HASH_REJECTED")

    for item in matrix["capabilities"]:
        capability_id = item["capability_id"]
        if item["commit_sha"] != candidate["commit_sha"]:
            failures.append(f"{capability_id}: capability commit does not match candidate")
            rejection_codes.add("WRONG_COMMIT_EVIDENCE_REJECTED")
        if artifact_set_digest(item["artifact_refs"]) != item["artifact_sha256"]:
            failures.append(f"{capability_id}: artifact set hash does not match declaration")
            rejection_codes.add("WRONG_HASH_REJECTED")
        artifact_targets = {
            target
            for ref in item["artifact_refs"]
            for target, path_error in [_safe_path(root, ref["path"])]
            if target is not None and path_error is None
        }
        runtime_targets = {
            target
            for ref in item["runtime_evidence"]
            for target, path_error in [_safe_path(root, ref["path"])]
            if target is not None and path_error is None
        }
        if artifact_targets & runtime_targets:
            failures.append(f"{capability_id}: runtime evidence reuses a static artifact")
            rejection_codes.add("MISSING_EVIDENCE_REJECTED")
        for field in ("code_tests",):
            for raw_path in item[field]:
                target, path_error = _safe_path(root, raw_path)
                if path_error or target is None or not target.exists():
                    failures.append(f"{capability_id}: {field} path is absent: {raw_path}")
                    rejection_codes.add("MISSING_EVIDENCE_REJECTED")
        for field in ("artifact_refs", "runtime_evidence"):
            for ref in item[field]:
                target, path_error = _safe_path(root, ref["path"])
                if path_error or target is None or not target.is_file():
                    failures.append(f"{capability_id}: {field} path is absent: {ref['path']}")
                    rejection_codes.add("MISSING_EVIDENCE_REJECTED")
                    continue
                if _hash_file(target) != ref["sha256"]:
                    failures.append(f"{capability_id}: {field} hash does not match: {ref['path']}")
                    rejection_codes.add("WRONG_HASH_REJECTED")
                if field == "runtime_evidence":
                    try:
                        runtime_record = json.loads(target.read_text(encoding="utf-8"))
                    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                        failures.append(f"{capability_id}: runtime evidence is not a readable JSON envelope: {ref['path']}")
                        rejection_codes.add("MISSING_EVIDENCE_REJECTED")
                        continue
                    if not isinstance(runtime_record, Mapping):
                        failures.append(f"{capability_id}: runtime evidence envelope must be a JSON object: {ref['path']}")
                        rejection_codes.add("MISSING_EVIDENCE_REJECTED")
                        continue
                    envelope_errors: list[str] = []
                    if runtime_record.get("schema_version") != RUNTIME_EVIDENCE_SCHEMA:
                        envelope_errors.append("schema_version")
                    if runtime_record.get("record_id") in {None, ""}:
                        envelope_errors.append("record_id")
                    if runtime_record.get("capability_id") != capability_id:
                        envelope_errors.append("capability_id")
                    if runtime_record.get("status") not in {"PASS", "VERIFIED_RUNTIME", "PROMOTABLE"}:
                        envelope_errors.append("status")
                    runtime_commit = runtime_record.get("commit_sha")
                    if not isinstance(runtime_commit, str) or runtime_commit.lower() != candidate["commit_sha"]:
                        envelope_errors.append("commit_sha")
                        rejection_codes.add("WRONG_COMMIT_EVIDENCE_REJECTED")
                    if runtime_record.get("exit_status") != 0:
                        envelope_errors.append("exit_status")
                    if not isinstance(runtime_record.get("procedure"), str) or not runtime_record["procedure"].strip():
                        envelope_errors.append("procedure")
                    observed_at = runtime_record.get("observed_at")
                    if not isinstance(observed_at, str):
                        envelope_errors.append("observed_at")
                    else:
                        timestamp_errors: list[str] = []
                        _validate_timestamp(observed_at, "runtime evidence observed_at", timestamp_errors)
                        envelope_errors.extend(timestamp_errors)
                    runtime_reviewer = runtime_record.get("reviewer")
                    if (
                        not isinstance(runtime_reviewer, Mapping)
                        or not isinstance(runtime_reviewer.get("id"), str)
                        or not isinstance(runtime_reviewer.get("kind"), str)
                        or not isinstance(runtime_reviewer.get("name"), str)
                    ):
                        envelope_errors.append("reviewer")
                    if envelope_errors:
                        failures.append(
                            f"{capability_id}: runtime evidence envelope invalid ({', '.join(envelope_errors)})"
                        )
                        rejection_codes.add("MISSING_EVIDENCE_REJECTED")
        if item["status"] == "BLOCKED_EXTERNAL":
            rejection_codes.add("BLOCKED_RUNTIME_REJECTED")
        if item["status"] == "NOT_RUN":
            rejection_codes.add("MISSING_EVIDENCE_REJECTED")
        if item["status"] == "FAILED":
            rejection_codes.add("FAILED_RUNTIME_REJECTED")

    if failures:
        result.update(
            {
                "classification": "FAILED",
                "reason": "; ".join(failures),
                "rejection_codes": sorted(rejection_codes),
            }
        )
        return result
    classification, reason = _classify_capabilities(matrix["capabilities"])
    result.update(
        {
            "classification": classification,
            "reason": reason,
            "rejection_codes": sorted(rejection_codes),
            "capability_counts": {
                status: sum(item["status"] == status for item in matrix["capabilities"])
                for status in sorted(STATUSES)
                if any(item["status"] == status for item in matrix["capabilities"])
            },
        }
    )
    return result


def build_artifact_ref(root: Path, path: str, description: str) -> dict[str, str]:
    target, path_error = _safe_path(root, path)
    if path_error or target is None or not target.is_file():
        raise FileNotFoundError(path)
    return {"path": path, "sha256": _hash_file(target), "description": description}


def build_capability(
    root: Path,
    *,
    capability_id: str,
    title: str,
    priority: str,
    status: str,
    code_tests: Sequence[str],
    artifact_paths: Sequence[tuple[str, str]],
    runtime_paths: Sequence[tuple[str, str]] = (),
    commit_sha: str,
    environment: str,
    reviewer: Mapping[str, Any],
    limitations: str,
    next_action: str,
    procedure: str = "local capability verification procedure",
    exit_status: int | None = 0,
    observed_at: str | None = None,
) -> dict[str, Any]:
    artifact_refs = [build_artifact_ref(root, path, description) for path, description in artifact_paths]
    runtime_evidence = [build_artifact_ref(root, path, description) for path, description in runtime_paths]
    return {
        "capability_id": capability_id,
        "title": title,
        "priority": priority,
        "status": status,
        "code_tests": list(code_tests),
        "runtime_evidence": runtime_evidence,
        "commit_sha": commit_sha,
        "artifact_sha256": artifact_set_digest(artifact_refs),
        "artifact_refs": artifact_refs,
        "environment": environment,
        "reviewer": dict(reviewer),
        "procedure": procedure,
        "exit_status": exit_status,
        "observed_at": observed_at or datetime.now().astimezone().isoformat(),
        "limitations": limitations,
        "next_action": next_action,
    }
