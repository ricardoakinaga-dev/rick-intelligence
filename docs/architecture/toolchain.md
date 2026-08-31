# Root toolchain contract

Status: `CURRENT` for Phase 1.1, observed 2026-08-31.

The machine-readable source for the root pins is [`toolchain.json`](../../toolchain.json).
The values preserve the Phase 0.5/0.6 reproducibility baseline rather than
silently normalizing the children to a new version.

| Layer | Pin | Evidence | Scope |
| --- | --- | --- | --- |
| Python | `3.12.3` | `docs/baselines/environment-2026-08-31.json`, `.github/workflows/phase-0.6.yml` | CVG and root Python tooling |
| Node.js | `22.19.0` | `docs/baselines/environment-2026-08-31.json`, `.github/workflows/phase-0.6.yml` | root orchestration, Professor, frontend, Locker tests |
| npm | `10.9.3` | `docs/baselines/environment-2026-08-31.json` | lockfile installation |
| Qdrant | `1.7.4` | Phase 0.5 isolated runtime and CI contract | disposable integration service |
| Redis | `7.0.15` | Phase 0.5 isolated runtime and CI contract | disposable integration service |
| Qdrant Python client | `1.7.3` | `cvg-master-rag-v2/src/requirements.txt` | compatibility with the pinned server |

All Node applications retain their own `package-lock.json`; the root does not
invent an npm workspace before package ownership and contracts exist. Python
dependencies remain in the preserved CVG requirements file during this
foundation phase. Changing a pin requires updating `toolchain.json`, the CI
contract, and a fresh reproducibility record together.

The preserved frontend `tsconfig.json` currently declares
`ignoreDeprecations: 6.0` while its lockfile resolves TypeScript `5.9.3`.
The root `make typecheck` passes the explicit compiler compatibility override
`--ignoreDeprecations 5.0`; it does not edit the child configuration. This
temporary bridge must be removed when the frontend compiler/configuration pins
are reconciled in a separately authorized migration task.

The Locker image still uses its preserved Node 20 base. That is a component
implementation detail and remains unchanged until the Locker is migrated via
an explicit contract and dual verification.

## Installation policy

`make bootstrap` calls the existing CVG runtime bootstrap and runs
`npm ci --ignore-scripts --no-audit --no-fund` in each preserved Node project.
The command is idempotent with respect to tracked source and lockfiles; it may
update ignored dependency/runtime directories. No production service is
started and no secret is read into a report.
