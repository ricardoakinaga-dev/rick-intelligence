# `apps/api` — Canonical Platform HTTP Boundary (Phase 1.6)

FastAPI kernel. prefix: `/api/v1/*` (platform) + `/v1/chat/completions` (OpenAI compat)
+ `/health/live`, `/health/ready`.

The local root path supports authenticated knowledge lifecycle operations:

```text
POST   /api/v1/documents/upload
GET    /api/v1/ingestion/jobs/{job_id}
POST   /api/v1/ingestion/jobs/{job_id}/cancel
POST   /api/v1/ingestion/jobs/{job_id}/retry
POST   /api/v1/ingestion/reindex
GET    /api/v1/documents?limit=20&cursor=<document_id>
DELETE /api/v1/documents/{document_id}
```

Multipart upload (`file` plus `collection_id`) is the primary request shape;
the bounded JSON body is retained for small compatibility clients. Uploads
are copied to a private, server-generated temporary path and return `202` with
a job id before the bounded local worker runs the canonical package pipeline.
The document becomes visible to local retrieval only after publication. Job
records, staging files, and the worker queue are process-local and are lost on
restart; production requires a later durable queue/object-storage integration.
Cancellation is cooperative and publicly actionable while the job is queued or
processing; retries accept fresh content and are capped at three per failed
attempt.

Document listing is stable cursor pagination over published documents only;
processing and failed attempts remain job state rather than library content.
Retry accepts fresh bounded JSON content and creates a new attempt without
mutating the original failed job. `RICK_API_ROOT_RETRIEVAL=0` is the explicit
rollback for the local grounded retrieval path.

The default local upload executor is wired to the instance-owned API telemetry
ring. Its worker lifecycle events are visible in the protected admin metrics
snapshot with opaque job/request/correlation references only; filenames,
content, tenant/workspace/collection scope and exception text are excluded.
The API admits only the finite documented worker event names, and the root
upload sequence is deterministically `enqueued` then `started` then terminal.
The ring and executor remain process-local, bounded and non-distributed.

## Local start

```bash
PYTHONPATH=apps/api/src:apps/worker:packages/jobs/src:packages/contracts/src:packages/authorization/src:packages/identity/src:packages/observability/src:packages/knowledge/src:packages/ingestion/src:packages/retrieval/src:packages/providers/src:packages/locking/src:packages/professor/src:packages/evidence/src:packages/decision/src \
  python3 -m uvicorn main:app --app-dir apps/api/src --port 8000
# or
make api-dev
```

Hermetic by default (in-memory identity/chat/retrieval). Legacy adapters are
an explicit opt-in/rollback:

```bash
RICK_API_USE_LEGACY=1 RICK_API_LEGACY_HEALTH=1 make api-dev
# equivalent explicit backend selector:
RICK_API_CHAT_BACKEND=legacy make api-dev
```

The root upload route requires `python-multipart`. Requires Qdrant/Redis/provider
only in legacy mode; plain dev remains hermetic and deterministic.
If a legacy adapter cannot be loaded, startup fails instead of silently serving
the ungrounded stub.

Production starts only with `RICK_API_COMPOSITION=module:factory`. The injected
factory receives `ApiSettings`, returns `ExternalCompositionInputs`, and the
entrypoint builds the canonical Postgres/S3/Qdrant/Redis/provider graph before
calling `create_app`; the Redis rate limiter and lease must be the package
capabilities bound to the exact injected client, with one explicit global
production namespace. Startup then performs required readiness checks before
admitting traffic; missing or invalid composition fails closed.

## Auth model

- Browser: HttpOnly session cookie (`SESSION_COOKIE_NAME`, `Secure`+`SameSite`).
- Compat/external: `Authorization: Bearer <compat-key>` or `X-API-Key` on `/v1/*` only.
- Precedence: valid cookie wins over Bearer (tested). See `docs/architecture/api-security.md`.

## Tests

```bash
make api-test        # full apps/api matrix
make api-contract    # OpenAPI generation check
make api-security    # route-policy + import-boundary + negatives
make api16-full      # ingestion, lifecycle, readiness, root API, benchmark
make api16-verify    # sanitized full/regression evidence matrix
```
