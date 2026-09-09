# Phase 2.7.5 — Redis runtime gate implementation

**Date:** 2026-09-09
**Decision:** `IMPLEMENTED / LOCAL_VERIFIED / RUNTIME BLOCKED_EXTERNAL`

## Gate delivered

`scripts/phase11/redis_runtime_gate.py` is the real-runtime harness for the
canonical Redis coordination boundary. It:

- requires an explicit `RICK_TEST_REDIS_URL` or command-line URL and refuses a
  non-loopback endpoint without explicit authority;
- uses the repository's real `redis.asyncio` factory, bounded pool and
  owner-safe lease/rate-limit adapters rather than a fake client;
- proves tenant namespace separation, two-client lease contention, renew,
  owner-bound release and reacquisition;
- proves atomic fixed-window rate limiting, request-ID replay idempotency and
  independent allowance for a different tenant namespace;
- separates a live local semantic result from a production-safe capability:
  `--require-tls` is required for a `rediss://` production composition;
- writes only redacted runtime state under the ignored `.runtime/phase-2`
  directory and returns exit 2 for `BLOCKED_EXTERNAL`.

The API and worker image contracts now install the pinned `redis==5.2.1`
dependency, and the locking package's Redis extra is pinned to the same
version. Production still requires the package factory's TLS/authentication
validation and a live readiness check; no local in-memory fallback is promoted.

## Verification

| Check | Result | Meaning |
| --- | --- | --- |
| `python3 -m py_compile scripts/phase11/redis_runtime_gate.py` | `PASS` | Gate compiles without Redis. |
| `make api15-lock` | `52 passed` | Lease, Redis adapter, namespace and rate-limit local contracts remain green. |
| `make redis-runtime` | `BLOCKED_EXTERNAL` / exit 2 | Correct result with no explicit Redis URL; no fake server or hidden credential discovery. |
| `git diff --check` | `PASS` | Current patch has no whitespace errors. |

No `VERIFIED_RUNTIME` or `PROMOTABLE` claim is made. A disposable Redis
instance, credentials and permission to run the live gate are still required;
TLS/authenticated production evidence is a separate promotion condition.
