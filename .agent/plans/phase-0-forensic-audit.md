# Phase 0 Forensic Audit — ExecPlan

## Purpose / Big Picture

Establish a reproducible, evidence-backed baseline for the three repositories
currently presented as RICK Intelligence: `cvg-master-rag-v2`, `rick-professor`,
and `modulo-redis-locker`. The observable success condition is a current-system
architecture map, data/dependency/integration inventory, characterization
coverage for the critical RAG and lock behaviors, executable baseline results,
ranked risks, and a report that can safely drive a later Phase 1 plan. Phase 0
does not merge repositories, rewrite runtime code, remove OpenWebUI support, or
claim production readiness.

## Progress

- [x] (2026-08-31T00:07:05Z) Read the user attachment, applicable skills, and child-repository instructions; confirmed the three independent Git repositories.
- [x] (2026-08-31T00:30:38Z) Inventory, A-O characterization status, and first executable baseline materialized in `docs/architecture/current-system.md` and `docs/baselines/`; child source worktrees remain untouched, with the required CVG docs overlay recorded separately.
- [x] (2026-08-31T00:30:38Z) Feasible characterization and performance procedures ran: isolated Locker black-box and replayable Professor/Locker harnesses passed; CVG Python/Qdrant, real provider, frontend, and end-to-end paths remain explicitly unavailable.
- [x] (2026-08-31T00:31:00Z) Wrote the current architecture, Phase 0 report, A-O status table, risk register, non-promotion decision, and evidence-backed Phase 1 proposal.
- [x] (2026-08-31T00:33:59Z) Obtained a fresh independent read-only critique, corrected stale control state, incomplete A-O traceability, replay placeholders, exact citations, target paths, and overlay wording, then retested.

## Surprises & Discoveries

- Observation: the workspace root is not a Git repository; each of the three
  named subsystems is a separate clean Git repository.
  Evidence: `git status` at the root fails; `git -C <child> status --short --branch`
  reports clean `main...origin/main` for all three children.
  Impact: the target monorepo layout is a proposal, not an existing repository
  boundary, and Phase 1 needs an explicit migration/rollback policy.

- Observation: historical CVG documents claim successful suites and live
  services, but those claims are not current executable evidence in this
  checkout.
  Evidence: `cvg-master-rag-v2/docs/99_runtime_state.md`,
  `docs/03_build/0310_MIGRATIONS.md`, and current dependency/runtime checks.
  Impact: historical records remain linked as stale context and cannot promote
  this workspace.

- Observation: Docker and Qdrant are unavailable; native Redis is available,
  but the default Redis port already answers `PONG` and is outside the isolated
  Phase 0 runtime.
  Evidence: `docker --version` is unavailable, Qdrant `127.0.0.1:6333` refuses
  connection, and `redis-cli 127.0.0.1:6379 ping` returns `PONG`.
  Impact: use an isolated Redis port for runtime lock characterization and mark
  Qdrant-live and container checks as not run, never as passed.

- Observation: the frontend lockfile is inconsistent with its package manifest,
  while the Node service lockfiles install successfully.
  Evidence: `npm ci` in `cvg-master-rag-v2/frontend` rejects missing Playwright
  entries and version mismatches; `npm ci` passes in the two Node services.
  Impact: frontend build/lint evidence is currently blocked by dependency
  reproducibility rather than treated as a code pass.

- Observation: three independent read-only scouts converged on the same
  cross-system contract gaps: no executable CVG ↔ Professor/OpenWebUI link,
  invalid compose sibling paths, divergent Qdrant collection/vector contracts,
  and missing owner-safe lock release.
  Evidence: scout reports cross-checked against `src/`, `deploy/`, and
  `server.js`; runtime Locker characterization reproduced acquisition, TTL,
  contention, and ownerless unlock.
  Impact: these are P0/P1 Phase 1 design constraints, not candidates for a
  speculative Phase 0 rewrite.

- Observation: the current Professor test source has a fallback case whose low
  score still takes the normal answer branch because the processor checks only
  `hasHits`; the package's declared Node 22 test command fails before execution,
  while `npm run build` passes.
  Evidence: `rick-professor/src/core/processor.ts:130` and `:159`,
  `src/core/processor.test.ts`, and `docs/baselines/phase-0-command-log.md`.
  Impact: current test green claims cannot establish the intended evidence gate;
  a future contract test must distinguish no-hit, low-score-hit, and grounded
  answer behavior.

- Observation: the root characterization test is intentionally a black-box
  current-contract test; it records ownerless unlock as a finding, not as a
  desired design assertion.
  Evidence: `tests/phase0/redis-locker-characterization.mjs` and its passing
  isolated runtime result.
  Impact: after the lock contract is redesigned, this test must be replaced by
  an owner-safe contract test rather than left as a release gate.

## Decision Log

- Decision: treat CVG as the current product candidate, Rick Professor as a
  separate compatibility/provider surface, and Redis Locker as a separate
  concurrency service until runtime and contract evidence proves otherwise.
  Context: code and deployment references are separate and collections/defaults
  differ.
  Alternatives: assume the components are already one monolith; merge them
  immediately; or audit each boundary first.
  Reason: the user explicitly requires preservation and characterization before
  refactoring, and the current repository boundaries are observable facts.
  Consequences: the Phase 1 proposal will use a modular-monolith plus separate
  worker/process boundary only where the evidence supports it.
  Date/Author: 2026-08-31 / Codex.

- Decision: make Phase 0 artifacts at workspace root under `docs/`, while
  preserving child-repository documents and appending required CVG runtime/log
  pointers only after the cross-system report is written.
  Context: the requested report paths are root-relative and no root Git repo or
  root documentation exists.
  Alternatives: place all artifacts inside CVG; create a destructive merge; or
  keep findings only in chat.
  Reason: root artifacts describe all three systems without pretending the
  consolidation already happened.
  Consequences: later migration work must decide the authoritative Git boundary
  and ownership of the root control plane.
  Date/Author: 2026-08-31 / Codex.

## Outcomes & Retrospective

Phase 0 produced the requested current-system inventory, Mermaid flow maps,
data/dependency audit, A-O characterization matrix, replayable local
performance harnesses, ranked risks, status table, and a proposed Phase 1
sequence. The isolated Locker contract and feasible Node measurements were
reproduced; CVG Python/Qdrant, real OpenAI, frontend, OpenWebUI, restart,
duplicate, and end-to-end integration paths remain explicitly NOT_RUN or
STATIC_ONLY because the environment lacks the required prerequisites. The
independent critic rejected promotion to `VERIFIED_CANDIDATE`, so the control
plane is left at `VERIFY` with a `PARTIAL` verification state. Human-owned
decisions are the authoritative Git boundary, canonical Qdrant/contracts,
environment provisioning, and whether/when Phase 1 is approved.

## Context and Orientation

The workspace root is `/home/ricardo/Área de trabalho/rick-intelligence`.
`cvg-master-rag-v2` is a Python 3.12/FastAPI backend with a Next.js frontend,
filesystem JSON corpus/enterprise state, Qdrant vectors, OpenAI-compatible
embedding/LLM adapters, and a large native UI. `rick-professor` is a Node 22
Fastify TypeScript OpenAI-compatible adapter that combines Redis memory, a
remote Redis-locker, Qdrant retrieval, and OpenAI chat/embedding calls.
`modulo-redis-locker` is a Node Express service exposing `/healthz`, `/lock`, and
`/unlock` over Redis.

Primary current entrypoints and evidence roots:

- CVG: `cvg-master-rag-v2/src/api/main.py`, `src/services/`,
  `src/core/config.py`, `src/tests/`, `frontend/app/`, and `ops/systemd/`.
- Professor: `rick-professor/src/server.ts`, `src/core/processor.ts`,
  `src/routes/`, `src/lib/`, `deploy/docker-compose.example.yml`.
- Locker: `modulo-redis-locker/server.js`, `package.json`, `Dockerfile`.
- Existing CVG process instructions: `cvg-master-rag-v2/AGENTS.md`.
- User requirements source: the attached pasted-text file supplied for this
  task; its exact attachment path is recorded in the session request.

## Scope and Constraints

- In scope: forensic inventory; current ingestion/retrieval/query/lock/API/UI
  flows; persistence and lifecycle audit; OpenWebUI contract; dependency and
  deployment mapping; characterization tests/procedures; isolated baseline
  measurements; risks; current architecture and evidence report; proposed
  Phase 1 implementation plan.
- Out of scope: monorepo merge; production deploy; schema migration; changing
  lock semantics; fixing security or architecture findings; removing services;
  adding fake tests/metrics/citations/health; using secrets; starting or
  modifying the existing default Redis instance; running destructive Git
  commands; beginning Phase 1.
- Applicable instructions: `cvg-master-rag-v2/AGENTS.md`, root `.agent/PLANS.md`,
  the `gauntlet-loop`, `orchestrate`, and `engineering-framework` skill
  instructions already loaded for this task.
- Requirements/decisions: the attached Phase 0 checklist and report contract;
  current behavior is authoritative over stale prose; all claims need a path,
  command, runtime observation, or an explicit limitation.
- Tier/risk/blast radius: `T4_CRITICAL`, `MEDIUM`, `CROSS_SYSTEM` for the
  cross-repository audit/control-plane scope. Activity remains safe `INSPECT`
  or `REVIEW`; no implementation gate is being bypassed.
- Authorization constraints: no external deployment, public message, secret
  retrieval, or irreversible restructuring is authorized by this request.

## Architecture and Interfaces

The current architecture is intentionally not assumed to be one system. The
audit will model these contracts as observed:

1. CVG upload stores raw/chunk JSON under a workspace filesystem path, creates
   embeddings, and writes dense/sparse points to a selected Qdrant collection;
   CVG search/query primarily resolve the configured global Qdrant collection
   and apply workspace filters.
2. Rick Professor exposes `/v1/models` and `/v1/chat/completions` for OpenWebUI
   style clients, then runs preprocess → Qdrant search → evidence selection →
   agent/fallback → Redis memory. It acquires a per-question lock through the
   locker service.
3. Redis Locker implements `SET NX PX` acquisition and an unconditional
   `DEL`-based unlock endpoint. The audit must characterize these exact
   semantics and not silently replace them.
4. The proposed target must preserve the native CVG web surface, make API,
   ingestion worker, provider compatibility, and lock/memory boundaries
   explicit, and define a migration path only after Phase 0 evidence.

## Milestones

### Milestone 1 — Current-system inventory and architecture evidence

- Outcome: `docs/architecture/current-system.md` contains exact stacks,
  entrypoints, dependencies, flows, stores, API contracts, Mermaid diagrams,
  OpenWebUI integration status, and stale-vs-current evidence labels.
- Scope/dependencies: all three child repositories; read-only inspection plus
  documentation only.
- Demonstration: a new contributor can trace upload → index → search/query and
  Professor → locker/memory/Qdrant/OpenWebUI using the cited paths.
- Acceptance/evidence: every Phase 0 inventory area is `CONFIRMED`,
  `INFERRED`, or `NOT_RUN/UNKNOWN` with a reason and path/command.

### Milestone 2 — Characterization and executable baseline

- Outcome: tests/procedures and baseline artifacts record representative parse,
  chunk, embedding fallback, persistence/index contracts, evidence/provenance,
  concurrency/lock, restart/recovery, malformed/provider/vector failures, and
  duplicate ingestion as PASS, PARTIAL, STATIC_ONLY, or NOT_RUN; latency and
  other measurements are saved where the environment permits.
- Scope/dependencies: isolated temporary data and Redis port; no external
  credentials; Qdrant-live is conditional on availability.
- Demonstration: exact commands produce the saved result or a deterministic
  blocked/not-run result.
- Acceptance/evidence: no test is labeled PASS when its real dependency was not
  available; existing historical metrics are labeled stale.

### Milestone 3 — Phase 0 decision package and independent critique

- Outcome: `docs/progress/phase-0-report.md` has the required sections, a
  `PHASE 0 STATUS` table, and an evidence-backed Phase 1 plan; a fresh
  read-only critic identifies and checks the largest remaining gap.
- Scope/dependencies: report/control-plane artifacts and child Git status only;
  no Phase 1 implementation.
- Demonstration: the report links architecture, baseline, tests, risk register,
  verification ledger, and proposed final layout.
- Acceptance/evidence: report promotion is `VERIFIED_CANDIDATE` only if the
  exit criteria are actually supported; otherwise status remains blocked/partial
  with explicit remediation.

## Plan of Work

First finish static discovery and reconcile existing documentation against the
current code. Then run the installable Node checks and isolated Redis locker
black-box checks. Because Python packaging and Docker are absent, execute
stdlib-only probes where useful and record CVG Python/Qdrant checks as blocked
until prerequisites exist. Add only narrowly scoped characterization artifacts
that do not alter runtime behavior. Materialize the architecture map and
baseline data, then write the report and proposed target layout. Finally ask a
fresh read-only critic to challenge stale claims, missing failure paths, and
unsupported promotion language; fix only report/test evidence gaps and rerun
the affected checks.

## Concrete Steps

From `/home/ricardo/Área de trabalho/rick-intelligence`:

1. Re-read child instructions and inspect Git status, manifests, entrypoints,
   configs, routes, stores, tests, deployment files, and existing evidence.
2. Run `npm ci`, `npm run build`, and declared tests only in the child Node
   projects where lockfiles permit it; run frontend checks only if the lockfile
   can be used without mutation.
3. Start a temporary Redis on an unused isolated port and the locker with an
   isolated `REDIS_URL`/`PORT`; characterize acquisition, contention, TTL, and
   owner-unsafe unlock, then stop both processes and verify the port is closed.
4. Run CVG's available static secret scan and, if Python prerequisites become
   available without system mutation, run its offline and Qdrant-live suites.
5. Create `docs/architecture/current-system.md`, `docs/baselines/`,
   `docs/progress/phase-0-report.md`, and narrowly scoped supporting tests or
   scripts with exact commands and environment notes.
6. Update the root control-plane records and the required CVG runtime/log
   pointers without rewriting historical entries.
7. Spawn a fresh independent read-only critic, inspect its findings against the
   current filesystem, fix material documentation/evidence gaps, rerun affected
   checks, and report the final Phase 0 status.

## Validation and Acceptance

| Criterion | Required | Procedure/environment | Expected observation | Evidence destination |
| --- | --- | --- | --- | --- |
| P0-INV | yes | Static inventory of all three repositories | stacks, manifests, entrypoints, stores, APIs, UI, deploy, tests, secrets/telemetry/errors mapped | `docs/architecture/current-system.md` |
| P0-FLOW | yes | Code-path tracing and Mermaid diagrams | ingestion, QA, Redis lock, and OpenWebUI flows are traceable | `docs/architecture/current-system.md` |
| P0-DATA | yes | Schema/model/store inspection | entities, keys, indexes, deletion, versioning, timestamps, provenance documented | `docs/architecture/current-system.md` |
| P0-CHAR | yes | Existing tests plus focused black-box/offline probes | critical behavior is characterized; unavailable dependencies are explicit | `docs/baselines/characterization-results.json` |
| P0-PERF | yes, conditional by runtime | Timed representative workload in isolated environment | latency/memory/index-size/duplicate/concurrency values or `NOT_RUN` with cause | `docs/baselines/phase-0-performance.json` |
| P0-RISK | yes | Independent static review and evidence matrix | ranked risks have evidence, confidence, impact, and Phase 1 routing | `docs/progress/phase-0-report.md` |
| P0-REPORT | yes | Required report sections and status table | report can be recovered and reviewed without chat history | `docs/progress/phase-0-report.md` |
| P0-PRESERVE | yes | Git status before/after and diff review | no runtime rewrite or destructive restructuring; child repos remain clean unless explicitly documented test/doc additions are made | `.agent/verification.jsonl` |

## Risks and Human Decisions

| Risk/decision | Evidence/confidence | Controls | Residual/authority | Trigger |
| --- | --- | --- | --- | --- |
| Filesystem JSON/Qdrant dual persistence may drift | CVG config, services, migration docs / high | characterize commit/reindex/delete/restart before migration | target storage decision is human-owned | any Phase 1 schema move |
| Professor lock has no observed release call | `src/core/processor.ts`, `src/lib/redis-lock.ts` / high | characterize TTL and contention; do not fix in Phase 0 | release semantics require explicit design and owner-safe unlock | Phase 1 concurrency work |
| Locker unlock accepts no owner value | `modulo-redis-locker/server.js` / high | black-box negative characterization; no public deployment | security fix requires contract/version decision | any shared-lock use |
| OpenAI/Qdrant/Redis defaults differ across components | configs and compose example / high | document collection/URL/model matrix | canonical provider boundary is human-owned | target layout decision |
| Current frontend lockfile is unsynchronized | `npm ci` output / high | preserve lockfile; do not run `npm install` in Phase 0 | dependency update needs owner approval | frontend build gate |
| Docker/Python prerequisites are absent | command observations / high | use only isolated available checks; mark blocked | environment provisioning decision | live integration gate |

## Idempotence and Recovery

All documentation and control-plane edits are additive or append-only. Re-run
static commands from the workspace root. Use a fresh temporary Redis port and
temporary data directory for each runtime probe; stop only processes started by
this plan. Never touch the existing Redis on 6379, Qdrant on 6333, Git history,
or user data. If a probe fails, retain its command/result in the baseline and
continue with independent checks. On session recovery, read this plan and all
`.agent` ledgers, check child Git status, verify which temporary processes still
belong to this task, and resume at the first unchecked concrete step. There is
no Phase 0 rollback beyond removing only newly created untracked audit artifacts
if the user explicitly requests that cleanup; source repositories must remain
recoverable.

## Artifacts and Evidence

- `docs/architecture/current-system.md`: current cross-system architecture,
  flows, data model, integrations, and evidence labels.
- `docs/baselines/`: raw machine-readable characterization/performance results,
  environment snapshot, command transcript references, and replay recipes.
- `tests/phase0/`: narrowly scoped current-contract characterization and
  deterministic local performance harnesses; no production source changes.
- `docs/progress/phase-0-report.md`: required user-facing report, status table,
  exit criteria, promotion recommendation, and Phase 1 proposal.
- `.agent/state.json`: current classification, active plan/task, next gate/action.
- `.agent/backlog.json`: auditable Phase 0 tasks and evidence links.
- `.agent/execution-log.jsonl`: append-only lifecycle events.
- `.agent/verification.jsonl`: procedures, results, freshness, artifacts, and
  limitations.

Plan revision note, 2026-08-31: created after discovery confirmed independent
repositories, missing Python/Docker prerequisites, and current Node lockfile
drift. The independent critique then required control-plane reconciliation,
literal A-O traceability, replayable benchmark commands, and citation/path
corrections; those were applied without changing runtime source. The plan
remains deliberately Phase 0-only and will be revised when fresh runtime
evidence changes the scope or ordering.
