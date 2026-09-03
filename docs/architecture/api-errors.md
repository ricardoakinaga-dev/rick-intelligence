# API Errors

Envelope: `{error:{code,message,request_id,details}}`. `request_id` always present
and echoed via `X-Request-ID`.

## Taxonomy (stable codes)

`validation_error, unauthorized, forbidden, not_found, conflict, rate_limited,
request_too_large, unsupported_media_type, provider_timeout, provider_unavailable,
provider_rate_limit, vector_store_unavailable, storage_unavailable,
lock_unavailable, ingestion_failed, retrieval_failed, generation_failed,
internal_error` (mirrored in `packages/contracts`).

## Rules

- Safe templates replace legacy messages; legacy `detail` dicts keep only
  `{error, tenant_id, user_id, workspace_id}` keys.
- Validation errors report field locations, never raw values.
- 5xx paths never include exception repr, provider bodies, credentials, URLs,
  hashes, or tokens. Covered by error/compat/streaming tests.
