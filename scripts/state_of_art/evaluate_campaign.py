#!/usr/bin/env python3
"""Inspect a retrieval campaign package without claiming a live evaluation.

This wrapper binds an offline pack to an explicit candidate/configuration,
strata, corpus-rights state and provider state. It reports sample uncertainty
for case-level Hit@1 and quality metrics per model/corpus pair, role or negative
expectation, and declared labels. Campaign eligibility remains separate from
pack status. It never calls a provider, retrieval service, API or network.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

try:
    from .evaluate_pack import FAIL, NOT_RUN, PASS, evaluate_pack
    from .evaluate_retrieval import evaluate_fixture, parse_k_values
    from .json_boundary import load_json
except ImportError:  # direct script execution with PYTHONPATH=scripts/state_of_art
    from evaluate_pack import FAIL, NOT_RUN, PASS, evaluate_pack
    from evaluate_retrieval import evaluate_fixture, parse_k_values
    from json_boundary import load_json


CAMPAIGN_SCHEMA_VERSION = "retrieval-campaign.v1"
RESULT_SCHEMA_VERSION = "retrieval-campaign-result.v4"
_ABSTENTION_EXPECTATIONS = {"no_evidence", "weak_evidence", "unsupported_assertion"}
_WILSON_Z_95 = 1.959963984540054
_STRATUM_DIMENSION = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
_METRIC_DETAIL_KEYS = {
    "case_id", "case_ids", "cases_without_citations", "per_case", "query",
    "source_mismatches", "text", "unobservable", "unresolved", "violations",
}


class CampaignError(ValueError):
    """A campaign manifest that cannot be safely or unambiguously inspected."""


def _text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CampaignError(f"{field} must be a non-empty string")
    return value.strip()


def _identity_text(value: Any, *, field: str) -> str:
    """Validate a Unicode identity string without changing its equality semantics."""
    if not isinstance(value, str) or not value:
        raise CampaignError(f"{field} must be a non-empty string")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise CampaignError(f"{field} must contain valid Unicode scalar values")
    return value


def _dimension_token(canonical_dimensions: str) -> str:
    encoded = base64.urlsafe_b64encode(canonical_dimensions.encode("utf-8"))
    return encoded.decode("ascii").rstrip("=")


def _load_object(path: Path, *, field: str) -> dict[str, Any]:
    try:
        value = load_json(path)
    except (OSError, ValueError) as exc:
        raise CampaignError(f"cannot read {field}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise CampaignError(f"{field} must be a JSON object")
    return dict(value)


def _configuration_digest(configuration: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        configuration,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _validate_candidate(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CampaignError("candidate must be an object")
    candidate = dict(value)
    candidate_id = _text(candidate.get("candidate_id"), field="candidate.candidate_id")
    source_revision = _text(candidate.get("source_revision"), field="candidate.source_revision")
    worktree_status = _text(candidate.get("worktree_status"), field="candidate.worktree_status")
    if not isinstance(candidate.get("is_product_candidate"), bool):
        raise CampaignError("candidate.is_product_candidate must be boolean")
    configuration = candidate.get("configuration")
    if not isinstance(configuration, Mapping) or not configuration:
        raise CampaignError("candidate.configuration must be a non-empty object")
    supplied_digest = _text(candidate.get("configuration_sha256"), field="candidate.configuration_sha256")
    observed_digest = _configuration_digest(configuration)
    if supplied_digest != observed_digest:
        raise CampaignError("candidate.configuration_sha256 does not match canonical configuration")
    return {
        "candidate_id": candidate_id,
        "source_revision": source_revision,
        "worktree_status": worktree_status,
        "is_product_candidate": candidate["is_product_candidate"],
        "configuration_sha256": observed_digest,
    }


def _resolve_pack(manifest_path: Path, reference: Any) -> Path:
    reference_text = _text(reference, field="pack_path")
    evaluation_root = manifest_path.parent.parent.parent.resolve()
    pack_path = (evaluation_root / reference_text).resolve()
    try:
        pack_path.relative_to(evaluation_root)
    except ValueError as exc:
        raise CampaignError("pack_path must remain inside the evaluation directory") from exc
    if not pack_path.is_dir() or not (pack_path / "manifest.json").is_file():
        raise CampaignError("pack_path must name a pack directory containing manifest.json")
    return pack_path


def _case_identity(case: Mapping[str, Any], index: int) -> str:
    return _text(case.get("case_id", case.get("id")), field=f"cases[{index}].case_id")


def _stratum_base_id(identity: Mapping[str, str]) -> str:
    role = identity.get("role")
    if role == "positive":
        components = (identity["model_id"], identity["corpus_id"])
    elif role == "negative":
        components = (identity["expectation"],)
    else:
        raise CampaignError("stratum identity role is unsupported")
    # Percent-encode each path component so embedded separators cannot alias another identity.
    encoded = (quote(component, safe="-._~") for component in components)
    return "/".join((role, *encoded))


def _pack_metadata_defaults(pack_manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    defaults = pack_manifest.get("metadata")
    if not isinstance(defaults, Mapping):
        raise CampaignError("pack manifest.metadata must be an object")
    return defaults


def _positive_model_corpus(
    metadata: Mapping[str, Any], defaults: Mapping[str, Any], *, index: int
) -> tuple[str, str]:
    model = _identity_text(
        metadata.get("model_id", defaults.get("model_id")),
        field=f"cases[{index}].pack.model_id",
    )
    corpus = _identity_text(
        metadata.get("corpus_id", defaults.get("corpus_id")),
        field=f"cases[{index}].pack.corpus_id",
    )
    return model, corpus


def _validate_strata_dimensions(
    evaluation_design: Mapping[str, Any], cases: list[dict[str, Any]]
) -> tuple[str, ...]:
    raw_dimensions = evaluation_design.get("strata_dimensions", [])
    if not isinstance(raw_dimensions, list):
        raise CampaignError("evaluation_design.strata_dimensions must be an array")
    dimensions = tuple(
        _text(value, field=f"evaluation_design.strata_dimensions[{index}]")
        for index, value in enumerate(raw_dimensions)
    )
    if len(set(dimensions)) != len(dimensions):
        raise CampaignError("evaluation_design.strata_dimensions must be unique")
    if any(_STRATUM_DIMENSION.fullmatch(value) is None for value in dimensions):
        raise CampaignError("strata dimension names must be lowercase snake_case identifiers")

    for index, case in enumerate(cases):
        metadata = case.get("pack")
        if not isinstance(metadata, Mapping):
            raise CampaignError(f"cases[{index}].pack must be an object")
        labels = metadata.get("strata", {})
        if not isinstance(labels, Mapping):
            raise CampaignError(f"cases[{index}].pack.strata must be an object")
        if not dimensions:
            if labels:
                raise CampaignError(
                    "case strata labels require evaluation_design.strata_dimensions"
                )
            continue
        if set(labels) != set(dimensions):
            raise CampaignError(
                f"cases[{index}].pack.strata must contain exactly the declared dimensions"
        )
        for dimension in dimensions:
            label = _identity_text(
                labels[dimension],
                field=f"cases[{index}].pack.strata.{dimension}",
            )
            if len(label) > 96 or any(ord(char) < 32 or ord(char) == 127 for char in label):
                raise CampaignError(
                    f"cases[{index}].pack.strata.{dimension} must be bounded plain text"
                )
    return dimensions


def _validate_split(value: Any, cases: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CampaignError("split must be an object")
    status = value.get("status")
    if status not in {"ASSIGNED", "NOT_ASSIGNED"}:
        raise CampaignError("split.status must be ASSIGNED or NOT_ASSIGNED")

    groups: dict[str, list[str]] = {}
    for name in ("train", "calibration", "reserved", "unassigned"):
        raw_ids = value.get(f"{name}_case_ids")
        if not isinstance(raw_ids, list):
            raise CampaignError(f"split.{name}_case_ids must be an array")
        groups[name] = [
            _text(case_id, field=f"split.{name}_case_ids[{index}]")
            for index, case_id in enumerate(raw_ids)
        ]

    expected = {_case_identity(case, index) for index, case in enumerate(cases)}
    seen: set[str] = set()
    for name, case_ids in groups.items():
        if len(case_ids) != len(set(case_ids)):
            raise CampaignError(f"split.{name}_case_ids contains duplicates")
        overlap = seen.intersection(case_ids)
        if overlap:
            raise CampaignError(f"split case ids appear in multiple groups: {sorted(overlap)}")
        seen.update(case_ids)
    if seen != expected:
        missing = sorted(expected - seen)
        unknown = sorted(seen - expected)
        raise CampaignError(f"split must account for every fixture case exactly once (missing={missing}, unknown={unknown})")

    if status == "ASSIGNED":
        if groups["unassigned"] or any(not groups[name] for name in ("train", "calibration", "reserved")):
            raise CampaignError("an ASSIGNED split needs non-empty train, calibration and reserved groups only")
    elif any(groups[name] for name in ("train", "calibration", "reserved")) or set(groups["unassigned"]) != expected:
        raise CampaignError("a NOT_ASSIGNED split must leave every fixture case unassigned")

    return {
        "status": status,
        "case_counts": {name: len(case_ids) for name, case_ids in groups.items()},
        "case_ids": groups,
        "interpretation": "case bookkeeping only; it does not establish an authorized or statistically powered sample",
    }


def _collect_strata(
    cases: list[dict[str, Any]],
    pack_result: Mapping[str, Any],
    pack_manifest: Mapping[str, Any],
    dimensions: tuple[str, ...],
) -> list[dict[str, Any]]:
    defaults = _pack_metadata_defaults(pack_manifest)
    grouped: dict[tuple[str, ...], list[str]] = defaultdict(list)
    labels: dict[tuple[str, ...], dict[str, Any]] = {}
    for index, case in enumerate(cases):
        case_id = _case_identity(case, index)
        metadata = case.get("pack")
        if not isinstance(metadata, Mapping):
            raise CampaignError(f"cases[{index}].pack must be an object")
        role = _text(metadata.get("role"), field=f"cases[{index}].pack.role")
        case_dimensions = {
            dimension: _identity_text(
                metadata["strata"][dimension],
                field=f"cases[{index}].pack.strata.{dimension}",
            )
            for dimension in dimensions
        }
        dimension_key = json.dumps(
            case_dimensions, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if role == "positive":
            model, corpus = _positive_model_corpus(metadata, defaults, index=index)
            base = ("positive", model, corpus)
            labels[base + (dimension_key,)] = {
                "role": role, "model_id": model, "corpus_id": corpus,
                "dimensions": case_dimensions,
            }
        elif role == "negative":
            expectation = _identity_text(metadata.get("expectation"), field=f"cases[{index}].pack.expectation")
            base = ("negative", expectation)
            labels[base + (dimension_key,)] = {
                "role": role, "expectation": expectation,
                "dimensions": case_dimensions,
            }
        else:
            raise CampaignError(f"cases[{index}].pack.role is unsupported")
        grouped[base + (dimension_key,)].append(case_id)

    negative_status = {
        item.get("case_id"): item.get("status")
        for item in pack_result.get("negative_cases", [])
        if isinstance(item, Mapping)
    }
    strata: list[dict[str, Any]] = []
    for group_key in sorted(grouped):
        group_labels = labels[group_key]
        case_ids = grouped[group_key]
        base_id = _stratum_base_id(group_labels)
        dimension_key = group_key[-1]
        stratum_id = base_id
        if dimensions:
            stratum_id = f"{base_id}/labels-{_dimension_token(dimension_key)}"
        row: dict[str, Any] = {
            "stratum_id": stratum_id,
            **{key: value for key, value in group_labels.items() if key != "dimensions"},
            "case_count": len(case_ids),
            "case_ids": case_ids,
            "interpretation": "descriptive fixture coverage; not a population estimate",
        }
        if dimensions:
            row["dimensions"] = group_labels["dimensions"]
        if group_labels["role"] == "negative":
            statuses = [negative_status.get(case_id, NOT_RUN) for case_id in case_ids]
            row["structural_fixture_status"] = (
                FAIL if FAIL in statuses else PASS if statuses and all(item == PASS for item in statuses) else NOT_RUN
            )
        strata.append(row)
    return strata


def _metric_summary(value: Any) -> Any:
    """Remove case-level identifiers and details from grouped metric reports."""
    if isinstance(value, Mapping):
        return {
            key: _metric_summary(item)
            for key, item in value.items()
            if key not in _METRIC_DETAIL_KEYS
        }
    if isinstance(value, list):
        if all(item is None or isinstance(item, (int, float, bool)) for item in value):
            return list(value)
        return {"item_count": len(value)}
    return value


def _quality_by_strata(
    cases: list[dict[str, Any]],
    pack_manifest: Mapping[str, Any],
    dimensions: tuple[str, ...],
) -> list[dict[str, Any]]:
    if not dimensions:
        return []
    defaults = _pack_metadata_defaults(pack_manifest)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    group_identity: dict[str, dict[str, str]] = {}
    dimension_values: dict[str, dict[str, str]] = {}
    for index, case in enumerate(cases):
        metadata = case.get("pack")
        if not isinstance(metadata, Mapping):
            raise CampaignError(f"cases[{index}].pack must be an object")
        role = _text(metadata.get("role"), field=f"cases[{index}].pack.role")
        labels = {
            name: _identity_text(
                metadata["strata"][name],
                field=f"cases[{index}].pack.strata.{name}",
            )
            for name in dimensions
        }
        if role == "positive":
            model, corpus = _positive_model_corpus(metadata, defaults, index=index)
            identity = {
                "role": role,
                "model_id": model,
                "corpus_id": corpus,
            }
        elif role == "negative":
            identity = {
                "role": role,
                "expectation": _identity_text(metadata.get("expectation"), field=f"cases[{index}].pack.expectation"),
            }
        else:
            raise CampaignError(f"cases[{index}].pack.role is unsupported")
        canonical = json.dumps(
            {"identity": identity, "dimensions": labels},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        grouped[canonical].append(case)
        group_identity[canonical] = identity
        dimension_values[canonical] = labels

    try:
        k_values = parse_k_values(pack_manifest.get("k_values"))
    except ValueError as exc:
        raise CampaignError(f"pack k_values are invalid: {exc}") from exc

    rows: list[dict[str, Any]] = []
    for canonical in sorted(grouped):
        group_cases = grouped[canonical]
        identity = group_identity[canonical]
        dimensions_canonical = json.dumps(
            dimension_values[canonical],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        base_id = _stratum_base_id(identity)
        dimension_token = _dimension_token(dimensions_canonical)
        result = evaluate_fixture(
            {"cases": group_cases, "k_values": list(k_values)},
            k_values=k_values,
        )
        metrics = result.get("metrics")
        metrics = metrics if isinstance(metrics, Mapping) else {}
        ranking = metrics.get("ranking")
        ranking = ranking if isinstance(ranking, Mapping) else {}
        rows.append({
            "stratum_id": f"{base_id}/labels-{dimension_token}",
            **identity,
            "dimensions": dimension_values[canonical],
            "case_count": len(group_cases),
            "positive_case_count": sum(case["pack"]["role"] == "positive" for case in group_cases),
            "negative_case_count": sum(case["pack"]["role"] == "negative" for case in group_cases),
            "case_ids": [_case_identity(case, index) for index, case in enumerate(group_cases)],
            "metrics": {
                name: _metric_summary(metrics.get(name, {"status": NOT_RUN}))
                for name in (
                    "ranking", "acl_leakage", "citation_source_coverage",
                    "citation_support", "latency",
                )
            },
            "retrieval_uncertainty": {
                "metric": "case-level Hit@1 among positive retrieval cases",
                **_hit_at_one_uncertainty(ranking.get("per_case")),
            },
            "abstention": {
                "expected_abstention_cases": sum(
                    case["pack"]["role"] == "negative" for case in group_cases
                ),
                "observed_response_dispositions": 0,
                "status": "NOT_MEASURED",
            },
            "evidence_type": "synthetic recorded observations only",
            "interpretation": (
                "descriptive metrics for this model/corpus pair or negative expectation and declared labels; "
                "not a population or product-quality estimate"
            ),
        })
    return rows


def _wilson_interval(successes: int, trials: int) -> dict[str, Any]:
    if isinstance(successes, bool) or isinstance(trials, bool) or not isinstance(successes, int) or not isinstance(trials, int):
        raise CampaignError("Wilson successes and trials must be integers")
    if trials < 0 or successes < 0 or successes > trials:
        raise CampaignError("Wilson counts must satisfy 0 <= successes <= trials")
    if trials == 0:
        return {
            "status": "INCONCLUSIVE",
            "successes": 0,
            "sample_size": 0,
            "estimate": None,
            "confidence_interval": None,
        }
    z2 = _WILSON_Z_95**2
    estimate = successes / trials
    denominator = 1.0 + z2 / trials
    center = (estimate + z2 / (2.0 * trials)) / denominator
    margin = (
        _WILSON_Z_95
        * math.sqrt(estimate * (1.0 - estimate) / trials + z2 / (4.0 * trials**2))
        / denominator
    )
    return {
        "status": "DESCRIPTIVE",
        "successes": successes,
        "sample_size": trials,
        "estimate": estimate,
        "confidence_interval": [max(0.0, center - margin), min(1.0, center + margin)],
    }


def _hit_at_one_uncertainty(rows: Any) -> dict[str, Any]:
    if not isinstance(rows, list):
        return _wilson_interval(0, 0)
    outcomes: list[int] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        hits = row.get("hit_at_k")
        if not isinstance(hits, Mapping):
            continue
        value = hits.get("1", hits.get(1))
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value not in (0, 1):
            continue
        outcomes.append(int(value))
    return _wilson_interval(sum(outcomes), len(outcomes))


def _uncertainty(
    pack_result: Mapping[str, Any], stratified_quality: list[dict[str, Any]]
) -> dict[str, Any]:
    aggregate = pack_result.get("aggregate")
    metrics = aggregate.get("metrics") if isinstance(aggregate, Mapping) else None
    ranking = metrics.get("ranking") if isinstance(metrics, Mapping) else None
    per_case = ranking.get("per_case") if isinstance(ranking, Mapping) else None
    groups = pack_result.get("per_model_corpus")
    by_group = []
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            group_metrics = group.get("metrics")
            group_ranking = group_metrics.get("ranking") if isinstance(group_metrics, Mapping) else None
            by_group.append({
                "model_id": group.get("model_id"),
                "corpus_id": group.get("corpus_id"),
                "case_count": group.get("case_count", 0),
                "hit_at_1": _hit_at_one_uncertainty(
                    group_ranking.get("per_case") if isinstance(group_ranking, Mapping) else None
                ),
            })
    return {
        "method": "Wilson score interval, two-sided 95%",
        "metric": "case-level Hit@1 among positive retrieval cases",
        "sample_unit": "query case",
        "overall": _hit_at_one_uncertainty(per_case),
        "by_model_corpus": by_group,
        "by_quality_stratum": [
            {
                "stratum_id": row["stratum_id"],
                "role": row["role"],
                **({"model_id": row["model_id"], "corpus_id": row["corpus_id"]} if row["role"] == "positive" else {}),
                **({"expectation": row["expectation"]} if row["role"] == "negative" else {}),
                "dimensions": row["dimensions"],
                "case_count": row["case_count"],
                "hit_at_1": row["retrieval_uncertainty"],
            }
            for row in stratified_quality
        ],
        "limitations": [
            "Intervals are descriptive and assume independent Bernoulli query outcomes.",
            "The synthetic sample is not representative and must not be used as a production-quality claim.",
            "Negative fixtures test retrieval/citation structure; they do not observe generated-answer abstention.",
        ],
    }


def _offline_fixture_checks(pack_result: Mapping[str, Any]) -> dict[str, Any]:
    aggregate = pack_result.get("aggregate")
    metrics = aggregate.get("metrics") if isinstance(aggregate, Mapping) else None
    if not isinstance(metrics, Mapping):
        metrics = {}

    def section(name: str) -> Mapping[str, Any]:
        value = metrics.get(name)
        return value if isinstance(value, Mapping) else {}

    ranking = section("ranking")
    hit_at_k = ranking.get("hit_at_k")
    recall_at_k = ranking.get("recall_at_k")
    hit_at_k = hit_at_k if isinstance(hit_at_k, Mapping) else {}
    recall_at_k = recall_at_k if isinstance(recall_at_k, Mapping) else {}
    source_support = section("citation_source_coverage")
    citation_support = section("citation_support")
    return {
        "interpretation": "checked-in synthetic recorded observations only; these are not product runtime measurements",
        "ranking": {
            "hit_at_1": hit_at_k.get("1"),
            "recall_at_2": recall_at_k.get("2"),
        },
        "source_support": {
            "status": source_support.get("status", NOT_RUN),
            "citation_coverage": source_support.get("citation_coverage"),
            "checksum_coverage": source_support.get("checksum_coverage"),
        },
        "citation_support": {
            "status": citation_support.get("status", NOT_RUN),
            "precision": citation_support.get("citation_precision"),
            "recall": citation_support.get("citation_recall"),
            "completeness": citation_support.get("citation_completeness"),
            "unsupported_claim_rate": citation_support.get("unsupported_claim_rate"),
            "faithfulness": citation_support.get("faithfulness"),
        },
        "tenant_isolation": section("acl_leakage"),
    }


def evaluate_campaign(manifest_path: str | Path) -> dict[str, Any]:
    """Inspect a campaign package and keep offline evidence separate from readiness."""
    path = Path(manifest_path).resolve()
    try:
        manifest = _load_object(path, field="campaign manifest")
        if manifest.get("schema_version") != CAMPAIGN_SCHEMA_VERSION:
            raise CampaignError("campaign schema_version is invalid")
        campaign_id = _text(manifest.get("campaign_id"), field="campaign_id")
        candidate = _validate_candidate(manifest.get("candidate"))
        pack_path = _resolve_pack(path, manifest.get("pack_path"))
        corpus = manifest.get("corpus")
        provider = manifest.get("provider")
        domain_review = manifest.get("domain_review")
        if not isinstance(corpus, Mapping) or not isinstance(provider, Mapping) or not isinstance(domain_review, Mapping):
            raise CampaignError("corpus, provider and domain_review must be objects")

        pack_manifest = _load_object(pack_path / "manifest.json", field="pack manifest")
        fixture_ref = _text(pack_manifest.get("fixture"), field="pack.fixture")
        fixture_path = (pack_path / fixture_ref).resolve()
        try:
            fixture_path.relative_to(pack_path.resolve())
        except ValueError as exc:
            raise CampaignError("pack fixture must remain inside the pack directory") from exc
        fixture = _load_object(fixture_path, field="pack fixture")
        pack_result = evaluate_pack(pack_path)
        if pack_result.get("status") != PASS:
            raise CampaignError(f"offline pack evaluation is not PASS: {pack_result.get('status')}")
        raw_cases = fixture.get("cases")
        if not isinstance(raw_cases, list):
            raise CampaignError("pack fixture cases must be an array")
        cases = [dict(item) for item in raw_cases if isinstance(item, Mapping)]
        if len(cases) != len(raw_cases):
            raise CampaignError("every pack fixture case must be an object")
        split = _validate_split(manifest.get("split"), cases)
        evaluation_design = manifest.get("evaluation_design")
        if not isinstance(evaluation_design, Mapping):
            raise CampaignError("evaluation_design must be an object")
        minimum_positive_cases = evaluation_design.get("minimum_cases_per_positive_stratum")
        if isinstance(minimum_positive_cases, bool) or not isinstance(minimum_positive_cases, int) or minimum_positive_cases < 1:
            raise CampaignError("evaluation_design.minimum_cases_per_positive_stratum must be a positive integer")
        strata_dimensions = _validate_strata_dimensions(evaluation_design, cases)
        strata = _collect_strata(cases, pack_result, pack_manifest, strata_dimensions)
        quality_by_strata = _quality_by_strata(cases, pack_manifest, strata_dimensions)

        blockers: list[str] = []
        if corpus.get("rights_status") != "APPROVED" or corpus.get("authorized_for_product_evaluation") is not True:
            blockers.append("representative corpus rights and evaluation authorization are not approved")
        if corpus.get("representative") is not True:
            blockers.append("the corpus has not been approved as representative for the target population")
        if provider.get("status") != "CONFIGURED":
            blockers.append("an authorized retrieval/model provider has not been configured")
        if domain_review.get("status") != "APPROVED":
            blockers.append("domain review and acceptance thresholds are not approved")
        if domain_review.get("ambiguity_policy_status") != "APPROVED":
            blockers.append("ambiguous-case policy and adjudication are not approved")
        if domain_review.get("risk_acceptance_status") != "APPROVED":
            blockers.append("domain risk acceptance is not approved")
        if candidate["is_product_candidate"] is not True:
            blockers.append("the recorded fixture is not an identified product candidate")
        missing_dimensions = {"risk", "ambiguity"} - set(strata_dimensions)
        if missing_dimensions:
            blockers.append(
                "product evaluation must declare risk and ambiguity strata: "
                + ", ".join(sorted(missing_dimensions))
            )
        if split["status"] != "ASSIGNED":
            blockers.append("train/calibration/reserved split is not assigned for an authorized campaign")
        undersized = [
            row["stratum_id"] for row in strata
            if row.get("role") == "positive" and row["case_count"] < minimum_positive_cases
        ]
        if undersized:
            blockers.append(
                "positive model/corpus/dimension strata are below the declared minimum sample size: "
                + ", ".join(undersized)
            )

        negative_by_id = {
            item.get("case_id"): item
            for item in pack_result.get("negative_cases", [])
            if isinstance(item, Mapping)
        }
        abstention_expectations = []
        for index, case in enumerate(cases):
            metadata = case.get("pack")
            if not isinstance(metadata, Mapping) or metadata.get("role") != "negative":
                continue
            expectation = metadata.get("expectation")
            if expectation not in _ABSTENTION_EXPECTATIONS:
                continue
            case_id = _case_identity(case, index)
            structural = negative_by_id.get(case_id, {})
            abstention_expectations.append({
                "case_id": case_id,
                "expectation": expectation,
                **({"dimensions": {
                    name: metadata["strata"][name] for name in strata_dimensions
                }} if strata_dimensions else {}),
                "expected_disposition": "ABSTAIN",
                "observed_response_disposition": "NOT_MEASURED",
                "structural_fixture_status": structural.get("status", NOT_RUN),
                "evidence_type": "synthetic retrieval/citation structure only",
            })

        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "campaign_id": campaign_id,
            "status": PASS,
            "campaign_status": NOT_RUN,
            "eligibility_status": "BLOCKED" if blockers else "READY_FOR_AUTHORIZED_RUN",
            "blockers": blockers,
            "evaluation_design": {
                "minimum_cases_per_positive_stratum": minimum_positive_cases,
                "strata_dimensions": list(strata_dimensions),
            },
            "candidate": candidate,
            "corpus": {
                "corpus_id": corpus.get("corpus_id"),
                "version": corpus.get("version"),
                "rights_status": corpus.get("rights_status"),
                "authorized_for_product_evaluation": corpus.get("authorized_for_product_evaluation"),
            },
            "provider_status": provider.get("status"),
            "domain_review_status": domain_review.get("status"),
            "pack": {
                "pack_id": pack_result["pack"]["pack_id"],
                "version": pack_result["pack"]["version"],
                "status": pack_result["status"],
                "case_count": pack_result["pack"]["case_count"],
                "positive_case_count": pack_result["pack"]["positive_case_count"],
                "negative_case_count": pack_result["pack"]["negative_case_count"],
            },
            "offline_fixture_checks": _offline_fixture_checks(pack_result),
            "split": split,
            "strata": strata,
            "quality_by_strata": quality_by_strata,
            "abstention_expectations": abstention_expectations,
            "uncertainty": _uncertainty(pack_result, quality_by_strata),
            "limitations": [
                "PASS means the local synthetic-pack harness ran successfully; campaign_status remains NOT_RUN.",
                "No product retrieval candidate, licensed corpus, live provider or generated answer was evaluated.",
                "No corpus representativeness, independent domain review, statistical power, production quality or release claim is made.",
            ],
        }
    except (CampaignError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "campaign_id": None,
            "status": FAIL,
            "campaign_status": NOT_RUN,
            "eligibility_status": "BLOCKED",
            "blockers": [str(exc)],
            "limitations": ["A malformed campaign package fails closed and produces no campaign verdict."],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, help="campaign manifest path")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    args = parser.parse_args(argv)
    result = evaluate_campaign(args.campaign)
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if result.get("status") == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
