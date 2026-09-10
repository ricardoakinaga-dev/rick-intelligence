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

The local and PostgreSQL chat-history read models cap persisted JSON before
decoding, reject non-finite or malformed values and omit corrupt response rows;
this protects the API read boundary without claiming that local history is the
production durability authority.

The local SQLite clinical-case read model uses the same finite, byte-bounded
JSON boundary for hypotheses, evidence and tags. If any persisted case field
is oversized, non-finite or malformed, the case is omitted from reads rather
than exposed as a partial record; this is local fail-closed behavior, not a
claim of production clinical-data durability.

The local object store is intentionally rejected in production. The S3 adapter
signs requests with AWS Signature Version 4, keeps credentials outside the
package, supports S3-compatible endpoints and validates response sizes and
checksums. Credentials, endpoint reachability, encryption, retention,
replication and restore still require an external integration gate.

The local envelope has a fixed 4 KiB header budget. Its JSON is emitted as
canonical finite data and decoded fail-closed: non-finite constants, duplicate
keys, recursive/encoding failures and malformed metadata are corruption, not
usable object state. This hardens the local primitive without turning it into
evidence for the live S3/object-storage gate.
