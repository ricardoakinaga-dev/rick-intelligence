"""Completion notification cannot override the public committed outcome."""
from copy import deepcopy
from io import BytesIO
import hashlib

import pytest

from external_ingestion import ExternalIngestionHandler
from rick_ingestion import IngestionService, ParseError
from rick_ingestion.pipeline import _CancellationRequested, _EmbeddingBatchError, _scoped_call
from rick_knowledge import InMemoryKnowledgeStore, SQLiteKnowledgeStore
from rick_retrieval import DeterministicHashEmbedding, InMemoryVectorStore, SQLiteVectorStore
from services.ingestion_service import IngestionApplicationService


class InvalidMetadataError(ValueError):
    """A caller-defined typed sink error, independent of the parser taxonomy."""


def exercise_completion(knowledge, vectors, tmp_path, scope, caller, operation, category):
    calls, snapshots = [], []
    class Events:
        enabled = False
        def emit(self, event):
            if self.enabled and event["type"] == "ingestion.completed":
                calls.append(deepcopy(event))
                doc = knowledge.get_document(event["document_id"])
                snapshots.append(deepcopy((doc, knowledge.get_chunks(doc.document_id))))
                if category == "parse":
                    raise ParseError("lock_unavailable", "private sink error")
                if category == "metadata":
                    raise InvalidMetadataError("private metadata")
                if category == "embedding":
                    raise _EmbeddingBatchError("provider_unavailable", "private embedding")
                if category == "cancel":
                    raise _CancellationRequested()
                raise RuntimeError("private sink error")
    events = Events()
    ingestion = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=DeterministicHashEmbedding(), events=events)
    old = None
    path = tmp_path / "old.txt"
    path.write_text("Published source retained through completion notification failure. " * 80)
    if operation in {"reindex", "duplicate"}:
        old = ingestion.ingest(path, **scope)
        assert old.status == "published"
    data = path.read_bytes() if operation == "duplicate" else b"Changed source commits before its completion callback fails. " * 80
    events.enabled = True
    if caller == "api":
        app = IngestionApplicationService(ingestion, staging_root=tmp_path / "staging")
        try:
            result = app.reindex(old.document_id, source=BytesIO(data), filename="new.txt", **scope) if operation == "reindex" else app.upload(BytesIO(data), filename="new.txt", **scope)
        finally:
            app.close()
        job = ingestion.get_status(result["job_id"])
    elif caller == "worker":
        class Objects:
            def get(self, *_args, **_kwargs):
                return data
        handler = ExternalIngestionHandler(ingestion, Objects(), temp_root=tmp_path / "worker")
        payload = {"operation": "reindex" if operation == "reindex" else "ingest", "object_key": "objects/v1",
                   "checksum": "sha256:" + hashlib.sha256(data).hexdigest(), "display_filename": "new.txt"}
        if operation == "reindex":
            payload["document_id"] = old.document_id
        try:
            job = handler({**scope, "job_id": "completion", "payload": payload}, lease_lost_check=lambda: False)
        finally:
            handler.close()
        assert list((tmp_path / "worker").iterdir()) == []
    else:
        new_path = tmp_path / "new.txt"
        new_path.write_bytes(data)
        job = ingestion.reindex(old.document_id, new_path, **scope) if operation == "reindex" else ingestion.ingest(new_path, **scope)
    assert len(calls) == 1, "a callback with unknown delivery outcome must not be retried"
    assert job.status == "published" and job.error_code is None
    assert job.metadata["completion_notification_error_after_commit"] is True
    assert deepcopy((knowledge.get_document(job.document_id), knowledge.get_chunks(job.document_id))) == snapshots[0]
    assert _scoped_call(vectors.count_for_document, job.document_id, scope["collection_id"], tenant_id=scope["tenant_id"], workspace_id=scope["workspace_id"]) == len(snapshots[0][1]) > 0
    return job.document_id, snapshots[0]


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
@pytest.mark.parametrize("caller", ["pipeline", "api", "worker"])
@pytest.mark.parametrize("operation", ["ingest", "reindex", "duplicate"])
@pytest.mark.parametrize("category", ["parse", "metadata"])
def test_public_completion_callback_preserves_outcome(tmp_path, kind, caller, operation, category):
    knowledge = InMemoryKnowledgeStore() if kind == "memory" else SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite")
    vectors = InMemoryVectorStore() if kind == "memory" else SQLiteVectorStore(tmp_path / "vectors.sqlite")
    try:
        identity, snapshot = exercise_completion(knowledge, vectors, tmp_path,
            dict(tenant_id="t", workspace_id="w", collection_id="c"), caller, operation, category)
    finally:
        if kind == "sqlite":
            knowledge.close()
            vectors.close()
    if kind == "sqlite":
        with SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite") as reopened:
            assert deepcopy((reopened.get_document(identity), reopened.get_chunks(identity))) == snapshot
