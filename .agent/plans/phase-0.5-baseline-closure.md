# Phase 0.5 Runtime, Contract, and Security Baseline Closure

## Purpose / Big Picture

Close the explicitly requested Phase 0.5 work for the three existing components in this workspace: CVG Master RAG, Rick Professor, and Redis Locker. The deliverable is a reproducible, security-aware `VERIFIED_CANDIDATE` assessment only when the required gates have current evidence. Phase 0 remains `PARTIAL — NOT PROMOTED` until this phase proves otherwise. Phase 1 monorepo consolidation is out of scope and must not start.

The implementation will preserve each component boundary while adding compatible, versioned contracts and adapters. The critical user-visible behavior is: authorized users retrieve only authorized collections; evidence is derived from retrieved, immutable chunks; fabricated planner citations are rejected; ingestion is idempotent; distributed locks are owner-safe; uploads cannot escape their workspace; and the baseline can be reproduced from a fresh local environment.

## Progress

- [x] Recovered the current state, Phase 0 report, CVG instructions, source manifests, and root/child Git state.
- [x] Confirmed the root publication is clean at the existing Phase 0 commit; no history rewrite or destructive cleanup is authorized.
- [x] Defined the Phase 0.5 scope, quality bar, ownership split, and promotion gate before implementation.
- [x] (2026-08-31T02:44:20Z) Reconciled the stale Phase 0 control-plane pointer and bound Phase 0.5 to the implementation-ready gate.
- [x] (2026-08-31T04:07:14Z) Provisioned the isolated runtime and captured the Phase 0.5 environment baseline; live-provider limitations remain explicit.
- [x] (2026-08-31T04:07:14Z) Froze and implemented the canonical RAG contract and compatibility adapters.
- [x] (2026-08-31T04:07:14Z) Closed the scoped lock ownership, evidence/citation, upload, identity, RBAC, and collection-ACL defects; one diagnostic leak was fixed and retested after review.
- [x] (2026-08-31T04:07:14Z) Ran deterministic E2E, regression, concurrency, security, frontend and performance checks; the full legacy CVG suite remains explicitly blocked by historical failures/errors.
- [x] (2026-08-31T04:07:14Z) Obtained fresh independent criticism, fixed the largest material finding, reran 40 focused tests, and recorded the honest `BLOCKED`/`NOT PROMOTED` decision.

## Surprises & Discoveries

- The root repository is already published and clean, but the persisted Phase 0 control plane still points at the old audit task. This is state drift, not permission to erase history; the new phase gets a separate task, plan, and append-only events.
- Python has no usable `pip`/`venv` path in the current shell, Docker is absent, Qdrant is not listening on port 6333, and a host Redis on 6379 responds. Tests must use an isolated Redis port or an explicit BLOCKED result; they must not mutate the host Redis database.
- Professor's declared Node test command fails under the installed Node 22 loader path, while its TypeScript build is available. The test runner and import-time Redis lifecycle need a reproducible fix rather than a silent omission.
- The current vector layer already creates named `dense` and `sparse` vectors but uses a global collection, incomplete payloads, and process-random `hash()` point IDs. The canonical contract must make collection scope and stable IDs explicit.
- Existing CVG tests assert legacy role and permission names. The implementation will retain compatibility aliases while moving business decisions to canonical role/permission helpers.

## Decision Log

1. Use `rag_phase0` as the canonical collection identifier because it is the active CVG collection and can be retained without a destructive migration. `cvg_master_rag` and `rickvet_documents` are explicit compatibility aliases only; no silent multi-collection fan-out is allowed.
2. Use named Qdrant vectors `dense` (1536 dimensions, cosine) and `sparse` (BM25-compatible sparse vector), with a versioned payload containing ownership, document/chunk identity, source, text, pagination, parser/chunker/embedding versions, and checksum metadata.
3. Use deterministic UUIDv5 point IDs derived from the canonical chunk identity. Re-ingesting unchanged content must converge on the same document/chunk IDs and point IDs; changed content creates a new document version.
4. Keep legacy external roles (`super_admin`, `admin_rag`, `auditor`, `operator`, `viewer`, `admin`) as aliases, but resolve authorization through canonical roles `PLATFORM_ADMIN`, `KNOWLEDGE_MANAGER`, and `VETERINARIAN` plus explicit permission constants.
5. Treat provider-unavailable execution as a typed limitation. A deterministic local embedding/answer path may verify plumbing and grounding, but it cannot be reported as evidence of live provider quality.
6. Do not add or execute Phase 1 consolidation, force-push, history rewrite, `git reset --hard`, or `git clean -fd`.

## Outcomes & Retrospective

The phase is complete only when the report, contract, identity/permission/ACL documents, baseline JSON artifacts, control tasks, runtime state, CVG execution log, and typed verification ledger agree with the observed code and commands. If any required gate remains open, the report must say `BLOCKED` or `INCOMPLETE`; a passing score cannot override a failed security, data-integrity, or correctness gate.

Current outcome: the independent review found no remaining P0/HIGH issue in the
corrected technical paths. The raw Qdrant preflight exception was removed from
operator-facing details and the focused retest passed 40 tests. The superseding
VERIFIED gate remains `BLOCKED` because the full CVG suite is 364 passed, 19
failed, 14 skipped and 6 errors, live provider quality is unavailable, and
deployment-bound residual controls remain open. Phase 0 stays
`PARTIAL — NOT PROMOTED`; Phase 1 and publication remain out of scope.

## Context and Orientation

The workspace contains three source boundaries:

- `cvg-master-rag-v2/` — FastAPI ingestion, chunking, embeddings, Qdrant retrieval, enterprise session/admin logic, and the CVG frontend.
- `rick-professor/` — Fastify orchestration, OpenAI embedding/planner/answer flow, Qdrant client, and Redis lock client.
- `modulo-redis-locker/` — Express HTTP lock service backed by Redis.

Root `docs/` holds the cross-system contract and evidence. `.agent/` is the control plane. CVG's `AGENTS.md` additionally requires the CVG runtime state and master execution log to be updated without rewriting historical entries.

## Scope and Constraints

In scope: runtime reproducibility, canonical RAG schema, stable identity, ingestion idempotency, authorized retrieval, evidence gates, safe upload handling, owner-safe locks, canonical identity and session lifecycle, RBAC, server-side authorization, collection ACLs, audit events, tests, performance baselines, and required documentation.

Out of scope: Phase 1 monorepo consolidation, broad UI implementation, provider/vendor migration, production deployment, destructive data cleanup, and history rewriting.

All changes must be reversible and reviewable. Secrets, raw Redis URLs, bearer/API keys, auth headers, uploaded bytes, and full user credentials must not enter logs or evidence artifacts.

## Architecture and Interfaces

### Canonical RAG interface

The CVG vector adapter owns canonical collection resolution, schema creation/validation, stable point IDs, payload serialization, workspace/collection Qdrant filters, and compatibility reads. Retrieval receives a `RetrievalContext` containing authenticated user, workspace, allowed collection IDs, and permissions. Authorization is applied in the server-side vector filter before evidence is built. The Professor adapter accepts only retrieved result records and an optional trusted retrieval context; planner output can select IDs but cannot supply evidence text or provenance.

### Identity and authorization interface

Users carry canonical identity fields, lifecycle status, tenant/workspace ownership, canonical role resolution, permissions, and collection grants. Passwords use a strong standard-library KDF for new records while old hashes remain verifiable during migration. Sessions are server-side, revocable, disabled-user aware, secure-cookie based, rate-limited at login, and generic on authentication failure. Admin endpoints use explicit permissions; knowledge management must not imply user/role administration.

### Lock interface

`/lock` acquires `(lock_key, lock_value, ttl_ms)` with `SET NX PX`. `/unlock` requires the same owner value and atomically compare-deletes using Lua. `/renew` (when used) requires the same owner and atomically extends TTL. Missing or wrong owners do not release another owner's lock. Error responses are generic and logs are redacted.

### Upload interface

The CVG API rejects NUL, absolute, traversal, and separator-bearing upload names; stores content under a generated safe workspace-local name; retains a sanitized display name; enforces supported extensions and bounded size; and uses checksum/document identity to avoid duplicate indexing.

## Milestones

### M1 — Control plane and environment baseline

Create the phase-specific control tasks, gate record, isolated Python/Node/runtime recipe, deterministic test services, and baseline artifacts. Record unavailable prerequisites as BLOCKED with an explicit unblock action.

### M2 — Contract and identity foundation

Add versioned RAG models, collection resolution, stable IDs, RetrievalContext, canonical role/permission helpers, session/user lifecycle fields, and documentation/tests before wiring all routes.

### M3 — P0 correctness and security closure

Implement owner-safe Locker operations, Professor release/failure cleanup, evidence gate and planner-ID validation, safe uploads, idempotent ingestion, server-side collection ACL filtering, explicit admin permissions, and redacted diagnostics.

### M4 — Integrated verification

Run Professor/CVG/Locker/frontend tests, a deterministic ingest-to-query restart/reingest scenario, negative authorization and citation tests, concurrent lock checks, and performance measurements. Persist commands, results, limitations, and artifacts.

### M5 — Independent gauntlet and promotion decision

Have a fresh reviewer inspect the resulting artifact and evidence. Fix the highest-risk finding, rerun affected regressions, then publish the required Phase 0.5 report. Do not write the Phase 1 plan unless the exact promotion decision is `VERIFIED_CANDIDATE` or `PROMOTED`; this work is not permitted to make that phase transition implicitly.

## Plan of Work

1. Reconcile `.agent` state from Phase 0 to Phase 0.5 after creating this plan and the quality-bar state; append a recovery/start event and add `PH05-ENV`, `PH05-RAG-CONTRACT`, `PH05-LOCK`, `PH05-EVIDENCE`, `PH05-UPLOAD`, `PH05-IDENTITY`, `PH05-ACL`, and `PH05-VERIFY`.
2. Provision isolated dependencies without mutating the host Redis database; repair only the frontend lock drift needed for reproducible installation; fix Professor test lifecycle/runner; capture exact versions and commands.
3. Freeze `rag-contract-v1.md`, implement the adapter/models and stable identity, then add fixtures for canonical payloads, aliases, schema mismatch, and idempotent reingestion.
4. Implement Locker compare-delete/renew and Professor `finally` release. Add failure, wrong-owner, contention, expiry, and provider-error tests.
5. Implement explicit `NO_EVIDENCE`, `WEAK_EVIDENCE`, and `APPROVED_EVIDENCE`; validate planner IDs against authorized retrieved chunks; add fabricated-ID, wrong-document, inaccessible-collection, and nonretrieved-text tests.
6. Harden upload names and generated storage paths; add identity/session/RBAC/audit changes and route-level authorization; add collection ACL filter tests and cross-tenant/non-leak checks.
7. Run A/B/C/D/E/F/G/J/K/L/M/N/O-equivalent Phase 0.5 checks with only `PASS`, `PASS_WITH_FINDING`, `FAIL`, or `BLOCKED`; capture latency, throughput, memory, index size, duplicates, restart behavior, and concurrency where measurable.
8. Update cross-system and CVG execution artifacts, run independent criticism, fix/retest, and publish the final status using the required report headings and promotion gate table.

## Concrete Steps

1. Verify current Git worktrees and the root HEAD; preserve all existing user changes.
2. Add `.gauntlet/state.md`, this ExecPlan, and the Phase 0.5 backlog/control events.
3. Record `IMPLEMENTATION_READY` only after scope, dependencies, acceptance, risks, and verification are present; keep any unresolved environment limitation explicit.
4. Implement one bounded workstream at a time with focused tests and append verification records after each material checkpoint.
5. Before each integration step, inspect diffs in the owning component and ensure no secrets or generated runtime state entered source control.
6. Before final status, rerun the full risk-shaped regression set after the independent review fix.

## Validation and Acceptance

Required gates:

- isolated versions and reproducible setup command;
- CVG test suite and Professor test suite pass or have explicitly scoped findings;
- frontend install/build/smoke passes with lockfile consistency;
- isolated Qdrant and Redis checks pass, or the report is BLOCKED with no false claim;
- end-to-end ingest → chunks → embeddings → vectors → query → answer → provenance → restart → reingest has no unauthorized leakage or duplicate points;
- canonical schema, stable IDs, and compatibility aliases are tested;
- evidence status rejects no-hit/weak/fabricated/wrong/inaccessible citations;
- lock owner, compare-delete, renewal, expiry, contention, and `finally` release are tested;
- upload traversal, collision, extension, size, and secret/log hygiene checks pass;
- identity lifecycle, password hashing, session invalidation, rate limiting, generic failures, RBAC, route authorization, and audit events are tested;
- collection ACLs are enforced in server-side Qdrant filters and citations do not leak inaccessible source metadata;
- regression, concurrency, restart, and performance evidence is current and independently reviewed.

The exact final status is one of `BLOCKED`, `INCOMPLETE`, `FUNCTIONALLY_COMPLETE`, `VERIFIED_CANDIDATE`, or `PROMOTED`. `VERIFIED_CANDIDATE` is forbidden while any P0/HIGH correctness or security issue remains open.

## Risks and Human Decisions

- Live OpenAI quality and production deployment capacity may remain unavailable; report those as limitations and do not substitute them with invented metrics.
- Existing data in legacy Qdrant collections may not satisfy the canonical payload. Migration is additive and explicit; no destructive cleanup or silent alias fan-out.
- Changing legacy roles or permissions could break existing clients. Compatibility aliases are required, and any behavior change must have route-level regression evidence.
- A human decision is required only if promotion authority, production credentials, irreversible migration, or a material policy choice is needed. Local reversible fixes and evidence collection remain authorized.

## Idempotence and Recovery

Every implementation step is scoped to a component and can be rerun. Runtime data lives in an ignored isolated directory or temporary service. If a command fails, append the failure and next action, do not rewrite a prior record, and rerun only after addressing the stated cause. If state contradicts code or evidence, preserve both observations, append a recovery/correction event, and make the corrected pointer explicit. If a gate reopens, append a new gate record and bound event; never edit the old decision.

## Artifacts and Evidence

Required final artifacts:

- `docs/progress/phase-0.5-report.md`
- `docs/architecture/contracts/rag-contract-v1.md`
- `docs/architecture/security/identity-model.md`
- `docs/architecture/security/permission-model.md`
- `docs/architecture/security/ui-access-matrix.md`
- `docs/architecture/security/collection-acl.md`
- `docs/baselines/phase-0.5-characterization.json`
- `docs/baselines/phase-0.5-performance.json`
- updated `docs/architecture/current-system.md` only where actual behavior changed
- `.agent/state.json`, `.agent/backlog.json`, `.agent/execution-log.jsonl`, `.agent/verification.jsonl`
- `cvg-master-rag-v2/docs/99_runtime_state.md` and `docs/20_master_execution_log.md` append-only updates

The report must use the required headings: `Phase 0.5 Result`, `Executive Summary`, `Changes Made`, `Runtime Baseline Closure`, `Canonical RAG Contract`, `Identity Model`, `Roles and Permissions`, `Collection ACL`, `Security Fixes`, `Redis Locking Fixes`, `Professor Evidence/Citation Fixes`, `Test Results`, `Performance Results`, `Regression Results`, `Remaining Risks`, `Deferred Items`, and `Promotion Decision`, followed by the required `Area | Before | After | Evidence | Remaining Risk` table.
