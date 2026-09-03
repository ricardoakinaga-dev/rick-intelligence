# RICK Intelligence — Phase 1.4 Report (Knowledge, Ingestion & Retrieval Extraction)

## Final Classification

`VERIFIED_CANDIDATE` — `packages/knowledge`, `packages/ingestion` and
`packages/retrieval` are real root-owned implementations with differential
parity to validated legacy behavior; low-risk API callers switched (DUAL +
flag rollback); no P0/HIGH review findings. Phase 0.6 stays `BLOCKED /
NOT_PROMOTED`; 1.3/1.3.1 stay `VERIFIED_CANDIDATE`. Phase 1.5 NOT begun.

## What was built

- `rick_knowledge` — byte-identical identity derivation, models, lifecycle
  (publish/unpublish/delete-cascade, deleted terminal), canonical payload
  builder + drift validator, hermetic store.
- `rick_ingestion` — parser iface (TXT/MD/DOCX + controlled PDF w/ heartbeat),
  recursive 1200/240 strategy (exact text parity incl. sentence-path finding),
  job state machine + transient/permanent split, idempotent pipeline
  (re-ingest converges; changed content → new version + prune; partials never
  publish; dimension mismatch fails pre-write; storage safety).
- `rick_retrieval` — tokenizer/sparse/RRF-k60/BM25F mirrors (rank/score/order
  parity), confidence blend, pipeline (query-time ACL + post revalidation +
  dedup + budget + immutable evidence), backends (memory / disk-fallback same
  ACL / lazy Qdrant), embedding + vector-store protocols with hermetic doubles.
- `rick_contracts.rag` — Document/Chunk/Evidence/RetrievalResult/IngestionJob
  DTOs; citations reuse the single Evidence schema.
- API switch — collections + document-metadata reads via
  `KnowledgeApplicationService` (default on, `RICK_API_ROOT_KNOWLEDGE=0`
  reverts); chat-evidence retrieval service flag-gated
  (`RICK_API_ROOT_RETRIEVAL`, default off); upload/worker stay stub/legacy.
- Facade — no legacy files touched; future caller switches via
  `adapters/legacy/` (auth facade precedent).

## Verification (2026-09-03, Python 3.12.3, hermetic)

| Check | Result |
| --- | --- |
| `phase14 units` (knowledge/ingestion/retrieval) | PASS — 17 |
| `phase14 differential` (chunk/identity/RRF/rerank/tokenizer parity, shadow rank/quality, E2E, auth differential) | PASS |
| `phase14 acl` + `api` (full 1.3 matrix incl. switch paths) | PASS — 108 total green |
| `phase14 legacy` (CVG contract/security/RBAC/closeout) | PASS — 40 |
| `phase14 benchmark` (chunk/RRF/rerank legacy vs root) | PASS — within 2x budget (root chunk faster) |
| Import boundary (no root→legacy; no HTTP in packages) | PASS |
| E2E (ingest→query→citation; grant removal denies) + failure E2E | PASS |
| Quality (recall/hit/MRR on fixtures; shadow overlap 1.0) | PASS |
| Legacy preservation | byte-identical; Professor untouched (1.5 not started) |

## Accepted limits (visible, not hidden)

Live Qdrant/OpenAI equivalence deferred (no credentials; adapters lazy, contract
proven); controlled-PDF live-page equivalence deferred (needs pdfplumber docs);
historical corpus blocker unchanged; `DeterministicHashEmbedding` is an explicit
non-semantic test double; tolerated drift = float rounding only.
ADR-008 audit, distributed limits, CSRF tokens carried forward.

## Phase 1.5 readiness

Safe to begin after this gate: RAG is a platform capability behind frozen
contracts (`rag-contract-v1`, `*-contract-v1`), versioned snapshots, and proven
facade seams. Chat orchestration/Professor extraction has a stable evidence
interface to build on.
