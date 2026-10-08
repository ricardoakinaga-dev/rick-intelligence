"""Completed-job replay must use persisted retirement authority, not today's owner."""
from copy import deepcopy
import pytest
from rick_ingestion.pipeline import IngestionService
from rick_knowledge import InMemoryKnowledgeStore, SQLiteKnowledgeStore
from rick_knowledge.fencing import ATTEMPT_METADATA_KEY
from rick_retrieval.vectordb import DeterministicHashEmbedding, InMemoryVectorStore

SCOPE = dict(tenant_id="tenant", workspace_id="workspace", collection_id="collection")

@pytest.mark.parametrize("backend", ["memory", "sqlite"])
@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize("owner", ["original", "old-successor", "new-successor"])
def test_reindex_same_committed_job_preserves_persisted_owners(tmp_path, backend, pending, owner):
    k = InMemoryKnowledgeStore() if backend == "memory" else SQLiteKnowledgeStore(tmp_path / "knowledge.db")
    v = InMemoryVectorStore()
    service = IngestionService(knowledge=k, vectors=v, embeddings=DeterministicHashEmbedding())
    source = tmp_path / "source.txt"
    source.write_text("The original searchable document has stable evidence for the old publication.")
    old = service.ingest(source, **SCOPE)
    assert old.status == "published"
    old_points = deepcopy(v.all_points())
    source.write_text("The new version of this searchable document contains changed evidence.")
    def defer():
        return pending and any(j.status == "published" and j.document_id != old.document_id
                               for j in service._jobs.values())
    new = service.reindex(old.document_id, source, cancel_check=defer, **SCOPE)
    assert new.status == "published"
    assert new.metadata["retirement_pending"] is pending
    if owner != "original":
        identity = old.document_id if owner == "old-successor" else new.document_id
        successor = deepcopy(k.get_document(identity))
        successor.metadata[ATTEMPT_METADATA_KEY] = "foreign-owner"
        successor.status = "published"
        k.upsert_document(successor)
        if owner == "old-successor" and not pending:
            v.upsert_points(old_points)
    before = deepcopy(v.all_points())
    old_before = deepcopy(k.get_document(old.document_id))
    new_before = deepcopy(k.get_document(new.document_id))
    authority = k.get_publication(new.job_id, **SCOPE)
    class NoReplay:
        model = "never-call"
        dimensions = 1536
        def embed(self, texts):
            raise AssertionError("committed replay must not call embedding")
    replay = IngestionService(knowledge=k, vectors=v, embeddings=NoReplay())
    source.unlink()
    try:
        for _ in range(2):
            done = replay.reindex(old.document_id, source, job_id=new.job_id, **SCOPE)
            assert done.status == "published"
            assert done.attempt == authority["job_snapshot"]["attempt"]
            assert done.finished_at == authority["job_snapshot"]["finished_at"]
            assert k.get_publication(new.job_id, **SCOPE)["outcome"] == "committed"
            assert k.get_document(new.document_id) == new_before
            if owner == "original":
                assert k.get_document(old.document_id).status == "unpublished"
                assert v.count_for_document(old.document_id, SCOPE["collection_id"]) == 0
            else:
                assert k.get_document(old.document_id) == old_before
                assert v.all_points() == before
    finally:
        if backend == "sqlite":
            k.close()
