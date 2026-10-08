# PostgreSQL migration compatibility — Q24-07 / Q24-11

Date: 2026-09-24. Scope: migration runner, migration sources, validation and
disposable PostgreSQL upgrade/recovery tests. The main implementation owner
retains canonical execution state and the broader API, identity/object-store
bootstrap and release evidence. This document does not approve production
cutover or claim those broader tasks are complete.

Acceptance sources: [Q24-07 and Q24-11](../backlog-qualidade-2026-09-24.md),
[executive plan](../plano-executivo-qualidade-2026-09-24.md), and
[roadmap M1/M2](../roadmap-qualidade-2026-09-24.md). Required outcomes are empty,
pre-0005 and already-applied-0005 compatibility; immutable recorded checksums;
rejection of unknown, tampered and incomplete states; repeatability; and real
transaction/rollback/restore evidence.

## Exact source inventory

`git log --all -- infrastructure/migrations/0005_rewrite_legacy_jobs.sql`
identified one historical revision, introduced by commit
`1c6fe4dc7da98386e2c09263d8d87df40e06ac6f`, blob `c3b38fc`.
The inspected worktree already contained four SQL corrections. They are
preserved byte-for-byte by this compatibility change.

The complete migration history also identified a previous 0004, introduced in
`a42a1eb9ee30fef0f1317b114679993f3ca862c9` (blob `4d4daf1`). Commit `1c6fe4d`
changed its operation check from length-only to the canonical identifier regex
(current blob `5a8d9cf`). Supporting a real pre-0005 installation therefore
requires preserving that historical 0004 digest **and** strengthening its
persisted constraint. The current numbered 0004 source is not modified.

| Artifact | SHA-256 |
| --- | --- |
| Historical 0004, actual Git bytes | `9ddcde2578d7c829a4efcba6db33fd37c7781b753f3676198a653f133436db8d` |
| Current 0004, required local bytes | `0621c726c6eaae17fba0a72a209452964eb6320c38f2ebc60966b1d562731274` |
| Historical 0005, actual Git bytes | `d577b70fb1af2790851c0f42d50d2269e80da412405cff2dfde53d63bb873a03` |
| Corrected 0005, required local bytes | `58878320223f9f30d42aea840c7e58795eb5c448daf90a0877adedc781cc9774` |
| Additive 0004 operation repair | `9691a200e4746e0cc69b035c7a81ac1ede8cab3053ab24b354294d9725afa1e2` |

The correction replaces two calls to `jsonb_object_length` with counts of
`jsonb_object_keys`, and replaces two oversized regex repetition bounds with
`*`. The existing explicit nonempty/512-character checks and 32-key checks
remain mandatory. The tests exercise their accepted and rejected boundaries
for both payload and result references, rather than assuming equivalent
behavior from a textual diff.

This inventory proves Git/worktree provenance and laboratory histories, **not
the contents of any user's deployed database**. No existing installation or
volume was inspected. Deployed checksums and data remain unknown until an
authorized, read-only inventory is performed.

## Supported states and decision

| Observed state | Runner behavior |
| --- | --- |
| Empty database, no RICK objects/history | Apply the ordered files, including corrected 0005, in one transaction. Record the bytes actually executed. |
| Valid contiguous prefix through current 0004 | Execute corrected 0005 against the legacy lane, then 0006. Preserve identity/grants/documents and convert valid jobs with attempts and projections. Invalid legacy data aborts the entire pending batch. |
| Historical 0004, with or without 0005/0006 already recorded | Retain its original checksum; apply the pinned additive operation constraint repair and record its actual digest in the separate repair ledger. Validate canonical state and apply pending numbered files in the same transaction. Invalid operations abort without changing either ledger. |
| Valid prefix including the historical 0005 checksum | Accept only the exact historical/current pair and exact filename. Retain the old checksum and `applied_at`; do not execute 0005 again. Verify the persisted canonical boundary before applying later files. |
| Corrected 0005 already recorded | Require its matching checksum, verify the same canonical boundary and execute only pending files. A repeated run changes neither data nor history. |
| Unknown checksum/application/version, duplicate/gapped history, or tampered/renamed 0004/0005/repair source | Stop. No force, baseline, rewrite-history or checksum-reset option exists. |
| Recorded repair with a mismatched digest, unknown repair ID, changed source history or missing/weakened/unvalidated constraint | Stop without repairing the recorded history or silently recreating the constraint. |
| Existing RICK tables with missing/empty history | Stop instead of treating the installation as empty or inventing prior history. |
| Recorded 0005 but NULL/noncanonical jobs, inconsistent attempt counts, or missing/disabled job guards | Stop before later migrations. No automatic merge, trigger disable, synthetic history rewrite or partial-state repair. |

The historical 0005 can execute on standard PostgreSQL when its legacy lane
is empty, including a database containing already-canonical jobs. The tests
create that state by **executing the historical bytes first**, then inserting
their actual digest in the same transaction. They also reproduce its failure
on populated legacy data. A successful old installation is never simulated by
running corrected SQL and then changing its recorded checksum.

The compatibility decisions are two narrowly pinned transitions in `migrate.py`,
not a generic list of ignored checksum errors. Other recorded checksum drift
still fails. Current local 0004, corrected 0005 and the repair source are pinned
even for an empty database and offline checking. Future revisions need a
separate reviewed strategy, not automatic expansion of the allowed pairs.

### Historical 0004 repair contract

`0004_operation_guard.sql.inc` adds the validated
`rick_ingestion_jobs_operation_v2_ck` constraint without dropping the original
one. It validates **all** rows, including canonical jobs that 0005 skips.
There is no automatic data cleanup or relaxation of validation. This sidecar
must be shipped with the migration directory; it is not a seventh numbered
migration and is not inserted into `rick_schema_migrations`.

Only the recognized historical-0004 path creates
`rick_schema_migration_repairs`. Repair ID `0004_operation_contract_v1` records
the source version/checksum, repair SHA-256, application and commit-transaction
timestamp. The runner executes the pinned repair SQL before inserting that
record, and commits both with the remaining migrations. It never updates or
deletes repair records. A later migration failure rolls back the additive
constraint and its repair record together.

On repeat, the runner checks the exact repair record and the actual validated
constraint definition. Unknown repair records, a changed source checksum, or
constraint drift abort the run. An existing unrecorded constraint with the
same repair name is not silently adopted; its installation requires inventory.
The number of numbered migration records remains six, preserving existing
runtime-consumer contracts.

## Transaction and failure contract

The runner acquires its transaction advisory lock **before** creating migration
bookkeeping. Concurrent first installations therefore serialize. It validates
the whole recorded history before executing pending SQL, checks that loaded
SQL bytes still match their discovered hashes, and executes that snapshot.

All pending DDL, data transformations and new history rows share one
transaction. Existing history rows are never updated or deleted. Per-file
success and the final success line are printed only after commit succeeds.
A later SQL error, deferred constraint failure or terminated backend cannot
leave earlier pending migrations recorded as committed.

Recognizing an old checksum does not prove an arbitrary schema is correct.
The additional boundary check verifies canonical contract markers, contiguous
attempt counts and five enabled canonical/append-only triggers. This is not a
complete database schema fingerprint, volume/capacity audit or attestation of
every custom function/privilege. Uninventoried custom schemas require review.

Database failures expose SQLSTATE, not driver messages, SQL payloads or DSNs.
Consult access-controlled PostgreSQL logs for detailed diagnosis. Connection
loss during commit can leave the outcome uncertain: inspect history after
reconnecting instead of inferring rollback from a missing success message.

## Operator procedure

Before an authorized upgrade, inventory the database and migration sources,
identify the state above, preserve a verified backup, and quiesce legacy writers
and workers. The legacy writer is disabled after successful 0005; mixed old
and new writers are not a supported rollout mode. Keep readers compatible with
the documented canonical schema. There is no automatic destructive downgrade.

Read-only history inventory:

```sql
SELECT version, checksum, application, applied_at
FROM rick_schema_migrations ORDER BY version;

SELECT contract_state, count(*) FROM rick_ingestion_jobs
GROUP BY contract_state ORDER BY contract_state;
```

The second query requires the 0004 schema. A missing history table on a
populated installation is an unknown state, not permission to bootstrap it.
When the source 0004 digest is historical and the repair table exists, also
inventory it without modifying its rows:

```sql
SELECT repair_id, source_version, source_checksum, repair_checksum,
       application, applied_at
FROM rick_schema_migration_repairs ORDER BY repair_id;
```

Offline checks do not connect to PostgreSQL:

```bash
python3 infrastructure/scripts/migrate.py infrastructure/migrations --check
python3 infrastructure/scripts/check-migration-order.py infrastructure/migrations
```

For an explicitly authorized database, provision `RICK_EXTERNAL_DATABASE_DSN`
through the operational environment without printing it or placing credentials
in command-line arguments. Set suitable libpq connection and SQL/lock timeouts
for that installation, then execute:

```bash
python3 infrastructure/scripts/migrate.py infrastructure/migrations --apply
```

The runner does not choose a production downtime window, transaction timeout or
batch size. The rewrite scans the legacy job lane and can hold locks for the
whole pending batch. Measure representative volume and choose a maintenance
budget before cutover; the small synthetic laboratory is not capacity evidence.

After success, compare the pre/post history prefix including timestamps;
confirm there are no NULL canonical rows, attempts match their append-only
history, document lineage is valid, and identities/grants remain unchanged.
Run the command again to check convergence before restoring writers.

## Recovery by state

For an ordinary SQL/deferred-constraint failure, reconnect and verify that the
previous history and data remain intact. Preserve diagnostics and the failed
source. Fix an unapplied artifact or reconcile invalid source data only through
an authorized, reviewed repair, then roll forward. Never delete a history row,
change an applied digest or remove an immutable attempt to force progress.

For a terminated migration backend, reconnect and inspect actual committed
history. The laboratory terminates only the uniquely identified migration
session after 0005/0006 SQL executes and before commit, verifies full rollback,
and retries successfully. A lost client response at commit still requires
inventory because its outcome may differ from a known pre-commit termination.

For a historical 0004, retain its digest and verify the additive repair's
recorded source/digest and validated constraint. Invalid operations require
reviewed source reconciliation; repair-history edits do not correct the data.
Restore or repeat the complete transaction after diagnosing a failed repair.

For an already-applied historical 0005, retain its digest. If the canonical
boundary is incomplete, stop and restore a verified backup into a separate
database or design a reviewed roll-forward repair. There is no reverse rewrite
that reconstructs lost legacy information. Cutover/restore must account for
writes after the backup; laboratory recovery does not establish production RPO.

For unknown/untracked history, preserve the original installation and compare
authorized backups/release sources. Do not adopt it as an empty database.

## Executable evidence

Fast/offline and live tests are in
`infrastructure/scripts/tests/test_migrate.py`, with SQL static checks in
`test_legacy_jobs_migration_static.py` and `test_postgres_jobs_migration_static.py`.
The historical fixtures reconstruct the four inverse 0005 corrections and the
single inverse 0004 change, checking their independently inventoried Git SHA-256
before execution. Neither fixture substitutes a checksum for unexecuted SQL.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  infrastructure/scripts/tests/test_migrate.py \
  infrastructure/scripts/tests/test_legacy_jobs_migration_static.py \
  infrastructure/scripts/tests/test_postgres_jobs_migration_static.py
```

Without explicit opt-in, PostgreSQL cases are skipped and do not count as live
evidence. With opt-in, unavailable Docker/image/driver or any required test
failure fails the suite. Use an already available PostgreSQL 16 or 17 image;
the fixture does not download one or connect to a caller-provided database:

```bash
RICK_MIGRATION_POSTGRES_TESTS=1 \
RICK_MIGRATION_POSTGRES_IMAGE=postgres:16-alpine \
RICK_MIGRATION_TEST_LOG_DIR=/tmp/rick-q24-migration-UNIQUE \
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  infrastructure/scripts/tests/test_migrate.py \
  infrastructure/scripts/tests/test_legacy_jobs_migration_static.py \
  infrastructure/scripts/tests/test_postgres_jobs_migration_static.py
```

Each live run creates a uniquely named/labeled container with a loopback-only
random port, tmpfs storage, one CPU, 512 MiB memory and 256 MiB data tmpfs.
Readiness is bounded at 30 seconds, Docker commands at 45 seconds, ordinary
test SQL at 10 seconds and lock waits at 5 seconds. The interruption case uses
a 45-second SQL ceiling and terminates the observed owned backend sooner.
Disposable loopback authentication contains no production credentials.

Every case creates a fresh database within that owned container. Recovery uses
`pg_dump` and `pg_restore` against two owned databases, preserves the synthetic
dump/hash, verifies the restored source, then upgrades and repeats. Finalizers
remove only the uniquely owned databases/container, verify its label before
container removal, and retain logs, image identity and teardown evidence. No
existing services, volumes or databases are used as fixtures.

Coverage includes both actual historical/current 0004 sources, their additive
repair and rollback, empty and concurrent first installation, populated legacy
statuses and leases, old/current recorded 0005, unmodified history timestamps,
permission retention, metadata boundaries, unknown/tampered/gapped/missing
history, incomplete legacy attempts and disabled guards, late SQL failure,
deferred commit failure, abrupt backend termination, CLI behavior, roll-forward
and backup restore. Synthetic corruption and trigger disabling occur only in
negative test setup; the production runner has no such recovery behavior.

Builder evidence for this execution resides under
`/tmp/rick-q24-migration-lvkwf_rh`. The final manifest binds exact file hashes,
commands, results and resource logs. The unchanged 0005 is included in that
manifest to prove preservation of the pre-existing SQL fixes. Test evidence is
local and synthetic; a builder report is not independent acceptance.

The repository's `make phase3-postgres-runtime` also owns canonical runtime
evidence and additional worker/crash assertions. Its wrapper writes outside
this builder's owned paths and remains with the main owner. Application
bootstrap, object-store policies, production-scale timing, full-stack restore
and release approval are not inferred from these migration tests.
