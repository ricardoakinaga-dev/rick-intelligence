# API Security (`apps/api`)

## Default-deny + allowlist

Every non-public route declares `auth+permission` in `routes/ROUTE_REGISTRY`;
structural test fails on missing policy. Public: `/health/live`, `/health/ready`,
`/api/v1/auth/login`, `/api/v1/auth/recovery`, `/request-password-reset`,
`/confirm-password-reset`. Compat `/v1/*` requires a valid API key (401 otherwise).

## Threat model coverage

- Route auth gaps: registry + anonymous-reject test over every entry.
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
- Header spoofing/proxy: `X-Forwarded-For` honored only when `TRUST_FORWARDED_HEADERS=1`
  (+`TRUSTED_PROXIES`); identity headers (`x-user-id` etc.) always ignored.
- Rate limiting: in-process buckets for login/chat now; Redis-backed interface ready;
  deployment limitation documented (single-process residual risk).

## Permissions (canonical)

`PLATFORM_ADMIN` = `*`. `KNOWLEDGE_MANAGER` = corpus ops (no `users.manage`,
no `sessions.revoke`, no `runtime.manage`). `VETERINARIAN` = `chat.query`,
own history, `sources.read`, `collections.read` within granted collections only.
`sources.read` ≠ `library.browse`/`documents.read` (no library enumeration bypass).
