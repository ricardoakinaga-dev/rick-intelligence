#!/usr/bin/env python3
"""Phase 1.4 lanes: canonical RAG packages, differential, shadow, E2E, ACL, perf."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_TESTS = ROOT / "apps" / "api" / "tests"
PKG_TESTS = {p: ROOT / "packages" / p / "tests" for p in
             ("knowledge", "ingestion", "retrieval", "contracts", "authorization", "identity")}


def _env(legacy: str = "last"):
    """legacy: 'last' (default; app-first, tests self-manage legacy loads),
    'first' (pure-legacy lanes where cvg `services`/`models`/`core` must win),
    'none' (hermetic package units)."""
    import os

    env = os.environ.copy()
    parts = [str(ROOT / "apps" / "api" / "src")] + [
        str(ROOT / "packages" / p / "src") for p in
        ("contracts", "authorization", "identity", "observability", "knowledge", "ingestion", "retrieval", "providers", "locking", "professor")]
    legacy_src = str(ROOT / "cvg-master-rag-v2" / "src")
    if legacy == "first":
        # Legacy CVG tests import top-level `services`/`models`/`core` packages;
        # the legacy src must precede apps/api/src (which has same-named modules).
        parts.insert(0, legacy_src)
    elif legacy == "last":
        parts.append(legacy_src)
    env["PYTHONPATH"] = os.pathsep.join(parts + [env.get("PYTHONPATH", "")])
    env.setdefault("RAG_SKIP_QDRANT_BOOTSTRAP", "1")
    env.setdefault("SESSION_COOKIE_SECURE", "false")
    env.setdefault("OPENAI_API_KEY", "")
    env.setdefault("RERANKING_ENABLED", "false")
    return env


def _run(cmd, *, legacy: str = "last"):
    print(f"==> {' '.join(cmd)}", flush=True)
    completed = subprocess.run(cmd, cwd=ROOT, env=_env(legacy))
    print(f"<== exit {completed.returncode}", flush=True)
    return completed.returncode


def mode_units() -> int:
    return _run([sys.executable, "-m", "pytest", "-q",
                 str(PKG_TESTS["knowledge"]), str(PKG_TESTS["ingestion"]), str(PKG_TESTS["retrieval"])],
                legacy="none")


def mode_differential() -> int:
    return _run([sys.executable, "-m", "pytest", "-q",
                 str(PKG_TESTS["retrieval"] / "test_differential.py"),
                 str(PKG_TESTS["retrieval"] / "test_shadow_quality.py"),
                 str(PKG_TESTS["retrieval"] / "test_rag_e2e.py"),
                 str(API_TESTS / "test_differential_auth.py")], legacy="last")


def mode_acl() -> int:
    return _run([sys.executable, "-m", "pytest", "-q",
                 str(API_TESTS / "test_negative_security.py"),
                 str(API_TESTS / "test_canonical_negatives.py"),
                 "-k", "acl or workspace or collection or widen or leak or provenance or fallback or negative or denied or forbidden or escalation"],
                legacy="none")


def mode_api() -> int:
    return _run([sys.executable, "-m", "pytest", "-q", str(API_TESTS)], legacy="last")


def mode_legacy() -> int:
    return _run([sys.executable, "-m", "pytest", "-q",
                 "cvg-master-rag-v2/src/tests/test_phase05_contract.py",
                 "cvg-master-rag-v2/src/tests/test_phase05_security.py",
                 "cvg-master-rag-v2/src/tests/test_phase06_rbac.py",
                 "cvg-master-rag-v2/src/tests/test_p0_closeout.py"], legacy="first")


def mode_benchmark() -> int:
    for _pkg in ("knowledge", "ingestion", "retrieval"):
        sys.path.insert(0, str(ROOT / "packages" / _pkg / "src"))
    sys.path.insert(0, str(ROOT / "cvg-master-rag-v2" / "src"))
    import time as _t

    from rick_ingestion import RecursiveChunkingStrategy
    from rick_retrieval import BM25FReranker, rrf_fusion
    from services.chunker import recursive_chunk
    from models.schemas import NormalizedDocument

    text = ("Mastite bovina: protocolo de ordenha e higiene. " * 60 + "\n\n") * 6
    doc = NormalizedDocument(document_id="d", source_type="txt", filename="f", workspace_id="w",
                             created_at="x", pages=[{"page_number": 1, "text": text}],
                             sections=[], metadata={}, raw_json_path="/tmp/x")
    strategy = RecursiveChunkingStrategy()

    def timed(fn, n=20):
        samples = sorted(((_t.perf_counter(), fn(), _t.perf_counter())[0:3:2]) for _ in range(n))
        deltas = sorted((end - start) * 1000 for start, end in samples)
        return {"p50_ms": round(deltas[n // 2], 3), "p95_ms": round(deltas[int(n * 0.95)], 3)}

    dense = [{"chunk_id": f"c{i}", "document_id": "d", "workspace_id": "w", "text": "t",
              "collection_id": "c", "score": 1.0 / (i + 1)} for i in range(30)]
    sparse = [{"chunk_id": f"c{i}", "document_id": "d", "workspace_id": "w", "text": "t",
               "collection_id": "c", "score": 0.5, "sparse_score": 0.5} for i in range(0, 30, 2)]
    cands = [{**c, "confidence_score": 0.5, "document_filename": "f", "tags": []} for c in dense]
    result = {
        "legacy_chunk_ms": timed(lambda: recursive_chunk(doc)),
        "root_chunk_ms": timed(lambda: strategy.chunk(text=text, pages=[(1, text)], document_id="d")),
        "legacy_rrf_ms": timed(lambda: __import__("services.vector_service", fromlist=["x"])._rrf_fusion(dense, sparse)),
        "root_rrf_ms": timed(lambda: rrf_fusion(dense, sparse)),
        "legacy_rerank_ms": timed(lambda: __import__("services.vector_service", fromlist=["x"]).BM25FReranker().rerank("mastite bovina", [dict(c) for c in cands])),
        "root_rerank_ms": timed(lambda: BM25FReranker().rerank("mastite bovina", [dict(c) for c in cands])),
        "budget": "root must stay within 2x legacy (no unjustified doubling)",
        "note": "fixture-scoped, hermetic; live Qdrant/OpenAI excluded",
    }
    out = ROOT / "docs" / "baselines" / "phase-1.4-perf.json"
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2), flush=True)
    for key in ("chunk", "rrf", "rerank"):
        ratio = result[f"root_{key}_ms"]["p50_ms"] / max(result[f"legacy_{key}_ms"]["p50_ms"], 1e-6)
        if ratio > 2.0:
            print(f"BUDGET BREACH: root_{key} {ratio:.2f}x legacy", flush=True)
            return 1
    return 0


def mode_full() -> int:
    results = [mode_units(), mode_differential(), mode_api(), mode_legacy()]
    return 0 if all(code == 0 for code in results) else 1


MODES = {"units": mode_units, "differential": mode_differential, "acl": mode_acl,
         "api": mode_api, "legacy": mode_legacy, "benchmark": mode_benchmark, "full": mode_full}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in MODES:
        print(f"usage: phase14.py <{'|'.join(sorted(MODES))}>", flush=True)
        return 2
    return MODES[argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
