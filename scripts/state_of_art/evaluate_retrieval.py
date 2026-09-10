#!/usr/bin/env python3
"""Evaluate recorded retrieval observations without contacting a provider.

The evaluator deliberately consumes JSON/JSONL observations instead of importing
the API or retrieval packages.  This keeps the harness usable when optional
dependencies, vector stores, credentials, or application services are absent.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from scripts.state_of_art.json_boundary import loads_json
except ImportError:  # pragma: no cover - direct script execution fallback.
    from json_boundary import loads_json


RESULT_SCHEMA_VERSION = "retrieval-evaluation-result.v1"
FIXTURE_SCHEMA_VERSION = "retrieval-evaluation.v1"
DEFAULT_K_VALUES = (1, 3, 5)

PASS = "PASS"
FAIL = "FAIL"
NOT_RUN = "NOT_RUN"
INCONCLUSIVE = "INCONCLUSIVE"

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_INCONCLUSIVE = 2
_CLAIM_SUPPORT_SOURCE = "approved_claim_support"


@dataclass(frozen=True)
class LoadedFixture:
    """Parsed fixture envelope before case-level validation."""

    cases: list[Any]
    format: str
    metadata: dict[str, Any]
    k_values: tuple[int, ...] | None = None


@dataclass(frozen=True)
class _Case:
    case_id: str
    query: str
    tenant_id: Any
    workspace_id: Any
    allowed_collection_ids: tuple[str, ...] | None
    results: list[dict[str, Any]]
    relevant_ids: tuple[str, ...] | None
    denied_ids: tuple[str, ...]
    citations: list[Any] | None
    claims: list[dict[str, Any]] | None
    latency_values_ms: tuple[float, ...]
    corpus: list[dict[str, Any]]


def _metric(status: str, *, reason: str | None = None, **fields: Any) -> dict[str, Any]:
    value: dict[str, Any] = {"status": status}
    if reason:
        value["reason"] = reason
    value.update(fields)
    return value


def _status_join(statuses: Sequence[str]) -> str:
    """Join statuses without allowing missing evidence to look like a pass."""

    if FAIL in statuses:
        return FAIL
    if INCONCLUSIVE in statuses:
        return INCONCLUSIVE
    if PASS in statuses:
        return PASS
    return NOT_RUN


def _round_ratio(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)


def _round_ms(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 3)


def _loads(text: str) -> Any:
    return loads_json(text)


def parse_k_values(value: Any) -> tuple[int, ...]:
    """Parse positive, unique k values from JSON or CLI-shaped input."""

    if value is None:
        return DEFAULT_K_VALUES

    raw_values: list[Any] = []
    if isinstance(value, str):
        raw_values.extend(part for part in value.split(",") if part.strip())
    elif isinstance(value, bool):
        raise ValueError("k values must be positive integers")
    elif isinstance(value, int):
        raw_values.append(value)
    elif isinstance(value, Sequence):
        for part in value:
            if isinstance(part, str) and "," in part:
                raw_values.extend(piece for piece in part.split(",") if piece.strip())
            else:
                raw_values.append(part)
    else:
        raise ValueError("k values must be a positive integer or a list of positive integers")

    parsed: set[int] = set()
    for raw in raw_values:
        if isinstance(raw, bool):
            raise ValueError("k values must be positive integers")
        if isinstance(raw, str):
            try:
                parsed_value = int(raw.strip())
            except ValueError as exc:
                raise ValueError(f"invalid k value: {raw!r}") from exc
        elif isinstance(raw, int):
            parsed_value = raw
        else:
            raise ValueError(f"invalid k value: {raw!r}")
        if parsed_value <= 0:
            raise ValueError("k values must be positive integers")
        parsed.add(parsed_value)

    if not parsed:
        raise ValueError("at least one k value is required")
    return tuple(sorted(parsed))


def _parse_jsonl(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = _loads(line)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"invalid JSONL at line {line_number}: {exc}") from exc
        if not isinstance(value, Mapping):
            raise ValueError(f"JSONL line {line_number} must contain an object")
        rows.append(dict(value))
    return rows


def _looks_like_case(value: Mapping[str, Any]) -> bool:
    return any(key in value for key in ("query", "results", "retrieved", "items", "evidence"))


def _fixture_from_value(value: Any, *, format: str) -> LoadedFixture:
    if isinstance(value, Mapping):
        if "cases" in value:
            raw_cases = value["cases"]
        elif "queries" in value:
            raw_cases = value["queries"]
        elif _looks_like_case(value):
            raw_cases = [value]
        else:
            raise ValueError("JSON fixture object must contain 'cases' or 'queries'")
        if not isinstance(raw_cases, list):
            raise ValueError("fixture cases must be a JSON array")
        raw_k_values = value.get("k_values", value.get("ks", value.get("k")))
        k_values = parse_k_values(raw_k_values) if raw_k_values is not None else None
        metadata = {
            "schema_version": value.get("schema_version"),
            "provider": value.get("provider", "offline-fixture"),
            "description": value.get("description"),
        }
        return LoadedFixture(
            cases=list(raw_cases),
            format=format,
            metadata=metadata,
            k_values=k_values,
        )

    if isinstance(value, list):
        return LoadedFixture(cases=list(value), format=format, metadata={})

    raise ValueError("fixture root must be a JSON object or array")


def load_fixture(path: str | Path) -> LoadedFixture:
    """Load a JSON or JSONL fixture using only the Python standard library."""

    fixture_path = Path(path)
    text = fixture_path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError("fixture is empty")

    suffix = fixture_path.suffix.lower()
    if suffix in {".jsonl", ".ndjson"}:
        return LoadedFixture(
            cases=_parse_jsonl(text),
            format="jsonl",
            metadata={},
        )

    try:
        value = _loads(text)
    except (json.JSONDecodeError, ValueError) as json_error:
        # A suffix is not a reliable contract in scratch/evaluation folders.
        # Accept JSONL as a fallback while retaining a useful parse error if it
        # is neither format.
        try:
            rows = _parse_jsonl(text)
        except ValueError as jsonl_error:
            raise ValueError(f"invalid JSON fixture: {json_error}; JSONL fallback: {jsonl_error}") from json_error
        return LoadedFixture(cases=rows, format="jsonl", metadata={})
    return _fixture_from_value(value, format="json")


def _nonempty_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _pick(mappings: Sequence[Mapping[str, Any]], key: str) -> Any:
    for mapping in mappings:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _id_list(value: Any, *, path: str, errors: list[str]) -> tuple[str, ...] | None:
    if value is None:
        return None
    raw_values: list[Any]
    if isinstance(value, str):
        raw_values = [value]
    elif isinstance(value, list):
        raw_values = value
    else:
        errors.append(f"{path} must be a string or array of strings")
        return tuple()

    result: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_values):
        identifier = _nonempty_text(raw)
        if identifier is None:
            errors.append(f"{path}[{index}] must be a non-empty string")
            continue
        if identifier not in seen:
            result.append(identifier)
            seen.add(identifier)
    return tuple(result)


def _claim_list(value: Any, *, path: str, errors: list[str]) -> list[dict[str, Any]] | None:
    """Validate the versioned claim observation contract.

    Claim support is intentionally annotation-driven.  This evaluator does not
    infer entailment from a query or silently turn lexical overlap into a
    faithfulness claim.  A claim may provide output ``citation_ids``, approved
    ``reference_citation_ids``, and an optional reviewed ``supported`` value.
    Missing fields remain observable as INCONCLUSIVE in the metric report.
    """

    if value is None:
        return None
    if not isinstance(value, list):
        errors.append(f"{path} must be an array")
        return []

    claims: list[dict[str, Any]] = []
    for index, raw_claim in enumerate(value):
        claim_path = f"{path}[{index}]"
        if not isinstance(raw_claim, Mapping):
            errors.append(f"{claim_path} must be an object")
            continue

        claim = dict(raw_claim)
        claim_id = _nonempty_text(claim.get("claim_id", claim.get("id")))
        if claim_id is None:
            errors.append(f"{claim_path}.claim_id must be a non-empty string")
            claim_id = f"claim-{index + 1}"
        text = _nonempty_text(claim.get("text", claim.get("claim")))
        if text is None:
            errors.append(f"{claim_path}.text must be a non-empty string")

        for field_name, aliases in (
            ("citation_ids", ("citation_ids", "cited_ids", "support_ids")),
            (
                "reference_citation_ids",
                ("reference_citation_ids", "gold_citation_ids", "expected_support_ids"),
            ),
        ):
            present = next((alias for alias in aliases if alias in claim), None)
            if present is None:
                claim[field_name] = None
                continue
            claim[field_name] = _id_list(
                claim[present],
                path=f"{claim_path}.{present}",
                errors=errors,
            )

        if "supported" in claim and not isinstance(claim["supported"], bool):
            errors.append(f"{claim_path}.supported must be a boolean when supplied")
            claim["supported"] = None
        elif "supported" not in claim:
            claim["supported"] = None

        # Faithfulness is an authority-owned annotation.  A boolean is useful
        # for reviewed yes/no labels; a bounded numeric value supports graded
        # review.  The evaluator never derives it from lexical overlap or
        # citation identity, because neither establishes entailment.
        faithfulness_key = next(
            (alias for alias in ("faithfulness", "faithful") if alias in claim),
            None,
        )
        if faithfulness_key is None:
            claim["faithfulness"] = None
        else:
            raw_faithfulness = claim[faithfulness_key]
            if isinstance(raw_faithfulness, bool):
                claim["faithfulness"] = 1.0 if raw_faithfulness else 0.0
            elif isinstance(raw_faithfulness, (int, float)) and not isinstance(raw_faithfulness, bool):
                faithfulness = float(raw_faithfulness)
                if not math.isfinite(faithfulness) or not 0.0 <= faithfulness <= 1.0:
                    errors.append(f"{claim_path}.{faithfulness_key} must be a finite number between zero and one")
                    claim["faithfulness"] = None
                else:
                    claim["faithfulness"] = faithfulness
            else:
                errors.append(f"{claim_path}.{faithfulness_key} must be a boolean or bounded number")
                claim["faithfulness"] = None

        claim["claim_id"] = claim_id
        claim["text"] = text or ""
        claims.append(claim)
    return claims


def _number(value: Any, *, path: str, errors: list[str], minimum: float = 0.0) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{path} must be a finite number")
        return None
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < minimum:
        errors.append(f"{path} must be a finite number >= {minimum:g}")
        return None
    return numeric


def _normalise_case(raw: Any, index: int, errors: list[str]) -> _Case | None:
    path = f"cases[{index}]"
    if not isinstance(raw, Mapping):
        errors.append(f"{path} must be an object")
        return None

    case_id = _nonempty_text(raw.get("case_id", raw.get("id"))) or f"case-{index + 1}"
    query = _nonempty_text(raw.get("query"))
    if query is None:
        errors.append(f"{path}.query must be a non-empty string")
        query = ""

    raw_context = raw.get("context", {})
    if raw_context is None:
        raw_context = {}
    if not isinstance(raw_context, Mapping):
        errors.append(f"{path}.context must be an object")
        raw_context = {}
    raw_metadata = raw.get("metadata", {})
    if raw_metadata is None:
        raw_metadata = {}
    if not isinstance(raw_metadata, Mapping):
        errors.append(f"{path}.metadata must be an object")
        raw_metadata = {}

    scope_sources = (raw, raw_context, raw_metadata)
    tenant_id = _pick(scope_sources, "tenant_id")
    workspace_id = _pick(scope_sources, "workspace_id")
    raw_allowed = _pick(scope_sources, "allowed_collection_ids")
    allowed_collection_ids = _id_list(
        raw_allowed,
        path=f"{path}.allowed_collection_ids",
        errors=errors,
    )

    result_key = next(
        (key for key in ("results", "retrieved", "items", "evidence") if key in raw),
        None,
    )
    raw_results = raw.get(result_key, []) if result_key else []
    results: list[dict[str, Any]] = []
    if not isinstance(raw_results, list):
        errors.append(f"{path}.{result_key or 'results'} must be an array")
    else:
        for result_index, result in enumerate(raw_results):
            if not isinstance(result, Mapping):
                errors.append(f"{path}.{result_key or 'results'}[{result_index}] must be an object")
                continue
            item = dict(result)
            if "rank" in item and item["rank"] is not None:
                rank = item["rank"]
                if isinstance(rank, bool) or not isinstance(rank, int) or rank < 0:
                    errors.append(
                        f"{path}.{result_key or 'results'}[{result_index}].rank must be a non-negative integer"
                    )
            results.append(item)

    relevant_value = next(
        (raw[key] for key in ("relevant_ids", "expected_relevant_ids", "gold_ids") if key in raw),
        None,
    )
    relevant_ids = _id_list(relevant_value, path=f"{path}.relevant_ids", errors=errors)
    denied_value = next(
        (raw[key] for key in ("denied_ids", "expected_not_returned_ids") if key in raw),
        [],
    )
    denied_ids = _id_list(denied_value, path=f"{path}.denied_ids", errors=errors) or tuple()

    citation_key = next(
        (key for key in ("citations", "citation_ids") if key in raw),
        None,
    )
    citations: list[Any] | None = None
    if citation_key is not None:
        raw_citations = raw[citation_key]
        if isinstance(raw_citations, list):
            citations = list(raw_citations)
        elif isinstance(raw_citations, str):
            citations = [raw_citations]
        else:
            errors.append(f"{path}.{citation_key} must be an array or string")
            citations = []

    claims = _claim_list(raw.get("claims"), path=f"{path}.claims", errors=errors)

    raw_latency: Any = None
    if "latency_samples_ms" in raw:
        raw_latency = raw["latency_samples_ms"]
    elif "latency_ms" in raw:
        raw_latency = raw["latency_ms"]
    if raw_latency is None:
        latency_values: list[float] = []
    else:
        raw_latency_values = raw_latency if isinstance(raw_latency, list) else [raw_latency]
        latency_values = []
        for latency_index, latency in enumerate(raw_latency_values):
            parsed_latency = _number(
                latency,
                path=f"{path}.latency_ms[{latency_index}]",
                errors=errors,
            )
            if parsed_latency is not None:
                latency_values.append(parsed_latency)

    raw_corpus = raw.get("corpus", [])
    corpus: list[dict[str, Any]] = []
    if raw_corpus is None:
        raw_corpus = []
    if not isinstance(raw_corpus, list):
        errors.append(f"{path}.corpus must be an array")
    else:
        for corpus_index, record in enumerate(raw_corpus):
            if not isinstance(record, Mapping):
                errors.append(f"{path}.corpus[{corpus_index}] must be an object")
                continue
            corpus.append(dict(record))

    return _Case(
        case_id=case_id,
        query=query,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        allowed_collection_ids=allowed_collection_ids,
        results=results,
        relevant_ids=relevant_ids,
        denied_ids=denied_ids,
        citations=citations,
        claims=claims,
        latency_values_ms=tuple(latency_values),
        corpus=corpus,
    )


def _identifiers(value: Any) -> set[str]:
    if isinstance(value, str):
        identifier = _nonempty_text(value)
        return {identifier} if identifier else set()
    if not isinstance(value, Mapping):
        return set()
    identifiers: set[str] = set()
    for key in ("evidence_id", "chunk_id", "document_id", "id"):
        identifier = _nonempty_text(value.get(key))
        if identifier:
            identifiers.add(identifier)
    return identifiers


def _ordered_identity_values(value: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("chunk_id", "evidence_id", "document_id", "id"):
        identifier = _nonempty_text(value.get(key))
        if identifier and identifier not in values:
            values.append(identifier)
    return values


def _ordered_results(results: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    if not any(isinstance(item.get("rank"), int) and not isinstance(item.get("rank"), bool) for item in results):
        return list(results)

    indexed = list(enumerate(results))
    indexed.sort(
        key=lambda pair: (
            0,
            pair[1]["rank"],
            pair[0],
        )
        if isinstance(pair[1].get("rank"), int) and not isinstance(pair[1].get("rank"), bool)
        else (1, pair[0]),
    )
    return [item for _, item in indexed]


def _ranking_metrics(cases: Sequence[_Case], k_values: tuple[int, ...]) -> dict[str, Any]:
    if not cases:
        return _metric(
            NOT_RUN,
            reason="no fixture cases were available",
            k_values=list(k_values),
            hit_at_k={},
            recall_at_k={},
            per_case=[],
        )

    eligible: list[_Case] = []
    excluded: list[dict[str, str]] = []
    for case in cases:
        if case.relevant_ids is None:
            excluded.append({"case_id": case.case_id, "reason": "relevant_ids were not supplied"})
        elif not case.relevant_ids:
            excluded.append({"case_id": case.case_id, "reason": "relevant_ids were empty; recall is undefined"})
        else:
            eligible.append(case)

    if not eligible:
        blank = {
            str(k): _metric(
                INCONCLUSIVE,
                reason="no case contained non-empty relevance annotations",
                value=None,
                numerator=0,
                denominator=0,
            )
            for k in k_values
        }
        return _metric(
            INCONCLUSIVE,
            reason="relevance annotations are required for hit@k and recall@k",
            k_values=list(k_values),
            eligible_cases=0,
            excluded_cases=excluded,
            hit_at_k=blank,
            recall_at_k={key: dict(value) for key, value in blank.items()},
            per_case=[],
        )

    per_case: list[dict[str, Any]] = []
    for case in eligible:
        expected = set(case.relevant_ids or ())
        ordered = _ordered_results(case.results)
        case_row: dict[str, Any] = {"case_id": case.case_id, "relevant_count": len(expected)}
        case_hits: dict[str, int] = {}
        case_recalls: dict[str, float] = {}
        for k in k_values:
            returned_ids: set[str] = set()
            for result in ordered[:k]:
                returned_ids.update(_identifiers(result))
            matched = expected.intersection(returned_ids)
            case_hits[str(k)] = 1 if matched else 0
            case_recalls[str(k)] = _round_ratio(len(matched) / len(expected)) or 0.0
        case_row["hit_at_k"] = case_hits
        case_row["recall_at_k"] = case_recalls
        per_case.append(case_row)

    status = INCONCLUSIVE if excluded else PASS
    hit_values: dict[str, dict[str, Any]] = {}
    recall_values: dict[str, dict[str, Any]] = {}
    for k in k_values:
        key = str(k)
        hit_numerator = sum(row["hit_at_k"][key] for row in per_case)
        recall_sum = sum(row["recall_at_k"][key] for row in per_case)
        matched_total = sum(
            round(row["recall_at_k"][key] * row["relevant_count"])
            for row in per_case
        )
        relevant_total = sum(row["relevant_count"] for row in per_case)
        hit_values[key] = _metric(
            status,
            value=_round_ratio(hit_numerator / len(per_case)),
            numerator=hit_numerator,
            denominator=len(per_case),
        )
        recall_values[key] = _metric(
            status,
            value=_round_ratio(recall_sum / len(per_case)),
            numerator=matched_total,
            denominator=relevant_total,
            aggregation="macro_over_queries",
        )

    result = _metric(
        status,
        k_values=list(k_values),
        eligible_cases=len(eligible),
        excluded_cases=excluded,
        hit_at_k=hit_values,
        recall_at_k=recall_values,
        per_case=per_case,
        aggregation="macro_over_queries",
    )
    # The symbolic spellings are convenient for downstream JSON consumers and
    # make the metric names explicit without changing the canonical fields.
    result["hit@k"] = result["hit_at_k"]
    result["recall@k"] = result["recall_at_k"]
    return result


def _corpus_index(corpus: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for record in corpus:
        for identifier in _ordered_identity_values(record):
            index.setdefault(identifier, record)
    return index


def _resolved_scope(value: Any, corpus: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    if isinstance(value, Mapping):
        for identifier in _ordered_identity_values(value):
            record = corpus.get(identifier)
            if record is not None:
                resolved = dict(record)
                break
        for key, item in value.items():
            if item is not None:
                resolved[key] = item
    elif isinstance(value, str):
        record = corpus.get(value)
        if record is not None:
            resolved = dict(record)
    return resolved


def _valid_scope_context(case: _Case) -> bool:
    return (
        isinstance(case.tenant_id, str)
        and bool(case.tenant_id.strip())
        and isinstance(case.workspace_id, str)
        and bool(case.workspace_id.strip())
        and case.allowed_collection_ids is not None
    )


def _acl_metrics(cases: Sequence[_Case]) -> dict[str, Any]:
    if not cases:
        return _metric(
            NOT_RUN,
            reason="no fixture cases were available",
            cases_evaluated=0,
            violations=[],
            unobservable=[],
            leakage_count=0,
        )

    violations: list[dict[str, Any]] = []
    unobservable: list[dict[str, Any]] = []
    cases_with_context = 0
    cases_with_unobservable_scope = 0
    returned_items = 0
    denied_assertions = 0

    for case in cases:
        if not _valid_scope_context(case):
            unobservable.append({
                "case_id": case.case_id,
                "reason": "tenant_id, workspace_id, and allowed_collection_ids are required",
            })
            cases_with_unobservable_scope += 1
            continue

        cases_with_context += 1
        case_unobservable = False
        corpus = _corpus_index(case.corpus)
        allowed = set(case.allowed_collection_ids or ())
        denied = set(case.denied_ids)
        denied_assertions += len(denied)

        def check_scope(value: Any, *, kind: str, position: int) -> None:
            nonlocal case_unobservable
            scope = _resolved_scope(value, corpus)
            identifiers = sorted(_identifiers(value))
            for dimension, expected in (
                ("tenant_id", case.tenant_id),
                ("workspace_id", case.workspace_id),
            ):
                actual = _nonempty_text(scope.get(dimension))
                if actual is None:
                    unobservable.append({
                        "case_id": case.case_id,
                        "kind": kind,
                        "position": position,
                        "identifiers": identifiers,
                        "reason": f"{dimension} was not observable in result or corpus",
                    })
                    case_unobservable = True
                elif actual != expected:
                    violations.append({
                        "case_id": case.case_id,
                        "kind": kind,
                        "position": position,
                        "identifiers": identifiers,
                        "dimension": dimension,
                        "expected": expected,
                        "actual": actual,
                    })

            collection = _nonempty_text(scope.get("collection_id"))
            if collection is None:
                unobservable.append({
                    "case_id": case.case_id,
                    "kind": kind,
                    "position": position,
                    "identifiers": identifiers,
                    "reason": "collection_id was not observable in result or corpus",
                })
                case_unobservable = True
            elif "*" not in allowed and collection not in allowed:
                violations.append({
                    "case_id": case.case_id,
                    "kind": kind,
                    "position": position,
                    "identifiers": identifiers,
                    "dimension": "collection_id",
                    "expected": sorted(allowed),
                    "actual": collection,
                })

            if denied.intersection(_identifiers(value)):
                violations.append({
                    "case_id": case.case_id,
                    "kind": kind,
                    "position": position,
                    "identifiers": sorted(denied.intersection(_identifiers(value))),
                    "dimension": "denied_id",
                    "expected": "not returned",
                    "actual": "returned",
                })

        for position, result in enumerate(case.results):
            returned_items += 1
            if not _identifiers(result):
                unobservable.append({
                    "case_id": case.case_id,
                    "kind": "result",
                    "position": position,
                    "reason": "result has no document_id, chunk_id, evidence_id, or id",
                })
                case_unobservable = True
            check_scope(result, kind="result", position=position)

        for position, citation in enumerate(case.citations or []):
            check_scope(citation, kind="citation", position=position)

        if case_unobservable:
            cases_with_unobservable_scope += 1

    if violations:
        status = FAIL
    elif not cases_with_context:
        status = INCONCLUSIVE
    elif unobservable:
        status = INCONCLUSIVE
    else:
        status = PASS

    return _metric(
        status,
        cases_evaluated=len(cases),
        cases_with_context=cases_with_context,
        cases_with_unobservable_scope=cases_with_unobservable_scope,
        returned_items=returned_items,
        denied_assertions=denied_assertions,
        leakage_count=len(violations),
        violations=violations,
        unobservable=unobservable,
    )


def _source_value(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    # document_filename is a documented compatibility provenance field. It is
    # accepted as a source label, but the report keeps checksum coverage separate.
    return _nonempty_text(value.get("source")) or _nonempty_text(value.get("document_filename"))


def _citation_source_metrics(cases: Sequence[_Case]) -> dict[str, Any]:
    if not cases:
        not_run = _metric(NOT_RUN, reason="no fixture cases were available", value=None, numerator=0, denominator=0)
        return _metric(
            NOT_RUN,
            reason="no fixture cases were available",
            source_coverage=not_run,
            checksum_coverage=dict(not_run),
            citation_coverage=dict(not_run),
        )

    result_count = sum(len(case.results) for case in cases)
    source_count = sum(1 for case in cases for result in case.results if _source_value(result))
    checksum_count = sum(
        1
        for case in cases
        for result in case.results
        if _nonempty_text(result.get("checksum"))
    )
    source_status = PASS if result_count and source_count == result_count else FAIL if result_count else INCONCLUSIVE
    checksum_status = PASS if result_count and checksum_count == result_count else FAIL if result_count else INCONCLUSIVE
    source_metric = _metric(
        source_status,
        value=_round_ratio(source_count / result_count) if result_count else None,
        numerator=source_count,
        denominator=result_count,
    )
    checksum_metric = _metric(
        checksum_status,
        value=_round_ratio(checksum_count / result_count) if result_count else None,
        numerator=checksum_count,
        denominator=result_count,
    )

    citation_case_ids = [case.case_id for case in cases if case.citations is not None]
    missing_citation_cases = [case.case_id for case in cases if case.citations is None]
    citation_count = sum(len(case.citations or []) for case in cases)
    citation_matches = 0
    fully_covered = 0
    unresolved: list[dict[str, Any]] = []
    source_mismatches: list[dict[str, Any]] = []
    for case in cases:
        if case.citations is None:
            continue
        for citation_index, citation in enumerate(case.citations):
            citation_ids = _identifiers(citation)
            matching_results = [
                result
                for result in case.results
                if citation_ids.intersection(_identifiers(result))
            ] if citation_ids else []
            if not matching_results:
                unresolved.append({
                    "case_id": case.case_id,
                    "citation_index": citation_index,
                    "identifiers": sorted(citation_ids),
                })
                continue
            citation_matches += 1
            citation_source = _source_value(citation)
            covered = False
            mismatch = False
            for result in matching_results:
                result_source = _source_value(result)
                if not result_source:
                    continue
                if citation_source and citation_source != result_source:
                    mismatch = True
                    continue
                covered = True
                break
            if covered:
                fully_covered += 1
            elif mismatch:
                source_mismatches.append({
                    "case_id": case.case_id,
                    "citation_index": citation_index,
                    "identifiers": sorted(citation_ids),
                    "reason": "citation source does not match the retrieved source",
                })

    if not citation_case_ids:
        citation_metric = _metric(
            NOT_RUN,
            reason="no citations were supplied in the fixture",
            value=None,
            numerator=0,
            denominator=0,
        )
    elif citation_count == 0:
        citation_metric = _metric(
            INCONCLUSIVE,
            reason="citation arrays were supplied but contained no citations",
            value=None,
            numerator=0,
            denominator=0,
        )
    else:
        citation_status = FAIL if fully_covered != citation_count else PASS
        if citation_status == PASS and missing_citation_cases:
            citation_status = INCONCLUSIVE
        citation_metric = _metric(
            citation_status,
            value=_round_ratio(fully_covered / citation_count),
            numerator=fully_covered,
            denominator=citation_count,
            retrieved_match_coverage=_round_ratio(citation_matches / citation_count),
            unresolved=unresolved,
            source_mismatches=source_mismatches,
            cases_with_citations=len(citation_case_ids),
            cases_without_citations=missing_citation_cases,
        )

    status = _status_join([source_metric["status"], checksum_metric["status"], citation_metric["status"]])
    return _metric(
        status,
        source_coverage=source_metric,
        checksum_coverage=checksum_metric,
        citation_coverage=citation_metric,
        result_count=result_count,
        source_items=source_count,
        checksum_items=checksum_count,
    )


def _claim_support_metrics(cases: Sequence[_Case]) -> dict[str, Any]:
    """Evaluate claim-to-citation observations and reviewed faithfulness.

    ``reference_citation_ids`` are reviewed, versioned support annotations from
    the approved evaluation pack.  ``citation_ids`` are the answer's emitted
    citations.  Faithfulness is accepted only as an explicit reviewed
    annotation on each claim; it is never inferred by this offline harness.
    """

    claims = [
        (case, claim)
        for case in cases
        for claim in (case.claims or [])
    ]
    if not claims:
        not_run = _metric(NOT_RUN, reason="no claims were supplied in the fixture")
        return _metric(
            NOT_RUN,
            reason="no claims were supplied in the fixture",
            source=_CLAIM_SUPPORT_SOURCE,
            citation_precision=dict(not_run),
            citation_recall=dict(not_run),
            citation_completeness=dict(not_run),
            unsupported_claim_rate=dict(not_run),
            faithfulness=dict(not_run),
            claim_count=0,
            per_claim=[],
        )

    per_claim: list[dict[str, Any]] = []
    precision_claims: list[dict[str, Any]] = []
    missing_support_annotations: list[str] = []
    invalid_citation_count = 0
    supported_count = 0
    unsupported_count = 0
    faithfulness_values: list[float] = []
    missing_faithfulness_annotations: list[str] = []

    for case, claim in claims:
        predicted_raw = claim.get("citation_ids")
        reference_raw = claim.get("reference_citation_ids")
        predicted = set(predicted_raw or ()) if predicted_raw is not None else set()
        references = set(reference_raw or ()) if reference_raw is not None else None
        available_ids = {
            identifier
            for citation in (case.citations or [])
            for identifier in _identifiers(citation)
        }
        valid_predicted = predicted.intersection(available_ids)
        invalid_predicted = predicted.difference(available_ids)
        invalid_citation_count += len(invalid_predicted)

        true_positive: set[str] = set()
        if references is not None:
            true_positive = valid_predicted.intersection(references)
            if references:
                precision_claims.append({
                    "case_id": case.case_id,
                    "claim_id": claim["claim_id"],
                    "predicted": valid_predicted,
                    "predicted_count": len(predicted),
                    "references": references,
                    "true_positive": true_positive,
                })

        explicit_supported = claim.get("supported")
        if isinstance(explicit_supported, bool):
            supported = explicit_supported
            support_source = "reviewed_annotation"
        elif references is not None:
            supported = bool(true_positive)
            support_source = "reference_citation_intersection"
        else:
            supported = None
            support_source = "unobservable"
            missing_support_annotations.append(f"{case.case_id}:{claim['claim_id']}")

        if supported is True:
            supported_count += 1
        elif supported is False:
            unsupported_count += 1

        faithfulness = claim.get("faithfulness")
        if isinstance(faithfulness, (int, float)) and not isinstance(faithfulness, bool):
            faithfulness_values.append(float(faithfulness))
        else:
            missing_faithfulness_annotations.append(f"{case.case_id}:{claim['claim_id']}")

        per_claim.append({
            "case_id": case.case_id,
            "claim_id": claim["claim_id"],
            "predicted_citation_ids": sorted(predicted),
            "valid_citation_ids": sorted(valid_predicted),
            "invalid_citation_ids": sorted(invalid_predicted),
            "reference_citation_ids": sorted(references) if references is not None else None,
            "true_positive_citation_ids": sorted(true_positive),
            "supported": supported,
            "support_source": support_source,
            "faithfulness": faithfulness,
            "faithfulness_source": "reviewed_annotation" if faithfulness is not None else "unobservable",
        })

    precision_numerator = sum(len(row["true_positive"]) for row in precision_claims)
    precision_denominator = sum(row["predicted_count"] for row in precision_claims)
    recall_denominator = sum(len(row["references"]) for row in precision_claims)

    annotation_status = INCONCLUSIVE if missing_support_annotations else PASS
    precision_status = annotation_status
    recall_status = annotation_status
    if invalid_citation_count:
        precision_status = FAIL
        recall_status = FAIL

    if not precision_claims:
        precision_metric = _metric(
            INCONCLUSIVE,
            reason="non-empty reference_citation_ids are required for citation precision",
            value=None,
            numerator=0,
            denominator=0,
            excluded_claims=[row["claim_id"] for row in per_claim],
        )
        recall_metric = _metric(
            INCONCLUSIVE,
            reason="non-empty reference_citation_ids are required for citation recall",
            value=None,
            numerator=0,
            denominator=0,
            excluded_claims=[row["claim_id"] for row in per_claim],
        )
    else:
        if precision_denominator:
            precision_metric = _metric(
                precision_status,
                value=_round_ratio(precision_numerator / precision_denominator),
                numerator=precision_numerator,
                denominator=precision_denominator,
                aggregation="micro_over_claim_citations",
            )
        else:
            precision_metric = _metric(
                INCONCLUSIVE,
                reason="no emitted citation was available to define citation precision",
                value=None,
                numerator=0,
                denominator=0,
            )
        recall_metric = _metric(
            recall_status,
            value=_round_ratio(
                sum(len(row["true_positive"]) for row in precision_claims) / recall_denominator
            ) if recall_denominator else None,
            numerator=precision_numerator,
            denominator=recall_denominator,
            aggregation="micro_over_reference_citations",
        )

    if missing_support_annotations:
        completeness_metric = _metric(
            INCONCLUSIVE,
            reason="each claim needs reference_citation_ids or a reviewed supported annotation",
            value=None,
            numerator=supported_count,
            denominator=len(claims),
            missing_claims=missing_support_annotations,
        )
        unsupported_metric = _metric(
            INCONCLUSIVE,
            reason="each claim needs reference_citation_ids or a reviewed supported annotation",
            value=None,
            numerator=unsupported_count,
            denominator=len(claims),
            missing_claims=missing_support_annotations,
        )
    else:
        completeness_status = FAIL if invalid_citation_count else PASS
        unsupported_status = FAIL if invalid_citation_count else PASS
        completeness_metric = _metric(
            completeness_status,
            value=_round_ratio(supported_count / len(claims)),
            numerator=supported_count,
            denominator=len(claims),
            aggregation="micro_over_claims",
        )
        unsupported_metric = _metric(
            unsupported_status,
            value=_round_ratio(unsupported_count / len(claims)),
            numerator=unsupported_count,
            denominator=len(claims),
            aggregation="micro_over_claims",
        )

    if missing_faithfulness_annotations:
        faithfulness_metric = _metric(
            INCONCLUSIVE,
            reason="each claim needs an explicit reviewed faithfulness annotation",
            value=None,
            numerator=None,
            denominator=len(claims),
            missing_claims=missing_faithfulness_annotations,
            source="reviewed_annotation",
        )
    else:
        faithfulness_metric = _metric(
            PASS,
            value=_round_ratio(sum(faithfulness_values) / len(faithfulness_values)),
            numerator=_round_ratio(sum(faithfulness_values)),
            denominator=len(faithfulness_values),
            aggregation="mean_over_reviewed_claims",
            source="reviewed_annotation",
        )

    status = _status_join([
        precision_metric["status"],
        recall_metric["status"],
        completeness_metric["status"],
        unsupported_metric["status"],
        faithfulness_metric["status"],
    ])
    return _metric(
        status,
        source=_CLAIM_SUPPORT_SOURCE,
        citation_precision=precision_metric,
        citation_recall=recall_metric,
        citation_completeness=completeness_metric,
        unsupported_claim_rate=unsupported_metric,
        faithfulness=faithfulness_metric,
        claim_count=len(claims),
        supported_claims=supported_count,
        unsupported_claims=unsupported_count,
        invalid_citation_count=invalid_citation_count,
        per_claim=per_claim,
        limitations=[
            "Citation support is identity-level evaluation against approved reference IDs; faithfulness is reported only from explicit reviewed annotations.",
            "Low metric values remain observable so pack-owned thresholds, rather than this evaluator, decide quality acceptance.",
        ],
    )


def _nearest_rank(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    position = max(1, math.ceil(percentile * len(ordered)))
    return ordered[position - 1]


def _latency_metrics(cases: Sequence[_Case]) -> dict[str, Any]:
    if not cases:
        return _metric(NOT_RUN, reason="no fixture cases were available", unit="ms", sample_count=0)

    values = [value for case in cases for value in case.latency_values_ms]
    missing_cases = [case.case_id for case in cases if not case.latency_values_ms]
    if not values:
        return _metric(
            INCONCLUSIVE,
            reason="fixture cases did not contain latency_ms or latency_samples_ms",
            unit="ms",
            sample_count=0,
            missing_cases=missing_cases,
        )

    status = INCONCLUSIVE if missing_cases else PASS
    return _metric(
        status,
        reason="latency is descriptive only; no target threshold was configured" if status == PASS else "some fixture cases lacked latency observations",
        unit="ms",
        sample_count=len(values),
        observed_cases=len(cases) - len(missing_cases),
        missing_cases=missing_cases,
        min=_round_ms(min(values)),
        p50=_round_ms(_nearest_rank(values, 0.50)),
        p95=_round_ms(_nearest_rank(values, 0.95)),
        mean=_round_ms(sum(values) / len(values)),
        max=_round_ms(max(values)),
        percentile_method="nearest_rank",
        observation="fixture-reported retrieval latency; not harness runtime",
    )


def _base_limitations() -> list[str]:
    return [
        "This run evaluates recorded observations only; it does not call the API, vector store, embedding provider, LLM, or network.",
        "Latency values are supplied by the fixture and do not establish a production SLO, capacity limit, or provider-performance claim.",
        "Metrics describe the supplied cases and do not establish corpus representativeness, statistical significance, freshness, concurrency behavior, or production quality.",
    ]


def _evaluate_loaded(
    loaded: LoadedFixture,
    *,
    k_values: tuple[int, ...],
    fixture_path: str | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    cases: list[_Case] = []
    for index, raw_case in enumerate(loaded.cases):
        case = _normalise_case(raw_case, index, errors)
        if case is not None:
            cases.append(case)

    metrics = {
        "ranking": _ranking_metrics(cases, k_values),
        "acl_leakage": _acl_metrics(cases),
        "citation_source_coverage": _citation_source_metrics(cases),
        "citation_support": _claim_support_metrics(cases),
        "latency": _latency_metrics(cases),
    }
    input_status = FAIL if errors else PASS if cases else INCONCLUSIVE
    overall_status = _status_join([input_status] + [metric["status"] for metric in metrics.values()])
    limitations = _base_limitations()
    if metrics["ranking"]["status"] == INCONCLUSIVE:
        limitations.append("Ranking metrics are partial or unavailable because one or more cases lack non-empty relevance annotations.")
    if metrics["acl_leakage"]["status"] == INCONCLUSIVE:
        limitations.append("ACL verification is inconclusive where tenant, workspace, collection, or trusted corpus scope is not observable.")
    if metrics["citation_source_coverage"]["status"] == INCONCLUSIVE:
        limitations.append("Citation coverage is inconclusive when citations or source provenance are absent from the fixture.")
    if metrics["citation_support"]["status"] == INCONCLUSIVE:
        limitations.append("Claim support metrics are inconclusive when reviewed support annotations are absent from the fixture.")
    if errors:
        limitations.append("The fixture contains schema or value errors; the overall result is not a valid quality pass.")

    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "status": overall_status,
        "mode": "offline_fixture",
        "fixture": {
            "status": input_status,
            "path": fixture_path,
            "format": loaded.format,
            "schema_version": loaded.metadata.get("schema_version"),
            "provider": loaded.metadata.get("provider", "offline-fixture"),
            "case_count": len(loaded.cases),
        },
        "configuration": {
            "k_values": list(k_values),
            "source": "cli" if fixture_path is not None and loaded.k_values != k_values else "fixture_or_default",
        },
        "input": {
            "status": input_status,
            "normalised_case_count": len(cases),
            "errors": errors,
        },
        "metrics": metrics,
        "live_provider": {
            "status": NOT_RUN,
            "configured": False,
            "reason": "offline fixture mode does not invoke live providers",
        },
        "limitations": limitations,
    }


def evaluate_fixture(payload: Any, *, k_values: Sequence[int] | None = None) -> dict[str, Any]:
    """Evaluate an already decoded JSON object/array.

    This public seam is intentionally independent of files so unit tests and
    callers embedding the harness can keep their data in memory.
    """

    loaded = _fixture_from_value(payload, format="json")
    chosen = parse_k_values(k_values) if k_values is not None else loaded.k_values or DEFAULT_K_VALUES
    return _evaluate_loaded(loaded, k_values=chosen)


def _live_provider_configured() -> bool:
    marker = (os.environ.get("RICK_RETRIEVAL_EVAL_LIVE") or "").strip().lower()
    provider = (os.environ.get("RICK_RETRIEVAL_EVAL_PROVIDER") or "").strip()
    return marker in {"1", "true", "yes", "on"} or bool(provider)


def _not_run_result(*, mode: str, reason: str, fixture_path: str | None = None) -> dict[str, Any]:
    metrics = {
        name: _metric(NOT_RUN, reason=reason)
        for name in ("ranking", "acl_leakage", "citation_source_coverage", "citation_support", "latency")
    }
    if mode == "live":
        configured = _live_provider_configured()
        live_reason = (
            "a provider marker exists, but this dependency-light harness has no live execution adapter; no provider call was made"
            if configured
            else "live provider is not configured; no provider call was made"
        )
        live = {"status": NOT_RUN, "configured": configured, "reason": live_reason}
    else:
        live = {
            "status": NOT_RUN,
            "configured": False,
            "reason": "offline fixture mode does not invoke live providers",
        }
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "status": NOT_RUN,
        "mode": mode,
        "fixture": {
            "status": NOT_RUN,
            "path": fixture_path,
            "format": None,
            "case_count": 0,
        },
        "configuration": {"k_values": list(DEFAULT_K_VALUES)},
        "input": {"status": NOT_RUN, "normalised_case_count": 0, "errors": []},
        "metrics": metrics,
        "live_provider": live,
        "limitations": [reason, *_base_limitations()],
    }


def _error_result(*, reason: str, fixture_path: str | None) -> dict[str, Any]:
    result = _not_run_result(mode="offline", reason="fixture could not be evaluated", fixture_path=fixture_path)
    result["status"] = FAIL
    result["fixture"]["status"] = FAIL
    result["input"] = {"status": FAIL, "normalised_case_count": 0, "errors": [reason]}
    result["limitations"].insert(0, "The supplied fixture is invalid; no quality conclusion was produced.")
    return result


def _exit_code(status: str) -> int:
    if status == PASS:
        return EXIT_PASS
    if status == FAIL:
        return EXIT_FAIL
    return EXIT_INCONCLUSIVE


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        help="offline JSON or JSONL observation fixture; omitted means NOT_RUN",
    )
    parser.add_argument(
        "--mode",
        choices=("offline", "live"),
        default="offline",
        help="live mode is declaration-only and never performs a provider call",
    )
    parser.add_argument(
        "--k",
        "--ks",
        dest="k_values",
        action="append",
        help="positive k values, e.g. --k 1,3,5 (repeatable)",
    )
    parser.add_argument("--output", type=Path, help="also write the machine-readable result to this path")
    parser.add_argument("--pretty", action="store_true", help="indent JSON output for humans")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    fixture_argument = str(args.fixture) if args.fixture is not None else None

    try:
        cli_k_values = parse_k_values(args.k_values) if args.k_values is not None else None
    except ValueError as exc:
        result = _error_result(reason=str(exc), fixture_path=fixture_argument)
    else:
        if args.mode == "live":
            result = _not_run_result(
                mode="live",
                reason="live evaluation was requested, but this harness only evaluates offline fixtures",
                fixture_path=fixture_argument,
            )
        elif args.fixture is None:
            result = _not_run_result(
                mode="offline",
                reason="no offline fixture was supplied",
            )
        elif not args.fixture.exists():
            result = _not_run_result(
                mode="offline",
                reason=f"offline fixture does not exist: {args.fixture}",
                fixture_path=fixture_argument,
            )
        else:
            try:
                loaded = load_fixture(args.fixture)
                chosen_k_values = cli_k_values or loaded.k_values or DEFAULT_K_VALUES
                result = _evaluate_loaded(
                    loaded,
                    k_values=chosen_k_values,
                    fixture_path=fixture_argument,
                )
            except (OSError, ValueError) as exc:
                result = _error_result(reason=str(exc), fixture_path=fixture_argument)

    serialized = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        indent=2 if args.pretty else None,
        separators=None if args.pretty else (",", ":"),
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return _exit_code(result["status"])


if __name__ == "__main__":
    sys.exit(main())
