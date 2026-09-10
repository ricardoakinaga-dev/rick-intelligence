from __future__ import annotations

import json
from pathlib import Path

from scripts.state_of_art.evaluate_retrieval import (
    FAIL,
    INCONCLUSIVE,
    NOT_RUN,
    PASS,
    evaluate_fixture,
    load_fixture,
    main,
)


FIXTURE = Path(__file__).parent / "fixtures" / "retrieval_fixture.json"


def test_fixture_proves_ranking_acl_and_provenance_metrics() -> None:
    loaded = load_fixture(FIXTURE)
    result = evaluate_fixture(
        {
            "schema_version": loaded.metadata["schema_version"],
            "cases": loaded.cases,
            "k_values": loaded.k_values,
        }
    )

    assert result["status"] == PASS
    assert result["metrics"]["ranking"]["hit_at_k"]["1"]["value"] == 1.0
    assert result["metrics"]["ranking"]["recall_at_k"]["1"]["value"] == 0.75
    assert result["metrics"]["acl_leakage"]["leakage_count"] == 0
    assert result["metrics"]["citation_source_coverage"]["citation_coverage"]["value"] == 1.0
    support = result["metrics"]["citation_support"]
    assert support["citation_precision"]["value"] == 1.0
    assert support["citation_recall"]["value"] == 1.0
    assert support["citation_completeness"]["value"] == 1.0
    assert support["unsupported_claim_rate"]["value"] == 0.0
    assert support["faithfulness"]["value"] == 1.0


def test_known_bad_acl_and_citation_cases_are_not_accepted() -> None:
    payload = {
        "k_values": [1],
        "cases": [
            {
                "case_id": "bad",
                "query": "q",
                "context": {
                    "tenant_id": "tenant-a",
                    "workspace_id": "workspace-a",
                    "allowed_collection_ids": ["clinical"],
                },
                "relevant_ids": ["secret"],
                "results": [
                    {
                        "chunk_id": "secret",
                        "tenant_id": "tenant-b",
                        "workspace_id": "workspace-b",
                        "collection_id": "clinical",
                        "source": "other.pdf",
                    }
                ],
                "citations": [{"chunk_id": "missing", "source": "other.pdf"}],
            }
        ],
    }

    result = evaluate_fixture(payload)

    assert result["status"] == FAIL
    assert result["metrics"]["acl_leakage"]["status"] == FAIL
    assert result["metrics"]["citation_source_coverage"]["status"] == FAIL


def test_claim_support_rejects_forged_and_missing_supporting_citations() -> None:
    result = evaluate_fixture(
        {
            "cases": [
                {
                    "case_id": "claim-negative",
                    "query": "q",
                    "citations": [{"chunk_id": "real", "source": "approved.txt"}],
                    "claims": [
                        {
                            "claim_id": "claim-1",
                            "text": "A claim with a forged citation.",
                            "citation_ids": ["forged"],
                            "reference_citation_ids": ["real"],
                        }
                    ],
                }
            ]
        }
    )

    support = result["metrics"]["citation_support"]
    assert result["status"] == FAIL
    assert support["status"] == FAIL
    assert support["invalid_citation_count"] == 1
    assert support["citation_precision"]["value"] == 0.0
    assert support["citation_recall"]["value"] == 0.0
    assert support["citation_completeness"]["value"] == 0.0
    assert support["unsupported_claim_rate"]["value"] == 1.0
    assert support["faithfulness"]["status"] == INCONCLUSIVE


def test_missing_annotations_are_inconclusive_instead_of_a_pass() -> None:
    result = evaluate_fixture(
        {
            "cases": [
                {
                    "query": "q",
                    "results": [{
                        "chunk_id": "chunk-1",
                        "source": "fixture.txt",
                        "checksum": "sha256:fixture",
                    }],
                }
            ]
        }
    )

    assert result["status"] == INCONCLUSIVE
    assert result["metrics"]["ranking"]["status"] == INCONCLUSIVE
    assert result["metrics"]["acl_leakage"]["status"] == INCONCLUSIVE
    assert result["metrics"]["citation_support"]["status"] == NOT_RUN


def test_claim_support_is_inconclusive_without_approved_annotations() -> None:
    result = evaluate_fixture(
        {
            "cases": [
                {
                    "case_id": "claim-unannotated",
                    "query": "q",
                    "context": {
                        "tenant_id": "tenant-a",
                        "workspace_id": "workspace-a",
                        "allowed_collection_ids": ["reference"],
                    },
                    "results": [{
                        "chunk_id": "chunk-1",
                        "tenant_id": "tenant-a",
                        "workspace_id": "workspace-a",
                        "collection_id": "reference",
                        "source": "fixture.txt",
                        "checksum": "sha256:fixture",
                    }],
                    "citations": [{
                        "chunk_id": "chunk-1",
                        "tenant_id": "tenant-a",
                        "workspace_id": "workspace-a",
                        "collection_id": "reference",
                        "source": "fixture.txt",
                    }],
                    "claims": [
                        {
                            "claim_id": "claim-1",
                            "text": "The fixture contains a claim.",
                            "citation_ids": ["chunk-1"],
                        }
                    ],
                }
            ]
        }
    )

    support = result["metrics"]["citation_support"]
    assert result["status"] == INCONCLUSIVE
    assert support["status"] == INCONCLUSIVE
    assert support["citation_completeness"]["status"] == INCONCLUSIVE
    assert support["unsupported_claim_rate"]["status"] == INCONCLUSIVE
    assert support["faithfulness"]["status"] == INCONCLUSIVE


def test_reviewed_faithfulness_is_bounded_and_cannot_be_inferred() -> None:
    result = evaluate_fixture(
        {
            "cases": [{
                "query": "q",
                "citations": [{"chunk_id": "chunk-1", "source": "approved.txt"}],
                "claims": [{
                    "claim_id": "claim-1",
                    "text": "A reviewed claim.",
                    "citation_ids": ["chunk-1"],
                    "reference_citation_ids": ["chunk-1"],
                    "faithfulness": 0.75,
                }],
            }],
        }
    )
    support = result["metrics"]["citation_support"]
    assert support["faithfulness"]["status"] == PASS
    assert support["faithfulness"]["value"] == 0.75

    missing = evaluate_fixture(
        {
            "cases": [{
                "query": "q",
                "claims": [{"claim_id": "claim-1", "text": "No review annotation."}],
            }],
        }
    )
    assert missing["metrics"]["citation_support"]["faithfulness"]["status"] == INCONCLUSIVE


def test_missing_fixture_is_not_run_and_live_mode_never_calls_a_provider(capsys, tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.json"
    assert main(["--fixture", str(missing)]) == 2
    not_run = json.loads(capsys.readouterr().out)
    assert not_run["status"] == NOT_RUN
    assert not_run["live_provider"]["status"] == NOT_RUN

    assert main(["--mode", "live"]) == 2
    live = json.loads(capsys.readouterr().out)
    assert live["status"] == NOT_RUN
    assert live["live_provider"]["status"] == NOT_RUN
