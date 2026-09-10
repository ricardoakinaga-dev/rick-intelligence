from __future__ import annotations

import json

import pytest

from scripts.state_of_art.json_boundary import load_json, loads_json
from scripts.state_of_art.validate_quality_bar import validate


def test_duplicate_object_keys_are_rejected() -> None:
    with pytest.raises(json.JSONDecodeError):
        loads_json('{"status":"FAIL","status":"PASS"}')


def test_nonfinite_constants_are_rejected() -> None:
    with pytest.raises(json.JSONDecodeError):
        loads_json('{"latency_ms":NaN}')


def test_invalid_utf8_is_rejected() -> None:
    with pytest.raises(UnicodeDecodeError):
        loads_json(b'{"status":"PASS"}\xff')


def test_file_decoder_is_bounded_before_projection(tmp_path) -> None:
    path = tmp_path / "oversized.json"
    path.write_text('{"padding":"' + ("x" * (1024 * 1024)) + '"}', encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        load_json(path)


def test_quality_bar_reader_rejects_duplicate_fields(tmp_path) -> None:
    path = tmp_path / "quality-bar.json"
    path.write_text('{"schema_version":1,"schema_version":2}', encoding="utf-8")

    errors = validate(path)

    assert errors and "not readable JSON" in errors[0]
