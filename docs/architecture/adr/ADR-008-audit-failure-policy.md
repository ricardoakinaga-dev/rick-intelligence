# ADR-008 — Audit failure policy

Date: 2026-09-03. Status: Accepted (with follow-up); amended by [ADR-024](ADR-024-audit-outcome-and-revocation-ordering.md) for logout/password-reset ordering (2026-10-24).

Phase 1.3: audit emission is best-effort — a sink failure is logged server-side
and never breaks the request path (availability over blocking on telemetry).
Rationale: the current sink is in-process/memory; fail-closed would turn every
telemetry hiccup into a platform outage.

Follow-up (before production promotion): security-critical admin mutations
(user/role create/update/delete, session revoke-all, document delete, reindex,
config changes) move to fail-closed (return 503 when the durable audit write
fails). Recorded as a Phase 1.4 promotion prerequisite, not silently dropped.


## Amendment — 2026-10-24

[ADR-024](ADR-024-audit-outcome-and-revocation-ordering.md) preserves the fail-closed requirement at the durable operation-record level and moves external sink delivery to an acknowledged, reconciled projection. For logout and password reset, the effect must not depend on sink availability; an unconfirmed acknowledgement returns `503 result_indeterminate` and never claims `signed_out`/`completed`.
