# ADR-013 — Application facade boundary

Date: 2026-09-03. Status: Accepted.

`apps/api` services/dependencies are orchestration facades: extract credentials,
resolve sessions, bind `RequestContext`, delegate decisions, translate
`AuthorizationError`→`ApiError`. They define no roles, registries, aliases, or
grants; `models.SessionSnapshot` is a re-export of the canonical contract
(drift-tested). Cookie-wins precedence and transport rate-limit buckets remain
app-level concerns because they are HTTP transport, not authorization policy.
