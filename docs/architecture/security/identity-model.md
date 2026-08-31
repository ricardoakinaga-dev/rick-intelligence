# Identity and session model

## Identity

The CVG enterprise identity is a persisted user record associated with a home
tenant and one or more accessible tenants. It carries lifecycle status,
password-change markers, a legacy-compatible role, canonical role resolution,
permission overrides, and optional collection grants.

New passwords use per-user salted PBKDF2-HMAC-SHA256 with 100,000 iterations.
Existing demo/legacy hashes remain verifiable during migration; new user records
use the PBKDF2 format. Passwords, reset tokens, and bearer values are not written
to audit metadata.

## Sessions

Sessions are server-side records keyed by a random URL-safe bearer value. The
session stores user/tenant snapshots, role and permission snapshots, creation and
last-seen times, expiry, revocation time/reason, and optional request metadata.
The API accepts the HttpOnly session cookie or a Bearer token for compatibility;
the cookie defaults to `Secure` and `SameSite=Lax` and can be disabled only for
local HTTP tests. Browser-facing session responses always set
`session_token: null`; the bearer is never placed in JSON or browser storage.

The lifecycle is:

```text
login -> active/sliding expiry -> logout or explicit revoke
                    |\
                    +-> expired/disabled/password-role-change invalidation
```

Every authenticated lookup checks expiry, revocation, user status, and whether a
password/status/role change predates the session. Password changes and user
deletion revoke the affected sessions. A session-targeted revoke verifies the
target token's owner before acting for a non-admin identity.

The role, effective permissions, canonical role, and authorized collection IDs
persisted at login are the authorization snapshot for that session. User
permission overrides are resolved as explicit additions/removals with removal
winning; wildcard expansion is materialized when a wildcard has removals. A
present `permissions_snapshot`, including an empty list, is authoritative and
is never replaced with current-role permissions during session refresh or tenant
switch. Override changes take effect on a new login. Password, status, or role
changes invalidate older sessions before a request is authorized.

The session administration list returns an opaque SHA-256 `session_id` and does
not return the bearer token. A revoke request resolves that identifier only on
the server; the raw token remains limited to the server-side session store and
explicit non-browser Bearer compatibility requests.

Anonymous bootstrap returns a neutral identity and an empty tenant list. It does
not enumerate tenant names, workspaces, counts, or document metadata. Login and
recovery therefore accept the tenant identifier manually; authenticated sessions
can receive their authorized tenant list for switching.

## Recovery and limits

Password reset requests return a neutral queued response whether or not the
identity exists. Reset tokens are hashed at rest, one-time, and time limited.
Login and reset request paths use in-memory rate buckets for the current process;
distributed rate limiting remains a deployment concern and is a documented
residual risk for production.

Evidence: `cvg-master-rag-v2/src/services/admin_service.py`,
`cvg-master-rag-v2/src/services/enterprise_service.py`,
`cvg-master-rag-v2/src/api/main.py`, and
`cvg-master-rag-v2/src/tests/test_phase05_security.py`.
