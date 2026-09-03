# ADR-017 — Vector store abstraction

Date: 2026-09-03. Status: Accepted.

`VectorStore`/`EmbeddingProvider` protocols hide qdrant-client (lazy) and model
choices from domain code. Deterministic hermetic doubles serve tests; dimension
guards make model changes explicit (fail or reindex, never silent corruption).
Standalone providers/storage packages will implement these protocols later.
