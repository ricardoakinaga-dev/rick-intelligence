from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).parents[3]


def _load(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=(
    ("redis", "run_phase3_redis.py", "redis_runtime_gate"),
    ("object-qdrant", "run_phase3_object_qdrant.py", "object_qdrant_runtime_gate"),
))
def adapter(request: pytest.FixtureRequest) -> ModuleType:
    _label, filename, _gate_name = request.param
    return _load(f"phase3_adapter_{request.param_index}", f"scripts/state_of_art/{filename}")


def _checkout(_root: Path) -> dict[str, str]:
    return {
        "head": "a" * 40,
        "tree": "b" * 40,
        "fingerprint": "c" * 64,
        "status": "CLEAN",
    }


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
    raw_path = tmp_path / "raw.json"

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
    assert raw_path.is_file()


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

    raw = (tmp_path / "raw.json").read_text(encoding="utf-8")
    assert envelope["status"] == "FAILED"
    assert envelope["artifact_sha256"]
    assert "remote secret" not in raw
    assert "RuntimeError" in raw


def test_output_path_cannot_escape_repository(adapter: ModuleType, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="inside the repository root"):
        adapter.run(tmp_path, output="../outside.json")
