# `infrastructure/scripts`

Reserved for deployment and operations scripts. Root Phase 1.1 validation and
test orchestration live in `scripts/phase11/` and do not perform production
operations.

`backup_restore.py` provides a local, file-based rehearsal boundary for
create/verify/restore/purge/reconcile. It expects already-exported component
artifacts, verifies SHA-256 and bounded counts, restores only into a new or
empty target, and defaults purge to dry-run. It does not dump live databases or
delete external volumes; those integrations remain an explicitly authorized
operations task.

For REC-30, exporters may attach bounded `semantic` metadata to each component:
`record_count`, `scope` (`tenant_ids`, `workspace_ids`, `collection_ids`), an
`acl_sha256`, and named `relation_checksums`. `reconcile_backup()` compares
those values as well as file summaries and fails closed when a declared logical
observation is missing. The CLI accepts `--required-component` and
`--expected-scope`; the observed JSON must be produced by the authorized
Postgres/object/vector/audit/conversation adapters described in the operations
runbook. No adapter is invoked by this repository-local script.
