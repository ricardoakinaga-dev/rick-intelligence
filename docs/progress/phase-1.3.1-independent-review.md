# Phase 1.3.1 Independent Review (fresh read-only)

Reviewer: independent read-only pass over canonical packages, facades, adapters,
differential/property/negative suites, docs/ADRs. Method: read source + tests,
ran `phase131 full`, `benchmark`, and the Phase 1.3 `api-test` lane; grepped for
duplicate registries, role comparisons, and fallback patterns; verified legacy
dirs clean. No implementation files edited.

## Answers (18 required questions)

1. One permission registry? **Yes** — `ROLE_PERMISSIONS` etc. exist only in
   `rick_authorization` (singleton test green).
2. One role map? **Yes** — `LEGACY_ROLE_ALIASES` only in `rick_authorization`;
   app `LEGACY_ROLE_MAP` deleted.
3. Removals re-grantable? **No** — engine has no fallback branch; removal-wins
   tested incl. 500-case property sweep and refresh-stability.
4. Empty snapshots fall back? **No** — `[]` denies under `authoritative=True` (tested).
5. Silent recompute on modern sessions? **No** — refresh touches timestamps only;
   migration is explicit one-time `MIGRATED`.
6. Legacy migration explicit/one-time? **Yes** — `LEGACY_UNMIGRATED` → derive →
   persist → `MIGRATED`; stable on re-validation (tested).
7. VET gains library/docs/admin? **No** — negative matrix green.
8. KM escalates to platform? **No** — users/sessions-revoke/system denied (tested).
9. Workspace widening? **No** — engine `AuthorizationError` → 403 (tested).
10. Collection widening? **No** — narrow-only (tested).
11. RetrievalContext from trusted context only? **Yes** — factory takes
    server-side session + narrows; raw body never trusted.
12. apps/api defines policy locally? **No** — facades delegate; detectors green.
13. In-memory provider defines RBAC? **No** — seed DATA + delegation; mode-gated
    verifiers with production fail-closed (tested).
14. Root packages import legacy? **No** — stdlib/pydantic only; boundary tests green.
15. CVG semantics equivalent? **Yes** — differential parity across aliases, bases,
    overrides, wildcards, authority, collections, plus observed-API spot-checks.
16. Phase 1.3 API tests green? **Yes** — full matrix unchanged and passing.
17. Phase 0.6 blockers visible? **Yes** — report retains them; nothing erased.
18. Phase 1.4 safe? **Yes**, with carried prerequisites (unchanged from 1.3).

## Findings

- LOW: `normalize_permission_overrides` preserves unknown ids verbatim (legacy
  parity); inert at enforcement points — documented, acceptable.
- LOW: Compat `_compat_session` uses a fixed service identity; collection scope
  server-bound — acceptable, semantics unchanged from 1.3.
- INFO: Permission check ~1µs; kernel overhead unchanged.

No P0/HIGH/MEDIUM findings. Decision: **PASS — VERIFIED_CANDIDATE; do not begin
Phase 1.4 in this run.**
