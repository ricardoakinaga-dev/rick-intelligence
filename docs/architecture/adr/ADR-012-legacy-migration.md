# ADR-012 — Legacy migration semantics

Date: 2026-09-03. Status: Accepted.

Pre-snapshot records are `LEGACY_UNMIGRATED`: on next validation the canonical
provider derives state from role+overrides ONCE, persists it with
`authorization_snapshot_version = 1`, and marks the record `MIGRATED`. Later
requests use the stored snapshot authoritatively. Preserved CVG modules stay
byte-identical; the migration path for callers is
legacy route → `adapters/legacy/auth_facade` → canonical packages, switched
per route after differential equivalence (already proven at engine level).
