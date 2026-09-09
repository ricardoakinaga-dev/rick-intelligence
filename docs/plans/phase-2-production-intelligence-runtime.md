# Phase 2 — Production Intelligence Runtime Closure

**Status:** `ACTIVE / PLAN AND AUDIT COMPLETE BEFORE BUILD`  
**Date:** 2026-09-08  
**Source prompt:** [`docs/prompts/state-of-art-triple-aaa-2026-09-08.txt`](../prompts/state-of-art-triple-aaa-2026-09-08.txt)  
**Source prompt SHA-256:** `b222cf1a52c54dc075e2f64896aab1678941371109ff3ac296f922b98dee7513`  
**Current candidate:** `HEAD 841a3dd` (`main`, synchronized with `origin/main` at audit start)

This is the canonical Phase 2 plan and current-state audit. It is deliberately
written before Phase 2.1 implementation. A row marked `PARTIAL`, `MISSING`,
`BLOCKED`, or `NOT RUN` is not a production claim and cannot be promoted by
the existence of this document.

## 1. Context

RICK Intelligence is a brownfield platform assembled from three preserved
systems: the canonical FastAPI/Next.js root, the preserved CVG RAG system, the
preserved Professor service, and the preserved Redis locker. Phase 1.6 created
the root contracts, tenant-aware local knowledge/retrieval, bounded ingestion,
provider and Professor seams, a local durable SQLite journal, a worker boundary,
an object-store abstraction, a canonical web caller, and a control plane for
plans, evidence, critics, and release integrity.

The current repository has meaningful local evidence, but the public path still
has explicit boundaries around external runtime. The local queue is restartable
SQLite, not a multi-instance production queue. Local object storage and local
vector/read models are not production storage. Redis, Qdrant, PostgreSQL,
object storage, an external provider, a telemetry collector, live OIDC, restore
drills, load/soak/chaos, and an approved veterinary corpus have not been
executed in this workspace. Existing reports correctly classify those claims as
`NOT_RUN`, `BLOCKED_EXTERNAL`, or local-only.

The requested outcome is therefore a system closure program: preserve the
working migration architecture, make each runtime boundary executable, and
promote only the exact artifact whose public path and evidence satisfy the
frozen bar. The target is a Knowledge + Reasoning + Evidence + Verification
platform, not a chatbot with an unbounded RAG shortcut.

## 2. Classification and working contract

| Axis | Current classification | Evidence and consequence |
| --- | --- | --- |
| Project profile | `BROWNFIELD` with `LEGACY` boundaries | Existing root runtime, preserved child systems, public contracts and migration map. Legacy code remains protected. |
| Primary work mode | Modernization / audit / feature implementation | The requested change crosses runtime, data, security, operations, API, evaluation and UI boundaries. |
| Overlays | Migration, security hardening, reliability, visual QA, release engineering | Each overlay keeps its own evidence and rollback requirements. |
| Lifecycle | `AUDIT → SPEC → BUILD → VERIFY → PROMOTE` | The current action is audit and specification; implementation begins only after this plan and bar are frozen. |
| Engineering tier | `T4 / critical cross-system` | Auth, tenancy, clinical safety boundary, durable data, recovery and production readiness have high or critical failure impact. |
| Blast radius | `CROSS_SYSTEM` | API, web, worker, packages, database, queue, vector index, object storage, CI and preserved callers. |
| External authority | Local implementation is authorized; production cutover, real credentials, live corpus and deployment remain separately gated | This plan can build adapters and isolated fixtures. It cannot infer production approval from local tests. |
| State persistence | Required | `.agent`, `.gauntlet`, `.orchestrate`, backlog, append-only logs, evidence manifests and this plan remain canonical control surfaces. |

## 3. Problems to close

1. Durable execution is split between local SQLite and a partially implemented
   PostgreSQL queue; the production composition root and multi-worker recovery
   path are not proven.
2. Redis, Qdrant, object storage and provider adapters exist as seams or local
   implementations, but their health, retry, security, tenancy and operational
   behavior are not all wired through one canonical runtime.
3. Ingestion has a bounded lifecycle and lineage fields locally, but a durable
   external publication transaction, replay, index verification and recovery
   drill remain open.
4. Retrieval and Professor have evidence-aware local contracts, but the
   decision layer, citation verification, calibration semantics, advanced
   retrieval experiments and approved evaluation corpus are not yet a complete
   acceptance chain.
5. Security and tenancy have strong local negatives, but the formal threat
   model, RAG/file adversarial corpus, external identity, distributed rate
   limits and live multi-replica proof remain incomplete.
6. Observability and SLO definitions are local/bounded. Distributed trace,
   metrics, log collection, alert delivery and incident evidence are not yet
   demonstrated at the runtime boundary.
7. The web surface has a verified local visual/interaction slice, while the
   full API-backed production states, independent final visual review, mobile
   recovery, performance under slow dependencies and release integration remain
   open.
8. The CI history is phase-specific. It needs one canonical quality workflow
   with explicit FAST, UNIT, CONTRACT, INTEGRATION, SECURITY, RAG-EVAL, E2E,
   PERFORMANCE, CHAOS and RELEASE lanes without erasing historical evidence.

## 4. Objectives

- Define and implement a durable job contract with retries, leases,
  idempotency, deduplication, heartbeats, cancellation, recovery and dead
  letters.
- Promote `apps/worker` to a real runtime while preserving the local worker as
  a development/test implementation.
- Make Redis, PostgreSQL, Qdrant, object storage and provider health explicit,
  bounded, tenant-safe and fail-closed in production composition.
- Make ingestion durable from upload through verification/publication with
  versioned lineage and auditable recovery.
- Formalize Evidence, citation validation and the decision layer at the
  Professor boundary.
- Prove authorization and tenant isolation across identity, retrieval, jobs,
  storage, audit, caches, rate limits and UI state.
- Produce distributed observability, SLOs, disaster recovery, soak/chaos and
  release-integrity evidence without inventing unavailable results.
- Raise the web surface to a product-specific, responsive, accessible and
  independently reviewed workflow at 375/768/1440 widths.
- Preserve legacy implementations, compatibility behavior, differential
  verification and rollback paths until promotion criteria explicitly allow a
  caller switch.

## 5. Non-goals and boundaries

- No rewrite of the preserved CVG, Professor or Locker implementations.
- No removal of legacy code before adapter, contract, differential, caller
  migration and production evidence exist.
- No production deployment, external data cutover, real clinical corpus,
  unbounded provider spend, or credential publication from this worktree.
- No invented veterinary knowledge, diagnosis, prescription or clinical
  conclusion. The clinical-case surface remains closed unless its explicit
  domain gate is approved.
- No vendor-specific storage or model contract where an S3-compatible,
  OpenAI-compatible or protocol-level adapter is sufficient.
- No feature flag is promoted because it exists; experimental retrieval
  strategies require an evaluation delta against a versioned baseline.
- No benchmark, screenshot, SLO, restore, chaos or security result is claimed
  when the required runtime or artifact was not observed.

## 6. Current architecture

```text
preserved CVG / Professor / Locker
          │ explicit compatibility and differential boundaries
          ▼
apps/web ──> apps/api composition root ──> packages/contracts
                                      ├── identity + authorization
                                      ├── knowledge + ingestion
                                      ├── retrieval + providers
                                      ├── Professor orchestration
                                      ├── storage + audit + observability
                                      └── locking / local durable seams

Current local evidence: SQLite knowledge/audit/job journal, in-memory/local
vector fixtures, deterministic provider, bounded local worker, local web/API.
External adapters and production runtime are present only in selected seams or
static compositions and remain separately gated.
```

Relevant current sources include:

- `README.md`, `CONTRIBUTING.md`, `docs/architecture/migration-map.md`;
- `docs/architecture/adr/ADR-001` through `ADR-020`;
- `docs/architecture/rec-integration-data.md`;
- `apps/api/src/app.py`, `apps/api/src/core/`, `apps/api/src/services/`;
- `apps/worker/durable_queue.py`, `apps/worker/postgres_queue.py`,
  `apps/worker/postgres_runner.py`;
- `packages/knowledge`, `packages/ingestion`, `packages/retrieval`,
  `packages/storage`, `packages/locking`, `packages/providers`,
  `packages/professor`, `packages/observability`;
- `infrastructure/compose`, `infrastructure/docker`, `infrastructure/migrations`,
  `infrastructure/scripts`;
- `.github/workflows/`, `scripts/phase15/`, `scripts/phase16/` and
  `scripts/state_of_art/`.

## 7. Target architecture

```text
                         RICK INTELLIGENCE

     ┌──────────────────────┬──────────────────────┬──────────────────────┐
     │ Knowledge Plane      │ Reasoning Plane      │ Control Plane         │
     │                      │                      │                       │
     │ upload/object store  │ Professor            │ OIDC/identity         │
     │ extract/chunk/embed  │ retrieval strategy   │ authorization/tenancy │
     │ durable ingestion    │ tool/provider use    │ audit/policy           │
     │ Qdrant projection    │ response generation  │ jobs/governance       │
     └──────────────┬───────┴──────────────┬───────┴──────────────┬────────┘
                    │                      │                      │
                    ▼                      ▼                      ▼
             Evidence Engine       Verification Engine     Observability
                    └──────────────┬──────────────┬──────────────┘
                                   ▼              ▼
                             Decision Layer   Recovery Layer
                                   │              │
                                   └──────┬───────┘
                                          ▼
                              API / Web / Worker / Agents

PostgreSQL: authority for identities, memberships, catalog, jobs, sessions,
conversations and audit/outbox. S3-compatible store: private immutable bytes
and derived artifacts. Qdrant: recoverable authorized projection. Redis:
distributed coordination, rate limit, leases and ephemeral state. Each boundary
has a contract, health signal, timeout, retry policy, scope enforcement,
telemetry and recovery procedure.
```

## 8. Decisions and dependencies

The existing REC integration decision records PostgreSQL with transactional
queue, S3-compatible storage and OIDC for an isolated local integration lab.
It does not authorize production cutover. The implementation will therefore
use the following sequence:

1. Keep SQLite/local adapters for development and differential tests.
2. Implement protocol-compatible PostgreSQL, S3-compatible, Redis, Qdrant and
   OIDC compositions behind explicit factories.
3. Run isolated disposable integration tests first.
4. Capture live runtime evidence only when services, credentials, corpus and
   cost limits are explicitly available.
5. Promote a component only after its independent gate and integrated
   rollback/recovery evidence are current.

Dependencies that can block only their dependent gates:

- Docker daemon or disposable service runtime for Compose and integration;
- PostgreSQL, Redis, Qdrant, S3-compatible, OIDC and telemetry endpoints;
- provider credential, model limits and an explicit spend ceiling;
- licensed/approved synthetic or veterinary evaluation corpus;
- browser, Lighthouse and axe execution for full visual evidence;
- independent security/domain reviewer for high-risk promotion.

## 9. Invariants

### Contracts and compatibility

- API/OpenAPI error, ordering, pagination and compatibility behavior remain
  explicit and deterministic.
- `apps -> packages -> shared/contracts` remains the dependency direction.
- Legacy implementations remain byte-preserved unless a separately approved
  migration changes the boundary.
- Every new public behavior has a contract, test, migration note and rollback
  path.

### Security and tenancy

- Tenant, workspace, collection, actor and resource scope are derived or
  validated server-side; missing scope denies rather than becoming `default`.
- Retrieved corpus content is untrusted data and cannot become a system
  instruction.
- Production rejects process-local coordination, local-only durability and
  test identity/provider fallbacks.
- Audit records contain actor, action, resource, scope, result and correlation,
  never passwords, tokens, provider secrets or unnecessary raw clinical text.

### Durability and recovery

- Every job mutation is idempotent and owner/lease bound.
- A lost lease cannot allow an old worker to acknowledge or publish a newer
  owner’s result.
- A failed ingestion attempt cannot replace the last verified published
  version.
- PostgreSQL is authoritative for durable job/catalog state; Qdrant is a
  rebuildable projection; object bytes are immutable and checksum-addressed.
- Shutdown, retry, replay, dead-letter and restore outcomes are observable and
  bounded.

### Evidence and promotion

- Evidence IDs and citations are server-generated and validated against the
  exact tenant/workspace/document version/chunk checksum.
- A missing, stale, blocked or unexecuted gate never becomes `PASS`.
- Builders do not approve their own material work; a fresh reviewer or
  externally owned deterministic gate is required at the applicable tier.
- All evidence manifests bind the exact artifact fingerprint, command, result,
  environment and limitations.

## 10. Capability audit matrix

`CURRENT` means the requested capability is implemented and observed at its
claimed boundary. `PARTIAL` means a local or bounded slice exists but the full
requested boundary is open. `MISSING` means no adequate implementation is
connected. `BLOCKED` means safe progress depends on an unavailable external
condition or explicit authority. `DONE` is reserved for the exact declared
local scope; it is not a production promotion.

| ID | Capability | State | Current evidence | Gap or promotion condition |
| --- | --- | --- | --- | --- |
| P2-A01 | Architecture audit and preservation map | `PARTIAL` | README, migration map, ADR-001..020, dependency-boundary checks | This plan freezes the Phase 2 target; independent architecture review remains. |
| P2-A02 | Phase 2 plan and implementation slices | `DONE` | This file, prompt hash and matrix | Keep it current as contracts/evidence change. |
| P2-A03 | `.agent` / `.gauntlet` evidence control | `PARTIAL` | Existing append-only state, gate history and review artifacts | Reconcile current HEAD and add Phase 2 task/evidence records without stale PASS reuse. |
| P2-P0-01 | Durable job contracts (`Job`, state, attempt, result, failure, lease, repository, queue, executor, scheduler) | `PARTIAL` | `apps/worker/durable_queue.py`, `postgres_queue.py`, ingestion contracts/tests | Canonical `packages/jobs` contract, state vocabulary, adapter parity and production rejection. |
| P2-P0-02 | Durable queue, retries, backoff, deduplication, leasing, recovery, DLQ and replay | `PARTIAL` | SQLite lease/retry/dead-letter tests and PostgreSQL queue implementation | Disposable PostgreSQL execution, multi-worker fencing, poison-job policy and replay evidence. |
| P2-P0-03 | Real worker lifecycle and bounded execution | `PARTIAL` | `apps/worker/runner.py`, `postgres_runner.py`, lifecycle tests | Canonical composition, startup/readiness, resource limits, crash/restart and operational metrics. |
| P2-P0-04 | Redis production capability | `PARTIAL` | `packages/locking`, HTTP/Redis seam and local health contracts | Shared Redis client/pool, TLS/auth/namespace, retry/circuit breaker and live health. |
| P2-P0-05 | Distributed rate limiting | `PARTIAL` | `RateLimiter` protocol and bounded local/injected implementation | Redis atomic buckets, tenant/route policy, multi-replica abuse tests and production rejection of local mode. |
| P2-P0-06 | Qdrant production runtime | `PARTIAL` | Qdrant vector/backend adapters and ACL filter contracts | Live collection/schema/migration/alias/reindex/partial-failure evidence and wiring. |
| P2-P0-07 | Private S3-compatible object storage | `PARTIAL` | `ObjectStore`, local and S3-compatible adapters with checksum/limits | Composition, private auth, streaming/retention/delete policy and authorized integration. |
| P2-P0-08 | Durable ingestion `UPLOAD→VERIFY→PUBLISH` | `PARTIAL` | Local journal, lineage fields, bounded worker and lifecycle routes | External DB/object/vector transaction choreography, version retention and recovery drill. |
| P2-P0-09 | Canonical API/Web/Worker/Redis/Qdrant/Object root stack | `PARTIAL` | Compose reference/integration files, Dockerfiles, static checks | `make up`/health/smoke/teardown on disposable services; no unsafe defaults. |
| P2-P0-10 | Container hardening and reproducible images | `PARTIAL` | Multi-service Dockerfiles, release manifest and static checks | Digest pinning, non-root/read-only verification, vulnerability/SBOM/signature evidence. |
| P2-P1-01 | Core hybrid retrieval with authorization and evidence | `PARTIAL` | `packages/retrieval`, ACL tests, local eval and provenance contracts | Live projection/freshness/latency and integrated citation verification. |
| P2-P1-02 | Query analysis and feature-flagged advanced retrieval | `MISSING` | No complete evaluated decomposition/multi-query/HyDE/MMR subsystem | Add one strategy at a time with baseline delta and safe flags; no hype promotion. |
| P2-P1-03 | Confidence semantics/calibration | `PARTIAL` | Existing retrieval quality/confidence fields and local scoring | Ensure non-probabilistic scores are named honestly; calibration dataset/Brier/ECE is P2. |
| P2-P1-04 | Formal Evidence/EvidenceBundle/EvidenceValidator | `PARTIAL` | Evidence DTOs and Professor evidence gates | One server-generated bundle/validator contract across retrieval, provider and API. |
| P2-P1-05 | Citation verification and unsupported-claim policy | `PARTIAL` | Citation metadata and weak/no-evidence local states | Claim-to-text support checks, precision/recall/completeness and abstain/retrieve-again path. |
| P2-P1-06 | Explicit intelligence decision layer | `MISSING` | Decision behavior is distributed through local orchestration/routes | Add `ANSWER`, `RETRIEVE_AGAIN`, `ASK_FOR_CLARIFICATION`, `ABSTAIN`, `ESCALATE` contract and tests. |
| P2-P1-07 | Professor reasoning plane | `PARTIAL` | `packages/professor` evidence-gated orchestration and provider adapter | Separate retrieval/reasoning/tool/response/citation/verification budgets at public boundary. |
| P2-P1-08 | Common resilient provider contract | `PARTIAL` | Typed provider, OpenAI-compatible adapter, deterministic provider and resilience | Complete capabilities/health/cancellation/streaming/limits and live failure matrix. |
| P2-P1-09 | Local OpenAI-compatible model support | `PARTIAL` | Provider endpoint configuration and compatibility route | Capability negotiation and disposable llama.cpp/vLLM/Ollama-compatible test. |
| P2-P1-10 | End-to-end multi-tenancy | `PARTIAL` | Tenant-aware identity/authorization/retrieval/local storage negatives | External DB/object/vector/job/audit/cache/rate-limit cross-tenant matrix. |
| P2-P1-11 | Formal threat model | `MISSING` | Existing security decisions and route/file tests | Create `docs/security/threat-model.md` with assets, actors, trust boundaries, abuse cases and residual risk. |
| P2-P1-12 | RAG security | `PARTIAL` | ACL and prompt/evidence boundaries in local Professor/retrieval paths | Adversarial corpus, untrusted-data policy, poisoning/exfiltration/tool-injection negatives. |
| P2-P1-13 | File-ingestion security | `PARTIAL` | Bounded uploads, MIME/path/size checks and object-store negatives | Magic bytes, archive/page/decompression limits, parser timeout/isolation and malicious corpus. |
| P2-P1-14 | Distributed observability | `PARTIAL` | Redacted events, correlation IDs, local metrics and bounded spans | OTel-compatible traces/metrics/logs through API/retrieval/provider/worker/storage/Redis/Qdrant. |
| P2-P1-15 | SLI/SLO and alert definitions | `MISSING` | Local metrics and runbooks, no canonical `docs/operations/slo.md` | Define local/staging/production SLOs, burn alerts and collector evidence. |
| P2-P1-16 | Disaster recovery and restore drills | `PARTIAL` | File-level backup/reconciliation contract and runbook | Service-level backup/restore, RPO/RTO and tenant-negative smoke on isolated restore. |
| P2-P1-17 | Canonical CI/CD quality lanes | `PARTIAL` | Phase workflows and release-integrity workflow | Add one laneed quality workflow, artifact retention, timeouts, permissions and drift checks. |
| P2-P1-18 | `app.py` composition root/API contract | `PARTIAL` | `create_app`, middleware/routes/lifecycle and OpenAPI checks | Keep composition root thin, deterministic OpenAPI, contract/error/permission/idempotency examples. |
| P2-P1-19 | Critical-operation idempotency | `PARTIAL` | Upload/reindex/delete/job/case idempotency slices and tests | Complete external transactional idempotency and replay semantics for all critical mutations. |
| P2-P1-20 | Frontend AAA workflow | `PARTIAL` | Next.js shell, chat/documents/cases/admin routes and Playwright matrix | Live API states, focus/recovery/slow backend/stream interruption and full permission journeys. |
| P2-P1-21 | Visual evidence and accessibility | `PARTIAL` | Existing visual artifacts, responsive tests, axe/reduced-motion local checks | Fresh complete matrix at 375/768/1440, native renders, independent critic and no unresolved High. |
| P2-P1-22 | Reproducible performance benchmark | `PARTIAL` | Phase 1.5/1.6 local benchmarks and web timings | API/retrieval/provider/worker p50/p95/p99 at declared workloads; separate production status. |
| P2-P1-23 | Soak test | `MISSING` | No current prolonged continuous runtime artifact | Add bounded isolated soak with leak/queue/latency observations. |
| P2-P1-24 | Chaos/fault injection | `MISSING` | Static failure contracts exist; no runtime drill | Add kill/restart/timeout/storage/provider partial-failure tests with recovery evidence. |
| P2-P1-25 | RAG evaluation harness | `PARTIAL` | `docs/evaluation/packs`, retrieval evaluator and local baseline | Add complete answer/citation/abstention metrics and CI regression against approved data. |
| P2-P1-26 | Veterinary golden-set framework | `PARTIAL / BLOCKED_EXTERNAL` | Safe non-clinical pack schema and clinical boundary | External domain owner/corpus/licence/thresholds are required for clinical evidence. |
| P2-P1-27 | Clinical safety boundary | `PARTIAL` | Closed-by-default case route and risk-aware documentation | Keep high-risk policies conservative; domain approval and corpus evidence remain open. |
| P2-P1-28 | Append-oriented auditability | `PARTIAL` | Local audit/redaction/retention and API context contracts | Durable external sink, mutation/audit transaction coupling and retention/restore evidence. |
| P2-P1-29 | Independent reviews | `PARTIAL` | Prior fresh I1 critics for local slices and review controller | Obtain fresh architecture, security, retrieval, ingestion, runtime, observability, web and operations reviews. |
| P2-P1-30 | Documentation AAA set | `PARTIAL` | Architecture/operations/evaluation/plans exist in part | Add missing canonical docs and bind each to current code/evidence. |
| P2-P2-01 | Advanced retrieval experiments | `MISSING` | No accepted evaluated strategy | Begin only after P0 durability and P1 baseline/eval gates pass. |
| P2-P2-02 | Confidence calibration | `MISSING` | No calibration dataset or reliability artifact | Begin only with approved labelled dataset and risk policy. |
| P2-P2-03 | Frontend polish and developer experience | `PARTIAL` | Existing token system and workflows | Polish after runtime states are stable; do not hide missing operational data. |
| P2-P2-04 | Additional providers | `PARTIAL` | OpenAI-compatible boundary exists | Add only when capability/health/cost/error contract justifies it. |
| P2-G01 | Quality target scorecard | `MISSING / BLOCKED_EXTERNAL` | Historical local candidate scores, explicit limitations | Recompute only from current evidence; no overall `>=96` claim until required gates pass. |
| P2-G02 | State-of-Art promotion gates | `PARTIAL / BLOCKED_EXTERNAL` | Release-integrity and local gates exist | Production-like, distributed, durability, recovery, corpus and independent gates remain. |
| P2-G03 | Final Phase 2 report | `MISSING` | No final report for this phase | Generate only after the exit audit with tests, eval, perf, chaos, restore and scorecard results. |

## 11. Priority and dependency graph

```text
P2.0 audit + bar + plan
       │
       ▼
P2.1 job contracts ──> P2.2 PostgreSQL queue/runtime ──> P2.3 worker composition
       │                         │                         │
       ├─────────────────────────┴──────────────┬──────────┘
       ▼                                        ▼
P2.4 Redis/rate limit                 P2.5 object store/Qdrant
       └──────────────────────┬─────────────────┘
                              ▼
                       P2.6 durable ingestion
                              ▼
                       P2.7 canonical root stack
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
       P2.8 observability  P2.9 security   P2.10 recovery/chaos
              │               │                │
              └───────────────┴────────────────┘
                              ▼
              P2.11 evidence/decision/evals/retrieval
                              ▼
              P2.12 web/CI/performance/promotion
```

P2.1–P2.7 are P0. No P2 experiment is promoted before the P0 runtime and
canonical stack gates are current. P1 lanes may proceed in parallel only when
their shared contracts are frozen and their writers have disjoint ownership.

## 12. Implementation slices

Each slice is a separate Gauntlet round with a builder artifact, focused test,
fresh critic, regression surface and evidence manifest. A slice reaches
`IMPLEMENTED` when its artifact and raw evidence exist; only the Lead and the
applicable independent gate can move it to `VERIFIED` or `DONE`.

### Phase 2.1 — Durable Job Contracts

- **Scope:** create or consolidate the canonical jobs package/protocol without
  deleting `apps/worker` local adapters; define state, attempt, result, failure,
  lease, repository, queue, executor and scheduler contracts.
- **Implementation:** stable serialized job envelope; tenant/workspace/
  collection scope; idempotency/deduplication keys; retry/backoff and poison
  policy; capability-bearing lease; cancellation and shutdown semantics.
- **Tests:** known-good/known-bad state transitions, duplicate enqueue,
  lease-owner rejection, expiry, retry exhaustion, cancellation, malformed
  payload and serialization compatibility.
- **Evidence/review:** package contract manifest, local adapter parity report,
  independent runtime critic; no production claim yet.
- **Gate:** `P2-P0-01 PASS`, with local implementation clearly marked as
  development/test where it cannot prove distribution.

### Phase 2.2 — Durable PostgreSQL Queue and Migrations

- **Scope:** make the existing PostgreSQL queue and migrations a complete
  bounded adapter for the contract, including transactional outbox/audit
  coupling where required.
- **Implementation:** migration checksum/lock, constraints and indexes,
  owner-safe claims, `FOR UPDATE SKIP LOCKED` or an equivalent reviewed
  strategy, recoverable expiry, dead-letter/replay tooling and retention.
- **Tests:** migration from empty/prior versions, history divergence, FK
  cross-scope rejection, concurrent claim, duplicate delivery, crash before/
  after commit and replay.
- **Gate:** disposable PostgreSQL integration PASS; otherwise `BLOCKED_EXTERNAL`.

### Phase 2.3 — Real Worker Runtime

- **Scope:** compose `apps/worker` with the durable queue, handler registry,
  startup validation, readiness/liveness, bounded concurrency, heartbeat,
  cancellation and graceful shutdown.
- **Tests:** crash/restart/resume, expired lease, two workers, cancellation,
  handler timeout, backpressure, poison job and shutdown during processing.
- **Gate:** worker runtime and queue evidence agree on every status and failure;
  local worker remains accepted only in local/test mode.

### Phase 2.4 — Redis Coordination and Distributed Rate Limits

- **Scope:** shared Redis client policy, locks/leases/heartbeats/ephemeral
  coordination and Redis-backed rate limiting.
- **Tests:** reconnect, timeout, auth/TLS config rejection, namespace/tenant
  key isolation, atomic bucket behavior, burst/multi-replica abuse, degraded
  health and local fallback rejection in production.
- **Gate:** all production security routes use the distributed interface and
  readiness fails closed when Redis is required and unavailable.

### Phase 2.5 — Object Storage and Qdrant Runtime

- **Scope:** private S3-compatible object lifecycle and production-capable
  Qdrant adapter with schema/version/alias/reindex health.
- **Tests:** checksum, streaming bounds, private scope, delete/retention,
  malformed payload, timeout/retry/circuit behavior, tenant filters, partial
  index failure, alias swap and zero-downtime rebuild fixture.
- **Gate:** storage/vector health and recovery evidence are current and bound to
  the exact runtime configuration.

### Phase 2.6 — Durable Ingestion

- **Scope:** persist every stage and lineage field from upload to publish;
  publish only after object/chunk/vector verification; preserve prior version
  on failure.
- **Tests:** idempotent upload/retry, parser failure, embedding failure,
  index failure, duplicate delivery, cancellation, reindex, delete, replay,
  crash at each boundary and wrong-tenant access.
- **Gate:** API→queue→worker→storage/vector→verification→catalog public path
  passes on disposable services.

### Phase 2.7 — Canonical Root Runtime Composition

- **Scope:** provide guarded `docker-compose.dev.yml` and
  `docker-compose.staging.yml` or an equivalent root boundary for API, web,
  worker, Redis, Qdrant, PostgreSQL, object storage and observability.
- **Tests:** environment validation, image/user/filesystem checks, health,
  readiness, seeded synthetic fixtures, smoke, teardown and no-secret scans.
- **Gate:** `make up` is no longer a placeholder only after the compose stack
  has a disposable runtime evidence packet.

### Phase 2.8 — Distributed Observability and SLO

- **Scope:** OTel-compatible traces/metrics/logs with safe propagation of
  request/correlation/trace/job/document/tenant/workspace identifiers.
- **Tests:** span coverage, redaction, collector unavailable, sampling,
  queue/provider/retrieval/ingestion latency and error counters; SLO fixtures.
- **Gate:** `docs/operations/slo.md`, dashboards/alerts and a bounded collector
  drill exist; production SLO remains distinct from local benchmark.

### Phase 2.9 — Security and RAG Safety

- **Scope:** threat model, external identity boundary, distributed abuse
  controls, file/parser limits, untrusted-corpus policy and adversarial tests.
- **Tests:** authorization matrix, tenant negatives, SSRF/path/archive/prompt
  injection/retrieval poisoning/tool injection/secret/log leakage/rate bypass.
- **Gate:** fresh security review and no open Critical/High finding in the
  declared scope; unresolved external evidence remains blocked.

### Phase 2.10 — Recovery, Soak and Chaos

- **Scope:** service-level backup/restore, RPO/RTO, controlled fault injection,
  continuous load and rollback/canary runbooks.
- **Tests:** Redis/Qdrant/provider/storage/worker/network faults, restore into
  isolated target, checksum/ACL reconciliation, queue growth and memory/leak
  observations.
- **Gate:** raw drills and manifests exist; static runbooks alone do not pass.

### Phase 2.11 — Evidence, Decision and Evaluation

- **Scope:** formal EvidenceBundle/validator, claim-to-citation verification,
  decision layer, Professor budget/failure contract, baseline RAG eval and safe
  veterinary fixture framework.
- **Tests:** unsupported claim, missing evidence, weak retrieval, clarification,
  abstention, escalation, citation precision/recall/completeness, ACL leakage,
  answer relevance and abstention accuracy.
- **Gate:** no model-generated evidence IDs; no high-risk clinical claim without
  the required evidence and approved domain policy.

### Phase 2.12 — Web, CI and Promotion

- **Scope:** complete API-backed web states, keyboard/focus/accessibility,
  responsive/visual matrix, CI lanes, release evidence and final scorecard.
- **Tests:** 375/768/1440 screenshots and interactions, axe/Lighthouse where
  available, Playwright full states, contract drift, performance, eval,
  security, recovery and fresh independent visual/integration critics.
- **Gate:** every mandatory promotion criterion is current and independently
  rejectable; otherwise final verdict is `CONDITIONAL PASS` or `FAIL`.

## 13. Verification strategy

### Frozen quality bar

The prompt is the `USER` source of required criteria. Existing repository
contracts and ADRs are `REPO` constraints. Operational/security requirements
are `DERIVED` only when tied to a named trust boundary and evidence method.
The following required gates are frozen for Phase 2:

| Bar ID | Required target | Evidence method | Priority |
| --- | --- | --- | --- |
| BAR-P0-RUNTIME | Production composition rejects local-only durability and handles queue/worker restart, lease loss, retry, cancellation and DLQ safely | Disposable runtime tests plus failure drill on the public API/worker path | P0 |
| BAR-P0-SCOPE | Every durable read/write and retrieval operation enforces tenant/workspace/collection/actor scope | Positive and negative API/DB/object/vector/job/audit matrix | P0 |
| BAR-P0-INGEST | Upload through publish is durable, idempotent, versioned, lineage-preserving and recoverable | End-to-end integration and crash/replay matrix | P0 |
| BAR-P0-STACK | Canonical root stack starts with pinned, non-root, secret-free services and reports truthful health/readiness | Compose static and disposable smoke evidence | P0 |
| BAR-P1-SECURITY | Threat model controls, RAG/file defenses, rate limits, audit redaction and fail-closed behavior hold | Adversarial tests plus fresh security review | P0 |
| BAR-P1-EVIDENCE | Evidence is server-generated, scope-bound, checksum/version-bound and citation support is validated | Known-good/known-bad citation and abstention harness | P0 |
| BAR-P1-OBS | Trace/metric/log context crosses API, retrieval, provider, Professor, worker and dependencies without sensitive leakage | Collector fixture, redaction tests and SLO artifacts | P1 |
| BAR-P1-RECOVERY | Backup/restore, restart, rollback, soak and controlled faults preserve integrity and report bounded failure | Isolated drills with checksums, RPO/RTO and raw logs | P0 |
| BAR-P1-EVAL | RAG baseline and regression metrics are reproducible and distinguish known-good from known-bad answers | Versioned safe pack and CI evaluator | P0 |
| BAR-P1-WEB | Critical web workflows remain usable, accessible, responsive and recoverable at 375/768/1440 | Native screenshots, interaction matrix, axe/Lighthouse and fresh critic | P1 |
| BAR-RELEASE | Release evidence is exact, current, complete and bound to the integrated artifact | Release checker, manifests, dependency/secret/SBOM scans | P0 |
| BAR-REVIEW | Architecture, security, retrieval, ingestion, runtime, observability, web and operations receive fresh read-only review | Sealed packets, mutation sentinels and criterion-level verdicts | P0 |

Harness validation must include at least one known-bad fixture for each
blocking evaluator. A producer's `passed` flag, a static file, a stale report,
or a self-authored score cannot establish a gate.

### Round loop

```text
baseline → hypothesis → smallest coherent change → public-path run
→ focused tests → fresh critic → mutation sentinel → regression
→ evidence manifest → integration review → next largest gap
```

Builders own implementation. Critics receive a sealed packet without builder
rationale or previous scores and must not edit the artifact or state. The Lead
is the only writer for `.agent`, `.gauntlet` and integrated verification state.
Fresh agent review is `I1` in this host unless a distinct externally owned
deterministic gate or qualified human reviewer raises the level. No I1 result
is mislabeled as human or production approval.

### Visual evidence

The web acceptance packet must bind route, state, viewport, DPR, browser,
artifact hash, screenshot hash, interaction result, console/network result and
critic packet. It must cover login, shell, chat, sources, documents, upload,
job status, error/recovery, admin and mobile states. Missing browser capability
is `NOT_RUN`/`BLOCKED`, never a visual pass.

## 14. Promotion gates

### Local candidate

The local candidate can be promoted only when architecture, unit, contract,
integration, security negatives, RAG evaluation, frontend E2E/visual, release
integrity and independent review are current for the same integrated artifact.

### Triple-A candidate

The additional required gates are production-like runtime, distributed queue and
rate limit, durable storage/ingestion, restore drill, operational recovery,
external corpus evidence, performance/soak/chaos, and fresh reviews across all
macro areas. The scorecard must report missing or blocked items rather than
averaging them away.

No target score is assigned in this plan. The requested approximate targets
remain an exit aspiration; each dimension is scored only from current evidence
with its denominator and confidence. A score below target or a blocked P0
keeps the verdict out of `PASS`.

## 15. Rollback strategy

- Preserve the prior application image and API compatibility surface.
- Roll forward migrations when external writes exist; do not assume code
  rollback preserves newer rows or objects.
- Stop new job writers before queue/schema rollback; let owned leases expire or
  explicitly cancel them with audit events.
- Keep prior published document versions and Qdrant aliases until the new index
  passes verification; switch aliases atomically and restore the previous alias
  on failure.
- Keep immutable object versions until retention policy and restore evidence
  permit deletion.
- Roll back feature flags for experimental retrieval, provider and UI states
  without silently falling back to an unsafe provider or cross-tenant scope.
- Reconcile PostgreSQL, object, Qdrant, audit and job counts/checksums after
  any recovery. Counts alone do not prove authorization or content integrity.
- Legacy caller switches remain explicit and reversible under ADR-020.

## 16. Risk register

| Risk | Impact | Treatment | Trigger |
| --- | --- | --- | --- |
| External service unavailable | P0 evidence cannot be proven | Build adapters and isolated fakes; mark live gates blocked | Any required runtime check cannot execute |
| Cross-tenant data leak | Critical security/data harm | Server-derived scope, DB constraints/RLS, negative matrix, fresh review | Any missing predicate, FK or cache key |
| Duplicate or lost job | Silent data corruption or missed ingestion | Idempotency key, owner lease, transactional state, replay/drill | Crash/timeout between stages |
| Qdrant projection drift | Incorrect or unauthorized retrieval | Versioned schema, alias, rebuild and reconciliation | Counts/checksum/ACL mismatch |
| Provider/prompt injection | Unsupported or unsafe response | Untrusted corpus policy, evidence validator, decision abstention | Unsupported claim or instruction in corpus |
| Parser/resource exhaustion | Availability/security incident | Magic bytes, bounds, isolation, timeout, malicious corpus | Oversized/archive/malformed input |
| Audit/telemetry leakage | Sensitive data exposure | Redaction allowlist and collector tests | Raw prompt/token/DSN in artifact or log |
| Visual polish hides missing truth | Product misuse | Real states, no fake metrics/placeholders, independent visual review | Missing runtime state presented as success |
| Stale evidence after integration | False promotion | Fingerprints, manifests, freshness checker and final critic | HEAD/artifact/contract changes |
| Legacy regression | Compatibility break | Preserved children, differential tests, explicit caller switch | Existing regression or boundary drift |

## 17. Exit criteria

Phase 2 is complete only when all of the following are current for the same
integrated candidate:

1. No P0 capability is `MISSING`, `BLOCKED`, `NOT_RUN`, `STALE` or merely
   local-only when its target is production runtime.
2. The worker and queue survive duplicate delivery, lease expiry, restart,
   cancellation, bounded retry and dead-letter/replay tests.
3. Redis rate limits and coordination are distributed, tenant-safe and required
   in production mode; Qdrant and object storage are wired and recoverable.
4. Ingestion persists lineage and publication state and preserves the last
   verified version through failures.
5. Threat model, RAG/file security, external identity, tenancy negatives and
   audit/redaction evidence pass their declared gates.
6. Distributed observability, SLOs, backup/restore, RPO/RTO, soak and chaos
   evidence are executed or are explicitly accepted as an external authority
   decision; missing required evidence keeps the promotion blocked.
7. Evidence/citation/decision/evaluation gates reject unsupported answers and
   produce truthful abstention, clarification, retry or escalation outcomes.
8. Web critical workflows pass accessible responsive interaction and fresh
   visual review at the declared breakpoints/states.
9. CI/CD lanes, release integrity, SBOM/secret/dependency scans and rollback
   procedures are current and reproducible.
10. Independent reviews across architecture, security, retrieval, ingestion,
    runtime, observability, web and operations find no unresolved Critical or
    High issue.
11. `docs/progress/phase-2-final-report.md` contains the required 18 sections,
    exact test/evaluation/performance/chaos/restore results, blocked external
    evidence, residual risks, promotion recommendation and final scorecard.

Until these criteria are met, the honest status is `ACTIVE`, `CONDITIONAL`
or `BLOCKED_EXTERNAL` by criterion, never “State of Art / Triple AAA”.

## 18. Immediate next action

The audit/bar is now frozen for the current candidate. The next implementation
unit is **Phase 2.1 — Durable Job Contracts**, owned sequentially because the
job state and serialized envelope are shared by the queue, worker, ingestion,
observability and API. Its completion must be followed by an independent
contract/runtime critic before Phase 2.2 begins.
