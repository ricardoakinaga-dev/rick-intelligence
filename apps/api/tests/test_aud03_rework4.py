"""Public catalog aliases and cancellation after durable publication."""
import asyncio
import hashlib
from copy import deepcopy
from io import BytesIO

import pytest

from external_ingestion import ExternalIngestionHandler
from rick_ingestion import IngestionService
from rick_knowledge import InMemoryKnowledgeStore, SQLiteKnowledgeStore
from rick_retrieval import DeterministicHashEmbedding, InMemoryVectorStore
from services.ingestion_service import IngestionApplicationService
from services.knowledge_service import KnowledgeApplicationService


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    store = InMemoryKnowledgeStore() if request.param == "memory" else SQLiteKnowledgeStore(tmp_path / "catalog.sqlite")
    yield store
    close = getattr(store, "close", None)
    if close:
        close()


@pytest.mark.parametrize("created", ["rag_phase0", "cvg_master_rag", "rickvet_documents"])
@pytest.mark.parametrize("archived", ["rag_phase0", "cvg_master_rag", "rickvet_documents"])
def test_public_archive_alias_blocks_every_upload_alias(store, tmp_path, created, archived):
    catalog = KnowledgeApplicationService(store)
    scope = dict(tenant_id="t", workspace_id="w")
    row = catalog.create_collection(**scope, collection_id=created, title="Retained")
    assert row["collection_id"] == "rag_phase0"
    catalog.update_collection(**scope, collection_id="rickvet_documents", description="retention")
    catalog.archive_collection(**scope, collection_id=archived)
    before = deepcopy(store.list_collections("w", tenant_id="t"))
    assert catalog.list_collections(**scope, allowed=["*"]) == []
    assert len(catalog.list_managed_collections(**scope)) == 1
    pipeline = IngestionService(knowledge=store, vectors=InMemoryVectorStore(), embeddings=DeterministicHashEmbedding())
    app = IngestionApplicationService(pipeline, staging_root=tmp_path / "api")
    try:
        for key in ("rag_phase0", "cvg_master_rag", "rickvet_documents"):
            result = app.upload(BytesIO(b"Archive rejects publication."), filename="guide.txt", **scope, collection_id=key)
            assert result["status"] == "failed"
            assert store.list_collections("w", tenant_id="t") == before
    finally:
        app.close()


@pytest.mark.parametrize("caller", ["pipeline", "api", "worker"])
@pytest.mark.parametrize("operation", ["ingest", "duplicate", "reindex"])
def test_cancelled_completion_public_callers(store, tmp_path, caller, operation):
    exercise_cancelled_completion(store, tmp_path, dict(tenant_id="t", workspace_id="w", collection_id="c"), caller, operation)


def exercise_cancelled_completion(store, tmp_path, scope, caller, operation):
    vectors = InMemoryVectorStore()
    pipeline = IngestionService(knowledge=store, vectors=vectors, embeddings=DeterministicHashEmbedding())
    source = tmp_path / "source.txt"
    source.write_text("Initial public content." * 80)
    old = pipeline.ingest(source, **scope) if operation != "ingest" else None
    if operation == "reindex":
        source.write_text("New public content must survive callback cancellation." * 80)
    calls = []
    class Events:
        def emit(self, event):
            if event["type"] == "ingestion.completed":
                calls.append(event)
                raise asyncio.CancelledError()
    pipeline.events = Events()
    data = source.read_bytes()
    if caller == "pipeline":
        job = pipeline.reindex(old.document_id, source, **scope) if operation == "reindex" else pipeline.ingest(source, **scope)
    elif caller == "api":
        app = IngestionApplicationService(pipeline, staging_root=tmp_path / "api")
        try:
            result = app.reindex(old.document_id, source=BytesIO(data), filename="new.txt", **scope) if operation == "reindex" else app.upload(BytesIO(data), filename="new.txt", **scope)
        finally:
            app.close()
        job = pipeline.get_status(result["job_id"])
        assert result["status"] == "published"
    else:
        class Objects:
            def get(self, *_args, **_kwargs):
                return data
        handler = ExternalIngestionHandler(pipeline, Objects(), temp_root=tmp_path / "worker")
        payload = {"operation": "reindex" if operation == "reindex" else "ingest", "object_key": "object", "display_filename": "new.txt", "checksum": "sha256:" + hashlib.sha256(data).hexdigest()}
        if operation == "reindex":
            payload["document_id"] = old.document_id
        job = handler({**scope, "job_id": "cancel-completion", "payload": payload})
        assert list((tmp_path / "worker").iterdir()) == []
    assert job.status == store.get_document(job.document_id).status == "published"
    assert len(calls) == 1 and job.metadata["completion_notification_error_after_commit"]
    points = [p for p in vectors.all_points() if p["payload"]["document_id"] == job.document_id]
    assert len(points) == len(store.get_chunks(job.document_id)) > 0


@pytest.mark.parametrize("operation", ["ingest", "duplicate", "reindex"])
def test_cancelled_api_refresh_reports_committed_outcome(store, tmp_path, operation):
    pipeline = IngestionService(knowledge=store, vectors=InMemoryVectorStore(), embeddings=DeterministicHashEmbedding())
    calls = []
    def refresh():
        calls.append("refresh")
        raise asyncio.CancelledError()
    app = IngestionApplicationService(pipeline, staging_root=tmp_path / "api", refresh_callback=refresh)
    scope = dict(tenant_id="t", workspace_id="w", collection_id="c")
    try:
        old = app.upload(BytesIO(b"Initial content." * 50), filename="initial.txt", **scope) if operation != "ingest" else None
        calls.clear()
        if operation == "reindex":
            result = app.reindex(old["document_id"], source=BytesIO(b"New refresh content." * 50), filename="new.txt", **scope)
        else:
            result = app.upload(BytesIO(b"Initial content." * 50), filename="initial.txt", **scope)
        assert result["status"] == "published" and calls == ["refresh"]
        assert app.get_status(result["job_id"], tenant_id="t", workspace_id="w", allowed_collection_ids=["*"])["status"] == "published"
    finally:
        app.close()
