#!/usr/bin/env python3
"""Validate the current prompt's canonical Triple AAA capability matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

try:
    from scripts.state_of_art.json_boundary import load_json
except ImportError:  # pragma: no cover
    from json_boundary import load_json


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / "docs/reports/triple-aaa-runtime-capability-matrix.json"
EXPECTED_PROMPT = "docs/prompts/triple-aaa-runtime-closure-2026-09-10.txt"
EXPECTED_PROMPT_SHA256 = "064be5e04ed483d5d95ef803a66faf6675f7c1f00633cdea83d5abfdd5370d5f"
ALLOWED_STATES = frozenset({
    "DONE_LOCAL_SCOPE", "LOCAL_VERIFIED", "VERIFIED_RUNTIME", "PARTIAL",
    "NOT_RUN", "BLOCKED_EXTERNAL", "FAILED", "PROMOTABLE",
})
REQUIRED_COLUMNS = (
    "CAPABILITY", "STATE", "SOURCE_EVIDENCE", "TEST_EVIDENCE",
    "RUNTIME_EVIDENCE", "INDEPENDENT_REVIEW", "BLOCKER", "OWNER",
    "PRIORITY", "PROMOTION_CONDITION",
)

# The prompt freezes an eleven-capability closure matrix.  A non-empty row
# list alone is insufficient: a truncated or substituted projection must not
# be accepted as the current matrix for a release packet.
EXPECTED_CAPABILITIES = (
    "Current prompt preservation",
    "Control plane and canonical CI",
    "Disposable production-like lab",
    "PostgreSQL durable queue and worker fencing",
    "Redis coordination and multi-replica rate limit",
    "Object storage and Qdrant lifecycle",
    "Golden ingestion, lineage and evidence authority",
    "Provider, Decision and citation verification",
    "Observability, SLO, DR, chaos, soak and performance",
    "Frontend, accessibility and supply chain",
    "Independent reviews and sealed promotion",
)


PACKET_SCHEMA = "state-of-art-triple-aaa-verify.v2"


def _load(path: Path) -> object:
    return load_json(path)


def _sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except (OSError, ValueError, RuntimeError):
        return None


def validate(path: Path = DEFAULT_PATH, *, packet: Path | None = None) -> dict[str, Any]:
    errors: list[str] = []
    try:
        document = load_json(path)
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        return {"status": "FAIL", "errors": [f"matrix unreadable: {type(exc).__name__}"]}
    if not isinstance(document, dict):
        return {"status": "FAIL", "errors": ["matrix root must be an object"]}
    if document.get("schema") != "rick-triple-aaa-runtime-capability-matrix.v1":
        errors.append("schema mismatch")
    if document.get("prompt") != EXPECTED_PROMPT:
        errors.append("prompt binding mismatch")
    if document.get("prompt_sha256") != EXPECTED_PROMPT_SHA256:
        errors.append("prompt hash mismatch")
    prompt_path = ROOT / EXPECTED_PROMPT
    try:
        observed_prompt_hash = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
    except OSError:
        observed_prompt_hash = None
    if observed_prompt_hash != EXPECTED_PROMPT_SHA256:
        errors.append("archived prompt bytes do not match the expected hash")
    binding = document.get("candidate_binding")
    if not isinstance(binding, dict) or binding.get("packet") != ".runtime/phase-3/triple-aaa-verify.json":
        errors.append("candidate binding must point to the same-run verifier packet")
    if packet is not None:
        try:
            packet_document = _load(packet)
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            errors.append(f"bound verifier packet is unreadable: {type(exc).__name__}")
            packet_document = None
        if not isinstance(packet_document, dict) or packet_document.get("schema_version") != PACKET_SCHEMA:
            errors.append("bound verifier packet has an unsupported schema")
        elif not isinstance(binding, dict):
            errors.append("candidate binding is absent")
        else:
            candidate = packet_document.get("candidate")
            packet_fields = {
                "commit_sha": "commit_sha",
                "tree_sha": "tree_sha",
                "checkout_fingerprint": "checkout_fingerprint",
                "artifact_set_sha256": "artifact_set_sha256",
            }
            if not isinstance(candidate, dict):
                errors.append("bound verifier packet candidate is absent")
            else:
                for matrix_field, packet_field in packet_fields.items():
                    if binding.get(matrix_field) != candidate.get(packet_field):
                        errors.append(f"candidate binding {matrix_field} does not match the verifier packet")
                if binding.get("classification") != packet_document.get("classification"):
                    errors.append("candidate binding classification does not match the verifier packet")
                if binding.get("exit_code") != packet_document.get("exit_code"):
                    errors.append("candidate binding exit_code does not match the verifier packet")
            current_matrix = packet_document.get("current_capability_matrix")
            if current_matrix is not None:
                if not isinstance(current_matrix, dict):
                    errors.append("bound verifier packet current_capability_matrix must be an object")
                else:
                    try:
                        expected_path = path.resolve().relative_to(ROOT.resolve()).as_posix()
                    except (OSError, ValueError, RuntimeError):
                        expected_path = None
                        errors.append("current matrix path must remain inside the checkout")
                    if expected_path is not None and current_matrix.get("path") != expected_path:
                        errors.append("bound verifier packet current_capability_matrix.path does not point to this matrix")
                    declared_hash = current_matrix.get("sha256")
                    normalized_hash = declared_hash.removeprefix("sha256:").lower() if isinstance(declared_hash, str) else ""
                    if not normalized_hash or not re.fullmatch(r"[0-9a-f]{64}", normalized_hash):
                        errors.append("bound verifier packet current_capability_matrix.sha256 is invalid")
                    else:
                        actual_hash = _sha256_file(path)
                        if actual_hash != normalized_hash:
                            errors.append("bound verifier packet current_capability_matrix.sha256 does not match this matrix")
    rows = document.get("rows")
    if not isinstance(rows, list) or not rows:
        errors.append("rows must be a non-empty array")
        rows = []
    names: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"row {index} must be an object")
            continue
        missing = [column for column in REQUIRED_COLUMNS if column not in row]
        if missing:
            errors.append(f"row {index} missing columns: {','.join(missing)}")
        capability = row.get("CAPABILITY")
        if not isinstance(capability, str) or not capability.strip() or capability in names:
            errors.append(f"row {index} has an invalid or duplicate CAPABILITY")
        else:
            names.add(capability)
        state = row.get("STATE")
        if state not in ALLOWED_STATES:
            errors.append(f"row {index} has forbidden STATE")
        if row.get("PRIORITY") not in {"P0", "P1", "P2"}:
            errors.append(f"row {index} has invalid PRIORITY")
        for column in ("SOURCE_EVIDENCE", "TEST_EVIDENCE", "RUNTIME_EVIDENCE"):
            if not isinstance(row.get(column), list):
                errors.append(f"row {index} {column} must be an array")
        for column in ("BLOCKER", "OWNER", "PROMOTION_CONDITION"):
            if not isinstance(row.get(column), str) or not row[column].strip():
                errors.append(f"row {index} {column} must be non-empty text")
        if state in {"VERIFIED_RUNTIME", "PROMOTABLE"}:
            if not isinstance(row.get("RUNTIME_EVIDENCE"), list) or not row["RUNTIME_EVIDENCE"]:
                errors.append(f"row {index} {state} requires non-empty RUNTIME_EVIDENCE")
            if not isinstance(row.get("INDEPENDENT_REVIEW"), list) or not row["INDEPENDENT_REVIEW"]:
                errors.append(f"row {index} {state} requires non-empty INDEPENDENT_REVIEW")
    expected_names = set(EXPECTED_CAPABILITIES)
    if len(rows) != len(EXPECTED_CAPABILITIES):
        errors.append(
            f"rows must contain exactly {len(EXPECTED_CAPABILITIES)} canonical capabilities"
        )
    missing_capabilities = sorted(expected_names - names)
    extra_capabilities = sorted(names - expected_names)
    if missing_capabilities:
        errors.append("matrix is missing canonical capabilities: " + ", ".join(missing_capabilities))
    if extra_capabilities:
        errors.append("matrix contains unsupported capabilities: " + ", ".join(extra_capabilities))
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "rows": len(rows)}


def bind_to_packet(
    source: Path = DEFAULT_PATH,
    packet: Path = ROOT / ".runtime/phase-3/triple-aaa-verify.json",
    output: Path = ROOT / ".runtime/phase-3/current-triple-aaa-runtime-capability-matrix.json",
) -> dict[str, Any]:
    """Export the current prompt matrix with the exact same-run packet identity."""

    source_result = validate(source)
    if source_result["status"] != "PASS":
        raise ValueError("current capability matrix is invalid: " + "; ".join(source_result["errors"]))
    packet_document = _load(packet)
    if not isinstance(packet_document, dict) or packet_document.get("schema_version") != PACKET_SCHEMA:
        raise ValueError("verifier packet has an unsupported schema")
    candidate = packet_document.get("candidate")
    if not isinstance(candidate, dict):
        raise ValueError("verifier packet has no candidate binding")
    required = ("commit_sha", "tree_sha", "checkout_fingerprint", "artifact_set_sha256")
    if any(not isinstance(candidate.get(field), str) or not candidate[field].strip() for field in required):
        raise ValueError("verifier packet candidate binding is incomplete")
    document = _load(source)
    if not isinstance(document, dict):
        raise ValueError("current capability matrix must be an object")
    bound = dict(document)
    binding = dict(bound.get("candidate_binding") or {})
    binding.update(
        {
            "commit_sha": candidate["commit_sha"],
            "tree_sha": candidate["tree_sha"],
            "checkout_fingerprint": candidate["checkout_fingerprint"],
            "artifact_set_sha256": candidate["artifact_set_sha256"],
            "classification": packet_document.get("classification"),
            "exit_code": packet_document.get("exit_code"),
        }
    )
    bound["candidate_binding"] = binding
    output = output.resolve()
    output.relative_to(ROOT.resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bound, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    result = validate(output, packet=packet)
    if result["status"] != "PASS":
        raise ValueError("bound capability matrix is invalid: " + "; ".join(result["errors"]))
    return {"output": str(output.relative_to(ROOT.resolve())), **result}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default=str(DEFAULT_PATH))
    parser.add_argument("--packet", help="same-run verifier packet used for binding validation")
    parser.add_argument("--bind-packet", action="store_true", help="export the current matrix bound to the verifier packet")
    parser.add_argument("--output", help="bound matrix output path")
    args = parser.parse_args(argv)
    if args.bind_packet:
        try:
            result = bind_to_packet(
                Path(args.path),
                Path(args.packet) if args.packet else ROOT / ".runtime/phase-3/triple-aaa-verify.json",
                Path(args.output) if args.output else ROOT / ".runtime/phase-3/current-triple-aaa-runtime-capability-matrix.json",
            )
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            print({"status": "FAIL", "errors": [str(exc)]})
            return 1
    else:
        result = validate(Path(args.path), packet=Path(args.packet) if args.packet else None)
    print(result)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
