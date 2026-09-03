# Retrieval Engine (`packages/retrieval`)

Hybrid engine: normalize → dense → sparse → RRF fusion → authorization
revalidation → dedup → rerank → context budget → immutable evidence.

- `sparse.py` — MD5%100000 token hash, min_len=2 stop filtering, tf log(1+c),
  collision aggregation (mirror).
- `fusion.py` — RRF k=60, `1/(k+rank+1)` (numerically equivalent; rank parity proven).
- `rerank.py` — `Reranker` protocol; `DisabledReranker`; `BM25FReranker`
  (k1=1.5/b=0.75/avgdl=200, weights 1.0/0.3/0.2, geo-mean blend, order parity
  proven); `ModelReranker` future slot with offline fallback.
- `pipeline.py` — `RetrievalEngine` requires a canonical `RetrievalContext`;
  candidate_limit = max(top_k*10, 20); confidence blend mirrors validated gates;
  adjacent-duplicate dedup; char-budget context selection (never unbounded).
- `backends.py` — `RetrievalBackend` protocol; `InMemoryBackend`; `DiskFallbackBackend`
  (identical ACL); `QdrantBackend` (lazy client, query-time filters + post-filter).
- `vectordb.py` — `EmbeddingProvider`/`VectorStore` protocols;
  `DeterministicHashEmbedding` (hermetic, documented non-semantic);
  `InMemoryVectorStore` (idempotent upsert); `QdrantVectorStore` (lazy adapter,
  named vectors, canonical payload, ACL filters).

Evidence uses `packages/contracts` (`EvidenceDto`/`RetrievalResultDto`) — no
second citation schema; provenance frozen at selection.
