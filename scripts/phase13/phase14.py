#!/usr/bin/env python3
"""Phase 1.4 lanes: canonical RAG packages, differential, shadow, E2E, ACL, perf."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_TESTS = ROOT / "apps" / "api" / "tests"
PKG_TESTS = {p: ROOT / "packages" / p / "tests" for p in
             ("knowledge", "ingestion", "retrieval", "contracts", "authorization", "identity")}
LEGACY_REFERENCE = ROOT / ".runtime" / "legacy-reference"

sys.path.insert(0, str(ROOT / "scripts" / "phase13"))
from pyenv import interpreter, test_environment  # noqa: E402

PYTHON = interpreter()


def _materialize_legacy_reference() -> int:
    completed = subprocess.run(
        [PYTHON, str(ROOT / "scripts" / "phase15" / "legacy_reference.py")],
        cwd=ROOT, env=test_environment())
    return completed.returncode


def _env():
    return test_environment(RICK_LEGACY_REFERENCE=str(LEGACY_REFERENCE))


def _run(cmd):
    print(f"==> {' '.join(str(part) for part in cmd)}", flush=True)
    completed = subprocess.run(cmd, cwd=ROOT, env=_env())
    print(f"<== exit {completed.returncode}", flush=True)
    return completed.returncode


def mode_units() -> int:
    return _run([PYTHON, "-m", "pytest", "-q",
                 str(PKG_TESTS["knowledge"]), str(PKG_TESTS["ingestion"]), str(PKG_TESTS["retrieval"])])


def mode_differential() -> int:
    if _materialize_legacy_reference() != 0:
        print("<== legacy reference unavailable; differential lane aborted", flush=True)
        return 1
    return _run([PYTHON, "-m", "pytest", "-q",
                 str(PKG_TESTS["retrieval"] / "test_differential.py"),
                 str(PKG_TESTS["retrieval"] / "test_shadow_quality.py"),
                 str(PKG_TESTS["retrieval"] / "test_rag_e2e.py"),
                 str(API_TESTS / "test_differential_auth.py")])


def mode_acl() -> int:
    return _run([PYTHON, "-m", "pytest", "-q",
                 str(API_TESTS / "test_negative_security.py"),
                 str(API_TESTS / "test_canonical_negatives.py"),
                 "-k", "acl or workspace or collection or widen or leak or provenance or fallback or negative or denied or forbidden or escalation"])


def mode_api() -> int:
    return _run([PYTHON, "-m", "pytest", "-q", str(API_TESTS)])


def mode_legacy() -> int:
    """Focused legacy contract/security regression against the read-only reference."""
    if _materialize_legacy_reference() != 0:
        print("<== legacy reference unavailable; legacy lane aborted", flush=True)
        return 1
    legacy_src = LEGACY_REFERENCE / "cvg-master-rag-v2" / "src"
    tests_root = legacy_src / "tests"
    env = _env()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(legacy_src), str(ROOT), env.get("PYTHONPATH", "")])
    command = [PYTHON, "-m", "pytest", "-q",
               "-p", "scripts.phase13.legacy_reference_plugin",
               str(tests_root / "test_phase05_contract.py"),
               str(tests_root / "test_phase05_security.py"),
               str(tests_root / "test_phase06_rbac.py"),
               str(tests_root / "test_p0_closeout.py")]
    print(f"==> {' '.join(str(part) for part in command)}", flush=True)
    completed = subprocess.run(command, cwd=ROOT, env=env)
    print(f"<== exit {completed.returncode}", flush=True)
    return completed.returncode


def _benchmark_paths() -> list[str]:
    reference_src = LEGACY_REFERENCE / "cvg-master-rag-v2" / "src"
    return [str(ROOT / "packages" / name / "src") for name in ("knowledge", "ingestion", "retrieval")] + [
        str(reference_src)
    ]


def mode_benchmark() -> int:
    """Same-run legacy↔root budget check (root must stay within 2x legacy).

    Both sides are measured in the same process, under the same machine load,
    so the ratio — not the absolute milliseconds — is what the gate asserts.
    The legacy implementation comes from the materialized read-only reference
    (`.runtime/legacy-reference`), never from the retired checkout paths.

    The measurement runs in a re-exec'd interpreter whose PYTHONPATH carries
    only the retrieval packages and that reference: `apps/api/src` would
    otherwise shadow the legacy top-level `models`/`services` packages with
    same-named modules of their own.
    """
    if os.environ.get("RICK_BENCH_CLEAN_ENV") == "1":
        return _benchmark_worker()
    if not (LEGACY_REFERENCE / "cvg-master-rag-v2" / "src").is_dir():
        print("FAIL: legacy reference missing; run scripts/phase15/legacy_reference.py", flush=True)
        return 1
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(_benchmark_paths())
    env["RICK_BENCH_CLEAN_ENV"] = "1"
    completed = subprocess.run([PYTHON, str(Path(__file__).resolve()), "benchmark"],
                               cwd=ROOT, env=env)
    return completed.returncode


def _benchmark_worker() -> int:
    for path in _benchmark_paths():
        if path not in sys.path:
            sys.path.append(path)
    import time as _t

    from models.schemas import NormalizedDocument
    from rick_ingestion import RecursiveChunkingStrategy
    from rick_retrieval import BM25FReranker, rrf_fusion
    from services.chunker import recursive_chunk
    from services.vector_service import BM25FReranker as LegacyBM25F
    from services.vector_service import _rrf_fusion as legacy_rrf

    text_value = ("Mastite bovina: protocolo de ordenha e higiene. " * 60 + "\n\n") * 6
    doc = NormalizedDocument(document_id="d", source_type="txt", filename="f", workspace_id="w",
                             created_at="x", pages=[{"page_number": 1, "text": text_value}],
                             sections=[], metadata={}, raw_json_path="/tmp/x")
    strategy = RecursiveChunkingStrategy()

    def timed(fn, n=200):
        """Sample enough that a sub-millisecond op's p50 is not scheduler noise.

        The budget is asserted on `min_ms`: on a shared machine the fastest
        sample is the only statistic that isolates algorithmic cost from
        preemption, and both sides of the ratio are sampled the same way.
        """
        samples = sorted(((_t.perf_counter(), fn(), _t.perf_counter())[0:3:2]) for _ in range(n))
        deltas = sorted((end - start) * 1000 for start, end in samples)
        return {"min_ms": round(deltas[0], 4),
                "p50_ms": round(deltas[n // 2], 3),
                "p95_ms": round(deltas[int(n * 0.95)], 3)}

    dense = [{"chunk_id": f"c{i}", "document_id": "d", "workspace_id": "w", "text": "t",
              "collection_id": "c", "score": 1.0 / (i + 1)} for i in range(30)]
    sparse = [{"chunk_id": f"c{i}", "document_id": "d", "workspace_id": "w", "text": "t",
               "collection_id": "c", "score": 0.5, "sparse_score": 0.5} for i in range(0, 30, 2)]
    cands = [{**c, "confidence_score": 0.5, "document_filename": "f", "tags": []} for c in dense]
    result = {
        "legacy_chunk_ms": timed(lambda: recursive_chunk(doc)),
        "root_chunk_ms": timed(lambda: strategy.chunk(text=text_value, pages=[(1, text_value)],
                                                      document_id="d")),
        "legacy_rrf_ms": timed(lambda: legacy_rrf(dense, sparse)),
        "root_rrf_ms": timed(lambda: rrf_fusion(dense, sparse)),
        "legacy_rerank_ms": timed(lambda: LegacyBM25F().rerank("mastite bovina",
                                                                [dict(c) for c in cands])),
        "root_rerank_ms": timed(lambda: BM25FReranker().rerank("mastite bovina",
                                                                [dict(c) for c in cands])),
        "budget": "root must stay within 2x legacy (no unjustified doubling)",
        "note": "fixture-scoped, hermetic; live Qdrant/OpenAI excluded; both sides measured in the same run",
    }
    breached = False
    for key in ("chunk", "rrf", "rerank"):
        legacy_min = result[f"legacy_{key}_ms"]["min_ms"]
        root_min = result[f"root_{key}_ms"]["min_ms"]
        ratio = root_min / max(legacy_min, 1e-6)
        result[f"{key}_min_ratio"] = round(ratio, 3)
        if ratio > 2.0:
            print(f"BUDGET BREACH: root_{key} {ratio:.2f}x legacy (min_ms {root_min} vs {legacy_min})",
                  flush=True)
            breached = True
    out = ROOT / "docs" / "baselines" / "phase-1.4-perf.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    return 1 if breached else 0


def mode_full() -> int:
    results = [mode_units(), mode_differential(), mode_api()]
    return 0 if all(code == 0 for code in results) else 1


MODES = {"units": mode_units, "differential": mode_differential, "acl": mode_acl,
         "api": mode_api, "legacy": mode_legacy, "benchmark": mode_benchmark, "full": mode_full}
REFERENCE_MODES = {"units", "differential", "api", "legacy", "full"}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in MODES:
        print(f"usage: phase14.py <{'|'.join(sorted(MODES))}>", flush=True)
        return 2
    if argv[1] in REFERENCE_MODES and _materialize_legacy_reference() != 0:
        print("WARN: legacy reference unavailable; parity suites stay fail-closed", flush=True)
    return MODES[argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
