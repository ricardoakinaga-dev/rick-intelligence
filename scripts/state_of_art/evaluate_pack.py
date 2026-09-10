#!/usr/bin/env python3
"""Evaluate a versioned, dependency-light retrieval promotion-pack candidate.

The pack runner is intentionally offline.  It composes the existing recorded
observation evaluator with explicit thresholds and structural negative cases;
it never calls an API, vector store, model provider, or network service.
"""

from __future__ import annotations

import argparse
import json
import math
import operator
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Callable

try:  # package import for tests and module callers
    from .json_boundary import load_json
    from .evaluate_retrieval import (
        FAIL,
        INCONCLUSIVE,
        NOT_RUN,
        PASS,
        evaluate_fixture,
        load_fixture,
        parse_k_values,
    )
except ImportError:  # direct script execution with PYTHONPATH=scripts/state_of_art
    from json_boundary import load_json
    from evaluate_retrieval import (
        FAIL,
        INCONCLUSIVE,
        NOT_RUN,
        PASS,
        evaluate_fixture,
        load_fixture,
        parse_k_values,
    )


PACK_SCHEMA_VERSION = "retrieval-evaluation-pack.v1"
PACK_RESULT_SCHEMA_VERSION = "retrieval-evaluation-pack-result.v1"
EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_INCONCLUSIVE = 2

_COMPARATORS: dict[str, Callable[[float, float], bool]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
}


class PackError(ValueError):
    """A malformed pack that cannot produce a quality result."""


def _load_json(path: Path) -> Any:
    return load_json(path)


def _text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PackError(f"{field} must be a non-empty string")
    return value.strip()


def _finite_number(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PackError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise PackError(f"{field} must be a finite number")
    return number


def _status_join(statuses: Sequence[str]) -> str:
    if FAIL in statuses:
        return FAIL
    if INCONCLUSIVE in statuses:
        return INCONCLUSIVE
    if PASS in statuses:
        return PASS
    return NOT_RUN


def _path_get(root: Any, path: str) -> Any:
    current = root
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            raise KeyError(path)
    return current


def _case_id(case: Mapping[str, Any], index: int) -> str:
    value = case.get("case_id", case.get("id", f"case-{index + 1}"))
    return _text(value, field=f"cases[{index}].case_id")


def _case_pack_metadata(case: Mapping[str, Any], index: int) -> Mapping[str, Any]:
    value = case.get("pack")
    if not isinstance(value, Mapping):
        raise PackError(f"cases[{index}].pack must be an object")
    role = _text(value.get("role"), field=f"cases[{index}].pack.role")
    if role not in {"positive", "negative"}:
        raise PackError(f"cases[{index}].pack.role must be positive or negative")
    if role == "negative":
        expectation = _text(value.get("expectation"), field=f"cases[{index}].pack.expectation")
        if expectation not in {"no_evidence", "weak_evidence", "unsupported_assertion"}:
            raise PackError(f"cases[{index}].pack.expectation is unsupported")
    return value


def _validate_manifest(manifest: Mapping[str, Any], pack_dir: Path) -> tuple[Path, tuple[int, ...], list[dict[str, Any]]]:
    if manifest.get("schema_version") != PACK_SCHEMA_VERSION:
        raise PackError("manifest schema_version is invalid")
    _text(manifest.get("pack_id"), field="pack_id")
    _text(manifest.get("version"), field="version")
    fixture_name = _text(manifest.get("fixture"), field="fixture")
    fixture = (pack_dir / fixture_name).resolve()
    try:
        fixture.relative_to(pack_dir.resolve())
    except ValueError as exc:
        raise PackError("fixture must remain inside the pack directory") from exc
    if not fixture.is_file():
        raise PackError("fixture does not exist")
    try:
        k_values = parse_k_values(manifest.get("k_values"))
    except ValueError as exc:
        raise PackError(str(exc)) from exc

    metadata = manifest.get("metadata")
    if not isinstance(metadata, Mapping):
        raise PackError("metadata must be an object")
    for field in ("corpus_id", "corpus_version", "model_id", "provenance"):
        _text(metadata.get(field), field=f"metadata.{field}")

    thresholds = manifest.get("thresholds")
    if not isinstance(thresholds, list) or not thresholds:
        raise PackError("thresholds must be a non-empty array")
    normalised_thresholds: list[dict[str, Any]] = []
    threshold_ids: set[str] = set()
    for index, raw in enumerate(thresholds):
        if not isinstance(raw, Mapping):
            raise PackError(f"thresholds[{index}] must be an object")
        threshold_id = _text(raw.get("id"), field=f"thresholds[{index}].id")
        if threshold_id in threshold_ids:
            raise PackError("threshold ids must be unique")
        threshold_ids.add(threshold_id)
        metric_path = _text(raw.get("metric_path"), field=f"thresholds[{index}].metric_path")
        comparison = _text(raw.get("operator"), field=f"thresholds[{index}].operator")
        if comparison not in _COMPARATORS:
            raise PackError(f"thresholds[{index}].operator is unsupported")
        normalised_thresholds.append(
            {
                "id": threshold_id,
                "metric_path": metric_path,
                "operator": comparison,
                "target": _finite_number(raw.get("value"), field=f"thresholds[{index}].value"),
            }
        )

    return fixture, k_values, normalised_thresholds


def _normalise_cases(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("cases"), list):
        raise PackError("fixture must contain a cases array")
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(payload["cases"]):
        if not isinstance(raw, Mapping):
            raise PackError(f"cases[{index}] must be an object")
        case = dict(raw)
        case_id = _case_id(case, index)
        if case_id in seen:
            raise PackError(f"duplicate case_id: {case_id}")
        seen.add(case_id)
        _case_pack_metadata(case, index)
        cases.append(case)
    if not cases:
        raise PackError("fixture must contain at least one case")
    return cases


def _group_key(case: Mapping[str, Any], *, defaults: Mapping[str, Any]) -> tuple[str, str]:
    pack = case["pack"]
    model_id = _text(pack.get("model_id", defaults.get("model_id")), field="case model_id")
    corpus_id = _text(pack.get("corpus_id", defaults.get("corpus_id")), field="case corpus_id")
    return model_id, corpus_id


def _check_negative(case: Mapping[str, Any]) -> dict[str, Any]:
    pack = case["pack"]
    expectation = str(pack["expectation"])
    results = case.get("results", case.get("retrieved", case.get("items", case.get("evidence", []))))
    citations = case.get("citations", [])
    reasons: list[str] = []
    if not isinstance(results, list):
        reasons.append("results must be an array")
        results = []
    if not isinstance(citations, list):
        reasons.append("citations must be an array")
        citations = []

    if expectation == "no_evidence":
        if results:
            reasons.append("no_evidence case returned evidence")
        if citations:
            reasons.append("no_evidence case returned citations")
    elif expectation == "weak_evidence":
        if not results:
            reasons.append("weak_evidence case has no observable weak result")
        for index, result in enumerate(results):
            if not isinstance(result, Mapping) or result.get("evidence_strength") != "weak":
                reasons.append(f"results[{index}] is not marked weak")
        if citations:
            reasons.append("weak_evidence case must not emit a citation")
    elif expectation == "unsupported_assertion":
        assertion = case.get("assertion")
        if not isinstance(assertion, Mapping):
            reasons.append("unsupported_assertion case requires an assertion object")
        else:
            if assertion.get("supported") is not False:
                reasons.append("assertion.supported must be false")
            support_ids = assertion.get("support_ids", [])
            if not isinstance(support_ids, list) or support_ids:
                reasons.append("unsupported assertion must have no support_ids")
        if citations:
            reasons.append("unsupported assertion must not emit a citation")

    return {
        "case_id": _case_id(case, 0),
        "role": "negative",
        "expectation": expectation,
        "status": FAIL if reasons else PASS,
        "reasons": reasons,
    }


def _check_threshold(result: Mapping[str, Any], threshold: Mapping[str, Any]) -> dict[str, Any]:
    threshold_id = str(threshold["id"])
    path = str(threshold["metric_path"])
    comparison = str(threshold["operator"])
    target = float(threshold["target"])
    try:
        observed = _path_get(result, path)
        observed_number = _finite_number(observed, field=f"metric {path}")
    except (KeyError, PackError) as exc:
        return {
            "id": threshold_id,
            "status": INCONCLUSIVE,
            "metric_path": path,
            "operator": comparison,
            "target": target,
            "observed": None,
            "reason": f"metric was unavailable: {exc}",
        }
    passed = _COMPARATORS[comparison](observed_number, target)
    return {
        "id": threshold_id,
        "status": PASS if passed else FAIL,
        "metric_path": path,
        "operator": comparison,
        "target": target,
        "observed": observed_number,
        "reason": "threshold satisfied" if passed else "threshold violated",
    }


def evaluate_pack(pack_path: str | Path) -> dict[str, Any]:
    """Evaluate a pack directory and return a stable machine-readable report."""

    manifest_path = Path(pack_path)
    if manifest_path.is_dir():
        manifest_path = manifest_path / "manifest.json"
    manifest_path = manifest_path.resolve()
    pack_dir = manifest_path.parent
    if not manifest_path.is_file():
        return _not_run_result(f"pack manifest does not exist: {manifest_path}")
    try:
        manifest = _load_json(manifest_path)
        if not isinstance(manifest, Mapping):
            raise PackError("pack manifest must be an object")
        fixture_path, k_values, thresholds = _validate_manifest(manifest, pack_dir)
        fixture = _load_json(fixture_path)
        cases = _normalise_cases(fixture)
        defaults = manifest["metadata"]
        positive_cases = [case for case in cases if case["pack"]["role"] == "positive"]
        negative_cases = [case for case in cases if case["pack"]["role"] == "negative"]
        if not positive_cases:
            raise PackError("pack must contain at least one positive case")

        fixture_payload = {
            "schema_version": fixture.get("schema_version") if isinstance(fixture, Mapping) else None,
            "provider": fixture.get("provider", "offline-pack") if isinstance(fixture, Mapping) else "offline-pack",
            "cases": positive_cases,
            "k_values": list(k_values),
        }
        aggregate = evaluate_fixture(fixture_payload, k_values=k_values)
        threshold_results = [_check_threshold(aggregate, threshold) for threshold in thresholds]
        negative_results = [_check_negative(case) for case in negative_cases]

        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for case in positive_cases:
            grouped[_group_key(case, defaults=defaults)].append(case)
        per_group: list[dict[str, Any]] = []
        for (model_id, corpus_id), group_cases in sorted(grouped.items()):
            group_result = evaluate_fixture(
                {"schema_version": fixture_payload["schema_version"], "cases": group_cases, "k_values": list(k_values)},
                k_values=k_values,
            )
            per_group.append(
                {
                    "model_id": model_id,
                    "corpus_id": corpus_id,
                    "case_count": len(group_cases),
                    "status": group_result["status"],
                    "metrics": group_result["metrics"],
                }
            )

        statuses = [aggregate["status"]]
        statuses.extend(item["status"] for item in threshold_results)
        statuses.extend(item["status"] for item in negative_results)
        statuses.extend(item["status"] for item in per_group)
        return {
            "schema_version": PACK_RESULT_SCHEMA_VERSION,
            "status": _status_join(statuses),
            "mode": "offline_pack",
            "pack": {
                "status": PASS,
                "path": str(pack_dir),
                "pack_id": manifest["pack_id"],
                "version": manifest["version"],
                "metadata": dict(defaults),
                "case_count": len(cases),
                "positive_case_count": len(positive_cases),
                "negative_case_count": len(negative_cases),
            },
            "aggregate": aggregate,
            "thresholds": threshold_results,
            "negative_cases": negative_results,
            "per_model_corpus": per_group,
            "live_provider": {"status": NOT_RUN, "reason": "pack evaluation is offline and makes no provider calls"},
            "limitations": [
                "The pack uses synthetic recorded observations and does not establish production retrieval quality.",
                "Provider, corpus, license, freshness, runtime, load, cost, and clinical acceptance evidence remain external gates.",
            ],
        }
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return _error_result(str(exc), manifest_path)


def _not_run_result(reason: str) -> dict[str, Any]:
    return {
        "schema_version": PACK_RESULT_SCHEMA_VERSION,
        "status": NOT_RUN,
        "mode": "offline_pack",
        "pack": {"status": NOT_RUN, "path": None},
        "aggregate": {"status": NOT_RUN},
        "thresholds": [],
        "negative_cases": [],
        "per_model_corpus": [],
        "live_provider": {"status": NOT_RUN, "reason": "no provider call was made"},
        "limitations": [reason],
    }


def _error_result(reason: str, manifest_path: Path) -> dict[str, Any]:
    return {
        "schema_version": PACK_RESULT_SCHEMA_VERSION,
        "status": FAIL,
        "mode": "offline_pack",
        "pack": {"status": FAIL, "path": str(manifest_path.parent)},
        "aggregate": {"status": NOT_RUN},
        "thresholds": [],
        "negative_cases": [],
        "per_model_corpus": [],
        "live_provider": {"status": NOT_RUN, "reason": "no provider call was made"},
        "limitations": ["The pack could not be evaluated; no quality conclusion was produced.", reason],
    }


def _exit_code(status: str) -> int:
    return EXIT_PASS if status == PASS else EXIT_FAIL if status == FAIL else EXIT_INCONCLUSIVE


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True, help="pack directory or manifest.json")
    parser.add_argument("--output", type=Path, help="also write the machine-readable result")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    result = evaluate_pack(args.pack)
    serialised = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        indent=2 if args.pretty else None,
        separators=None if args.pretty else (",", ":"),
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialised + "\n", encoding="utf-8")
    print(serialised)
    return _exit_code(result["status"])


if __name__ == "__main__":
    sys.exit(main())
