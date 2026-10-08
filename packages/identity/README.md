# `packages/identity`

Canonical users, credentials, sessions, revocation and authorization snapshots.
Policy is supplied by `rick_authorization`.

Modern `AUTHORITATIVE` and `MIGRATED` snapshots require version 1, a canonical
role, and explicit string lists for `permissions` and `allowed_collection_ids`.
Empty lists deny access. Missing or malformed fields, incompatible versions
and inconsistent role labels fail closed in the provider and PostgreSQL decoder.
Public validation intersects persisted permissions and collection grants with
current scoped user authority on every call, even if `users.save` preserves
version numbers. The persisted modern snapshot stays immutable: current
additions cannot restore its removals or expand its finite scope. A mismatch
between its canonical role and the current user's role denies the session.

Legacy import accepts either `LEGACY_UNMIGRATED` without modern permissions or
canonical role (version omitted or 1), or an old record with all four snapshot
markers absent: state, version, canonical role and permissions. It derives once
from the scoped user authority, then persists `MIGRATED` before authenticating.
The role and role label come from the current user, never the historical
session. Historical role defaults cap permissions; a role promotion beyond
those defaults requires fresh login. Explicit legacy session collection grants
(including `[]`) intersect current grants before persistence. Only an omitted
session grant field has no historical collection ceiling.
`SessionStore.update_authorization_snapshot(token, expected=..., snapshot=...)`
is the additive persistence capability: compare the previous record/snapshot,
reject expired/revoked or changed sources, and return a boolean. Memory and
PostgreSQL implement it; modern-only custom stores remain usable, but cannot
authenticate a legacy record without this capability. PostgreSQL commits the
conditional update before returning the migrated session; write failures remain
store errors and never yield an authenticated snapshot.

Collection grants omitted from a legacy user may use historical role defaults.
Explicit `authorized_collection_ids=[]`, invalid fields and missing grants on
modern records deny collection access. Importers must preserve omission rather
than replace it with an empty list. Modern demo/bootstrap data requiring global
scope must supply `authorized_collection_ids=["*"]` explicitly.

`OIDCIdentityProvider` requires an authoritative membership resolver. Its return
mapping must contain exact `subject` and `tenant_id` bindings, nonempty `user_id`
and `workspace_id`, a known role, `status="active"`,
`membership_status="active"`, and an explicit `authorized_collection_ids` list.
Optional `permission_overrides` is a mapping whose `add` and `remove` entries,
when present, are string lists. Disabled, incomplete or malformed memberships
and resolver failures yield anonymous sessions. Token role/workspace claims do
not supply authority; only subject and tenant select the lookup. Email may come
from the token for presentation. The `workspace_claim` constructor argument is
retained for compatibility but no longer grants a fallback workspace.

Resolvers wrapping `PostgresUserStore` must map its verified `external_subject`
to `subject` and retain both user `status` and `membership_status`; the provider
does not presume a database row alone proves the external identity binding.
No native SQLite identity adapter exists here. Tests use a detached SQLite
protocol fixture to check persistence/reopen semantics and DB-API fixtures to
check the PostgreSQL contract; these do not replace live PostgreSQL/IdP evidence.

The Lead can run the isolated live adapter suite after setting
`RICK_AUD03_IDENTITY_POSTGRES_DSN` to the private disposable lab DSN:

```sh
/tmp/rick-audit-20261002-618htkqr/testenv/bin/python -m pytest \
  --import-mode=importlib -p no:cacheprovider -q \
  packages/identity/tests/test_aud03_postgres_live.py
```

Use `PYTHONPATH` for the current repository and its package source directories.
The suite creates random private schemas from canonical identity table DDL and
credential/grant column additions, then drops only those schemas. It checks
durable grant revocation, modern corruption, concurrent legacy migration,
terminal migration fences and an OIDC resolver composed with PostgreSQL users.
It does not run the complete migration chain or contact a real external IdP.
Rework tests named `test_live_rework_*` additionally cover stale legacy admin
roles, explicit legacy collection denial/finite scopes and same-token revocation
through `PostgresUserStore.save` without a version bump.
