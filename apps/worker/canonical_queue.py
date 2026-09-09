"""Legacy-shaped API facade backed by the canonical :mod:`rick_jobs` queue.

The API still returns the small ``QueueRecord`` shape used by its route
boundary. This facade translates that shape to and from the canonical job
contract while keeping all reads and mutations tenant/workspace scoped. The
worker itself receives the canonical queue directly.
"""

from __future__ import annotations

from base64 import urlsafe_b64encode
from collections.abc import Mapping
from time import time

from rick_jobs import Job, JobState

try:
    from .durable_queue import QueueRecord
    from .postgres_jobs import (
        PostgresJobConcurrencyError,
        PostgresJobError,
        PostgresJobLeaseError,
    )
except ImportError:  # flattened worker image
    from durable_queue import QueueRecord
    from postgres_jobs import PostgresJobConcurrencyError, PostgresJobError, PostgresJobLeaseError


_STATUS = {
    JobState.PENDING: "queued",
    JobState.QUEUED: "queued",
    JobState.RETRYING: "queued",
    JobState.RUNNING: "processing",
    JobState.SUCCEEDED: "published",
    JobState.FAILED: "failed",
    JobState.CANCELLED: "cancelled",
    JobState.DEAD_LETTER: "dead",
}


class CanonicalIngestionQueueAdapter:
    """Expose the API's bounded queue surface over ``PostgresJobQueue``."""

    def __init__(self, queue: object, *, clock=time) -> None:
        if queue is None or not callable(getattr(queue, "enqueue", None)):
            raise ValueError("canonical queue is required")
        if not callable(getattr(queue, "get_for_workspace", None)):
            raise ValueError("canonical queue must expose scoped workspace reads")
        if not callable(getattr(queue, "get_by_idempotency", None)):
            raise ValueError("canonical queue must expose scoped idempotency reads")
        if not callable(getattr(queue, "list_for_workspace", None)):
            raise ValueError("canonical queue must expose scoped workspace lists")
        if not callable(clock):
            raise ValueError("clock is required")
        self.queue = queue
        self._clock = clock
        self.max_pending = getattr(queue, "max_pending", 256)

    @staticmethod
    def _record(job: Job) -> QueueRecord:
        failure = job.failure.code if job.failure is not None else None
        document_id = job.result.document_id if job.result is not None else None
        return QueueRecord(
            job_id=str(job.job_id),
            idempotency_key=job.idempotency_key,
            status=_STATUS[job.state],
            payload=dict(job.payload),
            tenant_id=job.tenant_id,
            workspace_id=job.workspace_id,
            collection_id=job.collection_id,
            attempts=job.attempt_count,
            available_at=job.available_at,
            lease_until=None,
            lease_token=None,
            created_at=job.created_at,
            updated_at=job.updated_at,
            last_error=failure,
            document_id=document_id,
        )

    def health_check(self) -> bool:
        checker = getattr(self.queue, "health_check", None)
        try:
            return bool(checker()) if callable(checker) else False
        except Exception:
            return False

    def readiness_check(self) -> bool:
        checker = getattr(self.queue, "readiness_check", None)
        if not callable(checker):
            return False
        try:
            return bool(checker())
        except Exception:
            return False

    def enqueue(
        self,
        *,
        job_id: str,
        idempotency_key: str,
        payload: Mapping[str, str],
        tenant_id: str,
        workspace_id: str,
        collection_id: str,
    ) -> QueueRecord:
        if not isinstance(payload, Mapping) or not payload:
            raise PostgresJobError("invalid_input", "payload is invalid")
        clean_payload: dict[str, str] = {}
        for raw_key, raw_value in payload.items():
            key = str(raw_key)
            value = str(raw_value)
            if key == "display_filename":
                if "filename_ref" in payload:
                    raise PostgresJobError("invalid_input", "filename references conflict")
                encoded = urlsafe_b64encode(value.encode("utf-8")).decode("ascii")
                if not encoded or len(encoded) > 512:
                    raise PostgresJobError("invalid_input", "display filename is out of range")
                clean_payload["filename_ref"] = encoded
            elif key == "document_id" and not value:
                continue
            else:
                clean_payload[key] = value
        job = Job.create(
            job_id=job_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            collection_id=collection_id,
            operation=str(payload.get("operation") or "ingest"),
            idempotency_key=idempotency_key,
            payload=clean_payload,
            now=float(self._clock()),
            max_attempts=getattr(self.queue, "max_attempts", 3),
        )
        queued = self.queue.enqueue(job, expected_version=0)
        return self._record(queued)

    def get(
        self,
        job_id: str,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> QueueRecord | None:
        if (tenant_id is None) != (workspace_id is None):
            raise PostgresJobError("invalid_input", "tenant/workspace scope is incomplete")
        if tenant_id is None or workspace_id is None:
            raise PostgresJobError("invalid_input", "scoped job reads are required")
        job = self.queue.get_for_workspace(job_id, tenant_id=tenant_id, workspace_id=workspace_id)
        return None if job is None else self._record(job)

    def get_by_idempotency(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        collection_id: str,
        idempotency_key: str,
    ) -> QueueRecord | None:
        job = self.queue.get_by_idempotency(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            collection_id=collection_id,
            idempotency_key=idempotency_key,
        )
        return None if job is None else self._record(job)

    def list(
        self,
        *,
        limit: int = 100,
        statuses: set[str] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> tuple[QueueRecord, ...]:
        if tenant_id is None or workspace_id is None or (tenant_id is None) != (workspace_id is None):
            raise PostgresJobError("invalid_input", "scoped job lists are required")
        records = tuple(
            self._record(job)
            for job in self.queue.list_for_workspace(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                limit=limit,
            )
        )
        if statuses is None:
            return records
        return tuple(record for record in records if record.status in statuses)

    def cancel(
        self,
        job_id: str,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> QueueRecord:
        current = self.get(job_id, tenant_id=tenant_id, workspace_id=workspace_id)
        if current is None:
            raise PostgresJobError("not_found")
        if current.status in {"published", "failed", "cancelled", "dead"}:
            return current
        job = self.queue.get_for_workspace(job_id, tenant_id=tenant_id, workspace_id=workspace_id)
        if job is None:
            raise PostgresJobError("not_found")
        try:
            cancelled = self.queue.cancel(
                job.job_id,
                tenant_id=job.tenant_id,
                workspace_id=job.workspace_id,
                collection_id=job.collection_id,
                now=float(self._clock()),
                expected_version=job.version,
            )
        except (PostgresJobConcurrencyError, PostgresJobLeaseError):
            # Running work requires owner-bound cancellation. Preserve the
            # current scoped snapshot instead of turning a race into a 500.
            return current
        return self._record(cancelled)

    def close(self) -> None:
        close = getattr(self.queue, "close", None)
        if callable(close):
            close()

    shutdown = close


__all__ = ["CanonicalIngestionQueueAdapter"]
