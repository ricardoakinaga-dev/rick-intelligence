# Phase 0.5 Gauntlet State

## Goal

Close the authorized Phase 0.5 runtime, contract, correctness, identity, ACL, security, and verification gaps across CVG Master RAG, Rick Professor, and Redis Locker. Produce a reproducible evidence package and an honest promotion decision. Do not begin Phase 1 consolidation.

## Quality bar v1 (frozen before implementation)

Release-blocking gates:

1. Runtime reproducibility: pinned versions, isolated services, executable setup, and no host Redis mutation.
2. Contract/data integrity: versioned canonical `rag_phase0` named-vector schema, complete ownership payload, deterministic IDs, compatibility aliases, and idempotent reingestion.
3. Retrieval security: authenticated RetrievalContext, server-side workspace/collection filters, no cross-ACL source/citation leakage.
4. Evidence correctness: explicit `NO_EVIDENCE`/`WEAK_EVIDENCE`/`APPROVED_EVIDENCE`; only retrieved authorized IDs can become citations/evidence.
5. Concurrency safety: owner-bound compare-delete, renewal/expiry semantics, failure cleanup, and contention evidence.
6. Identity/RBAC: strong password handling, session invalidation/lifecycle, generic failures/rate limits/secure cookies, canonical roles, explicit permissions, route enforcement, and audit events.
7. Upload/log security: traversal and collision resistance, size/extension checks, and secret/PII-safe diagnostics.
8. Regression/integration: CVG, Professor, Locker, frontend, E2E restart/reingest, negative security, concurrency, and performance evidence.
9. Independent review: fresh criticism, largest-gap fix, and affected regression rerun.

No score can override a failed mandatory security, correctness, data-integrity, or runtime gate. A provider-unavailable finding is reported as a limitation, never as a fabricated pass.

## Ownership and dependency graph

- Lead: control plane, contract integration, CVG auth/ACL/upload/ingestion, docs, verification, and final integration.
- Scout/reviewer: independent read-only architecture and test criticism; no secrets, pushes, destructive commands, or overlapping edits.
- Workstream order: `ENV -> RAG-CONTRACT -> {LOCK, EVIDENCE, UPLOAD, IDENTITY, ACL} -> VERIFY -> REVIEW -> FIX/RETEST -> FINAL`.
- CVG `AGENTS.md` remains binding for CVG state/log updates and append-only history.

## Gauntlet rounds

- Round 0 DISCOVER/DEFINE: complete; Phase 0 drift and current runtime gaps recorded.
- Round 1 BUILD: complete; bounded component changes landed in the three preserved component boundaries with focused tests.
- Round 2 RUN_INSPECT: complete; isolated runtime, E2E, restart, disk fallback, component and frontend evidence was captured.
- Round 3 CRITIQUE/SCORE: complete; a fresh independent reviewer found no P0/HIGH issue in the corrected technical paths and identified medium residual risks plus stale evidence.
- Round 4 FIX_RETEST/INTEGRATE: complete; the raw Qdrant preflight exception was removed from operator-facing details and the affected focused regression passed; control artifacts were refreshed append-only.
- Round 5 FINAL_GAUNTLET: complete with `BLOCKED`/`NOT PROMOTED`; the exact current decision and revalidation triggers are in `.agent/gates/phase-0.5-verified-blocked-final.json`.

## Stop conditions

Stop at `BLOCKED` or `INCOMPLETE` when required external/runtime evidence cannot be obtained safely; otherwise continue until all material P0/HIGH gaps are closed or a marginal-gain stop is justified. The current stop is justified by the full legacy CVG regression blocker, unavailable live provider evidence, and deployment-bound residual controls. No P0/HIGH issue remains in the corrected paths, but these findings are not silently promoted. Never start Phase 1 from this phase.
