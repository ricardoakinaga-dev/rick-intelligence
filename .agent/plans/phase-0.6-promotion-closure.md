# Phase 0.6 — Promotion Closure

## Objective

Close only the explicit Phase 0.5 promotion blockers and decide one of
`BLOCKED`, `INCOMPLETE`, `FUNCTIONALLY_COMPLETE`, `VERIFIED_CANDIDATE`, or
`PROMOTED`. The desired outcome is `VERIFIED_CANDIDATE` only when every
required criterion has fresh evidence. Phase 1 remains out of scope and its
plan must not be created unless the final decision is exactly
`VERIFIED_CANDIDATE`.

## Starting state

- Published root commit: `7925beb972cd7d3a85c883506254bad98a43cbee` on `main` and
  `origin/main`; root worktree was clean at recovery.
- Current Phase 0.5 gate: `.agent/gates/phase-0.5-verified-blocked-final.json`,
  decision `BLOCKED`.
- Historical CVG baseline: `364 passed, 19 failed, 14 skipped, 6 errors`.
- Live provider evidence and production deployment evidence were not available
  in Phase 0.5; no credentials may be copied into artifacts or agent briefs.
- Three component boundaries remain independent: `cvg-master-rag-v2/`,
  `rick-professor/`, and `modulo-redis-locker/`.

## Frozen quality bar v1

| ID | Required target | Evidence |
| --- | --- | --- |
| PH06-RBAC | Explicit additions/removals produce effective permissions; wildcard behavior is defined; removed permissions are never re-granted by role fallback; legacy session snapshots remain stable until invalidation; allow/deny tests pass. | CVG unit, session, route and negative security tests |
| PH06-LEGACY | Every 19 failure and 6 error baseline item is individually classified, explained, and resolved, waived, or explicitly remains a blocker; no xfail/skip masking. | Full CVG run plus `docs/baselines/phase-0.6-legacy-test-classification.md` |
| PH06-PROVIDER | A real configured provider or real local OpenAI-compatible HTTP server exercises success, timeout, unavailable, 429, 500, malformed/missing/invalid/empty/model-not-found/dimension cases with safe errors, bounded retry, correlation, state/lock cleanup and grounded citations. | `docs/baselines/phase-0.6-provider-contract.json` and raw contract run |
| PH06-CONTROL | HEAD, published SHA, remote SHA, worktree, branch, sync and Phase 0.6 pointer agree; corrections append history. | state, backlog, plan, ledgers, gate and control check |
| PH06-CI | Enforceable fast/integration checks cover Python, Phase 0.5/0.6 contracts/security, Professor, Locker, frontend, secret/dependency scans, fixtures and control-plane integrity; historical lane has explicit waiver if needed. | GitHub workflow and local CI validation |
| PH06-LOCKER | Locker has an internal-only deployment boundary with no public host port/ingress/reverse proxy and a lint/test guard. | deployment files, boundary doc, lint/test |
| PH06-VET | `sources.read`, `library.browse`, and `documents.read` are distinct; recommended VET has query/history/source/collection access only; ACL remains authoritative and negative tests pass. | policy/docs, permission/UI/ACL tests |
| PH06-PASSWORD | Argon2id migration is implemented or password hashing is formally deferred to Phase 1 with rationale and task; PBKDF2 is not silently treated as closed. | decision section and deferred task |
| PH06-REVIEW | Fresh independent review answers all 12 required questions and finds no open P0/HIGH blocker for a candidate decision. | `docs/progress/phase-0.6-independent-review.md` |

No score can cancel a failed required correctness, security, ACL, control-plane,
or provider-boundary criterion. A missing credential or unavailable external
provider is recorded as `BLOCKED`/waived with authority and cannot be called a
pass. No historical log or test is deleted or hidden.

## DAG and ownership

| Task | Owner | Owns | Depends on | Status |
| --- | --- | --- | --- | --- |
| PH06-RECON | Lead | root control plane and this plan | recovery discovery | DONE |
| PH06-RBAC | CVG worker | `src/services/authorization.py`, auth/session/admin schemas and assigned Phase 0.6 tests/docs | PH06-RECON | DONE |
| PH06-LEGACY | read-only scout then Lead | baseline inventory/classification report; no source edits by scout | PH06-RECON | BLOCKED |
| PH06-PROVIDER | Professor worker | Professor provider adapter and provider contract harness/tests | PH06-RECON | DONE |
| PH06-LOCKER-CI | Locker/CI worker | root `.github/`, Locker deployment/docs/tests, Professor compose example | PH06-RECON | DONE |
| PH06-INTEGRATE | Lead | cross-workstream docs, ledgers, state, final report/gate | all implementation lanes | DONE |
| PH06-REVIEW | fresh read-only reviewer | independent review artifact only | integrated retest | DONE |

Workers must not commit, push, force-push, reset, clean, mutate production, or
touch another lane's files. The Lead inspects all diffs and owns integration.
Runtime services and test data are isolated and disposable; secrets remain
outside files, logs, reports, and prompts.

## Execution order

1. Reconcile actual Git/control state and record Phase 0.6 start.
2. Correct RBAC/session snapshot semantics and veterinarian permission policy.
3. Enumerate and classify the complete legacy baseline; resolve real regressions
   and document legitimate waivers without masking tests.
4. Exercise the provider boundary through a real HTTP protocol server or the
   configured provider, including all required failures and state cleanup.
5. Formalize the Locker network boundary and enforceable CI.
6. Decide password hashing, run the full risk-shaped regression surface, and
   reconcile control-plane artifacts.
7. Obtain a fresh independent review, fix only material findings, retest, and
   write the Phase 0.6 report and final gate.
8. Create the Phase 1 plan only if and after the final gate is
   `VERIFIED_CANDIDATE`; never implement Phase 1 here.

## Current closeout checkpoint

The RBAC, provider, Locker-boundary, dependency, CI, VET, and password-decision
lanes have current local evidence. The legacy lane is explicitly blocked by
the absent approved default/Fluxpay/tenant corpus and the lack of an
owner-authorized permanent waiver. The final full CVG result is therefore
`383 passed, 13 failed, 15 skipped, 4 errors`, with every red item classified
in the baseline artifact. The fresh independent review is the final remaining
review gate; no Phase 1 plan or implementation is permitted while the final
classification is not exactly `VERIFIED_CANDIDATE`.

The superseding final gate is `.agent/gates/phase-0.6-promotion-final.json`:
`BLOCKED` / `NOT_PROMOTED`. Phase 1 was not started and no Phase 1 plan was
created. Reopening requires the approved corpus or an owner-authorized waiver,
plus the currently unavailable external provider, CI, dependency-audit and
production-network evidence.

## Required final artifacts

- `docs/progress/phase-0.6-report.md`
- `docs/baselines/phase-0.6-legacy-test-classification.md`
- `docs/baselines/phase-0.6-provider-contract.json`
- `docs/progress/phase-0.6-independent-review.md`
- `.agent/gates/phase-0.6-promotion-final.json`
- reconciled `.agent/state.json`, `.agent/backlog.json`,
  `.agent/execution-log.jsonl`, `.agent/verification.jsonl`, and
  `.gauntlet/state.md`

## Stop rule

Stop honestly at `BLOCKED` or `INCOMPLETE` when a required criterion lacks
current evidence or depends on unavailable authority/environment. Never promote
over an open P0/HIGH issue, unresolved legacy red surface, fake provider test,
public Locker exposure, implicit veterinarian admin access, or control-plane
drift.
