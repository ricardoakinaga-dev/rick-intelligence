# Controlled clinical-case boundary

REC-27 provides a deliberately narrow local surface for human-authored case
records, structured hypotheses, evidence references, human review, and
auditable feedback. The API and web console do not generate or persist a
diagnosis, prescription, recommendation, or other clinical conclusion.

The route is closed by default. Both `RICK_CLINICAL_CASES_ENABLED` and
`RICK_CLINICAL_CASES_D04_ENABLED` must be true before the application creates a
case store. The second flag represents the D04 decision: approved data scope,
permitted corpus, review thresholds, and a responsible domain owner. A single
flag or a missing store returns an explicit disabled or unavailable response.

Tenant, workspace, and owner scope come from the authenticated session. HTTP
payloads cannot choose those values. Case records and review/feedback events
carry the contract version, request identifier, actor, and scope fields. A
mutation first persists an audit intent and only then writes the case store;
the caller can repeat it safely with the same `Idempotency-Key` or
`X-Request-ID`. The SQLite adapter is a restart-safe local test adapter; it
is not production clinical persistence.

Evidence entries are references supplied by a human caller. The module does
not fetch, retrieve, interpret, or rank their contents. Agent and model
entries are metadata-only catalog records with an explicit purpose; the case
routes never invoke them. The web surface states these limits and leaves the
catalog unconfigured when no authorized deployment catalog is injected.

Local verification covers the disabled gate, strict contracts, scope
isolation, structured record persistence, restart round-trip, review,
feedback, audit events, catalog metadata, and the permission-aware web
surface. Clinical quality acceptance remains open until D04 supplies the
approved cases, corpus, thresholds, and domain review evidence.
