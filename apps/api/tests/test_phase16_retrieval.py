"""Direct root retrieval refresh proof for the Phase 1.6 lifecycle."""

from __future__ import annotations

from rick_retrieval import DeterministicHashEmbedding, InMemoryVectorStore
from rick_knowledge import Document, InMemoryKnowledgeStore
from services.retrieval_service import RetrievalApplicationService


def test_attach_points_refreshes_provenance_and_removes_stale_index_state() -> None:
    embeddings = DeterministicHashEmbedding()
    vectors = InMemoryVectorStore()
    retrieval = RetrievalApplicationService(knowledge=None, vectors=vectors, embeddings=embeddings)
    text = "Protocolo de higiene beta para manejo seguro."
    point = {
        "point_id": "point-phase16-beta",
        "vector": embeddings.embed([text])[0],
        "payload": {
            "chunk_id": "chunk-phase16-beta",
            "document_id": "doc-phase16-beta",
            "tenant_id": "default",
            "workspace_id": "default",
            "collection_id": "rag_phase0",
            "text": text,
            "document_filename": "beta.txt",
            "title": "beta.txt",
            "page_start": 2,
            "page_end": 3,
            "checksum": "sha256:phase16-beta",
        },
    }

    retrieval.attach_points([point])
    result = retrieval.retrieve(
        query="higiene beta manejo",
        context={
            "user_id": "km",
            "tenant_id": "default",
            "workspace_id": "default",
            "allowed_collection_ids": ["rag_phase0"],
            "permissions": ["chat.query"],
        },
        top_k=3,
    )
    assert result.selected_count == 1
    assert result.evidence[0].document_id == "doc-phase16-beta"
    assert result.evidence[0].title == "beta.txt"
    assert result.evidence[0].page_start == 2
    assert result.evidence[0].page_end == 3
    assert result.evidence[0].checksum == "sha256:phase16-beta"

    retrieval.attach_points([])
    refreshed = retrieval.retrieve(
        query="higiene beta manejo",
        context={
            "user_id": "km",
            "tenant_id": "default",
            "workspace_id": "default",
            "allowed_collection_ids": ["rag_phase0"],
            "permissions": ["chat.query"],
        },
        top_k=3,
    )
    assert refreshed.evidence == []


def test_refresh_excludes_points_for_unpublished_or_deleted_metadata() -> None:
    embeddings = DeterministicHashEmbedding()
    knowledge = InMemoryKnowledgeStore()
    knowledge.upsert_document(
        Document(
            document_id="doc-live",
            workspace_id="default",
            collection_id="rag_phase0",
            tenant_id="default",
            status="published",
        )
    )
    knowledge.upsert_document(
        Document(
            document_id="doc-failed",
            workspace_id="default",
            collection_id="rag_phase0",
            tenant_id="default",
            status="processing",
        )
    )
    live_text = "Protocolo publicado para higiene segura."
    failed_text = "UNIQUE-FAILED-CONTENT protocolo secreto."
    points = []
    for document_id, text in (("doc-live", live_text), ("doc-failed", failed_text)):
        points.append(
            {
                "point_id": f"point-{document_id}",
                "vector": embeddings.embed([text])[0],
                "payload": {
                    "chunk_id": f"chunk-{document_id}",
                    "document_id": document_id,
                    "tenant_id": "default",
                    "workspace_id": "default",
                    "collection_id": "rag_phase0",
                    "text": text,
                    "document_filename": f"{document_id}.txt",
                    "title": f"{document_id}.txt",
                    "page_start": 1,
                    "page_end": 1,
                    "checksum": f"sha256:{document_id}",
                },
            }
        )

    retrieval = RetrievalApplicationService(
        knowledge=knowledge,
        vectors=InMemoryVectorStore(),
        embeddings=embeddings,
    )
    retrieval.attach_points(points)
    result = retrieval.retrieve(
        query="UNIQUE-FAILED-CONTENT",
        context={
            "user_id": "km",
            "tenant_id": "default",
            "workspace_id": "default",
            "allowed_collection_ids": ["rag_phase0"],
            "permissions": ["chat.query"],
        },
        top_k=3,
    )

    assert "doc-failed" not in {item.document_id for item in result.evidence}
