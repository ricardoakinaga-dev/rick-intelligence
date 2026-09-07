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


def test_failed_reindex_to_existing_target_preserves_both_documents(tmp_path):
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
    assert failed.status == "failed"
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


def test_reindex_retirement_failure_rolls_back_new_version_and_restores_old_index(tmp_path):
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

    assert failed.status == "failed"
    assert failed.error_code == "storage_unavailable"
    assert knowledge.get_document(first.document_id).status == "published"
    assert base_vectors.count_for_document(first.document_id, "rag_phase0") == old_count
    assert knowledge.get_document(failed.document_id).status == "failed"
    assert base_vectors.count_for_document(failed.document_id, "rag_phase0") == 0


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
    assert failed.status == "failed"
    assert service.knowledge.get_document(first.document_id).status == "unpublished"
    assert service.knowledge.get_document(failed.document_id).status == "failed"
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
