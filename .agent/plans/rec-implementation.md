# REC implementation — ExecPlan

<!-- engineering-framework: active_action_id=REC-05:WAIT_RUNTIME -->

## Current state — 2026-09-08

The requested REC-01–35 plan has been implemented as far as the current
checkout can verify locally. The local candidate is dirty HEAD
`66781cbe96c10786bbf9b9150ee4798df62fdba6`. `make api15-full`,
`make api16-full`, storage/operations checks, OpenAPI generation, the Next
production build, and the 294-case browser matrix are green. The API root now
has 418 passing tests, including the controlled case record/review/feedback
surface, stream terminal-outcome, pagination, ACL, idempotent retry and SQLite
restart checks. REC-05 remains
blocked because the Docker daemon socket is inaccessible; the external runtime,
provider, corpus, restore, load, alert-delivery, rollout and release decision
are deliberately open.

The exact current source binding is snapshot v15 with 546/546 hashes matching.
The v13 and v14 local REC-34 approvals are historical: v13 followed the
identity permission expectation alignment and v14 preceded the finite-deadline
shutdown correction. A fresh current REC-34 review is required for v15.

The machine state remains `REC-05:WAIT_RUNTIME` and `BLOCKED`. This plan does
not turn local adapter tests into external acceptance and does not alter the
frozen `.gauntlet` bar or historical ledgers.

## Objective and scope

Implement the revised 35-item construction plan while preserving the three
legacy repositories and every historical acceptance decision. The current
candidate covers the canonical API/web surface, contracts, identity/session
boundaries, tenant/workspace scoping, audit, knowledge/RAG lifecycle, durable
adapter seams, worker, Professor path, conversations, browser UX and local
operational evidence.

The external completion path still requires D01–D05: integration ownership and
runtime, identity policy, provider/model/budget, corpus/golden-set/clinical
thresholds, and operational SLO/RPO/RTO/retention/alert decisions.

## Delivered local slices

- REC-01–04: owned Playwright harness, persona/route contract, effective
  provider configuration and server-derived permission navigation.
- REC-05 preparation: private Compose, filtered environment, fixed loopback
  ports, fail-closed launcher and no-volume-deletion teardown.
- REC-06–09: additive SQL migrations, Postgres knowledge/identity/audit/chat/
  queue seams, scoped reads and strict audit on sensitive mutations.
- REC-10–14: tenant-bound admin CRUD, session administration, recovery tokens
  with TTL/single-use consumption, explicit password-reset delivery port,
  collection/grant lifecycle and web console.
- REC-15–20: private S3 adapter, Postgres queue/worker with bounded handler
  timeout, Redis lease, Qdrant HTTP/vector seam, external composition root and
  dependency health checks.
- REC-21–26: Professor/provider boundary, evidence validation, chat history in
  memory/SQLite/Postgres, scoped context/idempotency, incremental SSE,
  cancellation, terminal stream outcomes, bounded TTFT/duration telemetry and
  conversational workspace.
- REC-22: versioned synthetic offline retrieval pack with explicit thresholds,
  negative evidence cases, ACL/citation checks and per-model/corpus output.
- REC-27: strict human case-record contracts, structured hypotheses/evidence,
  tenant/workspace/owner scoped InMemory/SQLite stores, double D04 gate,
  authorized catalog metadata, review/feedback audit intents before writes,
  stable-key idempotency and `/app/cases`.
- REC-28–33 local preparation: responsive/accessibility evidence, bounded
  telemetry/readiness, semantic backup reconciliation, injected distributed
  rate-limit seam wired into login, local benchmarks and release/compose
  preparation with storage dependencies included in API/worker images.

REC-22 and REC-27 now have bounded local implementations, but D04 remains
open: the checked-in pack is synthetic and offline, and the case surface is
disabled by default. No clinical quality, domain approval, live provider,
golden-set, or production persistence claim is made. REC-25 is locally
implemented: validated complete turns and partial/error/cancelled terminal
outcomes are persisted with bounded metadata, incomplete outcomes are excluded
from future prompt context, and the local telemetry seam records TTFT and
terminal duration. The external live provider/runtime acceptance remains open.

## Verification matrix

Current commands and artifacts are recorded in
`docs/reports/execucao-planejamento-2026-09-08.md`,
`docs/reports/rec-source-snapshot-2026-09-08-v15.json`,
`.gauntlet-state-of-art/evidence/visual-cycle5-current/`,
`.agent/verification.jsonl`, and `.agent/execution-log.jsonl`.

Required local checks:

1. `make api15-full` — boundary, contracts, providers, locking, Professor,
   API and benchmark.
2. `make api16-full` — controller validation, domain, worker/health, API and
   benchmark.
3. `make api-contract` — generated OpenAPI is current.
4. `make storage-test ops-static ops-backup-test` — storage, migration
   checksums/syntax and backup verifier.
5. `make web-lint web-typecheck web-build` — web static gates.
6. `make web-e2e` — 375/768/1440 production browser matrix and performance
   artifact.
7. `git diff --check` — whitespace and patch hygiene.
8. Focused REC-25 regression — terminal stream outcomes, live timing metrics,
   SQLite restart and Postgres adapter contract.
9. Focused bounded-observability/lifecycle regressions — 10 observability
   tests, 68 lifecycle/root tests and 45 identity/ingestion/knowledge tests;
   exact candidates V6 and V8 require fresh I1 review.

These commands are local evidence only. A passing command is not evidence for
Postgres execution, OIDC login, two replicas, real Redis/Qdrant/S3/provider,
external telemetry delivery, restore, load, image rollout or production.

## Review and release gate

REC-34 was approved for the local integration scope on snapshots v13 and v14.
Those approvals are historical after the identity expectation and finite-
deadline shutdown corrections. The scoped V6 observability and V8 lifecycle
reviews are current and approved; the final independent V15 Final Critic also
approved the local REC-34 integration scope with no Critical, High, Medium or
Low finding. An interrupted or timed-out reviewer is recorded as `NOT_RUN`,
never as approval. REC-35 is `NO-GO` until the
responsible product/security/operations owners decide on this concrete
candidate and authorize a rollout window with rollback ownership.

Frozen bar: `.gauntlet/bar.json` and
`.gauntlet-state-of-art/bar.canonical.json`. Do not weaken it, overwrite
historical evidence, or mark a criterion PASS without current evidence.

## Next action

Keep the active action at `REC-05:WAIT_RUNTIME`. The host owner must grant
controlled daemon access under local policy and inject only disposable lab
secrets from `infrastructure/compose/INTEGRATION.md`. Run preflight, then
exercise REC-05–09 with real local services. Resolve D01–D05 before external
corpus/provider/clinical/load work. Rebind the source snapshot and rerun the
affected gates after every source or deployment change.

## Recovery and idempotence

Read `.agent/state.json`, `.agent/backlog.json`, this plan and both append-only
ledgers before resuming. Preserve `.gauntlet/state.json`, the frozen bar,
legacy repositories, user changes and prior failed/rejected reviews. Apply
forward patches only; never reset or checkout the dirty worktree. Do not expose
secrets, relax Docker permissions, contact paid providers or deploy from this
plan.

## Purpose / Big Picture

The purpose is to make the canonical RICK product usable through secure,
scoped, durable and observable interfaces, then accept a concrete release
candidate only when the frozen fourteen-criterion bar and the REC backlog have
current evidence.

## Progress

- [x] (2026-09-08) Implemented and locally regressed REC-01–33 slices that do
  not require external runtime or unresolved D01–D05 decisions.
- [x] (2026-09-08) Closed the local REC-25 terminal-outcome and stream-timing
  gap with API regression evidence.
- [x] (2026-09-08) Marked in-flight chat text as provisional until citation validation, closed the local REC-23–25 review findings, and bound the current source/browser evidence to snapshot v15.
- [x] (2026-09-08) Added the REC-22 synthetic offline evaluation pack and the
  REC-27 double-gated human case record/review/feedback surface.
- [x] (2026-09-08) Added bounded REC-29–33 local telemetry, semantic backup,
  distributed-rate-limit, benchmark, Docker/Compose and release artifacts;
  prepared release validation now rejects `PASS` in every external status
  field until the corresponding evidence exists.
- [ ] (2026-09-08) Exercise the external integration laboratory; blocked by
  Docker daemon access and disposable runtime decisions.
- [x] (2026-09-08) Complete the REC-34 independent local integration review
  against snapshot v12; the Final Critic found no local High/Medium/Low blocker;
  preserve that result as historical after v12 became stale.
- [x] (2026-09-08) Complete the REC-34 Final Critic review against snapshot v13;
  the replacement critic found no local blocker after the plan binding fix.
- [x] (2026-09-08) Rebind the exact current local candidate to snapshot v14
  after aligning the two identity permission expectation tests; all 546 hashes
  match and v13 remains historical.
- [x] (2026-09-08) Rebind the exact local observability and ingestion lifecycle
  candidates as V5 and V7 with their before/after snapshots and current local
  regression evidence; preserve their stale-evidence and lifecycle findings.
- [x] (2026-09-08) Correct finite-deadline queued-future reconciliation and
  capture fresh V6/V8 regression logs; rebind the exact global candidate to
  snapshot v15 with all 546 hashes matching.
- [x] (2026-09-08) Obtain fresh I1 approvals for observability V6 and ingestion
  lifecycle V8; both scoped local reviews verified their exact bindings and
  found no Critical, High or Medium finding.
- [x] (2026-09-08) Obtain one complete fresh Final Critic approval for the
  global REC-34 v15 candidate; Erdos verified 546/546 hashes, 14/14 frozen
  criteria and the corrected local seams with no Critical, High, Medium or Low
  finding.
- [ ] (2026-09-08) Obtain the REC-35 human Go/No-Go.

## Surprises & Discoveries

The final local browser suite is larger than the original M0 evidence (294
cases versus 261), and the regenerated OpenAPI has 49 paths. The local runtime
can prove the adapter contracts, stream terminal lifecycle and authorization boundaries, but it cannot
prove a Postgres/S3/Qdrant/Redis/OIDC/provider deployment. The post-fix fresh
context REC-34 review of snapshot v8 did not return a final report within its
bounded windows and was shut down procedurally; it remains `NOT_RUN` evidence,
not approval. The fresh review of snapshot v10 found that prepared release
validation still accepted `PASS` in five external fields. The checker and
regression coverage were corrected, snapshot v11 was rebound, and a subsequent
API15/API16 retest refreshed two performance artifacts. Snapshot v11 was marked
stale, snapshot v12 was rebound, and the Final Critic approved the local REC-34
integration scope. A subsequent verification regenerated the bound performance
artifacts, so v12 was marked stale and v13 became the exact review target. Two
identity expectation tests then changed to reflect the current permission
policy, making v13 historical and producing the exact v14 binding. A finite-
deadline queue cleanup finding then led to a forward lifecycle fix, fresh V6/V8
evidence and exact global v15 rebinding. The current local v15 and V6/V8 scoped
candidates do not cover external runtime or REC-35.

## Decision Log

- 2026-09-08: Keep the frozen Gauntlet bar and historical acceptance records
  unchanged.
- 2026-09-08: Require a scoped `password_reset_delivery` port in external
  composition and never return reset tokens from HTTP.
- 2026-09-08: Keep REC-05 `BLOCKED` until the host owner grants controlled
  daemon access; do not change Docker group/socket permissions implicitly.
- 2026-09-08: Persist stream terminal outcomes in the scoped chat read model;
  exclude `partial`/`error`/`cancelled` entries from prompt context and keep
  TTFT/duration telemetry bounded to a finite outcome vocabulary.
- 2026-09-08: Classify REC-35 as local `NO-GO`/blocked because external gates,
  D01–D05 and human rollout authority are absent.

## Outcomes & Retrospective

The local implementation is materially ahead of the initial M0 baseline: the
API, worker, storage seams, contracts, admin/RAG/chat UI and full browser
matrix are current and tested. The remaining work is acceptance work across
external runtime and product/operations decisions, not a reason to weaken
assertions or turn synthetic evidence into production claims.

## Context and Orientation

The root is `/home/ricardo/rick-intelligence`; `apps/api` is FastAPI,
`apps/web` is Next.js, packages own contracts/domain adapters, and
`apps/worker` owns the separate worker seam. The active evidence report is
`docs/reports/execucao-planejamento-2026-09-08.md` and the current source
binding is `docs/reports/rec-source-snapshot-2026-09-08-v15.json`.

## Scope and Constraints

Preserve all three legacy repositories, existing dirty user work, frozen bars,
historical ledgers and production guardrails. Local synthetic fixtures are
allowed for bounded tests. Paid providers, external corpus, host permission
changes, database execution, deployment and production writes require explicit
runtime decisions and are not inferred from this task.

## Architecture and Interfaces

The product path is UI → API route → typed contract/application service →
scoped store or injected external adapter. Tenant and workspace are mandatory
at protected store boundaries. The external composition root owns Postgres,
S3-compatible storage, Qdrant, Redis lease, provider, identity, audit, chat
history, queue and worker resources; local adapters advertise their limited
durability explicitly.

## Milestones

### Milestone 1 — Local candidate

REC-01–04 and the locally testable slices through REC-33, with current API,
worker, storage and browser evidence.

### Milestone 2 — Integration laboratory

REC-05–20 after daemon access, secrets and D01–D02; exercise real stores,
identity, queue, worker and retrieval.

### Milestone 3 — Product acceptance

REC-21–32 after D03–D05, provider/corpus/clinical scope and operational
evidence.

### Milestone 4 — Release decision

REC-33–35 with current snapshot, independent review and human Go/No-Go.

## Plan of Work

Keep source changes forward-only and disjoint. Re-run the affected local gates,
regenerate OpenAPI and rebind the snapshot after every source change. When the
external runtime is available, start with preflight and migration checks,
exercise the Postgres/identity/audit/queue seams, then move through retrieval,
Professor, conversations, telemetry, restore and release review in backlog
dependency order.

## Concrete Steps

1. [REC-05:WAIT_RUNTIME] Obtain controlled Docker daemon access under host
   policy, inject disposable lab secrets, and run the integration preflight.
2. [REC-05:VERIFY_RUNTIME] Execute REC-05–09 against the disposable services;
   preserve logs, checksums, scopes and failure evidence.
3. [REC-21:VERIFY_PROVIDER] Resolve D03 and exercise the approved provider,
   corpus and citation path within the agreed budget.
4. [REC-34:VERIFY_REVIEW] Commission a complete independent review of the
   exact current snapshot and all mandatory criteria.
5. [REC-35:DECIDE] Obtain the responsible human Go/No-Go and rollout/rollback
   authorization for that exact candidate.

## Validation and Acceptance

Local acceptance requires the current API15/API16 gates, storage/ops checks,
OpenAPI generation, web lint/typecheck/build, 294-case browser matrix and
source snapshot. External acceptance additionally requires the live runtime,
approved data/provider, golden/clinical set, telemetry, restore, load/cost,
rollout and independent review evidence described in the report and backlog.

## Risks and Human Decisions

D01–D05 remain human decisions. The main risks are cross-tenant leakage from
unscoped external adapters, claiming durability from local stores, sending
unapproved data or paid requests, and promoting without restore/operations
evidence. The code and gates fail closed at the reviewed boundaries; they do
not remove the need for external acceptance.

## Idempotence and Recovery

Rerunning local checks is safe and re-generates the current OpenAPI/build
artifacts. Migration execution must use the checksum and lock protocol without
automatic destructive rollback. If a gate fails, preserve the failing output,
rebind the snapshot after a fix, and append a new ledger record; do not rewrite
or delete historical evidence.

## Artifacts and Evidence

Current artifacts are the execution report, source snapshot v15, regenerated
`apps/api/openapi.json`, browser/performance evidence under
`.gauntlet-state-of-art/evidence/visual-cycle5-current/`, the independent-review
status under `.gauntlet-state-of-art/evidence/rec-integration-local-current/`,
and the append-only `.agent` ledgers. The frozen bar and `.gauntlet/state.json`
remain authoritative for criterion and run state.
