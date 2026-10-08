"""A duplicate upload must remain recoverable without processing its source again."""
from copy import deepcopy

import pytest

from rick_ingestion.pipeline import IngestionService
from rick_knowledge import InMemoryKnowledgeStore, SQLiteKnowledgeStore
from rick_knowledge.fencing import OwnershipLostError
from rick_retrieval.vectordb import DeterministicHashEmbedding, InMemoryVectorStore

SCOPE = dict(tenant_id="tenant", workspace_id="workspace", collection_id="collection")


class NoReplay:
    model = "forbidden-replay"
    dimensions = 1536

    def embed(self, texts):
        raise AssertionError("committed deduplication must not call a provider")


@pytest.fixture(params=["memory", "sqlite"])
def rig(request, tmp_path):
    database = tmp_path / "knowledge.db"
    store = InMemoryKnowledgeStore() if request.param == "memory" else SQLiteKnowledgeStore(database)
    vectors = InMemoryVectorStore()
    source = tmp_path / "source.txt"
    source.write_text("Stable searchable evidence for repeated uploads of exactly the same content.")
    service = IngestionService(knowledge=store, vectors=vectors, embeddings=DeterministicHashEmbedding())
    first = service.ingest(source, **SCOPE)
    duplicate = service.ingest(source, **SCOPE)
    assert first.status == duplicate.status == "published"
    assert first.document_id == duplicate.document_id
    source.unlink()
    yield store, vectors, duplicate, source, database, request.param
    if request.param == "sqlite":
        store.close()


def test_duplicate_checkpoint_has_receipt_identity_and_recovers(rig):
    store, vectors, job, source, _, _ = rig
    receipt = store.get_publication(job.job_id, **SCOPE)
    checkpoint = store.get_ingestion_checkpoint(job.job_id, **SCOPE)
    assert checkpoint["document_id"] == receipt["document_id"] == job.document_id
    before = deepcopy(vectors.all_points())
    replay = IngestionService(knowledge=store, vectors=vectors, embeddings=NoReplay())
    for _ in range(2):
        done = replay.ingest(source, job_id=job.job_id, **SCOPE)
        assert done.status == "published"
        assert done.document_id == job.document_id
        assert done.finished_at == receipt["job_snapshot"]["finished_at"]
        assert done.started_at == receipt["job_snapshot"]["started_at"]
        assert vectors.all_points() == before
        assert store.get_publication(job.job_id, **SCOPE) == receipt


@pytest.mark.parametrize("corruption", [None, "document", "finish", "attempt", "fingerprint", "artifacts", "cancel", "not-dedup"])
def test_only_exact_legacy_duplicate_checkpoint_can_fill_missing_identity(rig, corruption):
    store, vectors, job, _, database, backend = rig
    receipt = store.get_publication(job.job_id, **SCOPE)
    # Reproduce the installed producer bug, not a new publication decision:
    # a duplicate bypassed checkpoint persistence before its committed finish.
    legacy = deepcopy(store.get_ingestion_checkpoint(job.job_id, **SCOPE))
    legacy.update(document_id=None, fingerprint=None, artifacts={})
    if corruption == "document":
        legacy["document_id"] = "foreign-document"
    elif corruption == "finish":
        legacy["job_snapshot"]["finished_at"] += 1
    elif corruption == "attempt":
        legacy["job_snapshot"]["attempt"] += 1
    elif corruption == "fingerprint":
        legacy["fingerprint"] = {"foreign": True}
    elif corruption == "artifacts":
        legacy["artifacts"] = {"foreign": True}
    elif corruption == "cancel":
        legacy["cancel_requested"] = not receipt["cancel_requested"]
    elif corruption == "not-dedup":
        legacy["job_snapshot"]["metadata"].pop("deduplicated")
    store._write_ingestion_checkpoint(legacy)
    if backend == "sqlite":
        store.close()
        store = SQLiteKnowledgeStore(database)
    before = deepcopy(vectors.all_points())
    replay = IngestionService(knowledge=store, vectors=vectors, embeddings=NoReplay())
    try:
        if corruption is not None:
            with pytest.raises((OwnershipLostError, ValueError)):
                replay.recover_publication(job.job_id, **SCOPE)
            assert store._read_ingestion_checkpoint(job.job_id, **SCOPE) == legacy
        else:
            for _ in range(2):
                done = replay.recover_publication(job.job_id, **SCOPE)
                assert done.status == "published" and done.document_id == receipt["document_id"]
                assert done.finished_at == receipt["job_snapshot"]["finished_at"]
            corrected = store.get_ingestion_checkpoint(job.job_id, **SCOPE)
            assert corrected == dict(legacy, document_id=receipt["document_id"])
        assert store.get_publication(job.job_id, **SCOPE) == receipt
        assert vectors.all_points() == before
    finally:
        if backend == "sqlite":
            store.close()
