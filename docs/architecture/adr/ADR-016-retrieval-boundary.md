# ADR-016 — Retrieval engine boundary

Date: 2026-09-03. Status: Accepted.

`rick_retrieval` owns normalize→dense→sparse→fusion→reauth→dedup→rerank→budget→
evidence with a mandatory canonical RetrievalContext. No unscoped production
path; no FastAPI in the engine. Reranking is an interface (disabled/BM25F/model
slot) so future upgrades never rewrite the pipeline.
