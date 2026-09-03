# API Kernel (`apps/api`)

Canonical platform HTTP boundary (Phase 1.3, FastAPI). Versioned platform surface
`/api/v1/*`; OpenAI compat `/v1/chat/completions` + `/v1/models`; health
`/health/live`, `/health/ready`.

## Direction

```text
HTTP -> routes (validate HTTP only) -> application services -> packages/* -> adapters/legacy/*
```

Routes never touch Qdrant/Redis/OpenAI/filesystem. Only `apps/api/src/adapters/legacy/`
may import preserved legacy paths (import-boundary test enforces this).

## Factory

`create_app(settings, providers)` — deterministic, no import-time singletons, no
automatic Qdrant/OpenAI/Redis init. Tests inject fakes via `Providers`
(identity, chat_backend, health_checks, audit_sink, rate_limiter).

## Middleware order

1. CORS (outermost) 2. request ID/correlation 3. security headers 4. size limits
5. request context (incl. trusted-proxy IP) 6. session/auth (dependency level)
7. audit/log context 8. error boundary (handlers) 9. metrics (low-cardinality).

## Request context

`RequestContext{request_id, correlation_id, user_id, session_id, workspace_id,
tenant_id, client_ip, user_agent, api_version, route}` — server-derived only.
Raw `Request` objects never flow into domain code. Correlation IDs capped at
128 chars/strict charset, else regenerated. `X-Request-ID` echoed on every response.

## Errors

`{error:{code,message,request_id,details}}`, taxonomy in `api-errors.md`.
Legacy `HTTPException` details mapped to canonical codes; messages replaced with
safe templates; no stack/provider/credential leakage.

## Health

- `GET /health/live` — process alive (public, minimal).
- `GET /health/ready` — `ready` (200) / `degraded` (200, optional down) /
  `not_ready` (503, any required down). Never 200+ok with a mandatory dep broken.
- `GET /api/v1/admin/health` — detailed diagnostics, requires `observability.read`.
