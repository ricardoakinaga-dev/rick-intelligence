"""Process-local and local-durable worker seams.

The package is intentionally small. `LocalJobRunner` is in-process; the
SQLite queue is a restartable local primitive. Neither is a distributed
production worker service.
"""

from .durable_queue import (
    DurableQueueError,
    QueueCapacityError,
    QueueConfigurationError,
    QueueIdempotencyError,
    QueueLeaseError,
    QueueNotFoundError,
    QueueRecord,
    SQLiteDurableQueue,
)
from .postgres_queue import (
    PostgresDurableQueue,
    PostgresIngestionQueue,
    PostgresQueueCapacityError,
    PostgresQueueError,
    PostgresQueueIdempotencyError,
    PostgresQueueLeaseError,
    QueueHealth,
)
try:
    from .postgres_jobs import (
        PostgresCanonicalJobQueue,
        PostgresJobConcurrencyError,
        PostgresJobCorruptionError,
        PostgresJobError,
        PostgresJobIdempotencyError,
        PostgresJobLeaseError,
        PostgresJobNotFoundError,
        PostgresJobQueue,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - legacy worker path
    if exc.name != "rick_jobs":
        raise
    _CANONICAL_EXPORTS: list[str] = []
else:
    _CANONICAL_EXPORTS = [
        "PostgresCanonicalJobQueue", "PostgresJobQueue", "PostgresJobError",
        "PostgresJobConcurrencyError", "PostgresJobCorruptionError",
        "PostgresJobIdempotencyError", "PostgresJobLeaseError",
        "PostgresJobNotFoundError",
    ]
from .postgres_runner import PostgresIngestionWorker, WorkerBatchResult

from .runner import (
    COMPLETED,
    FAILED,
    PUBLISHED,
    QUEUED,
    RUNNING,
    CANCELLED,
    TERMINAL_STATES,
    JobContext,
    JobOutcome,
    JobRejected,
    JobSnapshot,
    LocalJobRunner,
    RunnerClosed,
)

__all__ = [
    "CANCELLED",
    "COMPLETED",
    "FAILED",
    "JobContext",
    "JobOutcome",
    "JobRejected",
    "JobSnapshot",
    "LocalJobRunner",
    "PUBLISHED",
    "QUEUED",
    "RUNNING",
    "RunnerClosed",
    "TERMINAL_STATES",
    "DurableQueueError",
    "QueueCapacityError",
    "QueueConfigurationError",
    "QueueIdempotencyError",
    "QueueLeaseError",
    "QueueNotFoundError",
    "QueueRecord",
    "SQLiteDurableQueue",
    "PostgresDurableQueue", "PostgresIngestionQueue", "PostgresQueueError",
    "PostgresQueueCapacityError", "PostgresQueueIdempotencyError",
    "PostgresQueueLeaseError", "QueueHealth",
    "PostgresIngestionWorker", "WorkerBatchResult",
] + _CANONICAL_EXPORTS
