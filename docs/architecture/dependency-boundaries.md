# Dependency boundaries

Status: `CURRENT` for the Phase 1.1 skeleton. The machine-readable contract in
[`dependency-boundaries.json`](dependency-boundaries.json) is normative; this
document explains its intent and migration controls.

## Direction

```text
apps -> packages -> shared/contracts
tests -> apps/packages/legacy adapters
infrastructure -> apps/packages
```

`apps` own transport, composition, and user-facing concerns. `packages` own
domain or platform contracts. `packages/shared` and `packages/contracts` are
dependency-light foundations. Tests may inspect a boundary, but production
code may not depend on tests.

No package may import an application, UI implementation, or a preserved legacy
directory. No new app may import another app or reach into a preserved child
repository. Cross-system migration must go through a typed, versioned contract
and an adapter with an explicit expiry condition.

## Protected legacy boundaries

The following are preserved source/history boundaries in Phase 1.1:

- `cvg-master-rag-v2/`
- `rick-professor/`
- `modulo-redis-locker/`

Root orchestration may invoke their documented commands for verification. It
must not move, duplicate, or rewrite their runtime code. Their nested Git
repositories and local worktrees are inspected separately from the root Git
snapshot when that metadata is present. A clean root checkout must retain and
validate the tracked child snapshot even though nested `.git` metadata is not
part of the root tree; see
[`preserved-components.json`](preserved-components.json).

## Enforceable checks

`python3 scripts/phase11/check_skeleton.py` verifies:

- the expected app/package/infrastructure/test directories exist;
- skeleton directories contain documentation only in Phase 1.1;
- protected child snapshots remain present; workspaces with nested Git metadata
  additionally prove each independent child HEAD;
- no root diff touches a preserved child path;
- required root commands and toolchain files exist; and
- source files, if introduced accidentally, do not cross forbidden imports.

The check is intentionally conservative. A future exception requires changing
the contract and its tests in a later phase; it must not be smuggled in via a
new relative import.
