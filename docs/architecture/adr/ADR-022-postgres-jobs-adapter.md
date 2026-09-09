# ADR-022: Canonical PostgreSQL jobs adapter

Status: Accepted for Phase 2.2 local implementation; production gate pending

## Context

Phase 2.1 froze `rick_jobs` as the adapter-neutral boundary for durable
execution. The repository already had `rick_ingestion_jobs` and a legacy
`PostgresIngestionQueue`, but its lowercase status vocabulary, tenant-wide
idempotency key, scalar attempt count and owner predicates did not satisfy the
canonical scope, version, attempt and lease contracts. A second queue table
would create competing authorities.

## Decision

Keep `rick_ingestion_jobs` as the single durable queue authority. Migration
`0004_durable_jobs_contract.sql` adds the canonical state projection, contract
version, bounded retry policy, optimistic version, structured result/failure,
lease worker fields, composite document scope, durable attempt history and a
transactional lifecycle event table. State mutations write the job row,
attempt history, lifecycle event, outbox entry and audit projection in one
database transaction. Lease heartbeats and retention actions write a lifecycle
event plus the same outbox/audit projections; retention records them before
the job aggregate is deleted.

The empty `rick_ingestion_job_control` table from migration 0001 is renamed to
an explicit legacy archive. If it contains rows, migration 0004 fails closed
and requires operator reconciliation before the rename, so historical work is
never silently discarded or split between two authorities.

`apps/worker/postgres_jobs.py` exposes `PostgresJobQueue`, which implements
`JobRepository`, `JobQueue` and `JobScheduler`. Claims select the full scope
with `FOR UPDATE SKIP LOCKED`; every mutation carries the full scope and
expected version; completion and failure require the current worker and lease
token; expired leases are fenced before recovery. Retry exhaustion produces a
`DEAD_LETTER` row. Replay creates a new scoped envelope and leaves the
original failure history immutable. Terminal retention is an explicit bounded
operation rather than an implicit delete.

The connection factory is injected. The adapter does not read DSNs, create
drivers, or fall back to SQLite. The legacy queue remains available to callers
that have not crossed the Phase 2.3 worker migration boundary.

Rows already present at migration time and rows later created by that
compatibility facade intentionally leave `contract_state` NULL. The canonical
adapter reconstructs a read-only contract view for those rows, excludes them
from canonical claims, rejects canonical mutations until the rewrite, and the
legacy facade filters out canonical rows. This keeps the old writer compatible
while making the Phase 2.3 rewrite boundary explicit.

Attempt history is append-only at both seams: the adapter rejects finished
history changes and migration 0004 installs PostgreSQL immutability/delete
guards plus deferred count and contiguity checks for canonical rows. Lease
expiry and heartbeat comparisons use PostgreSQL `clock_timestamp()` so a
worker cannot extend or reclaim a lease with a caller-controlled clock.

## Consequences

The adapter can be tested independently of the canonical contracts and keeps
the migration boundary auditable. CAS versions and lease predicates prevent a
stale worker from publishing after recovery. The complete idempotency scope
allows the same client key in separate collections without cross-tenant
replay. Lifecycle events provide a durable audit/outbox seam without putting
raw payloads or provider responses into events.

The local scripted suite cannot prove PostgreSQL row-lock behavior, transaction
durability, FK enforcement, query plans or two-worker claim races. The
Phase 2.2 disposable PostgreSQL gate therefore remains `BLOCKED_EXTERNAL`
until the environment provides a PostgreSQL driver/container and records the
required migration, concurrency, crash and replay evidence.
