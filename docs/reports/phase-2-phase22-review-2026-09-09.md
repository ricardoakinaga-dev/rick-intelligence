# Phase 2.2 local review — canonical PostgreSQL jobs adapter

**Date:** 2026-09-09 UTC
**Candidate:** `HEAD 96bc09c9d90eeb98c186addf2d65b41ed43440cd` plus the current
Phase 2.2 dirty packet
**Packet fingerprint:** `0c2a6cd1ae161641ce33b5b79b1149c19c40657a9c61880d19711cb012651106`

## Independent verdict

Fresh I1 read-only review: **APPROVE for the declared local implementation
scope**. No current P0, P1 or P2 local findings remained after the corrective
rounds. The review did not edit source or control-plane state.

The external Phase 2.2 gate remains **`BLOCKED_EXTERNAL`**. This checkout has
no usable `psycopg`/`psql`, and Docker daemon access is denied. PostgreSQL DDL,
FK rejection, deferred triggers, row locks, `SKIP LOCKED` races, transaction
rollback, crash durability, query plans and live replay/retention behavior
remain unexecuted.

## Local evidence

- `make jobs-test` — 16 passed.
- Legacy queue plus canonical adapter and contract regression — 20 passed.
- Migration runner, migration static and migration history divergence tests — 6 passed.
- `make api16-worker` — 52 passed.
- `infrastructure/scripts/tests` — 23 passed.
- `make ops-static` — migration checksum check passed for four files; live execution `NOT_RUN`.
- `make validate` — 10/10 control-plane checks passed.
- `python3 -m py_compile` — passed for the changed Python modules.
- `git diff --check` — passed.

The local packet covers the canonical adapter, complete scoped idempotency,
legacy/canonical lane isolation, optimistic CAS versions, owner and expiry
fencing, database-clock lease timestamps, append-only attempt guards and
deferred count/contiguity checks, lifecycle event plus outbox/audit coupling,
dead-letter replay, retention projection and migration checksum/lock checks.
