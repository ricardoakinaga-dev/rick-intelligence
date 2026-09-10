# Durable worker queue boundary

`apps/worker/durable_queue.py` provides `SQLiteDurableQueue`, a bounded local
queue for the current migration slice. `max_pending` bounds active work and
`max_terminal_rows` bounds the retained terminal/idempotency window; rows
outside that window and their idempotency keys are intentionally forgotten.
It persists a small job envelope, not a document or provider response:

- idempotency key and generated job ID;
- tenant/workspace/collection scope;
- operation, document ID and private source key;
- bounded request/correlation/filename fields.

The state machine is `queued → leased → acked`, with failures returning to
`queued` until `max_attempts`, then `dead`; operators can `cancel` queued or
owned leased jobs. Lease claims return a capability token; renewals,
acknowledgements, retry transitions and expiry recovery use SQLite
transactions, and every mutation requires that exact token. Expired leases are requeued with
bounded exponential backoff or moved to the dead-letter state. Payloads reject
arbitrary fields and raw content.

Reads apply the same payload contract as writes: persisted JSON is capped at
32 KiB before parsing, non-finite constants and malformed/recursive values are
rejected, and only bounded string fields from the whitelist are returned. The
legacy SQLite and PostgreSQL queue adapters therefore do not turn corrupted
rows into arbitrary mappings; invalid stored payloads become an empty bounded
payload at the adapter boundary and remain subject to downstream required-field
validation.

The local file is WAL-backed and private (`0700` parent, `0600` database). A
reopened queue can recover a leased job after its lease expires. This proves a
restartable local primitive only. It is not a distributed queue, does not
provide multi-instance fencing, and is rejected when `RICK_ENV=production`.
Production still requires an external broker or reviewed database queue,
metrics/alerts, operator dead-letter tooling, and an integration drill.

The API's process-local recovery journal in
`apps/api/src/services/job_journal.py` applies the same read-side discipline:
persisted ACL and metadata JSON is capped at 32 KiB before and after decoding,
rejects non-finite, malformed or recursive values, and causes a corrupt row to
be omitted instead of being offered to restart recovery. Writes use the same
bounded canonical JSON contract. This protects the local recovery boundary; it
does not turn the journal into a production durable queue or provide
multi-instance recovery authority.

When the primary journal cannot retain a private source reference, the
ingestion facade writes a separate cleanup-lease marker under the private
staging root. That marker is canonical finite JSON capped at 8 KiB and its
version, job identity, scope and source path are validated before deletion;
oversized, malformed or non-finite markers are left untouched for operator
handling rather than authorizing a cleanup action. This is a local recovery
fallback, not external object-storage or distributed recovery evidence.

## Canonical PostgreSQL runtime

Phase 2.2 adds `apps/worker/postgres_jobs.py` as the canonical adapter for the
`rick_jobs` contract. Phase 2.3 adds `apps/worker/runtime.py` as the real worker
process boundary. A deployment supplies one explicit `JobScope`, a bounded
operation registry, a worker identity and the canonical queue; the runtime
validates the durable schema marker before claiming work, caps concurrency and
payload bytes, renews owner-bound leases, maps failures safely, and shuts down
under a finite deadline. The API uses
`apps/worker/canonical_queue.py` only as a tenant/workspace-scoped compatibility
facade.

The worker launcher calls startup before polling, exposes readiness/liveness,
and translates SIGINT/SIGTERM into cooperative stop plus bounded shutdown.
Migration `0005_rewrite_legacy_jobs.sql` rewrites legacy rows into canonical
attempt history, emits lifecycle/outbox/audit projections and rejects further
legacy writes. Upload objects use a checksum-derived key; after a successful
put, the request never deletes the object during a later queue failure because
a concurrent idempotent producer may already own the durable reference.
Unreferenced content is reclaimed by storage retention/GC. The local packet still needs disposable PostgreSQL, crash,
multi-worker, supervisor and hard handler-isolation evidence before production
promotion. A cooperative thread cannot safely kill arbitrary blocking Python
code; a deployment that needs that guarantee must add a process boundary.
