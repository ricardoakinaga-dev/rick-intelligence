from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "run_phase3_postgres",
    Path(__file__).parents[1] / "run_phase3_postgres.py",
)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


def test_missing_database_is_wrapped_as_blocked_without_runtime_claim(monkeypatch, tmp_path: Path) -> None:
    def fake_gate(argv: list[str]) -> int:
        output = tmp_path / Path(argv[argv.index("--output") + 1])
        output.write_text(json.dumps({"status": "BLOCKED_EXTERNAL", "results": []}), encoding="utf-8")
        return 2

    monkeypatch.setattr(adapter.postgres_runtime_gate, "main", fake_gate)
    monkeypatch.setattr(
        adapter,
        "capture_checkout",
        lambda _root: {
            "available": True,
            "head": "a" * 40,
            "tree": "b" * 40,
            "fingerprint": "c" * 64,
            "status": "CLEAN",
            "errors": [],
        },
    )
    monkeypatch.setattr(adapter, "RAW_OUTPUT", "raw.json")

    envelope = adapter.run(tmp_path, output="evidence.json")

    assert envelope["status"] == "BLOCKED_EXTERNAL"
    assert envelope["exit_status"] == 2
    assert envelope["reviewer"]["independent"] is False
    assert (tmp_path / "evidence.json").is_file()
    assert list(tmp_path.glob("raw-*.json"))


def test_output_path_cannot_escape_repository(tmp_path: Path) -> None:
    try:
        adapter.run(tmp_path, output="../outside.json")
    except ValueError:
        pass
    else:
        raise AssertionError("path traversal should be rejected")
