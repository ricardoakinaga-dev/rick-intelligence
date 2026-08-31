# Phase 1.1 — Monorepo Skeleton & Migration Safety

Status: `VERIFIED_CANDIDATE` (opened and verified 2026-08-31). This is the
user-authorized first Phase 1 slice. It is intentionally limited to a root
skeleton, contracts, commands, documentation, and safety checks. It does not
extract or run a new Phase 1 application.

## Goal and definition of done

Create one authoritative root repository experience around the three
preserved components while keeping their runtime and histories unchanged. The
phase is complete only when the root structure, pins, commands, dependency
rules, migration map, and evidence are present; existing suites remain
invocable without masking known failures; an independent read-only reviewer
has inspected the result; and a fresh final verification records the outcome.

The previous Phase 0.6 gate remains `BLOCKED / NOT_PROMOTED`. This phase is a
reversible, root-only foundation explicitly authorized by the current request;
it does not reopen, promote, or rewrite that gate.

## Current state and evidence

| Observation | Current evidence |
| --- | --- |
| Root | `main`, `HEAD == origin/main == f372582749c9a094814c49f29b12ca8f52db61ac`; `.agent/state.json` was already modified before this phase. |
| CVG child | independent `main` at `b78221793372552761c13febe36208172cf4586e`; local Phase 0.5/0.6 changes are preserved. |
| Professor child | independent `main` at `692290da8eb4a10fcec83dc19f358ab9643aa3`; local Phase 0.5/0.6 changes are preserved. |
| Locker child | independent `main` at `69e7896cf783f196cf32f56b05607643811ada43`; local Phase 0.5/0.6 changes are preserved. |
| Root tooling before this phase | no root `Makefile`, manifest, compose, `apps/`, or `packages/`. Existing root CI and Phase 0 scripts are preserved. |
| Local tools | Python `3.12.3`, Node `22.19.0`, npm `10.9.3`; Docker is unavailable. The project CVG virtualenv and child `node_modules` are present. |
| Previous gate | `.agent/gates/phase-0.6-promotion-final.json` is historical `BLOCKED`; its missing corpus and external evidence remain open. |

The root Git snapshot contains child files as normal trees while this workspace
also has independent `.git` metadata and dirty child worktrees. The
preservation manifest makes the dual representation explicit: a clean root
checkout validates the tracked child snapshot, while a workspace with nested
metadata additionally validates each independent child HEAD. This is a
migration risk, not a reason to merge or discard either history.

## Frozen quality bar v1

| ID | Dimension | Required target | Evidence method | Priority |
| --- | --- | --- | --- | --- |
| PH11-REPO | migration safety | `apps/`, `packages/`, `infrastructure/`, and root test categories exist as documentation-only placeholders; all three child snapshots remain present; workspaces with nested metadata additionally prove independent child HEADs; no root diff touches a child path | `python3 scripts/phase11/check_skeleton.py`, Git status/diff, child `git rev-parse` when metadata is present | critical |
| PH11-TOOLCHAIN | reproducibility | central root pins and installation policy exist without replacing child lockfiles or inventing a floating workspace | inspect `toolchain.json`, `.env.example`, docs, lockfiles; run `make validate` | high |
| PH11-COMMANDS | operability | required root command names exist; implemented commands delegate real existing commands; unavailable `dev/up/logs` paths fail explicitly and do not create fake runtime | `make help`, `make validate`, targeted root commands | high |
| PH11-BOUNDARIES | maintainability/security | machine-readable direction forbids app/package-to-legacy and app-to-app imports; the validator rejects a known forbidden source pattern | validator implementation/inspection and execution | critical |
| PH11-REGRESSION | compatibility | preserved component tests/builds remain invocable from the root; no known Phase 0.6 failure is hidden or relabeled | `make test-fast`, `make test`, child worktree/diff inspection | critical |
| PH11-DOCS | traceability | target architecture, migration mapping, plan, progress report, and recovery/limitations describe the observed state without claiming future code exists | document inspection and cross-reference check | high |
| PH11-REVIEW | independent judgment | fresh read-only reviewer compares the artifact to all required criteria and reports the largest remaining gap | independent reviewer artifact/response | critical |

The known Phase 0.6 corpus red surface and unavailable Docker/external
evidence are pre-existing limitations. They must remain visible in the Phase
1.1 report and cannot be converted into a Phase 1.1 pass by skipping tests.

## Scope and constraints

In scope:

- root `README.md`, `CONTRIBUTING.md`, `.env.example`, `.editorconfig`,
  `Makefile`, and machine-readable toolchain/boundary contracts;
- empty application/package/infrastructure/test boundaries with README
  placeholders;
- root command orchestration around existing safe component commands;
- target architecture, ownership, dependency, and migration documentation;
- root Phase 1.1 control-plane updates and independent review evidence.

Out of scope:

- moving, copying, deleting, or rewriting runtime code, tests, lockfiles,
  Dockerfiles, or manifests in the three components;
- implementing `apps/web`, `apps/api`, `apps/worker`, or any package;
- PostgreSQL, object storage, root compose, migrations, provider changes,
  authentication changes, ACL changes, UI redesign, deployment, or production
  operations;
- modifying `.git` metadata, branches, remotes, child history, `.runtime`
  service state, secrets, or external systems.

Applicable instructions are `cvg-master-rag-v2/AGENTS.md` for the preserved CVG
boundary, `.agent/PLANS.md` for root continuity, the existing Phase 0.6
plan/gate artifacts, and the installed Gauntlet, Orchestrate, and Engineering
Framework procedures read before this plan.

## Target architecture and dependency contract

The target shape is documented in
[`docs/architecture/target-system.md`](../architecture/target-system.md).
The root direction is:

```text
apps -> packages -> shared/contracts
tests -> apps/packages/legacy adapters
infrastructure -> apps/packages
```

The authoritative machine-readable rules are
[`docs/architecture/dependency-boundaries.json`](../architecture/dependency-boundaries.json)
and the preservation policy is
[`docs/architecture/preserved-components.json`](../architecture/preserved-components.json).
The validator is `scripts/phase11/check_skeleton.py`. Phase 1.1 permits only
placeholder documentation in new boundaries, making accidental runtime
movement fail closed.

## Workstreams and ownership

| Task | Owner | Owned paths | Dependencies | Validation |
| --- | --- | --- | --- | --- |
| PH11-DESIGN | Lead | `docs/architecture/`, `docs/plans/`, `.agent/plans/` | recovered Phase 0.6 state | cross-reference and plan inspection |
| PH11-SKELETON | Lead | root config/docs, `apps/`, `packages/`, `infrastructure/`, root test categories, `scripts/phase11/` | design and implementation-ready gate | `make validate`, root command checks, diff inspection |
| PH11-REVIEW | fresh read-only reviewer | review artifact only, returned to Lead for recording | candidate skeleton and current evidence | criterion-by-criterion independent review |
| PH11-FINAL | Lead integrator | `.agent` state/backlog/ledgers, final gate/report | review and regression evidence | integrated verification and final gate |

The Lead is the only writer for shared control-plane files. Scouts were
read-only and did not edit any lane.

## Migration mapping

The durable source-to-target map is
[`docs/architecture/migration-map.md`](../architecture/migration-map.md). The
required sequence for every future extraction is:

```text
preserved implementation -> versioned contract/adapter -> new package/app
-> dual verification -> caller switch -> legacy removal after equivalence
```

The CVG UI/API/ingestion, Professor orchestration/provider, and Locker lease
boundaries are reserved but remain authoritative in their existing paths.
Persistence migration is explicitly deferred until dual-read/write,
reconciliation, rollback/roll-forward, and restore evidence exist.

## Root command contract

`Makefile` exposes `bootstrap`, `validate`, `dev`, `test`, `test-fast`,
`test-integration`, `lint`, `typecheck`, `build`, `up`, `down`, `logs`, `ci`,
and `eval`. `scripts/phase11/runner.py` delegates to real preserved commands
and aggregates failures without hiding them. `dev`, `up`, and `logs` return an
explicit `NOT_READY`/`NOT_AVAILABLE` result until a canonical root runtime or
compose exists. `down` is a safe no-op when no root stack exists.

`make test` intentionally includes the full CVG suite and frontend smoke; the
known fixture-dependent Phase 0.6 failures remain a visible nonzero result.
`make test-fast` covers the root validator plus focused CVG contract/security,
Professor, and Locker tests. Integration/eval use only disposable loopback
resources through the existing Phase 0.5 scripts.

## Recovery and rollback

All Phase 1.1 additions are local and reversible by removing only the new root
files after inspecting the diff; no child path is a valid rollback target.
`make bootstrap` may update ignored dependency/runtime directories but does not
alter tracked source or lockfiles. Integration helpers stop only processes
they started and never touch host Redis port `6379`. If a check fails, retain
the failure, classify it as pre-existing versus regression, fix only the
bounded root cause, and rerun the focused check before the regression surface.

On interruption, read `.agent/state.json`, this plan, `.agent/backlog.json`,
the latest ledger records, the Phase 0.6 gate, and current Git/child statuses.
The executable next action is always the first incomplete criterion in this
plan; never infer that a command ran from an incomplete log entry.

## Progress

- [x] Recovery and read-only architecture/toolchain scouts completed.
- [x] Quality bar, ownership, target architecture, and migration map drafted.
- [x] Root skeleton and command runner validated.
- [x] Preserved regression surface rerun and limitations recorded without hiding the full-suite corpus red.
- [x] (2026-08-31T15:04:24Z) Fresh independent Round 3 review and append-only revalidation recorded; no material Phase 1.1 gap remained.
- [x] (2026-08-31T15:00:44Z) Final verification and bound `VERIFIED` gate completed; Phase 1.2 remains closed.
