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

`PostgresJobQueue` is the canonical `rick_jobs` adapter. It uses the existing
`rick_ingestion_jobs` authority, the `0004` contract migration, scoped
idempotency, optimistic versions, owner-bound leases, `FOR UPDATE SKIP
LOCKED`, durable attempt history, lifecycle outbox/audit rows, dead-letter
replay, and bounded terminal retention. It receives a DB-API connection
factory from the composition root and never discovers credentials itself.

`RealWorkerRuntime` is the Phase 2.3 process runtime. A reviewed composition
injects one explicit `JobScope`, a bounded operation registry, concurrency and
deadline limits, and the canonical queue directly. Startup checks the durable
schema marker before claiming work; the launcher handles readiness, cooperative
SIGTERM cancellation, heartbeats, owner-bound cancellation, safe failure
mapping, and a finite shutdown deadline. `CanonicalIngestionQueueAdapter`
keeps the API's `QueueRecord` surface scoped to tenant/workspace while the
worker stays on canonical `Job`/`JobLease` values.

Migration `0005_rewrite_legacy_jobs.sql` materializes bounded attempt history,
records a replay-safe lifecycle/outbox/audit event, and installs a trigger that
rejects new legacy writes. The old `PostgresIngestionQueue` remains importable
for read compatibility during rollout, but it cannot remain a writable
authority after that migration. Disposable PostgreSQL concurrency, crash and
SIGTERM evidence is still required before this runtime is called production
ready. Python handlers remain cooperative; process isolation for a handler that
ignores cancellation is an external deployment gate.
