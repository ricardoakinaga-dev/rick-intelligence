from __future__ import annotations

import json
from pathlib import Path

from scripts.state_of_art.evaluate_pack import FAIL, PASS, evaluate_pack, main


PACK = Path(__file__).parents[2].parent / "docs" / "evaluation" / "packs" / "rec22-local-v1"


def test_local_pack_checks_thresholds_negatives_and_model_corpus_groups() -> None:
    result = evaluate_pack(PACK)

    assert result["status"] == PASS
    assert result["pack"]["positive_case_count"] == 2
    assert result["pack"]["negative_case_count"] == 3
    assert {row["model_id"] for row in result["per_model_corpus"]} == {"offline-ranker-a", "offline-ranker-b"}
    assert {row["corpus_id"] for row in result["per_model_corpus"]} == {"synthetic-corpus-a", "synthetic-corpus-b"}
    assert all(row["status"] == PASS for row in result["thresholds"])
    assert all(row["status"] == PASS for row in result["negative_cases"])
    assert result["live_provider"]["status"] == "NOT_RUN"


def test_threshold_violation_is_a_failure(tmp_path: Path) -> None:
    manifest = json.loads((PACK / "manifest.json").read_text(encoding="utf-8"))
    manifest["thresholds"][0]["value"] = 1.1
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (pack / "cases.json").write_bytes((PACK / "cases.json").read_bytes())

    result = evaluate_pack(pack)

    assert result["status"] == FAIL
    assert result["thresholds"][0]["status"] == FAIL


def test_malformed_negative_case_is_not_accepted(tmp_path: Path) -> None:
    manifest = json.loads((PACK / "manifest.json").read_text(encoding="utf-8"))
    fixture = json.loads((PACK / "cases.json").read_text(encoding="utf-8"))
    fixture["cases"][2]["results"] = [{"chunk_id": "leak"}]
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (pack / "cases.json").write_text(json.dumps(fixture), encoding="utf-8")

    result = evaluate_pack(pack)

    assert result["status"] == FAIL
    assert result["negative_cases"][0]["status"] == FAIL


def test_missing_pack_is_not_run(capsys, tmp_path: Path) -> None:
    assert main(["--pack", str(tmp_path / "missing")]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "NOT_RUN"
