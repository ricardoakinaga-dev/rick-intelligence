# `infrastructure/migrations`

`0001_control_plane.sql` creates migration bookkeeping and the initial job
control table. `0002_product_schema.sql` adds the tenant, identity,
membership, session, collection/grant, document/chunk, outbox, conversation,
message, and audit authorities. `0003_product_contract_extensions.sql` adds
defaulted adapter projection fields for password hashes, collection metadata
and grants, document/chunk source metadata, queue payloads, and bounded lookup
indexes. `0007_admin_audit_reconciliation.sql` adds bounded scheduling,
failure, dead-letter, and manual-retry state to the generic outbox for durable
administrative completion auditing. `0008_composite_scope_constraints.sql`
validates scope-preserving composite foreign keys for chunks, jobs,
collections/conversations, and conversations/messages. It performs no repair,
merge, or backfill; incompatible existing rows must be reconciled explicitly.
All migrations are additive; deleted or published records are not removed by an
automatic rollback.

Use `python3 infrastructure/scripts/migrate.py infrastructure/migrations
--check` for an offline filename/checksum check. Live application requires an
explicit `--apply --database-url` and the optional `psycopg` driver. The runner
uses a transaction advisory lock, rejects checksum drift, and records a row
only after the migration transaction succeeds. Live execution and restore
remain separate acceptance evidence.

The pending batch (including its history rows) commits atomically. Migration
`0005_rewrite_legacy_jobs.sql` has one explicitly inventoried historical
checksum compatible with the exact corrected source. The runner retains that
recorded checksum, verifies the canonical job boundary, and applies only later
files. There is no history reset, checksum update, force flag, or implicit
adoption of an existing RICK schema without history. Both offline validators
share filename, sequence, and pinned-0004/0005 integrity checks.

The earlier, length-only 0004 is also explicitly inventoried. Its upgrade uses
the pinned `0004_operation_guard.sql.inc` sidecar to add the canonical regex
constraint without dropping the original constraint or changing its history.
The runner records the repair's actual checksum in
`rick_schema_migration_repairs` in the same transaction as pending numbered
migrations. Repeats validate the repair ledger and constraint instead of
reapplying them. Package the whole migration directory, including this sidecar.

See [the Q24-07/Q24-11 upgrade procedure](../../docs/operations/migration-upgrade-2026-09-24.md)
for supported database states, source provenance, recovery, and opt-in live
tests using newly created, disposable PostgreSQL containers.
The [0008 preflight](../../docs/operations/0008-scope-migration-preflight.md)
uses `docs/operations/0008-scope-preflight.sql` to count incompatible scoped rows before
the additive composite constraints are applied.
Run `python3 infrastructure/scripts/scope_preflight.py --snapshot-id <snapshot-id>`
with the explicitly authorized connection in `RICK_PREFLIGHT_DATABASE_DSN`, or
set `RICK_PREFLIGHT_SNAPSHOT_ID` and run `make ops-scope-preflight`. The tool
enforces a read-only repeatable-read transaction and emits only aggregate counts
and provenance metadata. Exit 0 means all four counts are zero; conflicts return
1, errors return 2. This does not validate installed migration history or
constraint definitions and does not authorize applying migrations.
