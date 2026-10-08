"""Public replacement recovery and operator cancellation regression controls."""
from asyncio import CancelledError
from copy import deepcopy

import pytest

from rick_ingestion.pipeline import IngestionService
from rick_knowledge import InMemoryKnowledgeStore, SQLiteKnowledgeStore
from rick_knowledge.fencing import ATTEMPT_METADATA_KEY
from rick_retrieval.vectordb import DeterministicHashEmbedding, InMemoryVectorStore


SCOPE = dict(tenant_id="tenant", workspace_id="workspace", collection_id="collection")


class FaultVectors(InMemoryVectorStore):
    target = None
    partial = False
    restore_fails = False
    on_delete = None

    def delete_document(self, document_id, collection_id):
        if document_id == self.target:
            if self.on_delete is not None:
                self.on_delete()
            if self.partial:
                point = next(p for p in self.all_points()
                             if p["payload"]["document_id"] == document_id)
                del self._points[point["point_id"]]
            raise RuntimeError("old deletion failed")
        return super().delete_document(document_id, collection_id)

    def upsert_points(self, points):
        if self.restore_fails and points[0]["payload"]["document_id"] == self.target:
            raise RuntimeError("restoration unavailable")
        return super().upsert_points(points)


@pytest.fixture(params=["memory", "sqlite"])
def rig(request, tmp_path):
    knowledge = (InMemoryKnowledgeStore() if request.param == "memory"
                 else SQLiteKnowledgeStore(tmp_path / "knowledge.db"))
    vectors = FaultVectors()
    service = IngestionService(knowledge=knowledge, vectors=vectors,
                               embeddings=DeterministicHashEmbedding())
    path = tmp_path / "source.txt"
    path.write_text("The original searchable document contains stable evidence.")
    yield service, knowledge, vectors, path
    if request.param == "sqlite":
        knowledge.close()


def replacement(rig):
    service, knowledge, vectors, path = rig
    old = service.ingest(path, **SCOPE)
    assert old.status == "published"
    path.write_text("The changed searchable document contains new evidence.")
    # Public reindex commits but deliberately defers old retirement.
    def defer_after_commit():
        return any(j.status == "published" and j.document_id != old.document_id
                   for j in service._jobs.values())

    new = service.reindex(old.document_id, path, cancel_check=defer_after_commit, **SCOPE)
    assert new.status == "published" and new.metadata["retirement_pending"]
    assert knowledge.get_document(old.document_id).status == "published"
    fresh = IngestionService(knowledge=knowledge, vectors=vectors,
                             embeddings=DeterministicHashEmbedding())
    return old, new, fresh


@pytest.mark.parametrize("partial", [False, True])
def test_recovery_old_delete_failure_restores_owned_publication(rig, partial):
    service, knowledge, vectors, path = rig
    old, new, fresh = replacement(rig)
    before = deepcopy(vectors.all_points())
    receipt = knowledge.get_publication(new.job_id, **SCOPE)
    vectors.target, vectors.partial = old.document_id, partial
    recovered = fresh.recover_publication(new.job_id, **SCOPE)
    assert recovered.status == "published"
    assert knowledge.get_publication(new.job_id, **SCOPE)["outcome"] == "committed"
    assert recovered.finished_at == receipt["job_snapshot"]["finished_at"]
    assert knowledge.get_document(new.document_id).status == "published"
    assert knowledge.get_document(old.document_id).status == "published"
    assert sorted(vectors.all_points(), key=lambda p: p["point_id"]) == sorted(before, key=lambda p: p["point_id"])
    assert recovered.metadata["previous_publication_restored"] is True
    assert recovered.metadata["retirement_pending"] is True


def test_recovery_healthy_retirement(rig):
    _, knowledge, vectors, _ = rig
    old, new, fresh = replacement(rig)
    recovered = fresh.recover_publication(new.job_id, **SCOPE)
    assert recovered.status == "published"
    assert recovered.metadata["retirement_pending"] is False
    assert knowledge.get_document(old.document_id).status == "unpublished"
    assert vectors.count_for_document(old.document_id, SCOPE["collection_id"]) == 0


@pytest.mark.parametrize("which", ["old", "new"])
def test_recovery_foreign_successor_untouched(rig, which):
    _, knowledge, vectors, _ = rig
    old, new, fresh = replacement(rig)
    doc = deepcopy(knowledge.get_document((old if which == "old" else new).document_id))
    doc.metadata[ATTEMPT_METADATA_KEY] = "foreign-successor"
    knowledge.upsert_document(doc)
    before = deepcopy(vectors.all_points())
    vectors.target = old.document_id
    recovered = fresh.recover_publication(new.job_id, **SCOPE)
    assert recovered.status == "published" and recovered.metadata["retirement_superseded"]
    assert vectors.all_points() == before
    assert knowledge.get_document(doc.document_id) == doc


def test_recovery_failed_restoration_keeps_old_hidden(rig):
    _, knowledge, vectors, _ = rig
    old, new, fresh = replacement(rig)
    vectors.target, vectors.partial, vectors.restore_fails = old.document_id, True, True
    recovered = fresh.recover_publication(new.job_id, **SCOPE)
    assert recovered.status == "published"
    assert knowledge.get_document(old.document_id).status == "unpublished"
    assert recovered.metadata["previous_publication_restored"] is False
    assert recovered.metadata["retirement_pending"] is True


@pytest.mark.parametrize("which", ["old", "new"])
def test_delete_failure_cannot_restore_successor_installed_during_delete(rig, which):
    _, knowledge, vectors, _ = rig
    old, new, fresh = replacement(rig)
    successor = deepcopy(knowledge.get_document((old if which == "old" else new).document_id))
    successor.metadata[ATTEMPT_METADATA_KEY] = "foreign-successor"
    vectors.target = old.document_id
    vectors.on_delete = lambda: knowledge.upsert_document(successor)
    before = deepcopy(vectors.all_points())
    recovered = fresh.recover_publication(new.job_id, **SCOPE)
    assert recovered.status == "published" and recovered.metadata["retirement_superseded"]
    assert knowledge.get_document(successor.document_id) == successor
    assert vectors.all_points() == before


def test_foreign_point_source_is_not_compensated(rig):
    _, knowledge, vectors, _ = rig
    old, new, fresh = replacement(rig)
    point = next(p for p in vectors.all_points() if p["payload"]["document_id"] == old.document_id)
    point["payload"]["object_ref"] = "foreign-source"
    vectors.target = old.document_id
    before = deepcopy(vectors.all_points())
    recovered = fresh.recover_publication(new.job_id, **SCOPE)
    assert recovered.status == "published" and recovered.metadata["retirement_pending"]
    assert vectors.all_points() == before
    assert knowledge.get_document(old.document_id).status == "unpublished"
    assert recovered.metadata["previous_publication_restored"] is False


def test_already_hidden_partial_index_cannot_be_republished(rig):
    _, knowledge, vectors, _ = rig
    old, new, fresh = replacement(rig)
    knowledge.set_document_status(old.document_id, "unpublished")
    vectors.target, vectors.partial = old.document_id, True
    recovered = fresh.recover_publication(new.job_id, **SCOPE)
    assert recovered.status == "published" and recovered.metadata["retirement_pending"]
    assert knowledge.get_document(old.document_id).status == "unpublished"


def test_active_public_cancel_compensates_and_does_not_replay(rig):
    service, knowledge, vectors, path = rig
    seen = []

    class Events:
        def emit(self, event):
            seen.append(event["type"])
            if event["type"] == "ingestion.cancelled":
                raise CancelledError()

    class CancelEmbedding(DeterministicHashEmbedding):
        def embed(self, texts):
            job = next(j for j in service._jobs.values() if j.status == "embedding")
            assert service.cancel(job.job_id) is True
            return super().embed(texts)

    service.events, service.embeddings = Events(), CancelEmbedding()
    job = service.ingest(path, **SCOPE)
    assert job.status == "cancelled" and not vectors.all_points()
    assert seen.count("ingestion.cancelled") == 1
    assert knowledge.get_ingestion_checkpoint(job.job_id, **SCOPE)["state"] == "cancelled"


@pytest.mark.parametrize("cancel_notification", [False, True])
def test_public_cancel_terminal_checkpoint_and_single_notification(rig, cancel_notification):
    service, knowledge, vectors, path = rig
    seen = []
    observed = {}

    class Events:
        def emit(self, event):
            seen.append(event["type"])
            if event["type"] == "ingestion.start":
                try:
                    observed["result"] = service.cancel(event["job_id"])
                except CancelledError as exc:
                    observed["escaped"] = exc
                job = service.get_status(event["job_id"])
                checkpoint = knowledge.get_ingestion_checkpoint(job.job_id, **SCOPE)
                observed["job_status"] = job.status
                observed["checkpoint_state"] = checkpoint["state"]
                observed["durable_cancel_requested"] = checkpoint["cancel_requested"]
            if event["type"] == "ingestion.cancelled" and cancel_notification:
                raise CancelledError()

    service.events = Events()
    job = service.ingest(path, **SCOPE)
    assert "escaped" not in observed, "public cancel notification cancellation escaped"
    assert observed["result"] is True
    assert observed["job_status"] == "cancelled" and observed["checkpoint_state"] == "active"
    assert observed["durable_cancel_requested"] is True
    assert job.status == "cancelled"
    assert seen.count("ingestion.cancelled") == 1
    checkpoint = knowledge.get_ingestion_checkpoint(job.job_id, **SCOPE)
    assert checkpoint["state"] == "cancelled"
    assert checkpoint["job_snapshot"]["finished_at"] == job.finished_at
    if cancel_notification:
        assert job.metadata["cancellation_notification_cancelled"] is True
        assert checkpoint["job_snapshot"]["metadata"]["cancellation_notification_cancelled"] is True
    assert not vectors.all_points()
    assert service.cancel(job.job_id) is False
    recovered = IngestionService(knowledge=knowledge, vectors=vectors,
        embeddings=DeterministicHashEmbedding(), events=service.events).recover_publication(job.job_id, **SCOPE)
    assert recovered.status == "cancelled"
    assert seen.count("ingestion.cancelled") == 1


def test_committed_cancellation_boundary(rig):
    service, knowledge, vectors, path = rig
    seen = []

    class Events:
        def emit(self, event):
            seen.append(event["type"])
            if event["type"] == "ingestion.completed":
                assert service.cancel(event["job_id"]) is False

    service.events = Events()
    job = service.ingest(path, **SCOPE)
    assert job.status == "published" and "ingestion.cancelled" not in seen
    assert knowledge.get_ingestion_checkpoint(job.job_id, **SCOPE)["state"] == "committed"


@pytest.mark.parametrize("which", ["old", "new"])
def test_live_reindex_delete_failure_cannot_compensate_foreign_successor(rig, which):
    service, knowledge, vectors, path = rig
    old = service.ingest(path, **SCOPE)
    assert old.status == "published"
    path.write_text("The changed document belongs to a new publication.")
    installed = {}

    def successor_during_delete():
        document_id = (old.document_id if which == "old" else
                       next(j.document_id for j in service._jobs.values()
                            if j.status == "published" and j.document_id != old.document_id))
        successor = deepcopy(knowledge.get_document(document_id))
        successor.metadata[ATTEMPT_METADATA_KEY] = "foreign-successor"
        successor.status = "unpublished"
        knowledge.upsert_document(successor)
        installed["document"] = successor

    vectors.target, vectors.partial = old.document_id, True
    vectors.on_delete = successor_during_delete
    new = service.reindex(old.document_id, path, **SCOPE)
    assert new.status == "published"
    assert knowledge.get_publication(new.job_id, **SCOPE)["outcome"] == "committed"
    assert knowledge.get_document(installed["document"].document_id) == installed["document"]
    assert vectors.count_for_document(old.document_id, SCOPE["collection_id"]) == 0
    assert new.metadata["retirement_superseded"] is True
    assert new.metadata["retirement_pending"] is False


@pytest.mark.parametrize("fails", [False, True])
def test_live_reindex_of_hidden_index_never_republishes_old_version(rig, fails):
    service, knowledge, vectors, path = rig
    old = service.ingest(path, **SCOPE)
    knowledge.set_document_status(old.document_id, "unpublished")
    path.write_text("New replacement of a hidden document.")
    if fails:
        vectors.target, vectors.partial = old.document_id, True
    new = service.reindex(old.document_id, path, **SCOPE)
    assert new.status == "published"
    assert knowledge.get_publication(new.job_id, **SCOPE)["outcome"] == "committed"
    assert knowledge.get_document(old.document_id).status == "unpublished"
    assert new.metadata["retirement_pending"] is fails
    if not fails:
        assert vectors.count_for_document(old.document_id, SCOPE["collection_id"]) == 0


def test_incomplete_old_index_is_hidden_without_restoring_partial_snapshot(rig):
    from rick_ingestion.chunking import ChunkPlan
    from rick_knowledge import content_checksum
    service, knowledge, vectors, path = rig

    class TwoChunks:
        def chunk(self, **kwargs):
            return [ChunkPlan(text=text, chunk_index=index, page_start=1,
                              checksum=content_checksum(text))
                    for index, text in enumerate(("first original chunk", "second original chunk"))]

    service.chunker = TwoChunks()
    old = service.ingest(path, **SCOPE)
    assert old.status == "published"
    assert len(knowledge.get_chunks(old.document_id)) == 2
    point = next(p for p in vectors.all_points() if p["payload"]["document_id"] == old.document_id)
    del vectors._points[point["point_id"]]
    path.write_text("A replacement with a different content checksum.")
    new = service.reindex(old.document_id, path, **SCOPE)
    assert new.status == "published"
    assert knowledge.get_publication(new.job_id, **SCOPE)["outcome"] == "committed"
    assert knowledge.get_document(old.document_id).status == "unpublished"
    assert new.metadata["previous_publication_restored"] is False
    assert vectors.count_for_document(old.document_id, SCOPE["collection_id"]) == 1
    recovered = IngestionService(knowledge=knowledge, vectors=vectors,
        embeddings=DeterministicHashEmbedding()).recover_publication(new.job_id, **SCOPE)
    assert recovered.status == "published"
    assert knowledge.get_document(old.document_id).status == "unpublished"
    assert vectors.count_for_document(old.document_id, SCOPE["collection_id"]) == 0


def test_cancel_checkpoint_cannot_compensate_document_in_other_collection(rig):
    from rick_ingestion.jobs import IngestionJob
    from rick_knowledge.fencing import OwnershipLostError
    service, knowledge, vectors, path = rig
    other = dict(SCOPE, collection_id="other")
    foreign = service.ingest(path, **other)
    assert foreign.status == "published"
    knowledge.set_document_status(foreign.document_id, "processing")
    job = IngestionJob(**SCOPE, document_id=foreign.document_id,
        metadata={"publication_attempt": foreign.metadata["publication_attempt"]})
    knowledge.begin_ingestion_checkpoint(job)
    knowledge.save_ingestion_checkpoint(job, fingerprint={"document_id": foreign.document_id}, artifacts={})
    knowledge.request_ingestion_cancel(job)
    before = deepcopy((knowledge.get_document(foreign.document_id),
        knowledge.get_chunks(foreign.document_id), vectors.all_points(),
        knowledge.get_ingestion_checkpoint(job.job_id, **SCOPE)))
    fresh = IngestionService(knowledge=knowledge, vectors=vectors,
        embeddings=DeterministicHashEmbedding())
    with pytest.raises(OwnershipLostError):
        fresh.recover_publication(job.job_id, **SCOPE)
    assert (knowledge.get_document(foreign.document_id),
        knowledge.get_chunks(foreign.document_id), vectors.all_points(),
        knowledge.get_ingestion_checkpoint(job.job_id, **SCOPE)) == before
