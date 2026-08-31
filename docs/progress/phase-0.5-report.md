# Phase 0.5 Result

**INCOMPLETE — candidate evidence collected, not promoted.** Phase 0 remains
`PARTIAL — NOT PROMOTED`. This report closes the isolated local verification
cycle for Phase 0.5 without starting Phase 1. The superseding VERIFIED gate is
`BLOCKED` after the independent review and material-gap retest.

## Executive Summary

Phase 0.5 established a reproducible local runtime and closed the highest-risk
contract, authorization, provenance, upload, locking and UI gaps found during
the baseline audit. The real local E2E path passed from ingestion through
restart and idempotent reingestion. The result is not promoted because the full
legacy CVG suite still contains data-dependent failures/errors in this clean
checkout, and live provider quality/outage behavior was not exercised.
The fresh independent review found no remaining P0/HIGH issue in the corrected
technical paths, but the full regression, provider and deployment-control gaps
still prevent promotion.

## Changes Made

- Pinned the isolated Python/Node/npm/Qdrant/Redis toolchain and added runtime
  bootstrap/start/stop scripts.
- Added `rag-contract-v1`, canonical `rag_phase0` collection aliases, stable
  document/chunk/point identities, checksums, versions and required payload
  fields.
- Added workspace and collection ACL enforcement to vector retrieval, disk
  fallback and protected metadata/list routes.
- Hardened upload filenames with generated storage names and retained display
  names as metadata.
- Added canonical roles, explicit permissions, server-side sessions, lifecycle
  invalidation, owner-safe opaque session revocation and neutral anonymous
  bootstrap.
- Removed bearer tokens from browser-facing session JSON/storage, scoped admin
  routes by workspace, and revalidated Qdrant result ownership before fusion.
- Fixed Locker compare-and-delete/renew ownership semantics and Professor
  evidence validation, trusted scope, named-vector usage and lock renewal.
- Removed raw Qdrant preflight exceptions from operator-facing job details while
  retaining server-side exception chaining for diagnostics.
- Repaired frontend dependency resolution and changed login/recovery to avoid
  anonymous tenant enumeration.
- Added typed runtime state, execution-log, gate, baseline, architecture and
  verification artifacts required by the engineering framework.

## Runtime Baseline Closure

The isolated runtime used Python 3.12.3, uv 0.8.14, FastAPI 0.109.2,
qdrant-client 1.7.3, Qdrant server 1.7.4, Node 22.19.0, npm 10.9.3 and Redis
7.0.15. Qdrant used HTTP port 6337 and Redis used isolated port 6380; host Redis
6379 was not touched. Exact commands and observations are in
`docs/baselines/phase-0.5-characterization.json` and
`docs/baselines/phase-0.5-performance.json`.

## Canonical RAG Contract

`rag-contract-v1` uses logical collection `rag_phase0`, named dense/sparse
vectors, `text-embedding-3-small` metadata, UUIDv5 identities derived from
workspace/collection/checksum and canonical provenance in every point, result
and citation. Retrieval applies workspace and collection filters before the
Qdrant query. The full contract is in
`docs/architecture/contracts/rag-contract-v1.md`.

## Identity Model

New passwords use per-user salted PBKDF2-HMAC-SHA256. Legacy demo hashes remain
read-compatible during migration. Sessions are server-side, expiring,
revocable and invalidated by user status, role or password changes. Anonymous
bootstrap returns no tenant inventory. The model and residual deployment
constraints are in `docs/architecture/security/identity-model.md`.

## Roles and Permissions

The canonical roles are `PLATFORM_ADMIN`, `KNOWLEDGE_MANAGER` and
`VETERINARIAN`. Legacy labels normalize only at the compatibility boundary.
Tenant/user administration is platform-admin-only; knowledge management is
separate from runtime/session administration; query access is distinct from
mutation access. See `docs/architecture/security/permission-model.md` and
`docs/architecture/security/ui-access-matrix.md`.

## Collection ACL

The effective access decision requires an active session, matching workspace and
an allowed logical collection (or an explicit wildcard). The same scope is
applied to Qdrant, disk fallback, list/detail endpoints and source metadata.
See `docs/architecture/security/collection-acl.md`.

## Security Fixes

Focused Phase 0.5 security tests passed for canonical role/permission mapping,
anonymous bootstrap, session invalidation and ownership, ACL filtering,
cross-workspace rejection, upload traversal/control-character rejection and
credential/secret redaction. Remaining production concerns are documented as
limitations rather than silently treated as verified behavior.
The HTTP login/session/me/switch responses are cookie-only for browser clients;
the backend retains an explicitly documented non-browser Bearer compatibility
path. Admin workspace scope, Qdrant result revalidation and Qdrant preflight
diagnostic redaction are covered by current focused regressions.

## Redis Locking Fixes

The Locker black-box run passed health, acquisition, contention, wrong-owner
unlock/renew, owner renewal, release, repeated release, expiry, malformed
requests and 16-way same-key contention with exactly one winner. Ownership is
checked in Redis-side scripts, and Professor releases only its own lock in a
`finally` path while renewing during long work.

## Professor Evidence/Citation Fixes

Professor retrieval uses the canonical named dense vector and trusted workspace
and collection scope. Planner-selected IDs are constrained to retrieved
evidence; fabricated replacement source/provenance is rejected. Final answers
retain citation section, collection and checksum fields. Evidence status and
weak-evidence handling are explicit.

## Test Results

- CVG focused Phase 0.5 contract/security and integration checks: **40 passed**.
- CVG full legacy suite: **364 passed, 19 failed, 14 skipped, 6 errors**.
  The failures/errors are scoped to absent `src/data/default/dataset.json`, the
  historical Fluxpay corpus, stale April-2026 telemetry fixtures and a small
  set of legacy expectations that conflict with canonical role/query/retention
  policy. No synthetic corpus was added to hide these gaps.
- Phase 0.5 full ingest/retrieval/provenance/idempotency E2E: **PASS**; Qdrant
  restart: **PASS**; Qdrant-unavailable disk fallback: **PASS**.
- Locker package tests: **2 passed**; black-box contract: **PASS**.
- Professor tests: **23 passed**; TypeScript build and fail-closed runtime
  probes: **PASS**.
- Frontend build and lint: **PASS**; Playwright smoke: **7 passed**.
- Production frontend dependency audit: **0 production vulnerabilities**.
- Independent review: no P0/HIGH in the corrected paths; final recommendation
  remains **NOT PROMOTED** because medium deployment/policy risks and the
  unresolved full-suite/provider gaps remain.

## Performance Results

Local loopback observations, not production SLOs: the latest CVG run measured
ingestion p50/p95 54.778/56.375 ms, retrieval 54.523/78.786 ms, answer
plumbing 7.037/9.547 ms;
Professor injected orchestration 0.296/2.875 ms; Locker HTTP unique-key
benchmark 133.201/144.544 ms. Provider latency/quality, multi-process capacity,
external OpenWebUI and production exporter behavior were not run. Full values
and sample sizes, including the current CVG refresh, are in
`docs/baselines/phase-0.5-performance.json`.

## Regression Results

The new risk-shaped checks and clean UI smoke pass. The independent review
confirmed that the previous HIGH findings were closed; the raw Qdrant error
leak was fixed and the affected focused retest passed 40 tests. The remaining
full-suite red tests are reproducibility/data-fixture or legacy-policy findings,
not claimed as passing, and must be resolved or explicitly accepted before a
promotion gate can pass.

## Remaining Risks

- Live OpenAI embedding and answer quality/outage behavior is unverified.
- The clean checkout lacks the historical default/Fluxpay evaluation corpus.
- The full CVG legacy suite remains blocked by 19 failures and 6 errors in the
  current clean checkout; 14 tests are skipped.
- In-memory login/reset rate limiting is process-local; production needs a
  distributed limiter and deployment-wide authentication middleware.
- Non-browser Bearer compatibility remains enabled by policy, and the Locker
  HTTP boundary relies on deployment network isolation rather than its own
  application credential.
- The local measurements do not establish production capacity or SLOs.
- Legacy payload migration and reconciliation remain additive follow-up work.

## Deferred Items

Phase 1 consolidation, production deployment validation, live provider quality
evaluation, historical corpus restoration, distributed rate limiting and any
legacy fixture/policy reconciliation are deferred. No Phase 1 work is included
in this result.

## Promotion Decision

**NOT PROMOTED.** The independent review found no remaining P0/HIGH issue in
the corrected technical paths, and the largest material diagnostic finding was
fixed and retested. The final superseding gate remains `BLOCKED` because the
full CVG suite is 364 passed, 19 failed, 14 skipped and 6 errors, live provider
quality is unavailable, and deployment-bound residual controls remain open.
The preserved Phase 0 status remains `PARTIAL — NOT PROMOTED`; Phase 1 and
publication are not authorized by this result.

Area | Before | After | Evidence | Remaining Risk
--- | --- | --- | --- | ---
Runtime | Unpinned/mixed local dependencies | Isolated pinned Python/Node/Qdrant/Redis runtime | phase-0.5 characterization | Production topology not exercised
RAG contract | Multiple names and unstable provenance | Canonical collection, IDs, payload and scoped retrieval | rag-contract-v1; E2E | Legacy data migration deferred
Identity | Mixed roles and anonymous tenant inventory | Canonical roles, server sessions, neutral bootstrap | identity/permission docs; security tests | Distributed rate limiting deferred
Collection ACL | Scope could diverge across routes | Workspace+collection scope across vectors, fallback and metadata | collection ACL; security tests | Legacy unauthenticated compatibility routes need deployment audit
Locking | Release/renew ownership not enforced | Owner-safe atomic release/renew and Professor lifecycle | Locker black-box; Professor tests | Local benchmark only
Evidence | Planner/citation provenance could drift | Trusted retrieval IDs and canonical citations | Professor tests; E2E | Live provider quality not run
Regression | Broad suite red with unclear baseline | New risk-shaped checks pass; legacy findings categorized | full pytest and smoke outputs | Missing historical fixtures still block final promotion
