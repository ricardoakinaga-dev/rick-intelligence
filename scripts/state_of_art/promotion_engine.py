#!/usr/bin/env python3
"""Derive the RICK promotion level from typed lane observations.

The engine is deliberately small and dependency-light.  It accepts observations
from a verifier, never a caller-supplied verdict, and applies a fixed ladder of
mandatory lane sets.  Missing, stale, blocked and self-promoted evidence stays
blocking; a score or a document cannot override it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

try:
    from scripts.state_of_art import packet_seal
except ImportError:  # pragma: no cover - direct script execution fallback.
    import packet_seal


PASS = "PASS"
FAIL = "FAIL"
BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"
NOT_RUN = "NOT_RUN"
STALE = "STALE"
INVALID = "INVALID"

EXIT_PASS = 0
EXIT_FAILED = 1
EXIT_BLOCKED_EXTERNAL = 2

CLASSIFICATIONS = (
    "DEVELOPMENT",
    "ADVANCED_ENGINEERING",
    "STATE_OF_ART_CANDIDATE",
    "STATE_OF_ART",
    "AAA",
    "TRIPLE_AAA",
)
PROMOTION_PACKET_SCHEMA = "state-of-art-triple-aaa-verify.v2"
QUALITY_BAR_PATH = "docs/reports/current-triple-aaa-quality-bar-v1.json"

# A sealed packet is the final evidence index, rather than a second summary
# of the lane statuses.  Keep its required sections explicit so a signer
# cannot accidentally authorize a packet that only contains a classification
# and a signature.
PACKET_EVIDENCE_FIELDS = (
    "ci_evidence",
    "runtime_evidence",
    "performance",
    "chaos",
    "soak",
    "dr",
    "frontend",
    "supply_chain",
)
PACKET_REVIEW_SCOPES = (
    "Architecture",
    "Security",
    "Runtime",
    "Database",
    "Distributed Systems",
    "RAG",
    "Observability",
    "Recovery",
    "Frontend",
    "Accessibility",
    "Supply Chain",
    "Operations",
)
PACKET_CRITIC_CHECKS = (
    "race_condition",
    "lost_update",
    "split_brain",
    "stale_lease",
    "duplicate_publish",
    "unsafe_retry",
    "deadlock",
    "cross_tenant_leakage",
    "timing_leak",
    "stale_evidence",
    "fake_promotion",
    "secret_leak",
    "retry_storm",
    "orphan_object",
    "stale_qdrant_projection",
    "audit_gaps",
    "unbounded_memory",
    "unsafe_fallback",
)
PACKET_SCORECARD_DIMENSIONS = (
    "Architecture",
    "Modularity",
    "Jobs",
    "Worker",
    "PostgreSQL",
    "Redis",
    "Qdrant",
    "Object Storage",
    "Ingestion",
    "Retrieval",
    "Evidence",
    "Decision",
    "Professor",
    "Provider",
    "Security",
    "Multi-tenancy",
    "Observability",
    "Resilience",
    "Disaster Recovery",
    "Performance",
    "Frontend",
    "Accessibility",
    "CI/CD",
    "Supply Chain",
    "Documentation",
    "Production Readiness",
)

FOUNDATION_LANES = (
    "control-plane",
    "ops-static",
    "compose-static",
    "adversarial-corpus",
    "release-contract-tests",
    "locking",
    "professor",
    "provider",
    "domain",
    "worker",
    "api-root",
    "api-contract",
    "web-lint",
    "web-typecheck",
    "web-build",
    "release-evidence-generation",
)

STATE_OF_ART_LANES = FOUNDATION_LANES + (
    "release-integrity",
    "phase3-evidence-verify",
    "lab-readiness",
    "postgresql-runtime",
    "multi-worker-runtime",
    "redis-runtime",
    "redis-multi-replica",
    "object-qdrant-runtime",
    "ingestion-e2e",
    "tenant-evidence-runtime",
    "provider-rag-runtime",
    "observability-runtime",
    "frontend-e2e",
    "frontend-accessibility",
    "supply-chain",
    "file-security-runtime",
)

AAA_LANES = STATE_OF_ART_LANES + (
    "restore-drill",
    "performance",
    "independent-reviews",
)

TRIPLE_AAA_LANES = AAA_LANES + (
    "chaos",
    "soak",
    "production-runtime",
    "sealed-packet",
    "final-go-no-go",
)

EXTERNAL_LANES = frozenset(set(TRIPLE_AAA_LANES) - set(FOUNDATION_LANES))
INDEPENDENT_LANES = frozenset({"independent-reviews", "final-go-no-go"})
HARD_FAILURES = frozenset({FAIL, STALE, INVALID})
NON_PASS = frozenset({FAIL, BLOCKED_EXTERNAL, NOT_RUN, STALE, INVALID})
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EXTERNAL_ONLY_REJECTIONS = frozenset({"BLOCKED_GATE_REJECTED", "BLOCKED_RUNTIME_REJECTED"})
_MISSING_EXTERNAL_AUTHORITY_REJECTIONS = frozenset(
    {"PACKET_REQUIRED_REJECTED", "PACKET_NOT_SEALED_REJECTED", "FINAL_DECISION_REJECTED"}
)
_MISSING = object()


def _raw_status(item: Mapping[str, Any]) -> str:
    for field in ("status", "classification", "result"):
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    return INVALID


def _status(item: Mapping[str, Any]) -> str:
    """Normalize one observation without treating local proof as runtime PASS."""

    raw = _raw_status(item)
    if raw == PASS:
        if item.get("promotion_allowed") is False:
            return INVALID
        explicit_exit = item.get("exit_status", item.get("return_code", _MISSING))
        if type(explicit_exit) is not int or explicit_exit != 0:
            return INVALID
        for field in ("return_code", "exit_status"):
            if field in item and (type(item[field]) is not int or item[field] != 0):
                return INVALID
        return PASS
    if raw == "PROMOTABLE":
        # PROMOTABLE is a derived matrix/report state, never an observation
        # that can be fed back into the promotion engine as proof.
        return INVALID
    if raw == "VERIFIED_RUNTIME":
        if item.get("production_safe") is True and type(item.get("exit_status")) is int and item.get("exit_status") == 0:
            return PASS
        return INVALID
    if raw in {FAIL, BLOCKED_EXTERNAL, NOT_RUN, STALE, INVALID}:
        return raw
    return INVALID


def _index(results: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Mapping[str, Any]], set[str]]:
    by_id: dict[str, Mapping[str, Any]] = {}
    duplicate_ids: set[str] = set()
    for item in results:
        raw_id = item.get("id", item.get("gate_id", item.get("name")))
        if not isinstance(raw_id, str) or not raw_id.strip():
            duplicate_ids.add("<missing-id>")
            continue
        lane_id = raw_id.strip()
        if lane_id in by_id:
            duplicate_ids.add(lane_id)
        else:
            by_id[lane_id] = item
    return by_id, duplicate_ids


def _synthetic_missing(lane_id: str) -> dict[str, Any]:
    return {
        "id": lane_id,
        "status": NOT_RUN,
        "required": True,
        # An absent observation is missing evidence, not proof that an
        # external dependency was actually attempted and blocked.
        "external": False,
        "detail": "mandatory lane has no observation in this packet",
    }


def _blocking_observations(
    required_lanes: Sequence[str],
    by_id: Mapping[str, Mapping[str, Any]],
    duplicate_ids: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    blockers: list[dict[str, Any]] = []
    rejection_codes: set[str] = set()
    for lane_id in required_lanes:
        item = by_id.get(lane_id) or _synthetic_missing(lane_id)
        status = _status(item)
        # A typed BLOCKED_EXTERNAL observation is itself an external blocker,
        # even when an older producer omitted the advisory ``external`` flag.
        # The status contract must not be weakened by producer metadata.
        external = item.get("external") is True or lane_id in EXTERNAL_LANES or status == BLOCKED_EXTERNAL
        if status == PASS:
            if lane_id in INDEPENDENT_LANES and item.get("independent") is not True:
                blockers.append(
                    {
                        "id": lane_id,
                        "status": INVALID,
                        "external": external,
                        "detail": "independent review/decision was not independently identified",
                    }
                )
                rejection_codes.add("SELF_PROMOTED_GATE_REJECTED")
            continue
        detail = item.get("detail") or item.get("reason") or item.get("limitations") or "lane is not PASS"
        blockers.append(
            {
                "id": lane_id,
                "status": status,
                "external": external,
                "detail": str(detail),
            }
        )
        if status == BLOCKED_EXTERNAL:
            rejection_codes.add("BLOCKED_GATE_REJECTED")
        elif status == NOT_RUN:
            rejection_codes.add("MISSING_GATE_REJECTED")
        elif status == STALE:
            rejection_codes.add("STALE_EVIDENCE_REJECTED")
        elif status == INVALID:
            rejection_codes.add("INVALID_EVIDENCE_REJECTED")
        elif status == FAIL:
            rejection_codes.add("FAILED_GATE_REJECTED")
        rejection_values = item.get("rejection_codes")
        if isinstance(rejection_values, Sequence) and not isinstance(rejection_values, (str, bytes, bytearray)):
            codes = rejection_values
        else:
            codes = ()
        for code in codes:
            if isinstance(code, str) and code.strip():
                rejection_codes.add(code.strip())
    if duplicate_ids:
        rejection_codes.add("DUPLICATE_GATE_REJECTED")
        blockers.append(
            {
                "id": ",".join(sorted(duplicate_ids)),
                "status": INVALID,
                "external": False,
                "detail": "duplicate or missing lane identifiers make the packet ambiguous",
            }
        )
    return blockers, sorted(rejection_codes)


def _all_pass(required_lanes: Sequence[str], by_id: Mapping[str, Mapping[str, Any]]) -> bool:
    return all(_status(by_id.get(lane_id) or _synthetic_missing(lane_id)) == PASS for lane_id in required_lanes)


def _has_hard_foundation_failure(by_id: Mapping[str, Mapping[str, Any]]) -> bool:
    return any(_status(by_id.get(lane_id) or _synthetic_missing(lane_id)) in HARD_FAILURES for lane_id in FOUNDATION_LANES)


def _has_blocked_foundation_lane(by_id: Mapping[str, Mapping[str, Any]]) -> bool:
    """Distinguish external incompleteness from a local foundation failure."""

    return any(
        _status(by_id.get(lane_id) or _synthetic_missing(lane_id)) == BLOCKED_EXTERNAL
        for lane_id in FOUNDATION_LANES
    )


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _packet_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value.removeprefix("sha256:").lower()) is not None


def _packet_nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _packet_reference_hash(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    candidate = value.removeprefix("sha256:").lower()
    return candidate if _SHA256_RE.fullmatch(candidate) else ""


def _packet_local_file(
    raw_path: str,
    *,
    evidence_root: Path | None,
) -> tuple[Path | None, str | None]:
    """Resolve a packet-local evidence path without following symlink swaps."""

    if evidence_root is None:
        return None, "local packet evidence requires an evidence root"
    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        return None, "packet evidence path must be relative to the checkout"
    root = evidence_root.resolve()
    cursor = root
    for component in relative.parts:
        cursor /= component
        if cursor.is_symlink():
            return None, "packet evidence path must not traverse a symlink"
    candidate = cursor.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None, "packet evidence path must remain inside the checkout"
    if not candidate.is_file():
        return None, "packet evidence file is absent"
    return candidate, None


def _validate_packet_reference(
    reference: Mapping[str, Any],
    *,
    field: str,
    evidence_root: Path | None,
) -> tuple[str, str | None]:
    """Validate a SHA-256 reference and, for local paths, its actual bytes."""

    raw_path = reference.get("path")
    expected_hash = _packet_reference_hash(reference.get("sha256"))
    if not _packet_nonempty_text(raw_path):
        return "PACKET_CONTENT_REJECTED", f"{field}.path is required"
    if not expected_hash:
        return "PACKET_CONTENT_REJECTED", f"{field}.sha256 is invalid"
    assert isinstance(raw_path, str)
    if raw_path.startswith("artifact://"):
        return "", None
    local_path, path_error = _packet_local_file(raw_path, evidence_root=evidence_root)
    if path_error or local_path is None:
        return "PACKET_BINDING_REJECTED", f"{field} cannot be verified: {path_error or 'invalid path'}"
    try:
        digest = sha256(local_path.read_bytes()).hexdigest()
    except OSError:
        return "PACKET_BINDING_REJECTED", f"{field} cannot be read from the checkout"
    if digest != expected_hash:
        return "PACKET_BINDING_REJECTED", f"{field}.sha256 does not match the referenced bytes"
    return "", None


def _packet_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _validate_packet_content(
    packet: Mapping[str, Any],
    *,
    checkout: Mapping[str, Any] | None,
    evidence_root: Path | None,
) -> tuple[set[str], list[str]]:
    """Validate the evidence, review, critic and scorecard sections of a seal.

    The Ed25519 seal proves immutability and signer identity, but it does not
    make an underspecified packet complete.  This structural contract keeps
    the final packet aligned with the prompt's explicit evidence inventory and
    prevents a signed classification from bypassing the review/risk bar.
    """

    codes: set[str] = set()
    errors: list[str] = []

    quality_bar = packet.get("quality_bar")
    if not isinstance(quality_bar, Mapping):
        codes.add("PACKET_CONTENT_REJECTED")
        errors.append("sealed packet quality_bar evidence is required")
    else:
        if quality_bar.get("path") != QUALITY_BAR_PATH:
            codes.add("PACKET_CONTENT_REJECTED")
            errors.append("sealed packet quality_bar.path is not the frozen quality bar")
        if not _packet_sha256(quality_bar.get("sha256")):
            codes.add("PACKET_CONTENT_REJECTED")
            errors.append("sealed packet quality_bar.sha256 is invalid")
        expected_quality_bar = checkout.get("quality_bar_sha256") if checkout is not None else None
        if not _packet_sha256(expected_quality_bar):
            codes.add("PACKET_BINDING_REJECTED")
            errors.append("current checkout quality_bar_sha256 is required to promote a sealed packet")
        elif quality_bar.get("sha256") != expected_quality_bar:
            codes.add("PACKET_BINDING_REJECTED")
            errors.append("sealed packet quality_bar.sha256 does not match this checkout")

    for field in PACKET_EVIDENCE_FIELDS:
        value = packet.get(field)
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)) or not value:
            codes.add("PACKET_CONTENT_REJECTED")
            errors.append(f"sealed packet {field} evidence must be a non-empty list")
            continue
        for index, reference in enumerate(value):
            if not isinstance(reference, Mapping):
                codes.add("PACKET_CONTENT_REJECTED")
                errors.append(f"sealed packet {field}[{index}] must be an evidence object")
                continue
            rejection_code, rejection = _validate_packet_reference(
                reference,
                field=f"sealed packet {field}[{index}]",
                evidence_root=evidence_root,
            )
            if rejection_code:
                codes.add(rejection_code)
            if rejection:
                errors.append(rejection)

    review_approvals = packet.get("review_approvals")
    seen_scopes: set[str] = set()
    if not isinstance(review_approvals, Sequence) or isinstance(review_approvals, (str, bytes, bytearray)) or not review_approvals:
        codes.add("INDEPENDENT_REVIEW_REJECTED")
        errors.append("sealed packet review_approvals must be a non-empty list")
    else:
        expected_scopes = {scope.casefold() for scope in PACKET_REVIEW_SCOPES}
        for index, approval in enumerate(review_approvals):
            if not isinstance(approval, Mapping):
                codes.add("INDEPENDENT_REVIEW_REJECTED")
                errors.append(f"sealed packet review_approvals[{index}] must be an object")
                continue
            scope = approval.get("scope")
            normalized_scope = scope.casefold() if isinstance(scope, str) else ""
            if normalized_scope not in expected_scopes:
                codes.add("INDEPENDENT_REVIEW_REJECTED")
                errors.append(f"sealed packet review_approvals[{index}].scope is unsupported")
            elif normalized_scope in seen_scopes:
                codes.add("INDEPENDENT_REVIEW_REJECTED")
                errors.append(f"sealed packet review scope is duplicated: {scope}")
            else:
                seen_scopes.add(normalized_scope)
            if approval.get("independent") is not True or approval.get("fresh") is not True:
                codes.add("INDEPENDENT_REVIEW_REJECTED")
                errors.append(f"sealed packet review_approvals[{index}] is not fresh independent review")
            if str(approval.get("decision", "")).upper() not in {"PASS", "APPROVE"}:
                codes.add("INDEPENDENT_REVIEW_REJECTED")
                errors.append(f"sealed packet review_approvals[{index}] is not an approval")
            if not _packet_nonempty_text(approval.get("reviewer_id")):
                codes.add("INDEPENDENT_REVIEW_REJECTED")
                errors.append(f"sealed packet review_approvals[{index}].reviewer_id is required")
            review_reference = approval.get("review_ref")
            review_sha256 = approval.get("review_sha256")
            if not _packet_nonempty_text(review_reference) or not _packet_sha256(review_sha256):
                codes.add("INDEPENDENT_REVIEW_REJECTED")
                errors.append(f"sealed packet review_approvals[{index}] must bind a review artifact")
            elif isinstance(review_reference, str):
                review_path, _separator, _fragment = review_reference.partition("#")
                review_ref = {"path": review_path, "sha256": review_sha256}
                rejection_code, rejection = _validate_packet_reference(
                    review_ref,
                    field=f"sealed packet review_approvals[{index}].review_ref",
                    evidence_root=evidence_root,
                )
                if rejection_code:
                    codes.add(rejection_code)
                if rejection:
                    errors.append(rejection)
        missing_scopes = sorted(expected_scopes - seen_scopes)
        if missing_scopes:
            codes.add("INDEPENDENT_REVIEW_REJECTED")
            errors.append("sealed packet is missing independent review scopes: " + ", ".join(missing_scopes))

    critic_checklist = packet.get("critic_checklist")
    seen_checks: set[str] = set()
    if not isinstance(critic_checklist, Sequence) or isinstance(critic_checklist, (str, bytes, bytearray)) or not critic_checklist:
        codes.add("CRITIC_CHECKLIST_REJECTED")
        errors.append("sealed packet critic_checklist must be a non-empty list")
    else:
        expected_checks = set(PACKET_CRITIC_CHECKS)
        for index, check in enumerate(critic_checklist):
            if not isinstance(check, Mapping):
                codes.add("CRITIC_CHECKLIST_REJECTED")
                errors.append(f"sealed packet critic_checklist[{index}] must be an object")
                continue
            check_id = check.get("check_id")
            if not isinstance(check_id, str) or check_id not in expected_checks:
                codes.add("CRITIC_CHECKLIST_REJECTED")
                errors.append(f"sealed packet critic_checklist[{index}].check_id is unsupported")
            elif check_id in seen_checks:
                codes.add("CRITIC_CHECKLIST_REJECTED")
                errors.append(f"sealed packet critic check is duplicated: {check_id}")
            else:
                seen_checks.add(check_id)
            if str(check.get("status", "")).upper() not in {"PASS", "CLEAR", "NO_FINDING"}:
                codes.add("CRITIC_CHECKLIST_REJECTED")
                errors.append(f"sealed packet critic_checklist[{index}] did not clear the check")
            if check.get("attempted_rejection") is not True:
                codes.add("CRITIC_CHECKLIST_REJECTED")
                errors.append(f"sealed packet critic_checklist[{index}] has no rejection attempt")
        missing_checks = sorted(expected_checks - seen_checks)
        if missing_checks:
            codes.add("CRITIC_CHECKLIST_REJECTED")
            errors.append("sealed packet is missing critic checks: " + ", ".join(missing_checks))

    risk_register = packet.get("risk_register")
    risk_high_count = 0
    if not isinstance(risk_register, Sequence) or isinstance(risk_register, (str, bytes, bytearray)):
        codes.add("RISK_REGISTER_REJECTED")
        errors.append("sealed packet risk_register must be a list")
    else:
        for index, risk in enumerate(risk_register):
            if not isinstance(risk, Mapping):
                codes.add("RISK_REGISTER_REJECTED")
                errors.append(f"sealed packet risk_register[{index}] must be an object")
                continue
            severity = str(risk.get("severity", "")).upper()
            if severity not in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}:
                codes.add("RISK_REGISTER_REJECTED")
                errors.append(f"sealed packet risk_register[{index}].severity is invalid")
                continue
            if severity in {"CRITICAL", "HIGH"}:
                risk_high_count += 1
            if severity == "MEDIUM":
                missing = [
                    field
                    for field in ("owner", "risk_acceptance", "mitigation", "review_date", "expiration")
                    if not _packet_nonempty_text(risk.get(field))
                ]
                if missing:
                    codes.add("RISK_REGISTER_REJECTED")
                    errors.append(
                        f"sealed packet medium risk {index} is missing: {', '.join(missing)}"
                    )
                expiration = _packet_date(risk.get("expiration"))
                if expiration is None or expiration <= datetime.now(timezone.utc):
                    codes.add("RISK_REGISTER_REJECTED")
                    errors.append(f"sealed packet medium risk {index} has an expired or invalid expiration")
    findings = packet.get("critical_high_findings")
    if risk_high_count or type(findings) is not int or findings != risk_high_count:
        codes.add("OPEN_CRITICAL_HIGH_REJECTED")
        errors.append("critical/high findings must equal the risk register count and be zero")

    final_classification = packet.get("final_classification")
    if final_classification != "TRIPLE_AAA":
        codes.add("FINAL_CLASSIFICATION_REJECTED")
        errors.append("sealed packet final_classification must be TRIPLE_AAA")

    scorecard = packet.get("scorecard")
    if not isinstance(scorecard, Mapping):
        codes.add("SCORECARD_REJECTED")
        errors.append("sealed packet scorecard is required")
    else:
        overall = scorecard.get("overall")
        dimensions = scorecard.get("dimensions")
        if not isinstance(overall, (int, float)) or isinstance(overall, bool) or not 0 <= overall <= 100:
            codes.add("SCORECARD_REJECTED")
            errors.append("sealed packet scorecard.overall must be between 0 and 100")
        if not isinstance(dimensions, Sequence) or isinstance(dimensions, (str, bytes, bytearray)):
            codes.add("SCORECARD_REJECTED")
            errors.append("sealed packet scorecard.dimensions must be a list")
        else:
            observed_scores: dict[str, float] = {}
            for index, dimension in enumerate(dimensions):
                if not isinstance(dimension, Mapping):
                    codes.add("SCORECARD_REJECTED")
                    errors.append(f"sealed packet scorecard.dimensions[{index}] must be an object")
                    continue
                name = dimension.get("dimension")
                score = dimension.get("score")
                if not isinstance(name, str) or name not in PACKET_SCORECARD_DIMENSIONS or name in observed_scores:
                    codes.add("SCORECARD_REJECTED")
                    errors.append(f"sealed packet scorecard dimension {name!r} is invalid or duplicated")
                elif not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 100:
                    codes.add("SCORECARD_REJECTED")
                    errors.append(f"sealed packet scorecard dimension {name!r} has an invalid score")
                else:
                    observed_scores[name] = float(score)
            if set(observed_scores) != set(PACKET_SCORECARD_DIMENSIONS):
                codes.add("SCORECARD_REJECTED")
                errors.append("sealed packet scorecard does not cover all required dimensions")
            elif isinstance(overall, (int, float)) and round(sum(observed_scores.values()) / len(observed_scores), 2) != round(float(overall), 2):
                codes.add("SCORECARD_REJECTED")
                errors.append("sealed packet scorecard.overall is not derived from its dimensions")
            if isinstance(overall, (int, float)) and overall < 96:
                codes.add("SCORECARD_REJECTED")
                errors.append("sealed packet scorecard overall is below the 96/100 target")

    return codes, errors


def _packet_rejections(
    packet: Mapping[str, Any] | None,
    results: Sequence[Mapping[str, Any]],
    checkout: Mapping[str, Any] | None = None,
    trusted_public_keys: Mapping[str, object] | None = None,
    evidence_root: Path | None = None,
) -> tuple[list[str], list[str]]:
    """Validate the independently sealed packet that authorizes promotion.

    A local verifier can derive a candidate classification without a packet,
    but it cannot promote one.  The packet must be a content-addressed seal
    produced outside this engine, contain the exact lane observations, and
    carry an authorized independent decision.
    """

    codes: set[str] = set()
    errors: list[str] = []
    if packet is None:
        return ["PACKET_REQUIRED_REJECTED", "PACKET_NOT_SEALED_REJECTED", "FINAL_DECISION_REJECTED"], [
            "packet is required for promotion"
        ]

    if packet.get("schema_version") != PROMOTION_PACKET_SCHEMA:
        codes.add("PACKET_SCHEMA_REJECTED")
        errors.append("sealed packet payload schema is not the current verifier schema")

    valid, seal_errors = packet_seal.verify_seal(
        packet,
        trusted_public_keys=trusted_public_keys,
        expected_payload_schema=PROMOTION_PACKET_SCHEMA,
    )
    if not valid:
        codes.add("PACKET_NOT_SEALED_REJECTED")
        errors.extend(seal_errors)

    if packet.get("sealed") is not True:
        codes.add("PACKET_NOT_SEALED_REJECTED")
        errors.append("packet.sealed must be true")

    content_codes, content_errors = _validate_packet_content(
        packet,
        checkout=checkout,
        evidence_root=evidence_root,
    )
    codes.update(content_codes)
    errors.extend(content_errors)

    packet_results = packet.get("results")
    try:
        same_results = _canonical(packet_results) == _canonical(list(results))
    except (TypeError, ValueError):
        same_results = False
    if not same_results:
        codes.add("PACKET_BINDING_REJECTED")
        errors.append("sealed packet does not contain the exact verifier lane observations")

    candidate = packet.get("candidate")
    if not isinstance(candidate, Mapping):
        codes.add("PACKET_BINDING_REJECTED")
        errors.append("sealed packet candidate binding is absent")
    else:
        for field, length in (("commit_sha", 40), ("tree_sha", 40), ("checkout_fingerprint", 64)):
            value = candidate.get(field)
            pattern = _SHA1_RE if length == 40 else _SHA256_RE
            if not isinstance(value, str) or pattern.fullmatch(value.lower()) is None:
                codes.add("PACKET_BINDING_REJECTED")
                errors.append(f"sealed packet candidate.{field} is invalid")
        artifact_set_sha256 = candidate.get("artifact_set_sha256")
        if not isinstance(artifact_set_sha256, str) or _SHA256_RE.fullmatch(artifact_set_sha256.lower()) is None:
            codes.add("PACKET_BINDING_REJECTED")
            errors.append("sealed packet candidate.artifact_set_sha256 is invalid")
        if candidate.get("clean_worktree") is not True:
            codes.add("PACKET_BINDING_REJECTED")
            errors.append("sealed packet candidate is not clean")
        if checkout is None:
            codes.add("PACKET_BINDING_REJECTED")
            errors.append("current checkout is required to promote a sealed packet")
        else:
            for field, checkout_field in (
                ("commit_sha", "head"),
                ("tree_sha", "tree"),
                ("checkout_fingerprint", "fingerprint"),
                ("artifact_set_sha256", "artifact_set_sha256"),
            ):
                if candidate.get(field) != checkout.get(checkout_field):
                    codes.add("PACKET_BINDING_REJECTED")
                    errors.append(f"sealed packet candidate.{field} does not match this checkout")
            if checkout.get("status") != "CLEAN":
                codes.add("PACKET_BINDING_REJECTED")
                errors.append("current checkout is not clean")

    if packet.get("final_decision") not in {"GO", "APPROVE"}:
        codes.add("FINAL_DECISION_REJECTED")
        errors.append("final decision is not an authorized GO/APPROVE")

    authority = packet.get("decision_authority")
    seal = packet.get("seal")
    signer_id = seal.get("signer_id") if isinstance(seal, Mapping) else None
    if (
        not isinstance(authority, Mapping)
        or authority.get("independent") is not True
        or authority.get("authorized") is not True
        or not isinstance(authority.get("reviewer_id"), str)
        or not authority["reviewer_id"].strip()
        or authority.get("reviewer_id") != signer_id
        or (isinstance(signer_id, str) and signer_id.lower().startswith(("automated-", "codex-")))
    ):
        codes.add("SELF_PROMOTED_GATE_REJECTED")
        errors.append("final decision must be signed by an authorized independent reviewer")

    return sorted(codes), errors


def evaluate(
    results: Sequence[Mapping[str, Any]],
    *,
    packet: Mapping[str, Any] | None = None,
    checkout: Mapping[str, Any] | None = None,
    trusted_public_keys: Mapping[str, object] | None = None,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    """Return a derived classification, rejection set and process exit code."""

    by_id, duplicate_ids = _index(results)
    required = TRIPLE_AAA_LANES
    blockers, rejection_codes = _blocking_observations(required, by_id, duplicate_ids)

    if not _all_pass(FOUNDATION_LANES, by_id):
        if _has_hard_foundation_failure(by_id):
            classification = "DEVELOPMENT"
        elif _has_blocked_foundation_lane(by_id):
            classification = "STATE_OF_ART_CANDIDATE"
        else:
            classification = "ADVANCED_ENGINEERING"
    elif not _all_pass(STATE_OF_ART_LANES, by_id):
        classification = "STATE_OF_ART_CANDIDATE"
    elif not _all_pass(AAA_LANES, by_id):
        classification = "STATE_OF_ART"
    elif not _all_pass(TRIPLE_AAA_LANES, by_id):
        classification = "AAA"
    else:
        classification = "TRIPLE_AAA"

    packet_rejection_codes, packet_errors = _packet_rejections(
        packet,
        results,
        checkout,
        trusted_public_keys,
        evidence_root,
    )
    rejection_codes.extend(packet_rejection_codes)
    rejection_codes = sorted(set(rejection_codes))

    if classification == "TRIPLE_AAA" and rejection_codes:
        classification = "AAA"

    hard_failure = any(item["status"] in HARD_FAILURES for item in blockers)
    external_block = any(
        item["external"] and item["status"] == BLOCKED_EXTERNAL
        for item in blockers
    )
    if hard_failure:
        exit_code = EXIT_FAILED
    elif external_block:
        non_external_rejections = set(rejection_codes) - _EXTERNAL_ONLY_REJECTIONS
        # With no packet at all, the missing seal/final authority are part of
        # the same external dependency boundary as the unavailable runtime.
        # A supplied but malformed/untrusted packet remains a real failure and
        # must not be relabeled as an external block.
        if packet is None:
            non_external_rejections -= _MISSING_EXTERNAL_AUTHORITY_REJECTIONS
        exit_code = (
            EXIT_BLOCKED_EXTERNAL
            if not non_external_rejections
            else EXIT_FAILED
        )
    elif blockers or rejection_codes:
        exit_code = EXIT_FAILED
    else:
        exit_code = EXIT_PASS

    stage_lanes = {
        "FOUNDATION": FOUNDATION_LANES,
        "STATE_OF_ART": STATE_OF_ART_LANES,
        "AAA": AAA_LANES,
        "TRIPLE_AAA": TRIPLE_AAA_LANES,
    }
    stage_results = {
        name: {
            "required_lanes": list(lanes),
            "passed": _all_pass(lanes, by_id),
        }
        for name, lanes in stage_lanes.items()
    }
    return {
        "classification": classification,
        "promotion_allowed": classification == "TRIPLE_AAA" and exit_code == EXIT_PASS,
        "exit_code": exit_code,
        "rejection_codes": sorted(set(rejection_codes)),
        "packet_errors": packet_errors,
        "required_lanes": list(required),
        "blocking_lanes": blockers,
        "stage_results": stage_results,
    }


def exit_code(result: Mapping[str, Any]) -> int:
    """Read the already-derived process contract without recomputing it."""

    value = result.get("exit_code")
    return value if type(value) is int and value in {EXIT_PASS, EXIT_FAILED, EXIT_BLOCKED_EXTERNAL} else EXIT_FAILED
