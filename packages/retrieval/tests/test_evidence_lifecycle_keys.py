"""Evidence keeps the lifecycle keys the API projection gate reads (A02).

``apps/api`` drops every evidence row whose tenant, workspace, collection or
document id is missing before it can be shown, so the engine must hand those
four keys back exactly as they were indexed — including for a wildcard grant
that spans more than one collection.
"""

from __future__ import annotations

from rick_retrieval import (
    BM25FReranker,
    DeterministicHashEmbedding,
    InMemoryBackend,
    RetrievalEngine,
    RetrievalOptions,
)

TENANT = "default"
WORKSPACE = "w"


def _chunk(embeddings, *, chunk_id: str, document_id: str, collection_id: str, text: str) -> dict:
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "tenant_id": TENANT,
        "workspace_id": WORKSPACE,
        "collection_id": collection_id,
        "text": text,
        "vector": embeddings.embed([text])[0],
        "page_start": 1,
        "checksum": f"sha256:{chunk_id}",
    }


def _engine(chunks_factory) -> tuple[RetrievalEngine, DeterministicHashEmbedding]:
    embeddings = DeterministicHashEmbedding()
    engine = RetrievalEngine(
        backend=InMemoryBackend(), reranker=BM25FReranker(), embed=embeddings.embed,
    )
    engine.attach_index(chunks_factory(embeddings))
    return engine, embeddings


def test_every_evidence_row_carries_the_keys_the_lifecycle_gate_reads() -> None:
    engine, embeddings = _engine(lambda e: [
        _chunk(e, chunk_id="chunk-a", document_id="doc-a", collection_id="rag_phase0",
               text="protocolo de ordenha para mastite bovina"),
        _chunk(e, chunk_id="chunk-b", document_id="doc-b", collection_id="vet-library",
               text="higiene rigorosa na ordenha previne mastite"),
    ])
    chunks = [
        _chunk(embeddings, chunk_id="chunk-a", document_id="doc-a", collection_id="rag_phase0",
               text="protocolo de ordenha para mastite bovina"),
        _chunk(embeddings, chunk_id="chunk-b", document_id="doc-b", collection_id="vet-library",
               text="higiene rigorosa na ordenha previne mastite"),
    ]
    context = {
        "user_id": "admin",
        "tenant_id": TENANT,
        "workspace_id": WORKSPACE,
        "allowed_collection_ids": ["*"],
        "permissions": ["sources.read"],
    }

    result = engine.retrieve(query="higiene ordenha mastite", context=context,
                             options=RetrievalOptions(top_k=5, rerank=True))

    assert len(result.evidence) == 2
    assert result.selected_count == len(result.evidence)
    indexed = {(chunk["collection_id"], chunk["document_id"]): chunk for chunk in chunks}
    for row in result.evidence:
        key = (row["collection_id"], row["document_id"])
        assert key in indexed
        assert row["tenant_id"] == TENANT
        assert row["workspace_id"] == WORKSPACE
        assert row["collection_id"] and row["document_id"] and row["chunk_id"]


def test_foreign_scope_candidates_never_reach_the_evidence_projection() -> None:
    engine, _ = _engine(lambda e: [
        _chunk(e, chunk_id="chunk-a", document_id="doc-a", collection_id="rag_phase0",
               text="protocolo de ordenha para mastite bovina"),
        _chunk(e, chunk_id="chunk-b", document_id="doc-b", collection_id="secret",
               text="protocolo de ordenha para mastite bovina"),
    ])
    context = {
        "user_id": "admin",
        "tenant_id": TENANT,
        "workspace_id": WORKSPACE,
        "allowed_collection_ids": ["rag_phase0"],
        "permissions": ["sources.read"],
    }

    result = engine.retrieve(query="higiene ordenha mastite", context=context,
                             options=RetrievalOptions(top_k=5, rerank=True))

    assert [row["collection_id"] for row in result.evidence] == ["rag_phase0"]
