from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.state_of_art.evaluate_pack import (
    FAIL,
    PASS,
    _check_threshold,
    _evaluate_cases,
    evaluate_pack,
    main,
    ndcg,
    reciprocal_rank,
)


PACK = Path(__file__).parents[2].parent / "docs" / "evaluation" / "packs" / "rec22-local-v1"
PASSING_PACK = Path(__file__).parents[2].parent / "docs" / "evaluation" / "packs" / "rec22-local-v2"


def test_local_pack_checks_thresholds_negatives_and_model_corpus_groups() -> None:
    result = evaluate_pack(PACK)

    assert result["status"] == FAIL
    alpha, beta = result["per_model_corpus"]
    assert alpha["status"] == FAIL
    assert beta["status"] == PASS
    failed = [row for row in alpha["thresholds"] if row["status"] == FAIL]
    assert [(row["id"], row["observed"], row["target"]) for row in failed] == [
        ("ranking-recall-at-1", 0.5, 0.75)
    ]
    assert result["pack"]["positive_case_count"] == 2
    assert result["pack"]["negative_case_count"] == 3
    assert {row["model_id"] for row in result["per_model_corpus"]} == {"offline-ranker-a", "offline-ranker-b"}
    assert {row["corpus_id"] for row in result["per_model_corpus"]} == {"synthetic-corpus-a", "synthetic-corpus-b"}
    assert all(row["status"] == PASS for row in result["thresholds"])
    assert all(row["status"] == PASS for row in result["negative_cases"])
    assert result["live_provider"]["status"] == "NOT_RUN"


def test_successor_pack_uses_recall_at_2_and_passes_each_positive_group() -> None:
    result = evaluate_pack(PASSING_PACK)

    assert result["status"] == PASS
    assert result["pack"]["version"] == "2.0.0"
    assert all(row["status"] == PASS for row in result["per_model_corpus"])
    for group in result["per_model_corpus"]:
        recall = next(row for row in group["thresholds"] if row["id"] == "ranking-recall-at-2")
        assert recall["metric_path"] == "metrics.ranking.recall_at_k.2.value"
        assert recall["observed"] == 1.0
        assert recall["target"] == 1.0


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


@pytest.mark.parametrize("metric", [{}, {"value": None}, {"value": "no_data"}, {"value": 0, "status": "INCONCLUSIVE"}, {"value": 0, "status": "NOT_RUN"}])
def test_required_missing_metric_fails_even_for_zero_target(metric) -> None:
    threshold = {"id": "required", "metric_path": "metric.value", "operator": "<=", "target": 0}
    result = _check_threshold({"metric": metric}, threshold)
    assert result["status"] == FAIL
    assert result["observed"] is None
    assert result["data_status"] == "no_data"
    assert _check_threshold({"metric": {"status": PASS, "value": 0}}, threshold)["status"] == PASS


def test_complete_passing_groups_and_missing_required_metric(tmp_path: Path) -> None:
    manifest = json.loads((PACK / "manifest.json").read_text())
    fixture = json.loads((PACK / "cases.json").read_text())
    fixture["cases"][0]["relevant_ids"] = ["alpha-1"]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "cases.json").write_text(json.dumps(fixture))
    assert evaluate_pack(tmp_path)["status"] == PASS
    del fixture["cases"][0]["claims"][0]["faithfulness"]
    (tmp_path / "cases.json").write_text(json.dumps(fixture))
    result = evaluate_pack(tmp_path)
    assert result["status"] == FAIL
    missing = next(row for row in result["per_model_corpus"][0]["thresholds"] if row["id"] == "faithfulness")
    assert missing["status"] == FAIL
    assert missing["data_status"] == "no_data"


def test_missing_group_latency_cannot_hide_behind_aggregate(tmp_path: Path) -> None:
    manifest = json.loads((PACK / "manifest.json").read_text())
    fixture = json.loads((PACK / "cases.json").read_text())
    del fixture["cases"][0]["latency_samples_ms"]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "cases.json").write_text(json.dumps(fixture))
    result = evaluate_pack(tmp_path)
    assert result["status"] == FAIL
    threshold = result["per_model_corpus"][0]["thresholds"][-1]
    assert threshold["id"] == "fixture-p95-latency"
    assert threshold["status"] == FAIL
    assert threshold["data_status"] == "no_data"


def test_reciprocal_rank_known_values_and_missing_annotations() -> None:
    assert reciprocal_rank(["x", "a", "b"], ["a", "b"]) == 1 / 2
    assert reciprocal_rank(["x", "y", "a"], ["a"]) == 1 / 3
    assert reciprocal_rank(["x"], ["a"]) == 0
    assert reciprocal_rank([], ["a"]) == 0
    assert reciprocal_rank(["a"], []) is None


def test_ndcg_known_values_cutoff_duplicates_and_missing_annotations() -> None:
    assert ndcg(["x", "y", "a"], ["a"], 3) == 1 / 2
    assert ndcg(["a", "x", "y", "b"], ["a", "b"], 3) == pytest.approx(0.6131471927654584)
    assert ndcg(["a", "a"], ["a", "b"], 2) == pytest.approx(0.6131471927654584)
    assert ndcg(["a", "b"], ["a", "b"], 2) == 1
    assert ndcg(["x", "a"], ["a"], 1) == 0
    assert ndcg([], ["a"], 3) == 0
    assert ndcg(["a"], [], 3) is None
    with pytest.raises(ValueError):
        ndcg(["a"], ["a"], 0)


def test_pack_mrr_is_macro_mean_and_ndcg_uses_rank_order() -> None:
    cases = [
        {"query": "one", "relevant_ids": ["a"], "results": [{"id": "a", "rank": 2}, {"id": "x", "rank": 1}]},
        {"query": "two", "relevant_ids": ["b"], "results": [{"id": "b"}]},
        {"query": "three", "relevant_ids": ["c"], "results": []},
    ]
    ranking = _evaluate_cases(cases, (1, 3))["metrics"]["ranking"]
    assert ranking["mrr"]["value"] == (1 / 2 + 1 + 0) / 3
    assert ranking["ndcg_at_k"]["1"]["value"] == 1 / 3
    assert ranking["ndcg_at_k"]["3"]["value"] == pytest.approx(0.5436432511904858)


def test_missing_pack_is_not_run(capsys, tmp_path: Path) -> None:
    assert main(["--pack", str(tmp_path / "missing")]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "NOT_RUN"
