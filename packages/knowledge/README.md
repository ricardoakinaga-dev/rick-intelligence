# `packages/knowledge`

This package owns document lifecycle, collection membership, versioning,
checksum, metadata, provenance, and publication state. Qdrant HTTP must remain
outside this domain package.

`InMemoryKnowledgeStore` remains the hermetic fixture. `SQLiteKnowledgeStore`
is a local transactional durability adapter with a versioned schema and
restart-recovery coverage; it is not a claim that Postgres, object storage or
multi-instance deployment is complete.

Collection identity includes `tenant_id`, `workspace_id`, and `collection_id`.
The local schema migrates older workspace/name-only collection keys without
allowing one tenant to overwrite another.

Publication effects use `mutation_guard("document:" + document_id)` across
the ownership read and the complete effect. Memory shares a store lock;
SQLite shares a local file lock across handles/processes; PostgreSQL holds a
session advisory lock on a dedicated connection. PostgreSQL factories must
provide independent connections, including one additional connection while
an effect runs. The advisory lock acquisition has a 15 second timeout.
Ordinary document lifecycle writes participate in the same guard. The pipeline
persists a fresh `_ingestion_attempt` metadata token per execution, including
retries with the same queue job ID. This token fences writes and compensation.
Every participating writer must use this contract; the vector adapter must
complete/acknowledge its effect before returning. Remote effects that outlive
a process or database connection require the distributed failure proof in
AUD03-28; a local passing test does not prove that failure boundary.

`ensure_collection` inserts only when absent and returns the current catalog.
It never edits an existing title, description, status, version or metadata.
Archival/reactivation remain explicit catalog operations.

Catalog writers and final publication use `collection_guard` over the complete
tenant/workspace/collection tuple. Its versioned JSON key has a separate namespace
from document locks; separator-bearing scopes cannot alias. `upsert_collection`
and `ensure_collection` acquire it in every adapter. Read/modify/write catalog
services must acquire it before reading or mutating, including memory aliases.
Catalog reads and writes in the memory adapter now use deep copies, including
nested metadata, to match detached SQLite/PostgreSQL values. Mutating a public
`get_collection`, `list_collections`, `ensure_collection`, or caller-supplied
collection never changes the stored catalog; persist changes through guarded
`upsert_collection` or the catalog service.
The final decision holds collection then document then job-state locks through
commit. Lease guard checks happen before that interval. An archive that commits
first denies fresh and duplicate publication; one that starts during the protected
interval waits until publication finishes. SQLite uses its existing database file
gate; PostgreSQL uses a separate dedicated session for each distinct advisory lock
(a final publication may need two guard connections plus its write connection).
Direct SQL must participate in the same guard contract.

New identities use a versioned JSON tuple for every non-default tenant and
separator-bearing workspace. Default-tenant workspaces without `:` preserve
the frozen v1 UUID bytes. `legacy_document_id_for_content` is an explicit lookup
helper for installed identities. Ingestion resolves that ID only when tenant,
workspace, collection and checksum match; stored IDs, chunks, vectors and
citations remain unchanged. No installed data is automatically migrated.
Before any installed-data migration, inventory legacy identities/references
and scope conflicts, export the mapping, test it on a copy, approve the mapping
and rollback procedure, then perform that separate operation (AUD03-27).

Deleted IDs reject ordinary upserts, status changes and nonempty chunk writes
in all three adapters. `restore_deleted_document(snapshot, chunks)` is the
explicit maintenance operation for failed-delete compensation: it verifies
the entire retained Document except the restored lifecycle status, and restores
status and chunks atomically. Object/ingestion/content versions, object reference,
publication/creation timestamps, parser/chunker/embedding lineage, source fields,
and metadata cannot change. Durable document columns are retained rather than
rewritten during SQLite/PostgreSQL restoration. Legacy omitted object/ingestion
defaults must resolve to the tombstone; omitted publication time retains the
durable timestamp. A different explicit value, attempt or lineage is rejected.
Idempotent deleted upserts cannot replace retained lineage. Memory deletion
detaches prior live aliases and returns detached tombstones.
Callers restoring a failed delete must use this operation rather than ordinary
`upsert_document`; a tombstone is otherwise terminal.
