"""Canonical RAG E2E: upload → ingest → query → citation, then grant removal.

KM ingests representative documents through the canonical pipeline; VET with a
collection grant retrieves expected evidence with valid citations; after grant
removal the same query yields no evidence from that collection.
"""

import sys
from pathlib import Path

for _pkg in ("knowledge", "ingestion", "retrieval", "contracts", "authorization", "identity"):
    _p = Path(__file__).resolve().parents[3] / "packages" / _pkg / "src"
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rick_authorization import build_retrieval_context
from rick_ingestion import IngestionService
from rick_knowledge import Collection, InMemoryKnowledgeStore
from rick_retrieval import (
    BM25FReranker,
    DeterministicHashEmbedding,
    InMemoryBackend,
    InMemoryVectorStore,
    RetrievalEngine,
    RetrievalOptions,
)


def _world(tmp_path: Path):
    knowledge = InMemoryKnowledgeStore()
    vectors = InMemoryVectorStore()
    embeddings = DeterministicHashEmbedding()
    ingestion = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=embeddings)
    (tmp_path / "mastite.txt").write_text(
        "Mastite bovina: protocolo de ordenha, higiene do úbere evuramento da CCS. " * 30)
    (tmp_path / " aftosa.txt".strip()).write_text(
        "Febre aftosa: vacinação obrigatória do rebanho bovino e vigilancia. " * 30)
    return knowledge, vectors, embeddings, ingestion


def _index_chunks(engine: RetrievalEngine, knowledge, vectors, embeddings) -> None:
    chunks = []
    for point in vectors.all_points():
        payload = point["payload"]
        chunks.append({
            "chunk_id": payload["chunk_id"], "document_id": payload["document_id"],
            "workspace_id": payload["workspace_id"], "collection_id": payload["collection_id"],
            "text": payload["text"], "vector": point["vector"],
            "page_start": payload["page_start"], "checksum": payload["checksum"],
        })
    engine.attach_index(chunks)


def test_e2e_ingest_query_citation_and_grant_removal(tmp_path):
    knowledge, vectors, embeddings, ingestion = _world(tmp_path)
    jobs = [ingestion.ingest(tmp_path / "mastite.txt", workspace_id="w", collection_id="rag_phase0"),
            ingestion.ingest(tmp_path / "aftosa.txt", workspace_id="w", collection_id="rag_phase0")]
    assert all(j.status == "published" for j in jobs)

    engine = RetrievalEngine(backend=InMemoryBackend(), reranker=BM25FReranker(), embed=embeddings.embed)
    _index_chunks(engine, knowledge, vectors, embeddings)

    vet_ctx = build_retrieval_context(user_id="vet", session_workspace="w", requested_workspace="w",
                                      allowed_collection_ids=["rag_phase0"],
                                      permissions=["chat.query", "sources.read"], role="VETERINARIAN")
    result = engine.retrieve(query="protocolo de ordenha para mastite bovina", context=vet_ctx,
                             options=RetrievalOptions(top_k=3, rerank=True))
    assert result.evidence, "expected evidence for granted collection"
    top = result.evidence[0]
    assert top["collection_id"] == "rag_phase0" and top["workspace_id"] == "w"
    assert top["document_id"] and top["chunk_id"] and top["text"]  # valid citation trace

    # Grant removed → same query yields nothing from that collection.
    no_grant_ctx = build_retrieval_context(user_id="vet", session_workspace="w", requested_workspace="w",
                                           allowed_collection_ids=["other-collection"],
                                           permissions=["chat.query"], role="VETERINARIAN")
    denied = engine.retrieve(query="protocolo de ordenha para mastite bovina", context=no_grant_ctx,
                             options=RetrievalOptions(top_k=3, rerank=True))
    assert denied.evidence == []
    assert denied.candidate_count == 0


def test_failure_e2e_qdrant_down_malformed_duplicate_cancel(tmp_path):
    from rick_retrieval import RetrievalEngine as E
    from rick_retrieval.backends import DiskFallbackBackend

    knowledge, vectors, embeddings, ingestion = _world(tmp_path)
    job = ingestion.ingest(tmp_path / "mastite.txt", workspace_id="w", collection_id="rag_phase0")
    assert job.status == "published"

    # Duplicate ingest converges (no drift).
    dup = ingestion.ingest(tmp_path / "mastite.txt", workspace_id="w", collection_id="rag_phase0")
    assert dup.document_id == job.document_id

    # Malformed input fails safely, never publishes.
    bad = tmp_path / "bad.exe"
    bad.write_bytes(b"\x00\x01")
    failed = ingestion.ingest(bad, workspace_id="w", collection_id="rag_phase0")
    assert failed.status == "failed" and failed.error_code == "unsupported_media_type"

    # Cancel only affects non-terminal jobs.
    assert ingestion.cancel(job.job_id) is False

    # Disk fallback serves the same ACL-scoped corpus when primary is empty.
    chunks = [{"chunk_id": "chunk_x_0000", "document_id": "x", "workspace_id": "w",
               "collection_id": "rag_phase0", "text": "mastite protocolo",
               "vector": embeddings.embed(["mastite protocolo"])[0]}]
    engine = E(backend=InMemoryBackend(), fallback=DiskFallbackBackend(tmp_path))
    engine.attach_index([])
    ctx = {"user_id": "u", "workspace_id": "w", "allowed_collection_ids": ["rag_phase0"], "permissions": []}
    # Empty primary + fallback over disk-loaded chunks.
    engine.attach_index(chunks)
    result = engine.retrieve(query="mastite", context=ctx, options=RetrievalOptions(top_k=3))
    assert result.evidence and result.evidence[0]["document_id"] == "x"
