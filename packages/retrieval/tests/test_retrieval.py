"""Retrieval unit tests: RRF math, rerank, ACL, budget, quality helpers."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rick_retrieval import (
    BM25FReranker,
    DisabledReranker,
    InMemoryBackend,
    RetrievalEngine,
    RetrievalOptions,
    compute_confidence,
    rrf_fusion,
    sparse_hash,
    sparse_overlap_score,
    tokenize_terms,
)


def _cand(chunk_id, score=0.0, doc="d", ws="w", coll="rag_phase0", text="t"):
    return {"chunk_id": chunk_id, "document_id": doc, "workspace_id": ws,
            "tenant_id": "default", "collection_id": coll, "text": text, "score": score}


def test_rrf_math_and_constant():
    from rick_retrieval.fusion import RRF_K

    assert RRF_K == 60
    dense = [_cand("a", 0.9), _cand("b", 0.8)]
    sparse = [_cand("b", 0.7), _cand("c", 0.6)]
    fused = rrf_fusion(dense, sparse)
    order = [c["chunk_id"] for c in fused]
    assert order[0] == "b"  # present in both lists
    b = next(c for c in fused if c["chunk_id"] == "b")
    assert abs(b["score"] - (1 / 62 + 1 / 61)) < 1e-9


def test_rrf_preserves_complete_provenance_across_sources():
    dense = [_cand("p", 0.9, text="grounded text")]
    dense[0].update({"source": "source.pdf", "page_start": 2})
    sparse = [_cand("p", 0.7, text="grounded text")]
    sparse[0].update({
        "source": "source.pdf",
        "title": "Source title",
        "page_end": 4,
        "document_filename": "source.pdf",
        "checksum": "sha256:fixture",
    })

    fused = rrf_fusion(dense, sparse)[0]

    assert fused["source"] == "source.pdf"
    assert fused["title"] == "Source title"
    assert fused["page_start"] == 2 and fused["page_end"] == 4
    assert fused["document_filename"] == "source.pdf"
    assert fused["checksum"] == "sha256:fixture"


def test_tokenizer_and_sparse_determinism():
    assert "de" not in tokenize_terms("Tratamento de mastite")
    assert sparse_hash("mastite") == sparse_hash("mastite")
    assert sparse_overlap_score("mastite bovina", "mastite bovina protocolo") > \
        sparse_overlap_score("mastite bovina", "fotossintese clorofila")


def test_bm25f_rerank_deterministic_and_stable():
    reranker = BM25FReranker()
    cands = [_cand("a", 0.5, text="mastite bovina protocolo de ordenha"),
             _cand("b", 0.9, text="fotossintese e clorofila nas plantas"),
             _cand("c", 0.4, text="mastite tratamento antibiotico")]
    for c in cands:
        c["confidence_score"] = 0.5
    first = reranker.rerank("tratamento de mastite bovina", cands)
    second = reranker.rerank("tratamento de mastite bovina", cands)
    assert [c["chunk_id"] for c in first] == [c["chunk_id"] for c in second]
    assert first[0]["chunk_id"] in ("a", "c")
    assert all("original_score" in c and "bm25f_score" in c for c in first)
    assert DisabledReranker().rerank("q", cands) == cands


def _index():
    return [
        {"chunk_id": "chunk_d1_0000", "document_id": "d1", "tenant_id": "default", "workspace_id": "w",
         "collection_id": "rag_phase0", "text": "Mastite bovina: protocolo de ordenha e higiene.",
         "vector": [1.0, 0.0]},
        {"chunk_id": "chunk_d2_0000", "document_id": "d2", "tenant_id": "default", "workspace_id": "w",
         "collection_id": "secret", "text": "Mastite bovina: protocolo secreto.",
         "vector": [1.0, 0.0]},
        {"chunk_id": "chunk_d3_0000", "document_id": "d3", "tenant_id": "default", "workspace_id": "foreign",
         "collection_id": "rag_phase0", "text": "Mastite bovina em outra workspace.",
         "vector": [1.0, 0.0]},
    ]


def test_workspace_and_collection_acl_enforced():
    engine = RetrievalEngine(backend=InMemoryBackend())
    engine.attach_index(_index())
    ctx = {"user_id": "vet", "tenant_id": "default", "workspace_id": "w",
           "allowed_collection_ids": ["rag_phase0"], "permissions": []}
    result = engine.retrieve(query="protocolo de mastite bovina", context=ctx,
                             options=RetrievalOptions(top_k=5))
    ids = {e["document_id"] for e in result.evidence}
    assert "d1" in ids and "d2" not in ids and "d3" not in ids


def test_context_budget_and_evidence_shape():
    engine = RetrievalEngine(backend=InMemoryBackend())
    engine.attach_index(_index())
    ctx = {"user_id": "u", "tenant_id": "default", "workspace_id": "w",
           "allowed_collection_ids": ["*"], "permissions": []}
    result = engine.retrieve(query="mastite", context=ctx,
                             options=RetrievalOptions(top_k=5, max_context_chars=20))
    assert sum(len(e["text"]) for e in result.evidence) <= 60
    for ev in result.evidence:
        assert {"evidence_id", "document_id", "chunk_id", "workspace_id", "collection_id",
                "text", "checksum", "score", "rank"} <= set(ev)


def test_confidence_bounds():
    assert 0.0 <= compute_confidence({"dense_score": 0.8, "sparse_score": 0.5, "score": 0.03}, "mastite bovina") <= 1.0
    assert compute_confidence({"dense_score": 0.0, "sparse_score": 0.0, "score": 0.0}) == 0.0


def test_disk_fallback_enforces_identical_acl():
    from rick_retrieval import DiskFallbackBackend, RetrievalEngine, RetrievalOptions

    chunks = [
        {"chunk_id": "c1", "document_id": "d1", "tenant_id": "default", "workspace_id": "w",
         "collection_id": "rag_phase0", "text": "mastite protocolo de ordenha",
         "vector": [1.0, 0.0]},
        {"chunk_id": "c2", "document_id": "d9", "tenant_id": "default", "workspace_id": "w",
         "collection_id": "secret", "text": "mastite protocolo secreto restrito",
         "vector": [1.0, 0.0]},
    ]
    engine = RetrievalEngine(backend=InMemoryBackend(), fallback=DiskFallbackBackend(__import__("pathlib").Path("/tmp")))
    engine.attach_index([])  # primary empty -> fallback path over disk-loaded chunks
    engine.attach_index(chunks)
    ctx = {"user_id": "u", "tenant_id": "default", "workspace_id": "w",
           "allowed_collection_ids": ["rag_phase0"], "permissions": []}
    result = engine.retrieve(query="mastite protocolo", context=ctx, options=RetrievalOptions(top_k=5))
    assert {e["document_id"] for e in result.evidence} == {"d1"}


def test_provenance_non_leak_on_denial():
    from rick_retrieval import InMemoryBackend, RetrievalEngine, RetrievalOptions

    secret_text = "UNIQUE-SECRETPHRASE protocolo confidencial"
    engine = RetrievalEngine(backend=InMemoryBackend())
    engine.attach_index([
        {"chunk_id": "cs", "document_id": "dsecret", "tenant_id": "default", "workspace_id": "w",
         "collection_id": "secret", "text": secret_text, "vector": [1.0, 0.0]},
    ])
    ctx = {"user_id": "u", "tenant_id": "default", "workspace_id": "w",
           "allowed_collection_ids": ["rag_phase0"], "permissions": []}
    result = engine.retrieve(query="UNIQUE-SECRETPHRASE", context=ctx, options=RetrievalOptions(top_k=5))
    assert result.evidence == []
    assert "UNIQUE-SECRETPHRASE" not in str(result.evidence)
