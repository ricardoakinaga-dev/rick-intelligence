# Phase 1.1 — Monorepo Skeleton & Migration Safety

## Purpose / Big Picture

Create a root-level, documentation-first monorepo boundary around the three
preserved RICK Intelligence systems. A contributor should be able to discover
the target applications/packages, run one root validation/test command, and see
exactly what remains legacy. Success is demonstrated by the root validator,
preserved child Git identities, focused regression commands, and a fresh
read-only review. No Phase 1.2 runtime extraction is part of this plan.

## Progress

- [x] (2026-08-31T10:49:18-03:00) Recovered the Phase 0.6 blocked state, read the required attachment and applicable instructions, and captured root/child Git/toolchain evidence.
- [x] (2026-08-31T10:49:18-03:00) Froze the Phase 1.1 quality bar and ownership boundaries in the public plan.
- [x] Root skeleton, command runner, boundary validator, preserved regression, integration, evaluation, static checks, and build have fresh verification; the full corpus-dependent red remains visible.
- [x] (2026-08-31T15:04:24Z) Independent Round 3 review passed; earlier review scopes were revalidated append-only.
- [x] (2026-08-31T15:00:44Z) Final verification and `GATE-PH11-VERIFIED-001` completed; Phase 1.2 remains closed.

## Surprises & Discoveries

- Observation: the root tracks normal file trees for the three children while this workspace also has independent `.git` metadata and local Phase 0.5/0.6 changes; a clean CI checkout has only the root snapshot.
  Evidence: `git ls-tree HEAD -- cvg-master-rag-v2 rick-professor modulo-redis-locker`; `git -C <child> rev-parse --show-toplevel`; child `git status`.
  Impact: the preservation manifest and validator must preserve both identities, validate the root snapshot in clean CI, and validate child HEADs when local metadata is present; root diffs touching child paths remain rejected during Phase 1.1.
- Observation: `.agent/state.json` was already modified and declared a clean root worktree although Git reported that state-file change.
  Evidence: `git diff -- .agent/state.json`; `python3 scripts/phase06/check_control_plane.py`.
  Impact: the historical Phase 0.6 state/gate must remain visible; Phase 1.1 uses a separate active task and records the scope transition rather than cleaning the file.
- Observation: Docker is unavailable locally, while Python 3.12.3, Node 22.19.0, npm 10.9.3, the CVG virtualenv, and child Node dependencies are available.
  Evidence: version commands and dependency-directory checks.
  Impact: root compose lifecycle is guarded; local checks focus on structure and available preserved suites.
- Observation: preserved Professor tests emit a tracked raw report and Next production builds rewrite the preserved `frontend/next-env.d.ts` reference.
  Evidence: the first root test/build pass exposed both changes; the root runner now snapshots and restores the exact pre-command bytes.
  Impact: root evidence commands remain repeatable without leaking disposable generated output into protected child paths.
- Observation: the Phase 0.5 service start script can start only the missing member of a Qdrant/Redis pair.
  Evidence: `scripts/phase05/start-local-services.sh` checks each service independently.
  Impact: the Phase 1.1 runner now records pre-existing PID files and stops only newly recorded service PIDs, including partial-readiness cases.

## Decision Log

- Decision: proceed with a root-only Phase 1.1 slice despite the historical Phase 0.6 promotion block.
  Context: the current user request explicitly authorizes “START WITH PHASE 1.1 ONLY” and limits the slice to skeleton/migration safety.
  Alternatives: stop all Phase 1 work until Phase 0.6 becomes `VERIFIED_CANDIDATE`; begin extracting runtime code.
  Reason: a no-runtime, additive foundation is reversible and does not claim or alter Phase 0.6 promotion; runtime extraction would violate the requested phase boundary.
  Consequences: the old blocked gate remains historical evidence and Phase 1.2 stays locked until the new Phase 1.1 verification gate passes.
  Date/Author: 2026-08-31 / Codex Lead.
- Decision: keep child lockfiles and independent Git histories instead of creating a root package workspace.
  Context: the frontend has both npm and pnpm lockfiles and the child snapshots contain intentional Phase 0 overlays.
  Alternatives: normalize package managers now; convert children to submodules.
  Reason: either action would change behavior/history before contracts and equivalence evidence exist.
  Consequences: root commands delegate to each child and the future contract package remains empty.
  Date/Author: 2026-08-31 / Codex Lead.
- Decision: fail closed for root `dev`, `up`, and `logs` until canonical apps/compose exist.
  Context: the existing Professor compose references missing paths and does not run the CVG app.
  Alternatives: copy the old compose or invent a partial root stack.
  Reason: a truthful unavailable command is safer than a misleading deployment surface.
  Consequences: Phase 1.1 provides command names and migration guidance; runtime startup is a later milestone.
  Date/Author: 2026-08-31 / Codex Lead.

## Outcomes & Retrospective

The outcome is an additive root skeleton with no protected child-path root
edits, explicit command availability, dual-mode preservation checks, a
traceable migration map, and a bound `VERIFIED` gate. The gauntlet found two
validator-coverage defects during independent review; both were corrected and
retested. The full preserved CVG corpus remains visibly blocked by missing
historical data, and Phase 1.2 is not opened by this result.

## Context and Orientation

The project root is `/home/ricardo/Área de trabalho/rick-intelligence`.
`cvg-master-rag-v2` is Python/FastAPI plus Next.js; `rick-professor` is
TypeScript/Fastify; `modulo-redis-locker` is JavaScript/Express. Their current
entrypoints and behavior remain in those directories. The current system map
is `docs/architecture/current-system.md`; the previous closure plan is
`.agent/plans/phase-0.6-promotion-closure.md` and its final gate is
`.agent/gates/phase-0.6-promotion-final.json`.

## Scope and Constraints

- In scope: root docs/config, placeholder app/package/infrastructure/test directories, root Make commands, machine-readable toolchain/dependency contracts, migration map, validation/review artifacts, and control-plane continuity.
- Out of scope: runtime moves/copies/deletes, child source/test/manifest/lockfile edits, database/object-storage migration, root compose, frontend redesign, provider/auth/ACL changes, production or external mutations.
- Applicable instructions: `cvg-master-rag-v2/AGENTS.md`, `.agent/PLANS.md`, existing Phase 0.6 plan/gate, and the loaded Gauntlet/Orchestrate/Engineering Framework references.
- Requirements/decisions: user attachment sections 5–12, 62–64, 80–85; `docs/architecture/current-system.md`; `docs/architecture/contracts/rag-contract-v1.md`; existing Phase 0.6 evidence.
- Tier/risk/blast radius: `T4_CRITICAL`, `MEDIUM`, `CROSS_SYSTEM`; the tier floor follows the framework rule for a cross-system control-plane change, while the bounded additive scope keeps residual risk at MEDIUM.
- Authorization constraints: current request authorizes Phase 1.1 only; no production, deployment, credential, destructive, child-history, or Phase 1.2 runtime action is authorized.

## Architecture and Interfaces

The target direction is `apps -> packages -> shared/contracts`; tests may
inspect production boundaries and infrastructure may compose them, but domain
packages must not import apps/UI or legacy paths. `packages/contracts` will
eventually own canonical serialized types, including `rag-contract-v1`,
identity, evidence, job, provider-error, and lock-lease schemas. In this phase
it is a README-only placeholder. `docs/architecture/dependency-boundaries.json`,
`docs/architecture/preserved-components.json`, and
`docs/architecture/migration-map.md` are the current root contracts.

## Milestones

### Milestone 1 — Root foundation

- Outcome: root files, command runner, and documentation-only directories exist.
- Scope/dependencies: no child path may be modified; use the frozen pins and target tree.
- Demonstration: `make validate` prints a PASS and lists preserved child HEADs.
- Acceptance/evidence: PH11-REPO, PH11-TOOLCHAIN, PH11-COMMANDS, PH11-BOUNDARIES, PH11-DOCS.

### Milestone 2 — Preserved regression and independent review

- Outcome: real available child checks run through root commands and a fresh reviewer judges the artifact.
- Scope/dependencies: use only disposable local integration state; preserve known Phase 0.6 red results.
- Demonstration: `make test-fast` and relevant `make lint/typecheck/build` outputs plus review artifact.
- Acceptance/evidence: PH11-REGRESSION and PH11-REVIEW.

## Plan of Work

1. Freeze the design, implementation-ready gate, and task ledger.
2. Add root config/contracts/placeholders and the phase11 validator/runner.
3. Inspect the diff and run `make validate`, then targeted root checks.
4. Run focused preserved suites and available build/lint/type checks; run full/integration commands where their prerequisites are available.
5. Ask a fresh read-only reviewer to compare the complete artifact to the frozen bar without builder rationale.
6. Fix only a material root gap, rerun affected checks, and record final verification/gate/report. Do not open Phase 1.2.

## Concrete Steps

From `/home/ricardo/Área de trabalho/rick-intelligence`:

1. `python3 scripts/phase11/check_skeleton.py` — validate root skeleton and protected child paths.
2. `make help && make validate` — validate the public command surface.
3. `make test-fast` — run focused preserved regression checks.
4. `make lint && make typecheck && make build` — run available static/compiler/build checks.
5. `make test-integration` and `make eval` — run only with disposable loopback Qdrant/Redis; record unavailable prerequisites.
6. Inspect `git diff --name-status`, child `git status`, and all generated evidence before finalizing.

## Validation and Acceptance

| Criterion | Required | Procedure/environment | Expected observation | Evidence destination |
| --- | --- | --- | --- | --- |
| PH11-REPO | YES | skeleton validator, root/child Git inspection | placeholders and tracked child snapshots exist; local child repos resolve when metadata is present; no root child-path diff | `.agent/verification.jsonl`, final report |
| PH11-TOOLCHAIN | YES | inspect `toolchain.json`, `.env.example`, lockfiles; `make validate` | pins match observed Phase 0 baseline; no lockfile replacement | `.agent/verification.jsonl`, toolchain docs |
| PH11-COMMANDS | YES | `make help`, targeted root commands | names exist; real commands delegate; unavailable runtime guarded | `.agent/verification.jsonl`, final report |
| PH11-BOUNDARIES | YES | validator and source scan | forbidden app/package/legacy patterns fail closed | `scripts/phase11/check_skeleton.py`, verification |
| PH11-REGRESSION | YES | `make test-fast`; broader commands as available | no new child regression; known historical red remains visible | verification ledger, report |
| PH11-DOCS | YES | cross-reference/accuracy inspection | current vs proposed state is explicit | plan/report/architecture docs |
| PH11-REVIEW | YES | fresh read-only review | criterion results, largest gap, severity/confidence, decision | independent review/report |

## Risks and Human Decisions

| Risk/decision | Evidence/confidence | Controls | Residual/authority | Trigger |
| --- | --- | --- | --- | --- |
| Root snapshot and child Git histories can diverge | direct Git inspection / high | protected paths, child HEAD capture, no child-path root diff | medium; no external approval required for additive scaffold | any source move or child content edit |
| Previous Phase 0.6 gate is blocked | final gate/report / high | preserve historical gate; do not claim promotion | remains blocked; corpus/owner waiver/external evidence needed for its reopening | request to promote Phase 0.6 or begin runtime extraction |
| Existing pins conflict across child docs/compose | current-system/scout / high | root pin record; retain child files until contract migration | compatibility remains unproven | root runtime/compose implementation |
| Docker and live provider are unavailable | command observation / high | explicit NOT_AVAILABLE/NOT_RUN results; no fake compose | external evidence missing | integration/deployment phase |

## Idempotence and Recovery

All created root directories/files are additive. Re-running the validator is
read-only. `npm ci` and the existing CVG bootstrap may replace ignored
dependency/runtime directories only; they do not rewrite tracked component
source or lockfiles. Integration startup uses loopback ports 6337/6380 and
stops only processes started by the runner. On recovery, reconcile current Git,
child HEADs/status, `.agent/state.json`, backlog, ledgers, this plan, and the
last verification before retrying. Never delete child changes or reset history.

## Artifacts and Evidence

- `docs/plans/phase-1.1-monorepo-skeleton.md`: public plan, bar, ownership, and migration scope.
- `docs/architecture/target-system.md`: proposed target tree, not implemented runtime.
- `docs/architecture/migration-map.md`: source-to-target extraction and removal gates.
- `docs/architecture/dependency-boundaries.json`: machine-readable import/protection rules.
- `docs/architecture/preserved-components.json`: clean-checkout snapshot and optional nested-Git preservation policy.
- `scripts/phase11/check_skeleton.py`: deterministic structural/boundary validator.
- `scripts/phase11/runner.py`: root command dispatcher with honest failure propagation.
- `.agent/verification.jsonl`: exact current procedures and limitations.
- `docs/progress/phase-1.1-report.md`: final phase report and classification.
- `.agent/gates/phase-1.1-verified.json`: bound final verification gate for the bounded root-only scope.
- `docs/progress/phase-1.1-independent-review.md`: three independent review rounds and append-only revalidation.

Plan revision note, 2026-08-31: created after recovery and read-only scouts;
the original Phase 0.6 blocked gate is preserved, while the current user
request explicitly opens only the additive Phase 1.1 foundation.
