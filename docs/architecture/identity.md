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
untrusted boundary: reads are finite and byte-bounded at 64 KiB, authorization
lists and snapshot fields are structurally validated, and corrupt rows fail
closed instead of being interpreted as legacy or wildcard authorization. User
and session JSON writes are canonicalized with non-finite values rejected and
the same byte cap enforced before the database `jsonb` cast. This is adapter
boundary protection; live PostgreSQL execution and recovery remain separate
runtime evidence.
