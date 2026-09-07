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

The local file is WAL-backed and private (`0700` parent, `0600` database). A
reopened queue can recover a leased job after its lease expires. This proves a
restartable local primitive only. It is not a distributed queue, does not
provide multi-instance fencing, and is rejected when `RICK_ENV=production`.
Production still requires an external broker or reviewed database queue,
metrics/alerts, operator dead-letter tooling, and an integration drill.
