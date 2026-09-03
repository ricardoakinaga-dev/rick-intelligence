# ADR-009 — Canonical identity source of truth

Date: 2026-09-03. Status: Accepted.

`packages/identity` (`rick_identity`) owns user/session lifecycle: credential
verification, session issue/lookup/expiry/revocation, disabled-user and
password/role-version invalidation, authoritative snapshot persistence, one-time
legacy migration. `apps/api` keeps a thin provider-selection facade (mode-gated
verifiers, demo seed DATA) and route orchestration only. Legacy CVG session code
stays byte-identical until per-route dual verification justifies a facade switch.
