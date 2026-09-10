#!/usr/bin/env python3
"""Derive the RICK promotion level from typed lane observations.

The engine is deliberately small and dependency-free.  It accepts observations
from a verifier, never a caller-supplied verdict, and applies a fixed ladder of
mandatory lane sets.  Missing, stale, blocked and self-promoted evidence stays
blocking; a score or a document cannot override it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
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
        for field in ("return_code", "exit_status"):
            if field in item and item[field] is not None and item[field] != 0:
                return INVALID
        return PASS
    if raw == "PROMOTABLE":
        # PROMOTABLE is a derived matrix/report state, never an observation
        # that can be fed back into the promotion engine as proof.
        return INVALID
    if raw == "VERIFIED_RUNTIME":
        if item.get("production_safe") is True and item.get("exit_status", 0) == 0:
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
        external = item.get("external") is True or lane_id in EXTERNAL_LANES
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


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _packet_rejections(
    packet: Mapping[str, Any] | None,
    results: Sequence[Mapping[str, Any]],
    checkout: Mapping[str, Any] | None = None,
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

    valid, seal_errors = packet_seal.verify_seal(packet)
    if not valid:
        codes.add("PACKET_NOT_SEALED_REJECTED")
        errors.extend(seal_errors)

    if packet.get("sealed") is not True:
        codes.add("PACKET_NOT_SEALED_REJECTED")
        errors.append("packet.sealed must be true")

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
        if candidate.get("clean_worktree") is not True:
            codes.add("PACKET_BINDING_REJECTED")
            errors.append("sealed packet candidate is not clean")
        if checkout is not None:
            for field, checkout_field in (
                ("commit_sha", "head"),
                ("tree_sha", "tree"),
                ("checkout_fingerprint", "fingerprint"),
            ):
                if candidate.get(field) != checkout.get(checkout_field):
                    codes.add("PACKET_BINDING_REJECTED")
                    errors.append(f"sealed packet candidate.{field} does not match this checkout")
            if checkout.get("status") != "CLEAN":
                codes.add("PACKET_BINDING_REJECTED")
                errors.append("current checkout is not clean")

    findings = packet.get("critical_high_findings")
    if type(findings) is not int or findings != 0:
        codes.add("OPEN_CRITICAL_HIGH_REJECTED")
        errors.append("critical/high findings must be exactly zero")

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
) -> dict[str, Any]:
    """Return a derived classification, rejection set and process exit code."""

    by_id, duplicate_ids = _index(results)
    required = TRIPLE_AAA_LANES
    blockers, rejection_codes = _blocking_observations(required, by_id, duplicate_ids)

    if not _all_pass(FOUNDATION_LANES, by_id):
        classification = "DEVELOPMENT" if _has_hard_foundation_failure(by_id) else "ADVANCED_ENGINEERING"
    elif not _all_pass(STATE_OF_ART_LANES, by_id):
        classification = "STATE_OF_ART_CANDIDATE"
    elif not _all_pass(AAA_LANES, by_id):
        classification = "STATE_OF_ART"
    elif not _all_pass(TRIPLE_AAA_LANES, by_id):
        classification = "AAA"
    else:
        classification = "TRIPLE_AAA"

    packet_rejection_codes, packet_errors = _packet_rejections(packet, results, checkout)
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
        exit_code = EXIT_BLOCKED_EXTERNAL
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
