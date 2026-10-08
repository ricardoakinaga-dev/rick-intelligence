from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path

import pytest

from scripts.state_of_art.evaluate_campaign import (
    CampaignError,
    _identity_text as _campaign_identity_text,
    _wilson_interval,
    evaluate_campaign,
)
from scripts.state_of_art.evaluate_pack import PackError, _identity_text as _pack_identity_text


ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN = ROOT / "docs/evaluation/campaigns/rec22-local-synthetic-v1/manifest.json"
PACK = ROOT / "docs/evaluation/packs/rec22-local-v2"


@pytest.mark.parametrize(
    "value",
    ["\ud800", "\udfff", "identity\ud800suffix"],
    ids=["high-surrogate", "low-surrogate", "embedded-surrogate"],
)
def test_identity_helpers_reject_unpaired_surrogates(value: str) -> None:
    with pytest.raises(CampaignError, match="valid Unicode scalar values"):
        _campaign_identity_text(value, field="identity")
    with pytest.raises(PackError, match="valid Unicode scalar values"):
        _pack_identity_text(value, field="identity")


def _copy_campaign(tmp_path: Path, mutate=None) -> Path:
    evaluation_root = tmp_path / "docs/evaluation"
    campaign_directory = evaluation_root / "campaigns/test-campaign"
    pack_directory = evaluation_root / "packs/rec22-local-v2"
    campaign_directory.mkdir(parents=True)
    shutil.copytree(PACK, pack_directory)
    manifest = json.loads(CAMPAIGN.read_text(encoding="utf-8"))
    if mutate:
        mutate(manifest)
    manifest_path = campaign_directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _annotate_case_strata(
    manifest_path: Path,
    dimensions: list[str],
    labels_by_case: dict[str, dict[str, str]],
) -> None:
    campaign = json.loads(manifest_path.read_text(encoding="utf-8"))
    campaign["evaluation_design"]["strata_dimensions"] = dimensions
    manifest_path.write_text(json.dumps(campaign), encoding="utf-8")

    evaluation_root = manifest_path.parent.parent.parent
    pack_directory = (evaluation_root / campaign["pack_path"]).resolve()
    pack_manifest = json.loads((pack_directory / "manifest.json").read_text(encoding="utf-8"))
    fixture_path = (pack_directory / pack_manifest["fixture"]).resolve()
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    for case in fixture["cases"]:
        case["pack"]["strata"] = labels_by_case[case["case_id"]]
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")


def test_synthetic_campaign_separates_harness_pass_from_campaign_status() -> None:
    result = evaluate_campaign(CAMPAIGN)

    assert result["status"] == "PASS"
    assert result["schema_version"] == "retrieval-campaign-result.v4"
    assert result["campaign_status"] == "NOT_RUN"
    assert result["eligibility_status"] == "BLOCKED"
    assert result["quality_by_strata"] == []
    assert result["uncertainty"]["by_quality_stratum"] == []
    assert any("risk and ambiguity strata" in item for item in result["blockers"])
    assert result["pack"] == {
        "pack_id": "rec22-local-synthetic-v2",
        "version": "2.0.0",
        "status": "PASS",
        "case_count": 5,
        "positive_case_count": 2,
        "negative_case_count": 3,
    }
    assert result["split"]["status"] == "NOT_ASSIGNED"
    assert result["split"]["case_counts"] == {
        "train": 0,
        "calibration": 0,
        "reserved": 0,
        "unassigned": 5,
    }
    assert len(result["strata"]) == 5
    assert result["evaluation_design"]["minimum_cases_per_positive_stratum"] == 30
    assert result["offline_fixture_checks"]["source_support"]["status"] == "PASS"
    assert result["offline_fixture_checks"]["citation_support"]["status"] == "PASS"
    assert result["offline_fixture_checks"]["tenant_isolation"]["leakage_count"] == 0

    interval = result["uncertainty"]["overall"]
    assert interval["successes"] == 2
    assert interval["sample_size"] == 2
    assert interval["estimate"] == 1.0
    assert interval["confidence_interval"][0] == pytest.approx(0.3424, abs=0.001)
    assert interval["confidence_interval"][1] == 1.0
    assert [row["hit_at_1"]["sample_size"] for row in result["uncertainty"]["by_model_corpus"]] == [1, 1]

    abstentions = result["abstention_expectations"]
    assert len(abstentions) == 3
    assert {row["expected_disposition"] for row in abstentions} == {"ABSTAIN"}
    assert {row["observed_response_disposition"] for row in abstentions} == {"NOT_MEASURED"}
    assert {row["structural_fixture_status"] for row in abstentions} == {"PASS"}


def test_declared_risk_and_ambiguity_strata_report_grouped_quality(tmp_path: Path) -> None:
    path = _copy_campaign(tmp_path)
    _annotate_case_strata(
        path,
        ["risk", "ambiguity"],
        {
            "alpha-positive": {"risk": "synthetic_low", "ambiguity": "synthetic_clear"},
            "beta-positive": {"risk": "synthetic_low", "ambiguity": "synthetic_clear"},
            "negative-no-evidence": {"risk": "synthetic_unknown", "ambiguity": "synthetic_no_evidence"},
            "negative-weak-evidence": {"risk": "synthetic_unknown", "ambiguity": "synthetic_weak_evidence"},
            "negative-unsupported-assertion": {
                "risk": "synthetic_unknown", "ambiguity": "synthetic_unsupported_assertion",
            },
        },
    )

    result = evaluate_campaign(path)

    assert result["status"] == "PASS"
    assert result["campaign_status"] == "NOT_RUN"
    assert result["eligibility_status"] == "BLOCKED"
    assert result["evaluation_design"]["strata_dimensions"] == ["risk", "ambiguity"]
    shared_positive_dimensions = {"risk": "synthetic_low", "ambiguity": "synthetic_clear"}
    positive_groups = [
        row for row in result["quality_by_strata"]
        if row["role"] == "positive" and row["dimensions"] == shared_positive_dimensions
    ]
    assert len(positive_groups) == 2
    positive_by_model = {row["model_id"]: row for row in positive_groups}
    assert set(positive_by_model) == {"offline-ranker-a", "offline-ranker-b"}
    alpha = positive_by_model["offline-ranker-a"]
    beta = positive_by_model["offline-ranker-b"]
    assert (alpha["corpus_id"], alpha["case_count"], alpha["positive_case_count"]) == (
        "synthetic-corpus-a", 1, 1,
    )
    assert (beta["corpus_id"], beta["case_count"], beta["positive_case_count"]) == (
        "synthetic-corpus-b", 1, 1,
    )
    assert alpha["metrics"]["latency"]["p95"] == 11
    assert beta["metrics"]["latency"]["p95"] == 15
    assert all(row["retrieval_uncertainty"]["sample_size"] == 1 for row in positive_groups)
    assert all(row["metrics"]["citation_source_coverage"]["status"] == "PASS" for row in positive_groups)
    assert all(row["metrics"]["citation_support"]["status"] == "PASS" for row in positive_groups)
    assert all(row["metrics"]["acl_leakage"]["leakage_count"] == 0 for row in positive_groups)
    assert all(row["abstention"]["status"] == "NOT_MEASURED" for row in positive_groups)

    negative_groups = [row for row in result["quality_by_strata"] if row["role"] == "negative"]
    assert {row["expectation"] for row in negative_groups} == {
        "no_evidence", "weak_evidence", "unsupported_assertion",
    }
    assert all(row["case_count"] == 1 for row in negative_groups)
    assert {row["stratum_id"] for row in result["strata"]} == {
        row["stratum_id"] for row in result["quality_by_strata"]
    }
    quality_intervals = result["uncertainty"]["by_quality_stratum"]
    positive_intervals = [row for row in quality_intervals if row["role"] == "positive"]
    assert {(row["model_id"], row["corpus_id"], row["hit_at_1"]["sample_size"]) for row in positive_intervals} == {
        ("offline-ranker-a", "synthetic-corpus-a", 1),
        ("offline-ranker-b", "synthetic-corpus-b", 1),
    }
    negative_intervals = [row for row in quality_intervals if row["role"] == "negative"]
    assert {row["expectation"] for row in negative_intervals} == {
        "no_evidence", "weak_evidence", "unsupported_assertion",
    }


def test_stratum_ids_escape_identity_separators_without_collisions(tmp_path: Path) -> None:
    path = _copy_campaign(tmp_path)
    _annotate_case_strata(
        path,
        ["risk", "ambiguity"],
        {
            "alpha-positive": {"risk": " synthetic_low ", "ambiguity": "synthetic_clear"},
            "beta-positive": {"risk": " synthetic_low ", "ambiguity": "synthetic_clear"},
            "negative-no-evidence": {"risk": "synthetic_unknown", "ambiguity": "synthetic_no_evidence"},
            "negative-weak-evidence": {"risk": "synthetic_unknown", "ambiguity": "synthetic_weak_evidence"},
            "negative-unsupported-assertion": {
                "risk": "synthetic_unknown", "ambiguity": "synthetic_unsupported_assertion",
            },
        },
    )
    campaign = json.loads(path.read_text(encoding="utf-8"))
    evaluation_root = path.parent.parent.parent
    pack_directory = (evaluation_root / campaign["pack_path"]).resolve()
    pack_manifest = json.loads((pack_directory / "manifest.json").read_text(encoding="utf-8"))
    fixture_path = (pack_directory / pack_manifest["fixture"]).resolve()
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    for case in fixture["cases"]:
        if case["case_id"] == "alpha-positive":
            case["pack"].update(model_id="a/b", corpus_id="c")
        elif case["case_id"] == "beta-positive":
            case["pack"].update(model_id="a", corpus_id="b/c")
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")

    result = evaluate_campaign(path)

    positive_quality = [row for row in result["quality_by_strata"] if row["role"] == "positive"]
    assert len(positive_quality) == 2
    assert len({row["stratum_id"] for row in positive_quality}) == 2
    assert {row["stratum_id"] for row in positive_quality} == {
        row["stratum_id"] for row in result["strata"] if row["role"] == "positive"
    }
    assert {row["stratum_id"] for row in positive_quality} == {
        row["stratum_id"] for row in result["uncertainty"]["by_quality_stratum"]
        if row["role"] == "positive"
    }
    assert {"a/b", "a"} == {row["model_id"] for row in positive_quality}
    assert {"c", "b/c"} == {row["corpus_id"] for row in positive_quality}
    assert any("a%2Fb" in row["stratum_id"] for row in positive_quality)
    assert any("b%2Fc" in row["stratum_id"] for row in positive_quality)
    encoded_dimensions = positive_quality[0]["stratum_id"].rsplit("/labels-", 1)[1]
    decoded_dimensions = base64.urlsafe_b64decode(
        encoded_dimensions + "=" * (-len(encoded_dimensions) % 4)
    ).decode("utf-8")
    assert json.loads(decoded_dimensions) == positive_quality[0]["dimensions"]
    assert positive_quality[0]["dimensions"]["risk"] == " synthetic_low "
    assert decoded_dimensions == json.dumps(
        positive_quality[0]["dimensions"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def test_stratum_identity_preserves_significant_whitespace(tmp_path: Path) -> None:
    path = _copy_campaign(tmp_path)
    _annotate_case_strata(
        path,
        ["risk", "ambiguity"],
        {
            "alpha-positive": {"risk": "synthetic_low", "ambiguity": "synthetic_clear"},
            "beta-positive": {"risk": "synthetic_low", "ambiguity": "synthetic_clear"},
            "negative-no-evidence": {"risk": "synthetic_unknown", "ambiguity": "synthetic_no_evidence"},
            "negative-weak-evidence": {"risk": "synthetic_unknown", "ambiguity": "synthetic_weak_evidence"},
            "negative-unsupported-assertion": {
                "risk": "synthetic_unknown", "ambiguity": "synthetic_unsupported_assertion",
            },
        },
    )
    campaign = json.loads(path.read_text(encoding="utf-8"))
    evaluation_root = path.parent.parent.parent
    pack_directory = (evaluation_root / campaign["pack_path"]).resolve()
    pack_manifest = json.loads((pack_directory / "manifest.json").read_text(encoding="utf-8"))
    fixture_path = (pack_directory / pack_manifest["fixture"]).resolve()
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    for case in fixture["cases"]:
        if case["case_id"] == "alpha-positive":
            case["pack"].update(model_id="ranker", corpus_id="shared-corpus")
        elif case["case_id"] == "beta-positive":
            case["pack"].update(model_id=" ranker ", corpus_id="shared-corpus")
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")

    result = evaluate_campaign(path)

    positive_quality = [row for row in result["quality_by_strata"] if row["role"] == "positive"]
    assert {(row["model_id"], row["corpus_id"]) for row in positive_quality} == {
        ("ranker", "shared-corpus"),
        (" ranker ", "shared-corpus"),
    }
    assert len({row["stratum_id"] for row in positive_quality}) == 2
    assert {row["stratum_id"] for row in positive_quality} == {
        row["stratum_id"] for row in result["strata"] if row["role"] == "positive"
    }
    assert {row["stratum_id"] for row in positive_quality} == {
        row["stratum_id"] for row in result["uncertainty"]["by_quality_stratum"]
        if row["role"] == "positive"
    }
    assert {(row["model_id"], row["corpus_id"]) for row in result["uncertainty"]["by_model_corpus"]} == {
        ("ranker", "shared-corpus"),
        (" ranker ", "shared-corpus"),
    }
    assert {row["model_id"] for row in result["strata"] if row["role"] == "positive"} == {
        "ranker", " ranker ",
    }


def test_strata_use_pack_identity_defaults_and_accept_whitespace_only_ids(tmp_path: Path) -> None:
    path = _copy_campaign(tmp_path)
    _annotate_case_strata(
        path,
        ["risk", "ambiguity"],
        {
            "alpha-positive": {"risk": " ", "ambiguity": "synthetic_clear"},
            "beta-positive": {"risk": " ", "ambiguity": "synthetic_clear"},
            "negative-no-evidence": {"risk": "synthetic_unknown", "ambiguity": "synthetic_no_evidence"},
            "negative-weak-evidence": {"risk": "synthetic_unknown", "ambiguity": "synthetic_weak_evidence"},
            "negative-unsupported-assertion": {
                "risk": "synthetic_unknown", "ambiguity": "synthetic_unsupported_assertion",
            },
        },
    )
    campaign = json.loads(path.read_text(encoding="utf-8"))
    evaluation_root = path.parent.parent.parent
    pack_directory = (evaluation_root / campaign["pack_path"]).resolve()
    pack_manifest_path = pack_directory / "manifest.json"
    pack_manifest = json.loads(pack_manifest_path.read_text(encoding="utf-8"))
    pack_manifest["metadata"].update(model_id=" ", corpus_id=" synthetic-corpus ")
    pack_manifest_path.write_text(json.dumps(pack_manifest), encoding="utf-8")
    defaults = pack_manifest["metadata"]
    fixture_path = (pack_directory / pack_manifest["fixture"]).resolve()
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    for case in fixture["cases"]:
        if case["case_id"] == "alpha-positive":
            case["pack"].pop("model_id")
            case["pack"].pop("corpus_id")
        elif case["case_id"] == "beta-positive":
            case["pack"].update(model_id="ranker", corpus_id="synthetic-corpus")
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")

    result = evaluate_campaign(path)

    positive_quality = [row for row in result["quality_by_strata"] if row["role"] == "positive"]
    expected_pairs = {
        (defaults["model_id"], defaults["corpus_id"]),
        ("ranker", "synthetic-corpus"),
    }
    assert {(row["model_id"], row["corpus_id"]) for row in positive_quality} == expected_pairs
    assert len({row["stratum_id"] for row in positive_quality}) == 2
    assert {row["stratum_id"] for row in positive_quality} == {
        row["stratum_id"] for row in result["strata"] if row["role"] == "positive"
    }
    assert {row["stratum_id"] for row in positive_quality} == {
        row["stratum_id"] for row in result["uncertainty"]["by_quality_stratum"]
        if row["role"] == "positive"
    }
    assert {(row["model_id"], row["corpus_id"]) for row in result["uncertainty"]["by_model_corpus"]} == expected_pairs
    whitespace_identity = next(row for row in positive_quality if row["model_id"] == " ")
    assert whitespace_identity["dimensions"]["risk"] == " "
    assert "/%20/%20synthetic-corpus%20/labels-" in whitespace_identity["stratum_id"]
    encoded_dimensions = whitespace_identity["stratum_id"].rsplit("/labels-", 1)[1]
    decoded_dimensions = base64.urlsafe_b64decode(
        encoded_dimensions + "=" * (-len(encoded_dimensions) % 4)
    ).decode("utf-8")
    assert json.loads(decoded_dimensions) == whitespace_identity["dimensions"]


def test_declared_strata_require_one_label_per_case_and_dimension(tmp_path: Path) -> None:
    path = _copy_campaign(tmp_path)
    campaign = json.loads(path.read_text(encoding="utf-8"))
    campaign["evaluation_design"]["strata_dimensions"] = ["risk", "ambiguity"]
    path.write_text(json.dumps(campaign), encoding="utf-8")

    result = evaluate_campaign(path)

    assert result["status"] == "FAIL"
    assert result["campaign_status"] == "NOT_RUN"
    assert "exactly the declared dimensions" in result["blockers"][0]


@pytest.mark.parametrize("successes,trials", [(0, 0), (0, 5), (5, 5), (2, 3)])
def test_wilson_interval_reports_descriptive_sample_counts(successes: int, trials: int) -> None:
    result = _wilson_interval(successes, trials)
    assert result["sample_size"] == trials
    if trials == 0:
        assert result["status"] == "INCONCLUSIVE"
        assert result["confidence_interval"] is None
    else:
        assert result["status"] == "DESCRIPTIVE"
        lower, upper = result["confidence_interval"]
        assert 0 <= lower <= result["estimate"] <= upper <= 1


@pytest.mark.parametrize("successes,trials", [(-1, 2), (3, 2), (1.5, 2), (True, 1)])
def test_wilson_interval_rejects_invalid_counts(successes, trials) -> None:
    with pytest.raises(CampaignError):
        _wilson_interval(successes, trials)


def test_campaign_with_configuration_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    path = _copy_campaign(tmp_path, lambda data: data["candidate"].update(configuration_sha256="0" * 64))

    result = evaluate_campaign(path)

    assert result["status"] == "FAIL"
    assert result["campaign_status"] == "NOT_RUN"
    assert result["eligibility_status"] == "BLOCKED"
    assert "configuration_sha256 does not match" in result["blockers"][0]


def test_campaign_pack_path_cannot_escape_evaluation_root(tmp_path: Path) -> None:
    path = _copy_campaign(tmp_path, lambda data: data.update(pack_path="../../../../etc"))

    result = evaluate_campaign(path)

    assert result["status"] == "FAIL"
    assert "inside the evaluation directory" in result["blockers"][0]


def test_campaign_split_rejects_case_reuse_between_groups(tmp_path: Path) -> None:
    def overlap_split(data):
        data["split"] = {
            "status": "ASSIGNED",
            "train_case_ids": ["alpha-positive"],
            "calibration_case_ids": ["alpha-positive"],
            "reserved_case_ids": [
                "beta-positive",
                "negative-no-evidence",
                "negative-weak-evidence",
                "negative-unsupported-assertion",
            ],
            "unassigned_case_ids": [],
        }

    path = _copy_campaign(tmp_path, overlap_split)

    result = evaluate_campaign(path)

    assert result["status"] == "FAIL"
    assert "multiple groups" in result["blockers"][0]


def test_pack_fixture_path_cannot_escape_pack_directory(tmp_path: Path) -> None:
    def corrupt_fixture_path(data):
        copied = tmp_path / "docs/evaluation/packs/rec22-local-v2/manifest.json"
        parsed = json.loads(copied.read_text(encoding="utf-8"))
        parsed["fixture"] = "../../../../etc/passwd"
        copied.write_text(json.dumps(parsed), encoding="utf-8")

    path = _copy_campaign(tmp_path, corrupt_fixture_path)

    result = evaluate_campaign(path)

    assert result["status"] == "FAIL"
    assert "fixture must remain inside" in result["blockers"][0]


def test_all_readiness_flags_never_claim_a_campaign_was_executed(tmp_path: Path) -> None:
    def approve_for_readiness_test(data):
        data["candidate"]["is_product_candidate"] = True
        data["corpus"].update(
            rights_status="APPROVED",
            authorized_for_product_evaluation=True,
            representative=True,
        )
        data["provider"]["status"] = "CONFIGURED"
        data["domain_review"].update(
            status="APPROVED",
            ambiguity_policy_status="APPROVED",
            risk_acceptance_status="APPROVED",
        )
        data["evaluation_design"]["minimum_cases_per_positive_stratum"] = 1
        data["split"] = {
            "status": "ASSIGNED",
            "train_case_ids": ["alpha-positive"],
            "calibration_case_ids": ["beta-positive"],
            "reserved_case_ids": [
                "negative-no-evidence",
                "negative-weak-evidence",
                "negative-unsupported-assertion",
            ],
            "unassigned_case_ids": [],
        }

    path = _copy_campaign(tmp_path, approve_for_readiness_test)
    _annotate_case_strata(
        path,
        ["risk", "ambiguity"],
        {
            "alpha-positive": {"risk": "synthetic_low", "ambiguity": "synthetic_clear"},
            "beta-positive": {"risk": "synthetic_low", "ambiguity": "synthetic_clear"},
            "negative-no-evidence": {"risk": "synthetic_unknown", "ambiguity": "synthetic_no_evidence"},
            "negative-weak-evidence": {"risk": "synthetic_unknown", "ambiguity": "synthetic_weak_evidence"},
            "negative-unsupported-assertion": {
                "risk": "synthetic_unknown", "ambiguity": "synthetic_unsupported_assertion",
            },
        },
    )

    result = evaluate_campaign(path)

    assert result["status"] == "PASS"
    assert result["eligibility_status"] == "READY_FOR_AUTHORIZED_RUN"
    assert result["campaign_status"] == "NOT_RUN"
    assert "No product retrieval candidate" in result["limitations"][1]


def test_product_campaign_without_ambiguity_labels_stays_blocked(tmp_path: Path) -> None:
    def configure_product_candidate(data):
        data["candidate"]["is_product_candidate"] = True
        data["corpus"].update(
            rights_status="APPROVED",
            authorized_for_product_evaluation=True,
            representative=True,
        )
        data["provider"]["status"] = "CONFIGURED"
        data["domain_review"].update(
            status="APPROVED",
            ambiguity_policy_status="APPROVED",
            risk_acceptance_status="APPROVED",
        )
        data["evaluation_design"]["minimum_cases_per_positive_stratum"] = 1
        data["split"] = {
            "status": "ASSIGNED",
            "train_case_ids": ["alpha-positive"],
            "calibration_case_ids": ["beta-positive"],
            "reserved_case_ids": [
                "negative-no-evidence",
                "negative-weak-evidence",
                "negative-unsupported-assertion",
            ],
            "unassigned_case_ids": [],
        }

    path = _copy_campaign(tmp_path, configure_product_candidate)
    _annotate_case_strata(
        path,
        ["risk"],
        {
            "alpha-positive": {"risk": "synthetic_low"},
            "beta-positive": {"risk": "synthetic_low"},
            "negative-no-evidence": {"risk": "synthetic_unknown"},
            "negative-weak-evidence": {"risk": "synthetic_unknown"},
            "negative-unsupported-assertion": {"risk": "synthetic_unknown"},
        },
    )

    result = evaluate_campaign(path)

    assert result["status"] == "PASS"
    assert result["campaign_status"] == "NOT_RUN"
    assert result["eligibility_status"] == "BLOCKED"
    assert any("must declare risk and ambiguity strata: ambiguity" in item for item in result["blockers"])
