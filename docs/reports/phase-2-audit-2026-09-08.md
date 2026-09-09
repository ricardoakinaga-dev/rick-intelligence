# Phase 2 audit — Production Intelligence Runtime Closure

**Date:** 2026-09-09
**Audited candidate:** current Phase 2.3 real-worker-runtime packet on top of the published Phase 2.2 candidate
**Source:** [`docs/prompts/state-of-art-triple-aaa-2026-09-08.txt`](../prompts/state-of-art-triple-aaa-2026-09-08.txt)  
**Canonical plan:** [`docs/plans/phase-2-production-intelligence-runtime.md`](../plans/phase-2-production-intelligence-runtime.md)

## Audit method

The audit inspected the current root source, preserved component boundaries,
contracts, migrations, tests, Compose/Docker files, CI workflows, visual
artifacts and operations documents. Four read-only scouts covered runtime/P0,
intelligence/retrieval, security/operations and frontend/design. Their reports
were based on the live checkout and did not edit source or control-plane state.
Historical scores and prior PASS labels were treated as references, not proof
of the current candidate.

Baseline checks executed locally:

- `make validate` — `PASS`; root boundaries and control plane validated with
  10/10 checks after the Phase 2.3 review binding.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/jobs/src python3 -m pytest -q -p no:cacheprovider packages/jobs/tests` — `PASS`, 9 tests.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q packages/jobs/src` — `PASS`.
- `make jobs-test` — `PASS`, 34 canonical jobs/runtime tests.
- `make api16-worker` — `PASS`, 68 worker/API health tests.
- `make api16-root` — `PASS`, 426 API tests.
- `make api16-domain` — `PASS`, 107 knowledge/ingestion/retrieval tests.
- Infrastructure scripts and Docker tests — `PASS`, 36 tests.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider infrastructure/scripts/tests` — `PASS`, 23 tests including migration history divergence, rollback and schema assertions.
- `make ops-static` — `PASS`; migration checksums report 5 files and live
  execution remains `NOT_RUN`.
- `git diff --check` — `PASS` for the current dirty packet.
- No external service, provider, corpus, production-like Compose, restore,
  chaos, soak or assistive-technology run was performed in this audit.

## Phase 2.1 contract gate

The durable-job contract slice was independently reviewed against the frozen
`P2-P0-01` bar after corrective rounds. The final sealed I1 review approved
the exact six-artifact candidate with combined fingerprint
`5c1bd3b11c9f6380e9400aa003bda8f6f229c143e59e4e4f858336f63c026459`.
The review ran 9 focused tests, compilation, whitespace checks and 12
adversarial assertions covering scope/version guards, idempotency replay and
conflict, retry limits, lease ownership, attempt chronology, state
reconstruction and metadata rejection.

This is a local contract approval only. No adapter, database, broker, worker,
recovery, observability or production promotion claim follows from it.

## Phase 2.2 local implementation packet

The bounded local slice adds `PostgresJobQueue` as the canonical adapter while
preserving the legacy facade for the Phase 2.3 worker migration. Migration
0004 keeps `rick_ingestion_jobs` as the authority, archives the empty competing
0001 queue table, adds the operation/state/version/result/failure/lease fields,
replaces tenant-wide idempotency with complete scope, enforces composite job to
document scope, records bounded attempt history, and creates lifecycle
outbox/event/audit coupling. Adapter mutations use scope predicates, advisory
serialization for scoped producers, optimistic versions, owner-bound lease
fencing, expiry recovery, explicit retry/DLQ transitions, authorized replay
clones and bounded terminal pruning.

The local packet is not a PostgreSQL execution gate. No disposable PostgreSQL
driver/container is available in the current environment, so row locks,
transaction isolation, FK rejection, query plans, concurrent producers,
two-worker claims and crash-before/after-commit behavior remain `NOT_RUN` or
`BLOCKED_EXTERNAL`.

The fresh I1 review in [`phase-2-phase22-review-2026-09-09.md`](phase-2-phase22-review-2026-09-09.md)
approved the exact local packet with no remaining P0/P1/P2 finding. The packet
keeps pre-existing and newly written legacy rows in a NULL canonical-state
lane, fences the legacy and canonical writers separately, uses
`clock_timestamp()` for lease decisions, protects attempt history with SQL
triggers and deferred count/contiguity checks, and projects heartbeat and
retention actions to lifecycle, outbox and audit records in the same
transaction.

## Phase 2.3 local implementation packet

The Phase 2.3 slice now composes `PostgresJobQueue` with
`RealWorkerRuntime`/`WorkerRuntime`, a frozen operation registry, bounded
payload and concurrency limits, heartbeat and lease fencing, cooperative
cancellation, timeout/failure mapping and finite shutdown. The API's
`CanonicalIngestionQueueAdapter` remains a scoped compatibility facade. The
production entrypoint is connected through the deployment-owned
`RICK_API_COMPOSITION=module:factory` hook, while the worker launcher keeps its
explicit composition hook and process-level health contract.

Migration 0005 normalizes legacy rows, reconstructs bounded attempts, projects
lifecycle/outbox/audit records and blocks future legacy writes. The runtime
preserves validated upload extensions for the real parser and the durable
upload path uses checksum-derived object keys without unsafe loser cleanup in
an idempotency race. Contract and migration operation validation use the same
bounded identifier grammar.

The fresh I1 review returned `READY_LOCAL_SCOPE` with no reproducible local P0,
P1 or P2 finding. The current local matrix passed 34 jobs tests, 68 worker/
health tests, 426 API tests, 107 domain tests, 36 infrastructure tests and
five migration checksum/static checks. This remains a local implementation
approval: PostgreSQL execution, multi-worker fencing, crash/restart, live
SIGTERM, handler process isolation, external stores and deployment remain
`BLOCKED_EXTERNAL` or `NOT_RUN`.

## Consolidated matrix

| Area | State | Current observation | Required next proof |
| --- | --- | --- | --- |
| Phase 2 plan and capability matrix | `DONE_LOCAL_SCOPE` | The canonical plan contains context, target architecture, invariants, matrix, slices, gates, rollback and exit criteria. | Keep it synchronized with each integrated slice. |
| Durable jobs | `DONE_LOCAL_SCOPE / BLOCKED_EXTERNAL` | Phase 2.1 contract and Phase 2.2 canonical PostgreSQL adapter are independently approved for local scope; migration 0004, attempt history, outbox/audit coupling, replay/retention and focused tests are current. | Execute PostgreSQL migration/concurrency/recovery/FK/crash/replay gates and complete worker composition. |
| Worker runtime | `DONE_LOCAL_SCOPE / BLOCKED_EXTERNAL` | Phase 2.3 canonical runtime, API composition, parser bridge, migration 0005 and launcher are independently reviewed for local scope; local matrix is current. | PostgreSQL execution, crash/restart, cancellation under live leases, two-worker fencing, live SIGTERM and hard handler isolation. |
| Redis coordination/rate limits | `PARTIAL/MISSING` | Owner-safe Redis lease adapter exists; no Redis-backed rate limiter or complete shared client policy exists. | Atomic distributed limiter, required production injection, namespace/TLS/auth/retry and multi-replica abuse tests. |
| Qdrant | `PARTIAL` | HTTP adapter validates scopes and payloads; live operations and schema/index lifecycle are absent. | Collection/schema migration, alias/reindex, retries/circuit behavior and disposable live integration. |
| Object storage | `PARTIAL` | Local and S3-compatible adapters cover scope/checksum/limits. | Streaming/content-addressed/retention policy, composition and live MinIO/S3 evidence. |
| Ingestion | `PARTIAL` | Local lifecycle and lineage exist; external path is not transactionally/recovery proven. | Durable stage state, publication choreography, replay, version retention and crash matrix. |
| Retrieval/evidence | `PARTIAL` | Hybrid retrieval, ACL revalidation, evidence DTO and citation marker checks exist locally. | EvidenceBundle/Validator, claim-level textual support, decision actions and live/freshness eval. |
| Providers/local models | `PARTIAL/BLOCKED_EXTERNAL` | OpenAI-compatible client and resilience exist; capability negotiation and local runtime matrix are absent. | Provider request/response/stream/capability/health contracts, budgets and disposable local runtime. |
| Tenancy/security | `PARTIAL` | Tenant-aware identity, authorization, storage and local negatives exist. | Full cross-boundary matrix, RLS/constraints, distributed rate limit and external identity. |
| File/RAG security | `PARTIAL` | Bounds, path normalization, scoped storage and untrusted-data messaging exist. | Magic bytes, archive/decompression limits, parser isolation/timeouts and adversarial injection corpus. |
| Observability/SLO | `PARTIAL/MISSING` | Redacted local counters/events/correlation exist; no OTel exporter or canonical SLO document. | Distributed traces/metrics/logs, collector, spans, SLO windows and alert delivery. |
| Disaster recovery | `PARTIAL/BLOCKED_EXTERNAL` | File-level checksum/reconciliation rehearsal and runbook exist. | Service backups/restores, RPO/RTO and wrong-tenant restore smoke. |
| Deployment/CI/supply chain | `PARTIAL/BLOCKED_EXTERNAL` | Reference Compose, Docker static gates and phase workflows exist. | Complete dev/staging stack, pinned/scanned/signed artifacts, laneed CI and current release evidence. |
| Frontend/design | `PARTIAL` | Current local six-route visual matrix and responsive/accessibility seams exist. | Cases/upload/jobs/admin mutation visual coverage, actionable axe incomplete findings, Lighthouse/equivalent, focus trap, fresh independent full-product critique. |
| Evaluation/clinical boundary | `PARTIAL/BLOCKED_EXTERNAL` | Safe synthetic evaluation pack and closed-by-default case route exist. | Approved/licensed veterinary corpus, risk classes, domain review and citation/abstention metrics. |
| Independent review/promotion | `PARTIAL/BLOCKED_EXTERNAL` | Historical scoped I1 reviews and anti-gaming controller exist. | Fresh current reviews for architecture, security, retrieval, ingestion, runtime, observability, web and operations. |

## Highest-risk findings

1. Production composition can still install a process-local rate limiter when a
   distributed limiter is not injected. This defeats multi-replica abuse
   protection and must be closed before production mode is accepted.
2. Upload validation relies partly on untrusted MIME/suffix information; DOCX
   ZIP and PDF parsing lack the complete archive, CPU, memory and wall-clock
   isolation required by the blueprint.
3. The preserved legacy RAG path is not a production tenant/security boundary;
   it must remain isolated or be explicitly gated before any production caller
   switch.
4. The local implementation now has one reviewed canonical worker composition,
   while the external PostgreSQL, multi-worker and supervisor gates remain
   unexecuted.
5. Local telemetry, prepared release manifests and file-level restore checks
   cannot establish distributed operational readiness.
6. The visual evidence packet covers a meaningful web slice, but not cases,
   upload/job recovery and admin mutation states; raw axe `incomplete` findings
   remain actionable until resolved or explicitly classified.
7. Evidence IDs and citation markers are validated syntactically, but claim
   textual support and the explicit decision actions are not yet implemented.

## Decision

The audit result is **`CONDITIONAL / NO-GO FOR PROMOTION`**. The Phase 2.3 local
implementation may continue to Phase 2.4 under the frozen plan. The disposable
PostgreSQL gate and the remaining P0 runtime gates still block production
promotion.
