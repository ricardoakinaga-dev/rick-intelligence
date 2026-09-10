# Knowledge Engine (`packages/knowledge`)

Canonical document/chunk/collection domain. No Qdrant/OpenAI/FastAPI/Redis I/O.

- `identity.py` — byte-identical derivation to rag-contract-v1 (UUIDv5 namespace,
  `document:{ws}:{coll}:{sha256}`, `point:{chunk_id}`, `sha256:{16}`, aliases).
- `models.py` — `Document`/`Chunk`/`Collection` (+lifecycle states).
- `store.py` — `KnowledgeStore` protocol + hermetic store: idempotent upsert by
  stable IDs; `unpublish` retains refs but excludes from retrieval; `delete`
  cascades chunks (no orphans); deleted is terminal (new version for changes).
- `payload.py` — canonical point-payload builder + `validate_payload` drift check
  (all 20 required fields; compatibility shims never replace canonical fields).

Knowledge never decides access — authorization owns collections (see
`authorization.md`); retrieval filters at query time and revalidates after fusion.

The SQLite and PostgreSQL knowledge adapters treat persisted collection,
document and chunk metadata as untrusted JSON. Writes use canonical finite JSON
with a 256 KiB UTF-8 ceiling; reads reject non-finite, malformed, recursive or
oversized values and omit the complete corrupt row rather than exposing a
partial knowledge entity. This protects the local read model and adapter
boundary only; PostgreSQL durability, multi-instance consistency and recovery
remain separate runtime evidence requirements.
