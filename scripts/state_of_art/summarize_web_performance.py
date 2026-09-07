#!/usr/bin/env python3
"""Validate and summarize durable local web LCP/CLS evidence."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


EXPECTED_ROUTES = ("login", "app", "app-search", "app-chat", "app-documents", "admin")
EXPECTED_PROJECTS = ("mobile", "tablet", "desktop")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    files = sorted(args.input.glob("*.json"))
    expected = {f"{route}-{project}.json" for route in EXPECTED_ROUTES for project in EXPECTED_PROJECTS}
    actual = {path.name for path in files}
    if actual != expected:
        missing, unexpected = sorted(expected - actual), sorted(actual - expected)
        raise SystemExit(f"FAIL performance evidence inventory: missing={missing} unexpected={unexpected}")

    cases = []
    for path in files:
        data = json.loads(path.read_text())
        measured = data["measured"]
        case = {
            "file": path.name,
            "test": data["test"],
            "route": data["route"],
            "viewport": data["viewport"],
            "lcp_ms": measured["lcp"],
            "cls": measured["cls"],
            "shift_count": len(measured.get("shifts", [])),
            "lcp_positive": data["assertion"]["lcp_positive"],
            "lcp_within_budget": data["assertion"]["lcp_within_budget"],
            "cls_within_budget": data["assertion"]["cls_within_budget"],
        }
        if not all((case["lcp_positive"], case["lcp_within_budget"], case["cls_within_budget"])):
            raise SystemExit(f"FAIL performance threshold assertion: {path}")
        cases.append(case)

    lcp_values = [case["lcp_ms"] for case in cases]
    cls_values = [case["cls"] for case in cases]
    summary = {
        "schema": "rick-web-performance-summary.v1",
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "profile": "Local production Next build; Chromium; 4x CPU throttle; cache disabled; synthetic/local API; reduced-motion preference.",
        "limitations": [
            "18 cold-context local lab samples, not field p75 or deployment acceptance.",
            "Synthetic intercepted API responses and local loopback API do not represent provider, network or database latency.",
        ],
        "expected_cases": len(expected),
        "observed_cases": len(cases),
        "thresholds": {"lcp_ms_max": 2500, "cls_max": 0.1},
        "aggregate": {
            "lcp_min_ms": min(lcp_values),
            "lcp_max_ms": max(lcp_values),
            "lcp_mean_ms": sum(lcp_values) / len(lcp_values),
            "cls_min": min(cls_values),
            "cls_max": max(cls_values),
            "cls_mean": sum(cls_values) / len(cls_values),
            "all_thresholds_pass": True,
        },
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(f"PASS performance evidence: {len(cases)} cases; LCP max={max(lcp_values):.2f}ms; CLS max={max(cls_values):.4f}; reduced-motion recorded per case")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
