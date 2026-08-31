# Phase 0.6 legacy CVG test classification

## Scope and decision rule

This record classifies the frozen Phase 0.5 legacy surface individually. It
does not add, synthesize, or silently substitute a dataset. The permitted
classification vocabulary is:

`REAL_REGRESSION`, `MISSING_REQUIRED_FIXTURE`, `STALE_TEST`,
`INTENTIONAL_POLICY_CHANGE`, `LEGACY_UNSUPPORTED_BEHAVIOR`,
`ENVIRONMENT_DEPENDENT`, `BROKEN_TEST_INFRASTRUCTURE`, and `UNKNOWN`.

The historical baseline required by Phase 0.6 is **364 passed, 19 failed, 14
skipped, and 6 errors**. An independent read-only reproduction on 2026-08-31
used the pinned Python 3.12.3 environment, Qdrant 1.7.4 on `127.0.0.1:6337`,
Redis 7.0.15 on `127.0.0.1:6380`, `OPENAI_API_KEY=''`, and
`RERANKING_ENABLED=false`:

```bash
cd cvg-master-rag-v2
PYTHONPATH=src QDRANT_HOST=127.0.0.1 QDRANT_PORT=6337 QDRANT_COLLECTION=rag_phase0 OPENAI_API_KEY='' RERANKING_ENABLED=false ../.runtime/venvs/cvg/bin/python -m pytest -q
```

That reproduction stabilized at **365 passed, 19 failed, 14 skipped, and 6
errors**. The one-test increase over the historical count is a collection
drift in the current checkout, not a claim that the legacy red surface is
fixed. Qdrant and Redis were reachable; the default, Fluxpay, and tenant
evaluation fixtures were not present.

The current checkout also contains the new Phase 0.6 RBAC contract tests. A
pre-repair integrated run collected 410 tests and reported **369 passed, 22
failed, 15 skipped, and 4 errors**. Its two additional corpus-sensitive
failures are listed under “Post-classification delta”; the two historical
Qdrant setup errors passed in that run because smoke points were present. After
the policy/fixture-test repairs recorded below, the final risk-shaped run
collected 411 tests and reported **379 passed, 13 failed, 15 skipped,
and 4 errors**; all remaining red items are corpus/fixture dependent.
After the session-migration, lifecycle-timestamp, and source-permission
regressions were added, a final recheck collected 415 tests and reported
**383 passed, 13 failed, 15 skipped, and 4 errors**. The four additional
passing tests are Phase 0.6 security coverage; the same 13/4 corpus-dependent
red items remain, with no new unexplained failure.

## Fixture and waiver finding

`cvg-master-rag-v2/src/data/default/dataset.json` does not exist in this
checkout. The expected historical Fluxpay files and the `northwind` tenant
dataset are also absent. The files currently under `src/data/` are runtime
document/chunk state and are not an approved replacement for the historical
evaluation corpus. No synthetic corpus was created.

The ten dataset/corpus classifications below therefore remain
`BLOCKED_PENDING_FIXTURE_OR_WAIVER`. A formal waiver has **not** been granted
by a corpus owner in this workspace. To close them, restore the approved
fixtures with provenance and reindex them, or record an owner-authorized
permanent waiver before promotion.

## Individual failure classifications

For every item, “final status” is the status of this Phase 0.6 decision, not a
claim that the legacy assertion passed.

1. **Failure** — `src/tests/test_sprint5.py::TestDatasetValidation::test_dataset_loads_without_error` (`test_sprint5.py:174`).
   - Failure text: `Dataset not found at .../src/data/default/dataset.json`.
   - Root cause: the runtime default evaluation dataset is absent.
   - Classification: `MISSING_REQUIRED_FIXTURE`.
   - Relevance/action: historical dataset validation cannot run without the approved 30-question dataset; restore it with provenance or obtain a formal waiver; do not synthesize data.
   - Evidence: independent reproduction above; `src/data/default/dataset.json` is absent.
   - Final status: `BLOCKED_PENDING_FIXTURE_OR_WAIVER`.

2. **Failure** — `src/tests/test_sprint5.py::TestChunkOffsets::test_chunk_offsets_not_all_zero` (`test_sprint5.py:3729`).
   - Failure text: `No document has non-zero chunk offsets`.
   - Root cause: the expected multi-chunk default corpus is not present/indexed; only unrelated runtime smoke state is available.
   - Classification: `MISSING_REQUIRED_FIXTURE`.
   - Relevance/action: restore the approved multi-document corpus and reindex it, then rerun the assertion.
   - Evidence: independent reproduction; no approved default corpus in `src/data/`.
   - Final status: `BLOCKED_PENDING_FIXTURE_OR_WAIVER`.

3. **Failure** — `src/tests/test_sprint5.py::TestLowConfidence::test_valid_query_not_low_confidence` (`test_sprint5.py:3775`).
   - Failure text: `reembolso prazo` returned `low_confidence=True` with no expected hit.
   - Root cause: expected Fluxpay/default content is absent; the available Qdrant state contains only smoke data.
   - Classification: `MISSING_REQUIRED_FIXTURE`.
   - Relevance/action: restore and provenance-check the approved corpus, reindex, and rerun; preserve the low-confidence safety behavior until then.
   - Evidence: independent reproduction; Qdrant was healthy but the required corpus was unavailable.
   - Final status: `BLOCKED_PENDING_FIXTURE_OR_WAIVER`.

4. **Failure** — `src/tests/test_sprint5.py::TestMultiDocumentSearch::test_qdrant_filter_includes_document_id_and_page_range` (`test_sprint5.py:4003`).
   - Failure text: expected 3 Qdrant `must` clauses, observed 4.
   - Root cause: the current `rag-contract-v1` deliberately adds the mandatory collection ACL condition to the workspace, document, and page constraints.
   - Classification: `INTENTIONAL_POLICY_CHANGE`.
   - Relevance/action: refresh the stale assertion to expect the ACL clause; do not remove collection filtering.
   - Evidence: current filter contains `workspace_id`, collection ACL, document ID, and page range; Phase 0.5 security contract requires scope enforcement.
   - Final status: `RESOLVED_IN_PHASE_0_6_TESTS`.

5. **Failure** — `src/tests/test_sprint5.py::TestMultiDocumentSearch::test_search_populates_document_filename` (`test_sprint5.py:4045`).
   - Failure text: expected retrieval results for `reembolso prazo`, including `politicas_fluxpay.md`, but no expected result was returned.
   - Root cause: the expected Fluxpay document is absent or not indexed.
   - Classification: `MISSING_REQUIRED_FIXTURE`.
   - Relevance/action: restore the approved Fluxpay corpus and provenance, reindex, and rerun filename propagation.
   - Evidence: independent reproduction; the expected file is not in the checkout.
   - Final status: `BLOCKED_PENDING_FIXTURE_OR_WAIVER`.

6. **Failure** — `src/tests/test_sprint5.py::TestMultiDocumentSearch::test_search_prefers_specific_webhook_document_for_backoff_query` (`test_sprint5.py:4062`).
   - Failure text: expected a result from `guia_integracao_webhooks_fluxpay.md`, but no expected result was returned.
   - Root cause: the expected Fluxpay webhook document is absent.
   - Classification: `MISSING_REQUIRED_FIXTURE`.
   - Relevance/action: restore and index the approved webhook document; do not weaken retrieval ranking or ACLs to make the test pass.
   - Evidence: independent reproduction and repository data inventory.
   - Final status: `BLOCKED_PENDING_FIXTURE_OR_WAIVER`.

7. **Failure** — `src/tests/test_sprint5.py::TestHealthEndpoint::test_health_reports_corpus_and_qdrant` (`test_sprint5.py:4793`).
   - Failure text: direct `health_check()` call raised `401 Active session required`.
   - Root cause: health workspace resolution is now protected and requires an authenticated session.
   - Classification: `INTENTIONAL_POLICY_CHANGE`.
   - Relevance/action: update the helper test to provide an active session or explicitly assert the protected contract; do not make the health route enumerate workspace data anonymously.
   - Evidence: `src/api/health_routes.py` calls `resolve_workspace_scope`; targeted reproduction returned 401.
   - Final status: `RESOLVED_IN_PHASE_0_6_TESTS`.

8. **Failure** — `src/tests/test_sprint5.py::TestHealthEndpoint::test_light_health_skips_inventory_counts_and_telemetry` (`test_sprint5.py:4827`).
   - Failure text: direct `health_check(light=True)` call raised `401 Active session required`.
   - Root cause: same protected-health policy as item 7.
   - Classification: `INTENTIONAL_POLICY_CHANGE`.
   - Relevance/action: exercise the light health helper with an authenticated session while retaining the no-inventory lightweight behavior.
   - Evidence: targeted reproduction; `resolve_workspace_scope` rejects the anonymous dependency value.
   - Final status: `RESOLVED_IN_PHASE_0_6_TESTS`.

9. **Failure** — `src/tests/test_sprint5.py::TestEvaluationService::test_question_results_are_returned` (`test_sprint5.py:5061`).
   - Failure text: `FileNotFoundError` for `src/data/default/dataset.json`.
   - Root cause: the default evaluation dataset is missing.
   - Classification: `MISSING_REQUIRED_FIXTURE`.
   - Relevance/action: restore the approved dataset or obtain a formal waiver; evaluation code must not manufacture questions.
   - Evidence: independent reproduction and missing-path check.
   - Final status: `BLOCKED_PENDING_FIXTURE_OR_WAIVER`.

10. **Failure** — `src/tests/test_sprint5.py::TestQueryPipeline::test_query_citations_include_document_filename` (`test_sprint5.py:5834`).
    - Failure text: `resp.citations` was empty.
    - Root cause: the expected Fluxpay retrieval context is absent from the current corpus.
    - Classification: `MISSING_REQUIRED_FIXTURE`.
    - Relevance/action: restore/index the approved corpus and rerun citation provenance; retain the no-answer/no-citation behavior for empty evidence.
    - Evidence: independent reproduction returned the safe insufficient-information answer with no citations.
    - Final status: `BLOCKED_PENDING_FIXTURE_OR_WAIVER`.

11. **Failure** — `src/tests/test_sprint5.py::TestEnterpriseAdminContracts::test_admin_evaluation_run_allows_foreign_workspace_without_switching` (`test_sprint5.py:7367`).
    - Failure text: response was `404 dataset_not_found`.
    - Root cause: authorization reached the dataset lookup, but the foreign workspace dataset is absent.
    - Classification: `MISSING_REQUIRED_FIXTURE`.
    - Relevance/action: restore the approved foreign-workspace fixture and rerun without changing tenant isolation.
    - Evidence: independent reproduction; `northwind`/foreign dataset file is unavailable.
    - Final status: `BLOCKED_PENDING_FIXTURE_OR_WAIVER`.

12. **Failure** — `src/tests/test_sprint5.py::TestEnterpriseTenantIsolation::test_admin_switches_between_three_tenants_without_data_leakage` (`test_sprint5.py:7600`).
    - Failure text: `northwind` dataset returned `404`.
    - Root cause: expected tenant evaluation fixture is absent.
    - Classification: `MISSING_REQUIRED_FIXTURE`.
    - Relevance/action: restore the approved `northwind` dataset/corpus and rerun the three-tenant isolation checks.
    - Evidence: independent reproduction; no authorized northwind fixture in the checkout.
    - Final status: `BLOCKED_PENDING_FIXTURE_OR_WAIVER`.

13. **Failure** — `src/tests/test_sprint5.py::TestSemanticChunking::test_ingestion_keep_all_policy_preserves_previous_operational_uploads` (`test_sprint5.py:8408`).
    - Failure text: `old-upload-doc` appeared in the deleted document IDs although the test expected `[]`.
    - Root cause: the test fixture is dated 2026-04-19; with a 999-hour TTL and the current 2026-08-31 clock, it is expired. Current `keep_all` still applies TTL cleanup.
    - Classification: `STALE_TEST`.
    - Relevance/action: refresh the fixture timestamp relative to the test clock or freeze time, and document that `keep_all` retains prior uploads within TTL but is not immortal.
    - Evidence: independent reproduction and `src/services/ingestion_service.py` TTL path.
    - Final status: `RESOLVED_IN_PHASE_0_6_TESTS`.

14. **Failure** — `src/tests/test_sprint5.py::TestEvaluationDatasetEndpoint::test_evaluation_dataset_returns_real_dataset_for_default_workspace` (`test_sprint5.py:8442`).
    - Failure text: default workspace returned `404 dataset_not_found`.
    - Root cause: `src/data/default/dataset.json` is absent.
    - Classification: `MISSING_REQUIRED_FIXTURE`.
    - Relevance/action: restore the approved operational dataset or obtain a formal waiver; do not return fabricated questions.
    - Evidence: independent reproduction and direct path inventory.
    - Final status: `BLOCKED_PENDING_FIXTURE_OR_WAIVER`.

15. **Failure** — `src/tests/test_sprint5.py::TestReindexTelemetry::test_get_chunking_metrics_aggregates_by_strategy` (`test_sprint5.py:9436`).
    - Failure text: expected 3 operations, observed 0.
    - Root cause: test-only events dated 2026-04-18 are outside the current rolling 30-day window.
    - Classification: `STALE_TEST`.
    - Relevance/action: generate timestamps relative to the current clock or inject a frozen clock; retain the rolling-window production behavior.
    - Evidence: independent reproduction; `get_chunking_metrics` applies `datetime.now() - days`.
    - Final status: `RESOLVED_IN_PHASE_0_6_TESTS`.

16. **Failure** — `src/tests/test_sprint5.py::TestReindexTelemetry::test_get_chunking_metrics_tracks_degraded_count` (`test_sprint5.py:9495`).
    - Failure text: expected 2 degraded events, observed 0.
    - Root cause: same stale April test-only timestamps are filtered before degraded counting.
    - Classification: `STALE_TEST`.
    - Relevance/action: refresh or freeze fixture timestamps, then rerun the aggregation assertion.
    - Evidence: independent reproduction and the telemetry rolling cutoff.
    - Final status: `RESOLVED_IN_PHASE_0_6_TESTS`.

17. **Failure** — `src/tests/test_sprint5.py::TestReindexTelemetry::test_get_chunking_metrics_backward_compat_missing_fields` (`test_sprint5.py:9553`).
    - Failure text: expected 1 operation, observed 0.
    - Root cause: the April fixture is filtered out before backward-compatible missing-field handling executes.
    - Classification: `STALE_TEST`.
    - Relevance/action: use a current relative timestamp or frozen clock so the compatibility logic is actually exercised.
    - Evidence: independent reproduction; same rolling-window implementation.
    - Final status: `RESOLVED_IN_PHASE_0_6_TESTS`.

18. **Failure** — `src/tests/test_sprint5.py::TestReindexTelemetry::test_same_document_multiple_events_deduplicated` (`test_sprint5.py:9675`).
    - Failure text: expected 4 operations, observed 0.
    - Root cause: same stale April test-only timestamps are outside the configured window.
    - Classification: `STALE_TEST`.
    - Relevance/action: refresh or freeze timestamps and rerun deduplication coverage.
    - Evidence: independent reproduction; rolling cutoff excludes all fixture events.
    - Final status: `RESOLVED_IN_PHASE_0_6_TESTS`.

19. **Failure** — `tests/test_phase0.py::test_query_request` (`tests/test_phase0.py:81`).
    - Failure text: expected threshold `0.70`, observed `0.25`.
    - Root cause: the canonical Phase 0.5 schema/configuration deliberately defines `DEFAULT_THRESHOLD=0.25`.
    - Classification: `INTENTIONAL_POLICY_CHANGE`.
    - Relevance/action: update the obsolete Phase 0 assertion to the canonical threshold; do not regress the current retrieval contract to satisfy the historical number.
    - Evidence: `src/core/config.py`, `SearchRequest`, and `QueryRequest` all use 0.25.
    - Final status: `RESOLVED_IN_PHASE_0_6_TESTS`.

## Individual setup errors

20. **Error** — `src/tests/test_sprint5.py::TestDatasetValidation::test_dataset_spans_multiple_canonical_documents` (`test_sprint5.py:180`).
    - Failure text: fixture setup raised `FileNotFoundError` for `src/data/default/dataset.json`.
    - Root cause: required default dataset is absent.
    - Classification: `MISSING_REQUIRED_FIXTURE`.
    - Relevance/action: restore the approved dataset or obtain a formal waiver; no synthetic replacement.
    - Evidence: shared `dataset_raw` fixture at `test_sprint5.py:107`; independent reproduction.
    - Final status: `BLOCKED_PENDING_FIXTURE_OR_WAIVER`.

21. **Error** — `src/tests/test_sprint5.py::TestEmbeddingBatching::test_dataset_categories_are_valid` (`test_sprint5.py:3594`).
    - Failure text: fixture setup raised `FileNotFoundError` for `src/data/default/dataset.json`.
    - Root cause: same absent default dataset.
    - Classification: `MISSING_REQUIRED_FIXTURE`.
    - Relevance/action: restore/provenance-check the approved dataset, then rerun category validation.
    - Evidence: shared `dataset_raw` fixture; independent reproduction.
    - Final status: `BLOCKED_PENDING_FIXTURE_OR_WAIVER`.

22. **Error** — `src/tests/test_sprint5.py::TestEmbeddingBatching::test_dataset_no_legacy_fields` (`test_sprint5.py:3601`).
    - Failure text: fixture setup raised `FileNotFoundError` for `src/data/default/dataset.json`.
    - Root cause: same absent default dataset.
    - Classification: `MISSING_REQUIRED_FIXTURE`.
    - Relevance/action: restore/provenance-check the approved dataset, then rerun schema compatibility validation.
    - Evidence: shared `dataset_raw` fixture; independent reproduction.
    - Final status: `BLOCKED_PENDING_FIXTURE_OR_WAIVER`.

23. **Error** — `src/tests/test_sprint5.py::TestEmbeddingBatching::test_all_questions_have_required_fields` (`test_sprint5.py:3607`).
    - Failure text: fixture setup raised `FileNotFoundError` for `src/data/default/dataset.json`.
    - Root cause: same absent default dataset.
    - Classification: `MISSING_REQUIRED_FIXTURE`.
    - Relevance/action: restore/provenance-check the approved dataset, then rerun required-field validation.
    - Evidence: shared `dataset_raw` fixture; independent reproduction.
    - Final status: `BLOCKED_PENDING_FIXTURE_OR_WAIVER`.

24. **Error** — `src/tests/test_sprint5.py::TestQdrantCorpusConsistency::test_qdrant_point_count_matches_disk` (`test_sprint5.py:3646`).
    - Failure text: fixture setup raised `FileNotFoundError` for `src/data/default/dataset.json`.
    - Root cause: corpus-consistency setup cannot determine the approved expected corpus without the dataset fixture; this is not a Qdrant availability failure.
    - Classification: `MISSING_REQUIRED_FIXTURE`.
    - Relevance/action: restore the approved corpus/dataset, reindex, and compare disk/Qdrant counts.
    - Evidence: shared `dataset_raw` fixture; Qdrant health probe was successful.
    - Final status: `BLOCKED_PENDING_FIXTURE_OR_WAIVER`.

25. **Error** — `src/tests/test_sprint5.py::TestQdrantCorpusConsistency::test_each_document_indexed_in_qdrant` (`test_sprint5.py:3674`).
    - Failure text: fixture setup raised `FileNotFoundError` for `src/data/default/dataset.json`.
    - Root cause: same missing expected corpus metadata, not an unavailable Qdrant service.
    - Classification: `MISSING_REQUIRED_FIXTURE`.
    - Relevance/action: restore/provenance-check the corpus, reindex it, and rerun document coverage.
    - Evidence: shared `dataset_raw` fixture; Qdrant answered readiness/smoke queries.
    - Final status: `BLOCKED_PENDING_FIXTURE_OR_WAIVER`.

## Post-classification delta

The post-RBAC integrated run collected additional Phase 0.6 tests and showed
three corpus-sensitive failures not present in the frozen independent 19-item
run:

- `src/tests/test_sprint5.py::TestMultiDocumentSearch::test_search_returns_chunks_from_multiple_documents` — no document IDs were returned. Classification `MISSING_REQUIRED_FIXTURE`; same absent default/Fluxpay corpus; status `BLOCKED_PENDING_FIXTURE_OR_WAIVER`.
- `src/tests/test_sprint5.py::TestQueryPipeline::test_query_returns_answer_with_citations` — no citations were returned. Classification `MISSING_REQUIRED_FIXTURE`; the available smoke state does not provide the expected grounded corpus; status `BLOCKED_PENDING_FIXTURE_OR_WAIVER`.
- `src/tests/test_sprint5.py::TestEvaluationDatasetEndpoint::test_candidate_count_uses_total_candidates` — the available corpus produced `total_candidates=0`. Classification `MISSING_REQUIRED_FIXTURE`; the expected indexed evaluation corpus is absent; status `BLOCKED_PENDING_FIXTURE_OR_WAIVER`.

The current integrated run's four remaining setup errors are the first four
dataset errors above; the two corpus-consistency setup errors passed because
the local Qdrant smoke state happened to satisfy those checks. This is
environment/state variation, not a waiver or a fabricated pass.

The repaired policy/clock assertions were independently rerun with the pinned
CVG environment. The focused `pytest -q` selection for the ACL filter,
authenticated full/light health, `keep_all`, and the four telemetry
aggregations resulted in **8 passed, 315 deselected**, exit 0. The two Phase 0
threshold assertions resulted in **2 passed**, exit 0. The remaining 13
failures and 4 errors in the final full run are the explicitly classified
corpus/fixture surface above.

## Classification summary

| Frozen surface | Count | Classification/result |
| --- | ---: | --- |
| Failures | 19 | 10 `MISSING_REQUIRED_FIXTURE`, 5 `STALE_TEST`, 4 `INTENTIONAL_POLICY_CHANGE` |
| Errors | 6 | 6 `MISSING_REQUIRED_FIXTURE` |
| Confirmed real regressions | 0 | None confirmed by independent reproduction |
| Unknown | 0 | None confirmed |

The legacy lane is therefore fully explained but not green. Its fixture
blockers remain open until an authorized historical corpus is restored or a
formal owner waiver is recorded. No xfail, skip, test deletion, synthetic
corpus, or policy weakening was used.
