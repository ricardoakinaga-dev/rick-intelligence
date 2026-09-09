from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import hashlib
import threading

import pytest

STORAGE_SRC = Path(__file__).resolve().parents[3] / "packages" / "storage" / "src"
if str(STORAGE_SRC) not in sys.path:
    sys.path.insert(0, str(STORAGE_SRC))

from rick_storage import ObjectMetadata, ObjectScope
from services.ingestion_service import IngestionApplicationError
from services.postgres_ingestion import PostgresIngestionApplicationService


def job(*, status="queued", tenant_id="tenant-a", workspace_id="workspace-a", collection_id="guides"):
    return SimpleNamespace(
        job_id="ing-job-1", status=status, tenant_id=tenant_id,
        workspace_id=workspace_id, collection_id=collection_id,
        attempts=1, created_at=100.0, last_error=None,
        payload={"object_key": "uploads/ing-job-1.md", "object_source_id": "ing-job-1"},
    )


class Queue:
    def __init__(self, record=None):
        self.record = record or job()
        self.enqueues = []
        self.cancel_calls = []

    def enqueue(self, **kwargs):
        self.enqueues.append(kwargs)
        self.record = SimpleNamespace(
            **{
                **vars(self.record),
                "job_id": kwargs["job_id"],
                "idempotency_key": kwargs["idempotency_key"],
                "tenant_id": kwargs["tenant_id"],
                "workspace_id": kwargs["workspace_id"],
                "collection_id": kwargs["collection_id"],
                "payload": kwargs["payload"],
            }
        )
        return self.record

    def get(self, job_id, *, tenant_id, workspace_id):
        if self.record.job_id != job_id or (self.record.tenant_id, self.record.workspace_id) != (tenant_id, workspace_id):
            return None
        return self.record

    def get_by_idempotency(self, *, tenant_id, workspace_id, collection_id, idempotency_key):
        if (
            getattr(self.record, "idempotency_key", None) == idempotency_key
            and self.record.tenant_id == tenant_id
            and self.record.workspace_id == workspace_id
            and self.record.collection_id == collection_id
        ):
            return self.record
        return None

    def cancel(self, job_id, *, tenant_id, workspace_id):
        self.cancel_calls.append((job_id, tenant_id, workspace_id))
        self.record = job(status="cancelled", tenant_id=tenant_id, workspace_id=workspace_id)
        return self.record


class Objects:
    def __init__(self):
        self.puts = []
        self.deletes = []

    def put(self, scope, key, data):
        self.puts.append((scope, key, data))
        checksum = hashlib.sha256(data).hexdigest()
        return ObjectMetadata(scope=scope, key=key, size=len(data), checksum=f"sha256:{checksum}")

    def delete(self, scope, key):
        self.deletes.append((scope, key))
        return True


def test_upload_is_scoped_and_idempotent_at_the_durable_boundary():
    queue = Queue()
    objects = Objects()
    service = PostgresIngestionApplicationService(queue=queue, object_store=objects, max_bytes=1024)

    result = service.submit_upload(
        b"# Guide", filename="Guide.md", collection_id="guides",
        workspace_id="workspace-a", tenant_id="tenant-a", idempotency_key="request-1",
    )

    assert result["status"] == "queued"
    assert result["job_id"].startswith("ing-")
    assert objects.puts[0][0] == ObjectScope("tenant-a", "workspace-a", result["job_id"])
    checksum = hashlib.sha256(b"# Guide").hexdigest()
    assert objects.puts[0][1] == f"uploads/{checksum}"
    assert queue.enqueues[0]["payload"]["object_source_id"] == result["job_id"]
    assert queue.enqueues[0]["payload"]["byte_size"] == "7"
    assert queue.enqueues[0]["payload"]["filename_ref"]
    assert "display_filename" not in queue.enqueues[0]["payload"]


def test_idempotent_replay_does_not_rewrite_content_addressed_object():
    queue = Queue()
    objects = Objects()
    service = PostgresIngestionApplicationService(queue=queue, object_store=objects, max_bytes=1024)

    first = service.submit_upload(
        b"# Guide", filename="Guide.md", collection_id="guides",
        workspace_id="workspace-a", tenant_id="tenant-a", idempotency_key="request-1",
    )
    second = service.submit_upload(
        b"# Guide", filename="Guide.md", collection_id="guides",
        workspace_id="workspace-a", tenant_id="tenant-a", idempotency_key="request-1",
    )

    assert second["job_id"] == first["job_id"]
    assert len(objects.puts) == 1
    assert len(queue.enqueues) == 1


def test_idempotency_conflict_is_rejected_before_object_write():
    queue = Queue()
    objects = Objects()
    service = PostgresIngestionApplicationService(queue=queue, object_store=objects, max_bytes=1024)

    service.submit_upload(
        b"# Guide", filename="Guide.md", collection_id="guides",
        workspace_id="workspace-a", tenant_id="tenant-a", idempotency_key="request-1",
    )
    with pytest.raises(IngestionApplicationError) as error:
        service.submit_upload(
            b"# Changed", filename="Guide.md", collection_id="guides",
            workspace_id="workspace-a", tenant_id="tenant-a", idempotency_key="request-1",
        )

    assert error.value.code == "conflict"
    assert len(objects.puts) == 1


def test_concurrent_idempotency_race_never_deletes_the_winner_object():
    class RacingQueue(Queue):
        def __init__(self):
            super().__init__()
            self.lookup_barrier = threading.Barrier(2)
            self.enqueue_lock = threading.Lock()

        def get_by_idempotency(self, **kwargs):
            self.lookup_barrier.wait(timeout=2)
            return None

        def enqueue(self, **kwargs):
            with self.enqueue_lock:
                if self.enqueues:
                    raise IngestionApplicationError("conflict")
                return super().enqueue(**kwargs)

    queue = RacingQueue()
    objects = Objects()
    service = PostgresIngestionApplicationService(queue=queue, object_store=objects, max_bytes=1024)

    def submit():
        return service.submit_upload(
            b"# Guide", filename="Guide.md", collection_id="guides",
            workspace_id="workspace-a", tenant_id="tenant-a", idempotency_key="request-1",
        )

    # Use explicit wrappers so the test records the exception from the
    # losing request without relying on a test-runner thread plugin.
    outcomes = []
    def invoke():
        try:
            outcomes.append(("ok", submit()))
        except IngestionApplicationError as error:
            outcomes.append(("error", error.code))

    threads = [threading.Thread(target=invoke) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert len(outcomes) == 2
    assert sorted(kind for kind, _ in outcomes) == ["error", "ok"]
    assert objects.deletes == []


def test_same_idempotency_key_in_different_collections_has_distinct_job_ids():
    queue = Queue()
    objects = Objects()
    service = PostgresIngestionApplicationService(queue=queue, object_store=objects, max_bytes=1024)

    first = service.submit_upload(
        b"# Guide", filename="Guide.md", collection_id="guides",
        workspace_id="workspace-a", tenant_id="tenant-a", idempotency_key="request-1",
    )
    second = service.submit_upload(
        b"# Guide", filename="Guide.md", collection_id="other",
        workspace_id="workspace-a", tenant_id="tenant-a", idempotency_key="request-1",
    )

    assert second["job_id"] != first["job_id"]


def test_leased_jobs_are_exposed_as_processing_and_cancel_keeps_scope():
    queue = Queue(job(status="leased"))
    service = PostgresIngestionApplicationService(queue=queue, object_store=Objects())

    status = service.get_status(
        "ing-job-1", tenant_id="tenant-a", workspace_id="workspace-a", allowed_collection_ids={"guides"},
    )
    cancelled = service.cancel(
        "ing-job-1", tenant_id="tenant-a", workspace_id="workspace-a", allowed_collection_ids={"guides"},
    )

    assert status["status"] == "processing"
    assert status["stage"] == "processing"
    assert queue.cancel_calls == [("ing-job-1", "tenant-a", "workspace-a")]
    assert cancelled["status"] == "cancelled"


def test_delete_removes_vectors_before_metadata_and_object_cleanup():
    order = []

    class Knowledge:
        def get_document(self, document_id, *, tenant_id, workspace_id):
            return {
                "document_id": document_id, "tenant_id": tenant_id,
                "workspace_id": workspace_id, "collection_id": "guides",
                "metadata": {"object_key": "uploads/doc.md", "object_source_id": "source-1"},
            }

        def delete_document(self, document_id, *, tenant_id, workspace_id):
            order.append("metadata")
            return 2

    class Vectors:
        def delete_document(self, document_id, collection_id, *, tenant_id, workspace_id):
            order.append("vectors")
            return 3

    objects = Objects()
    objects.delete = lambda scope, key: (order.append("object"), True)[1]
    service = PostgresIngestionApplicationService(
        queue=Queue(), object_store=objects, knowledge=Knowledge(), vectors=Vectors(),
    )

    result = service.delete_document(
        "doc-1", tenant_id="tenant-a", workspace_id="workspace-a", allowed_collection_ids={"guides"},
    )

    assert result["deleted_chunks"] == 2
    assert result["deleted_points"] == 3
    assert order == ["vectors", "metadata", "object"]
