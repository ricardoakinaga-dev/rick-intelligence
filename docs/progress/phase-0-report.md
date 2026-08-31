# RICK Intelligence — Phase 0 report

Date: 2026-08-31 UTC  
Scope: current workspace at `/home/ricardo/Área de trabalho/rick-intelligence`  
Decision status: `PARTIAL — NOT PROMOTED`  
Requested promotion target: `VERIFIED_CANDIDATE`

## Objective

Map the system that actually exists before consolidation: languages, frameworks,
entrypoints, stores, APIs, jobs, filesystem, cache/locks, authentication,
telemetry, deployment and OpenWebUI contracts; characterize critical RAG and
concurrency behavior; capture a reproducible performance baseline; identify
risks and preservable components; and propose a final monorepo layout plus a
Phase 1 implementation plan. No Phase 1 implementation was authorized or
performed.

## Repository state before

The workspace root was not a Git repository and contained three independent,
clean child repositories:

| Repository | HEAD | Tracked files / approximate lines | Initial state |
| --- | --- | ---: | --- |
| `cvg-master-rag-v2` | `b78221793372552761c13febe36208172cf4586e` | 391 / 99,802 | clean `main...origin/main` |
| `rick-professor` | `692290da8eb4a10fcec83dc19f358ab9643aa3a3` | 25 / 4,103 | clean `main...origin/main` |
| `modulo-redis-locker` | `69e7896cf783f196cf32f56b05607643811ada43` | 7 / 1,183 | clean `main...origin/main` |

No local `.env`, CVG runtime data, Qdrant process, Docker executable, root
compose, or OpenWebUI configuration was found. A pre-existing Redis on port
6379 answered `PONG`; it was not inspected or modified.

## Changes

Only Phase 0 evidence/control artifacts were added at the workspace root:

- recoverable engineering control plane under `.agent/`;
- `docs/architecture/current-system.md`;
- `docs/baselines/environment-2026-08-31.json`;
- `docs/baselines/characterization-results.json`;
- `docs/baselines/phase-0-performance.json`;
- `docs/baselines/phase-0-command-log.md`;
- `tests/phase0/redis-locker-characterization.mjs`.

No runtime source, package manifest, lockfile, deployment file, or child Git
history was rewritten. The Professor and Locker worktrees remain clean; the CVG
worktree now has only the two additive runtime-state/execution-log overlay
entries required by its `AGENTS.md`. The root test is deliberately a characterization of the current
Locker contract; its ownerless-unlock observation is recorded as a finding,
not as a target design.

## Files/modules

The main current ownership boundaries are:

| Boundary | Current files | Current responsibility |
| --- | --- | --- |
| CVG API/security | `cvg-master-rag-v2/src/api/main.py`, `api/route_security.py`, `services/api_security.py` | REST routes, session/RBAC/workspace guards, upload/search/query/admin |
| CVG ingestion | `src/services/document_parser.py`, `chunker.py`, `ingestion_service.py`, `ingestion_job_service.py`, `scripts/ingestion_worker.py` | parse, chunk, embeddings, Qdrant upsert, controlled PDF jobs and cleanup |
| CVG retrieval/QA | `src/services/vector_service.py`, `search_service.py`, clinical planner/evidence/response/grounding services | dense+sparse/RRF, rerank, answer, clinical v2, citations and telemetry |
| CVG persistence | `src/services/enterprise_store.py`, `document_registry.py`, `telemetry_service.py`, `src/data/`, `src/logs/` | JSON corpus, enterprise state, jobs, datasets, JSONL logs |
| CVG web | `frontend/app/`, `frontend/lib/api.ts`, session provider and shell | native Next.js chat, documents, search, dashboard, admin, audit |
| Professor core | `rick-professor/src/core/processor.ts`, `src/lib/` | OpenAI preprocess/planner/agent/fallback, Qdrant, Redis memory, lock client |
| Professor adapters | `rick-professor/src/routes/openai.ts`, `routes/webhook.ts`, `src/server.ts` | OpenAI-compatible HTTP, Telegram webhook, health/shutdown |
| Locker | `modulo-redis-locker/server.js` | Redis `SET NX PX`, HTTP health, unconditional `DEL` unlock |

Full flow diagrams, data fields, contract matrix, stale-document comparison,
and the proposed layout are in
[`docs/architecture/current-system.md`](../architecture/current-system.md).

## Architecture changes

No production/runtime architecture was changed. Phase 0 changed the workspace
only by adding evidence and recovery artifacts. The observed architecture is
three separately deployable projects, not a monorepo. The proposed target is a
modular monolith around the existing CVG product with explicit `web`, `api`,
`worker`, `provider-compat`, shared contract/storage/retrieval/auth/telemetry
packages, and a lock boundary only if its owner-safe contract justifies a
separate process. That proposal is not implemented.

## Tests

Existing characterization surface identified:

- CVG: controlled PDF ingestion, chunking, reindex, transaction cleanup,
  embedding batching, retrieval filters, grounding, clinical response/citation,
  auth/RBAC/non-leakage, jobs, CORS/cookie and observability tests in
  `cvg-master-rag-v2/src/tests/`.
- Professor: one `src/core/processor.test.ts` with happy path, lock rejection,
  and a misleading low-score fallback case. It mocks all dependencies and has
  no HTTP/Redis/Qdrant/OpenAI integration coverage.
- Locker: no package test script or test file before Phase 0. The new
  `tests/phase0/redis-locker-characterization.mjs` fills the minimum black-box
  gap without changing `server.js`; the two benchmark harnesses under
  `tests/phase0/` make the saved local timings replayable.

The RAG tests already cover many unit/contract branches, so no speculative
duplicate suite was added while their Python environment was unavailable. The
missing cases remain explicit in the characterization matrix: real ingest,
Qdrant index/query, grounded answer, provenance sample, restart/recovery,
duplicate ingestion, provider outage and end-to-end multi-tenant behavior.

## Tests executed/results

| Check | Result | Evidence/interpretation |
| --- | --- | --- |
| Root engineering control-plane checker | `PASS` | `check_state.py . --contracts-root ...` → `RESULT PASS (pass=9 warn=0 fail=0)` |
| CVG secret scan | `PASS` | `python3 src/scripts/scan_secrets.py` |
| Child Git diff checks/status | `PASS_WITH_EXPECTED_DOCS` | `git diff --check` clean; Professor/Locker clean; CVG contains only the documented additive overlay in `docs/20_master_execution_log.md` and `docs/99_runtime_state.md` |
| Professor `npm ci` | `PASS` | 194 packages installed from existing lockfile |
| Professor `npm run build` | `PASS` | TypeScript compiler completed |
| Professor declared `npm test` | `FAIL` | Node 22/ts-node ESM loader: `ERR_REQUIRE_CYCLE_MODULE` before test execution |
| Professor alternate CommonJS test invocation | `PARTIAL` | four assertions reached/passed, but imported Redis handles kept the process open and the process was interrupted; not a declared-script pass |
| Locker `npm ci` | `PASS` | 80 packages installed |
| Locker `node --check server.js` | `PASS` | syntax valid; package has no test script |
| Frontend `npm ci` | `BLOCKED` | package/lockfile mismatch: missing Playwright entries and dependency version conflicts |
| CVG Python suite | `BLOCKED` | Python 3.12 exists but `/usr/bin/python3` has no `pip`, `ensurepip`, `venv`, or `pytest` |
| Docker/Qdrant live checks | `BLOCKED` | `docker` not found; `127.0.0.1:6333/readyz` connection refused |
| Isolated Locker black-box | `PASS_WITH_FINDING` | local Redis 6397 + Locker 3317: health, NX contention, TTL, concurrent same key and malformed body passed; active lock was deleted without owner value |
| Saved performance harnesses | `PASS` | `OPENAI_API_KEY=phase0-test-key node tests/phase0/professor-injected-benchmark.mjs` and `LOCKER_URL=http://127.0.0.1:3317 node tests/phase0/locker-http-benchmark.mjs` reproduced the measured workload shapes |

The exact commands and outcomes are in
[`docs/baselines/phase-0-command-log.md`](../baselines/phase-0-command-log.md).

## Coverage/important branches

The A–O checklist is preserved literally below. A status of `STATIC_ONLY`,
`PARTIAL`, or `NOT_RUN` is an explicit result, not a claim that the runtime path
passed.

| ID | Required characterization path | Current evidence | Phase 0 status |
| --- | --- | --- | --- |
| A | representative document ingest | CVG ingestion/parser/chunker code and existing tests identified | `NOT_RUN`: Python dependencies and Qdrant unavailable |
| B | parse and chunks | parser/chunker modules and test files inspected | `STATIC_ONLY`: existing tests were not executable |
| C | embeddings offline | embedding service and fallback implementation inspected | `NOT_RUN`: CVG Python environment unavailable |
| D | persistence and vector index | atomic JSON/job persistence and Qdrant adapter inspected | `NOT_RUN`: no live Qdrant |
| E | known query and evidence | hybrid/RRF/search paths and tests inspected | `NOT_RUN`: no live collection |
| F | grounded answer | grounding/clinical response services and tests inspected | `STATIC_ONLY`: no live provider/RAG run |
| G | source provenance | payload/schema/evidence paths inspected | `STATIC_ONLY`: no live point/answer sample |
| H | concurrent requests | isolated Locker same-key race reproduced | `PARTIAL`: Professor/CVG end-to-end race not run |
| I | Redis lock | isolated health/acquire/TTL/contention/malformed probes | `PASS_WITH_FINDING`: ownerless unlock remains unsafe |
| J | restart and recovery | recovery/job code inspected | `NOT_RUN`: service restart environment unavailable |
| K | malformed document | parser error branches identified | `NOT_RUN`: CVG Python environment unavailable |
| L | provider unavailable | Professor retry/null/fallback code inspected | `STATIC_ONLY`: no fault-injected provider HTTP run |
| M | vector database unavailable | CVG disk fallback and Professor empty-result fallback inspected | `STATIC_ONLY`: no service transition run |
| N | duplicate ingestion | retention/reindex paths inspected | `NOT_RUN`: no isolated CVG corpus runtime |
| O | metrics and observability | Node/Locker measurements and CVG telemetry paths inspected | `PARTIAL`: live CVG metrics unavailable |

The current Professor evidence gate is especially important: `approved` is
calculated from score/term coverage but the actual branch proceeds whenever
there is any non-empty result. Its existing “low-score fallback” test can pass
without exercising the fallback branch.

## Performance evidence

The full CVG ingestion/embedding/retrieval/generation/TTFT/memory/index-size
baseline could not be measured honestly because Python dependencies, Qdrant and
OpenAI were unavailable. The feasible isolated measurements are:

| Workload | n | p50 | p95 | min | max | Meaning |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Professor `processMessage` with all dependencies injected | 12 | 0.342 ms | 5.386 ms | 0.098 ms | 5.386 ms | orchestration overhead only; no real provider/DB/network |
| Locker HTTP acquire, unique keys, loopback Redis | 20 | 119.423 ms | 124.649 ms | 102.649 ms | 147.532 ms | local HTTP + Redis observation, not a production SLO |

No TTFT claim is made: Professor emits a synthetic whole-answer SSE after the
pipeline completes. Raw machine-readable results are in
[`docs/baselines/phase-0-performance.json`](../baselines/phase-0-performance.json).
The exact replayable harnesses are
[`tests/phase0/professor-injected-benchmark.mjs`](../../tests/phase0/professor-injected-benchmark.mjs)
and
[`tests/phase0/locker-http-benchmark.mjs`](../../tests/phase0/locker-http-benchmark.mjs).

## Security impact

Phase 0 introduced no runtime security change. It identified these current
security/concurrency risks:

1. Locker `/unlock` validates only `lock_key` and unconditionally `DEL`s it;
   any reachable actor can remove another owner’s lease.
2. Professor never calls `/unlock`, so a completed request holds its key until
   45 seconds; work longer than the TTL can overlap a second request.
3. Professor `API_KEY` is optional; Telegram webhook and Locker have no auth.
4. CVG upload joins untrusted `file.filename` directly to the workspace upload
   path.
5. Professor does not apply a workspace filter to Qdrant search and trusts
   planner evidence without verifying it against retrieved results.
6. Professor logs the raw Redis URL in `src/lib/redis.ts`; a credential-bearing
   URL could leak.
7. Error strings can be exposed through API responses and dependencies collapse
   into fallback/HTTP 200 states, weakening security/operations signals.

These findings are routed to Phase 1 hardening; no fix was silently applied.

## RAG quality impact

No live RAG quality score was changed. The existing CVG code has a materially
more complete RAG path than the neighboring Professor adapter: named dense and
sparse Qdrant vectors, workspace filters, RRF/reranking, clinical v2 evidence
packs, bibliography and grounding checks. However, compatibility is not proven:

- CVG defaults to `rag_phase0`; upload form defaults to `cvg_master_rag`; the
  Professor defaults to `rickvet_documents`.
- CVG writes named `dense`/`sparse` vectors; Professor posts a bare vector to
  Qdrant REST.
- Professor evidence/citations are prompt conventions, not an enforced output
  provenance contract.
- No real OpenWebUI request, deployed Qdrant schema, or source payload sample
  was available.

Therefore no RAG quality promotion or regression claim is made.

## Limitations

- Python tests and offline CVG imports were not executable because the base
  Python installation lacks packaging support; system packages were not
  modified to bypass this.
- Docker is absent, so Qdrant, compose rendering/build, and container health
  could not be validated.
- No real OpenAI key, OpenWebUI installation/version, Telegram configuration,
  effective deployment env, systemd status, reverse-proxy config, or live Qdrant
  collection was accessed.
- The pre-existing Redis on 6379 was intentionally not inspected; the runtime
  lock test used an isolated temporary Redis instance and was stopped afterward.
- Historical CVG/Professor reports and pass counts remain useful context but are
  stale relative to this checkout/environment.

## Risks

| Priority | Risk | Evidence | Recommended Phase 1 control |
| --- | --- | --- | --- |
| P0 | No reproducible cross-system deployment | invalid compose siblings, no root Git/compose, absent Docker | select authoritative monorepo boundary; render/build in CI before migration |
| P0 | Lock ownership/release is unsafe | Locker runtime + Professor source | owner-safe compare-and-delete, release in `finally`, bounded timeout, race/crash tests |
| P0 | RAG collection/vector contract diverges | CVG vector service vs Professor config/client | one versioned contract/fixture for collection, named vectors, payload and workspace filter |
| P0 | Professor can answer from any non-empty/possibly unverified evidence | processor gate and planner trust | enforce evidence gate and origin/citation validation |
| P1 | CVG upload path accepts raw filename | `src/api/main.py:1380` | canonicalize basename, reject traversal/collision, adversarial test |
| P1 | Unstable CVG point IDs | Python `hash()` at `cvg-master-rag-v2/src/services/vector_service.py:406` | stable content/UUID mapping with migration/reconciliation |
| P1 | File JSON state only locks within process | `enterprise_store.py` `threading.RLock` | single-writer/DB or OS lock decision with crash/recovery tests |
| P1 | Dependency/build drift | frontend `npm ci` mismatch; Professor test loader failure | lockfile repair/version policy and root CI matrix |
| P1 | Health/degradation semantics hide dependencies | Professor health only Qdrant; fallback/HTTP 200 | dependency-aware readiness and explicit error taxonomy |
| P2 | Synthetic stream/usage zero/model ignored | Professor OpenAI route | contract-test actual OpenWebUI client behavior |

## Deferred

The following remain deliberately deferred to Phase 1 or a prerequisite gate:

- moving/merging the three Git repositories;
- changing lock, auth, path sanitization, point IDs, Qdrant schema or provider
  behavior;
- relational/object storage decision and migrations/rollback scripts;
- real Qdrant collection/payload audit and index-size measurement;
- real OpenWebUI compatibility capture and versioned API contract;
- full CVG test suite, Playwright, container, provider outage and restart tests;
- production deployment, secrets, SSO/MFA, backups, alerts and operational
  ownership;
- Phase 2+ roadmap items from the user attachment.

## Promotion recommendation

Do **not** promote the current workspace to `VERIFIED_CANDIDATE` for
implementation or deployment. Promote only the Phase 0 evidence package as a
**candidate planning baseline with open environment gates**. The promotion gate
must remain open until a reproducible environment provides:

1. Python dependencies and the full CVG suite;
2. isolated Qdrant with a real ingest → index → search → grounded-answer run;
3. duplicate/restart/provider/vector-failure characterization;
4. frontend lockfile-consistent lint/build/smoke;
5. real Professor/Locker HTTP + Redis tests and an OpenWebUI request capture;
6. a decision on canonical collection/payload/workspace/auth contracts.

This is an evidence-based non-promotion, not a claim that the underlying CVG
implementation is unusable.

## Status

`PHASE 0 PARTIAL — INVENTORY COMPLETE, CRITICAL RUNTIME BASELINE INCOMPLETE.`
The current architecture, cross-system risks, feasible lock characterization,
performance limitations and a proposed target layout are documented. Phase 1
must not start until the open gates above are resolved or explicitly accepted
by the responsible human authority.

## PHASE 0 STATUS

| Area | Current state | Evidence | Risk | Recommended action |
| --- | --- | --- | --- | --- |
| Repository topology | Three independent repos were clean at baseline capture; root has no Git; CVG now has only the required docs overlay | `docs/baselines/environment-2026-08-31.json`, `cvg-master-rag-v2/docs/99_runtime_state.md` | high migration drift | approve authoritative root boundary before moving files |
| Current architecture | Documented with Mermaid ingestion, QA, Professor/OpenWebUI and Redis flows | `docs/architecture/current-system.md` | medium/high stale docs | use this map as current baseline; preserve historical docs as labeled |
| Dependencies/toolchain | Node services install/build; Python/frontend environment incomplete | command log | high reproducibility | provision isolated Python/Qdrant and repair frontend lockfile |
| Stores/data model | Filesystem JSON + Qdrant mapped; Professor has Redis memory/lease | architecture data audit | high consistency | define stable IDs, versioned schemas and rollback before migration |
| Redis purpose | Professor conversation memory and distributed lease; CVG does not use it | source/config inspection + isolated runtime | P0 ownerless release/no Professor unlock | design owner-safe lease contract and characterize crash/TTL |
| OpenWebUI | no local installation/config/caller; Professor is a partial OpenAI-compatible adapter | `rick-professor/src/routes/openai.ts`, repository search | high compatibility uncertainty | obtain redacted deployed config/request capture |
| Characterization | Locker pass-with-finding; Professor injected partial; CVG real RAG not run | `docs/baselines/characterization-results.json` | critical gaps | run missing paths in provisioned harness |
| Performance | only isolated Professor mock and Locker loopback values | `phase-0-performance.json` | no production SLO | rerun with real representative corpus/provider/service chain |
| Security | no runtime fix; P0/P1 findings recorded | risks above/source paths | high | route hardening as gated Phase 1 work |
| CI/deployment | no root CI/compose; Professor compose paths broken; Docker absent | architecture/deployment audit | P0 | make a reproducible non-production stack first |
| Promotion | not `VERIFIED_CANDIDATE` for implementation | this report | open gates | hold Phase 1 implementation; request authority/prerequisites |

## PROPOSED PHASE 1 IMPLEMENTATION PLAN

This is a proposed sequence only. Each slice requires its own acceptance,
rollback and fresh verification; no item below was implemented in Phase 0.

### 1. Freeze authority and compatibility contracts

- Choose the authoritative Git root and preservation strategy for the three
  histories (tags/branches and a reversible import record).
- Freeze OpenAPI/JSON schemas for documents, chunks, jobs, evidence, citations,
  errors, health/readiness, workspace identity and OpenAI-compatible requests.
- Obtain a redacted effective environment and a real Qdrant collection/payload
  sample; decide whether Professor is a compatibility adapter or a separate
  product surface.

### 2. Establish the walking skeleton

- Create the proposed `apps/web`, `apps/api`, `apps/worker`, and
  `apps/provider-compat` boundaries while preserving the CVG native UI and
  public REST contracts.
- Add root package/Python/CI orchestration without changing runtime semantics.
- Render a local compose stack with explicit health conditions, volumes and
  service names; run it only in isolated development infrastructure.

### 3. Make storage and ingestion explicit

- Introduce storage interfaces around CVG filesystem corpus, enterprise state,
  jobs and Qdrant; do not migrate data until schema versions and rollback are
  tested.
- Secure upload names and define duplicate/idempotency keys.
- Replace process-randomized point IDs with stable IDs through a versioned
  migration/reconciliation procedure.
- Keep the controlled PDF worker/job path, add durable startup recovery and
  prove partial/failed cleanup.

### 4. Unify retrieval and RAG quality contracts

- Select one Qdrant collection policy, named-vector schema, dimension/distance,
  payload/provenance fields and workspace filter.
- Preserve CVG dense+sparse/RRF/clinical v2 behavior where characterization
  confirms it; add contract tests before changing thresholds or rerankers.
- Enforce Professor evidence gates and validate planner/answer citations against
  retrieved evidence rather than trusting prompt markers.

### 5. Harden provider compatibility and concurrency

- Decide whether the Professor route remains a separate adapter or delegates to
  the canonical API through a typed contract.
- Implement explicit auth, provider timeouts/retries/error statuses, real
  streaming semantics or document buffered compatibility, model selection and
  usage accounting.
- Either retain the lock service with owner-safe compare-and-delete/renewal and
  bounded clients, or replace it with a library-backed lease; in both cases add
  release-in-finally, expiry/overlap/crash tests and observability.

### 6. Finish tenant, operations and evidence gates

- Bind external keys to permitted workspaces/tenants and test cross-tenant
  non-leakage across CVG and Professor.
- Standardize readiness, request/trace IDs, redaction, error taxonomy, metrics,
  logs, backups and recovery runbooks.
- Add a root CI matrix for Python backend/full tests/Qdrant, frontend
  lint/build/smoke, Professor build/tests, Locker contract tests and
  cross-system integration/evaluation/performance.
- Re-run the Phase 0 A–O matrix on a representative fixture and compare
  retrieval quality, grounded/citation coverage, latency, TTFT, memory, index
  size, duplicate and concurrency behavior before any production promotion.

### Phase 1 exit gate

Phase 1 is implementation-ready only after the contracts, preservation/import
plan, isolated runtime, rollback path, risk-shaped tests and human-owned
collection/auth/deployment decisions are recorded in the root control plane.
