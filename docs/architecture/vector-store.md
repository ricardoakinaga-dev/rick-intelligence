# Vector Store (`packages/retrieval/vectordb.py` + knowledge payload)

Abstraction: `VectorStore.ensure` semantics via `upsert_points`,
`delete_document`, `count_for_document` — domain logic never touches
qdrant-client APIs (lazy import inside `QdrantVectorStore`/`QdrantBackend` only).

Preserved behind the adapter: collection `rag_phase0`, named vectors
(`dense` 1536 cosine + `sparse` BM25), full canonical payload schema
(20 required fields, drift-tested), query-time workspace+collection filters
with post-filter defense in depth, delete-by-document scoping.

Standalone `packages/providers` / `packages/storage` remain future seams
(migration-map): the protocols defined here are the contract those packages
will implement; no behavior waits on them.

## Disk fallback policy

`DiskFallbackBackend` serves persisted chunk files only when the primary yields
nothing, through the same scoring and the EXACT same workspace/collection ACL
(leakage-tested). It is a degraded-availability path, not a second index: writes
always go through the canonical pipeline; fallback never publishes.
