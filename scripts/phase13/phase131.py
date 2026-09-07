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


def _env():
    import os

    env = os.environ.copy()
    parts = [str(ROOT / "apps" / "api" / "src")] + [
        str(ROOT / "packages" / p / "src") for p in ("contracts", "authorization", "identity", "observability")
    ]
    env["PYTHONPATH"] = os.pathsep.join(parts + [env.get("PYTHONPATH", "")])
    env.setdefault("RAG_SKIP_QDRANT_BOOTSTRAP", "1")
    env.setdefault("SESSION_COOKIE_SECURE", "false")
    return env


def _run(cmd):
    print(f"==> {' '.join(cmd)}", flush=True)
    completed = subprocess.run(cmd, cwd=ROOT, env=_env())
    print(f"<== exit {completed.returncode}", flush=True)
    return completed.returncode


def mode_canonical() -> int:
    return _run([sys.executable, "-m", "pytest", "-q", str(AUTHZ_TESTS), str(IDENTITY_TESTS)])


def mode_differential() -> int:
    return _run([sys.executable, "-m", "pytest", "-q",
                 str(API_TESTS / "test_differential_auth.py"),
                 str(API_TESTS / "test_policy_source_of_truth.py"),
                 str(API_TESTS / "test_canonical_negatives.py")])


def mode_api() -> int:
    return _run([sys.executable, "-m", "pytest", "-q", str(API_TESTS)])


def mode_legacy_auth() -> int:
    import os

    env = _env()
    env["PYTHONPATH"] = f"{ROOT / 'cvg-master-rag-v2' / 'src'}{os.pathsep}{env['PYTHONPATH']}"
    print("==> legacy CVG auth regression (focused)", flush=True)
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q",
         "cvg-master-rag-v2/src/tests/test_phase05_security.py",
         "cvg-master-rag-v2/src/tests/test_phase06_rbac.py"],
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
    results = [mode_canonical(), mode_differential(), mode_api(), mode_legacy_auth()]
    return 0 if all(code == 0 for code in results) else 1


MODES = {"canonical": mode_canonical, "differential": mode_differential, "api": mode_api,
         "legacy-auth": mode_legacy_auth, "benchmark": mode_benchmark, "full": mode_full}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in MODES:
        print(f"usage: phase131.py <{'|'.join(sorted(MODES))}>", flush=True)
        return 2
    return MODES[argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
