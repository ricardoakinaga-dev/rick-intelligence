# RICK Jobs

`rick_jobs` is the adapter-neutral contract for durable execution in Phase 2.
It defines the job state machine, bounded serialized envelopes, attempts,
failures, results, owner-bound leases, and structural interfaces for queues,
repositories, executors and schedulers.

The package contains no database, Redis, broker, filesystem or vendor client.
It does not provide durability by itself. The SQLite queue remains a
development/test adapter. `apps/worker.PostgresJobQueue` is the reviewed
PostgreSQL implementation seam, but it remains a local implementation claim
until disposable PostgreSQL locking, migration, crash and replay gates pass.

## Contract

The canonical states are:

`PENDING → QUEUED → RUNNING → SUCCEEDED`

Failures may move through `FAILED → RETRYING → QUEUED` while attempts remain;
exhausted work moves to `DEAD_LETTER`. Cancellation is terminal. Every job has
explicit tenant/workspace/collection scope, an idempotency key, bounded
metadata, and an immutable attempt history.

Payloads contain references and control metadata only. Raw document text,
provider responses, bearer tokens, passwords, API keys and arbitrary secret-like
fields are rejected at the contract boundary.

## Migration rule

Adapters may translate their existing storage vocabulary (`queued`, `leased`,
`acked`, `dead`) into this contract, but they must preserve owner checks,
idempotency, retry counts, failure codes and scope. A local adapter cannot claim
distributed durability or production readiness merely because it satisfies the
Python protocols.
