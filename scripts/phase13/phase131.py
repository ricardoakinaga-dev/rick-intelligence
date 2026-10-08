#!/usr/bin/env python3
"""Phase 1.3.1 lanes: canonical packages, differential, negatives, drift, benchmark."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_TESTS = ROOT / "apps" / "api" / "tests"
AUTHZ_TESTS = ROOT / "packages" / "authorization" / "tests"
IDENTITY_TESTS = ROOT / "packages" / "identity" / "tests"

sys.path.insert(0, str(ROOT / "scripts" / "phase13"))
from pyenv import interpreter, test_environment  # noqa: E402

PYTHON = interpreter()


def _materialize_legacy_reference() -> int:
    completed = subprocess.run(
        [PYTHON, str(ROOT / "scripts" / "phase15" / "legacy_reference.py")],
        cwd=ROOT, env=test_environment())
    return completed.returncode


def _env(**overrides: str):
    return test_environment(**overrides)


def _run(cmd):
    print(f"==> {' '.join(str(part) for part in cmd)}", flush=True)
    completed = subprocess.run(cmd, cwd=ROOT, env=_env())
    print(f"<== exit {completed.returncode}", flush=True)
    return completed.returncode


def mode_canonical() -> int:
    return _run([PYTHON, "-m", "pytest", "-q", str(AUTHZ_TESTS), str(IDENTITY_TESTS)])


def mode_differential() -> int:
    return _run([PYTHON, "-m", "pytest", "-q",
                 str(API_TESTS / "test_differential_auth.py"),
                 str(API_TESTS / "test_policy_source_of_truth.py"),
                 str(API_TESTS / "test_canonical_negatives.py")])


def mode_api() -> int:
    return _run([PYTHON, "-m", "pytest", "-q", str(API_TESTS)])


def mode_legacy_auth() -> int:
    """Focused legacy CVG auth regression against the read-only reference."""
    import os

    if _materialize_legacy_reference() != 0:
        print("<== legacy reference unavailable; legacy-auth lane aborted", flush=True)
        return 1
    legacy_src = ROOT / ".runtime" / "legacy-reference" / "cvg-master-rag-v2" / "src"
    tests_root = legacy_src / "tests"
    env = _env()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(legacy_src), str(ROOT), env.get("PYTHONPATH", "")])
    print("==> legacy CVG auth regression (focused)", flush=True)
    completed = subprocess.run(
        [PYTHON, "-m", "pytest", "-q",
         "-p", "scripts.phase13.legacy_reference_plugin",
         str(tests_root / "test_phase05_security.py"),
         str(tests_root / "test_phase06_rbac.py")],
        cwd=ROOT, env=env)
    print(f"<== exit {completed.returncode}", flush=True)
    return completed.returncode


def mode_benchmark() -> int:
    sys.path.insert(0, str(ROOT / "packages" / "authorization" / "src"))
    import rick_authorization as authz

    for _ in range(1000):  # warm-up
        authz.permission_granted(role=None, permissions=["chat.query"], required="documents.read", authoritative=True)
    runs = []
    for _ in range(20000):
        start = time.perf_counter()
        authz.permission_granted(role=None, permissions=["chat.query", "sources.read"],
                                 required="documents.read", authoritative=True)
        runs.append((time.perf_counter() - start) * 1e6)
    runs.sort()
    import json

    result = {"permission_check_us": {"p50": round(runs[10000], 3), "p95": round(runs[19000], 3)},
              "note": "in-process canonical engine, authoritative snapshot path"}
    out = ROOT / "docs" / "baselines" / "phase-1.3.1-permission-overhead.json"
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2), flush=True)
    return 0


def mode_full() -> int:
    results = [mode_canonical(), mode_differential(), mode_api()]
    return 0 if all(code == 0 for code in results) else 1


MODES = {"canonical": mode_canonical, "differential": mode_differential, "api": mode_api,
         "legacy-auth": mode_legacy_auth, "benchmark": mode_benchmark, "full": mode_full}
REFERENCE_MODES = {"differential", "api", "legacy-auth", "full"}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in MODES:
        print(f"usage: phase131.py <{'|'.join(sorted(MODES))}>", flush=True)
        return 2
    if argv[1] in REFERENCE_MODES and _materialize_legacy_reference() != 0:
        print("WARN: legacy reference unavailable; parity suites stay fail-closed", flush=True)
    return MODES[argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
