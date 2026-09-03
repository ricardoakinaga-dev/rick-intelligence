# Ingestion Engine (`packages/ingestion`)

Validated pipeline as platform capability:
acquire → validate → parse → chunk → embed → index → verify → publish.

- `parsers.py` — `DocumentParser` protocol; TXT/MD/DOCX adapters; controlled PDF
  (page batches + heartbeat + prompt page-resource release; all-in-memory PDF
  stays disabled like legacy). Storage safety: server-generated keys, display
  names as metadata only, traversal/NUL/control-char sanitization.
- `chunking.py` — `ChunkingStrategy` with the recursive 1200/240 implementation
  as the one strategy (differential text parity proven, incl. the sentence-path
  no-overlap finding). No experimental chunking in migration.
- `jobs.py` — job contract + explicit state machine (impossible transitions
  rejected; retry creates a new attempt); transient vs permanent split
  (`is_retryable`); heartbeats carry stage/progress only.
- `pipeline.py` — `IngestionService.ingest/reindex/cancel/get_status`:
  idempotent re-ingest converges (same IDs, no drift); changed content → new
  version + stale-vector prune + unpublish; partial failures never publish;
  embedding dimension mismatch fails explicitly before any write;
  RequestContext/correlation propagate; no document text in events.

DTOs: `packages/contracts` (`DocumentDto`, `ChunkDto`, `IngestionJobDto`).
