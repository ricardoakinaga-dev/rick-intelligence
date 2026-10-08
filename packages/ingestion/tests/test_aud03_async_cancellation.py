"""Supported async cancellation is discriminated from process termination."""
import asyncio
from copy import deepcopy
from threading import Event, Thread

import pytest

from rick_ingestion import IngestionService
from rick_ingestion.pipeline import _scoped_call
from rick_knowledge import InMemoryKnowledgeStore, SQLiteKnowledgeStore
from rick_retrieval import DeterministicHashEmbedding, InMemoryVectorStore


def count(vectors, document_id, scope):
    return sum(point["payload"]["document_id"] == document_id
               and all(point["payload"][key] == value for key, value in scope.items())
               for point in vectors.all_points())


@pytest.fixture(params=["memory", "sqlite"])
def lab(request, tmp_path):
    knowledge = InMemoryKnowledgeStore() if request.param == "memory" else SQLiteKnowledgeStore(tmp_path / "cancel.sqlite")
    vectors = InMemoryVectorStore()
    pipeline = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=DeterministicHashEmbedding())
    source = tmp_path / "guide.txt"
    source.write_text("Cancellation must respect publication ownership. " * 90)
    yield pipeline, knowledge, vectors, source, dict(tenant_id="t", workspace_id="w", collection_id="c")
    close = getattr(knowledge, "close", None)
    if close:
        close()


@pytest.mark.parametrize("phase", ["entry", "check", "exit"])
@pytest.mark.parametrize("operation", ["ingest", "duplicate", "reindex"])
def test_async_cancel_guard_reports_real_outcome(lab, phase, operation):
    pipeline, knowledge, vectors, source, scope = lab
    previous = None
    if operation != "ingest":
        previous = pipeline.ingest(source, **scope)
        if operation == "reindex":
            source.write_text("Replacement must survive cancellation after commit. " * 80)
    retained = deepcopy((knowledge.get_document(previous.document_id), vectors.all_points())) if previous else None
    class Guard:
        def __enter__(self):
            if phase == "entry":
                raise asyncio.CancelledError()
            return self
        def check(self):
            if phase == "check":
                raise asyncio.CancelledError()
        def __exit__(self, *_):
            if phase == "exit":
                raise asyncio.CancelledError()
    result = pipeline.reindex(previous.document_id, source, **scope, publication_guard=Guard) if operation == "reindex" else pipeline.ingest(source, **scope, publication_guard=Guard)
    doc = knowledge.get_document(result.document_id)
    if phase == "exit":
        assert result.status == doc.status == "published"
        assert result.metadata["publication_guard_error_after_commit"]
        assert knowledge.get_chunks(doc.document_id)
        assert count(vectors, doc.document_id, scope) == len(knowledge.get_chunks(doc.document_id))
    else:
        assert result.status == "failed"
        if operation == "duplicate":
            assert deepcopy((knowledge.get_document(previous.document_id), vectors.all_points())) == retained
        else:
            assert doc.status == "failed" and knowledge.get_chunks(doc.document_id) == []
            assert count(vectors, doc.document_id, scope) == 0


@pytest.mark.parametrize("signal", [SystemExit, KeyboardInterrupt])
def test_process_termination_is_not_swallowed(lab, signal):
    pipeline, _, _, source, scope = lab
    class Events:
        def emit(self, event):
            if event["type"] == "ingestion.completed":
                raise signal()
    pipeline.events = Events()
    with pytest.raises(signal):
        pipeline.ingest(source, **scope)
    assert next(iter(pipeline._jobs.values())).status == "published"


def test_async_cancel_terminal_notification_does_not_escape(lab):
    pipeline, knowledge, _, source, scope = lab
    class Events:
        def emit(self, event):
            if event["type"] in {"ingestion.start", "ingestion.failed"}:
                raise asyncio.CancelledError()
    pipeline.events = Events()
    result = pipeline.ingest(source, **scope)
    assert result.status == "failed" and result.document_id is None


def test_cancelled_stale_attempt_compensates_only_its_owned_effects(lab):
    pipeline, knowledge, vectors, source, scope = lab
    paused, release = Event(), Event()
    class Partial:
        def __getattr__(self, name):
            return getattr(vectors, name)
        def plan_upsert_batches(self, points):
            yield points[:1]
            paused.set()
            assert release.wait(5)
            raise asyncio.CancelledError()
    pipeline.vectors = Partial()
    results, errors = [], []
    def stale():
        try:
            results.append(pipeline.ingest(source, **scope))
        except BaseException as error:
            errors.append(type(error).__name__)
    thread = Thread(target=stale)
    thread.start()
    try:
        assert paused.wait(5)
        successor = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=DeterministicHashEmbedding())
        winner = successor.ingest(source, **scope)
        before = deepcopy((knowledge.get_document(winner.document_id), knowledge.get_chunks(winner.document_id), vectors.all_points()))
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive() and not errors
    assert results[0].status == "failed" and winner.status == "published"
    assert deepcopy((knowledge.get_document(winner.document_id), knowledge.get_chunks(winner.document_id), vectors.all_points())) == before


def test_cancel_during_retirement_restores_previous_and_preserves_new_publication(lab):
    pipeline, knowledge, vectors, source, scope = lab
    old = pipeline.ingest(source, **scope)
    old_before = deepcopy((knowledge.get_document(old.document_id), knowledge.get_chunks(old.document_id), vectors.all_points()))
    source.write_text("New durable content must survive interrupted retirement. " * 70)
    class InterruptedRetirement:
        def __getattr__(self, name):
            return getattr(vectors, name)
        def delete_document(self, document_id, collection_id):
            result = vectors.delete_document(document_id, collection_id)
            if document_id == old.document_id:
                raise asyncio.CancelledError()
            return result
    pipeline.vectors = InterruptedRetirement()
    result = pipeline.reindex(old.document_id, source, **scope)
    assert result.status == knowledge.get_document(result.document_id).status == "published"
    assert count(vectors, result.document_id, scope) == len(knowledge.get_chunks(result.document_id)) > 0
    assert (knowledge.get_document(old.document_id), knowledge.get_chunks(old.document_id)) == old_before[:2]
    assert count(vectors, old.document_id, scope) == len(old_before[2])
    assert result.metadata["previous_publication_restored"] is True


def test_cancel_after_status_commit_before_acknowledgement_reports_publication(lab):
    pipeline, knowledge, vectors, source, scope = lab
    class InterruptedAcknowledgement:
        def __getattr__(self, name):
            return getattr(knowledge, name)
        def set_document_status(self, document_id, status, **kwargs):
            result = _scoped_call(knowledge.set_document_status, document_id, status, **kwargs)
            if status == "published":
                raise asyncio.CancelledError()
            return result
    pipeline.knowledge = InterruptedAcknowledgement()
    result = pipeline.ingest(source, **scope)
    doc = knowledge.get_document(result.document_id)
    assert result.status == doc.status == "published"
    assert count(vectors, doc.document_id, scope) == len(knowledge.get_chunks(doc.document_id)) > 0
    assert result.metadata["publication_guard_error_after_commit"] is True
