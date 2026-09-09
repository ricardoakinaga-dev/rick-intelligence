# RAG evaluation contract

The canonical offline harness is `scripts/state_of_art/evaluate_retrieval.py`
and its versioned-pack wrapper `evaluate_pack.py`. A case contains a query,
scope, corpus/provenance, expected evidence, allowed answer or unsupported
claims, difficulty and risk level. Results are grouped by model and corpus and
must retain `PASS`, `FAIL` or `INCONCLUSIVE` semantics.

Required metrics are Recall@K, MRR, nDCG, reranker gain, answer relevance,
faithfulness, citation correctness/completeness, abstention accuracy and
unsupported-claim rate. ACL leakage, deletion/freshness, provider failure and
scope negatives are mandatory cases. A clinical golden set may be added only
after an externally supplied and validated corpus with provenance and license.

The checked-in pack is synthetic and intentionally small. It is a harness
baseline, not clinical evidence, production latency, or a promotion decision.
Live provider/Qdrant evaluation remains a separately authorized gate.
