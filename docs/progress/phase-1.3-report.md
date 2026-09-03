# RICK Intelligence — Phase 1.3 Report (Unified API Kernel & Runtime Adapter Consolidation)

## Final Classification

`VERIFIED_CANDIDATE` — `apps/api` is an executable canonical HTTP boundary with
app factory, request context, error envelope, identity/authorization integration,
health/readiness, centralized legacy adapters, platform chat + OpenAI compat +
streaming, audit/observability hooks, versioned routes, and passing evidence
lanes. No P0/HIGH review findings. Historical Phase 0.6 remains `BLOCKED /
NOT_PROMOTED`; Phase 1.1 remains `VERIFIED` (skeleton scope). Phase 1.4 NOT begun.

## What was built

- `apps/api/src/` — `app.py` (`create_app`), `main.py`, `core/` (config, errors,
  request_context, security, middleware, lifecycle), `routes/` (auth, sessions,
  chat/history/sources, knowledge, admin, health, compat_openai + `ROUTE_REGISTRY`),
  `services/` (identity, authorization, chat, audit), `dependencies/`,
  `adapters/legacy/cvg.py` (only legacy-touching modules), `models.py`.
- `packages/contracts/src/rick_contracts/` — frozen `ChatRequest/ChatResponse/
  ChatStreamEvent`, `Page`, `ERROR_CODES` (dependency-light, no legacy imports).
- `apps/api/tests/` — 44 tests: routing, route-policy/default-deny, auth/session,
  negatives (§51 matrix), errors, health, compat, streaming, HTTP contract
  (IDs/headers/CORS/limits/rate-limit), import boundary, dual equivalence, goldens.
- Root: `make api-dev|api-test|api-contract|api-security|api-benchmark` (Phase 1.1
  targets untouched); `.github/workflows/phase-1.3.yml`; `openapi.json` (29 paths).
- Docs: `api-kernel.md`, `api-migration-map.md` (DUAL, no deletion), `api-security.md`,
  `api-errors.md`, `api-compatibility.md`; ADRs 001–008; `phase-1.3-api-overhead.json`.

## Verification state (executed 2026-09-03, Python 3.12.3, hermetic)

| Check | Result | Evidence |
| --- | --- | --- |
| `make api-test` | PASS — 44 passed | `apps/api/tests/` (all green) |
| `make api-security` | PASS (subset of above) | policy + negatives + boundary |
| `make api-contract` | PASS — 29 paths, required paths present | `apps/api/openapi.json` |
| `make api-benchmark` | PASS — http p50 5.195ms/p95 9.305ms vs direct 0.013/0.031ms | `docs/baselines/phase-1.3-api-overhead.json` |
| Legacy focused regression | PASS — 40 passed (`test_phase05_contract/security`, `test_phase06_rbac`, `test_p0_closeout`) | local run, `RAG_SKIP_QDRANT_BOOTSTRAP=1` |
| Professor/Locker suites | NOT RE-RUN (no `node_modules` in this env) | Phase 1.1 evidence stands; compat covered by adapter tests |
| `make validate` (Phase 1.1) | untouched lane; skeleton placeholders replaced only under `apps/api`+`packages/contracts` | git status shows additive scope |

## Security posture

Default-deny registry; cookie-wins precedence; ACL narrowing (request cannot widen
workspace/collection); VET/KM/anon matrix green; safe error envelope; allowlist CORS;
SameSite cookies; proxy headers untrusted by default; login/chat rate buckets
(in-process — distributed limiter is a documented residual risk); audit on sensitive
routes with ADR-008 fail-open→fail-closed follow-up before production.

## Historical blockers (still visible, not erased)

Phase 0.6 `BLOCKED`: approved corpus/dataset absent (full CVG suite red), live-provider
evidence pending, deployment controls pending. This phase adds no live-provider claim
and deletes no legacy path.

## Phase 1.4 readiness

Safe to begin after this gate: public chat contract frozen under
`packages/contracts`, adapter seam per route, DUAL rollback documented per endpoint.
Prerequisites carried forward: fail-closed audit for critical mutations, distributed
rate limiting, explicit CSRF tokens for browser production, Professor orchestration
wiring.
