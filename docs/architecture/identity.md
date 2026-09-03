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
