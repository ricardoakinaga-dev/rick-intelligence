# Phase 3 — Runtime Evidence & Production Promotion

**Status:** `ACTIVE — Phase 3.1 locally verified; Phase 3.2 external runtime gates blocked`
**Date:** 2026-09-10
**Frozen candidate:** `56a76004a75ec94178e35c82eab8405b5ac74729`
**Prompt copy:** [`docs/prompts/phase-3-runtime-evidence-production-promotion-2026-09-09.txt`](../prompts/phase-3-runtime-evidence-production-promotion-2026-09-09.txt)
**Current audit:** [`docs/reports/phase-3-runtime-evidence-current-audit.md`](../reports/phase-3-runtime-evidence-current-audit.md)
**Living ExecPlan:** [`../../.agent/plans/phase-3-runtime-evidence-production-promotion.md`](../../.agent/plans/phase-3-runtime-evidence-production-promotion.md)
**Current source implementation candidate:** `928bcd10cde225bedb6c237c0cc979a259919989` (tree `8da40a5b95bfa9787c2314aa89b7a0d3563c6eee`)

## Purpose

Raise the current local `STATE_OF_ART_CANDIDATE` to a promotion decision only
when executable, current, commit-bound evidence proves the runtime, security,
durability, retrieval, observability, frontend, infrastructure and operations
claims required by the supplied Phase 3 prompt. The plan is additive and
brownfield-safe: it preserves the previous fourteen-criterion Gauntlet bar,
the Phase 2 evidence and the three child repositories.

The target is not a score manufactured from documentation. A capability is
`VERIFIED_RUNTIME` only when its required runtime observation, raw artifact,
commit binding, environment and independent review are present. A capability
is `PROMOTABLE` only after all mandatory gates and authorities are current.

## Scope and constraints

In scope are the root CI, release evidence, disposable integration lab,
Postgres/Redis/S3-compatible/Qdrant/API/worker/web/OTel runtime paths, golden
ingestion and RAG evidence, multi-tenancy, DR/restore, chaos/soak/performance,
frontend runtime and accessibility/visual QA, supply chain and the final
promotion report.

Out of scope without an explicit owner decision are host Docker permission
changes, production writes, destructive volume/database operations, paid or
regulated provider calls, unapproved corpus, secret disclosure and deployment
to production. Local synthetic tests may prove bounded contracts but never
replace the corresponding real-runtime gate.

## Frozen acceptance model

The frozen `.gauntlet/bar.json` remains a required predecessor. Phase 3 also
requires:

- explicit status for every capability: `DONE_LOCAL_SCOPE`, `LOCAL_VERIFIED`,
  `VERIFIED_RUNTIME`, `PARTIAL`, `MISSING`, `BLOCKED_EXTERNAL`, `FAILED` or
  `PROMOTABLE`;
- exact commit SHA, artifact digest, environment, procedure, reviewer,
  limitations and next action for every evidence row;
- release rejection for stale evidence, wrong commit, wrong hash, missing
  evidence, blocked runtime and dirty checkout;
- current P0 closure before P1, and P1 closure before advanced P2 features;
- zero unresolved Critical/High finding at final review and a human Go/No-Go
  bound to the exact artifact and rollback owner.

The final required report is
[`docs/reports/state-of-art-triple-aaa-promotion-report.md`](../reports/state-of-art-triple-aaa-promotion-report.md).
It will contain the 26 sections and 25-dimension scorecard named in the
source prompt. Until that report has current evidence, the candidate is not
AAA or Triple AAA.

## Evidence architecture

Every lane emits a machine-readable record with at least:

```text
capability_id, status, commit_sha, artifact_sha256, environment,
procedure, exit_status, observed_at, reviewer, limitations, next_action
```

The release manifest must reject records whose commit differs from `HEAD`,
whose artifact digest differs from the recorded bytes, whose required artifact
is absent, whose runtime status is blocked/not-run, or whose checkout is not
clean. Raw logs, health responses, traces, metrics, screenshots, accessibility
results, database/object/vector snapshots and restore logs remain immutable
inputs to the summary. A summary may aggregate evidence; it may not upgrade a
status.

The disposable lab is canonical and loopback-scoped. It contains Postgres,
Redis, Qdrant, an S3-compatible object store, API, Worker A, Worker B, Web and
OTel collector/metrics/trace support with healthchecks. `make up` renders,
starts, waits for readiness and fails closed; `make down` removes only resources
owned by the lab and never deletes unrelated volumes.

## Ordered milestones

### Phase 3.1 — CI and release-evidence closure (P0)

Canonicalize FAST, UNIT, CONTRACT, RAG_EVAL, FRONTEND, SUPPLY_CHAIN, RELEASE,
runtime, performance, chaos and nightly/manual lanes. Add typed evidence
schemas and negative tests for stale evidence, wrong commit, wrong hash,
missing evidence and blocked runtime. Bind raw artifacts to the exact HEAD and
make the release gate fail closed.

### Phase 3.2 — Disposable real integration lab (P0)

Complete Compose healthchecks/readiness and deterministic `make up/down`, with
loopback ports, disposable secrets, log collection, endpoint probes and no
implicit host permission changes. Runtime startup remains `BLOCKED_EXTERNAL`
until the daemon is available.

### Phase 3.3 — PostgreSQL runtime and durable queue (P0)

Execute migrations, checksums, FK/trigger behavior, transaction boundaries,
claim/fence/lease/retry/retention and concurrent-worker tests against real
Postgres. Capture query/error logs and prove crash/replay semantics.

### Phase 3.4 — Real workers and crash/fencing matrix (P0)

Exercise Worker A/B ownership, stale lease fencing, SIGTERM, process crash,
restart, duplicate delivery, handler timeout and recovery. Keep
`ProcessIsolatedExecutor` optional; it cannot replace `RealWorkerRuntime`.

### Phase 3.5 — Redis multi-replica runtime (P0)

Run lease, fencing, rate-limit and TTL behavior with multiple Redis replicas or
the approved equivalent. Record failover, clock/deadline and unavailable-broker
behavior without converting degraded mode into success.

### Phase 3.6 — Object and vector lifecycle (P0)

Prove S3-compatible put/read/delete/checksum/version/restore and Qdrant
collection/point/filter/delete/rebuild behavior, including tenant scope and
wrong-version/unknown-object negatives.

### Phase 3.7 — Golden ingestion, lineage and recovery (P0)

Run the approved golden corpus end-to-end through upload, parsing, chunking,
embedding, indexing, query and citation. Exercise idempotency, partial failure,
crash/replay, stale document and lineage verification with raw artifacts.

### Phase 3.8 — Evidence runtime closure and mandatory negatives (P1)

Make runtime evidence authoritative only when cryptographically bound to the
candidate. Execute forged evidence, cross-tenant, stale version, wrong
checksum, unknown chunk, missing citation and contradictory-decision tests.

### Phase 3.9 — Real provider/local OpenAI-compatible integration (P1)

After D03 approval, execute the provider/model/budget/citation path against the
approved endpoint or local OpenAI-compatible service. Record redacted request
metadata, latency/cost budgets, failure and cancellation behavior.

### Phase 3.10 — Multi-tenancy and adversarial RAG (P1)

Run tenant/workspace isolation, ACL, prompt-injection, poisoned document,
citation mismatch, stale index, unknown chunk and cross-tenant retrieval tests
against the live stack and approved corpus.

### Phase 3.11 — Distributed observability and SLO (P1)

Exercise trace propagation across Web/API/worker/storage/provider, redaction,
metrics cardinality, alert delivery, dashboards and the SLO contract. Update
[`docs/operations/slo.md`](../operations/slo.md) with local, lab and production
evidence classifications plus the exact runtime artifacts and owners.

### Phase 3.12 — DR, restore, chaos, soak and performance (P1)

Define and verify RPO/RTO, backup integrity, restore into an isolated target,
worker/service chaos, dependency failures, long soak, concurrency and latency/
throughput budgets. Store the mandatory
`docs/reports/disaster-recovery-runtime-evidence.md` report.

### Phase 3.13 — Frontend runtime and independent design QA (P1)

Run the real Web/API runtime at 375, 768 and 1440 widths; verify keyboard and
screen-reader paths, contrast, reduced motion, error/loading/empty states and
visual baselines. Obtain a fresh independent visual review using the
design-director critic contract; static build success is insufficient.

### Phase 3.14 — Supply chain and deployment hardening (P1)

Run dependency/license/secret/SBOM/image scans, pin and verify immutable
digests, harden containers, sign provenance, validate least privilege and
capture deployment/rollback evidence. Any Critical or High finding blocks
promotion.

### Phase 3.15 — Triple-AAA promotion decision (P1/P2 boundary)

Classify every matrix row, rerun the frozen fourteen criteria plus Phase 3
addendum, obtain fresh independent reviews, calculate the scorecard without
counting missing/blocked evidence as pass, publish the final report and obtain
human Go/No-Go for this exact commit/artifact/rollback plan. Enable advanced
retrieval flags only after this closure.

## Verification commands and evidence outputs

The first implementation slice must preserve the current local gates and add
focused tests. The complete plan will use, as applicable:

```text
make validate
make ops-static compose-static security-adversarial api-contract
make web-lint web-typecheck web-build
make up                       # only with approved disposable daemon access
make postgres-runtime redis-runtime object-qdrant-runtime
make triple-aaa-verify
make release-evidence
python scripts/state_of_art/release_integrity.py --require-clean \
  --evidence docs/progress/release-evidence.json
```

Each live gate additionally stores raw service logs, health responses, test
output, trace/metric references, artifact hashes and an independent review
record. A failed or blocked command remains failed or blocked in the report.

## Recovery, rollback and authority

All changes are forward-only and idempotent. Re-run static checks safely;
rerun live gates only against disposable, owned resources. Never reset the
worktree, rewrite append-only `.agent` ledgers, delete unrelated volumes or
replace a stale evidence record in place. A correction creates a new record
that cites the old one and marks the old evidence stale. If a live gate fails,
retain its raw artifacts, return the capability to `FAILED` or
`BLOCKED_EXTERNAL`, repair in a disjoint slice and rebind the candidate.

The current external blocker is Docker daemon access, not a reason to relax
the gates. Human decisions are required for lab secrets, provider/corpus,
clinical or product thresholds, SLO/RPO/RTO/retention, deployment window,
rollback owner and final promotion.

## Current candidate closure

The current source implementation candidate is
928bcd10cde225bedb6c237c0cc979a259919989 with tree
8da40a5b95bfa9787c2314aa89b7a0d3563c6eee. It retains the corrected
PostgreSQL worker gate, canonical two-process Redis/API HTTP gate, strict
release artifact postconditions and same-run diagnostic transport, bounded
same-run GitHub CI envelopes, exact provenance validation, runtime-primary
supply-chain evidence, frontend Phase 3 envelope transport, authenticated
packet sealing, scoped frontend-lane projection, checkout-bound frontend
evidence and reproducible release-test dependencies. The State-of-Art suite
has 295 passing tests and the relevant static/API checks pass; the full
preserved `make test` remains incomplete because the CVG dataset and local
Playwright browser are unavailable. The current integrated verifier packet is
bound to this exact clean checkout and remains diagnostic
`STATE_OF_ART_CANDIDATE` / exit `2`; live runtime, distributed, operational,
provider/corpus and human-approval gates remain open, so no Triple AAA claim
is made.

## Current next action

Phase 3.1 implementation and the readiness-aware Compose change are complete
for local scope and have passed fresh independent review. The next action is
`PH3-2-LAB-READINESS:WAIT_RUNTIME`: obtain an approved disposable Docker
daemon and private runtime configuration, then execute
`make up`, endpoint readiness, bounded log capture and idempotent `make down`.
Keep all unavailable live capabilities `BLOCKED_EXTERNAL` or `NOT_RUN`.
