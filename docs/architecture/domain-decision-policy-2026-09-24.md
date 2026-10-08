# Q24-13/14/15 — Request policy and final evidence publication

Scope: reversible technical implementation with D04 accepted as broad clinical
intake plus mandatory human review. Clinical-domain entry is now explicit, but
this document is not a clinical safety approval, release approval, or
replacement for the Lead-owned execution ledgers.

## Frozen local acceptance

| ID | Required behavior | Discriminating proof |
| --- | --- | --- |
| Q24-13a | Server-owned classification independent of retrieval quality or supplied labels | Allowed/unknown/clinical/mixed/injection/missing-policy tests |
| Q24-13b | Version and reason survive API serialization | Compare response, SSE, replay and stored metadata |
| Q24-14a | All five actions reachable; only ANSWER with evidence calls the provider | Decision/API matrix with a counted deterministic provider |
| Q24-14b | At most one retrieval retry with an actually different search query | Record both queries and the exhausted outcome |
| Q24-15a | Re-read document/chunk/version/checksum/collection before final publication | Mutate or revoke sources while the provider is suspended |
| Q24-15b | Provisional deltas never imply approval; cancellation/truncation never completes | JSON, streaming, fallback, cancellation and budget tests |

The baseline is 101 passing decision/evidence/professor/gate tests. The existing
adapter always supplied UNKNOWN risk and intent; its retry repeated the same
query. Final generation validated citation markers against a retrieval snapshot.

## Policy versions

`rick-nonclinical-request-v1` remains available as the narrow technical baseline.
The canonical API now uses `rick-clinical-domain-v1` (`ClinicalDomainPolicy`):
it accepts broad clinical requests into the classified workflow, marks them
`HIGH` and `human_review_required=true`, and therefore forces `ESCALATE` before
provider generation. This is broad intake, not autonomous clinical advice.

The base policy uses finite whole-question matches in English and Portuguese for
document upload, citation help, document collections and retry/status help. The
complete executable sentence list is in
`packages/decision/src/rick_decision/request_policy.py`. Case, whitespace, a final
question mark and accents are normalized; suffix clauses, arbitrary embedded text
and hidden controls do not inherit permission. These are product-information rules,
not a medical triage model. In the canonical clinical policy, clinical markers
enter the review-required path; instruction override attempts remain denied
before allow rules. Unknown requests remain UNKNOWN; short non-clinical topic
requests ask for clarification; known creative requests abstain as unsupported.

Context-dependent requests are conservatively unreviewed in v1. Classification
uses the original question and prior messages, never a rewritten retrieval query,
retrieval metadata, evidence quality, or a caller-supplied risk/intent. Omitted or
failing classifier configuration produces UNKNOWN with a safe recorded reason.
Changing policy behavior requires a new version and reviewable examples.

## Integration and publication

The gate classifies once, issues canonical evidence and applies the existing
DecisionLayer. Retry uses policy-owned topic terms, shares the request's existing
time budget and permits no more than one additional search. The evidence bundle
remains single-collection: choose the first valid authorized source's collection;
never merge unrelated collections into a fictitious single scope.

The canonical Professor composition requires a final publication callback. It
re-resolves every source given to the provider, compares identity, version,
checksum, source, location and text, checks active collection and published
document status, and validates citation membership. No per-request evidence is
stored on the shared gate. An optional server-owned authorization refresher can
re-read current user grants; it may only narrow the original scope and fails
closed on errors. Composition owners must wire that refresher for live grant
revocation guarantees. Collection lifecycle revocation is checked directly by the
gate, independently of that hook.

JSON, SSE and fallback completion share the same final validation. The existing
wire contracts and metadata containers remain intact. Source validation is a
structural/provenance result; semantic support and clinical approval are never
fabricated from citation existence. Deltas are provisional. Missing stop signals,
length truncation, invalid citations, exhausted budgets and cancellation cannot
produce an approved final answer.

## Limits and handoff

Tests use synthetic stores and deterministic providers; no live provider calls,
production changes, domain acceptance, distributed transaction proof, independent
review or AAA claim is authorized by this builder result. Revalidation immediately
precedes the backend final response; atomic authorization through chat persistence
and after-publication historical revocation belong to the Lead's shared chat/store
integration. Historical metadata is preserved, not silently relabeled.

Recovery must preserve all pre-existing patches. Baseline snapshots, commands,
exit codes and logs are kept in a unique `/tmp/rick-q24-decision-*` directory;
revert only this lane's reviewed diff, never reset or clean the shared tree.
