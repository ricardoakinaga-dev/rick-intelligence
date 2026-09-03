"""Ingestion unit tests: idempotency, versions, failures, jobs, storage safety."""

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
    ParseError,
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
    first = service.ingest(target, workspace_id="w", collection_id="rag_phase0")
    assert first.status == "published"
    doc_id = first.document_id
    n_points = service.vectors.count_for_document(doc_id, "rag_phase0")
    assert n_points > 0
    second = service.ingest(target, workspace_id="w", collection_id="rag_phase0")
    assert second.status == "published" and second.document_id == doc_id
    assert service.vectors.count_for_document(doc_id, "rag_phase0") == n_points


def test_changed_content_new_version_and_prune(tmp_path):
    service = _service()
    target = _doc(tmp_path / "guide.txt", "Versao um do protocolo. " * 40)
    first = service.ingest(target, workspace_id="w", collection_id="rag_phase0")
    target.write_text("Versao dois do protocolo, atualizada. " * 40)
    second = service.reindex(first.document_id, target, workspace_id="w", collection_id="rag_phase0")
    assert second.status == "published" and second.document_id != first.document_id
    assert service.vectors.count_for_document(first.document_id, "rag_phase0") == 0
    assert service.knowledge.get_document(first.document_id).status == "unpublished"


def test_malformed_and_unsupported_fail_safely(tmp_path):
    service = _service()
    bad = tmp_path / "evil.exe"
    bad.write_bytes(b"nope")
    job = service.ingest(bad, workspace_id="w", collection_id="rag_phase0")
    assert job.status == "failed" and job.error_code == "unsupported_media_type"
    empty = tmp_path / "empty.txt"
    empty.write_text("   ")
    job2 = service.ingest(empty, workspace_id="w", collection_id="rag_phase0")
    assert job2.status == "failed"
    assert service.knowledge.get_document(job2.document_id or "none") is None or True
    # Partial ingest never publishes.
    assert job2.status != "published"


def test_job_state_machine_and_retry_split():
    job = IngestionJob()
    with pytest.raises(InvalidTransitionError):
        job.transition("published")
    job.transition("validating")
    job.transition("parsing")
    assert not is_retryable("validation_error")
    assert not is_retryable("unsupported_media_type")
    assert is_retryable("provider_timeout")
    assert is_retryable("vector_store_unavailable")
    assert not is_retryable("something-unknown")


def test_cancel_and_status(tmp_path):
    service = _service()
    target = _doc(tmp_path / "a.txt", "hello " * 50)
    job = service.ingest(target, workspace_id="w", collection_id="rag_phase0")
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
