"""Public cancellation must retain durable recovery until scoped effects are gone."""
from copy import deepcopy
import pytest
from rick_ingestion.jobs import IngestionJob
from rick_ingestion.pipeline import IngestionService
from rick_knowledge import Collection, Document, InMemoryKnowledgeStore, SQLiteKnowledgeStore
from rick_retrieval.vectordb import InMemoryVectorStore

SCOPE = dict(tenant_id="tenant-a", workspace_id="workspace-a", collection_id="collection-a")

class NoProvider:
    model = "never-called"
    dimensions = 1
    def embed(self, texts):
        raise AssertionError("cancellation recovery must not replay provider work")

class FaultVectors(InMemoryVectorStore):
    fault = "unavailable"
    def delete_document(self, document_id, collection_id, **scope):
        if self.fault == "unavailable":
            raise RuntimeError("delete unavailable")
        count = super().delete_document(document_id, collection_id, **scope)
        if self.fault == "ack-lost":
            raise RuntimeError("delete acknowledgement lost")
        return count
    def count_for_document(self, document_id, collection_id, **scope):
        if self.fault == "count-unavailable":
            raise RuntimeError("count unavailable")
        return super().count_for_document(document_id, collection_id, **scope)

@pytest.fixture(params=["memory", "sqlite"])
def rig(request, tmp_path):
    path = tmp_path / "knowledge.db"
    k = InMemoryKnowledgeStore() if request.param == "memory" else SQLiteKnowledgeStore(path)
    k.ensure_collection(Collection(**SCOPE))
    job = IngestionJob(**SCOPE, job_id="cancel", status="indexing", stage="indexing",
        created_at=1., started_at=2., metadata={"publication_attempt": "owner"})
    k.begin_ingestion_checkpoint(job)
    job.document_id = "document"
    k.save_ingestion_checkpoint(job, fingerprint={"fixture": "bounded"}, artifacts={})
    k.upsert_document(Document(**SCOPE, document_id=job.document_id, status="processing",
        metadata={"_ingestion_attempt": "owner"}))
    v = FaultVectors()
    v.upsert_points([dict(point_id="owned", vector=[1.], payload=dict(SCOPE, document_id=job.document_id)),
        dict(point_id="foreign", vector=[1.], payload=dict(SCOPE, tenant_id="foreign", document_id=job.document_id))])
    k.request_ingestion_cancel(job)
    yield k, v, job, path, request.param
    if request.param == "sqlite":
        k.close()

def service(k, v):
    return IngestionService(knowledge=k, vectors=v, embeddings=NoProvider())

@pytest.mark.parametrize("fault", ["unavailable", "count-unavailable"])
def test_cleanup_failure_stays_active_and_recovers_after_restart(rig, fault):
    k, v, original, path, backend = rig
    v.fault = fault
    recovered = service(k, v).recover_publication(original.job_id, **SCOPE)
    assert recovered.status == "verifying"
    assert recovered.finished_at is None
    cp = k.get_ingestion_checkpoint(original.job_id, **SCOPE)
    assert cp["state"] == "active" and cp["cancel_requested"]
    assert k.get_document(original.document_id).status != "published"
    assert any(p["point_id"] == "foreign" for p in v.all_points())
    again = service(k, v).recover_publication(original.job_id, **SCOPE)
    assert again.status == "verifying" and again.finished_at is None
    if backend == "sqlite":
        k.close()
        k = SQLiteKnowledgeStore(path)
    try:
        v.fault = None
        done = service(k, v).recover_publication(original.job_id, **SCOPE)
        assert done.status == "cancelled"
        cp = k.get_ingestion_checkpoint(original.job_id, **SCOPE)
        assert cp["state"] == "cancelled" and cp["cancel_requested"]
        assert cp["job_snapshot"]["finished_at"] == done.finished_at
        assert [p["point_id"] for p in v.all_points()] == ["foreign"]
        finished = done.finished_at
        assert service(k, v).recover_publication(original.job_id, **SCOPE).finished_at == finished
    finally:
        if backend == "sqlite":
            k.close()

@pytest.mark.parametrize("fault", [None, "ack-lost"])
def test_confirmed_cleanup_can_finish_without_touching_other_scope(rig, fault):
    k, v, original, _, _ = rig
    v.fault = fault
    done = service(k, v).recover_publication(original.job_id, **SCOPE)
    assert done.status == "cancelled"
    assert k.get_ingestion_checkpoint(original.job_id, **SCOPE)["state"] == "cancelled"
    assert [p["point_id"] for p in v.all_points()] == ["foreign"]

def test_foreign_successor_remains_intact(rig):
    k, v, original, _, _ = rig
    document = deepcopy(k.get_document(original.document_id))
    document.metadata["_ingestion_attempt"] = "successor"
    k.upsert_document(document)
    points = deepcopy(v.all_points())
    done = service(k, v).recover_publication(original.job_id, **SCOPE)
    assert done.status == "cancelled"
    assert k.get_document(original.document_id) == document
    assert v.all_points() == points

def test_pending_publication_cancel_retains_receipt_until_cleanup(rig):
    k, v, original, _, _ = rig
    k.begin_publication(original, ready_count=1)
    pending = service(k, v).recover_publication(original.job_id, **SCOPE)
    assert pending.status == "verifying" and pending.finished_at is None
    assert k.get_publication(original.job_id, **SCOPE)["outcome"] == "pending"
    assert k.get_ingestion_checkpoint(original.job_id, **SCOPE)["state"] == "active"
    v.fault = None
    done = service(k, v).recover_publication(original.job_id, **SCOPE)
    assert done.status == "cancelled"
    assert k.get_publication(original.job_id, **SCOPE)["outcome"] == "cancelled"
    assert k.get_ingestion_checkpoint(original.job_id, **SCOPE)["state"] == "cancelled"
    assert [p["point_id"] for p in v.all_points()] == ["foreign"]


def test_live_operator_cancel_keeps_failed_cleanup_recoverable(rig, tmp_path):
    k, v, _, _, _ = rig
    events = []
    class Events:
        def emit(self, event):
            events.append(event["type"])
    class Embedding:
        dimensions = 1
        model = "finite-test"
        calls = 0
        def embed(self, texts):
            self.calls += 1
            return [[1.] for _ in texts]
    embedding = Embedding()
    live = IngestionService(knowledge=k, vectors=v, embeddings=embedding, events=Events())
    upsert = v.upsert_points
    def upsert_and_cancel(points):
        result = upsert(points)
        job = next(j for j in live._jobs.values() if j.status == "indexing")
        assert live.cancel(job.job_id) is True
        return result
    v.upsert_points = upsert_and_cancel
    path = tmp_path / "source.txt"
    path.write_text("A sufficiently long searchable document for deterministic cancellation testing.")
    pending = live.ingest(path, **SCOPE)
    assert pending.status == "verifying" and pending.finished_at is None
    assert k.get_ingestion_checkpoint(pending.job_id, **SCOPE)["state"] == "active"
    assert k.get_ingestion_checkpoint(pending.job_id, **SCOPE)["cancel_requested"]
    assert k.get_document(pending.document_id).status == "failed"
    assert events.count("ingestion.cancelled") == 1
    calls = embedding.calls
    v.fault = None
    done = service(k, v).recover_publication(pending.job_id, **SCOPE)
    assert done.status == "cancelled"
    assert k.get_ingestion_checkpoint(pending.job_id, **SCOPE)["state"] == "cancelled"
    assert v.count_for_document(pending.document_id, SCOPE["collection_id"],
        tenant_id=SCOPE["tenant_id"], workspace_id=SCOPE["workspace_id"]) == 0
    assert embedding.calls == calls and events.count("ingestion.cancelled") == 1
