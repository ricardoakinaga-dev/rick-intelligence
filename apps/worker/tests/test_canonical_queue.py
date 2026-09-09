from __future__ import annotations

from dataclasses import dataclass

import pytest

from canonical_queue import CanonicalIngestionQueueAdapter
from rick_jobs import Job, JobState


@dataclass
class FakeCanonicalQueue:
    max_attempts: int = 3

    def __post_init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.cancel_calls = 0

    def enqueue(self, job: Job, *, expected_version: int) -> Job:
        assert expected_version == 0
        existing = self.jobs.get(str(job.job_id))
        if existing is not None:
            return existing
        queued = job.transition(JobState.QUEUED, now=job.updated_at + 1.0)
        self.jobs[str(queued.job_id)] = queued
        return queued

    def get_for_workspace(self, job_id: str, *, tenant_id: str, workspace_id: str) -> Job | None:
        job = self.jobs.get(job_id)
        if job is None or (job.tenant_id, job.workspace_id) != (tenant_id, workspace_id):
            return None
        return job

    def get_by_idempotency(self, *, tenant_id: str, workspace_id: str, collection_id: str, idempotency_key: str) -> Job | None:
        return next(
            (
                job for job in self.jobs.values()
                if (job.tenant_id, job.workspace_id, job.collection_id, job.idempotency_key)
                == (tenant_id, workspace_id, collection_id, idempotency_key)
            ),
            None,
        )

    def list_for_workspace(self, *, tenant_id: str, workspace_id: str, limit: int = 100) -> tuple[Job, ...]:
        return tuple(
            job for job in self.jobs.values()
            if (job.tenant_id, job.workspace_id) == (tenant_id, workspace_id)
        )[:limit]

    def cancel(self, job_id, *, tenant_id, workspace_id, collection_id, now, expected_version):
        self.cancel_calls += 1
        current = self.jobs[job_id]
        cancelled = current.transition(JobState.CANCELLED, now=max(now, current.updated_at))
        self.jobs[job_id] = cancelled
        return cancelled

    def health_check(self) -> bool:
        return True


def test_adapter_translates_api_enqueue_and_scoped_reads() -> None:
    queue = CanonicalIngestionQueueAdapter(FakeCanonicalQueue(), clock=lambda: 100.0)
    record = queue.enqueue(
        job_id="job-1",
        idempotency_key="idem-1",
        payload={
            "operation": "ingest",
            "object_key": "uploads/job-1.txt",
            "display_filename": "job one.txt",
            "byte_size": "7",
        },
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        collection_id="collection-a",
    )

    assert record.status == "queued"
    assert record.payload["object_key"] == "uploads/job-1.txt"
    assert "filename_ref" in record.payload
    assert "display_filename" not in record.payload
    assert record.payload["byte_size"] == "7"
    assert queue.get("job-1", tenant_id="tenant-a", workspace_id="workspace-a") == record
    assert queue.list(tenant_id="tenant-a", workspace_id="workspace-a")[0] == record
    assert queue.cancel("job-1", tenant_id="tenant-a", workspace_id="workspace-a").status == "cancelled"


def test_adapter_rejects_unscoped_api_access() -> None:
    queue = CanonicalIngestionQueueAdapter(FakeCanonicalQueue(), clock=lambda: 100.0)
    with pytest.raises(Exception):
        queue.get("job-1")
    with pytest.raises(Exception):
        queue.list()
