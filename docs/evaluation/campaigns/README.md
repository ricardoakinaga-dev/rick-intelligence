# Retrieval campaign manifests

`evaluate_campaign.py` binds an offline evaluation pack to a candidate identity,
canonical configuration hash, corpus-rights state, provider state, domain
review, minimum positive sample size, and train/calibration/reserved split. It
does not call a product API, retrieval service, model provider, or network. It
emits `retrieval-campaign-result.v4`.

Run the checked-in synthetic example from the repository root:

```sh
PYTHONPATH=scripts/state_of_art PYTHONDONTWRITEBYTECODE=1 \
  python3 scripts/state_of_art/evaluate_campaign.py \
  --campaign docs/evaluation/campaigns/rec22-local-synthetic-v1/manifest.json \
  --pretty
```

Interpret the result fields separately:

- `status: PASS` means the local manifest and fixture pack were inspected and
  the offline pack evaluator passed its own checks.
- `campaign_status: NOT_RUN` means no product candidate or provider was
  evaluated, even if a manifest declares readiness.
- `eligibility_status: BLOCKED` identifies unmet prerequisites. The example
  intentionally has no approved product corpus, provider, domain review,
  representative sample, or assigned campaign split.
- `uncertainty` reports descriptive two-sided 95% Wilson intervals for
  case-level Hit@1. `uncertainty.overall` pools all positive cases;
  `by_model_corpus` separates exact model/corpus identities, and
  `by_quality_stratum` further separates the declared labels. These intervals
  assume independent Bernoulli query outcomes; the five synthetic fixtures are
  not a population sample and support no product-quality claim.
- A manifest may declare `evaluation_design.strata_dimensions`; every fixture
  case must then provide exactly one label for each dimension in
  `pack.strata`. A product candidate must declare both `risk` and `ambiguity`.
  Quality rows and Hit@1 intervals are separated by each positive case's
  model/corpus pair, or each negative case's expectation, as well as the exact
  declared label combination. Different candidates and negative-case types
  therefore cannot be pooled into one row. These descriptive rows remain
  diagnostic; the harness invents no domain labels or acceptance thresholds.
  Positive cases may inherit missing `model_id` and `corpus_id` from the pack
  manifest's `metadata`. Every non-empty valid Unicode identity string is
  preserved exactly, including whitespace-only strings; empty strings and
  strings containing an unpaired surrogate are invalid.
  `stratum_id` percent-encodes
  identity components and stores canonical dimension JSON as reversible,
  unpadded URL-safe base64, so IDs do not depend on a truncated label hash.
- `offline_fixture_checks` surfaces the pack's recorded ranking, source
  support, citation support, and ACL leakage metrics so their synthetic scope
  stays visible in the campaign result.
- Negative fixtures record expected abstention labels, but their observed
  answer disposition is always `NOT_MEASURED`; structural retrieval/citation
  checks do not test generated-answer abstention.

A real campaign requires a separately authorized, representative corpus and
labels; approved rights and retention; a product candidate with immutable
source/configuration identity; complete disjoint train, calibration, and
reserved case assignments; enough cases in every declared positive
model/corpus/risk/ambiguity stratum; an authorized provider; and independent
domain approval of ambiguity handling, risk, and thresholds (D04). Passing
this wrapper never executes or authorizes that campaign.
