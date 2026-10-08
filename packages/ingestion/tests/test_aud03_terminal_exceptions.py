"""Discriminate typed precommit failures from errors after real publication."""
from contextlib import contextmanager
from copy import deepcopy

import pytest

from rick_ingestion import IngestionService, ParseError
from rick_ingestion.pipeline import _CancellationRequested, _EmbeddingBatchError
from rick_knowledge import InMemoryKnowledgeStore, SQLiteKnowledgeStore
from rick_retrieval import DeterministicHashEmbedding, InMemoryVectorStore, SQLiteVectorStore


def publication_error(category):
    if category == "parse":
        return ParseError("lock_unavailable", "Lease authority failed.")
    if category == "embedding":
        return _EmbeddingBatchError("provider_unavailable", "Provider authority failed.")
    if category == "cancel":
        return _CancellationRequested()
    return RuntimeError("Publication guard failed.")


def snapshot(knowledge, vectors, document_id):
    return deepcopy((knowledge.get_document(document_id), knowledge.get_chunks(document_id), vectors.all_points()))


def stores(tmp_path, kind):
    if kind == "memory":
        return InMemoryKnowledgeStore(), InMemoryVectorStore()
    return SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite"), SQLiteVectorStore(tmp_path / "vectors.sqlite")


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
@pytest.mark.parametrize("deduplicated", [False, True])
@pytest.mark.parametrize("category", ["runtime", "parse", "embedding", "cancel"])
def test_all_exception_categories_after_commit_preserve_exact_publication(tmp_path, kind, deduplicated, category):
    knowledge, vectors = stores(tmp_path, kind)
    service = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=DeterministicHashEmbedding())
    path = tmp_path / "guide.txt"
    path.write_text("Publication integrity with typed guard failures. " * 80)
    scope = dict(tenant_id="t", workspace_id="w", collection_id="c")
    if deduplicated:
        assert service.ingest(path, **scope).status == "published"
    committed = []

    @contextmanager
    def guard():
        yield
        job = service.get_status("terminal-error")
        assert job.status == "published"
        committed.append(snapshot(knowledge, vectors, job.document_id))
        raise publication_error(category)

    result, escaped = None, None
    try:
        result = service.ingest(path, **scope, job_id="terminal-error", publication_guard=guard)
    except Exception as exc:
        escaped = repr(exc)
    job = service.get_status("terminal-error")
    actual = snapshot(knowledge, vectors, job.document_id)
    reopened = None
    if kind == "sqlite":
        knowledge.close()
        vectors.close()
        knowledge, vectors = stores(tmp_path, kind)
        try:
            reopened = snapshot(knowledge, vectors, job.document_id)
        finally:
            knowledge.close()
            vectors.close()
    print("postcommit", kind, deduplicated, category, "escaped", escaped,
          "job", job.status, "document", actual[0].status,
          "chunks", len(actual[1]), "points", len(actual[2]))
    assert committed and committed[0][0].status == "published"
    assert committed[0][1] and committed[0][2]
    assert escaped is None
    assert result is job and job.status == "published"
    assert job.error_code is None
    assert job.metadata["publication_guard_error_after_commit"] is True
    assert actual == committed[0]
    if kind == "sqlite":
        assert reopened == committed[0]


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
@pytest.mark.parametrize("deduplicated", [False, True])
@pytest.mark.parametrize("category", ["runtime", "parse", "embedding", "cancel"])
@pytest.mark.parametrize("boundary", ["entry", "precommit"])
def test_typed_errors_before_commit_still_reject_and_compensate(tmp_path, kind, deduplicated, category, boundary):
    knowledge, vectors = stores(tmp_path, kind)
    service = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=DeterministicHashEmbedding())
    path = tmp_path / "guide.txt"
    path.write_text("Publication integrity before the commit boundary. " * 80)
    scope = dict(tenant_id="t", workspace_id="w", collection_id="c")
    original = None
    if deduplicated:
        first = service.ingest(path, **scope)
        assert first.status == "published"
        original = snapshot(knowledge, vectors, first.document_id)

    class Guard:
        def __enter__(self):
            if boundary == "entry":
                raise publication_error(category)
            return self

        def check(self):
            raise publication_error(category)

        def __exit__(self, *_):
            return False

    try:
        result = service.ingest(path, **scope, publication_guard=Guard)
        actual = snapshot(knowledge, vectors, result.document_id)
        assert result.status == ("cancelled" if category == "cancel" else "failed")
        assert not result.metadata.get("publication_guard_error_after_commit")
        if category == "parse":
            assert result.error_code == "lock_unavailable"
        elif category == "embedding":
            assert result.error_code == "provider_unavailable"
        if deduplicated:
            assert actual == original
        else:
            assert actual[0].status == "failed"
            assert actual[1] == actual[2] == []
    finally:
        if kind == "sqlite":
            knowledge.close()
            vectors.close()
