# RICK Intelligence — Triple AAA Promotion Report

**Report state:** `DIAGNOSTIC / NO-GO / NOT SEALED`  
**Promotion claim:** none  
**Decision rule:** this report is descriptive until the automatic verifier
binds a current clean candidate, current evidence and an authorized decision.

## 1. Executive decision

The current program is not promoted. Local source, control and static checks
are useful, but unavailable disposable services, runtime evidence, current
independent reviews and human authority keep the candidate below `TRIPLE_AAA`.

## 2. Candidate identity

The exact commit, tree, checkout fingerprint and artifact-set digest must be
read from the same-run packet at
`.runtime/phase-3/triple-aaa-verify.json`. This report never substitutes a
manually typed SHA and is invalid if the packet is absent, stale or dirty.

## 3. Prompt provenance

Requirements are bound to the stored closure prompt and its recorded source
attachment hash in `docs/reports/current-triple-aaa-gap-audit.md` and
`docs/reports/current-triple-aaa-quality-bar-v1.json`. The stored copy's
normalized final newline is explicitly documented; it is not represented as
byte identity with the attachment.

## 4. Frozen quality bar

The twelve-criterion bar in `current-triple-aaa-quality-bar-v1.json` is the
minimum acceptance contract. Its baseline statuses remain `NOT_RUN` or
runtime-blocked until current evidence satisfies the declared method.

## 5. Scope and non-goals

The scope is the root RICK platform and its API, web, worker, contracts,
storage, retrieval, provider, evidence, decision, observability, operations,
CI and release boundaries. The three preserved child repositories remain
compatibility surfaces. No production data, host-owned service, paid
provider, credential, destructive operation or permission change is in scope
for local verification.

## 6. Architecture and authority

Durable metadata and jobs remain authoritative; Redis coordinates, object
storage holds immutable bytes, Qdrant is a rebuildable projection, and the
evidence/decision layer is the authority for supported responses. Every
protected boundary must carry tenant/workspace scope and server-derived IDs.

## 7. CI and release lanes

The canonical workflow names FAST, UNIT, CONTRACT, SECURITY, RAG_EVAL,
FRONTEND, SUPPLY_CHAIN and RELEASE. Runtime-heavy lanes are conditional or
scheduled, but a skipped lane remains non-promotable. The release job must
consume same-run, commit-bound artifacts and return `1` or `2` rather than
silently skipping an unmet gate.

## 8. Disposable production-like lab

The lab target is Postgres, Redis, Qdrant, S3-compatible object storage, API,
Worker A/B, Web and OTel/metrics. Compose start must validate configuration,
wait for health/readiness and emit redacted diagnostics; teardown is
project-scoped, idempotent and preserves volumes unless explicitly scoped.
Current live readiness is `BLOCKED_EXTERNAL` when the approved daemon is not
available.

## 9. PostgreSQL durability

Required evidence covers migration upgrade safety, constraints/indexes/query
plans, transactions, concurrency, idempotency, DLQ/replay, retention, leases
and fencing against a real disposable database. Static SQL and unit tests do
not close this section.

## 10. Worker A/B behavior

Two real worker processes must prove ownership, heartbeat fencing, stale ACK
and publish rejection, crash/restart recovery, duplicate delivery handling,
timeouts and reconciliation. A cooperative thread timeout is not a process
isolation proof.

## 11. Redis coordination

Required evidence covers authentication/TLS policy, timeouts, pools,
reconnect/circuit behavior, namespace and tenant isolation, leases,
heartbeats, rate limits and replica/failover behavior. The local
`redis_multi_replica_runtime_gate.py` now starts two independent canonical
`apps/api` HTTP processes against one Redis URL and checks login, recovery,
chat and compatibility policies, shared atomic buckets, replay idempotency,
tenant separation and bucket TTL; its real run remains external evidence.
Alternating API replicas must consume one shared bucket; a bypass is a
rejection.

## 12. Object storage

The S3-compatible authority must prove private scoped access, checksum and
length integrity, streaming, retention, deletion and restore with synthetic
owned data. Local filesystem state is not accepted as source of truth.

## 13. Qdrant projection

Qdrant must prove schema/index/filter behavior, alias swap, reindex, partial
failure, deletion, rebuild and restore. The durable authority must be able to
reconstruct the projection without accepting stale or cross-tenant content.

## 14. Golden ingestion path

`RICK_GOLDEN_RUNTIME_PATH` is the required upload → object → job → worker →
parse → normalize → chunk → embed → Qdrant → verify → publish → retrieve →
evidence → professor → decision → response journey. Each transition needs
lineage, idempotency, fault and recovery evidence; a prompt or offline pack
cannot stand in for the journey.

## 15. Multi-tenancy

Tenant A/B tests must cover identity, API, durable stores, cache, queue,
object storage, vector filters, evidence, decision, logs and timing-sensitive
metadata. Hidden UI elements and local ACL tests are not sufficient.

## 16. Evidence security

Forged IDs, cross-tenant references, stale versions, wrong checksums, unknown
chunks, poisoned documents, prompt injection and stale publication attempts
must reject with stable identifiers, including
`STALE_EVIDENCE_REJECTED`, `WRONG_COMMIT_REJECTED`, `WRONG_TREE_REJECTED`,
`WRONG_HASH_REJECTED`, `MISSING_GATE_REJECTED`, `BLOCKED_GATE_REJECTED` and
`SELF_PROMOTED_GATE_REJECTED`.

## 17. Provider and RAG

An approved bounded provider/corpus packet must cover health, streaming,
timeouts, cancellation, 429/500, retry/backoff, circuit behavior, context,
tool/JSON handling, budgets, ACL and adversarial RAG. Citation relevance,
validity, support, faithfulness and unsupported-claim metrics must feed
conservative answer/retry/clarify/abstain/escalate decisions.

## 18. Observability and SLO

The required trace is HTTP → auth → retrieval → stores → queue → worker →
provider → evidence → decision. Redaction, bounded labels, metrics, alerts
and no-data behavior must be observed. Development, staging and production
SLOs are separate evidence classes in `docs/operations/slo.md`.

## 19. Disaster recovery and restore

The real drill is seed → backup → destroy isolated copy → restore → verify,
including schema, jobs, attempts, audit, lineage, object bytes, ACLs and
Qdrant rebuild. It must report measured RPO/RTO and preserve the previous
checkpoint; the runbook alone is not evidence.

## 20. Chaos and distributed failure

Owned disposable faults must cover worker, Redis, Qdrant, Postgres, object
storage, provider and network boundaries. Recovery must show no silent
corruption, duplicate publication, stale acknowledgement or tenant leak.

## 21. Soak and performance

Short/extended soak and 1/10/50/100 concurrency runs must bind p50/p95/p99,
throughput, errors, CPU, memory, threads, connections, queue depth, retries
and starvation to the exact environment. A local fixture is not a production
SLO claim.

## 22. Frontend and accessibility

The real API/browser matrix must cover login, chat, upload, documents,
sources, jobs, offline, interruption, permission and degraded provider states
at 375/768/1440. Keyboard/focus, axe, screen-reader, zoom, contrast,
reduced-motion, touch, console/network and native screenshot evidence require
a fresh independent design review.

## 23. Supply chain and containers

The exact image digests, dependency/license/secret scans, SBOM, provenance,
signatures, non-root/read-only/capability/resource/health hardening and
rollback digest must be current. The prepared packet is not a built-image
PASS.

## 24. Independent reviews

Fresh reviewers must attempt rejection across architecture, security,
runtime, database, observability, recovery, RAG, frontend and operations.
Builder review is not independent approval, and a self-promoted PASS is
rejected by the evidence contract.

The current Phase 3 matrix additionally requires each promoted capability to
bind a hashed, candidate-scoped independent record in the canonical
verification ledger. The current candidate has no such complete promotion
packet or fresh full-product reviewer; this local binding is a rejection guard,
not approval evidence.

## 25. Risks and residuals

Open residuals are runtime authority, provider/corpus approval, live tenant
isolation, distributed telemetry, restore/chaos/soak/performance evidence,
container provenance, exact packet sealing and human release ownership.
Each residual needs an owner, mitigation, expiry and revalidation trigger
before promotion.

## 26. Rollback and recovery decision

No deployment or destructive rollback is authorized by this report. A failed
slice creates a new exact run, preserves prior evidence and uses reviewed
roll-forward or an isolated restore. Application rollback requires a previous
immutable digest and migration-compatible boundary.

## 27. Twenty-five-dimension scorecard

| # | Dimension | Current state | Required evidence |
| ---: | --- | --- | --- |
| 1 | Architecture | `LOCAL_VERIFIED` | independent boundary review |
| 2 | CI control | `PARTIAL` | current exact-SHA workflow run |
| 3 | Release truth | `NOT_RUN` | clean manifest, seal and negative probes |
| 4 | Disposable lab | `BLOCKED_EXTERNAL` | live health/readiness/teardown |
| 5 | PostgreSQL | `BLOCKED_EXTERNAL` | real migration/transaction/queue run |
| 6 | Durable jobs | `BLOCKED_EXTERNAL` | DLQ/replay/retention/recovery |
| 7 | Worker fencing | `BLOCKED_EXTERNAL` | real A/B crash and stale ACK |
| 8 | Redis coordination | `BLOCKED_EXTERNAL` | auth/lease/reconnect/failover |
| 9 | Object authority | `BLOCKED_EXTERNAL` | checksum/ACL/restore |
| 10 | Vector projection | `BLOCKED_EXTERNAL` | alias/rebuild/restore |
| 11 | Golden ingestion | `BLOCKED_EXTERNAL` | full named runtime path |
| 12 | Lineage | `PARTIAL` | source-to-response lineage packet |
| 13 | Tenancy | `PARTIAL` | live A/B isolation negatives |
| 14 | Evidence security | `PARTIAL` | forged/stale/hash/chunk negatives |
| 15 | Provider runtime | `BLOCKED_EXTERNAL` | bounded approved provider matrix |
| 16 | Retrieval/RAG | `NOT_RUN` | approved corpus metrics |
| 17 | Citation support | `NOT_RUN` | support/faithfulness metrics |
| 18 | Decision policy | `PARTIAL` | conservative live decision matrix |
| 19 | OTel propagation | `PARTIAL` | distributed trace export |
| 20 | SLO/alerts | `PARTIAL` | env-separated telemetry/alerts |
| 21 | DR/restore | `NOT_RUN` | measured isolated drill |
| 22 | Chaos | `NOT_RUN` | fault/recovery packet |
| 23 | Soak/performance | `NOT_RUN` | declared load/resource budgets |
| 24 | Frontend/a11y | `PARTIAL` | real browser matrix + critic |
| 25 | Supply/review/promotion | `NOT_RUN` | scans, independent review, Go/No-Go |

Scores are advisory only. No numeric score is issued while mandatory evidence
is missing or blocked; no score can override a required rejection.

## 28. Final Go/No-Go and next action

**Decision:** `NO-GO / NOT PROMOTED`.  
**Authorized approver:** `NOT_RUN`.  
**Sealed packet:** `NOT_RUN`.  
**Executable next action:** run the P0 control packet from a clean candidate,
then obtain an explicitly owned disposable runtime; re-run all blocked lanes,
rebind every artifact to the resulting SHA/tree and request fresh independent
review before any promotion decision.
