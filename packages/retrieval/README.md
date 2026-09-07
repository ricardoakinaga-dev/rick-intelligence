# `packages/retrieval`

Reserved for authorized query normalization, dense/sparse retrieval, fusion,
reranking, deduplication, context selection, and evidence packing. The
`rag-contract-v1` behavior must be proven before extraction.

`SQLiteVectorStore` is a bounded, private, local/test-only read-model adapter
for restart drills. It persists validated point dictionaries and is wired only
when `RICK_VECTOR_SQLITE_PATH` is explicitly configured. It is not a Qdrant
replacement and is rejected in production-shaped environments.
