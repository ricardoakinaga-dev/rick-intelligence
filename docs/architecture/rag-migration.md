# RAG Migration (Phase 1.6 strangler status)

| Legacy module | Root owner | Equivalence | Caller switch | Rollback | State |
| --- | --- | --- | --- | --- | --- |
| `rag_contract.py` identity/payload | `rick_knowledge.identity/payload` | byte-parity differential | contracts consumed by pipeline | revert import | ROOT_CANONICAL |
| `chunker.py` recursive | `rick_ingestion.RecursiveChunkingStrategy` | text/index/page parity | pipeline default | flag to legacy path | ROOT_CANONICAL |
| `document_parser.py` txt/md/docx | `rick_ingestion.parsers` | behavior tests | pipeline default | legacy parser | DUAL |
| controlled PDF ingest | `ControlledPdfParser` + heartbeats | contract tests (live PDF deferred) | opt-in (needs pdfplumber) | legacy job path | DUAL |
| `ingestion_service.py` | `rick_ingestion.IngestionService` + bounded API lifecycle facade | idempotency/version/failure matrix + publish gate | root multipart upload and reindex ON in local mode; production adapter deferred | legacy service | DUAL |
| `ingestion_job_service.py` | canonical job DTO + `apps/worker.LocalJobRunner` seam | state-machine/status/cancellation tests | root status/cancel routes ON; durable queue deferred | legacy jobs | DUAL |
| `vector_service.py` sparse/RRF/BM25F | `rick_retrieval` sparse/fusion/rerank | numeric/order parity | engine default (memory backend) | legacy functions | ROOT_CANONICAL |
| Qdrant live I/O | `QdrantVectorStore`/`QdrantBackend` (lazy) | adapter contract (live deferred) | flag-gated | legacy client | LEGACY_ONLY |
| disk fallback | `DiskFallbackBackend` | ACL-leakage tests | fallback order preserved | legacy search | DUAL |
| `search_service.py` orchestration | `RetrievalEngine.retrieve` | shadow rank/quality overlap | collections+doc-meta switched; Professor chat path switched by `RICK_API_CHAT_BACKEND` | `stub` or explicit `legacy` mode | DUAL |
| `document_registry.py` reads | `KnowledgeApplicationService` + store | same shapes, ACL-filtered | collections/doc-meta/upload lifecycle ON in local mode (`RICK_API_ROOT_KNOWLEDGE=0` reverts) | flag off | DUAL |
| provider boundary | `packages/providers` | hermetic HTTP/deterministic contract fixtures | Professor backend selects typed provider | `RICK_API_CHAT_BACKEND=stub` or `legacy` | DUAL |
| lock boundary | `packages/locking` | deterministic lease and HTTP adapter fixtures | Professor backend selects owner-safe lease | configure locker or local in-memory lease | DUAL |
| grounded chat orchestration | `packages/professor` | evidence/citation/failure contract tests | `/api/v1/chat` and `/v1/chat/completions` | backend mode rollback | ROOT_CANONICAL |

Tolerated drift: score float rounding. Not tolerated: different sources, missing
filters, changed canonical IDs, provenance loss. Live Qdrant/OpenAI equivalence
deferred (no credentials in this env); fixture-scoped hermetic parity is proven.
Historical corpus blocker (Phase 0.6) remains visible. The Phase 1.6 local
upload-path fixture is intentionally local and deterministic: live provider, Qdrant, Redis,
durable ingestion jobs, object storage, and the canonical web caller are not
implied by this table and remain later rollout gates. See
[`ingestion-lifecycle.md`](ingestion-lifecycle.md) for the exact process-local
contract and non-claims.
