# Phase 1.3 — Unified API Kernel & Runtime Adapter Consolidation

Status: IMPLEMENTATION_READY
Scope: `apps/api` canonical FastAPI kernel + centralized legacy adapters. No full
ingestion/retrieval/Professor extraction, no web/worker/Postgres migration, no legacy deletion.

## Tasks

| ID | Title | Acceptance |
| --- | --- | --- |
| PH13-API-KERNEL | App factory + versioned router registry | `create_app()` deterministic; `/api/v1/*` + `/v1/chat/completions` + `/health/*`; route inventory test |
| PH13-REQUEST-CONTEXT | RequestContext + correlation IDs | `X-Request-ID` always set; trusted correlation preserved/capped; context flows to logs/audit |
| PH13-AUTH | Identity integration via `packages/identity` seam + legacy adapter | cookie wins over bearer; session snapshot; 401 envelope; session tests |
| PH13-ERRORS | Canonical error envelope + taxonomy | stable codes; no secret/provider/stack leakage; error tests |
| PH13-HEALTH | live/ready + detailed admin health | live=process; ready=checks with ready/degraded/not_ready; 200 only when ready/degraded per contract |
| PH13-LEGACY-ADAPTERS | Centralized `adapters/legacy/` boundary | routes/services never import legacy directly; import-boundary test; failure translation |
| PH13-COMPAT-OPENAI | OpenAI compat adapter on canonical chat service | stream true/false; model mapping; no fabricated usage; compat tests |
| PH13-AUDIT | Audit sink on sensitive routes | login/logout/denied/user/role/session-revoke/upload/reindex events; failure policy ADR |
| PH13-OBSERVABILITY | Structured logs + metrics stubs | request_id/user/route/status/duration; no content logging; low-cardinality metrics |
| PH13-EQUIVALENCE | Dual-run legacy vs new | login/me/health/openai parity ignoring request_id/timestamp/token |
| PH13-SECURITY | Negatives + policy enforcement | VET/KM/anon matrix; default-deny; public allowlist; CORS/CSRF/proxy/cookie-bearer tests |
| PH13-REVIEW | Fresh read-only review (16 questions) | no P0/HIGH for VERIFIED_CANDIDATE |
| PH13-FINAL | Gates + report + migration map + ADRs | all Phase 1.3 gate boxes evidenced |

## Route inventory (legacy → new)

Legacy `cvg-master-rag-v2/src/api/main.py` (~50 routes) + `health_routes` + `admin_runtime_routes`
+ `observability_routes`; Professor `POST /v1/chat/completions`, `GET /v1/models`,
`POST /webhook/telegram`; Locker `POST /lock|/unlock|/renew`, `GET /healthz`.

New canonical surface (this phase, low-risk first + skeletons):

- `GET /health/live` (public), `GET /health/ready` (public minimal)
- `POST /api/v1/auth/login` (public, rate-limited), `POST /api/v1/auth/logout`,
  `POST /api/v1/auth/recovery` (public neutral), `GET /api/v1/auth/me`, `GET /api/v1/session`
- `GET /api/v1/auth/sessions`, `POST /api/v1/auth/sessions/revoke`
- `POST /api/v1/chat` (+SSE when `stream=true`), `GET /api/v1/history`, `GET /api/v1/sources`
- `GET /api/v1/collections`, `GET /api/v1/documents`, `GET /api/v1/documents/{id}`
- `POST /api/v1/documents/upload` (skeleton → adapter, `documents.upload`)
- `POST /api/v1/ingestion/reindex` (skeleton → adapter, `reindex.run`)
- `GET /api/v1/admin/users` (`users.manage`), `POST /api/v1/admin/users`
- `GET /api/v1/admin/sessions` (`sessions.revoke`), `POST /api/v1/admin/sessions/revoke`
- `GET /api/v1/admin/health` (`observability.read`), `GET /api/v1/admin/audit` (`audit.read`)
- `GET /api/v1/admin/system` (`runtime.manage`)
- Compat: `POST /v1/chat/completions`, `GET /v1/models` (API-key domain, separate from cookie sessions)

Full migration matrix: `docs/architecture/api-migration-map.md` with
LEGACY_ONLY / DUAL / ROOT_CANONICAL / DEPRECATED_LEGACY / REMOVED.

## Architecture rules

- HTTP → `apps/api` routes (validate HTTP only) → application services → `packages/*`
  → `adapters/legacy/*` (only place allowed to import legacy). Routes never touch
  Qdrant/Redis/OpenAI/filesystem directly.
- `packages/*` never import `apps/*` or legacy paths (import-boundary test).
- `create_app(settings, deps)` — no import-time singletons; Qdrant/OpenAI/Redis
  clients lazy; tests inject fakes via dependency providers.
- Default-deny: every non-public route declares auth+permission in `ROUTE_REGISTRY`;
  structural test fails on missing policy. Public allowlist: `/health/live`,
  `/health/ready`, `/api/v1/auth/login`, `/api/v1/auth/recovery`,
  `/api/v1/auth/request-password-reset`, `/api/v1/auth/confirm-password-reset`,
  `/v1/models`+`/v1/chat/completions` only with valid API key (not anonymous).
- Cookie precedence: valid session cookie wins over Bearer for browser safety;
  Bearer compatibility tokens only apply on compat/external domains. Tested.
- Errors: `{error:{code,message,request_id,details}}`; taxonomy per prompt §12.
- Streaming: single SSE abstraction (start/delta/citation/completion/error);
  disconnect propagates cancellation; no fake streaming.
- Audit failure: best-effort with error log for availability, EXCEPT documented
  follow-up to move security-critical admin mutations to fail-closed (ADR-008).

## Verification

- `apps/api/tests/*`: routing, auth, negatives, error contract, CORS, request IDs,
  health, compat, streaming, rate limiting, adapter translation, route-policy,
  import boundary, dual equivalence, golden contracts.
- Root: `make api-test`, `make api-contract`, `make api-security`, `make api-dev`;
  Phase 1.1 lanes untouched. CI: `.github/workflows/phase-1.3.yml`.
- Perf: kernel-overhead p50/p95 legacy-vs-adapter observation (local, no live provider).
- Review: 16 questions, severity P0/HIGH/MEDIUM/LOW/INFO.
