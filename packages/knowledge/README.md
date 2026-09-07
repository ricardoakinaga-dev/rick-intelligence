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
