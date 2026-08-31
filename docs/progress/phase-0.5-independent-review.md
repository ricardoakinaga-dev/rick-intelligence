# Phase 0.5 Independent Review

## Review Result

**NOT PROMOTED.** A fresh read-only review found no P0 or HIGH issue in the
corrected security paths, but identified medium residual risks and stale
control evidence. The largest factual issue was corrected after the review:
the Qdrant preflight exception is no longer included in operator-facing job
details, and a regression test now protects that boundary.

## Scope and Independence

- Review type: fresh independent read-only critique after the integrated test
  run.
- Scope: CVG Master RAG, Rick Professor, Redis Locker, frontend, and Phase 0.5
  control artifacts.
- No files were edited, committed, or pushed by the reviewer.

## Findings

### P0/HIGH

No P0 or HIGH finding remained in the six previously identified technical
paths:

- Browser sessions return `session_token: null`; the frontend uses cookie
  credentials and does not persist or inject bearer tokens.
- Admin workspace scope distinguishes `KNOWLEDGE_MANAGER` from
  `PLATFORM_ADMIN`.
- Professor OpenAI-compatible routes fail closed without `API_KEY`.
- The Telegram webhook requires a secret, uses constant-time comparison and
  Redis idempotency; the liveness health route is public.
- CVG and Professor validate Qdrant workspace and collection ownership before
  evidence is used.
- Planner output is allowlisted and citations are constrained to retrieved
  authorized IDs.

Evidence includes the current focused CVG tests, Professor tests, frontend
smoke and the runtime probes recorded in the final verification ledger.

### MEDIUM

- Bearer authentication remains an explicit non-browser compatibility path;
  the browser surface is cookie-only, but the whole backend is not exclusively
  cookie-only.
- Redis Locker HTTP authentication is deployment/network-bound and has no
  independent application credential at the loopback service boundary.
- Live provider quality/outage behavior and the historical default/Fluxpay
  corpus remain unavailable.
- The full legacy CVG suite remains red in the clean checkout and requires
  fixture/policy reconciliation.

The reviewed diagnostic-leak finding was fixed in
`cvg-master-rag-v2/src/services/ingestion_job_service.py`: the internal Qdrant
exception remains chained for server diagnostics but is absent from public
preflight details. The focused regression
`test_large_ingestion_preflight_does_not_expose_qdrant_exception` covers it.

## Fresh Evidence

- CVG Phase 0.5 focused integration/security slice: **40 passed**.
- CVG full legacy suite: **364 passed, 19 failed, 14 skipped, 6 errors**.
- Professor: **23 passed**, build passed.
- Locker: **2 passed**, black-box protocol PASS with one contention winner.
- Frontend: lint/build passed; Playwright smoke **7 passed**.
- E2E full, Qdrant restart and disk fallback: **PASS**.

## Decision

The corrected implementation is materially stronger and the previous HIGH
findings are closed, but the Phase 0.5 VERIFIED gate remains **BLOCKED**. The
remaining provider, historical-corpus, full-regression and deployment-bound
risks are explicit and are not silently promoted to `VERIFIED_CANDIDATE`.
