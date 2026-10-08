from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
import sys
from types import SimpleNamespace

STORAGE_SRC = Path(__file__).resolve().parents[3] / "packages" / "storage" / "src"
if str(STORAGE_SRC) not in sys.path:
    sys.path.insert(0, str(STORAGE_SRC))
INGESTION_SRC = Path(__file__).resolve().parents[3] / "packages" / "ingestion" / "src"
if str(INGESTION_SRC) not in sys.path:
    sys.path.insert(0, str(INGESTION_SRC))

import pytest

from external_ingestion import ExternalIngestionError, ExternalIngestionHandler
from rick_ingestion import validate_file
from rick_storage import ObjectScope


RECORD = SimpleNamespace(
    job_id="job-1",
    tenant_id="tenant-a",
    workspace_id="workspace-a",
    collection_id="guides",
    payload={
        "object_key": "uploads/job-1.md",
        "object_source_id": "job-1",
        "display_filename": "guide.md",
        "operation": "ingest",
        "checksum": f"sha256:{hashlib.sha256(b'# Guide').hexdigest()}",
    },
)


class Store:
    def __init__(self, data=b"# Guide"):
        self.data = data
        self.calls = []

    def get(self, scope, key, *, max_bytes):
        self.calls.append((scope, key, max_bytes))
        return self.data


class Ingestion:
    def __init__(self):
        self.calls = []

    def ingest(self, source, **kwargs):
        self.calls.append((Path(source), kwargs))
        assert os.stat(source).st_mode & 0o777 == 0o600
        validate_file(Path(source), max_bytes=1024)
        with kwargs["publication_guard"]():
            assert Path(source).read_bytes() == b"# Guide"
        return {"status": "published", "document_id": "document-1"}


    def reindex(self, document_id, source, **kwargs):
        assert document_id == "document-1"
        return self.ingest(source, **kwargs)


@pytest.mark.parametrize("operation", ["ingest", "reindex"])
def test_external_handler_hydrates_private_source_and_cleans_it(tmp_path, operation):
    store = Store()
    ingestion = Ingestion()
    handler = ExternalIngestionHandler(
        ingestion, store, max_bytes=1024, temp_root=tmp_path, created_by="user-a",
    )

    record = SimpleNamespace(**{
        **vars(RECORD),
        "payload": {**RECORD.payload, "operation": operation, "document_id": "document-1"},
    })
    result = handler(record)

    assert result["document_id"] == "document-1"
    assert store.calls[0][0] == ObjectScope("tenant-a", "workspace-a", "job-1")
    assert ingestion.calls[0][1]["document_metadata"] == {
        "object_key": "uploads/job-1.md",
        "object_source_id": "job-1",
        "byte_size": 7,
        "created_by": "user-a",
    }
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("operation", ["ingest", "reindex"])
def test_external_handler_rejects_corrupted_bytes_before_parsing(tmp_path, operation):
    store = Store(b"# Guidf")
    ingestion = Ingestion()
    record = SimpleNamespace(**{
        **vars(RECORD),
        "payload": {**RECORD.payload, "operation": operation, "document_id": "document-1"},
    })
    handler = ExternalIngestionHandler(ingestion, store, temp_root=tmp_path)

    with pytest.raises(ExternalIngestionError) as error:
        handler(record)

    assert error.value.code == "validation_error"
    assert ingestion.calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("checksum", [None, "", "sha256:abc", "md5:" + "a" * 32, 123])
def test_external_handler_rejects_absent_or_invalid_checksum_before_read(tmp_path, checksum):
    store = Store()
    ingestion = Ingestion()
    payload = dict(RECORD.payload)
    if checksum is None:
        payload.pop("checksum")
    else:
        payload["checksum"] = checksum
    record = SimpleNamespace(**{**vars(RECORD), "payload": payload})
    handler = ExternalIngestionHandler(ingestion, store, temp_root=tmp_path)

    with pytest.raises(ExternalIngestionError) as error:
        handler(record)

    assert error.value.code == "validation_error"
    assert store.calls == []
    assert ingestion.calls == []
    assert list(tmp_path.iterdir()) == []


def test_external_handler_stops_publication_when_the_lease_is_lost(tmp_path):
    store = Store()

    class LeaseAwareIngestion:
        def ingest(self, source, **kwargs):
            with kwargs["publication_guard"]():
                raise AssertionError("publication must not start after lease loss")

    handler = ExternalIngestionHandler(LeaseAwareIngestion(), store, temp_root=tmp_path)

    with pytest.raises(ExternalIngestionError) as error:
        handler(RECORD, lease_lost_check=lambda: True)

    assert error.value.code == "lock_unavailable"
    assert list(tmp_path.iterdir()) == []


def test_external_handler_propagates_lease_cancellation_to_pipeline(tmp_path):
    store = Store()
    observed = {}

    class CancellationAwareIngestion:
        def ingest(self, source, **kwargs):
            observed["cancel_check"] = kwargs.get("cancel_check")
            return SimpleNamespace(status="published", document_id="document-1")

    cancelled = lambda: False
    handler = ExternalIngestionHandler(CancellationAwareIngestion(), store, temp_root=tmp_path)

    handler(RECORD, lease_lost_check=cancelled)

    assert observed["cancel_check"] is cancelled


def test_external_handler_decodes_bounded_filename_reference(tmp_path):
    store = Store()
    ingestion = Ingestion()
    record = SimpleNamespace(
        job_id="job-2",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        collection_id="guides",
        payload={
            "object_key": "uploads/job-2.md",
            "object_source_id": "job-2",
            "filename_ref": base64.urlsafe_b64encode("guide notes.md".encode()).decode(),
            "operation": "ingest",
            "checksum": RECORD.payload["checksum"],
        },
    )
    handler = ExternalIngestionHandler(ingestion, store, temp_root=tmp_path)

    handler(record)

    assert ingestion.calls[0][1]["display_filename"] == "guide notes.md"


@pytest.mark.parametrize("lost_at", [1, 2, 3])
def test_canonical_pipeline_lease_entry_commit_and_exit_are_consistent(tmp_path, lost_at):
    from external_ingestion import _LeaseGuard
    from rick_ingestion import IngestionService
    from rick_knowledge import InMemoryKnowledgeStore
    from rick_retrieval import DeterministicHashEmbedding, InMemoryVectorStore
    knowledge, vectors = InMemoryKnowledgeStore(), InMemoryVectorStore()
    ingestion = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=DeterministicHashEmbedding())
    path = tmp_path / "lease.md"
    path.write_text("Publication with lease authority. " * 60)
    checks = []
    def lost():
        checks.append(len(checks) + 1)
        return len(checks) >= lost_at
    result = ingestion.ingest(path, tenant_id="t", workspace_id="w", collection_id="c", publication_guard=lambda: _LeaseGuard(lost))
    document = knowledge.get_document(result.document_id)
    if lost_at < 3:
        assert result.status == document.status == "failed"
        assert result.error_code == "lock_unavailable"
        assert vectors.all_points() == [] and knowledge.get_chunks(result.document_id) == []
    else:
        assert result.status == document.status == "published"
        assert result.metadata["publication_guard_error_after_commit"] is True
        assert vectors.count_for_document(result.document_id, "c") == len(knowledge.get_chunks(result.document_id)) > 0
