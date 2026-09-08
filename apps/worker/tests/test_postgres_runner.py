from __future__ import annotations

import threading
from types import SimpleNamespace
import time

from postgres_runner import PostgresIngestionWorker


def record():
    return SimpleNamespace(
        job_id="job-1",
        lease_token="worker:token",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        payload={"object_key": "uploads/job-1.md"},
    )


class Queue:
    lease_seconds = 0.3

    def __init__(self, records):
        self.records = list(records)
        self.calls: list[tuple[str, object]] = []

    def claim(self, *, worker_id, limit):
        self.calls.append(("claim", (worker_id, limit)))
        return tuple(self.records.pop(0) for _ in range(min(limit, len(self.records))))

    def mark_processing(self, job_id, *, lease_token):
        self.calls.append(("processing", (job_id, lease_token)))
        return self.records_by_id(job_id)

    def records_by_id(self, job_id):
        return record()

    def heartbeat(self, job_id, *, lease_token):
        self.calls.append(("heartbeat", (job_id, lease_token)))
        return record()

    def bind_document(self, job_id, document_id, *, lease_token):
        self.calls.append(("bind", (job_id, document_id, lease_token)))
        return record()

    def ack(self, job_id, *, lease_token):
        self.calls.append(("ack", (job_id, lease_token)))
        return record()

    def fail(self, job_id, *, lease_token, error):
        self.calls.append(("fail", (job_id, lease_token, error)))
        return record()

    def cancel(self, job_id, *, lease_token=None):
        self.calls.append(("cancel", (job_id, lease_token)))
        return record()


def test_worker_marks_processing_heartbeats_binds_document_and_acknowledges():
    queue = Queue([record()])

    def handler(_record, *, lease_lost_check):
        time.sleep(0.14)
        assert lease_lost_check() is False
        return {"document_id": "document-1"}

    worker = PostgresIngestionWorker(
        queue, handler, worker_id="worker-a", poll_interval_seconds=0.01,
    )
    result = worker.run_once()

    assert result.claimed == 1
    assert result.published == 1
    assert result.failed == 0
    names = [name for name, _ in queue.calls]
    assert names[0] == "claim"
    assert "processing" in names
    assert "heartbeat" in names
    assert names[-2:] == ["bind", "ack"]


def test_worker_fails_with_a_safe_code_and_does_not_retry_ack():
    queue = Queue([record()])

    def handler(_record):
        raise RuntimeError("provider secret should never cross the queue boundary")

    worker = PostgresIngestionWorker(queue, handler, worker_id="worker-a")
    result = worker.run_once()

    assert result.failed == 1
    assert result.published == 0
    assert [name for name, _ in queue.calls].count("ack") == 0
    fail = next(fields for name, fields in queue.calls if name == "fail")
    assert fail[-1] == "ingestion_failed"
    assert "secret" not in repr(fail)


def test_stopped_worker_cancels_claimed_record_with_its_lease():
    queue = Queue([record()])
    worker = PostgresIngestionWorker(queue, lambda _record: None, worker_id="worker-a")
    worker.stop()

    result = worker.run_once()

    assert result.claimed == 1
    assert result.cancelled == 1
    assert result.failed == 0
    assert ("cancel", ("job-1", "worker:token")) in queue.calls


def test_handler_timeout_fails_the_lease_without_blocking_the_worker():
    queue = Queue([record()])
    started = threading.Event()
    release = threading.Event()

    def handler(_record):
        started.set()
        release.wait(1)

    worker = PostgresIngestionWorker(
        queue, handler, worker_id="worker-a", handler_timeout_seconds=0.01,
    )
    started_at = time.monotonic()
    result = worker.run_once()
    elapsed = time.monotonic() - started_at
    release.set()

    assert result.failed == 1
    assert elapsed < 0.5
    assert ("fail", ("job-1", "worker:token", "provider_timeout")) in queue.calls
