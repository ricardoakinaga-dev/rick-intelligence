# RICK Intelligence

RICK Intelligence is being consolidated from three preserved systems into one
knowledge-intelligence platform:

- `cvg-master-rag-v2/` — the current Python/FastAPI RAG system and native Next.js UI;
- `rick-professor/` — the current TypeScript/Fastify Professor compatibility service;
- `modulo-redis-locker/` — the current JavaScript/Express Redis lease service.

The repository is now in **Phase 2 — Production Intelligence Runtime
Closure**. `packages/knowledge`, `packages/ingestion` and `packages/retrieval`
remain root-owned implementations with differential parity to validated legacy
behavior; `packages/providers`, `packages/locking`, `packages/evidence`,
`packages/decision` and `packages/professor` provide typed platform boundaries.
`apps/api`, `apps/worker` and `apps/web` contain the canonical public,
durable-job and browser surfaces, while the three legacy systems remain
byte-identical compatibility/migration surfaces.

The current honest classification is **STATE_OF_ART_CANDIDATE**. Local
contracts, deterministic tests, static checks and frontend build evidence are
substantial; live PostgreSQL/Redis/Qdrant/object-storage execution,
multi-worker fencing, distributed observability, restore/chaos/soak,
production-shaped performance, complete API-backed visual states and release
promotion evidence remain open or externally blocked. No production,
`STATE_OF_ART`, `AAA` or `TRIPLE_AAA` claim is made here. A mandatory gate
that is `NOT_RUN`, `BLOCKED_EXTERNAL` or failed keeps the candidate below
promotion.

The current audit is
[`phase-2-current-gap-audit.md`](docs/reports/phase-2-current-gap-audit.md)
and the execution plan is
[`phase-2-production-intelligence-runtime.md`](docs/plans/phase-2-production-intelligence-runtime.md).
The final local report, scorecard and external blocker matrix are
[`phase-2-final-report.md`](docs/progress/phase-2-final-report.md),
[`state-of-art-triple-aaa-final-audit.md`](docs/reports/state-of-art-triple-aaa-final-audit.md)
and [`external-evidence-blockers.md`](docs/reports/external-evidence-blockers.md).
The original request is archived at
[`state-of-art-triple-aaa-2026-09-09.txt`](docs/prompts/state-of-art-triple-aaa-2026-09-09.txt).

## Repository layout

```text
apps/api/              canonical FastAPI boundary (Phase 1.3/1.5)
apps/worker/            canonical durable worker boundary and runtime
apps/web/               canonical root web caller and visual-state surface
packages/              reusable domain and platform packages
infrastructure/        future deployment, migration, and operations assets
tests/                 root contract, integration, security, regression, and performance lanes
docs/                  architecture, plans, progress, and evidence
scripts/phase11/       root foundation validators and command orchestration
scripts/phase15/       Phase 1.5 boundary checks and vertical-slice verification
scripts/phase16/       bounded ingestion lifecycle, benchmark, and verification

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

| Command | Current behavior |
| --- | --- |
| `make bootstrap` | Installs from the preserved lockfiles and prepares the existing CVG local runtime through its current bootstrap script. |
| `make validate` | Checks current root package boundaries, protected legacy paths, and repository layout. |
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
| `make api14-units` | Canonical knowledge/ingestion/retrieval unit suites. |
| `make api14-differential` | Legacy↔root parity, shadow quality, RAG E2E. |
| `make api14-acl` | RAG ACL negative matrix. |
| `make api14-full` | Phase 1.4 units + differential + API matrix + legacy regression. |
| `make api14-benchmark` | Legacy-vs-root perf budget check. |
| `make api15-boundaries` | Current root boundary and preservation validator. |
| `make api15-full` | Phase 1.5 boundaries, contracts, provider, locking, Professor, and root API suites. |
| `make api16-full` | Phase 1.6 boundaries, domain lifecycle, worker seam, readiness, root API, and hermetic benchmark. |
| `make api16-verify` | Sanitized Phase 1.6 matrix plus Phase 1.5/1.4 regression, security, OpenAPI, and whitespace checks. |
| `make web-validate` | Lints, typechecks, builds, and runs the canonical browser matrix at 375/768/1440 against the root API loopback. |
| `make web-e2e` | Runs the canonical browser smoke and writes visual evidence under `artifacts/visual/state-of-art/`. |
| `make dev` | Runs the canonical development Compose lifecycle in the foreground; it fails closed when Docker, required environment or reviewed composition inputs are unavailable. |
| `make up`, `make down`, `make logs` | Operate the selected canonical root Compose file (`RICK_COMPOSE_FILE` may select staging); static configuration is not runtime proof. |
| `make release-evidence` | Generates the ignored, commit-bound release manifest; the release gate still rejects missing, stale, wrong-hash, blocked or not-run mandatory evidence. |
| `make postgres-runtime` | Runs the real PostgreSQL migration/queue/fencing gate from an explicit `RICK_TEST_DATABASE_DSN`; returns `BLOCKED_EXTERNAL` when unavailable. |
| `make redis-runtime` | Runs the real Redis namespace/lease/rate-limit gate from an explicit `RICK_TEST_REDIS_URL`; local semantics do not imply production-safe TLS/auth. |
| `make object-qdrant-runtime` | Runs the real object/vector lifecycle gate from explicit test endpoints; no endpoint discovery or fake transport is used. |
| `make triple-aaa-verify` | Executes the integrated fail-closed packet and writes a redacted ignored result; `0` is reserved for all mandatory lanes passing, `2` means external blocking, `1` means failure. |

For current component-specific commands and runtime prerequisites, see
[`docs/plans/phase-1.1-monorepo-skeleton.md`](docs/plans/phase-1.1-monorepo-skeleton.md)
and [`docs/architecture/professor-provider-locking.md`](docs/architecture/professor-provider-locking.md).
The Phase 2 lifecycle contract and its current gaps are in
[`docs/architecture/ingestion-lifecycle.md`](docs/architecture/ingestion-lifecycle.md),
[`docs/architecture/release-integrity.md`](docs/architecture/release-integrity.md)
and [`docs/operations/release-readiness.md`](docs/operations/release-readiness.md).

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
