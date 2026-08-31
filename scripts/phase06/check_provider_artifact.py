#!/usr/bin/env python3
"""Fail closed when the real-protocol provider artifact is empty or incomplete."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "rick-professor/test/artifacts/phase-0.6-provider-contract.json"
EXPECTED_CASES = {
    "success",
    "timeout",
    "unavailable",
    "429 rate limit",
    "500 server error",
    "malformed response",
    "missing field",
    "invalid JSON",
    "empty model",
    "embedding dimension mismatch",
    "model not found",
    "document to cited answer flow with real provider HTTP",
}


def main() -> int:
    try:
        artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: cannot read provider artifact: {exc}")
        return 1

    errors: list[str] = []
    if artifact.get("schema_version") != "phase-0.6-provider-contract.v1":
        errors.append("schema_version is not phase-0.6-provider-contract.v1")
    environment = artifact.get("environment")
    if not isinstance(environment, dict):
        errors.append("environment is missing")
    else:
        if environment.get("bind_host") != "127.0.0.1":
            errors.append("provider server is not bound to loopback")
        if environment.get("live_provider_called") is not False:
            errors.append("live_provider_called must be false for this local artifact")
        if not str(environment.get("provider_base_url", "")).startswith("http://127.0.0.1:"):
            errors.append("provider_base_url is not an ephemeral loopback URL")
        if environment.get("max_provider_attempts") != 3:
            errors.append("max_provider_attempts is not 3")

    cases = artifact.get("cases")
    if not isinstance(cases, list):
        errors.append("cases is not a list")
        cases = []
    names = {item.get("name") for item in cases if isinstance(item, dict)}
    missing = sorted(EXPECTED_CASES - names)
    if missing:
        errors.append(f"missing observed cases: {', '.join(missing)}")
    if len(cases) != len(EXPECTED_CASES):
        errors.append(f"expected {len(EXPECTED_CASES)} cases, observed {len(cases)}")

    observations = artifact.get("http_observations")
    requests = observations.get("requests") if isinstance(observations, dict) else None
    if not isinstance(requests, list) or len(requests) < len(EXPECTED_CASES) - 1:
        errors.append("HTTP observations are empty or incomplete")

    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1

    print(f"Provider artifact check PASS: {len(cases)} cases, {len(requests)} HTTP observations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
