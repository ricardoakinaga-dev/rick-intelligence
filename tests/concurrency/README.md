# Concurrency tests

Status: CURRENT (2026-10-09). This directory documents the lane; it does not
contain a second executable suite.

Lock ownership, lease expiry, retry, idempotency and worker cancellation. The executable sources are in
[packages/locking/tests](../../packages/locking/tests/). Run from the repository root:

```bash
make api15-lock api16-worker
```

The [root command contract](../../README.md) identifies related gates. Local
adapter/fixture results do not establish distributed production behavior.
Runtime gates use explicit approved endpoints and return `2` when externally
blocked; `0` is reserved for an executed pass and `1` for an observed failure.
