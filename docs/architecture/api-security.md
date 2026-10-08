# API Security (`apps/api`)

## Default-deny + allowlist

Every non-public route declares `auth` plus either a catalog `permission` or an
explicit `scope: "self"` decision in `routes/ROUTE_REGISTRY`. The structural test
fails on a missing policy, on a permission the policy engine never grants, on a
registry entry without a mounted handler and on a handler without an entry.
Public: `/health/live`, `/health/ready`, `/api/v1/auth/login`,
`/api/v1/auth/recovery`, `/request-password-reset`, `/confirm-password-reset`.
Compat `/v1/*` requires a valid API key (401 otherwise).

Declaration model:

- `permission` — `str`, or `list[str]` when the handler denies unless several
  independent permissions hold. Every id must exist in
  `rick_authorization.CANONICAL_PERMISSION_IDS`; a fabricated id (one the policy
  engine never grants) fails the test even if it looks plausible.
- `scope: "self"` — the route acts only on data the caller already owns (their own
  session, their own audit operations). `SELF_SCOPED_PATHS` is the explicit
  allowlist; being on it is a policy decision, never a default, and a self-scoped
  route must enforce **no** catalog permission at all.
- Parity is resolved through `routes.ROUTERS`, not `app.routes`: FastAPI 0.141
  mounts routers as `_IncludedRouter`, so `app.routes` never exposes an `APIRoute`
  and a parity check written against it compares nothing.
- Enforcement is proven twice: a static walk of the endpoint **and** its declared
  delegation targets (`_DELEGATED_ENFORCEMENT`, e.g. `POST /api/v1/chat` is
  checked inside `ChatApplicationService.chat`), plus a live request as a session
  that does not hold the declared permissions — which must be `403`.

## Threat model coverage

- Route auth gaps: registry ↔ handler parity, catalog membership, anonymous-reject
  over every entry, and a denied-session probe per declared permission.
- Self-scope boundary: `scope: "self"` routes serve their own caller and refuse a
  foreign `session_id` / `user_id` (`POST /api/v1/auth/sessions/revoke` → 403).
- Session confusion: single `get_current_session`; snapshot (role/perms/collections)
  bound at login; bearer never in JSON.
- Cookie vs Bearer: cookie wins when present; Bearer applies only without a cookie
  (compat/external domains). Tested both directions.
- Workspace/collection widening: `build_retrieval_context` — request input narrows
  only; foreign workspace/collection → 403. Tested (VET secret-collection probe).
- CORS: allowlist from config; wildcard+credentials rejected at startup; tested.
- CSRF: cookie `SameSite=Lax`+`Secure` (configurable; `Secure=false` local/test only);
  mutating browser requests rely on SameSite; explicit CSRF tokens deferred with
  deployment-model note (see ADR). CORS ≠ CSRF documented.
- Error leaks: safe templates; legacy detail allowlisted keys only; tests assert
  no `redis://`/traceback/provider bodies.
- Header spoofing/proxy: `X-Forwarded-For` is honored only when
  `TRUST_FORWARDED_HEADERS=1` and the direct peer belongs to the explicit
  `TRUSTED_PROXIES` IP/CIDR allowlist; malformed/untrusted hops are ignored and
  identity headers (`x-user-id` etc.) are always ignored.
- Startup safety: production requires `RICK_IDENTITY_MODE=production` and a
  secure session cookie. `SameSite=None` is rejected without `Secure`, and a
  configured legacy backend fails closed if its adapter cannot load.
- Rate limiting: in-process buckets cover login, chat/compatibility and both public
  recovery entry points; recovery keys hash tenant/email/client identity and return
  a neutral 429 envelope. A distributed limiter remains required for multi-replica
  production (the injected interface is ready; local fallback is not a production
  security boundary).
- Request bodies: the streaming middleware enforces the configured byte ceiling for
  both declared and chunked bodies. The JSON upload, reindex and retry routes use a
  finite UTF-8 decoder that rejects non-finite constants, duplicate object keys,
  recursive/malformed bodies and non-object/array roots before Pydantic validation;
  invalid input returns the canonical `validation_error` envelope.

## Permissions (canonical)

`PLATFORM_ADMIN` = `*`. `KNOWLEDGE_MANAGER` = corpus ops (no `users.manage`,
no `sessions.revoke`, no `runtime.manage`). `VETERINARIAN` = `chat.query`,
own history, `sources.read`, `collections.read` within granted collections only.
`sources.read` ≠ `library.browse`/`documents.read` (no library enumeration bypass).
