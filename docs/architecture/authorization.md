# Canonical Authorization (`packages/authorization`)

Single policy engine (`rick_authorization.policy`, stdlib only, no legacy imports).

## Owned artifacts

`CANONICAL_ROLES`, `CANONICAL_PERMISSION_IDS`, `ROLE_PERMISSIONS`,
`LEGACY_ROLE_ALIASES`, `LEGACY_PERMISSION_ALIASES`, override normalization,
`permissions_for_role`, `permission_granted`, collection grants, workspace rules,
`build_retrieval_context`. Contract: `authorization-contract-v1`,
`retrieval-context-v1`.

## Roles (frozen, no proliferation)

- `PLATFORM_ADMIN` = `("*",)` with removal-materialization.
- `KNOWLEDGE_MANAGER` = corpus ops (`chat.query`, `history.read`, `library.browse`,
  `documents.read/upload/manage`, `sources.read`, `collections.read/manage`,
  `ingestion.run`, `reindex.run`, `observability.read`, `audit.read`,
  `corpus.audit/repair`). NO `users.manage`, `sessions.revoke`, `runtime.manage`.
- `VETERINARIAN` = `chat.query`, `history.read`, `sources.read`, `collections.read` only.

## Algebra

`effective = role_defaults + add − remove`; removal wins; `[]` means none.
Wildcard with removals materializes the registry; removing `"*"` denies
inheritance while explicit adds survive.

## Authority

Modern snapshots are checked with `authoritative=True`: no role fallback, ever.
Legacy sessions migrate explicitly (`LEGACY_UNMIGRATED` → derive once → persist →
`MIGRATED`). Cross-workspace: `PLATFORM_ADMIN` only. Collections: narrow-only.

See `security/permission-resolution.md` and `security/session-authority.md`.
Differential parity vs preserved CVG semantics is proven in
`apps/api/tests/test_differential_auth.py`; legacy files are byte-identical.
