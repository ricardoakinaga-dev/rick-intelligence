# Local durable vector read-model

`rick_retrieval.SQLiteVectorStore` is the hermetic restart adapter for the
root retrieval read-model. It uses a private SQLite WAL file, validates finite
vectors and bounded JSON payloads, upserts by stable `point_id`, verifies the
payload checksum on read, and exposes only the narrow point-store operations
used by the canonical ingestion/retrieval path. Read-side decoding applies a
byte cap before JSON parsing, rejects non-finite or dimension-invalid vectors,
and re-canonicalizes the bounded payload before checksum comparison; a
corrupted persisted point fails closed instead of becoming a usable result.

The API factory selects it only when `RICK_VECTOR_SQLITE_PATH` is configured
outside production. Demo points and newly published ingestion points then
survive an API factory restart, while the retrieval facade still applies the
same server-side tenant/workspace/collection ACL.

This is local/test durability evidence, not production vector-store evidence.
Qdrant remains the production adapter boundary; the local store does not claim
distributed consistency, replication, backups, encryption, or live endpoint
health.
