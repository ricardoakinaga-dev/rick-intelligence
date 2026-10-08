"""Ingestion unit tests: idempotency, versions, failures, jobs, storage safety."""

from contextlib import contextmanager
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "knowledge" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "retrieval" / "src"))

import pytest

from rick_ingestion import (
    IngestionJob,
    IngestionService,
    InvalidTransitionError,
    MAX_HEARTBEATS,
    ParseError,
    ParsedDocument,
    ParsedPage,
    RecursiveChunkingStrategy,
    generated_storage_name,
    is_retryable,
    sanitize_display_filename,
    validate_file,
)
from rick_knowledge import InMemoryKnowledgeStore
from rick_retrieval import DeterministicHashEmbedding, InMemoryVectorStore


def _doc(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


def _service():
    return IngestionService(knowledge=InMemoryKnowledgeStore(), vectors=InMemoryVectorStore(),
                            embeddings=DeterministicHashEmbedding())


def test_idempotent_reingest_no_drift(tmp_path):
    service = _service()
    target = _doc(tmp_path / "guide.txt", "Mastite bovina: protocolo de ordenha. " * 40)
    first = service.ingest(target, workspace_id="w", collection_id="rag_phase0", tenant_id="default")
    assert first.status == "published"
    doc_id = first.document_id
    n_points = service.vectors.count_for_document(doc_id, "rag_phase0")
    assert n_points > 0
    second = service.ingest(target, workspace_id="w", collection_id="rag_phase0", tenant_id="default")
    assert second.status == "published" and second.document_id == doc_id
    assert service.vectors.count_for_document(doc_id, "rag_phase0") == n_points


def test_deduplicated_publication_uses_the_application_gate(tmp_path):
    service = _service()
    target = _doc(tmp_path / "guarded.txt", "Publication guard. " * 40)
    first = service.ingest(target, workspace_id="w", collection_id="rag_phase0", tenant_id="default")
    calls = []

    @contextmanager
    def publication_guard():
        calls.append("enter")
        try:
            yield
        finally:
            calls.append("exit")

    second = service.ingest(
        target,
        workspace_id="w",
        collection_id="rag_phase0",
        tenant_id="default",
        publication_guard=publication_guard,
    )

    assert second.status == "published"
    assert second.document_id == first.document_id
    assert calls == ["enter", "exit"]


def test_cancel_duplicate_after_identity_preserves_publication(tmp_path):
    service = _service()
    target = _doc(tmp_path / "duplicate.txt", "Conteudo publicado. " * 400)
    first = service.ingest(target, workspace_id="w", collection_id="rag_phase0", tenant_id="default")
    points = service.vectors.all_points()
    chunks = service.knowledge.get_chunks(first.document_id)

    def cancel_after_identity():
        job = service.get_status("cancel-duplicate")
        return job.document_id is not None

    second = service.ingest(
        target, workspace_id="w", collection_id="rag_phase0", tenant_id="default",
        job_id="cancel-duplicate", cancel_check=cancel_after_identity,
    )
    assert second.status == "cancelled"
    assert points and service.vectors.all_points() == points
    assert service.knowledge.get_chunks(first.document_id) == chunks
    assert service.knowledge.get_document(first.document_id).status == "published"


def test_committed_reindex_to_existing_target_preserves_both_documents_on_retirement_failure(tmp_path):
    service = _service()
    original = _doc(tmp_path / "a.txt", "Documento original. " * 400)
    target = _doc(tmp_path / "b.txt", "Outro documento publicado. " * 400)
    first = service.ingest(original, workspace_id="w", collection_id="rag_phase0", tenant_id="default")
    second = service.ingest(target, workspace_id="w", collection_id="rag_phase0", tenant_id="default")
    delegate = service.vectors
    points = delegate.all_points()
    chunks = service.knowledge.get_chunks(second.document_id)

    class FailAfterRetirement:
        def __getattr__(self, name):
            return getattr(delegate, name)

        def delete_document(self, document_id, collection_id):
            result = delegate.delete_document(document_id, collection_id)
            if document_id == first.document_id:
                raise RuntimeError("lost acknowledgement")
            return result

    service.vectors = FailAfterRetirement()
    failed = service.reindex(
        first.document_id, target, workspace_id="w", collection_id="rag_phase0", tenant_id="default"
    )
    assert failed.status == "published"
    assert failed.metadata['retirement_pending'] is True
    assert failed.document_id == second.document_id
    assert sorted(delegate.all_points(), key=lambda p: p["point_id"]) == sorted(points, key=lambda p: p["point_id"])
    assert service.knowledge.get_chunks(second.document_id) == chunks
    for job in (first, second):
        assert service.knowledge.get_document(job.document_id).status == "published"


def test_overlapping_duplicate_cancellation_cannot_erase_other_publication(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    service = _service()
    target = _doc(tmp_path / "concurrent.txt", "Conteudo concorrente. " * 400)
    delegate = service.vectors
    first_indexed, release_first, second_started, second_indexed = (Event() for _ in range(4))

    class PauseFirstWrite:
        calls = 0

        def __getattr__(self, name):
            return getattr(delegate, name)

        def upsert_points(self, points):
            result = delegate.upsert_points(points)
            self.calls += 1
            if self.calls == 1:
                first_indexed.set()
                assert release_first.wait(3)
            else:
                second_indexed.set()
            return result

    service.vectors = PauseFirstWrite()

    def ingest(job_id):
        if job_id == "overlap-b":
            second_started.set()
        return service.ingest(
            target, workspace_id="w", collection_id="rag_phase0", tenant_id="default", job_id=job_id
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(ingest, "overlap-a")
        try:
            assert first_indexed.wait(2)
            second = pool.submit(ingest, "overlap-b")
            assert second_started.wait(2)
            assert not second_indexed.wait(0.1)
            assert service.cancel("overlap-a") is True
        finally:
            release_first.set()
        cancelled, published = first.result(timeout=3), second.result(timeout=3)

    assert cancelled.status == "cancelled"
    assert published.status == "published"
    assert published.document_id == cancelled.document_id
    assert service.knowledge.get_document(published.document_id).status == "published"
    chunks = service.knowledge.get_chunks(published.document_id)
    assert chunks
    assert delegate.count_for_document(published.document_id, "rag_phase0") == len(chunks)


def test_changed_content_new_version_and_prune(tmp_path):
    service = _service()
    target = _doc(tmp_path / "guide.txt", "Versao um do protocolo. " * 40)
    first = service.ingest(target, workspace_id="w", collection_id="rag_phase0", tenant_id="default")
    target.write_text("Versao dois do protocolo, atualizada. " * 40)
    second = service.reindex(
        first.document_id, target, workspace_id="w", collection_id="rag_phase0", tenant_id="default"
    )
    assert second.status == "published" and second.document_id != first.document_id
    assert service.vectors.count_for_document(first.document_id, "rag_phase0") == 0
    assert service.knowledge.get_document(first.document_id).status == "unpublished"


def test_failed_reindex_preserves_the_current_published_version(tmp_path):
    knowledge = InMemoryKnowledgeStore()
    vectors = InMemoryVectorStore()
    service = IngestionService(
        knowledge=knowledge,
        vectors=vectors,
        embeddings=DeterministicHashEmbedding(),
    )
    target = _doc(tmp_path / "guide.txt", "Versao publicada e segura. " * 40)
    first = service.ingest(target, workspace_id="w", collection_id="rag_phase0", tenant_id="default")
    old_count = vectors.count_for_document(first.document_id, "rag_phase0")

    class FailingEmbedding:
        model = "fixture"
        dimensions = 8

        def embed(self, texts):
            raise RuntimeError("provider unavailable")

    service.embeddings = FailingEmbedding()
    target.write_text("Versao nova que falha no provider. " * 40)
    failed = service.reindex(
        first.document_id,
        target,
        workspace_id="w",
        collection_id="rag_phase0",
        tenant_id="default",
    )

    assert failed.status == "failed"
    assert knowledge.get_document(first.document_id).status == "published"
    assert vectors.count_for_document(first.document_id, "rag_phase0") == old_count


def test_reindex_retirement_failure_preserves_committed_new_version_and_restores_old_index(tmp_path):
    knowledge = InMemoryKnowledgeStore()
    base_vectors = InMemoryVectorStore()
    service = IngestionService(
        knowledge=knowledge,
        vectors=base_vectors,
        embeddings=DeterministicHashEmbedding(),
    )
    target = _doc(tmp_path / "atomic.txt", "Versao antiga publicada. " * 40)
    first = service.ingest(target, workspace_id="w", collection_id="rag_phase0", tenant_id="default")
    old_count = base_vectors.count_for_document(first.document_id, "rag_phase0")

    class FailingRetirementStore:
        def __init__(self, delegate, old_id):
            self.delegate = delegate
            self.old_id = old_id

        def upsert_points(self, points):
            return self.delegate.upsert_points(points)

        def delete_document(self, document_id, collection_id):
            if document_id == self.old_id:
                raise RuntimeError("retirement failed")
            return self.delegate.delete_document(document_id, collection_id)

        def count_for_document(self, document_id, collection_id):
            return self.delegate.count_for_document(document_id, collection_id)

        def all_points(self):
            return self.delegate.all_points()

    service.vectors = FailingRetirementStore(base_vectors, first.document_id)
    target.write_text("Versao nova cuja aposentadoria antiga falha. " * 40)
    failed = service.reindex(
        first.document_id, target, workspace_id="w", collection_id="rag_phase0", tenant_id="default"
    )

    assert failed.status == "published" and failed.error_code is None
    assert failed.metadata['retirement_pending'] is True
    assert knowledge.get_document(first.document_id).status == "published"
    assert base_vectors.count_for_document(first.document_id, "rag_phase0") == old_count
    assert knowledge.get_document(failed.document_id).status == "published"
    assert base_vectors.count_for_document(failed.document_id, "rag_phase0") > 0


def test_http_qdrant_reindex_restores_old_vectors_after_mutating_delete_failure(tmp_path):
    import copy
    import json

    import httpx

    from rick_retrieval import QdrantHttpVectorStore

    knowledge = InMemoryKnowledgeStore()
    embeddings = DeterministicHashEmbedding()
    points: dict[str, dict] = {}
    requests: list[tuple[str, str, dict | None]] = []
    control = {"old_document_id": None, "fail_retirement": False}

    def matches(payload, filters):
        for condition in filters:
            key = condition["key"]
            match = condition["match"]
            if "any" in match:
                if payload.get(key) not in match["any"]:
                    return False
            elif payload.get(key) != match.get("value"):
                return False
        return True

    def handle(request):
        body = json.loads(request.content) if request.content else None
        requests.append((request.method, request.url.path, body))
        if request.method == "GET":
            return httpx.Response(200, json={"result": {"status": "green", "config": {"params": {
                "vectors": {"dense": {"size": embeddings.dimensions, "distance": "Cosine"}},
                "sparse_vectors": {"sparse": {}},
            }}}})
        if request.method == "PUT" and request.url.path.endswith("/points"):
            for point in body["points"]:
                points[point["id"]] = copy.deepcopy(point)
            return httpx.Response(200, json={"result": {"status": "completed"}})
        if request.method == "POST" and request.url.path.endswith("/points/count"):
            count = sum(matches(point["payload"], body["filter"]["must"]) for point in points.values())
            return httpx.Response(200, json={"result": {"count": count}})
        if request.method == "POST" and request.url.path.endswith("/points/scroll"):
            filters = body["filter"]["must"]
            selected = sorted(
                (point for point in points.values() if matches(point["payload"], filters)),
                key=lambda point: point["id"],
            )
            offset = body.get("offset")
            start = next((index + 1 for index, point in enumerate(selected) if point["id"] == offset), 0)
            page = selected[start:start + body["limit"]]
            next_offset = page[-1]["id"] if page and start + len(page) < len(selected) else None
            return httpx.Response(200, json={"result": {
                "points": page, "next_page_offset": next_offset,
            }})
        if request.method == "POST" and request.url.path.endswith("/points/delete"):
            filters = body["filter"]["must"]
            document_id = next(item["match"]["value"] for item in filters if item["key"] == "document_id")
            selected = [point_id for point_id, point in points.items()
                        if matches(point["payload"], filters)]
            for point_id in selected:
                del points[point_id]
            if document_id == control["old_document_id"] and control["fail_retirement"]:
                control["fail_retirement"] = False
                # Qdrant applied the delete but the acknowledgement was lost.
                return httpx.Response(503, json={"status": "injected_lost_ack"})
            return httpx.Response(200, json={"result": {"status": "completed"}})
        raise AssertionError(f"unexpected Qdrant request: {request.method} {request.url.path}")

    store = QdrantHttpVectorStore(
        "http://qdrant.test",
        "rag_phase0",
        transport=httpx.MockTransport(handle),
        max_attempts=1,
        retry_backoff_seconds=0,
    )
    service = IngestionService(knowledge=knowledge, vectors=store, embeddings=embeddings)
    target = _doc(tmp_path / "http-reindex.txt", "Published HTTP Qdrant version. " * 40)
    first = service.ingest(target, workspace_id="w", collection_id="rag_phase0", tenant_id="default")
    assert first.status == "published"
    old_points = {
        point_id: copy.deepcopy(point)
        for point_id, point in points.items()
        if point["payload"]["document_id"] == first.document_id
    }
    assert old_points

    control.update(old_document_id=first.document_id, fail_retirement=True)
    target.write_text("Replacement HTTP Qdrant version. " * 40)
    failed = service.reindex(
        first.document_id,
        target,
        workspace_id="w",
        collection_id="rag_phase0",
        tenant_id="default",
    )

    assert failed.status == "published" and failed.error_code is None
    assert failed.metadata['retirement_pending'] is True
    assert knowledge.get_document(first.document_id).status == "published"
    assert knowledge.get_document(failed.document_id).status == "published"
    restored = {
        point_id: point
        for point_id, point in points.items()
        if point["payload"]["document_id"] == first.document_id
    }
    assert restored == old_points
    assert any(point["payload"]["document_id"] == failed.document_id for point in points.values())

    scroll_requests = [body for method, path, body in requests
                       if method == "POST" and path.endswith("/points/scroll")]
    assert scroll_requests
    for body in scroll_requests:
        conditions = body["filter"]["must"]
        assert {condition["key"] for condition in conditions} == {
            "tenant_id", "workspace_id", "collection_id", "document_id",
        }
        assert body["limit"] == 1 and body["with_payload"] and body["with_vector"]
    store.close()


def test_reindex_failed_compensation_never_republishes_missing_vectors(tmp_path):
    service = _service()
    target = _doc(tmp_path / "compensation.txt", "Old published version. " * 40)
    first = service.ingest(target, workspace_id="w", collection_id="rag_phase0", tenant_id="default")
    delegate = service.vectors

    class BrokenCompensation:
        def all_points(self, **kwargs):
            return delegate.all_points(**kwargs)

        def upsert_points(self, points):
            if any(p["payload"]["document_id"] == first.document_id for p in points):
                raise RuntimeError("restore failed")
            return delegate.upsert_points(points)

        def count_for_document(self, *args):
            return delegate.count_for_document(*args)

        def delete_document(self, document_id, collection_id):
            count = delegate.delete_document(document_id, collection_id)
            if document_id == first.document_id:
                raise RuntimeError("delete failed after mutation")
            return count

    service.vectors = BrokenCompensation()
    target.write_text("Replacement version. " * 40)
    failed = service.reindex(
        first.document_id, target, workspace_id="w", collection_id="rag_phase0", tenant_id="default"
    )
    assert failed.status == "published"
    assert failed.metadata['retirement_pending'] is True
    assert service.knowledge.get_document(first.document_id).status == "unpublished"
    assert service.knowledge.get_document(failed.document_id).status == "published"
    assert delegate.count_for_document(failed.document_id, "rag_phase0") > 0
    assert delegate.count_for_document(first.document_id, "rag_phase0") == 0


def test_malformed_and_unsupported_fail_safely(tmp_path):
    service = _service()
    bad = tmp_path / "evil.exe"
    bad.write_bytes(b"nope")
    job = service.ingest(bad, workspace_id="w", collection_id="rag_phase0", tenant_id="default")
    assert job.status == "failed" and job.error_code == "unsupported_media_type"
    empty = tmp_path / "empty.txt"
    empty.write_text("   ")
    job2 = service.ingest(empty, workspace_id="w", collection_id="rag_phase0", tenant_id="default")
    assert job2.status == "failed"
    assert service.knowledge.get_document(job2.document_id or "none") is None
    # Partial ingest never publishes.
    assert job2.status != "published"


def test_pipeline_enforces_optional_declared_mime(tmp_path):
    service = _service()
    target = _doc(tmp_path / "payload.txt", "ordinary text")

    job = service.ingest(
        target,
        workspace_id="w",
        collection_id="rag_phase0",
        tenant_id="default",
        declared_mime="application/pdf",
    )

    assert job.status == "failed"
    assert job.error_code == "unsupported_media_type"


class _FixedEmbedding:
    model = "fixture"
    dimensions = 2

    def __init__(self, response):
        self.response = response

    def embed(self, texts):
        return self.response


@pytest.mark.parametrize(
    "response",
    [
        [],
        [[0.0, 0.0], [0.0, 0.0]],
        [[float("nan"), 0.0]],
        [[float("inf"), 0.0]],
        [[0.0]],
    ],
)
def test_invalid_embedding_response_writes_nothing(tmp_path, response):
    knowledge = InMemoryKnowledgeStore()
    vectors = InMemoryVectorStore()
    service = IngestionService(
        knowledge=knowledge,
        vectors=vectors,
        embeddings=_FixedEmbedding(response),
    )
    target = _doc(tmp_path / "bad-embedding.txt", "finite boundary")

    job = service.ingest(target, workspace_id="w", collection_id="rag_phase0", tenant_id="default")

    assert job.status == "failed"
    assert knowledge.list_documents("w", tenant_id="default") == []
    assert vectors.all_points() == []


class _BatchEmbedding:
    model = "batch-fixture"
    dimensions = 2

    def __init__(self, fault=None):
        self.calls = []
        self.fault = fault
        self.on_batch = None

    def embed(self, texts):
        offset = sum(len(batch) for batch in self.calls)
        self.calls.append(list(texts))
        if len(texts) > 256:
            raise ValueError("embedding batch is out of range")
        if self.on_batch is not None:
            self.on_batch()
        if len(self.calls) == 2 and self.fault is not None:
            if isinstance(self.fault, Exception):
                raise self.fault
            return self.fault(texts)
        return [[float(offset + index), 1.0] for index in range(len(texts))]


class _BatchEvents:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


def _batch_ingestion(tmp_path, count, fault=None):
    target = _doc(
        tmp_path / "batches.txt",
        "\n\n".join(f"Paragraph {index:04d} " + "x" * 980 for index in range(count)),
    )
    embeddings = _BatchEmbedding(fault)
    events = _BatchEvents()
    service = IngestionService(
        knowledge=InMemoryKnowledgeStore(), vectors=InMemoryVectorStore(),
        embeddings=embeddings, events=events,
    )
    return target, service, embeddings, events


@pytest.mark.parametrize("count", [255, 256, 257, 513])
def test_embedding_batches_preserve_order_and_replay(tmp_path, count):
    target, service, embeddings, events = _batch_ingestion(tmp_path, count)

    def assert_no_partial_writes():
        assert service.knowledge.list_documents("w", tenant_id="default") == []
        assert service.vectors.all_points() == []

    embeddings.on_batch = assert_no_partial_writes
    job = service.ingest(target, workspace_id="w", collection_id="rag_phase0", tenant_id="default")

    assert job.status == "published"
    assert [len(batch) for batch in embeddings.calls] == [
        min(256, count - offset) for offset in range(0, count, 256)
    ]
    points = sorted(service.vectors.all_points(), key=lambda point: point["payload"]["chunk_index"])
    assert len(points) == count
    assert [point["vector"] for point in points] == [[float(index), 1.0] for index in range(count)]
    chunks = service.knowledge.get_chunks(job.document_id)
    assert [chunk.text for chunk in chunks] == [text for batch in embeddings.calls for text in batch]
    assert [point["payload"]["chunk_id"] for point in points] == [chunk.chunk_id for chunk in chunks]
    calls = list(embeddings.calls)
    replay = service.ingest(target, workspace_id="w", collection_id="rag_phase0", tenant_id="default")
    assert replay.status == "published"
    assert replay.document_id == job.document_id
    assert embeddings.calls == calls


@pytest.mark.parametrize(
    "fault, error_code",
    [
        (RuntimeError("private provider failure"), "provider_unavailable"),
        (ValueError("private invalid input"), "validation_error"),
        (lambda texts: [[0.0, 1.0]] * (len(texts) - 1), "validation_error"),
        (lambda texts: [[0.0, 1.0]] * (len(texts) + 1), "validation_error"),
        (lambda texts: [[0.0]] * len(texts), "validation_error"),
        (lambda texts: [[float("nan"), 1.0]] * len(texts), "validation_error"),
        (lambda texts: [[float("inf"), 1.0]] * len(texts), "validation_error"),
        (lambda texts: [[True, 1.0]] * len(texts), "validation_error"),
    ],
    ids=["unavailable", "input", "missing", "extra", "dimension", "nan", "inf", "bool"],
)
def test_embedding_batches_intermediate_failure_writes_nothing(tmp_path, fault, error_code):
    target, service, embeddings, events = _batch_ingestion(tmp_path, 513, fault)
    job = service.ingest(target, workspace_id="w", collection_id="rag_phase0", tenant_id="default")

    assert job.status == "failed"
    assert job.error_code == error_code
    assert [len(batch) for batch in embeddings.calls] == [256, 256]
    assert service.knowledge.list_documents("w", tenant_id="default") == []
    assert service.knowledge.get_chunks(job.document_id) == []
    assert service.vectors.all_points() == []
    assert events.events[-1]["retryable"] is is_retryable(error_code)
    assert "private" not in repr(events.events) + repr(job)
    assert not any(event["type"] == "ingestion.completed" for event in events.events)

    embeddings.calls.clear()
    embeddings.fault = None
    retry = service.ingest(target, workspace_id="w", collection_id="rag_phase0", tenant_id="default")
    assert retry.status == "published"
    assert retry.document_id == job.document_id
    assert len(service.vectors.all_points()) == 513


@pytest.mark.parametrize("cancel_after", [1, 2, 3])
@pytest.mark.parametrize("cancellation", ["callback", "operator"])
def test_embedding_batches_cancel_before_next_call_or_publication(tmp_path, cancel_after, cancellation):
    target, service, embeddings, events = _batch_ingestion(tmp_path, 513)
    if cancellation == "operator":
        def cancel_on_batch():
            if len(embeddings.calls) == cancel_after:
                assert service.cancel("batch-cancel")
        embeddings.on_batch = cancel_on_batch

    job = service.ingest(
        target, workspace_id="w", collection_id="rag_phase0", tenant_id="default",
        job_id="batch-cancel",
        cancel_check=(lambda: len(embeddings.calls) >= cancel_after) if cancellation == "callback" else None,
    )

    assert job.status == "cancelled"
    assert len(embeddings.calls) == cancel_after
    assert service.knowledge.list_documents("w", tenant_id="default") == []
    assert service.knowledge.get_chunks(job.document_id) == []
    assert service.vectors.all_points() == []
    assert not any(event["type"] == "ingestion.completed" for event in events.events)


@pytest.mark.parametrize(
    "code, retryable",
    [("invalid_model", False), ("malformed_response", False),
     ("embedding_dimension_mismatch", False), ("invalid_configuration", False),
     ("unavailable", True), ("timeout", True)],
)
def test_embedding_batches_preserve_typed_provider_retryability(tmp_path, code, retryable):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "providers" / "src"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "contracts" / "src"))
    from rick_providers.errors import ProviderError

    fault = ProviderError(code, "embeddings", "batch-failure", 1)
    target, service, embeddings, events = _batch_ingestion(tmp_path, 513, fault)
    job = service.ingest(target, workspace_id="w", collection_id="rag_phase0", tenant_id="default")

    assert job.status == "failed"
    assert [len(batch) for batch in embeddings.calls] == [256, 256]
    assert is_retryable(job.error_code) is retryable
    assert events.events[-1]["retryable"] is retryable
    assert service.knowledge.list_documents("w", tenant_id="default") == []
    assert service.vectors.all_points() == []


@pytest.mark.parametrize("fault", [None, "raise", "short", "bool", "cancel"])
def test_vector_batches_preserve_order_and_compensate(tmp_path, fault):
    target, service, embeddings, events = _batch_ingestion(tmp_path, 257)

    class BoundedVectors(InMemoryVectorStore):
        def __init__(self):
            super().__init__()
            self.calls = []

        def upsert_points(self, points):
            self.calls.append(list(points))
            assert len(points) <= 256
            count = super().upsert_points(points)
            if len(self.calls) == 2:
                if fault == "raise":
                    raise RuntimeError("second batch failed after write")
                if fault == "short":
                    return 0
                if fault == "bool":
                    return True
            return count

    vectors = BoundedVectors()
    service.vectors = vectors
    job = service.ingest(
        target, workspace_id="w", collection_id="rag_phase0", tenant_id="default",
        cancel_check=lambda: fault == "cancel" and len(vectors.calls) == 1,
    )

    assert [len(batch) for batch in vectors.calls] == ([256] if fault == "cancel" else [256, 1])
    written = [point for batch in vectors.calls for point in batch]
    assert [point["payload"]["chunk_index"] for point in written] == list(range(len(written)))
    assert [point["vector"] for point in written] == [[float(index), 1.0] for index in range(len(written))]
    if fault is None:
        assert job.status == "published"
        assert len(vectors.all_points()) == 257
        assert events.events[-1]["points"] == 257
    else:
        assert job.status == ("cancelled" if fault == "cancel" else "failed")
        assert vectors.all_points() == []
        documents = service.knowledge.list_documents("w", tenant_id="default")
        assert len(documents) == 1
        assert documents[0].status == "failed"
        assert service.knowledge.get_chunks(documents[0].document_id) == []
        assert not any(event["type"] == "ingestion.completed" for event in events.events)


@pytest.mark.parametrize("max_points, max_bytes, count", [(256, 4 * 1024 * 1024, 257), (2, 4096, 5), (256, 3500, 5)])
@pytest.mark.parametrize("fault", [None, "status", "transport", "ack", "cancel"])
@pytest.mark.parametrize("hybrid", [False, True])
def test_qdrant_planned_ingestion_batches(tmp_path, max_points, max_bytes, count, fault, hybrid):
    import json
    import httpx
    from rick_retrieval.qdrant import QdrantHttpVectorStore, QdrantLimits

    target, service, embeddings, events = _batch_ingestion(tmp_path, count)
    if max_bytes > 4096:
        embeddings.dimensions = 1536
        embeddings.embed = lambda texts: [[(index + 1) / 1537 for index in range(1536)] for _ in texts]
    requests, upserts, stored = [], [], {}

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"result": {"config": {"params": {
                "vectors": {"dense": {"size": embeddings.dimensions, "distance": "Cosine"}},
                "sparse_vectors": {"sparse": {}} if hybrid else None,
            }}}})
        body = json.loads(request.content)
        if request.method == "PUT":
            upserts.append(request)
            for point in body["points"]:
                stored[point["id"]] = point
            if len(upserts) == 2:
                if fault == "status":
                    return httpx.Response(400, text="private failure")
                if fault == "transport":
                    raise RuntimeError("private transport failure")
                if fault == "ack":
                    return httpx.Response(200, json={"result": False})
            return httpx.Response(200, json={"result": {"status": "completed", "operation_id": 1}})
        if request.url.path.endswith("/count"):
            return httpx.Response(200, json={"result": {"count": len(stored)}})
        assert request.url.path.endswith("/delete")
        assert [entry["key"] for entry in body["filter"]["must"]] == [
            "tenant_id", "workspace_id", "collection_id", "document_id",
        ]
        stored.clear()
        return httpx.Response(200, json={"result": True})

    with QdrantHttpVectorStore(
        "http://qdrant.test", "rag_phase0", max_attempts=1,
        limits=QdrantLimits(max_points=max_points, max_request_bytes=max_bytes),
        transport=httpx.MockTransport(handler),
    ) as store:
        service.vectors = store
        job = service.ingest(
            target, workspace_id="w", collection_id="rag_phase0", tenant_id="default",
            cancel_check=lambda: fault == "cancel" and len(upserts) == 1,
        )
    if fault:
        assert len(upserts) == (1 if fault == "cancel" else 2)
    else:
        assert 1 < len(upserts) <= count
    assert all(len(request.content) <= max_bytes for request in upserts)
    assert all(0 < len(json.loads(request.content)["points"]) <= max_points for request in upserts)
    written = [point for request in upserts for point in json.loads(request.content)["points"]]
    assert all(("sparse" in point["vector"]) is hybrid for point in written)
    assert [point["payload"]["chunk_index"] for point in written] == list(range(len(written)))
    assert all(request.url.params["wait"] == "true" for request in upserts)
    assert "private" not in repr(job) + repr(events.events)
    if fault is None:
        assert job.status == "published"
        assert len(stored) == count
        assert events.events[-1]["points"] == count
    else:
        assert job.status == ("cancelled" if fault == "cancel" else "failed")
        assert stored == {}
        # Cancellation additionally confirms scoped cleanup before removing
        # its durable checkpoint from the recovery queue.
        assert len(requests) == len(upserts) + (3 if fault == "cancel" else 2)
        if fault == "cancel":
            assert requests[-1].url.path.endswith("/count")
            assert [entry["key"] for entry in json.loads(requests[-1].content)["filter"]["must"]] == [
                "tenant_id", "workspace_id", "collection_id", "document_id",
            ]
        assert service.knowledge.get_document(job.document_id).status == "failed"
        assert service.knowledge.get_chunks(job.document_id) == []
        assert not any(event["type"] == "ingestion.completed" for event in events.events)


class _PartialVectorStore(InMemoryVectorStore):
    """Fault-injection store: persist one point, then fail the batch."""

    def upsert_points(self, points):
        if points:
            super().upsert_points(points[:1])
        raise RuntimeError("simulated index failure")


def test_partial_index_failure_compensates_metadata_and_vectors(tmp_path):
    knowledge = InMemoryKnowledgeStore()
    vectors = _PartialVectorStore()
    service = IngestionService(
        knowledge=knowledge,
        vectors=vectors,
        embeddings=DeterministicHashEmbedding(),
    )
    target = _doc(tmp_path / "partial.txt", "conteudo que precisa falhar " * 80)

    job = service.ingest(target, workspace_id="w", collection_id="rag_phase0", tenant_id="default")

    assert job.status == "failed"
    assert vectors.all_points() == []
    assert job.document_id is not None
    failed_document = knowledge.get_document(job.document_id)
    assert failed_document is not None and failed_document.status == "failed"
    assert knowledge.get_chunks(job.document_id) == []


def test_document_write_that_raises_is_compensated(tmp_path):
    class WriteThenRaiseStore(InMemoryKnowledgeStore):
        def upsert_document(self, document):
            super().upsert_document(document)
            raise RuntimeError("adapter acknowledged then failed")

    knowledge = WriteThenRaiseStore()
    service = IngestionService(
        knowledge=knowledge,
        vectors=InMemoryVectorStore(),
        embeddings=DeterministicHashEmbedding(),
    )
    target = _doc(tmp_path / "write-then-raise.txt", "compensate this write " * 40)

    job = service.ingest(target, workspace_id="w", collection_id="rag_phase0", tenant_id="default")

    assert job.status == "failed"
    assert knowledge.get_document(job.document_id).status == "failed"
    assert knowledge.get_chunks(job.document_id) == []


def test_pdf_heartbeat_is_passed_to_parser(tmp_path, monkeypatch):
    captured = []

    class FakePdfParser:
        def __init__(self, heartbeat):
            self.heartbeat = heartbeat

        def parse(self, path, *, workspace_id):
            self.heartbeat(stage="parsing", pages_done=1, pages_total=1)
            return ParsedDocument(text="pdf content", pages=[ParsedPage(page_number=1, text="pdf content")])

    def fake_parser_for(path, *, pdf_heartbeat=None):
        captured.append(pdf_heartbeat)
        return FakePdfParser(pdf_heartbeat)

    monkeypatch.setattr("rick_ingestion.pipeline.parser_for", fake_parser_for)
    service = _service()
    target = tmp_path / "heartbeat.pdf"
    target.write_bytes(b"%PDF-fixture")

    job = service.ingest(target, workspace_id="w", collection_id="rag_phase0", tenant_id="default")

    assert job.status == "published"
    assert captured and captured[0] is not None
    assert any(heartbeat.get("pages_done") == 1 for heartbeat in job.heartbeats)


def test_job_state_machine_and_retry_split():
    with pytest.raises(TypeError):
        IngestionJob()
    job = IngestionJob(tenant_id="default", workspace_id="w", collection_id="rag_phase0")
    with pytest.raises(InvalidTransitionError):
        job.transition("published")
    job.transition("validating")
    job.transition("parsing")
    assert not is_retryable("validation_error")
    assert not is_retryable("unsupported_media_type")
    assert is_retryable("provider_timeout")
    assert is_retryable("vector_store_unavailable")
    assert not is_retryable("something-unknown")


def test_heartbeat_history_is_bounded_and_allowlisted():
    job = IngestionJob(tenant_id="default", workspace_id="w", collection_id="rag_phase0")
    for index in range(MAX_HEARTBEATS + 9):
        job.heartbeat(
            pages_done=index,
            pages_total=MAX_HEARTBEATS + 9,
            source_text="must never be retained",
            token="secret",
        )

    assert len(job.heartbeats) == MAX_HEARTBEATS
    assert job.heartbeats[0]["pages_done"] == 9
    assert job.heartbeats[-1]["pages_done"] == MAX_HEARTBEATS + 8
    assert all(set(item) <= {"at", "stage", "pages_done", "pages_total"} for item in job.heartbeats)
    assert all("source_text" not in item and "token" not in item for item in job.heartbeats)


def test_package_job_registry_is_bounded(tmp_path):
    service = IngestionService(
        knowledge=InMemoryKnowledgeStore(),
        vectors=InMemoryVectorStore(),
        embeddings=DeterministicHashEmbedding(),
        max_jobs=2,
    )
    jobs = []
    for index in range(5):
        target = tmp_path / f"job-{index}.txt"
        target.write_text("bounded job " * 20)
        jobs.append(service.ingest(target, workspace_id="w", collection_id="rag_phase0", tenant_id="default"))

    assert len(service._jobs) <= 2
    assert service.get_status(jobs[-1].job_id) is jobs[-1]


def test_cancel_and_status(tmp_path):
    service = _service()
    target = _doc(tmp_path / "a.txt", "hello " * 50)
    job = service.ingest(target, workspace_id="w", collection_id="rag_phase0", tenant_id="default")
    assert service.get_status(job.job_id).status == "published"
    assert service.cancel(job.job_id) is False  # terminal: cannot cancel
    assert service.cancel("missing") is False


def test_storage_safety():
    assert sanitize_display_filename("../../etc/passwd") == "passwd"
    assert sanitize_display_filename("a\x00b") == "ab"
    a, b = generated_storage_name(".pdf"), generated_storage_name(".pdf")
    assert a != b and a.endswith(".pdf") and "/" not in a
    with pytest.raises(Exception):
        validate_file(Path("/nonexistent/file.txt"))


def test_chunking_stability(tmp_path):
    strategy = RecursiveChunkingStrategy()
    text = ("Paragrafo um sobre mastite bovina e manejo de ordenha.\n\n" * 30)
    first = strategy.chunk(text=text, pages=[(1, text)], document_id="d")
    second = strategy.chunk(text=text, pages=[(1, text)], document_id="d")
    assert [c.text for c in first] == [c.text for c in second]
    assert all(c.checksum for c in first)
    assert len(first) > 1  # multi-chunk fixture actually chunks


def test_chunking_preserves_multi_page_span():
    strategy = RecursiveChunkingStrategy()
    page_one = "Pagina um com protocolo de higiene."
    page_two = "Pagina dois com a continuidade do protocolo."

    plans = strategy.chunk(
        text=f"{page_one}\n{page_two}",
        pages=[(1, page_one), (2, page_two)],
        document_id="multi-page",
        chunk_size=1200,
    )

    assert len(plans) == 1
    assert plans[0].page_start == 1
    assert plans[0].page_end == 2
