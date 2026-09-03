# Permission Resolution

Resolution order for every check:

1. Normalize the required id through `LEGACY_PERMISSION_ALIASES`.
2. Normalize the snapshot list (aliases, dedupe, sorted).
3. `"*" in snapshot` → grant. `required in snapshot` → grant.
4. Modern path ends here (deny otherwise). Legacy-helper path
   (`authoritative=False`, migration-only) may consult role defaults when the
   snapshot was OMITTED — never when it is explicit.

Overrides normalize as `{add, remove}` with removal winning conflicts; unknown
identifiers are preserved verbatim but inert (no enforcement point checks them).
`permissions_for_role` implements the wildcard materialization table from the
Phase 0.6-tested semantics, proven equivalent by the differential suite.

Denials return 401 (unauthenticated/expired) or 403 with the canonical error
envelope; no permission structure leaks. Denials emit `auth.access_denied`
audit events (ADR-008 best-effort policy preserved).
