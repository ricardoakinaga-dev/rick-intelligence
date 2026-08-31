# Contributing to RICK Intelligence

## Scope discipline

The root repository coordinates three preserved component repositories. Keep
their histories and local changes intact. A Phase 1.1 change must not move,
rewrite, delete, or duplicate runtime code from `cvg-master-rag-v2`,
`rick-professor`, or `modulo-redis-locker`.

Use a strangler migration: define a contract, add an adapter/package, prove
equivalence, switch one caller, and remove a legacy path only after fresh
regression and integration evidence. Do not import one preserved component
directly into another.

## Local workflow

1. Read the applicable `AGENTS.md` before changing a nested component.
2. Inspect `git status` in the root and in every child repository.
3. Run `make validate` before and after root changes.
4. Run the narrowest relevant command first, then `make test-fast` and the
   affected component checks.
5. Run `make ci` for root foundation changes. Run `make test` when the change
   affects preserved behavior or test orchestration.
6. Record unavailable services, fixture-dependent failures, and external gates;
   never hide them with skips, xfails, mocks at the boundary under test, or
   relaxed thresholds.

## Boundaries

The dependency direction is `apps -> packages -> shared/contracts`. Packages
must not import applications, UI modules, or legacy component paths. The
enforceable source of truth is
[`docs/architecture/dependency-boundaries.json`](docs/architecture/dependency-boundaries.json).

Root orchestration may invoke preserved component commands, but it must not
silently alter their source, lockfiles, data, services, or credentials.

## Secrets and data

Never commit `.env`, tokens, passwords, private keys, provider responses, or
unnecessary personal data. Use disposable loopback services and synthetic
fixtures for tests. Do not run destructive migrations, resets, deployments,
force pushes, or production operations from a normal development task.

## Evidence

Every material change needs exact commands and honest results. A worker or
builder may provide evidence but does not approve its own work. Root phase
artifacts belong in `docs/plans/`, `docs/progress/`, and the existing control
plane when continuity requires it.
