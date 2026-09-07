# `apps/worker`

This directory exposes two explicit worker seams. `LocalJobRunner` is a bounded
process-local seam for API integration. It has explicit `max_pending` and
`max_workers` limits, safe submission rejection, status/cancellation/shutdown
controls, terminal job snapshots, and no automatic retries.

`SQLiteDurableQueue` is a separate local-durability primitive with idempotency,
private WAL storage, exact capability-token leases, bounded retry/backoff and a
dead-letter state. Active jobs are bounded by `max_pending`; terminal rows are
kept in a separate bounded `max_terminal_rows` idempotency window, after which
their keys may be reused. Both seams accept an optional `event_sink` from
`packages/observability`: lifecycle events are emitted only after local state
changes, use opaque job/worker references, omit payload and scope fields, and
cannot fail the queue or runner. `run_next()`/`drain()` provide deterministic
hooks for the in-memory runner; the SQLite queue exposes explicit
enqueue/claim/heartbeat/ack/fail/recover operations.

The in-memory runner remains intentionally non-durable: jobs and status
disappear on process restart. The SQLite queue survives reopen but is still a
single-process/local file boundary and is rejected in production mode. These
two worker seams remain independent of the root ingestion executor; the root
API's actual `IngestionApplicationService` has its own bounded executor and is
wired to the API telemetry ring separately. An external broker or reviewed
database deployment is required for multi-instance production operation. The
local worker event streams are therefore bounded composition seams, not a
distributed telemetry guarantee.
