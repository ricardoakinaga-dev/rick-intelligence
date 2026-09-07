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
]
