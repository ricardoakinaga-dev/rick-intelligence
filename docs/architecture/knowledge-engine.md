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
