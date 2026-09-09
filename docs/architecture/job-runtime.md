# Durable job runtime

The canonical job contract is in `packages/jobs` and the PostgreSQL adapter is
in `apps/worker/postgres_jobs.py`. The lifecycle is:

```text
PENDING → QUEUED → RUNNING → SUCCEEDED
                    ├──────→ RETRYING → QUEUED
                    ├──────→ FAILED
                    ├──────→ CANCELLED
                    └──────→ DEAD_LETTER
```

Every job carries tenant/workspace/collection scope, an idempotency key,
operation, bounded payload metadata and correlation references. Claim,
heartbeat, acknowledge, fail, cancel and replay operations require the current
lease owner and version. The queue stores attempt history and makes recovery of
expired leases explicit.

`LocalJobRunner` and SQLite fixtures remain development/test implementations.
Production composition rejects them and requires the durable PostgreSQL queue
plus an externally controlled worker process. The live database, multi-worker,
crash/restart and retention evidence is still `BLOCKED_EXTERNAL` in this
checkout.

See [ADR-023](adr/ADR-023-real-worker-runtime.md) and
[durable-worker.md](durable-worker.md) for the detailed contract and current
verification boundary.
