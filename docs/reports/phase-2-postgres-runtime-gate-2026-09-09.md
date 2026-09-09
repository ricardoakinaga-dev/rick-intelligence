# Phase 2.7.3 — PostgreSQL runtime gate implementation

**Date:** 2026-09-09
**Decision:** `IMPLEMENTED / LOCAL_VERIFIED / RUNTIME BLOCKED_EXTERNAL`

## Gate delivered

`scripts/phase11/postgres_runtime_gate.py` is the real-runtime harness for the
canonical `PostgresJobQueue`. It:

- refuses non-PostgreSQL and non-loopback DSNs unless explicit runtime
  authority is supplied;
- applies the six migrations through the existing transactional migration
  runner;
- verifies migration history, queue constraints, claim/idempotency/dead-letter
  indexes and a real `FOR UPDATE SKIP LOCKED` query plan;
- seeds a unique disposable tenant/workspace/collection fixture;
- exercises enqueue idempotency, lease ownership, expiry/reclaim, stale Worker A
  ACK rejection after Worker B reclaim, dead-letter, replay, successful ACK and
  terminal retention against real PostgreSQL connections;
- cleans only the fixture scope and writes a redacted JSON result under the
  ignored runtime directory;
- returns `BLOCKED_EXTERNAL` when the DSN/driver/database is unavailable rather
  than treating a fake connection as runtime proof.

The image dependency contract now includes pinned `psycopg[binary]` in the API
and worker images so an approved composition can actually open PostgreSQL
connections.

## Verification

| Check | Result | Meaning |
| --- | --- | --- |
| `python3 -m py_compile scripts/phase11/postgres_runtime_gate.py` | `PASS` | Gate compiles without services. |
| `make postgres-runtime` | `BLOCKED_EXTERNAL` / exit 2 | Correct result with no `RICK_TEST_DATABASE_DSN`; no fake DB or hidden credential discovery. |
| `make compose-static` | `PASS` | Canonical stack still renders with the declared service set. |
| migration/static/docker focused tests | `24 passed` | Existing migration and image policy contracts remain intact; the lineage migration is additionally covered by targeted knowledge tests. |

No `VERIFIED_RUNTIME` claim is made. A disposable loopback PostgreSQL daemon,
`psycopg`, non-production credentials and permission to run the harness are
still required before this gate can produce live evidence.
