# `apps/api` — Canonical Platform HTTP Boundary (Phase 1.3)

FastAPI kernel. prefix: `/api/v1/*` (platform) + `/v1/chat/completions` (OpenAI compat)
+ `/health/live`, `/health/ready`.

## Local start

```bash
PYTHONPATH=apps/api/src:packages/contracts/src python3 -m uvicorn main:app --app-dir apps/api/src --port 8000
# or
make api-dev
```

Hermetic by default (in-memory identity/chat). Legacy adapters opt-in:

```bash
RICK_API_USE_LEGACY=1 RICK_API_LEGACY_HEALTH=1 make api-dev
```

Requires Qdrant/Redis/provider only in legacy mode; plain dev prints required deps.

## Auth model

- Browser: HttpOnly session cookie (`SESSION_COOKIE_NAME`, `Secure`+`SameSite`).
- Compat/external: `Authorization: Bearer <compat-key>` or `X-API-Key` on `/v1/*` only.
- Precedence: valid cookie wins over Bearer (tested). See `docs/architecture/api-security.md`.

## Tests

```bash
make api-test        # full apps/api matrix
make api-contract    # OpenAPI generation check
make api-security    # route-policy + import-boundary + negatives
```
