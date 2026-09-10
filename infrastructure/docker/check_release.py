#!/usr/bin/env python3
"""Validate the REC-33 release packet without Docker or network access."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

try:  # Package import for repository execution; root-relative fallback for direct execution.
    from scripts.state_of_art.json_boundary import load_json
except ImportError:  # pragma: no cover - exercised by direct script execution.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "state_of_art"))
    from json_boundary import load_json


DOCKER_ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST = DOCKER_ROOT / "release-manifest.json"
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
IMMUTABLE_REF = re.compile(r"^.+@sha256:[0-9a-f]{64}$")
SERVICES = ("api", "worker", "web")
DOCKERFILES = {
    "api": "api.Dockerfile",
    "worker": "worker.Dockerfile",
    "web": "web.Dockerfile",
}
# A prepared packet may only describe work that has not executed.  ``PASS``
# belongs exclusively to candidate evidence and must never make an unbuilt
# image or unrun scan look ready for promotion.
ALLOWED_NOT_RUN = {"NOT_RUN", "PREPARED"}
ALLOWED_SOURCE_NOT_CAPTURED = {"NOT_CAPTURED", *ALLOWED_NOT_RUN}


def _load_json(path: Path) -> dict[str, Any]:
    value = load_json(path)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _dict(value: object, label: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return {}
    return value


def _list(value: object, label: str, errors: list[str]) -> list[Any]:
    if not isinstance(value, list):
        errors.append(f"{label} must be an array")
        return []
    return value


def _require(value: object, label: str, errors: list[str]) -> None:
    if value is None or value == "":
        errors.append(f"{label} is required")


def _validate_digest(value: object, label: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        errors.append(f"{label} must be sha256:<64 lowercase hex characters>")


def _validate_dockerfile(service: str, path: Path, errors: list[str]) -> None:
    if not path.is_file():
        errors.append(f"{service}: Dockerfile is missing: {path}")
        return
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    global_args: set[str] = set()
    from_count = 0
    has_user = False
    has_healthcheck = False
    has_start = False
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.match(r"^ARG\s+([A-Z][A-Z0-9_]*)\s*$", stripped):
            global_args.add(stripped.split()[1])
        if re.match(r"^FROM\s+", stripped, re.IGNORECASE):
            from_count += 1
            match = re.match(r"^FROM\s+\$\{([A-Z][A-Z0-9_]*)\}(?:\s+AS\s+\S+)?$", stripped, re.IGNORECASE)
            if not match:
                errors.append(f"{service}:{line_number}: FROM must use an explicit image build argument")
            elif match.group(1) not in global_args:
                errors.append(f"{service}:{line_number}: FROM argument {match.group(1)} was not declared")
        if re.match(r"^USER\s+", stripped, re.IGNORECASE):
            has_user = True
            user = stripped.split(None, 1)[1]
            if user not in {"10001:10001", "10001", "node"}:
                errors.append(f"{service}:{line_number}: runtime user must be non-root")
        if stripped.upper().startswith("HEALTHCHECK "):
            has_healthcheck = True
        if stripped.upper().startswith("ENTRYPOINT ") or stripped.upper().startswith("CMD "):
            has_start = True
        if re.match(r"^ADD\s+", stripped, re.IGNORECASE):
            errors.append(f"{service}:{line_number}: ADD is forbidden; use reviewed COPY paths")
        if re.search(r"(?:\.env|\.pem|\.key|credentials|secrets)", stripped, re.IGNORECASE):
            errors.append(f"{service}:{line_number}: secret-bearing path is forbidden in Dockerfile")
        if re.search(r"(?:curl|wget)\s+[^\n|]*\|\s*(?:sh|bash)", stripped, re.IGNORECASE):
            errors.append(f"{service}:{line_number}: remote shell bootstrap is forbidden")
        if re.search(r"^ENV\s+.*(?:PASSWORD|SECRET|API_KEY|TOKEN|DSN)", stripped, re.IGNORECASE):
            errors.append(f"{service}:{line_number}: secret-shaped ENV is forbidden")
    if from_count == 0:
        errors.append(f"{service}: Dockerfile has no FROM")
    if not has_user:
        errors.append(f"{service}: Dockerfile must declare a non-root USER")
    if not has_healthcheck:
        errors.append(f"{service}: Dockerfile must declare a healthcheck")
    if not has_start:
        errors.append(f"{service}: Dockerfile must declare ENTRYPOINT or CMD")
    if service in {"api", "worker"} and "pip install" not in text:
        errors.append(f"{service}: Python dependencies are not installed")
    if service == "web":
        if "npm ci" not in text:
            errors.append("web: dependencies must be installed with npm ci")
        if "npm run build" not in text:
            errors.append("web: Dockerfile must run npm run build")


def _validate_policy(policy: dict[str, Any], errors: list[str]) -> None:
    if policy.get("schema") != "rick.release.policy/v1":
        errors.append("policy: unsupported schema")
    immutable = _dict(policy.get("immutable_image"), "policy.immutable_image", errors)
    if immutable.get("require_digest") is not True or immutable.get("allow_mutable_tags") is not False:
        errors.append("policy: mutable image references must be rejected")
    signature = _dict(policy.get("signature"), "policy.signature", errors)
    if signature.get("required") is not True or signature.get("tool") != "cosign":
        errors.append("policy: cosign signature verification is required")
    scan = _dict(policy.get("scan"), "policy.scan", errors)
    if scan.get("required") is not True or scan.get("tool") != "trivy":
        errors.append("policy: trivy scan is required")
    if scan.get("sbom_required") is not True:
        errors.append("policy: SBOM is required")
    if set(scan.get("block_severities", [])) != {"CRITICAL", "HIGH"}:
        errors.append("policy: CRITICAL and HIGH must block promotion")
    canary = _dict(policy.get("canary"), "policy.canary", errors)
    if not isinstance(canary.get("min_duration_seconds"), int) or canary["min_duration_seconds"] < 900:
        errors.append("policy: canary window must be at least 900 seconds")
    if not isinstance(canary.get("min_requests"), int) or canary["min_requests"] < 100:
        errors.append("policy: canary must observe at least 100 requests")
    rollback = _dict(policy.get("rollback"), "policy.rollback", errors)
    if rollback.get("previous_release_digest_required") is not True:
        errors.append("policy: rollback must retain a previous immutable digest")
    if rollback.get("data_deletion_forbidden") is not True:
        errors.append("policy: rollback must forbid data deletion")


def validate_release(manifest_path: Path, *, mode: str = "prepared") -> list[str]:
    """Return static validation errors for a prepared or candidate packet."""

    errors: list[str] = []
    try:
        manifest = _load_json(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"manifest: {exc}"]
    if mode not in {"prepared", "candidate"}:
        return [f"unsupported mode: {mode}"]
    if manifest.get("schema") != "rick.release.manifest/v1":
        errors.append("manifest: unsupported schema")
    if mode == "prepared" and manifest.get("status") != "PREPARED_NOT_RUN":
        errors.append("manifest: prepared mode requires PREPARED_NOT_RUN")
    if mode == "candidate" and manifest.get("status") not in {"CANDIDATE", "READY_FOR_REVIEW"}:
        errors.append("manifest: candidate mode requires CANDIDATE or READY_FOR_REVIEW")

    build = _dict(manifest.get("build"), "build", errors)
    if build.get("context") != ".":
        errors.append("build.context must be the repository root")
    if build.get("network_access_during_validation") is not False:
        errors.append("build.network_access_during_validation must be false for this checker")
    if mode == "candidate" and build.get("status") != "PASS":
        errors.append("build.status must be PASS for a candidate")
    elif mode == "prepared" and build.get("status") not in ALLOWED_NOT_RUN:
        errors.append("build.status is invalid")
    source = _dict(manifest.get("source_revision"), "source_revision", errors)
    if mode == "candidate":
        if not isinstance(source.get("value"), str) or not re.fullmatch(r"[0-9a-f]{7,64}", source["value"]):
            errors.append("source_revision.value must be a captured hexadecimal revision")
        if source.get("status") != "CAPTURED":
            errors.append("source_revision.status must be CAPTURED")
    else:
        if source.get("status") not in ALLOWED_SOURCE_NOT_CAPTURED:
            errors.append("source_revision.status is invalid")
        if source.get("value") is not None:
            errors.append("source_revision.value must be null before capture")

    policy_file = manifest.get("policy_file")
    if not isinstance(policy_file, str) or Path(policy_file).name != policy_file:
        errors.append("policy_file must name a file in infrastructure/docker")
    else:
        policy_path = DOCKER_ROOT / policy_file
        try:
            _validate_policy(_load_json(policy_path), errors)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"policy: {exc}")

    base_images = _list(manifest.get("base_images"), "base_images", errors)
    expected_base_args = {
        ("api", "PYTHON_IMAGE"),
        ("worker", "PYTHON_IMAGE"),
        ("web", "NODE_BUILD_IMAGE"),
        ("web", "NODE_RUNTIME_IMAGE"),
    }
    actual_base_args: set[tuple[str, str]] = set()
    for index, item in enumerate(base_images):
        base = _dict(item, f"base_images[{index}]", errors)
        service, argument = base.get("service"), base.get("argument")
        actual_base_args.add((service, argument))
        if base.get("required") != "immutable-ref-with-sha256-digest":
            errors.append(f"base_images[{index}].required must require an immutable digest")
        ref = base.get("ref")
        if mode == "candidate":
            if not isinstance(ref, str) or not IMMUTABLE_REF.fullmatch(ref):
                errors.append(f"base_images[{index}].ref must be immutable")
            if base.get("status") != "CAPTURED":
                errors.append(f"base_images[{index}].status must be CAPTURED")
        else:
            if base.get("status") not in ALLOWED_NOT_RUN:
                errors.append(f"base_images[{index}].status is invalid")
            if ref is not None and (not isinstance(ref, str) or not IMMUTABLE_REF.fullmatch(ref)):
                errors.append(f"base_images[{index}].ref must be null or immutable")
    if actual_base_args != expected_base_args:
        errors.append("base_images must cover the four Dockerfile image arguments exactly")

    images = _list(manifest.get("images"), "images", errors)
    by_service: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(images):
        image = _dict(item, f"images[{index}]", errors)
        service = image.get("service")
        if service in by_service:
            errors.append(f"images: duplicate service {service}")
        if service not in SERVICES:
            errors.append(f"images[{index}].service must be api, worker, or web")
            continue
        by_service[service] = image
        dockerfile = image.get("dockerfile")
        expected = f"infrastructure/docker/{DOCKERFILES[service]}"
        if dockerfile != expected:
            errors.append(f"images[{index}].dockerfile must be {expected}")
        _validate_dockerfile(service, DOCKER_ROOT / DOCKERFILES[service], errors)
        if image.get("context") != ".":
            errors.append(f"images[{index}].context must be repository root")
        if mode == "candidate":
            if image.get("build_status") != "PASS":
                errors.append(f"images[{index}].build_status must be PASS for a candidate")
        elif image.get("build_status") not in ALLOWED_NOT_RUN:
            errors.append(f"images[{index}].build_status is invalid")
        digest = image.get("digest")
        digest_status = image.get("digest_status")
        if mode == "candidate":
            _validate_digest(digest, f"images[{index}].digest", errors)
            if digest_status != "PASS":
                errors.append(f"images[{index}].digest_status must be PASS")
            image_ref = image.get("image_ref")
            if not isinstance(image_ref, str) or not IMMUTABLE_REF.fullmatch(image_ref):
                errors.append(f"images[{index}].image_ref must be immutable")
            elif not image_ref.endswith(digest):
                errors.append(f"images[{index}].image_ref digest must match digest")
        elif digest is not None:
            _validate_digest(digest, f"images[{index}].digest", errors)
        if mode == "prepared" and digest_status not in ALLOWED_NOT_RUN:
            errors.append(f"images[{index}].digest_status is invalid")
        scan = _dict(image.get("scan"), f"images[{index}].scan", errors)
        if scan.get("tool") != "trivy":
            errors.append(f"images[{index}].scan.tool must be trivy")
        signature = _dict(image.get("signature"), f"images[{index}].signature", errors)
        if signature.get("tool") != "cosign":
            errors.append(f"images[{index}].signature.tool must be cosign")
        if mode == "candidate":
            if scan.get("status") != "PASS":
                errors.append(f"images[{index}].scan.status must be PASS")
            if not isinstance(scan.get("critical"), int) or scan["critical"] != 0:
                errors.append(f"images[{index}].scan.critical must be 0")
            if not isinstance(scan.get("high"), int) or scan["high"] != 0:
                errors.append(f"images[{index}].scan.high must be 0")
            for key in ("report", "sbom"):
                _require(scan.get(key), f"images[{index}].scan.{key}", errors)
            if signature.get("status") != "PASS":
                errors.append(f"images[{index}].signature.status must be PASS")
            for key in ("bundle", "identity", "issuer"):
                _require(signature.get(key), f"images[{index}].signature.{key}", errors)
        else:
            if scan.get("status") not in ALLOWED_NOT_RUN:
                errors.append(f"images[{index}].scan.status is invalid")
            if signature.get("status") not in ALLOWED_NOT_RUN:
                errors.append(f"images[{index}].signature.status is invalid")
    if set(by_service) != set(SERVICES):
        errors.append("images must contain exactly api, worker, and web")

    secrets = _dict(manifest.get("secrets"), "secrets", errors)
    if secrets.get("baked_into_image") is not False:
        errors.append("secrets.baked_into_image must be false")
    if secrets.get("build_secret_mounts_required") is not False:
        errors.append("secrets.build_secret_mounts_required must be false")
    if secrets.get("runtime_injected") is not True:
        errors.append("secrets.runtime_injected must be true")

    rollout = _dict(manifest.get("rollout"), "rollout", errors)
    canary = _dict(rollout.get("canary"), "rollout.canary", errors)
    rollback = _dict(rollout.get("rollback"), "rollout.rollback", errors)
    if mode == "candidate":
        if canary.get("status") != "PASS" or not canary.get("evidence"):
            errors.append("rollout.canary requires PASS and evidence")
        if rollback.get("status") != "PASS" or not rollback.get("evidence"):
            errors.append("rollout.rollback requires PASS and evidence")
        if not isinstance(rollback.get("previous_release_digest"), str):
            errors.append("rollout.rollback.previous_release_digest is required")
        elif not SHA256.fullmatch(rollback["previous_release_digest"]):
            errors.append("rollout.rollback.previous_release_digest must be a digest")
        if rollback.get("migration_compatibility") != "PASS":
            errors.append("rollout.rollback.migration_compatibility must be PASS")
    else:
        if canary.get("status") not in ALLOWED_NOT_RUN:
            errors.append("rollout.canary.status is invalid")
        if rollback.get("status") not in ALLOWED_NOT_RUN:
            errors.append("rollout.rollback.status is invalid")
        if rollback.get("migration_compatibility") not in ALLOWED_NOT_RUN:
            errors.append("rollout.rollback.migration_compatibility is invalid")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--mode", choices=("prepared", "candidate"), default="prepared")
    args = parser.parse_args(argv)
    errors = validate_release(args.manifest, mode=args.mode)
    if errors:
        print(f"FAIL: {len(errors)} static release check(s)", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 2
    print(f"PASS: REC-33 {args.mode} packet is statically consistent; no daemon/network checks were run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
