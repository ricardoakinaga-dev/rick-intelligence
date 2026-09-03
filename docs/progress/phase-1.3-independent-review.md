# Phase 1.3 Independent Review (fresh read-only)

Reviewer: independent read-only pass over `apps/api`, `packages/contracts`,
routes/registry, tests, docs/ADRs, gates. Method: read source + tests, ran
`make api-test`, `api-security`, `api-contract`, legacy focused suite; inspected
registry vs mounted routes and error paths. No implementation files edited.

## Answers (16 required questions)

1. Real runtime app? **Yes.** `create_app` builds 34 routes; TestClient + uvicorn
   entrypoint work; hermetic default with legacy opt-in.
2. Logic out of routes? **Yes.** Routes validate HTTP and call services/adapters;
   no Qdrant/Redis/OpenAI/filesystem/embedding/prompt code in routes (boundary test).
3. Auth centralized? **Yes** — single `get_current_session`; cookie-wins tested.
4. Authz centralized? **Yes** — `has_permission`/`build_retrieval_context`; no role-string
   comparisons in routes.
5. Explicit policy per protected route? **Yes** — `ROUTE_REGISTRY` + enumeration test;
   one documented safe exception: `POST /auth/logout` idempotent without session.
6. VET→admin? **No.** 403 verified (`/admin/users`, upload, library).
7. ACL widening? **No.** Foreign workspace/collection → 403; narrowing-only enforced
   in one function with tests.
8. Secret leaks? **No.** Safe templates, allowlisted legacy keys, location-only
   validation errors; tests assert absence of URLs/tracebacks/provider bodies.
9. Cookie/bearer precedence safe? **Yes** — cookie wins; bearer-only without cookie is
   anonymous on platform routes; compat domain separate. Tested.
10. Compat via canonical service? **Yes** — both `/api/v1/chat` and
    `/v1/chat/completions` drive `ChatApplicationService`; `usage:null` documented.
11. Legacy imports isolated? **Yes at import level** — only `adapters/legacy/`
    contains legacy imports (test checks import statements + sys.path, not prose).
12. Root packages independent? **Yes** — `rick_contracts` has no legacy/app imports.
13. Migrations reversible? **Yes** — all DUAL, no deletion, rollback = re-point callers.
14. Health truthful? **Yes** — `not_ready`→503 on required failure; `degraded`→200
    only for optional; detail gated behind `observability.read`.
15. Phase 0.6 blockers visible? **Yes** — report retains corpus/provider/deployment gaps.
16. Phase 1.4 safe? **Yes**, with carried prerequisites (ADR-008 fail-closed audit,
    distributed limiting, CSRF tokens, Professor wiring).

## Findings

- MEDIUM: CSRF relies on SameSite-only; explicit tokens deferred (deployment note). Acceptable for 1.3.
- MEDIUM: In-process rate buckets (single-process residual risk); Redis interface ready. Acceptable for 1.3.
- MEDIUM: Audit best-effort with ADR-008 fail-closed follow-up gating production. Acceptable for 1.3.
- LOW: Upload/ingestion are validated stubs; heavy behavior stays legacy by design until 1.4.
- LOW: Professor/Locker suites not re-run here (missing `node_modules`); Phase 1.1 evidence + adapter tests cover.
- INFO: Kernel overhead ~5ms p50 local (stub backend).

No P0/HIGH findings. Decision: **PASS — VERIFIED_CANDIDATE scope met; do not begin Phase 1.4 in this turn.**
