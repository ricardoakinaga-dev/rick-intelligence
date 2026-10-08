# `apps/worker`

From the repository root, run `uv venv .venv --python python3.12`,
`uv pip sync --python .venv/bin/python --require-hashes requirements/test.lock`,
then `make worker-coverage PYTHON=.venv/bin/python`. CI installs the same
`requirements/test.lock` with pip's `--require-hashes`. The worker suite
must cover at least 74% of statements in `apps/worker/*.py`; `apps/worker/tests`
is excluded because test code is the measurement input. The health test runs
with the worker suite but is outside its coverage denominator. The sanitized
summary is `.runtime/qa/worker-summary.json`; the full local report stays in
`.runtime/qa/worker-coverage.json`.

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

`run_once()` reports outcomes for jobs started in that call. `run_forever()`
reports all outcomes observed during its invocation, including completions
from earlier nonwaiting cycles and its final monitor pass. It consumes
monotonic outcome counters once so delayed queue errors reach the configured
stop threshold even after completed executions have been reaped. Poisoned
claims validate returned canonical job identity, scope and recovery state
before counting their outcome; the poison marker is independent of that state.

Polling cycles serialize admission across capacity observation and claiming.
A running daemon owns polling until it returns: other cycle/daemon callers
receive `RuntimeConfigurationError`. Reentrant polling within a cycle is
also rejected. Cancellation, health and cooperative shutdown remain available
independently. Timeout detection is counted once regardless of the recovered
job state; claimed counts jobs, and invalid claims contribute to poison counts
in both cycle results and cumulative metrics. Callable mutation ports must
return canonical confirmations; missing/non-Job and PENDING confirmations
are queue errors. FAILED/RETRYING/QUEUED/DEAD_LETTER remain valid failed-attempt
results, and an absent optional cancellation capability retains its fallback.

Duplicate/currently active claim identities are invalid admissions and never
replace an existing execution. A failed thread launch rolls back its reserved
slot and does not count as started. Handler result readiness is separate from
thread termination: capacity remains reserved through tracing/context cleanup
until the worker thread exits, including after logical completion.

Exceptions after a confirmed thread launch preserve the admitted execution
instead of poisoning a live job. A supervisor interrupt still propagates after
counting that launch. Trace entry failures finish through the safe handler
failure boundary; trace exit/recording failures preserve an already obtained
handler result and never escape to the thread exception hook. Tracing cleanup
continues to occupy physical capacity until thread termination.

A reserved claim has one finalization owner even if thread launch fails while
a timeout or shutdown is finalizing it. Failed launches report started=0 and
poison detection without a second mutation. Threads confirmed after a pending
cancellation check the token before invoking the handler. Finalization stays
owned until its outcome and counters have been published atomically.
