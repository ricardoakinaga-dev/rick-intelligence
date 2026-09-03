# RICK Intelligence — Phase 1.3.1 Report (Identity/Auth Canonicalization Closure)

## Final Classification

`VERIFIED_CANDIDATE` — the Phase 1.3 re-grant defect is closed: canonical
`packages/authorization` + `packages/identity` + `packages/contracts` own all
security semantics; `apps/api` holds no local registries, role maps, or
fallbacks. Differential parity with preserved CVG semantics proven; legacy files
byte-identical. No P0/HIGH review findings. Phase 0.6 stays `BLOCKED /
NOT_PROMOTED`; 1.3 stays `VERIFIED_CANDIDATE`. Phase 1.4 NOT begun.

## Defect closed

Phase 1.3 `services/authorization_service.has_permission()` fell back to role
defaults when a permission was absent from the snapshot, so an explicit removal
could be re-granted. The canonical engine has no fallback branch under
`authoritative=True`, snapshots persist explicitly, refresh never recomputes,
and a static test bans the pattern from app code.

## What was built

- `packages/authorization/src/rick_authorization/` — engine (stdlib only):
  roles/registry/aliases/overrides/wildcard/authority/collections/workspace/
  `RetrievalContext`; tests incl. 500-case fixed-seed property sweep.
- `packages/identity/src/rick_identity/` — protocols, PBKDF2 passwords,
  in-memory stores, provider (login/validate/logout/revoke/invalidation,
  one-time `LEGACY_UNMIGRATED`→`MIGRATED` migration, mode-gated verifiers).
- `packages/contracts` — `security.py` (Role/Permission/UserIdentity/
  SessionSnapshot+version/state/CollectionGrant/RetrievalContext/Evidence/APIError).
- `apps/api` — facades only: authorization delegates authoritatively,
  identity wraps canonical stores/provider (seed DATA, no policy),
  `models.SessionSnapshot` re-exports canonical (drift-tested), cookie-wins
  preserved, `RICK_IDENTITY_MODE` gating (+`identity_mode` config validation).
- `adapters/legacy/auth_facade.py` — canonical-backed legacy-shaped helpers
  (default authoritative) for future per-route caller switch.
- Tests: canonical packages, differential (aliases/base/overrides/wildcard/
  authority/collections/observed), source-of-truth + duplication + role-compare
  + fallback bans, canonical negatives (removal-wins, empty-denied,
  no-escalation, no-widening, no-refresh-restore, production fail-closed,
  serialization hygiene).

## Verification (executed 2026-09-03, Python 3.12.3, hermetic)

| Check | Result |
| --- | --- |
| `phase131 canonical` (package suites) | PASS |
| `phase131 differential` (parity + truth + negatives) | PASS |
| `phase131 api` (full Phase 1.3 matrix, unchanged) | PASS — 44 + new suites, 78 total green |
| `phase131 legacy-auth` (CVG `test_phase05_security`, `test_phase06_rbac`) | PASS — 26 passed |
| `phase131 benchmark` (permission check) | p50 0.931µs / p95 1.162µs — negligible |
| Legacy preservation | `cvg-master-rag-v2`, `rick-professor`, `modulo-redis-locker` clean |
| `packages/*` legacy-import ban | PASS (existing boundary test; canonical pkgs stdlib/pydantic only) |

## Residual risks (carried, not new)

ADR-008 audit fail-open→fail-closed follow-up; in-process rate buckets;
SameSite-only CSRF; Professor/Locker suites not re-run here (no node_modules).
Phase 0.6 corpus/provider/deployment blockers remain visible and unchanged.

## Phase 1.4 readiness

Safe to begin after this gate: identity/authorization are platform capabilities
with frozen contracts (`*-contract-v1`), versioned snapshots, and a proven
facade seam. Prerequisites carried: fail-closed audit, distributed limiting,
CSRF tokens, Professor wiring.
