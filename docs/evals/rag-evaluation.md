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

## Pack threshold and ranking semantics

Every manifest threshold is required and is evaluated both against the aggregate
and independently against each positive-case `(model_id, corpus_id)` group.
`per_model_corpus[].thresholds` retains the metric path, operator, unchanged target,
observation and verdict. Any failing group fails the pack even if the aggregate
passes. Negative structural cases remain separate from ranking averages.

A missing path, null/non-finite/non-numeric value, or nearest metric status of
`NOT_RUN`, `INCONCLUSIVE` or `no_data` produces threshold `FAIL`, `observed: null`
and `data_status: no_data`. An observed numeric zero is still a real measurement;
it can satisfy a zero target only when its metric is observable. Missing packs
remain `NOT_RUN`; evaluator exit codes are 0 for PASS, 1 for FAIL, 2 otherwise.

The pack wrapper additionally reports `metrics.ranking.mrr` (macro mean of
reciprocal first relevant ranks over the full returned list) and
`metrics.ranking.ndcg_at_k` (macro binary nDCG, log2 rank discount, ideal ranking
truncated to K). Results use the existing explicit-rank ordering and identity
aliases; each result contributes at most one binary gain, and repeated relevant
IDs never earn another gain. Empty retrieved results with relevance annotations
score zero; absent/empty relevance annotations are undefined, not zero.

Known-value tests use RR = 1/2 for a first match at rank 2 and 1/3 at rank 3;
MRR for ranks 2, 1 and no match is `(1/2 + 1 + 0)/3 = 0.5`.
For one relevant result at rank 3, nDCG@3 is `1/log2(4) = 0.5`.
For two relevant IDs but only the first returned within K, nDCG is
`1/(1 + 1/log2(3)) = 0.6131471927654584`. These tests do not obtain
expected values from the implementation.

### Frozen baseline conflict / Q17-14.A partial

The unchanged `rec22-local-v1` fixture has alpha Recall@1 = 1/2 and beta
Recall@1 = 1, so its aggregate passes the frozen 0.75 threshold while alpha fails.
Consequently strict per-group enforcement makes `make eval-retrieval-pack` fail;
keeping this exact baseline green and enforcing every unchanged threshold per
group are incompatible. No exemption, post-result threshold relaxation or
fixture relabeling is applied. A pack-owner decision is required before a new
baseline can be accepted. The regression explicitly preserves this discrepancy.

Reranker gain, answer relevance, abstention accuracy, representative licensed
holdout data and live semantic evaluation remain NOT-DONE; the new ranking
metrics do not silently add or change any frozen threshold.

### Successor synthetic baseline / Q24-06

`rec22-local-v1` remains immutable historical evidence of the invalid per-group
Recall@1 contract above. The active synthetic harness is now
`rec22-local-v2`: it keeps Hit@1 = 1.0 to require a relevant first result and
measures coverage with Recall@2 = 1.0, which is mathematically attainable for
the alpha case containing two relevant IDs. Every threshold still applies to
the aggregate and to each positive `(model_id, corpus_id)` group.

This successor changes only the synthetic harness contract. It does not claim
clinical quality, choose a production model, authorize a corpus, or replace the
representative holdout work required by Q24-26.
