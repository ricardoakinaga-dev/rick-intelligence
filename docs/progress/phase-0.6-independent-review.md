# Phase 0.6 — Independent Review

## Review provenance

This is the final fresh review by the read-only reviewer **Descartes**. The
reviewer was spawned without the lead conversation context after the latest
implementation changes and regression reruns, was instructed to read the
Phase 0.6 requirements directly, and did not edit files, create fixtures,
commit, or push. The review was completed on 2026-08-31 against the current
workspace.

The reviewer independently observed the Git refs as HEAD and origin/main both
at 7925beb972cd7d3a85c883506254bad98a43cbee and the intentionally dirty Phase
0.6 worktree. Its no-cache CVG observation was 381 passed, 10 failed, 14
skipped, and 6 errors across 411 collected tests. The lead recheck after the
latest security additions was 383 passed, 13 failed, 15 skipped, and 4 errors
across 415 collected tests. The difference is local Qdrant smoke-state
variation; the red nodes remain the documented corpus/fixture surface. Both
observations are retained rather than collapsed into a falsely stable number.

## 1. RBAC overrides and wildcard behavior

**PASS for canonical authoritative paths.** Authorization normalizes add and
remove sets, applies removals last, materializes a wildcard against the
canonical permission registry when individual permissions are removed, and
handles remove wildcard as deny-all unless an explicit addition opts a
permission back in. Session and route checks call permission_granted with
authoritative=True, so an explicit reduced or empty snapshot cannot fall back
to the current role. Evidence is in
cvg-master-rag-v2/src/services/authorization.py,
cvg-master-rag-v2/src/services/api_security.py, and
cvg-master-rag-v2/src/tests/test_phase06_rbac.py. The focused security
selection passed 26 tests.

The non-authoritative direct helper retains a compatibility fallback for old
callers. No authenticated route uses that mode; it remains a documented
compatibility seam rather than a candidate promotion claim.

## 2. Session snapshots and invalidation

**PASS after targeted remediation, with migration semantics explicit.** New
sessions persist role, canonical role, effective permissions, and collection
grants. Records from before the snapshot fields existed are migrated once on
their first successful access; the generated fields are persisted before the
response is built, so later override or collection edits do not silently
change that session. Present empty lists remain authoritative.

Password, status, role, expiry, and revocation checks remain active.
Malformed lifecycle timestamps now fail closed by expiring the session rather
than being ignored. Evidence is in
cvg-master-rag-v2/src/services/enterprise_service.py and the migration and
malformed-timestamp tests in test_phase06_rbac.py. The unavoidable limitation
is that a legacy record first accessed after an earlier unrecorded change can
only be snapshotted from the state visible at migration time; it cannot
reconstruct history that was never persisted.

## 3. Frozen legacy failures and errors

**BLOCKED, fully classified.** The required artifact enumerates all 19 frozen
failures and all 6 frozen errors with test ID, file, failure text, root cause,
allowed classification, action, evidence, and final status. It uses no xfail,
skip masking, deletion, synthetic corpus, or weakened assertion.

The approved default, Fluxpay, and tenant evaluation corpus is absent. The
frozen classification is 10 missing fixtures, 5 stale tests, and 4 intentional
policy changes among failures, plus 6 missing-fixture errors. No confirmed
real regression or unknown item was found. The current final lead run is
383 passed, 13 failed, 15 skipped, and 4 errors; all current red items are
corpus/fixture dependent. No owner-authorized permanent waiver exists, so
PH06-LEGACY remains a P0 promotion blocker.

Evidence: docs/baselines/phase-0.6-legacy-test-classification.md and the
current full-suite verification record.

## 4. Real provider boundary

**PASS_LOCAL_PROTOCOL_ONLY.** The Professor contract starts a disposable
HTTP server on 127.0.0.1 and the provider performs actual HTTP requests to
the OpenAI-compatible embeddings and chat-completions endpoints. It is not a
function mock. The contract covers success, timeout, unavailable, 429, 500,
malformed response, missing field, invalid JSON, empty model, embedding
dimension mismatch, model not found, and the full document-to-citation flow.

The regenerated raw artifact has 12 observed cases and 26 HTTP observations.
scripts/phase06/check_provider_artifact.py now fails closed if the artifact is
empty or missing a required case. The root baseline is classified
REAL_PROTOCOL_LOCAL_SERVER. No live external provider was called, so this
does not claim provider quality, quota, or production availability.

## 5. Provider failure safety, retry, correlation, and locks

**PASS for the local contract; medium operational residual remains.** Errors
are typed and serialized without raw bodies, URLs, credentials, causes, or
stacks. Timeout, unavailable, 429, and 500 retry at most three times with
bounded backoff and stable correlation IDs. Schema, model, dimension, and
model-not-found failures are non-retryable where appropriate.

Professor returns a generic user error, preserves state, releases the
owner-bound lock in finally, and now returns a safe error when acquisition
itself throws. Omitting an injectable release dependency no longer silently
no-ops; it uses the real default owner-bound release attempt. Renewal failures
remain logged and bounded by the lock TTL, which is a medium operational
residual requiring production observability.

Evidence: rick-professor/src/lib/openai.ts,
rick-professor/src/core/processor.ts,
rick-professor/src/lib/openai.contract.test.ts, the raw artifact, and the
37-test Professor run.

## 6. Control-plane consistency

**PASS structurally; final promotion remains BLOCKED.** The final gate,
independent-review artifact, report, provider and legacy baselines, active
plan, backlog, and append-only ledgers are present and mutually referenced.
The observed branch is main, HEAD equals origin/main at the published Phase
0.5 SHA, and the worktree is explicitly DIRTY_PHASE_0_6 because Phase 0.6
changes have not been published.

The executable control-plane checks validate state, backlog, ledgers, required
artifacts, current Git observations, and the allowed final classification.
They do not convert a dirty local worktree or absent remote Phase 0.6 commit
into publication evidence.

## 7. CI enforceability

**IMPLEMENTED_NOT_RUN_GITHUB.** The workflow defines 13 jobs covering secret
scanning, control plane, Locker boundary, CVG contract/security/RBAC,
Professor tests/build/artifact validation, Locker tests, frontend lint/build,
Node and pinned Python audits, Qdrant/Redis contracts, Locker/Redis
black-box behavior, browser smoke, historical regression, and explicit
live-provider NOT RUN status.

The historical lane runs the full suite without continue-on-error when the
classification artifact is present; it therefore remains visibly red until
the approved corpus or an authorized waiver is supplied. GitHub Actions and
branch protection were not run or configured from this workspace. The
workflow and final artifacts are local changes, not yet present in the
published commit.

## 8. Redis Locker deployment boundary

**PASS_STATIC_LOCAL, production verification unavailable.** The preserved
Compose example places Redis and Locker on a private internal network,
publishes no Locker host port, declares no ingress or reverse-proxy route,
and uses redis-locker:3000 for the private service URL. Boundary lint,
syntax, unit, and prior loopback black-box lock tests pass.

The boundary document explicitly treats lock_value as owner-safe lock data,
not HTTP authentication. Production network policy, gateway configuration,
and out-of-band deployment changes remain unknown and are not represented as
verified.

## 9. Veterinarian document browsing

**PASS for canonical routes.** VETERINARIAN has chat.query, history.read,
sources.read, and collections.read, but not library.browse or documents.read.
Document list/detail/job/collection routes require documents.read. The
frontend hides catalog, upload, dashboard, and audit surfaces from the VET
legacy labels while retaining Chat and own browser history.

Evidence: the canonical permission registry, API route checks,
frontend/lib/navigation.ts, the UI matrix, and the focused negative tests.

## 10. Veterinarian source and ACL escape

**PASS for the exposed query/search path.** /search and /query require both
chat.query and sources.read before a retrieval context is built. The context
binds the authenticated workspace and authorized collection IDs; filtering
happens before pagination and source/citation output cannot widen that scope.
Source-only identities cannot read arbitrary documents, and a query-only
identity without sources.read is denied by the focused regression.

Direct legacy service seams and production gateway routes remain outside the
local test boundary. They are documented residual integration scope, not
evidence of a known canonical-route escape.

## 11. P0 and HIGH findings

The final review found one active P0 promotion blocker: the absent approved
historical corpus and missing owner-authorized waiver. The full red suite is
understood and visible but cannot be promoted as green.

No unresolved canonical RBAC, session-migration, source-ACL, provider
serialization, or Locker-example exploit was found after remediation. HIGH
operational evidence gaps remain for production network fidelity, live
provider quality, GitHub branch protection, and the pinned Python dependency
audit; they are explicitly recorded as unavailable rather than passed.

## 12. Final decision

The independent recommendation is **BLOCKED — NOT PROMOTED**. A
VERIFIED_CANDIDATE decision is not justified while the historical corpus or
owner waiver is absent and external production evidence remains unavailable.
Phase 1 was not started and no Phase 1 plan was created.
