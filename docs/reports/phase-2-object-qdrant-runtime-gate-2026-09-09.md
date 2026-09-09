# Phase 2.7.6 — Object storage and Qdrant runtime gate implementation

**Date:** 2026-09-09
**Decision:** `IMPLEMENTED / LOCAL_VERIFIED / RUNTIME BLOCKED_EXTERNAL`

## Gate delivered

`scripts/phase11/object_qdrant_runtime_gate.py` is a dependency-bounded live
HTTP harness for both projection stores. It:

- requires explicit object endpoint, bucket, region and credentials plus an
  explicit Qdrant URL; it does not discover a service or create a fake
  transport;
- defaults to loopback-only endpoints and refuses non-loopback destinations
  without `--allow-nonlocal`; `--require-tls` is a separate explicit safety
  condition;
- exercises object PUT, HEAD, bounded GET, checksum comparison, DELETE and
  post-cleanup absence through the repository S3-compatible adapter;
- creates a unique Qdrant collection, probes health, creates the schema,
  upserts a tenant-scoped point, queries with ACL filters, deletes it, checks
  the count and removes only the unique fixture collection;
- records object and vector results separately, writes redacted runtime state
  under `.runtime/phase-2`, and never emits URLs, credentials, API keys or raw
  backend exception text.

## Verification

| Check | Result | Meaning |
| --- | --- | --- |
| `python3 -m py_compile scripts/phase11/object_qdrant_runtime_gate.py` | `PASS` | Gate compiles without services. |
| Missing endpoint/credential configuration | `BLOCKED_EXTERNAL` / exit 2 | No hidden discovery or fake runtime claim. |
| Closed loopback endpoints without services | `FAIL` | Configuration was accepted but live operations could not pass. |
| Non-loopback endpoints without `--allow-nonlocal` | `BLOCKED_EXTERNAL` | Endpoint policy refused unapproved authority. |
| `make compose-static` | `PASS` | The canonical stack still declares Qdrant and object storage. |

No `VERIFIED_RUNTIME` or `PROMOTABLE` claim is made. A disposable
S3-compatible service, Qdrant instance, credentials, TLS policy and
permission to run the fixture are still required.
