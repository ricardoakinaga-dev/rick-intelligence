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

Each app owns its provider container and health registration mappings. Explicitly
injected service/client references remain caller-owned; constructing a second app
does not mutate the first app's settings. Routes and HTTP dependencies resolve
`get_providers(request)` from the effective `request.app.state.providers`, never
from a process-global pointer. Route-local helpers may receive Request; domain
services do not. Missing app providers fail closed. See
[app-provider isolation](app-provider-isolation.md) for scope and current evidence;
this is not a claim that explicitly shared adapters or databases are isolated.

## Middleware order

The actual stack wraps native server-error handling in transport observation,
then applies request IDs, security headers, CSRF, body limits, request context,
CORS and routing/dependencies. The current ordering, terminal metrics and
stream-cleanup contract is documented in
[HTTP transport observation](http-transport-observation.md). Provider isolation
does not introduce another middleware layer or change that composition.

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
- Production lifespan admission runs the required readiness set before the
  server serves traffic; a failed Redis or other mandatory check aborts
  startup rather than relying only on the readiness endpoint.
- `GET /api/v1/admin/health` — detailed diagnostics, requires `observability.read`.
