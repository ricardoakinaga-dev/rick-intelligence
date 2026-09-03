# ADR-006 — OpenAI compatibility strategy

Date: 2026-09-03. Status: Accepted.

Compat is an adapter over `ChatApplicationService`, not a fork. Deviations are
explicit: `usage:null` (never fabricated), metadata-only citations, constant-time
key comparison, keys via server config. The old isolated Professor server stays
as the migration surface until dual verification + caller switch complete; no
second chat implementation is maintained.
