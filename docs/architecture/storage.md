# Storage architecture

RICK separates durable metadata, immutable source objects and the vector read
model behind typed ports.

| Data | Port | Local implementation | Production boundary |
| --- | --- | --- | --- |
| documents, chunks, lineage | knowledge store | in-memory/SQLite fixtures | PostgreSQL |
| immutable originals and derived artifacts | `ObjectStore` | private local envelope | S3/MinIO/R2-compatible service |
| dense/sparse read model | vector store | SQLite/fake | Qdrant |
| jobs and attempts | `JobQueue` | SQLite/fake | PostgreSQL durable queue |
| audit and history | audit/history ports | bounded local sinks | external durable stores |

Object keys are content-addressed where ingestion can safely share bytes.
Metadata carries checksum, byte size, source identity, document version,
parser/chunker/embedding/index versions and tenant/workspace/collection scope.
Writes are bounded, streamed, checksum-verified and idempotent. Deletion and
retention are policy operations, not an implicit filesystem unlink.

The local object store is intentionally rejected in production. The S3 adapter
signs requests with AWS Signature Version 4, keeps credentials outside the
package, supports S3-compatible endpoints and validates response sizes and
checksums. Credentials, endpoint reachability, encryption, retention,
replication and restore still require an external integration gate.
