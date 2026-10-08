"""Cancellation requests cannot terminalize an unresolved publication commit."""
import asyncio
from copy import deepcopy
from threading import Event, Thread

import pytest

from rick_ingestion import IngestionService
from rick_ingestion.pipeline import _scoped_call
from rick_knowledge import InMemoryKnowledgeStore, SQLiteKnowledgeStore
from rick_retrieval import DeterministicHashEmbedding, InMemoryVectorStore, SQLiteVectorStore


@pytest.fixture(params=["memory", "sqlite"])
def lab(request, tmp_path):
    knowledge = InMemoryKnowledgeStore() if request.param == "memory" else SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite")
    vectors = InMemoryVectorStore() if request.param == "memory" else SQLiteVectorStore(tmp_path / "vectors.sqlite")
    events = []

    class Events:
        def emit(self, event):
            events.append(deepcopy(event))

    pipeline = IngestionService(knowledge=knowledge, vectors=vectors,
                               embeddings=DeterministicHashEmbedding(), events=Events())
    source = tmp_path / "source.txt"
    source.write_text("Durable publication owns its outcome through acknowledgement loss. " * 70)
    yield pipeline, knowledge, vectors, source, events
    for store in (knowledge, vectors):
        close = getattr(store, "close", None)
        if close:
            close()


@pytest.mark.parametrize("signal", [RuntimeError, asyncio.CancelledError])
@pytest.mark.parametrize("committed", [True, False])
def test_cancel_during_lost_acknowledgement_resolves_owned_outcome(lab, signal, committed):
    pipeline, knowledge, vectors, source, events = lab
    scope = dict(tenant_id="t", workspace_id="w", collection_id="c")
    recovering, cancelled = Event(), Event()
    acknowledgement_lost = False
    cancellation_results, thread_errors = [], []

    class InterruptedAcknowledgement:
        def __getattr__(self, name):
            return getattr(knowledge, name)

        def set_document_status(self, document_id, status, **kwargs):
            nonlocal acknowledgement_lost
            if status == "published":
                if committed:
                    _scoped_call(knowledge.set_document_status, document_id, status, **kwargs)
                acknowledgement_lost = True
                raise signal("publication acknowledgement interrupted")
            return _scoped_call(knowledge.set_document_status, document_id, status, **kwargs)

        def get_document(self, document_id, **kwargs):
            if acknowledgement_lost:
                recovering.set()
                assert cancelled.wait(3), "cancellation must remain responsive during commit recovery"
            return knowledge.get_document(document_id, **kwargs)

    pipeline.knowledge = InterruptedAcknowledgement()

    def cancel():
        try:
            assert recovering.wait(3)
            cancellation_results.append(pipeline.cancel("ack-race"))
        except BaseException as error:
            thread_errors.append(error)
        finally:
            cancelled.set()

    thread = Thread(target=cancel, daemon=True)
    thread.start()
    try:
        result = pipeline.ingest(source, job_id="ack-race", **scope)
    finally:
        cancelled.set()
        thread.join(4)
    assert not thread.is_alive() and not thread_errors
    assert cancellation_results == [True]
    document = knowledge.get_document(result.document_id)
    chunks = knowledge.get_chunks(result.document_id)
    points = _scoped_call(vectors.count_for_document, result.document_id, "c",
                          tenant_id="t", workspace_id="w")
    if committed:
        assert result.status == document.status == "published"
        assert result.error_code is None
        assert result.metadata["publication_guard_error_after_commit"] is True
        assert points == len(chunks) > 0
        assert not any(event["type"] == "ingestion.cancelled" for event in events)
        assert sum(event["type"] == "ingestion.completed" for event in events) == 1
        assert pipeline.cancel(result.job_id) is False
    else:
        assert result.status == "cancelled" and document.status == "failed"
        assert chunks == [] and points == 0
        assert not any(event["type"] == "ingestion.completed" for event in events)


def test_healthy_cancel_before_commit_still_prevents_publication(lab):
    pipeline, knowledge, vectors, source, events = lab
    at_check, cancelled = Event(), Event()
    cancellation_results, thread_errors = [], []

    class Guard:
        def __enter__(self):
            return self

        def check(self):
            at_check.set()
            assert cancelled.wait(3)

        def __exit__(self, *_):
            return False

    def cancel():
        try:
            assert at_check.wait(3)
            cancellation_results.append(pipeline.cancel("before-commit"))
        except BaseException as error:
            thread_errors.append(error)
        finally:
            cancelled.set()

    thread = Thread(target=cancel, daemon=True)
    thread.start()
    try:
        result = pipeline.ingest(source, job_id="before-commit", tenant_id="t",
                                 workspace_id="w", collection_id="c", publication_guard=Guard)
    finally:
        cancelled.set()
        thread.join(4)
    assert not thread.is_alive() and not thread_errors
    assert cancellation_results == [True]
    assert result.status == "cancelled"
    assert knowledge.get_document(result.document_id).status == "failed"
    assert knowledge.get_chunks(result.document_id) == [] and vectors.all_points() == []
    assert not any(event["type"] == "ingestion.completed" for event in events)
