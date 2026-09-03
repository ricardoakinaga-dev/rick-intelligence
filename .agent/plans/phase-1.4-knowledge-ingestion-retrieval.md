# Phase 1.4 — Knowledge, Ingestion & Retrieval Engine Extraction

Status: IMPLEMENTATION_READY. Strangler migration; no rewrites, no deletions, no
chunking/embedding changes without benchmark; legacy files byte-identical.

## Characterization (legacy as-built, read-only source)

- Identity: `document:{ws}:{coll}:{sha256}` UUIDv5 under
  `uuid5(NAMESPACE_URL, rick-intelligence.local/rag-contract-v1)`; point =
  `uuid5(ns, point:{chunk_id})`; version `sha256:{16}`; aliases
  cvg_master_rag/rickvet_documents→rag_phase0; dense `dense`/1536/cosine +
  sparse `sparse` BM25; required payload fields frozen (rag-contract-v1).
- Chunking: recursive 1200/240, paragraph→sentence fallback, char overlap, page
  hints; `chunk_{doc}_{idx:04d}`; semantic chunker exists but recursive is canonical.
- Parsers: PDF/DOCX/MD/TXT; PDF forced to controlled pipeline (batches+heartbeat);
  docx via python-docx; random uuid4 at parse level (stability comes from ingestion).
- Retrieval: query-time workspace+collection Qdrant filters + post-filter;
  candidate_limit = max(top_k*10, 20); RRF k=60 `1/(k+rank+1)`; dedupe; confidence
  blend (dense/sparse/rrf/diversity/support gates); BM25F reranker default
  (k1=1.5 b=0.75 avgdl=200, weights 1.0/0.3/0.2, geo-mean blend); neural reranker
  optional w/ offline fallback; sparse = md5%100000 tf log(1+c); disk fallback ACL-scoped.
- Ingestion: atomic JSON writes, prune-previous idempotent reindex, job states +
  heartbeats, transient/permanent failure split.

## Tasks

| ID | Scope | Acceptance |
| --- | --- | --- |
| PH14-INVENTORY | this plan | characterization above |
| PH14-CONTRACTS | `rick_contracts.rag` DTOs | Document/Chunk/RetrievalResult/Evidence/Job DTOs; no second citation schema |
| PH14-KNOWLEDGE | `rick_knowledge` | identity (exact namespace/semantics), models, lifecycle, store w/ idempotent upsert + delete cascade |
| PH14-INGESTION | `rick_ingestion` | parser iface (txt/md/docx/pdf-controlled), recursive strategy (byte-parity), jobs state machine, pipeline w/ idempotency + partial-failure + retry split |
| PH14-INDEX | vector/embedding ifaces | VectorStore + EmbeddingProvider protocols, dim guard, deterministic stub for tests, lazy Qdrant adapter |
| PH14-RETRIEVAL | `rick_retrieval` | tokenizer/sparse/RRF/BM25F mirrors, pipeline (normalize→dense→sparse→fusion→reauth→dedup→rerank→budget→evidence), backends (memory/disk-acl/qdrant-lazy) |
| PH14-RERANK | reranker iface | disabled/BM25F(current)/model-future; offline fallback |
| PH14-PROVENANCE | payload builder + drift test | required-fields validation; evidence immutable |
| PH14-ACL | negative matrix | VET/foreign/forged/disk-leak/payload-scope |
| PH14-DIFFERENTIAL | legacy↔root harnesses | chunking/identity/RRF/rerank/ACL parity; quality overlap on fixtures |
| PH14-SHADOW | dual-run reads | doc-ids/chunk-ids/rank-overlap compare; no dual side-effects |
| PH14-API-SWITCH | low-risk callers | collections→root, doc-meta→root, search-adapter→root engine; DUAL + rollback; upload/worker last (stubs stay) |
| PH14-PERFORMANCE | baseline + budget | legacy vs root timings; no 2x regression w/o justification |
| PH14-SECURITY | §61-63 | negatives + provenance non-leak + storage safety |
| PH14-REVIEW/FINAL | 18 questions, gate | no P0/HIGH; 1.5 not started |

## Non-negotiables

- `packages/{knowledge,ingestion,retrieval}` import nothing legacy (CI).
- No HTTP/FastAPI/Redis/OpenAI/qdrant-client imports in domain code (lazy adapter only).
- Stable IDs byte-identical to legacy derivation; RRF/fusion/rerank numerically equivalent.
- Historical corpus blocker stays visible; quality equivalence fixture-scoped (live Qdrant/OpenAI deferred).
