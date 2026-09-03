# ADR-010 — Canonical authorization source of truth

Date: 2026-09-03. Status: Accepted.

`packages/authorization` (`rick_authorization`, stdlib only) owns roles, the
permission registry, aliases, overrides, effective resolution, wildcard
semantics, workspace/collection scope and `RetrievalContext`. It imports nothing
legacy. `apps/api` services/dependencies delegate with authoritative semantics;
static tests fail CI on duplicate registries, role-string comparisons in routes,
or role-fallback code. Parity with preserved CVG semantics is proven by a
read-only differential suite, not by copying policy.
