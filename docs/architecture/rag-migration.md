# RAG Migration (Phase 1.4 strangler status)

| Legacy module | Root owner | Equivalence | Caller switch | Rollback | State |
| --- | --- | --- | --- | --- | --- |
| `rag_contract.py` identity/payload | `rick_knowledge.identity/payload` | byte-parity differential | contracts consumed by pipeline | revert import | ROOT_CANONICAL |
| `chunker.py` recursive | `rick_ingestion.RecursiveChunkingStrategy` | text/index/page parity | pipeline default | flag to legacy path | ROOT_CANONICAL |
| `document_parser.py` txt/md/docx | `rick_ingestion.parsers` | behavior tests | pipeline default | legacy parser | DUAL |
| controlled PDF ingest | `ControlledPdfParser` + heartbeats | contract tests (live PDF deferred) | opt-in (needs pdfplumber) | legacy job path | DUAL |
| `ingestion_service.py` | `rick_ingestion.IngestionService` | idempotency/version/failure matrix | API upload stays stub (heavy last) | legacy service | DUAL |
| `ingestion_job_service.py` | `rick_ingestion.jobs` | state-machine tests | status reads via root DTO | legacy jobs | DUAL |
| `vector_service.py` sparse/RRF/BM25F | `rick_retrieval` sparse/fusion/rerank | numeric/order parity | engine default (memory backend) | legacy functions | ROOT_CANONICAL |
| Qdrant live I/O | `QdrantVectorStore`/`QdrantBackend` (lazy) | adapter contract (live deferred) | flag-gated | legacy client | LEGACY_ONLY |
| disk fallback | `DiskFallbackBackend` | ACL-leakage tests | fallback order preserved | legacy search | DUAL |
| `search_service.py` orchestration | `RetrievalEngine.retrieve` | shadow rank/quality overlap | collections+doc-meta switched; chat retrieval flag-gated | env flags | DUAL |
| `document_registry.py` reads | `KnowledgeApplicationService` + store | same shapes, ACL-filtered | collections + doc-meta ON (`RICK_API_ROOT_KNOWLEDGE=0` reverts) | flag off | DUAL |

Tolerated drift: score float rounding. Not tolerated: different sources, missing
filters, changed canonical IDs, provenance loss. Live Qdrant/OpenAI equivalence
deferred (no credentials in this env); fixture-scoped hermetic parity is proven.
Historical corpus blocker (Phase 0.6) remains visible.
