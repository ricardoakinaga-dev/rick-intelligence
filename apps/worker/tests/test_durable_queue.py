from __future__ import annotations

from pathlib import Path

import pytest

from rick_observability import BoundedEventBuffer

from durable_queue import (
    QueueCapacityError,
    QueueIdempotencyError,
    QueueLeaseError,
    SQLiteDurableQueue,
)


def _enqueue(queue: SQLiteDurableQueue, job_id: str = "job-1"):
    return queue.enqueue(
        job_id=job_id,
        idempotency_key=f"idem-{job_id}",
        payload={"operation": "ingest", "document_id": f"doc-{job_id}", "source_key": f"source/{job_id}"},
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        collection_id="clinical",
        now=100.0,
    )


def test_idempotency_and_payload_boundary(tmp_path: Path) -> None:
    queue = SQLiteDurableQueue(tmp_path / "queue.sqlite", mode="test")
    first = _enqueue(queue)
    assert queue.enqueue(
        job_id="job-1",
        idempotency_key="idem-job-1",
        payload=dict(first.payload),
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        collection_id="clinical",
        now=101.0,
    ) == first
    with pytest.raises(QueueIdempotencyError):
        queue.enqueue(
            job_id="job-1-other",
            idempotency_key="idem-job-1",
            payload={"operation": "different"},
            tenant_id="tenant-a",
            workspace_id="workspace-a",
            collection_id="clinical",
            now=101.0,
        )
    with pytest.raises(Exception):
        queue.enqueue(
            job_id="job-2",
            idempotency_key="idem-job-2",
            payload={"raw_document": "must-not-be-queued"},
            tenant_id="tenant-a",
            workspace_id="workspace-a",
            collection_id="clinical",
        )


def test_claim_heartbeat_ack_and_wrong_owner(tmp_path: Path) -> None:
    queue = SQLiteDurableQueue(tmp_path / "queue.sqlite", mode="test", lease_seconds=10)
    _enqueue(queue)
    claimed = queue.claim(worker_id="worker-a", now=100.0)
    assert len(claimed) == 1 and claimed[0].status == "leased" and claimed[0].attempts == 1
    lease_token = claimed[0].lease_token
    assert lease_token
    with pytest.raises(QueueLeaseError):
        queue.ack("job-1", lease_token="worker-b:wrong", now=101.0)
    renewed = queue.heartbeat("job-1", lease_token=lease_token, now=105.0)
    assert renewed.lease_until == 115.0
    done = queue.ack("job-1", lease_token=lease_token, now=106.0)
    assert done.status == "acked"


def test_expired_lease_requeues_then_dead_letters_after_finite_attempts(tmp_path: Path) -> None:
    queue = SQLiteDurableQueue(tmp_path / "queue.sqlite", mode="test", max_attempts=2, backoff_seconds=0)
    _enqueue(queue)
    assert queue.claim(worker_id="worker-a", now=100.0)[0].attempts == 1
    assert queue.recover(now=131.0) == 1
    assert queue.claim(worker_id="worker-b", now=131.0)[0].attempts == 2
    assert queue.recover(now=162.0) == 1
    assert queue.get("job-1").status == "dead"  # type: ignore[union-attr]


def test_capacity_cancel_restart_and_private_scope_fields(tmp_path: Path) -> None:
    path = tmp_path / "queue.sqlite"
    queue = SQLiteDurableQueue(path, mode="test", max_pending=1)
    _enqueue(queue)
    with pytest.raises(QueueCapacityError):
        _enqueue(queue, "job-2")
    cancelled = queue.cancel("job-1", now=101.0)
    assert cancelled.status == "cancelled"
    queue.close()

    reopened = SQLiteDurableQueue(path, mode="test", max_pending=1)
    record = reopened.get("job-1")
    assert record is not None and record.payload["source_key"] == "source/job-1"
    assert record.tenant_id == "tenant-a"
    assert path.stat().st_mode & 0o077 == 0


def test_terminal_history_has_an_explicit_bounded_retention_window(tmp_path: Path) -> None:
    queue = SQLiteDurableQueue(
        tmp_path / "queue.sqlite",
        mode="test",
        max_pending=1,
        max_terminal_rows=1,
    )

    _enqueue(queue, "job-1")
    assert queue.cancel("job-1", now=101.0).status == "cancelled"
    _enqueue(queue, "job-2")
    assert queue.cancel("job-2", now=102.0).status == "cancelled"

    terminal = queue.list(statuses={"acked", "dead", "cancelled"}, limit=100)
    assert len(terminal) == 1
    assert terminal[0].job_id == "job-2"
    assert queue.get("job-1") is None


def test_idempotent_replay_prunes_expired_terminal_rows_before_returning(tmp_path: Path) -> None:
    queue = SQLiteDurableQueue(
        tmp_path / "queue.sqlite",
        mode="test",
        max_pending=4,
        max_terminal_rows=1,
        max_attempts=1,
        lease_seconds=1,
        backoff_seconds=0,
    )

    _enqueue(queue, "job-1")
    assert queue.cancel("job-1", now=100.0).status == "cancelled"
    _enqueue(queue, "job-2")
    assert queue.claim(worker_id="worker-a", now=100.0)[0].status == "leased"

    replay = queue.enqueue(
        job_id="job-1",
        idempotency_key="idem-job-1",
        payload={"operation": "ingest", "document_id": "doc-job-1", "source_key": "source/job-1"},
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        collection_id="clinical",
        now=102.0,
    )
    assert replay.status == "cancelled"
    terminals = queue.list(statuses={"acked", "dead", "cancelled"}, limit=10)
    assert len(terminals) == 1
    assert terminals[0].job_id == "job-1"


def test_queue_events_are_bounded_opaque_and_do_not_include_scope_or_payload(tmp_path: Path) -> None:
    sink = BoundedEventBuffer(max_events=16)
    queue = SQLiteDurableQueue(tmp_path / "queue.sqlite", mode="test", event_sink=sink, backoff_seconds=0)
    _enqueue(queue)
    claimed = queue.claim(worker_id="worker-a", now=100.0)
    assert claimed and claimed[0].lease_token
    queue.heartbeat("job-1", lease_token=claimed[0].lease_token, now=101.0)
    failed = queue.fail("job-1", lease_token=claimed[0].lease_token, error="provider_timeout", now=102.0)
    assert failed.status == "queued"
    claimed_again = queue.claim(worker_id="worker-a", now=102.0)
    assert claimed_again and claimed_again[0].lease_token
    queue.ack("job-1", lease_token=claimed_again[0].lease_token, now=103.0)

    events = sink.snapshot()
    names = [event["event"] for event in events]
    assert names == [
        "worker.queue.enqueued",
        "worker.queue.claimed",
        "worker.queue.heartbeat",
        "worker.queue.failed",
        "worker.queue.claimed",
        "worker.queue.acked",
    ]
    serialized = repr(events)
    assert "job-1" not in serialized
    assert "tenant-a" not in serialized
    assert "workspace-a" not in serialized
    assert "source/job-1" not in serialized
    assert all(set(event["fields"]) <= {"job_ref", "status", "attempts", "worker_ref", "error"} for event in events)


def test_queue_continues_when_event_sink_raises(tmp_path: Path) -> None:
    class BrokenSink:
        def emit(self, _event: object) -> None:
            raise RuntimeError("telemetry failure")

    queue = SQLiteDurableQueue(tmp_path / "queue.sqlite", mode="test", event_sink=BrokenSink())
    _enqueue(queue)
    claimed = queue.claim(worker_id="worker-a", now=100.0)
    assert claimed and claimed[0].lease_token
    assert queue.ack("job-1", lease_token=claimed[0].lease_token, now=101.0).status == "acked"
