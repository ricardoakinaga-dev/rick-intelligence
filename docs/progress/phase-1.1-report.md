# RICK Intelligence — Phase 1.1 Report

## Final Classification

`VERIFIED_CANDIDATE` — the Phase 1.1 root foundation passed the bound
`VERIFIED` gate (`GATE-PH11-VERIFIED-001`). This classification applies only to
the additive skeleton/migration-safety scope; it is not a Phase 0.6 promotion,
production release, or Phase 1.2 authorization.

## Executive Summary

Phase 1.1 establishes the root monorepo boundary and migration-safety
contracts around the three preserved component repositories. It does not move
runtime code, replace child toolchains, create a root compose stack, or claim
that Phase 0.6 promotion is unblocked.

The historical Phase 0.6 result remains `BLOCKED / NOT_PROMOTED` because its
approved corpus and external evidence are unavailable. The current Phase 1.1
slice is separately authorized and root-only.

## Architecture Before

The root had control-plane files, documentation, scripts, and CI, but no root
Makefile, central environment contract, application/package boundary, or
unified command runner. `cvg-master-rag-v2`, `rick-professor`, and
`modulo-redis-locker` were independent Git repositories with preserved local
Phase 0.5/0.6 changes. Their current entrypoints remain the authoritative
runtime.

## Architecture After

The root now defines an additive `apps/`, `packages/`, `infrastructure/`, and
root `tests/` boundary with documentation-only placeholders. It adds a pinned
toolchain contract, canonical environment template, root Make commands, a
machine-readable dependency rule set, and a validator that rejects child-path
root changes and forbidden future imports. No Phase 1.2 runtime exists in the
new directories.

## Monorepo Structure

See [`docs/architecture/target-system.md`](../architecture/target-system.md)
for the proposed tree and the placeholder READMEs under `apps/`, `packages/`,
`infrastructure/`, and root test categories. The target remains `PROPOSED`; the
placeholders are the only Phase 1.1 content in those boundaries.

## Packages and Apps

The package/app directories are reserved for identity, authorization,
knowledge, ingestion, retrieval, Professor, providers, storage, locking,
audit, observability, contracts, shared primitives, web, API, and worker.
Their implementation is explicitly deferred to Phase 1.2+.

## Identity, RBAC, Knowledge, Ingestion, Retrieval, Professor, Web, Admin, Clinical Workspace, Worker

These domains remain in the preserved CVG/Professor/Locker implementations.
Phase 1.1 records ownership and extraction seams only; it does not duplicate
or change their behavior. The future `/app` and `/admin` separation is a target
contract, not an implemented route in this phase.

## Persistence, Security, CI, Tests, Performance, Migration, Compatibility

- Persistence remains filesystem JSON/Redis/Qdrant as documented in the current
  system map; PostgreSQL/object storage migration is deferred.
- Existing identity, ACL, citation, provider, and owner-safe Locker evidence
  remains under the Phase 0.6 artifacts; no Phase 1.1 security behavior changes.
- The root adds a Phase 1.1 foundation workflow and commands while preserving
  the existing Phase 0.6 historical workflow and checks.
- Tests are delegated to preserved suites without masking the known historical
  corpus red surface. Integration/evaluation use disposable loopback state.
- No new performance claim is made; existing Phase 0.5 baselines remain the
  comparison source.
- The migration map requires contract, dual verification, caller switch, and
  rollback/removal evidence before legacy paths may be deleted.

## Current Verification State

The current root-only verification is:

| Check | Result | Evidence/limitation |
| --- | --- | --- |
| `make bootstrap` | `PASS` | Existing CVG runtime bootstrap and all three preserved npm lockfile installs completed; no tracked child file changed. |
| `make help`, `make validate` | `PASS` | All required root targets are exposed; 28 placeholders are present; local nested child HEADs remain independently resolvable and the tracked child snapshot policy is validated; no root status path touches a child. |
| Clean-checkout preservation fixture | `PASS` | A temporary root fixture with nested child `.git` metadata omitted passed the validator and reported all three components in `PROTECTED_CHILD_SNAPSHOT_ONLY`, proving the CI branch uses tracked root snapshots. |
| Boundary regression | `PASS` | `python3 -m unittest scripts/phase11/test_check_skeleton.py` returned 4 tests OK, including the clean-checkout policy, dual-mode root snapshot assertion, and a synthetic forbidden legacy-pattern rejection. |
| `make test-fast` | `PASS` | CVG focused contract/security suite: 40 passed; Professor: 37 passed; Locker: 2 passed. The runner restores Professor's disposable report artifact after the command. |
| `make ci` after first review remediation | `PASS` | Validator, 3 boundary tests, focused preserved suites, lint, typecheck, and builds returned exit 0; the root runner restored generated child artifacts. |
| `make ci` after dual-mode snapshot fix | `PASS` | Validator, 4 boundary tests, focused preserved suites, lint, typecheck, and builds returned exit 0; the clean-checkout fixture also passed with all three components in snapshot-only mode. |
| `make lint` | `PASS` | Root Python syntax, Locker JavaScript syntax, and frontend lint passed. |
| `make typecheck` | `PASS` | Professor TypeScript, frontend TypeScript with the documented `--ignoreDeprecations 5.0` compatibility override, and CVG Python compilation passed. |
| `make build` | `PASS` | Professor build, frontend production build, and CVG Python compilation passed; generated frontend `next-env.d.ts` is restored by the root runner. |
| `make test-integration` | `PASS` | Final disposable loopback Qdrant/Redis, deterministic CVG full/restart probes, three non-leakage tests, and real Locker HTTP lease checks passed; only runner-started services were stopped. |
| `make eval` | `PASS` | Final deterministic non-live Phase 0.5 RAG plumbing evaluation passed with stable document identity, scoped retrieval, citation checksum, and no duplicate points. |
| `make test` | `BLOCKED_PREEXISTING` | The full preserved CVG suite remains visibly red because `src/data/default/dataset.json` and the approved corpus are absent: current direct reproduction was 382 passed, 12 failed, 17 skipped, and 4 errors. Professor (37), Locker (2), and frontend smoke (7) passed. |
| `make dev`, `make up`, `make logs`, `make down` | `NOT_READY` / `NOT_APPLICABLE` | Docker is unavailable and no canonical root compose exists in Phase 1.1; guarded commands make no external state change. |
| Phase 1.1 final gate | `PASS` | `GATE-PH11-VERIFIED-001` is bound to `VER-PH11-FINAL-CURRENT`; Round 3 independent review passed and earlier review findings were revalidated append-only. |
| Generic engineering-framework audit | `BLOCKED_HISTORICAL` | The checker still reports 55 pre-existing Phase 0/0.5/0.6 ledger incompatibilities; no Phase 1.1-specific finding remains. The phase-aware control-plane check passes. |

The full-suite red result is not relabeled as a Phase 1.1 pass and does not
reopen the historical Phase 0.6 gate. The root command remains runnable and
continues through the preserved component lanes so the failure surface stays
visible.

## Remaining Risks

- The root snapshot and independent child Git histories are dual authorities;
  clean CI retains only the root snapshot, while local nested metadata supplies
  independent child HEAD evidence; future extraction must reconcile them
  explicitly.
- The first two independent review rounds found and closed clean-checkout and
  dual-mode snapshot coverage defects; Round 3 passed, and the earlier review
  streams were revalidated append-only.
- Child docs/compose use conflicting pins and one references missing paths;
  this is recorded, not silently normalized.
- Docker, live provider, historical corpus/waiver, Python audit, production
  networking, and branch protection evidence remain unavailable.
- The preserved frontend compiler/configuration pins are temporarily
  inconsistent; the root check records the compatibility override and leaves
  the child configuration unchanged.
- A root `dev/up/logs` runtime is intentionally not ready until canonical apps
  and compose are implemented.

## Deferred Work

Phase 1.2 must not begin until the Phase 1.1 final verification gate passes.
The next approved scope is shared contracts/identity/authorization extraction,
with no caller switch until dual verification is available.

## Promotion Decision

`VERIFIED_CANDIDATE` for the bounded Phase 1.1 root-only scope. The final gate
is [`GATE-PH11-VERIFIED-001`](../../.agent/gates/phase-1.1-verified.json), bound
to `VER-PH11-FINAL-CURRENT`. The generic engineering-framework audit still
reports pre-existing Phase 0/0.5/0.6 ledger incompatibilities; the
phase-aware Phase 1.1 control check is green and those historical records were
not rewritten. The separate Phase 0.6 gate remains `BLOCKED / NOT_PROMOTED`,
and Phase 1.2/runtime extraction remains closed.
