from __future__ import annotations

import pytest

from postgres_queue import (
    PostgresIngestionQueue,
    PostgresQueueIdempotencyError,
    PostgresQueueLeaseError,
)


def job_row(*, status="queued", lease_owner=None, attempts=0):
    return {
        "job_id": "job-1",
        "idempotency_key": "upload-1",
        "status": status,
        "payload": {"filename": "guide.md"},
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "collection_id": "guides",
        "attempts": attempts,
        "available_at": 100.0,
        "lease_until": 130.0 if lease_owner else None,
        "lease_owner": lease_owner,
        "created_at": 100.0,
        "updated_at": 100.0,
        "last_error_code": None,
    }


def test_database_payload_decoder_rejects_unbounded_and_nonfinite_json():
    oversized = '{"filename":"' + ("a" * (32 * 1024)) + '"}'

    assert PostgresIngestionQueue._decode({**job_row(), "payload": oversized}).payload == {}
    assert PostgresIngestionQueue._decode({**job_row(), "payload": '{"filename":NaN}'}).payload == {}
    assert PostgresIngestionQueue._decode({**job_row(), "payload": '{"filename":"first","filename":"second"}'}).payload == {}


class ScriptedCursor:
    def __init__(self, steps):
        self.steps = list(steps)
        self.queries = []
        self.rowcount = 0
        self._rows = []
        self.description = None

    def execute(self, query, params=()):
        self.queries.append((query, params))
        if not self.steps:
            raise AssertionError(f"unexpected query: {query}")
        expected, rows, rowcount = self.steps.pop(0)
        if expected not in query:
            raise AssertionError(f"expected {expected!r}, got {query!r}")
        self._rows = list(rows)
        self.rowcount = rowcount

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def close(self):
        return None


class ScriptedConnection:
    def __init__(self, steps):
        self.cursor_instance = ScriptedCursor(steps)
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def factory_for(*connections):
    remaining = list(connections)

    def factory():
        if not remaining:
            raise AssertionError("connection factory was called more often than scripted")
        return remaining.pop(0)

    return factory


def test_enqueue_is_idempotent_and_keeps_payload_opaque():
    first = ScriptedConnection([
        ("SELECT pg_advisory_xact_lock", [], 0),
        ("SELECT * FROM rick_ingestion_jobs", [], 0),
        ("SELECT COUNT(*)", [{"count": 0}], 0),
        ("INSERT INTO rick_ingestion_jobs", [job_row()], 1),
    ])
    replay = ScriptedConnection([
        ("SELECT pg_advisory_xact_lock", [], 0),
        ("SELECT * FROM rick_ingestion_jobs", [job_row()], 1),
    ])
    queue = PostgresIngestionQueue(factory_for(first, replay))

    created = queue.enqueue(
        job_id="job-1", idempotency_key="upload-1", payload={"filename": "guide.md"},
        tenant_id="tenant-a", workspace_id="workspace-a", collection_id="guides",
    )
    repeated = queue.enqueue(
        job_id="job-1", idempotency_key="upload-1", payload={"filename": "guide.md"},
        tenant_id="tenant-a", workspace_id="workspace-a", collection_id="guides",
    )

    assert created == repeated
    assert first.commits == 1 and replay.commits == 1
    assert "guide.md" not in first.cursor_instance.queries[2][0]
    assert all("contract_state IS NULL" in query for query, _params in first.cursor_instance.queries[1:3])


def test_claim_requires_owner_for_heartbeat_and_ack():
    claimed_row = job_row(status="leased", lease_owner="worker-a:token", attempts=1)
    claim = ScriptedConnection([
        ("UPDATE rick_ingestion_jobs", [], 0),
        ("FOR UPDATE SKIP LOCKED", [{"job_id": "job-1"}], 0),
        ("SET status='leased'", [claimed_row], 1),
    ])
    heartbeat = ScriptedConnection([
        ("SET lease_until", [claimed_row], 1),
    ])
    ack = ScriptedConnection([
        ("SET status=%s", [{**claimed_row, "status": "published", "lease_owner": None}], 1),
    ])
    queue = PostgresIngestionQueue(factory_for(claim, heartbeat, ack))

    leased = queue.claim(worker_id="worker-a")[0]
    renewed = queue.heartbeat(leased.job_id, lease_token=leased.lease_token or "")
    published = queue.ack(leased.job_id, lease_token=renewed.lease_token or "worker-a:token")

    assert leased.status == "leased"
    assert renewed.status == "leased"
    assert published.status == "published"
    assert published.terminal
    assert "FOR UPDATE SKIP LOCKED" in claim.cursor_instance.queries[1][0]
    assert all("contract_state IS NULL" in query for query, _params in claim.cursor_instance.queries)


def test_wrong_lease_rolls_back_and_does_not_ack():
    connection = ScriptedConnection([
        ("SET status=%s", [], 0),
    ])
    queue = PostgresIngestionQueue(factory_for(connection))

    with pytest.raises(PostgresQueueLeaseError):
        queue.ack("job-1", lease_token="wrong-owner")

    assert connection.rollbacks == 1


def test_idempotency_conflict_is_explicit():
    connection = ScriptedConnection([
        ("SELECT pg_advisory_xact_lock", [], 0),
        ("SELECT * FROM rick_ingestion_jobs", [job_row()], 1),
    ])
    queue = PostgresIngestionQueue(factory_for(connection))

    with pytest.raises(PostgresQueueIdempotencyError):
        queue.enqueue(
            job_id="different-job", idempotency_key="upload-1", payload={"filename": "guide.md"},
            tenant_id="tenant-a", workspace_id="workspace-a", collection_id="guides",
        )

    assert connection.rollbacks == 1
