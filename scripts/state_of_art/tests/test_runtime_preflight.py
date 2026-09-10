from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path

from scripts.state_of_art.runtime_preflight import (
    DEFAULT_PATH,
    REQUIRED_SERVICES,
    build_preflight,
    canonical_compose_project,
    load_preflight,
    validate_preflight,
    write_preflight,
)


CHECKOUT = {
    "head": "a" * 40,
    "tree": "b" * 40,
    "fingerprint": "c" * 64,
    "status": "CLEAN",
    "clean_worktree": True,
}


def _payload(tmp_path: Path, *, generated_at: datetime | None = None) -> dict[str, object]:
    (tmp_path / "docker-compose.dev.yml").write_text("services:\n", encoding="utf-8")
    now = generated_at or datetime.now(timezone.utc)
    project = canonical_compose_project(tmp_path, "docker-compose.dev.yml")
    return build_preflight(
        run_id="run-12345678",
        target_id=f"phase3-compose:{project}:docker-compose.dev.yml",
        compose_file="docker-compose.dev.yml",
        compose_project=project,
        compose_config_sha256="d" * 64,
        compose_source_sha256=sha256((tmp_path / "docker-compose.dev.yml").read_bytes()).hexdigest(),
        required_services=[
            {"name": name, "state": "running", "health": "healthy", "ready": True}
            for name in REQUIRED_SERVICES
        ],
        required_service_names=REQUIRED_SERVICES,
        endpoints=[
            {
                "name": "api-readiness",
                "url": "http://127.0.0.1:18000/health/ready",
                "status": "PASS",
                "reachable": True,
                "http_status": 200,
                "verified_at": now.isoformat(),
            },
            {
                "name": "web-readiness",
                "url": "http://127.0.0.1:13000/login",
                "status": "PASS",
                "reachable": True,
                "http_status": 200,
                "verified_at": now.isoformat(),
            },
        ],
        checkout=CHECKOUT,
        generated_at=now,
    )


def test_valid_preflight_is_current_and_hashable(tmp_path: Path) -> None:
    payload = _payload(tmp_path)

    assert validate_preflight(payload, root=tmp_path, expected_checkout=CHECKOUT) == []
    digest = write_preflight(tmp_path, DEFAULT_PATH, payload)
    loaded, errors, actual_digest = load_preflight(
        tmp_path,
        expected_checkout=CHECKOUT,
        expected_compose_project=canonical_compose_project(tmp_path, "docker-compose.dev.yml"),
        expected_config_sha256="d" * 64,
    )

    assert errors == []
    assert loaded == payload
    assert actual_digest == digest


def test_preflight_rejects_wrong_identity_target_or_service_readiness(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    payload["commit_sha"] = "e" * 40
    payload["compose_project"] = "another-project"
    payload["required_services"] = [
        {**item, "health": "starting"}
        if item["name"] == "redis"
        else item
        for item in payload["required_services"]  # type: ignore[index]
    ]

    errors = validate_preflight(
        payload,
        root=tmp_path,
        expected_checkout=CHECKOUT,
        expected_compose_project=canonical_compose_project(tmp_path, "docker-compose.dev.yml"),
    )

    assert any("commit_sha" in error for error in errors)
    assert any("compose_project" in error for error in errors)
    assert any("redis" in error and "healthy" in error for error in errors)


def test_preflight_rejects_noncanonical_target_binding(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    payload["target_id"] = "phase3-compose:another-project:compose.yml"
    payload["compose_file"] = "compose.yml"
    (tmp_path / "compose.yml").write_text("services:\n", encoding="utf-8")

    errors = validate_preflight(payload, root=tmp_path)

    assert any("canonical Phase 3 Compose" in error for error in errors)
    assert any("target_id" in error for error in errors)


def test_preflight_rejects_stale_and_secret_bearing_endpoint(tmp_path: Path) -> None:
    old = datetime.now(timezone.utc) - timedelta(days=2)
    payload = _payload(tmp_path, generated_at=old)
    payload["endpoints"][0]["url"] = "http://user:secret@127.0.0.1:18000/health/ready"  # type: ignore[index]

    errors = validate_preflight(payload, root=tmp_path, expected_checkout=CHECKOUT)

    assert any("stale" in error for error in errors)
    assert any("userinfo" in error for error in errors)


def test_preflight_rejects_dirty_non_disposable_missing_endpoint_and_symlink(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    payload["clean_worktree"] = False
    payload["disposable"] = False
    payload["endpoints"] = [payload["endpoints"][0]]  # type: ignore[index]
    assert any("clean" in error for error in validate_preflight(payload, root=tmp_path, expected_checkout=CHECKOUT))

    outside = tmp_path.parent / "preflight-outside.json"
    outside.write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "linked-compose.yml").symlink_to(tmp_path / "docker-compose.dev.yml")
    payload["compose_file"] = "linked-compose.yml"
    errors = validate_preflight(payload, root=tmp_path, expected_checkout=CHECKOUT)

    assert any("disposable" in error for error in errors)
    assert any("web-readiness" in error for error in errors)
    assert any("symlinked" in error for error in errors)
    outside.unlink()
