from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace

STORAGE_SRC = Path(__file__).resolve().parents[3] / "packages" / "storage" / "src"
if str(STORAGE_SRC) not in sys.path:
    sys.path.insert(0, str(STORAGE_SRC))

import pytest

from external_ingestion import ExternalIngestionError, ExternalIngestionHandler
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
        with kwargs["publication_guard"]():
            assert Path(source).read_bytes() == b"# Guide"
        return {"status": "published", "document_id": "document-1"}


def test_external_handler_hydrates_private_source_and_cleans_it(tmp_path):
    store = Store()
    ingestion = Ingestion()
    handler = ExternalIngestionHandler(
        ingestion, store, max_bytes=1024, temp_root=tmp_path, created_by="user-a",
    )

    result = handler(RECORD)

    assert result["document_id"] == "document-1"
    assert store.calls[0][0] == ObjectScope("tenant-a", "workspace-a", "job-1")
    assert ingestion.calls[0][1]["document_metadata"] == {
        "object_key": "uploads/job-1.md",
        "object_source_id": "job-1",
        "byte_size": 7,
        "created_by": "user-a",
    }
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
