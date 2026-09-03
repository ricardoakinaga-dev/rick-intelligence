# RICK Intelligence

RICK Intelligence is being consolidated from three preserved systems into one
knowledge-intelligence platform:

- `cvg-master-rag-v2/` — the current Python/FastAPI RAG system and native Next.js UI;
- `rick-professor/` — the current TypeScript/Fastify Professor compatibility service;
- `modulo-redis-locker/` — the current JavaScript/Express Redis lease service.

The repository is currently at **Phase 1.3 — Unified API Kernel & Runtime Adapter
Consolidation**. `apps/api` is now the canonical executable platform HTTP boundary
(FastAPI): versioned `/api/v1/*` routes, OpenAI-compatible `/v1/chat/completions`,
typed config + app factory, request context/correlation, canonical errors,
`identity`/`authorization` integration, health/readiness, centralized legacy
adapters, audit/observability hooks, and a 44-test matrix with dual-verification
evidence. Legacy CVG/Professor/Locker servers remain as compatibility/migration
surfaces (see `docs/architecture/api-migration-map.md`); no legacy code is deleted
in this phase. The previous Phase 0.6 promotion gate remains recorded as `BLOCKED`
and Phase 1.1 as `VERIFIED` (root skeleton scope).

## Repository layout

```text
apps/                  future canonical runtime applications
packages/              future reusable domain and platform packages
infrastructure/        future deployment, migration, and operations assets
tests/                 root contract, integration, security, regression, and performance lanes
docs/                  architecture, plans, progress, and evidence
scripts/phase11/       root foundation validators and command orchestration

cvg-master-rag-v2/     preserved CVG implementation (not moved in Phase 1.1)
rick-professor/        preserved Professor implementation (not moved in Phase 1.1)
modulo-redis-locker/   preserved Locker implementation (not moved in Phase 1.1)
```

The intended dependency direction is `apps -> packages -> shared/contracts`.
Domain packages must not import applications, UI code, or legacy component
paths. Legacy systems are consumed through explicit contracts/adapters in a
later phase; direct cross-component imports are not a migration strategy. The
machine-readable rule set lives in
[`docs/architecture/dependency-boundaries.json`](docs/architecture/dependency-boundaries.json)
and is checked by `make validate`.

## Root commands

Run `make help` for the complete list.

| Command | Phase 1.1 behavior |
| --- | --- |
| `make bootstrap` | Installs from the preserved lockfiles and prepares the existing CVG local runtime through its current bootstrap script. |
| `make validate` | Checks the skeleton, protected legacy paths, root commands, toolchain contract, and dependency-boundary rules. |
| `make test-fast` | Runs the root validator and focused CVG, Professor, and Locker regression suites. |
| `make test` | Runs the available full component suites, including the existing frontend smoke command; known Phase 0.6 corpus failures remain visible. |
| `make test-integration` | Uses only disposable loopback Qdrant/Redis state and the existing Phase 0.5 integration probes. |
| `make lint` | Runs the root static checks, Python compilation, JavaScript syntax check, and existing frontend lint. |
| `make typecheck` | Runs the existing TypeScript checks/build compiler and Python syntax/import compilation; no new Python type checker is introduced yet. |
| `make build` | Builds the existing Professor and frontend artifacts and compiles the preserved Python source. |
| `make ci` | Runs the root foundation validation plus fast tests, lint, typecheck, and build. |
| `make eval` | Runs the deterministic, explicitly non-live Phase 0.5 RAG plumbing evaluation. |
| `make api-dev` | Runs the canonical `apps/api` kernel (hermetic by default; legacy opt-in). |
| `make api-test` | Phase 1.3 API matrix (routing/auth/errors/health/compat/streaming/policy). |
| `make api-contract` | OpenAPI generation + required-path check. |
| `make api-security` | Route-policy + negatives + import-boundary checks. |
| `make api-benchmark` | Kernel-overhead p50/p95 observation (stub backend, local). |
| `make dev`, `make up`, `make logs` | Fail closed until a canonical root application/compose boundary exists; they never guess at legacy service wiring. |
| `make down` | Reports that no canonical root stack exists yet and changes no external state. |

For the current component-specific commands and runtime prerequisites, see
[`docs/plans/phase-1.1-monorepo-skeleton.md`](docs/plans/phase-1.1-monorepo-skeleton.md)
and each preserved component README.

## Toolchain

The root contract records Python `3.12.3`, Node.js `22.19.0`, npm `10.9.3`,
Qdrant `1.7.4`, and Redis `7.0.15`. See [`toolchain.json`](toolchain.json) and
[`docs/architecture/toolchain.md`](docs/architecture/toolchain.md). Runtime
secrets are never committed; start from `.env.example` and keep `.env` local.

## Migration rule

Every future extraction must follow:

```text
preserved implementation
  -> explicit contract/adapter
  -> new package or app
  -> dual verification
  -> caller switch
  -> legacy removal only after equivalence evidence
```

The current mapping and exit criteria are in
[`docs/architecture/migration-map.md`](docs/architecture/migration-map.md).
