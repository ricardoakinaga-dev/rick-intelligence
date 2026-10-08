"""Reindex returns a committed outcome even when later lease checks fail."""
from copy import deepcopy
import hashlib

import pytest

from external_ingestion import ExternalIngestionHandler
from rick_ingestion import IngestionService, ParseError
from rick_ingestion.pipeline import _CancellationRequested, _EmbeddingBatchError
from rick_knowledge import InMemoryKnowledgeStore, SQLiteKnowledgeStore
from rick_retrieval import DeterministicHashEmbedding, InMemoryVectorStore, SQLiteVectorStore


def exercise_reindex_outcome(knowledge, vectors, tmp_path, scope, category, published_check):
    service = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=DeterministicHashEmbedding())
    old_path = tmp_path / "old.txt"
    old_path.write_text("The existing published version retains authoritative citations. " * 80)
    old = service.ingest(old_path, **scope)
    assert old.status == "published"
    old_before = deepcopy((knowledge.get_document(old.document_id), knowledge.get_chunks(old.document_id)))
    data = b"A changed source publishes before retirement needs another lease check. " * 80
    record = {**scope, "job_id": "reindex-outcome", "payload": {
        "operation": "reindex", "document_id": old.document_id,
        "object_key": "reindex-source", "display_filename": "new.txt",
        "checksum": "sha256:" + hashlib.sha256(data).hexdigest(),
    }}
    class Objects:
        def get(self, *_args, **_kwargs):
            return data
    checks, committed = [], []
    def lease_lost():
        job = service.get_status("reindex-outcome")
        if job is None or job.status != "published":
            return False
        checks.append(1)
        if not committed:
            committed.append(deepcopy((knowledge.get_document(job.document_id), knowledge.get_chunks(job.document_id), vectors.all_points())))
        if len(checks) == published_check:
            if category == "parse":
                raise ParseError("lock_unavailable", "Lease callback failed after commit.")
            if category == "embedding":
                raise _EmbeddingBatchError("provider_unavailable", "Typed callback failed after commit.")
            if category == "cancel":
                raise _CancellationRequested()
            if category == "lease_true":
                return True
            raise RuntimeError("Lease callback failed after commit.")
        return False
    handler = ExternalIngestionHandler(service, Objects(), temp_root=tmp_path / "worker")
    result, escaped = None, None
    try:
        result = handler(record, lease_lost_check=lease_lost)
    except Exception as exc:
        escaped = repr(exc)
    job = service.get_status("reindex-outcome")
    actual = deepcopy((knowledge.get_document(job.document_id), knowledge.get_chunks(job.document_id), vectors.all_points()))
    print("reindex postcommit", category, published_check, "checks", len(checks), "escaped", escaped,
          "job", job.status, "document", actual[0].status, "chunks", len(actual[1]))
    assert committed and committed[0][0].status == "published" and committed[0][1]
    assert escaped is None
    assert result is job and job.status == "published" and job.error_code is None
    assert job.metadata["retirement_deferred"] == "lock_unavailable"
    assert actual == committed[0]
    assert deepcopy((knowledge.get_document(old.document_id), knowledge.get_chunks(old.document_id))) == old_before
    assert list((tmp_path / "worker").iterdir()) == []
    return job.document_id, actual


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
@pytest.mark.parametrize("category", ["parse", "embedding", "cancel", "runtime", "lease_true"])
@pytest.mark.parametrize("published_check", [1, 2, 3])
def test_actual_handler_reindex_postcommit_checks_preserve_real_outcome(tmp_path, kind, category, published_check):
    def stores():
        if kind == "memory":
            return InMemoryKnowledgeStore(), InMemoryVectorStore()
        return SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite"), SQLiteVectorStore(tmp_path / "vectors.sqlite")
    knowledge, vectors = stores()
    try:
        document_id, actual = exercise_reindex_outcome(knowledge, vectors, tmp_path,
            dict(tenant_id="t", workspace_id="w", collection_id="c"), category, published_check)
    finally:
        if kind == "sqlite":
            knowledge.close()
            vectors.close()
    if kind == "sqlite":
        knowledge, vectors = stores()
        try:
            assert deepcopy((knowledge.get_document(document_id), knowledge.get_chunks(document_id), vectors.all_points())) == actual
        finally:
            knowledge.close()
            vectors.close()
