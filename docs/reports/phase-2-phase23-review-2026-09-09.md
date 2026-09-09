# Phase 2.3 local review — real worker runtime

**Date:** 2026-09-09 UTC
**Candidate:** current Phase 2.3 worker-runtime packet, ready for integration
**Review status:** `READY_LOCAL_SCOPE`; fresh I1 review complete

## Scope

This packet connects the canonical `rick_jobs` PostgreSQL adapter to a bounded
worker runtime and keeps the API compatibility surface scoped. It includes:

- `apps/worker/runtime.py` with explicit scope, registry, admission limits,
  heartbeats, owner cancellation, timeout/failure mapping and finite shutdown;
- `apps/worker/canonical_queue.py` and API composition wiring;
- readiness/startup/signal handling in `infrastructure/docker/worker-entrypoint.py`
  and the worker image's jobs-package boundary;
- migration `0005_rewrite_legacy_jobs.sql` with legacy payload normalization,
  attempt reconstruction, lifecycle/outbox/audit projection and the legacy
  write guard; and
- focused runtime, adapter, external-ingestion, API composition, entrypoint and
  migration static tests.

## Local evidence

The packet passes the focused runtime/adapter/composition/entrypoint matrix, the
canonical jobs regression, infrastructure tests, migration checksum checks and
whitespace/compilation checks. The final local matrix is:

- `make jobs-test` — 34 passed;
- `make api16-worker` — 68 passed;
- `make api16-root` — 426 passed, 238 deprecation warnings;
- `make api16-domain` — 107 passed;
- infrastructure scripts and Docker tests — 36 passed;
- targeted Phase 2.3 paths — 57 passed in the fresh I1 review;
- `make ops-static` — five migration checksums, shell syntax and compilation
  checks passed; live migration execution remains `NOT_RUN`;
- `git diff --check` and Python compilation — passed.

The final I1 verdict is `READY_LOCAL_SCOPE` with no reproducible local P0, P1 or
P2 finding. The review covered the API production factory hook, content
addressed upload race, parser extension bridge, canonical deadline/lease
fencing, migration projections and Docker import/signal boundaries.

## Findings boundary

The runtime prevents late acknowledgement after timeout, lease loss or
cooperative cancellation. It cannot force-stop a Python handler that ignores
the token; such a handler can continue in a daemon thread after its durable job
has been failed. Process isolation or a supervisor-owned hard kill boundary is
therefore an external production gate. No disposable PostgreSQL, two-worker,
crash/restart, live SIGTERM, object store, Qdrant, Redis, provider or production
deployment execution was available for this review.

## Required independent decision

The fresh read-only I1 critic inspected the exact packet, verified that the API
uses the canonical queue/runtime, checked the migration's durable projections
and scope guards, and returned `READY_LOCAL_SCOPE` without editing source or
control state. This approval is limited to the local implementation scope and
does not promote the external gates.
