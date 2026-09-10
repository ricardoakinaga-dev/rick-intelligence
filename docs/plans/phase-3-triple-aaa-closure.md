# Phase 3 Triple AAA Closure Plan

**Status:** `ACTIVE — local release hardening complete; live runtime evidence blocked`
**Prompt:** [`phase-3-triple-aaa-closure-2026-09-09.txt`](../prompts/phase-3-triple-aaa-closure-2026-09-09.txt)  
**Source attachment SHA-256:** `0d431cf3ec75e4d6455735d32f135b3270b59996866a28fd7296d73a18cabf3d`  
**Stored copy SHA-256:** `0d431cf3ec75e4d6455735d32f135b3270b59996866a28fd7296d73a18cabf3d`
**Candidate:** `ca54b4ab9db1f39f94a14ad600f690d438cd144b` / tree `354485c5e88aacf9b9217cc92b6d87c68e60bfbc`
**Entry audit:** [`current-triple-aaa-gap-audit.md`](../reports/current-triple-aaa-gap-audit.md)

## 1. Outcome and constraints

Transform RICK Intelligence from `STATE_OF_ART_CANDIDATE` into a platform
that is proven distributed, durable, secure, multi-tenant, observable,
recoverable, resilient, reproducible, auditable, evidence-grounded and
production-grade. The final status is calculated from current evidence; it is
never promoted by prose or score.

Preserve the brownfield architecture, explicit contracts/adapters,
differential verification, durable jobs, legacy repositories, frozen quality
bar and append-only control-plane history. Do not perform a general rewrite,
use fake transports for runtime promotion, weaken thresholds, remove tests,
fabricate evidence/reviewers, change host permissions, use production data,
contact paid providers or deploy without the required authority.

## 2. Frozen definition of done

The program is complete only when the entry audit is reconciled, exact clean
SHA has current CI and release evidence, every P0/P1 runtime/product/operation
row in the audit matrix is `PASS`, real PostgreSQL/Redis/Qdrant/S3-compatible
services and Worker A/B have passed, the golden path and tenant/evidence
negatives have passed, provider/citation/decision/budget and OTel evidence are
current, DR/restore/chaos/soak/performance/frontend/accessibility/supply-chain
evidence is current, zero Critical/High findings remain, all named independent
reviews have attempted rejection, and a sealed packet has an authorized final
Go/No-Go for the same candidate.

The final scorecard has the prompt's 25 dimensions, with overall score at
least 96 as an advisory threshold. A score cannot override a mandatory
blocker. `TRIPLE_AAA` is not declared while any required evidence is missing,
blocked, stale or unreviewed.

## 3. Evidence contract

Each slice must produce:

- scope and explicit non-goals;
- implementation artifact and rollback/recovery procedure;
- focused tests and credible regression checks;
- exact commit/tree and artifact hashes;
- runtime evidence or explicit `BLOCKED_EXTERNAL`/`NOT_RUN` record;
- reviewer identity, independence and mutation sentinel;
- gate result, limitations, next action and revalidation trigger.

Raw runtime output is sanitized and hashed before it enters a packet. A sealed
packet is immutable: any byte, candidate, tree, environment, reviewer or gate
change creates a new run and invalidates the prior promotion decision.

## 4. Dependency graph and slices

The lead owns shared contracts, control-plane writes and integration. Parallel
work is allowed only for disjoint read-only investigations or disjoint source
files after the contract is frozen. Builders return `IMPLEMENTED`; fresh
critics decide `APPROVE`, `REJECT`, or `BLOCKED`.

| Slice | Scope | Non-goals | Implementation | Tests | Runtime evidence | Rollback | Critic | Gate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 3.1 Control / CI closure | Prompt binding, README truth, CI lanes, release schema, automatic status | No runtime promotion | Update docs/workflow/verifier contracts and rejection tests | State-of-art suite, workflow checks, known-bad fixtures | Current clean-SHA local packet; remote CI if available | Revert docs/workflow/verifier commit | Fresh release/control critic | `CONTROL_RELEASE_PASS` |
| 3.2 Disposable lab | Compose topology, env validation, readiness, diagnostics and safe teardown | No use of host-owned services | Guarded start/health/readiness/endpoints/down | Compose render/lifecycle tests | Real API/Web/Worker A/B/OTel service evidence | Owned project teardown; preserve volumes unless explicitly scoped | Fresh runtime critic | `LAB_READY` |
| 3.3 PostgreSQL + workers | Migrations, queue, leases, fencing, crash matrix | No fake DB or single-process substitution | Execute the PostgreSQL gate plus `multi_worker_runtime_gate.py` with two spawned processes, heartbeat, crash/reclaim and stale-ACK negatives | SQL/migration, concurrency and recovery suite | Real DSN, two workers, attempt/outbox/audit evidence | Roll-forward or isolated restore | DB/runtime critics | `POSTGRES_WORKERS_PASS` |
| 3.4 Redis replicas | Redis config, lease, heartbeat, rate limit and API A/B | No local in-memory fallback | Run shared Redis gate and replica harness | Locking, reconnect, namespace and bypass negatives | Real Redis auth/TLS/replica evidence | Restart owned Redis; preserve evidence | Redis/security critic | `REDIS_REPLICA_PASS` |
| 3.5 Object + Qdrant | Object lifecycle, checksums, tenant scope, projection/alias/rebuild | Qdrant is never authority | Run real storage/vector gate and failure paths | checksum, filter, alias and restore tests | S3-compatible and Qdrant envelopes | Rebuild projection from verified authority | storage/retrieval critic | `STORAGE_VECTOR_PASS` |
| 3.6 Golden ingestion | `RICK_GOLDEN_RUNTIME_PATH`, idempotency, lineage and publish safety | No unapproved corpus or provider | Run real upload-to-decision path with synthetic approved fixture | all declared ingestion fault boundaries | Full trace/state/lineage/evidence packet | Restore last verified document version and replay | ingestion/RAG critic | `GOLDEN_PATH_PASS` |
| 3.7 Tenant / evidence security | Tenant A/B isolation, server IDs, forged/stale/hash/chunk negatives | No relaxed ACL for diagnostics | Exercise all stores, cache, audit and response paths | adversarial tenant/evidence matrix | Real cross-tenant negative evidence | Revoke fixture identities and delete only owned data | security critic | `TENANT_EVIDENCE_PASS` |
| 3.8 Provider / citation | Controlled OpenAI-compatible runtime, citation metrics and decision policies | No paid/unbounded calls | Execute bounded provider/citation/budget matrix | 429/500/timeout/cancel/tool/JSON and adversarial RAG | Provider trace + approved corpus packet | Disable provider route and use explicit abstention | provider/RAG critic | `PROVIDER_CITATION_PASS` |
| 3.9 Observability | OTel propagation, redaction, metrics, alerts and SLO separation | No inferred production SLO | Wire and observe collector/backend and safe dimensions | redaction/propagation/metric-cardinality tests | HTTP-to-decision traces and alert/SLO artifact | Stop exporter; preserve local bounded diagnostics | observability critic | `OBSERVABILITY_PASS` |
| 3.10 DR / restore | Seed, backup, destroy, restore, rebuild and verify | No production destruction | Run isolated service restore and reconciliation | checksum/count/ACL/lineage/replay checks | RPO/RTO and operator evidence | Restore previous isolated checkpoint | recovery critic | `RESTORE_PASS` |
| 3.11 Chaos | Worker, Redis, Qdrant, Postgres, S3, provider and network faults | No uncontrolled host fault injection | Inject only in owned disposable project | fault matrix and duplicate/corruption checks | failure traces, state and recovery packet | Restore services from owned checkpoint | chaos critic | `CHAOS_PASS` |
| 3.12 Soak / performance | short/extended soak and 1/10/50/100 concurrency | No production benchmark claim from local fixture | Run declared workloads and budgets | metric integrity and tail-distribution checks | environment-bound p50/p95/p99/throughput/CPU/RAM | stop workload and retain raw data | operations/performance critic | `SOAK_PERF_PASS` |
| 3.13 Frontend / accessibility | real API browser states at 375/768/1440 and visual QA | No source-only visual approval | Run route/state matrix, axe/keyboard/focus/contrast/reduced motion | browser/e2e plus frontend quality packet | native screenshots, interaction and console/network evidence | revert scoped UI change | fresh design critic | `FRONTEND_A11Y_PASS` |
| 3.14 Supply chain | dependencies, secrets, containers, SBOM, license and digest | No scanner-only security claim | Run available scanners and bind outputs | known-bad scan fixtures and Dockerfile checks | immutable scan/SBOM/signature packet | revoke artifact and use prior digest | supply-chain critic | `SUPPLY_CHAIN_PASS` |
| 3.15 Independent review | architecture, security, runtime, DB, observability, recovery, RAG, frontend, operations | No builder self-approval | Commission fresh blind packets | reviewer mutation sentinels and criterion coverage | current review reports bound to candidate | rework and open gate | distinct fresh critics | `INDEPENDENT_REVIEW_PASS` |
| 3.16 Promotion | scorecard, packet seal, final Go/No-Go | No status by documentation | Derive classification and require exact authority | all negative/anti-gaming paths | sealed packet + final decision | no deployment; retain candidate for rework | fresh final critic | `TRIPLE_AAA_PASS` |

P2 advanced retrieval/calibration is explicitly deferred until 3.16 has no
open P0/P1 blockers.

## 5. Automatic classification

The promotion engine must calculate, never accept as input, one of:

`DEVELOPMENT → ADVANCED_ENGINEERING → STATE_OF_ART_CANDIDATE → STATE_OF_ART → AAA → TRIPLE_AAA`.

`STATE_OF_ART` requires architecture, security, contracts, unit, integration,
core runtime, observability and release integrity. `AAA` adds live data
services, workers, tenants, golden ingestion, DR, performance, frontend,
accessibility, supply chain and independent review. `TRIPLE_AAA` adds chaos,
soak, restore, distributed failure, production-like runtime, zero Critical/
High, sealed packet and final independent Go/No-Go. Any required non-PASS
short-circuits to the appropriate lower classification and maps to exit `2`
when the cause is external blocking, otherwise exit `1`.

## 6. Current risks and authority boundaries

| Risk | Treatment | Evidence needed | Authority |
| --- | --- | --- | --- |
| False promotion from stale/forged evidence | Typed exact-SHA/tree/hash validation, immutable sealing and negative tests | Current known-good/known-bad manifest probes | Lead + fresh release critic |
| Cross-tenant disclosure | Enforce scope at identity, stores, retrieval, evidence, decision, logs and timing | Tenant A/B runtime negatives | Security authority if residual risk remains |
| Data loss/duplicate publication | Durable authority, idempotency, fencing, outbox and restore | Real crash/replay/restore packet | DB/recovery owner |
| Secret leakage in logs/traces | Redact before persistence and test nested/escaped forms | Raw sanitized artifact and adversarial tests | Security owner |
| Unbounded provider/corpus use | Explicit endpoint, budget, fixture and cancellation controls | Provider/citation budget packet | Provider/corpus authority |
| Host/runtime mutation | Use owned disposable project and abort conditions | Compose ownership and teardown evidence | Operations owner |
| Visual/accessibility regression | Native viewport/state renders and fresh independent review | Browser packet and visual ledger | Design/UX reviewer |

## 7. Recovery and reporting

Every interrupted slice is recovered from actual Git, process, artifact and
service state. Previous failures stay in append-only history. A later pass does
not erase an unexplained failure; it creates a new exact run. The final report
must contain the prompt's 28 sections, 25-dimension scorecard, all mandatory
gate results, remaining risks and a single executable next action.

The current next action is to execute the disposable Compose/runtime gates from
this clean candidate when an approved Docker daemon, disposable secrets and
endpoints are available. The authenticated packet correction is locally tested
and remains fail-closed; it does not substitute for live Redis/API,
PostgreSQL, storage, provider, observability, frontend, operations or human
promotion evidence.

## 8. Current local correction — authenticated promotion packet

An independent challenge found that the former packet seal was a recalculable
digest and allowed self-declared authority. The correction introduces a
versioned Ed25519 seal, an explicit public-key trust store, full seal-metadata
coverage, current-checkout binding and a 24-hour freshness window. Unknown
keys, missing trust, stale/future timestamps, mutated metadata and absent
checkout binding remain non-promotable. The local State-of-Art suite now has
264 passing tests; this does not close live runtime or human promotion gates.
