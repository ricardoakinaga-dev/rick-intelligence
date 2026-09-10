from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "gauntlet_state_boundary",
    ROOT / "scripts/control_plane/vendor/gauntlet_loop/gauntlet_state.py",
)
assert SPEC is not None and SPEC.loader is not None
gauntlet_state = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gauntlet_state)


def test_state_reader_rejects_duplicate_and_nonfinite_fields(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"status":"ACTIVE","status":"STOPPED"}', encoding="utf-8")
    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"status":NaN}', encoding="utf-8")

    for path in (duplicate, nonfinite):
        with pytest.raises(gauntlet_state.StateError, match="invalid JSON"):
            gauntlet_state.read_json(path)


def test_state_reader_enforces_byte_bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gauntlet_state, "MAX_STATE_JSON_BYTES", 4)
    path = tmp_path / "oversized.json"
    path.write_text('{"x":1}', encoding="utf-8")

    with pytest.raises(gauntlet_state.StateError, match="invalid JSON"):
        gauntlet_state.read_json(path)


def test_jsonl_reader_rejects_duplicate_fields(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    path.write_text('{"event":"round","event":"forged"}\n', encoding="utf-8")

    with pytest.raises(gauntlet_state.StateError, match="invalid JSONL"):
        gauntlet_state.load_jsonl(path)


def test_jsonl_reader_rejects_invalid_utf8(tmp_path: Path) -> None:
    path = tmp_path / "invalid-utf8.jsonl"
    path.write_bytes(b'{"event":"\xff"}\n')

    with pytest.raises(gauntlet_state.StateError, match="invalid JSONL"):
        gauntlet_state.load_jsonl(path)
