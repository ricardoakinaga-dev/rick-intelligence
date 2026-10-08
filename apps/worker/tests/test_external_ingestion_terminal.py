"""The real worker lease guard must preserve typed postcommit failures."""
from copy import deepcopy

import pytest

from external_ingestion import _LeaseGuard
from rick_ingestion import IngestionService, ParseError
from rick_knowledge import InMemoryKnowledgeStore, SQLiteKnowledgeStore
from rick_retrieval import DeterministicHashEmbedding, InMemoryVectorStore, SQLiteVectorStore


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
@pytest.mark.parametrize("deduplicated", [False, True])
def test_lease_callback_parse_error_after_commit_preserves_durable_effects(tmp_path, kind, deduplicated):
    def stores():
        if kind == "memory":
            return InMemoryKnowledgeStore(), InMemoryVectorStore()
        return SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite"), SQLiteVectorStore(tmp_path / "vectors.sqlite")
    knowledge, vectors = stores()
    service = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=DeterministicHashEmbedding())
    path = tmp_path / "guide.txt"
    path.write_text("Typed worker callback preserves the committed publication. " * 80)
    scope = dict(tenant_id="t", workspace_id="w", collection_id="c")
    if deduplicated:
        assert service.ingest(path, **scope).status == "published"
    checks, committed = [], []
    def snapshot(document_id):
        return deepcopy((knowledge.get_document(document_id), knowledge.get_chunks(document_id), vectors.all_points()))
    def lease_lost():
        checks.append(1)
        if len(checks) == 3:
            job = service.get_status("worker-typed-exit")
            assert job.status == "published"
            committed.append(snapshot(job.document_id))
            raise ParseError("lock_unavailable", "Lease callback unavailable.")
        return False
    result, escaped = None, None
    try:
        result = service.ingest(path, **scope, job_id="worker-typed-exit", publication_guard=lambda: _LeaseGuard(lease_lost))
    except Exception as exc:
        escaped = repr(exc)
    job = service.get_status("worker-typed-exit")
    actual = snapshot(job.document_id)
    reopened = None
    if kind == "sqlite":
        knowledge.close()
        vectors.close()
        knowledge, vectors = stores()
        try:
            reopened = snapshot(job.document_id)
        finally:
            knowledge.close()
            vectors.close()
    print("worker callback", kind, deduplicated, "checks", len(checks), "escaped", escaped,
          "document", actual[0].status, "chunks", len(actual[1]), "points", len(actual[2]))
    assert len(checks) == 3
    assert committed and committed[0][0].status == "published" and committed[0][1] and committed[0][2]
    assert escaped is None
    assert result is job and job.status == "published" and job.error_code is None
    assert job.metadata["publication_guard_error_after_commit"] is True
    assert actual == committed[0]
    if kind == "sqlite":
        assert reopened == committed[0]
