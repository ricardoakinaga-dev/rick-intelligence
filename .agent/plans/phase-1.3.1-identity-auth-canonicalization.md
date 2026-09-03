# Phase 1.3.1 — Identity/Auth Canonicalization Closure

Status: IMPLEMENTATION_READY
Scope: bounded security correction. No ingestion/retrieval/Professor extraction,
no frontend/DB work, no new features. Phase 1.4 stays closed.

## Defect map (Phase 1.3 as-built)

| Duplicated policy | Current owner (wrong) | Canonical owner (target) |
| --- | --- | --- |
| `CANONICAL_PERMISSIONS` role table | `apps/api/src/services/identity_service.py` | `packages/authorization` (`ROLE_PERMISSIONS`) |
| `LEGACY_ROLE_MAP` + `canonical_role()` | `apps/api/.../identity_service.py` | `packages/authorization` (`LEGACY_ROLE_ALIASES`) |
| role-fallback in `has_permission()` | `apps/api/.../authorization_service.py` | forbidden for modern snapshots; engine enforces authority |
| collection defaults + workspace rule | `apps/api/.../authorization_service.py` | `packages/authorization` |
| `SessionSnapshot` model | `apps/api/src/models.py` | `packages/contracts` (re-export shim only) |
| in-memory session lifecycle | app-local provider | `packages/identity` (provider delegates to canonical authz) |

Known live defect: `has_permission()` falls back to role defaults when a permission
is absent from the snapshot — an explicit removal can be re-granted. Forbidden after closure.

## Tasks

| ID | Title | Acceptance |
| --- | --- | --- |
| PH131-AUDIT | Duplication map + freeze contract | this plan §defect map; contract versions frozen |
| PH131-CONTRACTS | Canonical security contracts | Role/Permission/UserIdentity/SessionSnapshot(+version/state)/CollectionGrant/RetrievalContext/Evidence/Citation/APIError in `packages/contracts` |
| PH131-IDENTITY | Real `packages/identity` runtime | stores+provider+lifecycle; PBKDF2; mode-gated test/dev/prod providers |
| PH131-AUTHZ | Real `packages/authorization` engine | registry/aliases/overrides/wildcard/authority/collections/workspace/RetrievalContext; no legacy imports |
| PH131-SESSION | Snapshot authority + migration | version=1, AUTHORITATIVE vs LEGACY_UNMIGRATED one-time migration; invalidation matrix |
| PH131-ACL | Collection/workspace ACL | narrow-only; cross-workspace frozen per role |
| PH131-API-INTEGRATION | Facades in apps/api | no local tables/maps/fallback; deps consume canonical APIs; cookie/bearer preserved |
| PH131-LEGACY-FACADE | Adapter-boundary facade | legacy CVG files byte-identical; facade in `adapters/legacy/`; differential parity proven |
| PH131-DIFFERENTIAL | Differential + property tests | legacy vs canonical vs observed; fixed-seed property invariants |
| PH131-SECURITY | Negative matrix | removal-wins, empty-denied, no-escalation, no-widening, no-refresh-restore |
| PH131-REVIEW | Fresh 18-question review | no P0/HIGH |
| PH131-FINAL | Gate + reports | VERIFIED_CANDIDATE or BLOCKED; 1.4 not begun |

## Non-negotiables

- `effective = role_defaults + add − remove`, removal wins, `[]` means none.
- Modern snapshots: never `if missing → check role`. Static test bans the pattern.
- Wildcard with removals materializes the registry (legacy semantics preserved).
- `packages/*` import nothing legacy; apps/api imports legacy only under `adapters/legacy/`.
- Legacy CVG files unchanged (preservation); equivalence via differential harness.
