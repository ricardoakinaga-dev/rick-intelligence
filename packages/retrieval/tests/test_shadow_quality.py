"""Shadow dual-run + quality equivalence (fixture-scoped, no live services).

Runs legacy fusion/rerank and the canonical engine over identical candidate
sets; compares document IDs, chunk IDs, rank overlap and top-k overlap.
Tolerated: float rounding. Not tolerated: different sources, missing filters,
ID changes, provenance loss.
"""

import importlib.util as _importlib_util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for _pkg in ("knowledge", "ingestion", "retrieval", "contracts", "authorization", "identity"):
    _p = ROOT / "packages" / _pkg / "src"
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
LEGACY_SRC = str(ROOT / "cvg-master-rag-v2" / "src")
if LEGACY_SRC not in sys.path:
    sys.path.append(LEGACY_SRC)


def _load(name, relpath):
    """Read-only legacy loader with package-collision purge (see test_differential)."""
    key = f"legacy_shadow_{name}"
    if key in sys.modules:
        return sys.modules[key]
    saved_path = list(sys.path)
    saved = {k: sys.modules.pop(k) for k in
             [m for m in sys.modules if m.split(".")[0] in ("services", "core", "models")]}
    try:
        sys.path.insert(0, LEGACY_SRC)
        spec = _importlib_util.spec_from_file_location(key, ROOT / relpath)
        module = _importlib_util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = saved_path
        for mod in [m for m in sys.modules if m.split(".")[0] in ("services", "core", "models")]:
            sys.modules.pop(mod, None)
        sys.modules.update(saved)


legacy_vectors = _load("vectors", "cvg-master-rag-v2/src/services/vector_service.py")

from rick_retrieval import (  # noqa: E402
    BM25FReranker,
    RetrievalEngine,
    RetrievalOptions,
    rrf_fusion,
)


def _candidates():
    texts = [
        ("c0", "d0", "Mastite bovina: protocolo de ordenha e higiene do úbere."),
        ("c1", "d0", "A CCS do rebanho cai com manejo preventivo da ordenha."),
        ("c2", "d1", "Febre aftosa: vacinação obrigatória do rebanho bovino."),
        ("c3", "d2", "Fotossíntese e clorofila nas plantas forrageiras."),
        ("c4", "d1", "Vigilância sanitária e controle de foco de aftosa."),
    ]
    dense, sparse = [], []
    for rank, (cid, doc, text) in enumerate(texts):
        dense.append({"chunk_id": cid, "document_id": doc, "workspace_id": "w",
                      "collection_id": "rag_phase0", "text": text, "score": 0.9 - rank * 0.1})
        if rank % 2 == 0:
            sparse.append({"chunk_id": cid, "document_id": doc, "workspace_id": "w",
                           "collection_id": "rag_phase0", "text": text, "score": 0.6,
                           "sparse_score": 0.6})
    return dense, sparse


def _overlap(a: list[str], b: list[str], k: int) -> float:
    sa, sb = set(a[:k]), set(b[:k])
    return len(sa & sb) / max(1, min(k, len(sa | sb)))


def test_shadow_rank_overlap():
    dense, sparse = _candidates()
    legacy_ranked = legacy_vectors._rrf_fusion([dict(c) for c in dense], [dict(c) for c in sparse], k=60)
    root_ranked = rrf_fusion([dict(c) for c in dense], [dict(c) for c in sparse], k=60)
    legacy_ids = [c["chunk_id"] for c in legacy_ranked]
    root_ids = [c["chunk_id"] for c in root_ranked]
    assert legacy_ids == root_ids  # exact rank parity on shared fixtures
    assert _overlap(legacy_ids, root_ids, 3) == 1.0
    # Document-level overlap is total; no source substitution.
    assert {c["document_id"] for c in legacy_ranked} == {c["document_id"] for c in root_ranked}


def test_shadow_rerank_overlap_and_quality():
    dense, sparse = _candidates()
    for cand in dense + sparse:
        cand["confidence_score"] = 0.5
        cand["document_filename"] = "f.pdf"
        cand["tags"] = []
    legacy_out = legacy_vectors.BM25FReranker().rerank("protocolo de mastite bovina", [dict(c) for c in dense])
    root_out = BM25FReranker().rerank("protocolo de mastite bovina", [dict(c) for c in dense])
    legacy_ids = [c["chunk_id"] for c in legacy_out]
    root_ids = [c["chunk_id"] for c in root_out]
    assert legacy_ids == root_ids
    # Quality: the mastitis protocol chunk outranks the photosynthesis chunk.
    assert root_ids.index("c0") < root_ids.index("c3")
    # Recall@3 for the mastitis topic: both mastitis chunks of d0 present.
    assert {"c0", "c1"} <= set(root_ids[:3])


def test_engine_recall_hitrate_mrr_on_fixtures():
    from rick_retrieval import DeterministicHashEmbedding, InMemoryBackend

    embedder = DeterministicHashEmbedding()
    texts = [
        ("d0", "Mastite bovina protocolo de ordenha e higiene"),
        ("d0", "CCS do rebanho e manejo preventivo da ordenha"),
        ("d1", "Febre aftosa vacinação obrigatória"),
        ("d2", "Fotossíntese e clorofila das forrageiras"),
    ]
    vectors = embedder.embed([t for _, t in texts])
    chunks = [
        {"chunk_id": f"c{i}", "document_id": doc, "workspace_id": "w", "collection_id": "rag_phase0",
         "text": text, "vector": vec}
        for i, ((doc, text), vec) in enumerate(zip(texts, vectors))
    ]
    engine = RetrievalEngine(backend=InMemoryBackend(), embed=embedder.embed)
    engine.attach_index(chunks)
    ctx = {"user_id": "u", "workspace_id": "w", "allowed_collection_ids": ["rag_phase0"], "permissions": []}
    result = engine.retrieve(query="protocolo de ordenha mastite bovina", context=ctx,
                             options=RetrievalOptions(top_k=4))
    ids = [e["chunk_id"] for e in result.evidence]
    relevant = {"c0", "c1"}
    retrieved = set(ids[:2])
    recall_at_2 = len(relevant & retrieved) / len(relevant)
    hit = 1.0 if relevant & set(ids) else 0.0
    mrr = next((1.0 / (rank + 1) for rank, cid in enumerate(ids) if cid in relevant), 0.0)
    assert recall_at_2 >= 0.5 and hit == 1.0 and mrr >= 0.5
