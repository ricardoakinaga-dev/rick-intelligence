# Phase 2 audit — Production Intelligence Runtime Closure

**Date:** 2026-09-08  
**Audited candidate:** `HEAD 841a3dd59dcbef07418f6afec47214299e1e3dbd` plus the current untracked Phase 2 plan/prompt artifacts  
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
  10/10 checks, 30 historical files, 220 execution events and 211 verification
  records.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/jobs/src python3 -m pytest -q -p no:cacheprovider packages/jobs/tests` — `PASS`, 9 tests.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q packages/jobs/src` — `PASS`.
- `git diff --check` — `PASS` for the new Phase 2 plan, prompt copy, jobs
  package and ADR.
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

## Consolidated matrix

| Area | State | Current observation | Required next proof |
| --- | --- | --- | --- |
| Phase 2 plan and capability matrix | `DONE_LOCAL_SCOPE` | The canonical plan contains context, target architecture, invariants, matrix, slices, gates, rollback and exit criteria. | Keep it synchronized with each integrated slice. |
| Durable jobs | `DONE_LOCAL_CONTRACT / PARTIAL_RUNTIME` | Local SQLite and PostgreSQL queue implementations have bounded idempotency/lease behavior; the Phase 2.1 adapter-neutral `rick_jobs` contract is independently approved for its local bar. | Integrate adapters, normalize state vocabulary, execute PostgreSQL concurrency/recovery and multi-worker tests. |
| Worker runtime | `PARTIAL/BLOCKED_EXTERNAL` | PostgreSQL worker has polling, heartbeat, timeout and shutdown seams; no reviewed production factory is wired. | Canonical composition, startup/readiness, crash/restart, cancellation, dead-letter and real health evidence. |
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
4. The API process-local ingestion executor, local worker, PostgreSQL worker and
   new generic job contract have different vocabularies until adapter
   reconciliation is complete.
5. Local telemetry, prepared release manifests and file-level restore checks
   cannot establish distributed operational readiness.
6. The visual evidence packet covers a meaningful web slice, but not cases,
   upload/job recovery and admin mutation states; raw axe `incomplete` findings
   remain actionable until resolved or explicitly classified.
7. Evidence IDs and citation markers are validated syntactically, but claim
   textual support and the explicit decision actions are not yet implemented.

## Decision

The audit result is **`CONDITIONAL / NO-GO FOR PROMOTION`**. Local implementation
may continue under the frozen Phase 2 plan. The next required implementation
slice is Phase 2.2 adapter integration into the existing queue/worker seams;
no P2 retrieval experiment or production label is justified before P0 runtime
closure.
