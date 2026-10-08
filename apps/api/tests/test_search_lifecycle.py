"""A02 regressions: an archived collection must never come back from search.

The lifecycle verdict comes from the same authority the catalog and the
Professor already consult (``store.get_collection`` / ``store.get_document``),
revalidated at query admission and again at the response projection. The index
cache may be hot or cold; the store is what decides.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import login_as, make_settings
from rick_knowledge import Collection, Document, InMemoryKnowledgeStore, SQLiteKnowledgeStore
from rick_retrieval import DeterministicHashEmbedding, QdrantBackend
from services.knowledge_service import (
    KnowledgeApplicationService,
    LifecycleAuthorityError,
)
from services.retrieval_service import RetrievalApplicationService

TENANT = "default"
WORKSPACE = "default"
COLLECTION = "rag_phase0"
TEXT = "Higiene rigorosa na ordenha previne mastite bovina."


def _document(document_id: str = "doc-a02") -> Document:
    return Document(
        tenant_id=TENANT, workspace_id=WORKSPACE, collection_id=COLLECTION,
        document_id=document_id, status="published", title="ordenha.pdf",
        filename="ordenha.pdf", display_filename="ordenha.pdf",
    )


def _active_store(store=None) -> InMemoryKnowledgeStore:
    knowledge = store if store is not None else InMemoryKnowledgeStore()
    knowledge.upsert_collection(Collection(
        tenant_id=TENANT, workspace_id=WORKSPACE, collection_id=COLLECTION,
        status="active",
    ))
    knowledge.upsert_document(_document())
    return knowledge


def _archive(knowledge) -> None:
    KnowledgeApplicationService(knowledge).archive_collection(
        workspace_id=WORKSPACE, tenant_id=TENANT, collection_id=COLLECTION,
    )


def _point(embeddings, *, collection_id: str = COLLECTION, document_id: str = "doc-a02") -> dict:
    return {
        "point_id": f"point-{document_id}",
        "vector": embeddings.embed([TEXT])[0],
        "payload": {
            "chunk_id": f"chunk-{document_id}",
            "document_id": document_id,
            "tenant_id": TENANT,
            "workspace_id": WORKSPACE,
            "collection_id": collection_id,
            "text": TEXT,
            "document_filename": "ordenha.pdf",
            "source": "ordenha.pdf",
            "title": "ordenha.pdf",
            "page_start": 2,
            "page_end": 3,
            "section": "Ordenha",
            "checksum": "sha256:a02",
            "document_version": "v1",
        },
    }


def _service(*, knowledge, points, backend=None) -> RetrievalApplicationService:
    embeddings = DeterministicHashEmbedding()
    service = RetrievalApplicationService(knowledge=knowledge, embeddings=embeddings, backend=backend)
    service.attach_points([_point(embeddings, **kwargs) for kwargs in points])
    return service


def _context(*, allowed: list[str]) -> dict:
    return {
        "user_id": "admin",
        "tenant_id": TENANT,
        "workspace_id": WORKSPACE,
        "allowed_collection_ids": allowed,
        "permissions": ["sources.read"],
    }


def test_active_collection_preserves_ranking_and_provenance() -> None:
    knowledge = _active_store()
    service = _service(knowledge=knowledge, points=[{}])

    result = service.retrieve(query="higiene ordenha", context=_context(allowed=[COLLECTION]), top_k=3)

    assert len(result.evidence) == 1
    item = result.evidence[0]
    assert item.document_id == "doc-a02"
    assert item.collection_id == COLLECTION
    assert item.title == "ordenha.pdf"
    assert item.page_start == 2 and item.page_end == 3
    assert item.checksum == "sha256:a02"
    assert item.section == "Ordenha"
    assert item.retrieval_quality_score > 0
    assert result.selected_count == 1
    assert result.metadata.get("authorization") != "lifecycle_denied"


def test_archived_collection_is_denied_on_a_hot_index() -> None:
    knowledge = _active_store()
    service = _service(knowledge=knowledge, points=[{}])
    warm = service.retrieve(query="higiene ordenha", context=_context(allowed=[COLLECTION]))
    assert len(warm.evidence) == 1

    _archive(knowledge)

    scoped = service.retrieve(query="higiene ordenha", context=_context(allowed=[COLLECTION]))
    assert scoped.evidence == []
    assert scoped.selected_count == 0
    assert scoped.metadata["authorization"] == "lifecycle_denied"

    wildcard = service.retrieve(query="higiene ordenha", context=_context(allowed=["*"]))
    assert wildcard.evidence == []
    assert wildcard.selected_count == 0


def test_archived_collection_is_denied_on_a_cold_index() -> None:
    knowledge = _active_store()
    embeddings = DeterministicHashEmbedding()
    points = [_point(embeddings)]
    service = RetrievalApplicationService(knowledge=knowledge, embeddings=embeddings)
    service.attach_points(points)
    assert len(service.retrieve(query="higiene ordenha", context=_context(allowed=[COLLECTION])).evidence) == 1

    _archive(knowledge)
    # A cold index rehydrates every point after the archive: the store, not
    # the cache, is what has to keep the archived collection out.
    service.attach_points(points)

    cold = service.retrieve(query="higiene ordenha", context=_context(allowed=[COLLECTION]))
    assert cold.evidence == []
    assert cold.metadata["authorization"] == "lifecycle_denied"


def test_unpublished_document_is_dropped_at_the_response_edge() -> None:
    knowledge = _active_store()
    service = _service(knowledge=knowledge, points=[{}])
    assert len(service.retrieve(query="higiene ordenha", context=_context(allowed=[COLLECTION])).evidence) == 1

    document = knowledge.get_document("doc-a02", tenant_id=TENANT, workspace_id=WORKSPACE)
    document.status = "processing"
    knowledge.upsert_document(document)

    result = service.retrieve(query="higiene ordenha", context=_context(allowed=[COLLECTION]))
    assert result.evidence == []
    assert result.metadata.get("authorization") != "lifecycle_denied"


def test_lifecycle_authority_failure_denies_the_query() -> None:
    embeddings = DeterministicHashEmbedding()

    class BrokenStore:
        def get_collection(self, *args, **kwargs):
            raise RuntimeError("knowledge store is down")

    for knowledge in (None, BrokenStore()):
        service = RetrievalApplicationService(knowledge=knowledge, embeddings=embeddings)
        service.attach_points([_point(embeddings)])
        with pytest.raises(LifecycleAuthorityError):
            service.retrieve(query="higiene ordenha", context=_context(allowed=[COLLECTION]))


class _RemoteStore:
    """Authorized remote adapter stub for the Qdrant backend."""

    def __init__(self, hits: list[dict]) -> None:
        self.hits = hits
        self.calls: list[dict] = []

    def search(self, query_vector=None, *, tenant_id, workspace_id,
               allowed_collection_ids, limit=10, **kwargs):
        self.calls.append({
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "allowed_collection_ids": list(allowed_collection_ids),
        })
        return list(self.hits)


def _remote_service(knowledge) -> tuple[RetrievalApplicationService, _RemoteStore]:
    embeddings = DeterministicHashEmbedding()
    payload = _point(embeddings)["payload"]
    store = _RemoteStore([{"payload": payload, "score": 0.91}])
    service = RetrievalApplicationService(
        knowledge=knowledge, embeddings=embeddings, backend=QdrantBackend(store),
    )
    service.attach_points([_point(embeddings)])
    return service, store


def test_remote_backend_is_subject_to_the_same_lifecycle_gate() -> None:
    knowledge = _active_store()
    service, store = _remote_service(knowledge)

    warm = service.retrieve(query="higiene ordenha", context=_context(allowed=[COLLECTION]))
    assert [item.document_id for item in warm.evidence] == ["doc-a02"]
    assert store.calls[-1]["allowed_collection_ids"] == [COLLECTION]

    _archive(knowledge)

    scoped = service.retrieve(query="higiene ordenha", context=_context(allowed=[COLLECTION]))
    assert scoped.evidence == []
    assert scoped.metadata["authorization"] == "lifecycle_denied"

    wildcard = service.retrieve(query="higiene ordenha", context=_context(allowed=["*"]))
    assert wildcard.evidence == []


def _http_app(knowledge, *, points: list[dict]):
    from app import create_app
    from dependencies.services import Providers
    from services.audit import InMemoryAuditSink
    from services.chat_service import StubChatBackend
    from services.identity_service import InMemoryIdentityProvider

    embeddings = DeterministicHashEmbedding()
    retrieval = RetrievalApplicationService(knowledge=knowledge, embeddings=embeddings)
    attached = [_point(embeddings, **kwargs) for kwargs in points]
    retrieval.attach_points(attached)
    providers = Providers(
        settings=make_settings(),
        identity=InMemoryIdentityProvider(),
        chat_backend=StubChatBackend(),
        health_checks={},
        audit_sink=InMemoryAuditSink(),
        knowledge=knowledge,
        retrieval=retrieval,
    )
    return create_app(providers.settings, providers), attached


def _search(client: TestClient, *, collection_id: str | None) -> dict:
    body: dict = {"query": "higiene ordenha", "top_k": 3}
    if collection_id is not None:
        body["collection_id"] = collection_id
    response = client.post("/api/v1/search", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_archive_then_search_returns_no_items_scoped_and_globally() -> None:
    knowledge = _active_store()
    app, _ = _http_app(knowledge, points=[{}])

    with TestClient(app, raise_server_exceptions=False) as client:
        login_as(client, "admin@example.com")
        assert _search(client, collection_id=COLLECTION)["total"] >= 1
        assert _search(client, collection_id=None)["total"] >= 1

        archived = client.post(f"/api/v1/collections/{COLLECTION}/archive")
        assert archived.status_code == 200, archived.text
        assert archived.json()["status"] == "archived"

        assert _search(client, collection_id=COLLECTION)["total"] == 0
        assert _search(client, collection_id=None)["total"] == 0

    # Cold index over the same store: a fresh service rehydrates after the
    # archive and must reach the same denial.
    cold, _ = _http_app(knowledge, points=[{}])
    with TestClient(cold, raise_server_exceptions=False) as client:
        login_as(client, "admin@example.com")
        assert _search(client, collection_id=COLLECTION)["total"] == 0
        assert _search(client, collection_id=None)["total"] == 0


def test_archive_survives_a_restart_with_the_sqlite_store(tmp_path) -> None:
    path = tmp_path / "knowledge.db"
    knowledge = _active_store(SQLiteKnowledgeStore(str(path)))
    app, _ = _http_app(knowledge, points=[{}])

    with TestClient(app, raise_server_exceptions=False) as client:
        login_as(client, "admin@example.com")
        assert _search(client, collection_id=COLLECTION)["total"] >= 1
        archived = client.post(f"/api/v1/collections/{COLLECTION}/archive")
        assert archived.status_code == 200, archived.text

    # New process equivalent: a second store handle over the same file, with
    # no re-seeding that could silently un-archive the collection.
    restarted = SQLiteKnowledgeStore(str(path))
    managed = {
        item["collection_id"]: item["status"]
        for item in KnowledgeApplicationService(restarted).list_managed_collections(
            workspace_id=WORKSPACE, tenant_id=TENANT,
        )
    }
    assert managed[COLLECTION] == "archived"

    cold, _ = _http_app(restarted, points=[{}])
    with TestClient(cold, raise_server_exceptions=False) as client:
        login_as(client, "admin@example.com")
        assert _search(client, collection_id=COLLECTION)["total"] == 0
        assert _search(client, collection_id=None)["total"] == 0
