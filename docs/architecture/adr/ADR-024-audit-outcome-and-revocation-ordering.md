# ADR-024 — Audit outcome state machine and revocation ordering

**Date:** 2026-10-24 (America/Sao_Paulo). **Status:** Accepted — human decision `AUD24-D1` (A+ two-stage), local/reversible scope. **Stage 1 and Stage 2 implemented and verified locally on 24/10/2026; live PostgreSQL/IdP remains NOT_RUN.** **Production execution:** not authorized by this ADR.
**Supersedes/amends:** [ADR-008](ADR-008-audit-failure-policy.md) for logout and password-reset ordering. Does not change ADR-008's fail-closed requirement for security mutations.
**Related:** [AUD24 audit](../../reports/relatorio-auditoria-2026-10-24.md), [AUD24 plan](../../plans/execplan-aud24-2026-10-24.md), [AUD24 backlog](../../backlog-auditoria-2026-10-24.md), `AUD24-01/02/03`.

## 1. Context

Logout and password reset are security effects that also require an audit trail. The current implementation emits `requested` before revocation and `completed` after it. The sink is an arbitrary synchronous port. If the process times out after the effect commits but before the completion write is acknowledged, the API returns 503 while the sink may later persist `completed`. If the requested write succeeds and the effect fails, an orphan `requested` remains. There is no unique key or reconciler.

The B01 regression proves the false-completion class is reachable. It is not sufficient to delete the test or to declare the timeout harmless: the contract between the security effect, the HTTP response and the durable audit record must be explicit.

ADR-008 says security-critical mutations are fail-closed when the durable audit write fails. That intent stays. What changes is **where durability is enforced**: on the operation record written with the effect, not on an external sink delivery that can block or fail after the effect is already committed.

## 2. Decision

Adopt **A+ in two stages**.

> **A+** = durable audit-outcome record with idempotency and reconciliation (A), plus a same-transaction fast path when the canonical sink shares the identity database (D), using the honest indeterminate response semantics (C) as the HTTP contract.

**Stage 1 (semantics and idempotency, required before M1 exits):**
- Revocation is the security effect and does not depend on external sink availability.
- `completed` means **acknowledged by the audit boundary**, not “attempted” or “the handler returned”.
- No terminal event may be written after the HTTP response was abandoned.
- A unique operation key prevents duplicate terminal records.
- Unconfirmed effect returns `503` with code `result_indeterminate` and a `request_id`; it never returns `signed_out`.
- Cookies are deleted only when the session revocation is confirmed; an unconfirmed audit does not keep a dead session cookie alive. The response does **not** claim `signed_out` or `completed`.

**Stage 2 (durable outcome and reconciliation, required before M3 exits):**
- A durable operation record is written in the same transaction as the security effect (revocation, credential change, session revocation).
- The external audit sink is a **projection** of that record, delivered at-least-once with an idempotency key.
- A reconciler closes `effect_applied`/`indeterminate` records as `acknowledged` or `failed`.
- When the canonical sink is the same PostgreSQL, the projection is written in the same transaction (fast path D); external sinks use the outbox path (A).

Stage 1 is deliberately smaller: it removes the false completion and unblocks the CONTRACT lane without waiting for the full outbox. Stage 2 is the target contract and cannot be dropped silently.

## 3. State machine

The durable record is keyed by `(action, request_id)`. One row per operation, not a stream of unrelated events.

| State | Meaning | Terminal |
|---|---|---|
| `requested` | Intent registered; effect not yet confirmed | No |
| `effect_applied` | Revocation or credential change committed | No |
| `acknowledged` | Audit projection accepted by the boundary | **Yes (success)** |
| `indeterminate` | Effect applied; acknowledgement not confirmed within budget | No |
| `failed` | Effect not applied, or unrecoverable projection failure after retries | **Yes (failure)** |

Allowed transitions:

```text
requested ──► effect_applied ──► acknowledged
    │               │
    │               └──► indeterminate ──► acknowledged
    │                                      └──► failed
    └──► failed
```

Rules:
- No transition out of `acknowledged` or `failed` except an explicit correction record with its own audit trail.
- A late sink callback may only confirm the existing record; it may not create a second terminal record.
- `completed` in the public event vocabulary is an alias for `acknowledged`; it is not a separate write after the fact.

## 4. Ordering and HTTP contract

### Logout

1. Open the identity transaction; register the operation (`requested`) and revoke the session (`effect_applied`) atomically.
2. Commit. The effect is now real and durable.
3. Project the audit event to the sink with the operation key and a bounded deadline.
4. On acknowledgement: mark `acknowledged`, delete session/CSRF cookies, return `200 {"status":"signed_out"}`.
5. On timeout/ambiguous acknowledgement: keep `effect_applied`/`indeterminate`, delete the session/CSRF cookies (the authority is already invalid), return `503` with `{"error":{"code":"result_indeterminate",...,"request_id":"..."}}`. Do not write `completed`; do not claim `signed_out`.
6. On effect failure: mark `failed`, keep cookies, return `503 provider_unavailable`; retry is safe.

### Password reset

1. In one transaction: consume the single-use token, update credentials, revoke sessions, register the operation, mark `effect_applied`.
2. Commit.
3. Project and acknowledge exactly as logout.
4. If the effect committed but the acknowledgement did not: return `503 result_indeterminate` with `request_id`; the password is already changed and the token is consumed. Do not claim success; do not allow a second consume.
5. If the transaction fails: no effect, no terminal record; return a safe error.

### Admin security mutations

ADR-008 remains in force: the durable operation record is part of the mutation transaction. If it cannot be written, the mutation fails closed. The external projection is reconciled; it does not block the effect after the durable record exists.

## 5. Durable record vs audit sink

- The **operation record** is authoritative for “what happened and whether it was acknowledged”.
- The **audit sink** is the delivery/projection boundary. It may be PostgreSQL, an external log store, or a test sink.
- The sink must accept an idempotency key and expose an acknowledgement. A sink that returns void is treated as acknowledged only if the canonical composition declares it durable; otherwise it is a projection with reconciliation.
- `emit_required` becomes “register/project with acknowledgement”, not “call an arbitrary emitter and hope”.
- No second event vocabulary: one operation schema, one writer, one status set.

## 6. Reconciliation

- The reconciler runs outside the API request path (worker/cron/CLI), with its own bounded concurrency and timeout.
- It selects `requested`, `effect_applied` and `indeterminate` records older than a threshold, retries projection with idempotency, and marks `acknowledged` or, after the configured budget, `failed`.
- It emits a metric for oldest indeterminate age, attempts, and failures. A sustained backlog is an operational alert, not a silent state.
- It never deletes records. Retention is a separate policy.
- A manual CLI exists for operators; there is no public HTTP endpoint to force acknowledgement.

## 7. Storage and migration

Proposed additive table (name may change at implementation; the contract does not):

```sql
CREATE TABLE rick_audit_operations (
    operation_id      TEXT PRIMARY KEY,
    action            TEXT NOT NULL,
    request_id        TEXT NOT NULL,
    tenant_id         TEXT NOT NULL,
    actor_user_id     TEXT,
    workspace_id      TEXT,
    state             TEXT NOT NULL CHECK (state IN
                        ('requested','effect_applied','acknowledged','indeterminate','failed')),
    payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
    effect_at         TIMESTAMPTZ,
    acknowledged_at   TIMESTAMPTZ,
    attempts          INTEGER NOT NULL DEFAULT 0,
    last_error_code   TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (action, request_id)
);
CREATE INDEX rick_audit_operations_state_idx
    ON rick_audit_operations (state, updated_at);
```

- Additive migration; existing `rick_audit_events` remains append-only and receives projections.
- Deploy order: migration → code that writes the operation record → code that reconciles. Rollback drops the table only after the previous code is restored.
- The same-transaction fast path uses the identity connection; no second connection inside the transaction.

## 8. Consequences

**Positive**
- The security effect no longer depends on external sink availability.
- `completed` cannot be written after an abandoned response.
- Duplicate concurrent logout/reset collapse to one operation.
- Orphans have a terminal disposition and an operational signal.
- The CONTRACT lane can be green without deleting B01.

**Negative / costs**
- New table, migration, reconciler, runbook and alert.
- Sink projections are at-least-once; the sink or projection must deduplicate by key.
- The API returns `503 result_indeterminate` in a case where the user is effectively logged out; clients must show the `request_id` and avoid claiming success.
- More code on the identity path; must not block the event loop or extend the transaction.

**Neutral**
- OIDC remains without logout; this ADR does not invent broker capability. The OIDC profile stays out of production until AUD24-D3 is resolved.

## 9. Alternatives rejected

- **B — sink-level prepare/commit/abort alone:** requires every sink to implement fencing; arbitrary synchronous sinks cannot guarantee no commit after timeout; high cost, low portability. Acceptable only as an internal optimization for the canonical Postgres, not as the general contract.
- **C alone — semantic honesty without durable outcome:** removes the false completion but leaves orphans and no terminal state. Acceptable as Stage 1, not as the target.
- **D alone — same-transaction audit:** strongest when identity and audit share PostgreSQL, but not portable to external sinks and does not cover the general composition. Retained as the fast path inside A+.

## 10. Test matrix (minimum)

| Scenario | Expected |
|---|---|
| Sink blocks after effect; response times out | `503 result_indeterminate`; no `acknowledged` after abandon; reconciler later marks exactly one |
| Sink unavailable before effect | Effect not applied; `503 provider_unavailable`; no terminal record |
| Duplicate concurrent logout with same request | One operation row; one terminal state |
| Retry after indeterminate | Same operation; no second revocation/consume |
| Crash between commit and projection | `effect_applied` survives; reconciler closes |
| Reset effect commits, ack times out | `503 result_indeterminate`; token consumed; one audit operation; retry cannot consume again |
| Cookie policy | Deleted only when revocation confirmed; no `signed_out` on indeterminate |
| Reconciler retry storm | Bound/backoff; no duplicate terminal rows; metric/alerts |
| Old B01 test | Rejects late `completed`; remains in the CONTRACT lane |

## 11. Rollout

1. **Stage 1:** contract, unique key, ordering, HTTP semantics, tests; update the B01 regression expectation to the new contract; CONTRACT lane green.
2. **Stage 2:** table/migration, operation writer in the identity transaction, projection, reconciler, metrics; crash/concurrency tests; lab migration.
3. **Promotion:** requires the usual external gates; this ADR is local/reversible and does not authorize production execution.

## 12. Relationship to ADR-008

ADR-008 required fail-closed audit for security-critical mutations. ADR-024 preserves that requirement at the **durable operation record** level: if the record cannot be written with the effect, the mutation fails. It changes only the post-effect external projection, which becomes asynchronous/reconciled with an explicit indeterminate response. The earlier “audit before revoke” ordering is superseded for logout and password reset because it made a security effect depend on telemetry availability.

## 13. Open items (not blocking the decision)

- Exact table name and whether the operation record lives in the identity schema or a shared control schema.
- Whether the canonical Postgres sink can accept the projection in the same transaction for all mutations or only logout/reset.
- Reconciler cadence, retention and alert thresholds to be ratified with operations.
- Client copy for `503 result_indeterminate` and whether the UI offers a “consultar status” action by `request_id`.
- OIDC broker/revocation is explicitly out of scope (AUD24-D3).


## 14. Implementation status (2026-10-24)

**Stage 1 — implemented locally.**
- Logout revokes before audit; the request path writes `effect_applied`, never `completed`.
- Audit failure/abandonment returns `503 result_indeterminate` with `request_id`; no false `signed_out`.
- Password reset carries server-derived scope and emits `auth.reset_effect` once on the normal path; audit failure is indeterminate.
- `PostgresAuditSink` derives a stable event id from `(action, request_id, status)` and uses `ON CONFLICT (event_id) DO NOTHING`.
- B01 regression remains in the CONTRACT lane and passes under the new contract.

**Stage 2 — implemented locally.**
- Migration `0011_audit_operations.sql` creates `rick_audit_operations` keyed by `(action, request_id)` with the state machine and a pending index.
- `PostgresAuditOperationStore` writes `requested`, marks `effect_applied`, acknowledges, fails/retries and lists pending operations.
- `PostgresIdentityProvider.logout` revokes the session and marks the operation on the **same connection/transaction** when the store is bound; `consume_password_reset` does the same inside its claim/credential transaction.
- The API opens the operation before the effect, acknowledges after the projection, and marks `indeterminate` when the effect is applied but the durable outcome cannot be enrolled.
- `apps/worker/audit_reconcile.py` re-projects pending rows, acknowledges, retries and fails after the attempt budget; `--apply` is explicit, dry-run is the default.
- `Providers.audit_operations` and the external composition bind the store; no ambient connection is opened at import.

**Evidence:** [implementation-stage1.md](../../reports/evidence/auditoria-2026-10-24/implementation-stage1.md) — **6.040 Python passed, 137 skipped**, **263 web passed (91,95% lines)**, API coverage 79,22% with CONTRACT green, lint/typecheck/validate PASS. New tests cover the store, same-connection logout, reconciler and the route begin/mark/ack path.

**Residual:** live PostgreSQL/IdP and a real outbox worker are `NOT_RUN`; the reset same-transaction path is code-reviewed and covered by the identity tests but not exercised against a live claim table. AUD24-018 (typed audit-event unification) remains P2. AUD24-012/010 are **not DONE** until the live-store gate and controller acceptance.
