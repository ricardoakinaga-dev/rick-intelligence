# Session Authority (HARD SECURITY INVARIANT)

An authenticated modern session snapshot is AUTHORITATIVE:

- `permissions` persisted at login (or one-time legacy migration) is the final
  word. `permissions = []` means NO permissions — never "derive role defaults".
- The forbidden pattern is exactly:

  ```text
  if permission not in session.permissions:
      check role defaults        # FORBIDDEN for modern snapshots
  ```

  It is banned by `test_no_role_fallback_pattern_in_app_code` and by the engine
  itself (`permission_granted(..., authoritative=True)` has no fallback branch).

- Legacy records without a snapshot carry `authorization_state = LEGACY_UNMIGRATED`
  (or lack `permissions`). On next validation they are migrated ONCE
  (`MIGRATED`, persisted with `authorization_snapshot_version = 1`); all later
  requests treat the stored snapshot as authoritative.
- Session refresh (`validate_session`) touches timestamps only — it never
  recomputes permissions, so removals cannot be restored (tested).
- Invalidation (logout/expiry/disabled/password_version/role_version/revoke)
  returns an anonymous snapshot before any authorization decision.
