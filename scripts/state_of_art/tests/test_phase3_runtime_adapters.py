from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from scripts.state_of_art.runtime_preflight import (
    DEFAULT_PATH,
    REQUIRED_SERVICES,
    build_preflight,
    canonical_compose_project,
    write_preflight,
)


ROOT = Path(__file__).parents[3]


def _load(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=(
    ("redis", "run_phase3_redis.py", "redis_runtime_gate"),
    ("redis-multi-replica", "run_phase3_redis_multi_replica.py", "redis_multi_replica_runtime_gate"),
    ("object-qdrant", "run_phase3_object_qdrant.py", "object_qdrant_runtime_gate"),
    ("multi-worker", "run_phase3_multi_worker.py", "multi_worker_runtime_gate"),
))
def adapter(request: pytest.FixtureRequest) -> ModuleType:
    _label, filename, _gate_name = request.param
    return _load(f"phase3_adapter_{request.param_index}", f"scripts/state_of_art/{filename}")


def _checkout(_root: Path) -> dict[str, object]:
    return {
        "available": True,
        "head": "a" * 40,
        "tree": "b" * 40,
        "fingerprint": "c" * 64,
        "status": "CLEAN",
        "errors": [],
    }


@pytest.fixture(autouse=True)
def valid_shared_preflight(tmp_path: Path) -> None:
    """Give PASS-path adapter tests an explicit same-run lab attestation."""

    (tmp_path / "docker-compose.dev.yml").write_text("services:\n", encoding="utf-8")
    now = datetime.now(timezone.utc)
    project = canonical_compose_project(tmp_path, "docker-compose.dev.yml")
    payload = build_preflight(
        run_id="run-adapter-12345678",
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
        checkout=_checkout(tmp_path),
    )
    write_preflight(tmp_path, DEFAULT_PATH, payload)


def _gate_module(adapter: ModuleType) -> ModuleType:
    return next(
        value
        for value in vars(adapter).values()
        if isinstance(value, ModuleType) and value.__name__.endswith("runtime_gate")
    )


def test_blocked_gate_emits_current_commit_bound_envelope(
    adapter: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_gate(argv: list[str]) -> int:
        output = tmp_path / Path(argv[argv.index("--output") + 1])
        output.write_text(
            json.dumps({"status": "BLOCKED_EXTERNAL", "results": [], "production_safe": False}),
            encoding="utf-8",
        )
        return 2

    monkeypatch.setattr(adapter, "RAW_OUTPUT", "raw.json")
    monkeypatch.setattr(adapter, "capture_checkout", _checkout)
    monkeypatch.setattr(_gate_module(adapter), "main", fake_gate)

    envelope = adapter.run(tmp_path, output="evidence.json")

    assert envelope["status"] == "BLOCKED_EXTERNAL"
    assert envelope["exit_status"] == 2
    assert envelope["freshness"] == "CURRENT"
    assert envelope["production_safe"] is False
    assert envelope["clean_worktree"] is True
    assert envelope["reviewer"]["independent"] is False
    assert (tmp_path / "evidence.json").is_file()
    assert list(tmp_path.glob("raw-*.json"))


def test_gate_failure_is_not_normalized_to_runtime_pass(
    adapter: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_gate(argv: list[str]) -> int:
        output = tmp_path / Path(argv[argv.index("--output") + 1])
        output.write_text(json.dumps({"status": "PASS", "production_safe": True}), encoding="utf-8")
        return 1

    monkeypatch.setattr(adapter, "RAW_OUTPUT", "raw.json")
    monkeypatch.setattr(adapter, "capture_checkout", _checkout)
    monkeypatch.setattr(_gate_module(adapter), "main", fake_gate)

    envelope = adapter.run(tmp_path, output="evidence.json")

    assert envelope["status"] == "FAILED"
    assert envelope["exit_status"] == 1


def test_missing_raw_output_cannot_reuse_a_stale_pass(
    adapter: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "raw.json").write_text(
        json.dumps({"status": "PASS", "production_safe": True}),
        encoding="utf-8",
    )

    def fake_gate(_argv: list[str]) -> int:
        return 0

    monkeypatch.setattr(adapter, "RAW_OUTPUT", "raw.json")
    monkeypatch.setattr(adapter, "capture_checkout", _checkout)
    monkeypatch.setattr(_gate_module(adapter), "main", fake_gate)

    envelope = adapter.run(tmp_path, output="evidence.json")

    assert envelope["status"] == "FAILED"
    assert envelope["exit_status"] == 1
    assert envelope["production_safe"] is False


def test_pass_without_shared_preflight_is_blocked_external(
    adapter: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / DEFAULT_PATH).unlink()

    def fake_gate(argv: list[str]) -> int:
        output = tmp_path / Path(argv[argv.index("--output") + 1])
        output.write_text(json.dumps({"status": "PASS", "production_safe": True}), encoding="utf-8")
        return 0

    monkeypatch.setattr(adapter, "RAW_OUTPUT", "raw.json")
    monkeypatch.setattr(adapter, "capture_checkout", _checkout)
    monkeypatch.setattr(_gate_module(adapter), "main", fake_gate)

    envelope = adapter.run(tmp_path, output="evidence.json")

    assert envelope["status"] == "BLOCKED_EXTERNAL"
    assert envelope["exit_status"] == 2
    assert envelope["production_safe"] is False
    assert envelope["preflight"]["status"] == "MISSING"


def test_gate_cannot_create_shared_preflight_after_it_started(
    adapter: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    preflight_path = tmp_path / DEFAULT_PATH
    preflight_bytes = preflight_path.read_bytes()
    preflight_path.unlink()

    def fake_gate(argv: list[str]) -> int:
        output = tmp_path / Path(argv[argv.index("--output") + 1])
        output.write_text(json.dumps({"status": "PASS", "production_safe": True}), encoding="utf-8")
        preflight_path.parent.mkdir(parents=True, exist_ok=True)
        preflight_path.write_bytes(preflight_bytes)
        return 0

    monkeypatch.setattr(adapter, "RAW_OUTPUT", "raw.json")
    monkeypatch.setattr(adapter, "capture_checkout", _checkout)
    monkeypatch.setattr(_gate_module(adapter), "main", fake_gate)

    envelope = adapter.run(tmp_path, output="evidence.json")

    assert envelope["status"] == "FAILED"
    assert envelope["exit_status"] == 1
    assert envelope["production_safe"] is False
    assert envelope["preflight"]["status"] == "INVALID"


def test_missing_checkout_identity_cannot_emit_a_successful_runtime_envelope(
    adapter: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_gate(argv: list[str]) -> int:
        output = tmp_path / Path(argv[argv.index("--output") + 1])
        output.write_text(json.dumps({"status": "PASS", "production_safe": True}), encoding="utf-8")
        return 0

    def unavailable_checkout(_root: Path) -> dict[str, object]:
        return {
            "available": False,
            "head": None,
            "tree": None,
            "fingerprint": None,
            "status": "UNKNOWN",
            "errors": ["git unavailable"],
        }

    monkeypatch.setattr(adapter, "RAW_OUTPUT", "raw.json")
    monkeypatch.setattr(adapter, "capture_checkout", unavailable_checkout)
    monkeypatch.setattr(_gate_module(adapter), "main", fake_gate)

    envelope = adapter.run(tmp_path, output="evidence.json")

    assert envelope["status"] == "FAILED"
    assert envelope["exit_status"] == 1
    assert envelope["checkout_available"] is False
    assert envelope["production_safe"] is False


def test_missing_raw_digest_cannot_emit_a_successful_runtime_envelope(
    adapter: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_gate(argv: list[str]) -> int:
        output = tmp_path / Path(argv[argv.index("--output") + 1])
        output.write_text(json.dumps({"status": "PASS", "production_safe": True}), encoding="utf-8")
        return 0

    monkeypatch.setattr(adapter, "RAW_OUTPUT", "raw.json")
    monkeypatch.setattr(adapter, "capture_checkout", _checkout)
    monkeypatch.setattr(_gate_module(adapter), "main", fake_gate)
    monkeypatch.setitem(adapter.run_gate_adapter.__globals__, "_sha256", lambda _path: None)

    envelope = adapter.run(tmp_path, output="evidence.json")

    assert envelope["status"] == "FAILED"
    assert envelope["exit_status"] == 1
    assert envelope["artifact_sha256"] is None
    assert envelope["production_safe"] is False


def test_checkout_mutation_during_gate_is_rejected(
    adapter: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    capture_count = 0

    def capture(_root: Path) -> dict[str, object]:
        nonlocal capture_count
        capture_count += 1
        checkout = _checkout(_root)
        if capture_count == 2:
            checkout["head"] = "d" * 40
        return checkout

    def fake_gate(argv: list[str]) -> int:
        output = tmp_path / Path(argv[argv.index("--output") + 1])
        output.write_text(json.dumps({"status": "PASS", "production_safe": True}), encoding="utf-8")
        return 0

    monkeypatch.setattr(adapter, "RAW_OUTPUT", "raw.json")
    monkeypatch.setattr(adapter, "capture_checkout", capture)
    monkeypatch.setattr(_gate_module(adapter), "main", fake_gate)

    envelope = adapter.run(tmp_path, output="evidence.json")

    assert envelope["status"] == "FAILED"
    assert envelope["exit_status"] == 1
    assert envelope["checkout_sentinel"]["unchanged"] is False


def test_malformed_raw_gate_output_cannot_emit_a_successful_runtime_envelope(
    adapter: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_gate(argv: list[str]) -> int:
        output = tmp_path / Path(argv[argv.index("--output") + 1])
        output.write_text("not-json", encoding="utf-8")
        return 0

    monkeypatch.setattr(adapter, "RAW_OUTPUT", "raw.json")
    monkeypatch.setattr(adapter, "capture_checkout", _checkout)
    monkeypatch.setattr(_gate_module(adapter), "main", fake_gate)

    envelope = adapter.run(tmp_path, output="evidence.json")

    assert envelope["status"] == "FAILED"
    assert envelope["exit_status"] == 1
    assert envelope["production_safe"] is False


def test_dirty_checkout_cannot_emit_a_successful_runtime_envelope(
    adapter: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_gate(argv: list[str]) -> int:
        output = tmp_path / Path(argv[argv.index("--output") + 1])
        output.write_text(
            json.dumps({"status": "PASS", "production_safe": True}),
            encoding="utf-8",
        )
        return 0

    monkeypatch.setattr(adapter, "RAW_OUTPUT", "raw.json")
    monkeypatch.setattr(adapter, "capture_checkout", lambda _root: {**_checkout(_root), "status": "DIRTY"})
    monkeypatch.setattr(_gate_module(adapter), "main", fake_gate)

    envelope = adapter.run(tmp_path, output="evidence.json")

    assert envelope["status"] == "FAILED"
    assert envelope["exit_status"] == 1
    assert envelope["freshness"] == "DIRTY_CHECKOUT"
    assert envelope["clean_worktree"] is False
    assert envelope["production_safe"] is False


def test_raw_gate_payload_is_redacted_before_persistence(
    adapter: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = "super-secret-value"
    secret_uri = f"https://user:{secret}@runtime.example.test/service"

    def fake_gate(argv: list[str]) -> int:
        output = tmp_path / Path(argv[argv.index("--output") + 1])
        output.write_text(
            json.dumps({
                "status": "PASS",
                "production_safe": True,
                "password": secret,
                "endpoint": secret_uri,
                "detail": f"token={secret} DATABASE_URL={secret_uri} DB_PASSWORD={secret} client_secret={secret}",
                "nested": {"api_key": secret},
            }),
            encoding="utf-8",
        )
        return 0

    monkeypatch.setattr(adapter, "RAW_OUTPUT", "raw.json")
    monkeypatch.setattr(adapter, "capture_checkout", _checkout)
    monkeypatch.setattr(_gate_module(adapter), "main", fake_gate)

    envelope = adapter.run(tmp_path, output="evidence.json")

    raw_path = next(tmp_path.glob("raw-*.json"))
    raw = raw_path.read_text(encoding="utf-8")
    assert envelope["status"] == "PASS"
    assert envelope["production_safe"] is True
    assert envelope["gate"]["password"] == "[REDACTED]"
    assert "token=[REDACTED]" in raw
    assert secret not in raw
    assert secret_uri not in raw


def test_free_form_secret_arguments_are_redacted() -> None:
    adapter_module = _load("phase3_redaction", "scripts/state_of_art/phase3_runtime_adapter.py")
    output = adapter_module.redact_runtime_value("--password super-secret password another-secret")

    assert "super-secret" not in output
    assert "another-secret" not in output
    assert output.count("[REDACTED]") == 2


def test_quoted_json_secret_keys_are_redacted() -> None:
    adapter_module = _load("phase3_quoted_redaction", "scripts/state_of_art/phase3_runtime_adapter.py")
    output = adapter_module.redact_runtime_value(
        '{"password": "json-secret", "token": "json-token"}'
    )
    escaped_output = adapter_module.redact_runtime_value(
        r'{"password": "safe \" json-escaped-secret"}'
    )
    escaped_argument = adapter_module.redact_runtime_value(
        r'--password "safe \" cli-escaped-secret"'
    )

    assert "json-secret" not in output
    assert "json-token" not in output
    assert output.count("[REDACTED]") == 2
    assert "json-escaped-secret" not in escaped_output
    assert "cli-escaped-secret" not in escaped_argument


def test_blocked_payload_gets_blocking_exit_even_if_gate_returns_zero(
    adapter: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_gate(argv: list[str]) -> int:
        output = tmp_path / Path(argv[argv.index("--output") + 1])
        output.write_text(json.dumps({"status": "BLOCKED_EXTERNAL"}), encoding="utf-8")
        return 0

    monkeypatch.setattr(adapter, "RAW_OUTPUT", "raw.json")
    monkeypatch.setattr(adapter, "capture_checkout", _checkout)
    monkeypatch.setattr(_gate_module(adapter), "main", fake_gate)

    envelope = adapter.run(tmp_path, output="evidence.json")

    assert envelope["status"] == "BLOCKED_EXTERNAL"
    assert envelope["exit_status"] == 2
    assert envelope["production_safe"] is False


def test_gate_exception_retains_sanitized_raw_diagnostic(
    adapter: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_gate(_argv: list[str]) -> int:
        raise RuntimeError("remote secret should not be persisted")

    monkeypatch.setattr(adapter, "RAW_OUTPUT", "raw.json")
    monkeypatch.setattr(adapter, "capture_checkout", _checkout)
    monkeypatch.setattr(_gate_module(adapter), "main", fake_gate)

    envelope = adapter.run(tmp_path, output="evidence.json")

    raw_path = next(tmp_path.glob("raw-*.json"))
    raw = raw_path.read_text(encoding="utf-8")
    assert envelope["status"] == "FAILED"
    assert envelope["artifact_sha256"]
    assert "remote secret" not in raw
    assert "RuntimeError" in raw


def test_output_path_cannot_escape_repository(adapter: ModuleType, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="inside the repository root"):
        adapter.run(tmp_path, output="../outside.json")
