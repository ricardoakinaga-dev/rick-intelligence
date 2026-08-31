# Phase 0.6 — Promotion Closure

## Executive Summary

Phase 0.6 closed the concrete RBAC, session-snapshot, veterinarian access,
provider-boundary, Locker-boundary, CI, dependency, and test-fixture
classification work that can be completed from this checkout. The final
decision is **BLOCKED — NOT PROMOTED**. The approved default/Fluxpay/tenant
evaluation corpus is absent, no corpus-owner waiver is recorded, and the
current full CVG run therefore remains red on explicitly classified fixture
cases. Phase 1 was not started and no Phase 1 plan was created.

The provider contract passed through a real loopback OpenAI-compatible HTTP
server (`REAL_PROTOCOL_LOCAL_SERVER`), including all required failure cases,
safe error handling, bounded retry, correlation IDs, grounded citations, and
lock cleanup. This is valid local protocol evidence, not live-provider quality
evidence. Node dependency audits are clean after compatible lockfile updates;
the local environment could not run `pip-audit` because it has no pip/venv
bootstrap, so the pinned Python audit remains enforced in CI.

## Starting State

- Published root Phase 0.5 commit: `7925beb972cd7d3a85c883506254bad98a43cbee`.
- Branch: `main`; at recovery `HEAD == origin/main` and the worktree was clean.
- Phase 0.5 gate: `BLOCKED` / `NOT PROMOTED`.
- Frozen historical CVG baseline: `364 passed, 19 failed, 14 skipped, 6 errors`.
- Live provider, approved evaluation corpus, and production deployment
  evidence were unavailable.
- `cvg-master-rag-v2/`, `rick-professor/`, and `modulo-redis-locker/` remain
  independent component boundaries with their preserved child histories.

## Scope

Only the explicit Phase 0.6 promotion blockers were addressed: RBAC override
semantics and immutable session snapshots; complete legacy-test classification;
real provider protocol evidence; control-plane reconciliation; enforceable CI;
private Locker deployment; veterinarian policy; password-hashing decision;
fresh regression evidence; and an independent review. No RAG redesign,
monorepo move, Phase 1 implementation, test masking, or synthetic historical
corpus was introduced.

## RBAC Override Fix

`add` and `remove` overrides are normalized to canonical permission IDs, with
removal winning conflicts. A wildcard role remains `*` when unrestricted; when
it has explicit removals, it is materialized against the registered permission
set so removed permissions cannot be restored by wildcard or role fallback.
Enforcement passes `authoritative=True` for session snapshots, including an
explicit empty list.

Sessions persist role, canonical role, effective permissions, and authorized
collection snapshots. Refresh and tenant switching preserve those snapshots;
legacy records missing snapshot fields are migrated once on first successful
access, then remain stable. Password, status, role, expiry, and explicit
revocation lifecycle checks remain active, and malformed lifecycle timestamps
fail closed by expiring the session. `permission_overrides` is available
through the admin create/update schemas. The recommended veterinarian role has `chat.query`, `history.read`,
`sources.read`, and `collections.read`; it has neither `library.browse` nor
unrestricted `documents.read`.

Evidence: `cvg-master-rag-v2/src/services/authorization.py`,
`cvg-master-rag-v2/src/services/admin_service.py`,
`cvg-master-rag-v2/src/services/enterprise_service.py`,
`cvg-master-rag-v2/src/services/api_security.py`,
`cvg-master-rag-v2/src/models/schemas.py`, and
`cvg-master-rag-v2/src/tests/test_phase06_rbac.py`.

Validation: focused RBAC plus Phase 0.5 security tests — **26 passed**,
including legacy-session migration, malformed-lifecycle denial, source ACL
enforcement, and the deny-all wildcard-removal regression.

## Legacy Test Classification

The frozen 19 failures and 6 errors are individually classified in
[`phase-0.6-legacy-test-classification.md`](../baselines/phase-0.6-legacy-test-classification.md).
The independent reproduction stabilized at `365 passed, 19 failed, 14
skipped, 6 errors`. The 19 failures are 10
`MISSING_REQUIRED_FIXTURE`, 5 `STALE_TEST`, and 4
`INTENTIONAL_POLICY_CHANGE`; all 6 errors are
`MISSING_REQUIRED_FIXTURE`. No `REAL_REGRESSION` or `UNKNOWN` was confirmed.

The stale clock assertions, current ACL filter assertion, authenticated health
helper calls, and current threshold assertion were repaired and rerun. The
final risk-shaped integrated run collected 415 tests: **383 passed, 13 failed,
15 skipped, 4 errors**. All 13 failures and 4 errors are corpus/fixture
dependent: the approved default dataset, Fluxpay documents, and tenant
evaluation data are absent. The report records the three additional current
corpus-sensitive nodes and the two setup errors that pass or fail depending on
local Qdrant smoke state; no result was hidden.

No xfail, test skip, deletion, fabricated dataset, or weakened ACL was used.
The historical CI lane runs the full suite when the classification artifact is
present and fails visibly until the approved corpus or an owner-authorized
permanent waiver is supplied.

## Provider Contract Verification

The Professor harness uses a disposable HTTP server bound to `127.0.0.1`, not
an injected provider function mock. The provider makes actual HTTP requests to
`/v1/embeddings` and `/v1/chat/completions`, sends the configured bearer and a
correlation header, validates response schemas and embedding dimension, and
serializes only safe error summaries.

The contract covers success, timeout, unavailable, 429, 500, malformed
response, missing field, invalid JSON, empty model, embedding dimension
mismatch, and model not found. Retryable cases stop at three attempts with
backoff. The vertical case exercises document → embedding → index → query →
retrieval → LLM answer → citation, rejects fabricated citations, and verifies
lock release and state integrity on success and provider failure.

Evidence: [`phase-0.6-provider-contract.json`](../baselines/phase-0.6-provider-contract.json),
the raw Professor artifact at
`rick-professor/test/artifacts/phase-0.6-provider-contract.json`, and
`rick-professor/src/lib/openai.contract.test.ts`. The raw artifact was
regenerated by the complete Professor test command and currently contains 12
observed cases and 26 HTTP requests; it is not a zero-case placeholder.

Validation: Professor `npm test -- --test-force-exit` — **37 tests passed**;
focused provider cases — **12 observed**; `npm run build` — exit 0.

## Control-Plane Reconciliation

At the final control observation, `HEAD` was
`7925beb972cd7d3a85c883506254bad98a43cbee`, branch `main`,
`origin/main` was the same SHA, and the worktree was intentionally
`DIRTY_PHASE_0_6`. The published Phase 0.5 SHA is recorded in
`.agent/state.json`; the active plan is
`.agent/plans/phase-0.6-promotion-closure.md`; `PH06-RECON` is complete; and
the append-only execution/verification ledgers retain the reconciliation
events. The root structural checker passes and does not rewrite history.

Evidence: `scripts/phase06/check_control_plane.py`,
`docs/ci/check_control_plane.py`, `.agent/state.json`,
`.agent/backlog.json`, `.agent/execution-log.jsonl`, and
`.agent/verification.jsonl`.

Validation: `python3 scripts/phase06/check_control_plane.py` and
`python3 docs/ci/check_control_plane.py` — exit 0, with the expected dirty
worktree warning for local Phase 0.6 changes.

## CI Implementation

`.github/workflows/phase-0.6.yml` defines pinned fast and integration lanes
for secret scanning, control-plane integrity, Locker boundary, CVG
contract/security/RBAC, Professor tests/build and provider-artifact validation,
Locker tests, frontend lint/build, dependency audits, disposable Qdrant/Redis contracts,
Locker–Redis black-box behavior, and browser smoke. The historical lane
has real Qdrant/Redis services and runs without masking when the classification
artifact is present; a genuinely unavailable artifact produces an explicit
waiver summary. The live-provider lane reports `NOT RUN` without credentials.

Pinned contract: Ubuntu 24.04, Python 3.12.3, Node 22.19.0, Qdrant 1.7.4,
Redis 7.0.15, `npm ci --ignore-scripts --no-audit --no-fund`, and the pinned
Python requirements install. Exact required status names and the inability to
configure GitHub branch protection from this workspace are documented in
`docs/ci/README.md`.

Validation: workflow YAML parses with 13 jobs; secret scan passes; the local
control and Locker checks pass. GitHub Actions/Docker execution is not
available in the local environment.

## Redis Locker Deployment Boundary

Locker is internal-only. The preserved deployment examples use an internal
private network and `expose`, publish no Locker host port, declare no ingress or
reverse-proxy route, and use the private `redis-locker:3000` service name.
The boundary document explicitly states that the current `lock_value` is
owner-safe Redis data, not HTTP authentication, and defines the network threat
model, trust boundary, exposure policy, application-auth expectation, and
future extraction controls.

Evidence: `docs/architecture/security/locker-boundary.md`,
`scripts/phase06/check_locker_boundary.py`,
`modulo-redis-locker/README.md`, and
`rick-professor/deploy/docker-compose.example.yml`.

Validation: boundary lint — exit 0; Locker unit tests — **2 passed**; prior
black-box local Redis/Locker evidence covers owner safety, renewal, expiry,
malformed requests, and contention.

## Veterinarian Access Policy

The policy distinguishes `sources.read` from `library.browse` and
`documents.read`. `sources.read` exposes only source metadata/citations selected
by an authorized answer/retrieval context. It does not list the library, open
arbitrary documents, download files, or bypass collection ACLs. VET receives
query, own browser-side chat history, source output, and authorized collection
scope. KM retains library browse, document read/manage/upload, ingestion, and
collection management.

The frontend navigation hides catalog, search-inspection, dashboard, and audit
surfaces from the VET legacy labels while keeping Chat available. `/search`
and `/query` now require both `chat.query` and `sources.read` before building a
retrieval context; API negatives cover cross-collection access, document
listing, source-only document reads, missing source permission, and foreign
collection filtering.

Evidence: `docs/architecture/security/permission-model.md`,
`docs/architecture/security/ui-access-matrix.md`,
`docs/architecture/security/collection-acl.md`,
`cvg-master-rag-v2/frontend/lib/navigation.ts`, and
`cvg-master-rag-v2/src/tests/test_phase06_rbac.py`.

## Password Hashing Decision

Argon2id is formally **deferred to Phase 1**. Current PBKDF2-HMAC-SHA256 uses
per-user random salt and 100,000 iterations, handles legacy verification, and
has no demonstrated unsafe behavior in the Phase 0.6 scope. The deferment is
not treated as silently closed: the migration task, triggers, acceptance
criteria, rollback, dependency audit, and removal condition are recorded in
[`password-hashing-decision.md`](../architecture/security/password-hashing-decision.md).

## Regression Results

- CVG focused RBAC/security: **26 passed**.
- CVG policy/clock repair subset: **8 passed**; Phase 0 threshold assertions:
  **2 passed**.
- CVG full risk-shaped run: **383 passed, 13 failed, 15 skipped, 4 errors**;
  all red items are individually classified corpus/fixture cases.
- Professor: **37 passed**, build passed.
- Redis Locker: **2 passed** plus prior real Redis black-box evidence.
- Frontend: lint and production build passed (Next.js 15.5.24).
- Secret scan passed.
- Node dependency audits: Professor, Locker, and frontend all report 0
  vulnerabilities at the high threshold.
- Python dependency audit: CI is configured with `pip-audit==2.9.0`; local
  execution was unavailable because this environment has no pip/venv bootstrap.
- Control and Locker deployment checks passed.

## Security Results

No raw provider response, stack, credential, bearer token, or owner value is
included in provider/API error serialization or audit metadata. Permission and
collection checks are server-side and snapshot-aware. The secret scanner
passed. Node dependency vulnerabilities reported by the initial audit were
removed through compatible package/lockfile updates: Axios/Fastify, Express,
and transitive packages. Production gateway/network policy and live deployment
remain unverified.

## Provider Failure Results

| Case | Classification | Result |
| --- | --- | --- |
| timeout | timeout | 3 attempts; safe error |
| unavailable | unavailable | 3 attempts; safe error |
| 429 | rate_limit | 3 attempts; status retained safely |
| 500 | server_error | 3 attempts; status retained safely |
| malformed/missing/invalid JSON | schema-safe non-retryable errors | 1 attempt each |
| empty model | invalid_model | 0 HTTP calls |
| embedding dimension mismatch | embedding_dimension_mismatch | 1 attempt |
| model not found | model_not_found | safe 404 classification, 1 attempt |

All cases preserve correlation IDs, avoid secret/stack leakage, and the
vertical failure path releases the lock exactly once.

## Independent Review

The fresh read-only review by Descartes was completed after the latest
implementation and regression evidence, with all twelve questions answered.
Its response is recorded in
[`phase-0.6-independent-review.md`](phase-0.6-independent-review.md). The
review found no unresolved canonical RBAC or source-ACL escape, but confirmed
the missing-corpus P0 and external-evidence blockers. Its material findings
were either fixed and retested or preserved as explicit residual risks.

## Remaining Risks

- The approved default, Fluxpay, and tenant evaluation corpus is unavailable;
  this blocks a green historical suite and promotion.
- No corpus-owner permanent waiver is recorded.
- No live external provider or production deployment/network verification was
  authorized or run; local protocol evidence must not be presented as live
  quality evidence.
- GitHub branch protection and required status checks cannot be configured from
  this workspace; exact names are documented.
- Docker-backed CI integration and browser smoke were not executable locally.
- Python dependency audit is configured but not locally observed.
- Lock renewal failure remains a medium operational residual; the release
  fallback now always attempts the real owner-bound default release.
- PBKDF2 remains until the formally deferred Argon2id migration.

## Deferred Items

- Restore/provenance-check and reindex the approved historical corpus, or obtain
  an owner-authorized permanent waiver, then rerun all 19/6 classifications.
- Complete Argon2id migration before Phase 1 production readiness.
- Verify live provider quality/availability using approved credentials and a
  secret-safe harness.
- Verify production gateway, private network, ingress, Redis, and Locker
  deployment policy.
- Configure GitHub branch protection using the documented fast/integration
  check names.
- Create the Phase 1 consolidation plan only after a future final gate is
  exactly `VERIFIED_CANDIDATE`.

## Promotion Decision

**Final classification: `BLOCKED` — `NOT PROMOTED`.**

The gate is not `VERIFIED_CANDIDATE` because the current full suite still has
13 corpus-dependent failures and 4 fixture-setup errors, and the missing
corpus has no owner-authorized permanent waiver. The independent review also
confirmed that live provider, GitHub enforcement, Python audit, and production
network evidence remain unavailable. The red surface is understood and
individually recorded; it is not hidden. No Phase 1 plan or implementation was
created.

| Area | Phase 0.5 State | Phase 0.6 State | Evidence | Residual Risk |
| --- | --- | --- | --- | --- |
| RBAC | Implemented but override/snapshot semantics incomplete | Effective overrides, wildcard removal, legacy migration, immutable snapshots and negatives pass | `test_phase06_rbac.py` plus Phase 0.5 security tests (26 passed) | New permission IDs and legacy records need ongoing review |
| Legacy CVG suite | 364/19/14/6 unexplained red | 19/6 individually classified; current 383/13/15/4 red is fixture-dependent | legacy classification baseline and full run | Approved corpus or formal waiver absent |
| Provider contract | No real boundary evidence | Local OpenAI-compatible HTTP contract passes all 12 cases | provider baseline JSON, raw artifact and artifact checker | No live provider quality/availability evidence |
| Provider failure handling | Null/uncategorized failures | Safe typed errors, bounded retry, correlation, acquisition handling and cleanup | Professor contract tests (37 passed) | Renewal/production behavior still unobserved |
| Control-plane integrity | Phase 0.5 publication reconciled | Phase 0.6 plan/state/ledgers/checks aligned | control check, state, ledgers | Final commit publication/branch protection pending |
| CI | Characterization only | Fast/integration/historical/live lanes with pinned tools, provider-artifact validation and checks | workflow and CI README | GitHub execution/branch protection unavailable locally |
| Locker boundary | Host port existed in example | Private network, no host port/ingress, lint guard | boundary doc/lint/compose | Production network fidelity unverified |
| Veterinarian permissions | Broad legacy viewer surface | Query/history/source/collection only; source permission required for retrieval | permission/UI/ACL docs and negatives | UI/API policy must stay synchronized |
| Document/source ACL | Retrieval ACL present, source distinction incomplete | Source output cannot widen workspace/collection ACL | collection ACL docs and tests | Full approved corpus revalidation pending |
| Password hashing | Secure PBKDF2 baseline | Formally deferred to Phase 1 with rationale/task | password decision doc | Argon2id migration remains outstanding |
| RAG E2E | Local E2E passed in Phase 0.5 | Preserved; provider vertical flow independently passes locally | Phase 0.5 E2E plus provider artifact | Full corpus E2E blocked by missing fixtures |
| Citation provenance | Local authorized citation checks passed | Local real-protocol grounded citation and no-fake-citation checks pass | provider artifact, CVG ACL tests | Corpus provenance cannot be fully rerun |
| Production readiness | Not promoted | Not promoted; `BLOCKED` | final gate and report | Deployment/live/waiver evidence remains open |
