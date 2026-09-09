# Retrieval architecture

The canonical retrieval pipeline is:

```text
normalize → analyze → dense + sparse → fusion → ACL revalidation
→ dedupe → diversity/rerank → context budget → evidence bundle
```

Every candidate is checked against server-derived tenant, workspace and
collection scope before it is returned. Qdrant requests contain the same
filters, and response payloads are revalidated so a faulty or compromised
backend cannot publish a foreign point. Empty grants deny without querying.

Scores are ranking signals. A blend of dense, sparse and fused scores is
reported as `retrieval_quality_score`; it must not be described as calibrated
probability. A future confidence subsystem requires a reviewed calibration
dataset and reports Brier score, ECE and reliability diagrams separately.

The checked-in evaluation pack is synthetic and offline. It proves harness
shape, ACL negatives and provenance checks only. Query decomposition, multi
query, HyDE, contextual retrieval, parent-child retrieval, MMR and semantic
deduplication remain feature-flagged experiments until an evaluation shows a
useful, reproducible delta.
