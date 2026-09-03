# ADR-008 — Audit failure policy

Date: 2026-09-03. Status: Accepted (with follow-up).

Phase 1.3: audit emission is best-effort — a sink failure is logged server-side
and never breaks the request path (availability over blocking on telemetry).
Rationale: the current sink is in-process/memory; fail-closed would turn every
telemetry hiccup into a platform outage.

Follow-up (before production promotion): security-critical admin mutations
(user/role create/update/delete, session revoke-all, document delete, reindex,
config changes) move to fail-closed (return 503 when the durable audit write
fails). Recorded as a Phase 1.4 promotion prerequisite, not silently dropped.
