# ADR-021 — Canonical durable job contract

**Status:** Accepted for Phase 2.1 local implementation; production promotion pending runtime evidence  
**Date:** 2026-09-08

## Context

RICK has a pipeline-specific `IngestionJob`, a bounded SQLite queue and a
PostgreSQL queue adapter. Their state names and persistence concerns are useful
local/adapter behavior, but they do not yet provide one cross-runtime contract
for API admission, durable queues, workers, retries, leases, replay and
observability. The Phase 2 blueprint requires explicit durable execution while
preserving the local implementation as a development/test adapter.

## Decision

`packages/jobs/src/rick_jobs/contracts.py` is the canonical adapter-neutral
contract for durable execution. It defines:

- `Job` and `JobState` with `PENDING`, `QUEUED`, `RUNNING`, `SUCCEEDED`,
  `FAILED`, `CANCELLED`, `RETRYING` and `DEAD_LETTER`;
- immutable bounded `JobAttempt`, `JobResult`, `JobFailure` and `JobLease`
  values;
- explicit tenant, workspace, collection and idempotency scope;
- deterministic metadata-only serialization;
- structural `JobRepository`, `JobQueue`, `JobExecutor` and `JobScheduler`
  protocols;
- fail-closed validation of identifiers, timestamps, attempts, transitions and
  secret/raw-content-like payload fields.

Existing SQLite and PostgreSQL queue implementations remain preserved until
each adapter is migrated through differential verification. Implementing this
contract does not itself claim durability, distribution, recovery or production
readiness.

## Alternatives

1. Keep the pipeline-specific `IngestionJob` as the only contract. Rejected:
   it cannot express the full worker/runtime lifecycle without coupling every
   adapter to ingestion details.
2. Put queue models in `apps/worker`. Rejected: API admission and other durable
   producers would depend on an application package.
3. Bind the contract directly to PostgreSQL/Redis or a broker SDK. Rejected:
   it would make the public contract vendor-specific and weaken local,
   differential and adapter testing.

## Consequences

Positive:

- future adapters share state, scope, retry and lease semantics;
- unsafe payloads and impossible transitions fail before persistence;
- local and external implementations can be compared without deleting legacy
  behavior;
- the worker and ingestion migration have a stable dependency direction.

Costs and limits:

- existing adapters need explicit translators and new contract tests;
- the package does not persist or execute jobs;
- a production gate still requires disposable/integration runtime, multi-worker
  recovery, observability, restore and independent review;
- `IngestionJob` retains its stage-specific state machine until Phase 2.6
  durable ingestion reconciliation.
