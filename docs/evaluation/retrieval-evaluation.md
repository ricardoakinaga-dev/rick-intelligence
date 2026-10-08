# Retrieval evaluation contract

`scripts/state_of_art/evaluate_retrieval.py` is the dependency-light offline
harness for the current retrieval contract. It reads recorded JSON or JSONL
observations and emits `retrieval-evaluation-result.v1`; it does not import the
API, call Qdrant, call an embedding/LLM provider, or turn a synthetic fixture
into production evidence.

`scripts/state_of_art/evaluate_pack.py` composes that harness with a versioned
manifest, explicit thresholds, model/corpus grouping, and structural negative
cases. The checked-in REC-22 local pack can be run with:

```bash
PYTHONPATH=scripts/state_of_art python3 scripts/state_of_art/evaluate_pack.py \
  --pack docs/evaluation/packs/rec22-local-v2 --pretty
```

The pack includes positive ranking/ACL/provenance observations and synthetic
`no_evidence`, `weak_evidence`, and `unsupported_assertion` cases. Its report
keeps results per model/corpus pair and returns `PASS`, `FAIL`, or
`INCONCLUSIVE` when a threshold or negative-case expectation cannot be proved.

## Run

```bash
PYTHONPATH=. python3 scripts/state_of_art/evaluate_retrieval.py \
  --fixture scripts/state_of_art/tests/fixtures/retrieval_fixture.json \
  --pretty
```

The checked-in fixture is intentionally small and synthetic. The current
observed result is `PASS` for that fixture: hit@1 `1.0`, recall@1 `0.75`,
hit@3 `1.0`, recall@3 `1.0`, ACL leakage `0`, citation/source coverage `1.0`,
claim citation precision/recall/completeness `1.0`, unsupported-claim rate
`0.0`, faithfulness `1.0`, and fixture-reported latency p50 `9 ms` / p95 `12 ms`.
These numbers
describe only the fixture and are not a production quality, capacity, or SLO
claim.

## Metrics and status semantics

- `hit@k` and `recall@k` use relevance annotations and deterministic rank order;
- ACL checks require observable tenant, workspace, collection, and trusted
  corpus scope, and report leakage as `FAIL` rather than hiding it;
- source, checksum, and citation coverage check provenance completeness and
  citation-to-retrieved-source correspondence;
- `metrics.citation_support` keeps claim support separate from retrieval
  relevance and citation validity. Each claim in a promoted offline pack must
  carry approved `reference_citation_ids` (or a reviewed `supported` boolean)
  plus the emitted `citation_ids` and an explicit reviewed `faithfulness`
  annotation; the five explicit metrics are `citation_precision`,
  `citation_recall`, `citation_completeness`, `unsupported_claim_rate`, and
  `faithfulness`;
- latency summaries are descriptive fixture observations using nearest-rank
  percentiles, with no implicit target threshold;
- `PASS` means the supplied observations satisfy the harness checks;
- `FAIL` means a supplied observation violates a check or the fixture is
  invalid;
- `INCONCLUSIVE` means required annotations/scope are absent or partial;
- `NOT_RUN` means no fixture was supplied or live evaluation was requested.

Pack thresholds are local harness thresholds over the supplied observations;
they do not constitute the D04 promotion pack. A real promotion decision still
requires reviewed golden queries, corpus provenance/license, freshness and
deletion cases, provider failure cases, threshold ownership, and a reproducible
runtime artifact.

## Stratified campaign harness

`scripts/state_of_art/evaluate_campaign.py` emits
`retrieval-campaign-result.v4`. The campaign manifest may declare
`evaluation_design.strata_dimensions`, and each case must provide exactly those
labels in `pack.strata`. Product-candidate eligibility requires the `risk` and
`ambiguity` dimensions. The dimension names describe measurement groups; their
labels, interpretation, and acceptance thresholds must come from the approved
domain/corpus decision (D04), not from the harness author.

The result reports ranking, source/citation, ACL, and latency metrics for each
combination of declared labels and measurement identity. Positive cases remain
separate by `model_id`/`corpus_id`; if a positive case omits either value, the
campaign uses the corresponding pack-manifest metadata default. Negative cases
remain separate by expected failure type. `uncertainty.overall` is pooled
across all positive cases; the `by_model_corpus` projection keeps each exact
pair separate, and `by_quality_stratum` adds the declared labels. Distinct
pairs and negative expectations therefore cannot disappear inside either
grouped projection.

Every non-empty valid Unicode identity string is preserved exactly, including
strings made only of whitespace; empty strings and strings containing an
unpaired surrogate are invalid. Components are
percent-encoded as path segments in `stratum_id`, so embedded separators and
surrounding spaces cannot collapse distinct model/corpus pairs. Declared
dimension JSON is canonicalized and encoded losslessly as unpadded URL-safe
base64 in the `labels-` suffix; consumers can recover the exact dimension map
without a truncated digest or collision assumption. Top-level offline fixture
checks remain aggregate and must be read with the pack's `per_model_corpus`
results. Grouped rows remain diagnostic: they do not
get a PASS threshold until the domain owner approves one. Expected abstentions
are listed separately, while observed response dispositions remain
`NOT_MEASURED` because this offline harness does not run the product or
generate answers. The top-level harness `PASS`, campaign `NOT_RUN`, and
eligibility `BLOCKED` are independent states; synthetic labels and
observations cannot make a product campaign eligible or complete.

The checked-in campaign has no risk/ambiguity annotations, so its stratified
quality array is empty and the readiness report names those missing dimensions.
Tests use values prefixed `synthetic_` only to verify grouping and calculation;
they do not define product categories.

Live mode is deliberately declaration-only. It returns `NOT_RUN` whether or
not provider environment markers exist until a separately reviewed live
adapter, corpus policy, and execution evidence are added.

## Claim-support contract

The optional case field below is the smallest supported shape for the
identity-level metrics plus the reviewed faithfulness annotation:

```json
{
  "claims": [
    {
      "claim_id": "claim-1",
      "text": "A bounded statement from the approved corpus.",
      "citation_ids": ["chunk-1"],
      "reference_citation_ids": ["chunk-1"],
      "faithfulness": true
    }
  ]
}
```

`reference_citation_ids` and `faithfulness` are approved evaluation
annotations, not generated by the answer. Missing annotations produce
`INCONCLUSIVE`; forged emitted IDs are a `FAIL`. The evaluator reports
faithfulness only when an approved reviewer supplies the explicit annotation;
it never infers entailment or truth from lexical overlap or citation identity.

## Evidence boundary

Fixtures must not contain secrets, raw clinical content, access tokens, or
unlicensed corpus data. A promoted evaluation pack still needs versioned
golden queries, corpus provenance/license, freshness/delete cases, provider
failure cases, threshold ownership, and a reproducible runtime artifact. The
current fixture is a harness smoke test, not that promotion pack.
