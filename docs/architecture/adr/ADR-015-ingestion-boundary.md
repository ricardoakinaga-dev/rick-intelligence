# ADR-015 — Ingestion pipeline boundary

Date: 2026-09-03. Status: Accepted.

`rick_ingestion` exposes `ingest/reindex/cancel/get_status` over parser,
chunking, job and pipeline seams. Formats frozen to validated TXT/MD/DOCX/PDF;
PDF stays controlled-batched; chunking behavior frozen (parity-proven). Partial
results never publish; dimension mismatches fail before writes. Heavy
upload/worker switching waits for isolated live equivalence.
