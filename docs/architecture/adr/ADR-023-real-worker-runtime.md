# ADR-023 — Canonical real worker runtime

**Status:** Accepted for local implementation; production promotion blocked by
external runtime evidence

**Date:** 2026-09-09

## Context

The repository had a bounded local runner and a legacy PostgreSQL worker, while
the canonical `rick_jobs` contract and `PostgresJobQueue` lived beside them.
Keeping the legacy worker as the production composition would split claim,
lease, attempt history and failure ownership. API callers also need a scoped
status/cancel surface without becoming a second worker authority.

## Decision

`apps/worker/runtime.py` is the canonical process runtime. A deployment injects
one explicit `JobScope`, a finite `OperationRegistry`, a `JobQueue`, a worker
identity and bounded execution settings. The runtime:

- validates queue health and the `0005` schema marker before its first claim;
- claims directly through the canonical queue with `FOR UPDATE SKIP LOCKED`
  semantics supplied by the adapter;
- limits active handlers and payload bytes;
- renews owner-bound leases, maps failures to a safe bounded vocabulary and
  never acknowledges after lease loss or cooperative cancellation;
- supports owner-bound running-job cancellation and a finite shutdown deadline;
- exposes readiness, liveness, metrics and redacted lifecycle events; and
- freezes the operation registry at startup so no import discovery or fallback
  handler can enter the worker.

`apps/worker/canonical_queue.py` is an API compatibility facade only. It
translates scoped `QueueRecord` values to canonical jobs, rejects unscoped
reads, and encodes display filenames as bounded references. The API composition
constructs the canonical queue and runtime without opening a database; the
worker launcher calls startup before polling and handles process signals.

Migration `0005_rewrite_legacy_jobs.sql` is the caller switch. It acquires the
same advisory lock as the legacy enqueue path, fails closed for malformed rows,
normalizes legacy payloads, materializes append-only attempt history, emits one
stable lifecycle/outbox/audit event per rewrite, and rejects new legacy rows
after the switch.

## Consequences

There is one worker authority for canonical jobs, and API compatibility does
not widen tenant/workspace reads. Startup and readiness are truthful about the
schema marker, while API composition remains lazy and testable without network
I/O. Legacy imports remain available during rollout, but legacy writes cannot
continue after the migration.

The runtime uses cooperative Python handler threads. It bounds admission,
leases, acknowledgement and shutdown behavior, but Python cannot safely kill a
handler that ignores its cancellation token. A deployment requiring hard
process isolation must supply that boundary and its evidence before calling the
runtime production ready.

## Evidence and limits

The local packet is covered by `make jobs-test`, `make api16-worker`, the
worker-entrypoint tests, infrastructure static tests, `make ops-static` and
`git diff --check`. A fresh I1 review is required for the exact integrated
packet. Disposable PostgreSQL migration, FK, trigger, two-worker, crash,
restart, replay, SIGTERM and handler-isolation execution remains
`BLOCKED_EXTERNAL` until the required services and supervisor are available.
