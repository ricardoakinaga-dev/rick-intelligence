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

The authoritative identity is always the same-run packet at
`.runtime/phase-3/triple-aaa-verify.json`: commit, tree, checkout fingerprint,
artifact-set digest, packet hash and quality-bar hash must be read from that
packet together. This report never substitutes a manually typed SHA and is
invalid if the packet is absent, stale, dirty or inconsistent with the exact
candidate. The latest source-closure notes are recorded in section 23 of the
current gap audit; the packet remains authoritative for exact hashes.

## 3. Prompt provenance

Requirements are bound to the stored closure prompt and its recorded source
attachment hash in `docs/reports/current-triple-aaa-gap-audit.md` and
`docs/reports/current-triple-aaa-quality-bar-v1.json`. The stored copy's
normalized final newline is explicitly documented; it is not represented as
byte identity with the attachment.

## 4. Frozen quality bar

The historical twelve-criterion bar in `current-triple-aaa-quality-bar-v1.json`
remains a minimum predecessor contract. The current prompt's twenty-five
dimensions are the explicit scorecard in section 27; neither contract may be
averaged around a mandatory runtime or authority blocker. Their baseline
statuses remain `NOT_RUN` or runtime-blocked until current evidence satisfies
the declared method.

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

The State-of-Art release test environment now pins the provider test
dependencies and exports a contiguous internal-package `PYTHONPATH`. The
same-SHA remote run reaches the explicit release checks; its exit `2` is the
expected external-block classification, while the pinned test suite itself
passes in a clean venv.

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

The current managed API/browser packet passes login, authenticated workbench
and chat at 375/768/1440, with keyboard/focus, axe, contrast, reduced-motion,
touch and console/request checks passing. It is real non-intercepted local
evidence; it does not prove production runtime or independent visual approval.
Upload, documents, sources, jobs, offline, interruption, permission and
degraded provider states plus a fresh independent design review remain
required for promotion.

## 23. Supply chain and containers

Source lockfiles, source SBOM, secret and license checks pass in the current
packet. The exact image digests, image SBOM, provenance, signatures,
non-root/read-only/capability/resource/health hardening and rollback digest
must still be current. `container-digests` and `container-sbom` are
`NOT_RUN`, so the scoped supply lane remains `BLOCKED_EXTERNAL`; the packet
is not a built-image PASS.

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
| 1 | Architecture | `LOCAL_VERIFIED` | current boundary checks and independent architecture review |
| 2 | Modularity | `PARTIAL` | package/adaptor boundaries plus fresh architecture review |
| 3 | Jobs | `BLOCKED_EXTERNAL` | real queue, DLQ, replay, retention and recovery run |
| 4 | Worker | `BLOCKED_EXTERNAL` | two real workers, lease fencing and crash recovery |
| 5 | PostgreSQL | `BLOCKED_EXTERNAL` | real migration, transaction, constraint and queue run |
| 6 | Redis | `BLOCKED_EXTERNAL` | real auth, lease, reconnect and multi-replica run |
| 7 | Qdrant | `BLOCKED_EXTERNAL` | live schema, filters, alias, rebuild and restore |
| 8 | Object Storage | `BLOCKED_EXTERNAL` | live scoped PUT/GET/checksum/retention/restore |
| 9 | Ingestion | `BLOCKED_EXTERNAL` | complete named golden ingestion path |
| 10 | Retrieval | `NOT_RUN` | approved corpus and retrieval-quality metrics |
| 11 | Evidence | `PARTIAL` | live lineage plus forged/stale/hash/chunk negatives |
| 12 | Decision | `PARTIAL` | citation support metrics feeding conservative decisions |
| 13 | Professor | `PARTIAL` | provider-backed reasoning and bounded budget evidence |
| 14 | Security | `PARTIAL` | live threat, file, redaction and supply-chain review |
| 15 | Multi-tenancy | `PARTIAL` | live Tenant A/B isolation negatives across every store |
| 16 | Observability | `PARTIAL` | distributed traces, bounded metrics, alerts and SLO evidence |
| 17 | Resilience | `NOT_RUN` | distributed failure and bounded recovery packet |
| 18 | Disaster Recovery | `NOT_RUN` | measured seed/backup/destroy/restore/rebuild drill |
| 19 | Performance | `NOT_RUN` | 1/10/50/100 concurrency and resource measurements |
| 20 | Frontend | `PARTIAL` | real API browser states at 375/768/1440 |
| 21 | Accessibility | `PARTIAL` | keyboard, focus, axe, zoom, contrast, motion and touch review |
| 22 | CI/CD | `PARTIAL` | current exact-SHA FAST/UNIT/CONTRACT/SECURITY/RAG/FRONTEND/SUPPLY/RELEASE run |
| 23 | Supply Chain | `BLOCKED_EXTERNAL` | dependency, secret, container, SBOM, digest and signature evidence |
| 24 | Documentation | `LOCAL_VERIFIED` | current audit, plan, report and `make validate` |
| 25 | Production Readiness | `BLOCKED_EXTERNAL` | all mandatory gates, zero Critical/High, seal and human Go/No-Go |

**Advisory score: `14/100`.** The score uses equal 25-dimension weighting:
`LOCAL_VERIFIED = 2`, `PARTIAL = 1`, and `PASS`/`VERIFIED_RUNTIME`/
`PROMOTABLE = 4`; `BLOCKED_EXTERNAL` and `NOT_RUN` score zero. The current
matrix has two `LOCAL_VERIFIED` dimensions and ten `PARTIAL` dimensions.
This is a diagnostic measure only; it cannot override a mandatory rejection,
and the definition-of-done threshold remains `96/100` with all required
runtime and promotion gates passing.

## 28. Final Go/No-Go and next action

**Decision:** `NO-GO / NOT PROMOTED`.  
**Authorized approver:** `NOT_RUN`.  
**Sealed packet:** `NOT_RUN`.  
**Executable next action:** provide the approved disposable Docker daemon and
runtime configuration, rerun the current adapters and real service lanes,
rebind every artifact to the resulting SHA/tree, obtain fresh independent
review and an authorized sealed Go/No-Go decision. The current packet's
PostgreSQL, Redis, provider and release envelopes are fresh
`BLOCKED_EXTERNAL` observations. Its scoped frontend-e2e and accessibility
lanes are PASS, while the combined frontend/supply envelope and supply-chain
lane remain `BLOCKED_EXTERNAL` because image evidence is absent; none is a
promotion signal. The promotion engine correctly returns `2` for this
external-only block; local failures and malformed supplied packets remain
`1`.
