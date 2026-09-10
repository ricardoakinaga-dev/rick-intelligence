#!/usr/bin/env python3
"""Validate the checked-in Triple AAA quality-bar contract without services."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
QUALITY_BAR = ROOT / "docs/reports/current-triple-aaa-quality-bar-v1.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_BASELINE_STATUSES = {
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
REQUIRED_CRITERION_FIELDS = {
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
    "validity_notes",
}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(path: Path = QUALITY_BAR) -> list[str]:
    errors: list[str] = []
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"quality bar is not readable JSON: {exc}"]
    if not isinstance(payload, dict):
        return ["quality bar root must be an object"]
    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    for field in ("version", "frozen_at", "goal"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            errors.append(f"{field} must be a non-empty string")
    if isinstance(payload.get("frozen_at"), str):
        try:
            datetime.fromisoformat(payload["frozen_at"].replace("Z", "+00:00"))
        except ValueError:
            errors.append("frozen_at must be ISO-8601")

    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("sources must be a non-empty list")
    else:
        for index, source in enumerate(sources):
            if not isinstance(source, dict):
                errors.append(f"sources[{index}] must be an object")
                continue
            if not isinstance(source.get("location"), str) or not source["location"].strip():
                errors.append(f"sources[{index}].location is required")
            digest = source.get("snapshot_sha256")
            if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
                errors.append(f"sources[{index}].snapshot_sha256 must be a SHA-256 digest")
            attachment_digest = source.get("source_attachment_sha256")
            if attachment_digest is not None and (
                not isinstance(attachment_digest, str) or SHA256_RE.fullmatch(attachment_digest) is None
            ):
                errors.append(f"sources[{index}].source_attachment_sha256 must be a SHA-256 digest")
            location = source.get("location")
            if isinstance(location, str) and location.strip():
                target = (ROOT / location).resolve()
                try:
                    target.relative_to(ROOT.resolve())
                except ValueError:
                    errors.append(f"sources[{index}].location must remain inside the repository")
                else:
                    snapshot = source.get("snapshot_sha256")
                    if not isinstance(snapshot, str) or SHA256_RE.fullmatch(snapshot) is None:
                        errors.append(f"sources[{index}].snapshot_sha256 is required for repository sources")
                    elif target.is_file() and _digest(target) != snapshot:
                        errors.append(f"sources[{index}].snapshot_sha256 does not match {location}")
                    elif not target.is_file():
                        errors.append(f"sources[{index}].location is absent: {location}")

    criteria = payload.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        errors.append("criteria must be a non-empty list")
    else:
        identifiers: set[str] = set()
        for index, criterion in enumerate(criteria):
            prefix = f"criteria[{index}]"
            if not isinstance(criterion, dict):
                errors.append(f"{prefix} must be an object")
                continue
            missing = sorted(REQUIRED_CRITERION_FIELDS - set(criterion))
            errors.extend(f"{prefix}.{field} is required" for field in missing)
            identifier = criterion.get("id")
            if not isinstance(identifier, str) or not identifier.strip():
                errors.append(f"{prefix}.id must be a non-empty string")
            elif identifier in identifiers:
                errors.append(f"{prefix}.id is duplicated: {identifier}")
            else:
                identifiers.add(identifier)
            if criterion.get("required") is not True:
                errors.append(f"{prefix}.required must be true")
            if criterion.get("priority") not in {"critical", "high", "medium", "low"}:
                errors.append(f"{prefix}.priority is invalid")
            baseline = criterion.get("baseline")
            if not isinstance(baseline, dict):
                errors.append(f"{prefix}.baseline must be an object")
            else:
                status = baseline.get("status")
                if status not in ALLOWED_BASELINE_STATUSES:
                    errors.append(f"{prefix}.baseline.status is invalid")
                if not isinstance(baseline.get("actual"), str) or not baseline["actual"].strip():
                    errors.append(f"{prefix}.baseline.actual must be a non-empty string")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps({"status": "PASS", "path": str(QUALITY_BAR.relative_to(ROOT)), "sha256": _digest(QUALITY_BAR)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
