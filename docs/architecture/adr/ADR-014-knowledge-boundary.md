# ADR-014 — Knowledge domain boundary

Date: 2026-09-03. Status: Accepted.

`rick_knowledge` owns document/chunk/collection models, stable identity, payload
schema and lifecycle — no I/O, no access decisions. Access stays in
`packages/authorization`; retrieval filters at query time. Rationale: identity
and schema must be computable offline (idempotency, drift checks, tests) while
enforcement stays request-scoped.
