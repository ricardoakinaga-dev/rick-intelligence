# Canonical Identity (`packages/identity`)

Single runtime source of truth for user/session lifecycle. Route authorization
lives in `packages/authorization`, never here.

## Layout (`rick_identity`, stdlib + `rick_authorization`)

- `protocols.py` — `CredentialVerifier`, `UserStore`, `SessionStore`, `IdentityProvider` ports.
- `passwords.py` — PBKDF2-HMAC-SHA256 100k, per-user salt, portable
  `$pbkdf2$<salt>$<hash>` format (migrated-record compatible).
- `stores.py` — `InMemoryUserStore`, `InMemorySessionStore` (TTL, revocation,
  password/role version capture). Storage only, no policy.
- `provider.py` — `IdentityProviderImpl`: login, `validate_session`, logout,
  revoke, lifecycle invalidation, one-time legacy migration. Effective
  permissions always resolved via the canonical engine and persisted as an
  AUTHORITATIVE snapshot (`authorization_snapshot_version = 1`).

## Provider modes (`RICK_IDENTITY_MODE`)

- `test`/`dev`: `PlainTestVerifier` + seeded demo users (never production).
- `production`: `Pbkdf2Verifier`; startup FAILS CLOSED if the test verifier is
  selected (`RuntimeError`).

## Lifecycle matrix (tested)

login → active/sliding TTL → logout | expiry | explicit revoke | disabled user |
password_version bump | role_version bump | credential reset. Session list exposes
opaque ids only; `get_user` redacts credential material; API responses carry
`session_token: null`.

Contracts: `identity-contract-v1`, `session-contract-v1` (`packages/contracts`).

The PostgreSQL adapter treats persisted ACL and session-snapshot JSON as an
untrusted boundary: reads are finite and byte-bounded at 64 KiB, reject
duplicate object keys, authorization lists and snapshot fields are
structurally validated, and corrupt rows fail closed instead of being
interpreted as legacy or wildcard authorization. User and session JSON writes
are canonicalized with non-finite values rejected and the same byte cap
enforced before the database `jsonb` cast. This is adapter boundary protection;
live PostgreSQL execution and recovery remain separate runtime evidence.

## API execution and logout boundary — AUD15

The [API auth routes](<../../apps/api/src/routes/auth.py>) execute identity,
credential and quota work through [bounded offload](<../../apps/api/src/services/identity_offload.py>):
40 shared admissions, no queue, one absolute configured request deadline. Sync,
async and lazy quota paths share this boundary; HTTP cancellation does not release
capacity while underlying work still runs. Application shutdown drains that work
before closing stores. This is a local scheduling guarantee, not a load SLO.

Logout succeeds only after the authority accepted by this API rejects the token.
A verification-only OIDC adapter is not a revocation capability: unsupported/no-op
logout returns unavailability, not a successful local blacklist or a claim of
upstream revocation. Only confirmed completion clears the response cookies; an
already-invalid session can receive cleanup-only success without inventing a new
revocation/audit mutation. Membership/store outage is not anonymous identity.

**Open audit boundary:** a blocking synchronous audit sink can persist completion
after an HTTP timeout even when revocation already occurred. A timeout therefore
must not be described as rollback. The strict completion criterion remains failed;
a transactional/fencing capability or explicit indeterminate-outcome contract
needs ratification before this gap can close. See the [implementation evidence and
remaining decisions](<../reports/implementacao-auditoria-2026-10-15.md>).

Reset admission is checked before KDF/one-time-token consumption, with private
hashed quota keys; successful consumption remains single-use. Real distributed
stores, deployed IdP behavior and mixed-version browser rollout require their own
authorized evidence; local tests do not supply that authority.
