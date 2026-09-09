#!/usr/bin/env python3
"""Validate the bounded synthetic RAG adversarial corpus."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "tests/security/rag_adversarial/corpus.jsonl"
REQUIRED_CATEGORIES = {
    "direct_prompt_injection",
    "encoded_instruction",
    "retrieval_poisoning",
    "tool_injection",
    "secret_exfiltration",
    "cross_tenant_scope",
    "citation_spoofing",
    "malformed_metadata",
}
SECRET_LIKE = re.compile(r"(?:sk-[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]+ KEY-----|postgres(?:ql)?://[^\s]+)")


def main() -> int:
    if not CORPUS.is_file():
        print("FAIL: adversarial corpus is absent", file=sys.stderr)
        return 1
    records: list[dict[str, object]] = []
    errors: list[str] = []
    for line_number, line in enumerate(CORPUS.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"line {line_number}: invalid JSON")
            continue
        if not isinstance(record, dict):
            errors.append(f"line {line_number}: record must be an object")
            continue
        records.append(record)
        if not isinstance(record.get("id"), str) or not record["id"].strip():
            errors.append(f"line {line_number}: id is required")
        category = record.get("category")
        if category not in REQUIRED_CATEGORIES:
            errors.append(f"line {line_number}: unsupported category")
        text = record.get("text")
        if not isinstance(text, str) or not 1 <= len(text) <= 2_000:
            errors.append(f"line {line_number}: text must be bounded")
        elif SECRET_LIKE.search(text):
            errors.append(f"line {line_number}: secret-like fixture content is forbidden")
        if not isinstance(record.get("expected"), str) or not record["expected"].strip():
            errors.append(f"line {line_number}: expected disposition is required")
    ids = [record.get("id") for record in records]
    if len(ids) != len(set(ids)):
        errors.append("duplicate corpus id")
    categories = {record.get("category") for record in records}
    missing = REQUIRED_CATEGORIES - categories
    if missing:
        errors.append(f"missing required categories: {sorted(missing)}")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS: {len(records)} bounded adversarial records across {len(categories)} categories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
