# `infrastructure/migrations`

`0001_control_plane.sql` creates migration bookkeeping and the initial job
control table. `0002_product_schema.sql` adds the tenant, identity,
membership, session, collection/grant, document/chunk, outbox, conversation,
message, and audit authorities. `0003_product_contract_extensions.sql` adds
defaulted adapter projection fields for password hashes, collection metadata
and grants, document/chunk source metadata, queue payloads, and bounded lookup
indexes. All migrations are
additive; deleted or published records are not removed by an automatic
rollback.

Use `python3 infrastructure/scripts/migrate.py infrastructure/migrations
--check` for an offline filename/checksum check. Live application requires an
explicit `--apply --database-url` and the optional `psycopg` driver. The runner
uses a transaction advisory lock, rejects checksum drift, and records a row
only after the migration transaction succeeds. Live execution and restore
remain separate acceptance evidence.
