"""Fail-closed shared attestation for the disposable Phase 3 Compose lab.

The service gates remain responsible for their domain assertions.  This module
proves the common target those assertions are allowed to describe: one clean
checkout, one Compose project/configuration, every required service healthy,
and explicit local HTTP readiness probes.  The attestation intentionally
contains no rendered Compose output, credentials, response bodies, or tokens.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit


SCHEMA_VERSION = "state-of-art-runtime-preflight.v1"
DEFAULT_PATH = ".runtime/phase-3/preflight.json"
MAX_AGE_SECONDS = 24 * 60 * 60
MAX_FUTURE_SKEW_SECONDS = 5 * 60
SHA1_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
REQUIRED_ENDPOINTS = ("api-readiness", "web-readiness")
DEFAULT_COMPOSE_FILE = "docker-compose.dev.yml"
COMPOSE_PROJECT_BASES = {
    "docker-compose.dev.yml": "rick-intelligence-dev",
    "docker-compose.staging.yml": "rick-intelligence-staging",
}
ENDPOINT_CONTRACT = {
    "api-readiness": ("/health/ready", 18000),
    "web-readiness": ("/login", 13000),
}
REQUIRED_SERVICES = (
    "postgres",
    "redis",
    "qdrant",
    "object-store",
    "jaeger",
    "otel-collector",
    "metrics",
    "api",
    "worker",
    "worker-b",
    "web",
)


class PreflightError(ValueError):
    """Raised when a preflight cannot be safely loaded or written."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: Any, field: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} is missing")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{field} is not an ISO-8601 timestamp")
        return None
    if parsed.tzinfo is None:
        errors.append(f"{field} must include a timezone")
        return None
    return parsed.astimezone(timezone.utc)


def _safe_relative(root: Path, raw: Any, field: str, errors: list[str]) -> Path | None:
    if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
        errors.append(f"{field} must be a non-empty relative path")
        return None
    candidate = Path(raw)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        errors.append(f"{field} must be a normalized relative path")
        return None
    if candidate.as_posix() != raw.replace("\\", "/"):
        errors.append(f"{field} must use normalized POSIX separators")
        return None
    resolved_root = root.resolve()
    resolved = (root / candidate).resolve(strict=False)
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        errors.append(f"{field} escapes the repository root")
        return None
    return candidate


def _sha256_file(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def sha256_path(root: Path, relative_path: str) -> str | None:
    """Hash a non-symlink file that stays inside ``root``."""

    errors: list[str] = []
    safe = _safe_relative(root, relative_path, "path", errors)
    return None if safe is None else _sha256_file(root / safe)


def canonical_compose_project(root: Path, compose_file: str) -> str:
    """Derive the same path-scoped Compose project name used by the runner."""

    base = COMPOSE_PROJECT_BASES.get(compose_file, "rick-intelligence-local")
    suffix = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:10]
    return f"{base}-{suffix}"


def _valid_checkout(value: Mapping[str, Any] | None) -> bool:
    if not isinstance(value, Mapping):
        return False
    head = value.get("head", value.get("commit_sha"))
    tree = value.get("tree", value.get("tree_sha"))
    fingerprint = value.get("fingerprint", value.get("checkout_fingerprint"))
    return bool(
        value.get("status") == "CLEAN"
        and value.get("clean_worktree", True) is True
        and isinstance(head, str)
        and SHA1_RE.fullmatch(head)
        and isinstance(tree, str)
        and SHA1_RE.fullmatch(tree)
        and isinstance(fingerprint, str)
        and SHA256_RE.fullmatch(fingerprint)
    )


def _compare_checkout(payload: Mapping[str, Any], expected: Mapping[str, Any] | None, errors: list[str]) -> None:
    if not _valid_checkout({
        "status": "CLEAN" if payload.get("clean_worktree") is True else "DIRTY",
        "clean_worktree": payload.get("clean_worktree"),
        "commit_sha": payload.get("commit_sha"),
        "tree_sha": payload.get("tree_sha"),
        "checkout_fingerprint": payload.get("checkout_fingerprint"),
    }):
        errors.append("preflight checkout is not a clean, valid identity")
        return
    if expected is None:
        return
    expected_head = expected.get("head", expected.get("commit_sha"))
    expected_tree = expected.get("tree", expected.get("tree_sha"))
    expected_fingerprint = expected.get("fingerprint", expected.get("checkout_fingerprint"))
    if payload.get("commit_sha") != expected_head:
        errors.append("preflight commit_sha does not match the current checkout")
    if payload.get("tree_sha") != expected_tree:
        errors.append("preflight tree_sha does not match the current checkout")
    if payload.get("checkout_fingerprint") != expected_fingerprint:
        errors.append("preflight checkout_fingerprint does not match the current checkout")


def _validate_endpoint(value: Any, name: str, now: datetime, errors: list[str]) -> None:
    if not isinstance(value, Mapping):
        errors.append(f"endpoint {name} is not an object")
        return
    if value.get("name") != name:
        errors.append(f"endpoint {name} has an invalid name")
    raw_url = value.get("url")
    if not isinstance(raw_url, str) or not raw_url.strip():
        errors.append(f"endpoint {name} has no URL")
    else:
        try:
            parsed = urlsplit(raw_url)
        except ValueError:
            errors.append(f"endpoint {name} URL is malformed")
            parsed = None
        if parsed is None:
            parsed = urlsplit("http://127.0.0.1")
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            errors.append(f"endpoint {name} URL has an invalid scheme or userinfo")
        if parsed.query or parsed.fragment:
            errors.append(f"endpoint {name} URL must not contain query or fragment")
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            errors.append(f"endpoint {name} URL must target the local disposable lab")
        expected_path, expected_port = ENDPOINT_CONTRACT.get(name, (None, None))
        if expected_path is not None and parsed.path != expected_path:
            errors.append(f"endpoint {name} URL has an unexpected readiness path")
        try:
            port = parsed.port
        except ValueError:
            errors.append(f"endpoint {name} URL has an invalid port")
        else:
            if expected_port is not None and port != expected_port:
                errors.append(f"endpoint {name} URL has an unexpected local port")
    if value.get("status") != "PASS" or value.get("reachable") is not True:
        errors.append(f"endpoint {name} was not verified as reachable")
    status_code = value.get("http_status")
    if not isinstance(status_code, int) or status_code != 200:
        errors.append(f"endpoint {name} has no successful HTTP status")
    verified_at = _parse_timestamp(value.get("verified_at"), f"endpoint {name}.verified_at", errors)
    if verified_at is not None and (verified_at - now).total_seconds() > MAX_FUTURE_SKEW_SECONDS:
        errors.append(f"endpoint {name} verification is in the future")
    if verified_at is not None and (now - verified_at).total_seconds() > MAX_AGE_SECONDS:
        errors.append(f"endpoint {name} verification is stale")


def validate_preflight(
    payload: Any,
    *,
    root: Path,
    expected_checkout: Mapping[str, Any] | None = None,
    expected_compose_file: str | None = None,
    expected_compose_project: str | None = None,
    expected_config_sha256: str | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Return all contract violations; an empty list is a valid attestation."""

    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return ["preflight payload is not an object"]
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append("preflight schema_version is unsupported")
    if payload.get("status") != "PASS":
        errors.append("preflight status is not PASS")
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        errors.append("preflight run_id is missing or invalid")
    target_id = payload.get("target_id")
    if not isinstance(target_id, str) or not target_id.strip():
        errors.append("preflight target_id is missing")
    if payload.get("disposable") is not True:
        errors.append("preflight is not explicitly disposable")
    _compare_checkout(payload, expected_checkout, errors)

    compose_file = _safe_relative(root, payload.get("compose_file"), "compose_file", errors)
    if compose_file is not None:
        compose_path = root / compose_file
        if not compose_path.is_file() or compose_path.is_symlink():
            errors.append("preflight compose_file is absent or symlinked")
    if expected_compose_file is not None and payload.get("compose_file") != expected_compose_file:
        errors.append("preflight compose_file does not match the selected target")
    project = payload.get("compose_project")
    if not isinstance(project, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{1,127}", project):
        errors.append("preflight compose_project is missing or invalid")
    canonical_project = expected_compose_project
    if canonical_project is None and compose_file is not None:
        canonical_project = canonical_compose_project(root, compose_file.as_posix())
    if canonical_project is not None and project != canonical_project:
        errors.append("preflight compose_project does not match the selected target")
    config_hash = payload.get("compose_config_sha256")
    if not isinstance(config_hash, str) or not SHA256_RE.fullmatch(config_hash):
        errors.append("preflight compose_config_sha256 is missing or invalid")
    if expected_config_sha256 is not None and config_hash != expected_config_sha256:
        errors.append("preflight compose_config_sha256 does not match the rendered target")
    source_hash = payload.get("compose_source_sha256")
    if not isinstance(source_hash, str) or not SHA256_RE.fullmatch(source_hash):
        errors.append("preflight compose_source_sha256 is missing or invalid")
    elif compose_file is not None:
        actual_source_hash = _sha256_file(root / compose_file)
        if actual_source_hash != source_hash:
            errors.append("preflight compose_source_sha256 does not match compose_file")

    required_services = payload.get("required_services")
    if not isinstance(required_services, Sequence) or isinstance(required_services, (str, bytes, bytearray)):
        errors.append("preflight required_services is not a list")
    else:
        seen: set[str] = set()
        for item in required_services:
            if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
                errors.append("preflight contains an invalid required service record")
                continue
            name = item["name"]
            if name in seen:
                errors.append(f"preflight service {name} is duplicated")
            seen.add(name)
            if item.get("state") != "running":
                errors.append(f"preflight service {name} is not running")
            if item.get("health") != "healthy" or item.get("ready") is not True:
                errors.append(f"preflight service {name} is not healthy and ready")
        declared = set(seen)
        expected_services = payload.get("required_service_names")
        if isinstance(expected_services, Sequence) and not isinstance(expected_services, (str, bytes, bytearray)):
            expected_set = {item for item in expected_services if isinstance(item, str)}
            if declared != expected_set:
                errors.append("preflight service records do not match required_service_names")
            if expected_set != set(REQUIRED_SERVICES):
                errors.append("preflight required_service_names do not cover the canonical Phase 3 lab")
        else:
            errors.append("preflight required_service_names is missing")
        if not declared:
            errors.append("preflight has no required service records")

    current = (now or utc_now()).astimezone(timezone.utc)
    generated_at = _parse_timestamp(payload.get("generated_at"), "generated_at", errors)
    expires_at = _parse_timestamp(payload.get("expires_at"), "expires_at", errors)
    if generated_at is not None:
        age = (current - generated_at).total_seconds()
        if age > MAX_AGE_SECONDS:
            errors.append("preflight is stale")
        if age < -MAX_FUTURE_SKEW_SECONDS:
            errors.append("preflight generated_at is in the future")
    if expires_at is not None:
        if expires_at <= current:
            errors.append("preflight is expired")
        if generated_at is not None and expires_at <= generated_at:
            errors.append("preflight expires_at is not after generated_at")
        if generated_at is not None and (expires_at - generated_at).total_seconds() > MAX_AGE_SECONDS:
            errors.append("preflight validity exceeds the maximum age")

    endpoints = payload.get("endpoints")
    if not isinstance(endpoints, Sequence) or isinstance(endpoints, (str, bytes, bytearray)):
        errors.append("preflight endpoints is not a list")
    else:
        by_name: dict[str, Any] = {}
        for item in endpoints:
            name = item.get("name") if isinstance(item, Mapping) else None
            if isinstance(name, str):
                if name in by_name:
                    errors.append(f"preflight endpoint {name} is duplicated")
                by_name[name] = item
                _validate_endpoint(item, name, current, errors)
            else:
                errors.append("preflight contains an endpoint without a name")
        for required in REQUIRED_ENDPOINTS:
            if required not in by_name:
                errors.append(f"preflight endpoint {required} is missing")
    return errors


def load_preflight(
    root: Path,
    path: str = DEFAULT_PATH,
    *,
    expected_checkout: Mapping[str, Any] | None = None,
    expected_compose_file: str | None = None,
    expected_compose_project: str | None = None,
    expected_config_sha256: str | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, Any] | None, list[str], str | None]:
    """Load and validate an attestation, returning payload, errors, and hash."""

    root = root.resolve()
    path_errors: list[str] = []
    safe = _safe_relative(root, path, "preflight path", path_errors)
    if safe is None:
        return None, path_errors, None
    target = root / safe
    if not target.is_file() or target.is_symlink():
        return None, ["preflight artifact is missing or symlinked"], None
    try:
        raw = target.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        return None, [f"preflight artifact is unreadable: {type(exc).__name__}"], None
    digest = _sha256_file(target)
    if digest is None:
        return None, ["preflight artifact could not be hashed"], None
    errors = validate_preflight(
        payload,
        root=root,
        expected_checkout=expected_checkout,
        expected_compose_file=expected_compose_file,
        expected_compose_project=expected_compose_project,
        expected_config_sha256=expected_config_sha256,
        now=now,
    )
    return (dict(payload) if isinstance(payload, Mapping) else None), errors, digest


def build_preflight(
    *,
    run_id: str,
    target_id: str,
    compose_file: str,
    compose_project: str,
    compose_config_sha256: str,
    compose_source_sha256: str,
    required_services: Sequence[Mapping[str, Any]],
    endpoints: Sequence[Mapping[str, Any]],
    checkout: Mapping[str, Any],
    generated_at: datetime | None = None,
    expires_at: datetime | None = None,
    required_service_names: Sequence[str] | None = None,
) -> dict[str, Any]:
    generated = (generated_at or utc_now()).astimezone(timezone.utc)
    expires = (expires_at or generated + timedelta(seconds=MAX_AGE_SECONDS)).astimezone(timezone.utc)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "run_id": run_id,
        "target_id": target_id,
        "commit_sha": checkout.get("head", checkout.get("commit_sha")),
        "tree_sha": checkout.get("tree", checkout.get("tree_sha")),
        "checkout_fingerprint": checkout.get("fingerprint", checkout.get("checkout_fingerprint")),
        "clean_worktree": checkout.get("status") == "CLEAN" and checkout.get("clean_worktree", True) is True,
        "compose_file": compose_file,
        "compose_project": compose_project,
        "compose_config_sha256": compose_config_sha256,
        "compose_source_sha256": compose_source_sha256,
        "required_service_names": list(required_service_names or (item.get("name") for item in required_services)),
        "required_services": [dict(item) for item in required_services],
        "endpoints": [dict(item) for item in endpoints],
        "disposable": True,
        "generated_at": generated.isoformat(),
        "expires_at": expires.isoformat(),
    }


def write_preflight(root: Path, path: str, payload: Mapping[str, Any]) -> str:
    """Atomically write a validated preflight and return its SHA-256."""

    root = root.resolve()
    errors = validate_preflight(payload, root=root)
    if errors:
        raise PreflightError("; ".join(errors))
    path_errors: list[str] = []
    safe = _safe_relative(root, path, "preflight path", path_errors)
    if safe is None:
        raise PreflightError("; ".join(path_errors))
    target = root / safe
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
        temporary.chmod(0o600)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    digest = _sha256_file(target)
    if digest is None:
        raise PreflightError("preflight was written but could not be hashed")
    return digest
