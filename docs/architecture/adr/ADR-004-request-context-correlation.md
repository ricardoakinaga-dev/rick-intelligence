# ADR-004 — RequestContext and correlation IDs

Date: 2026-09-03. Status: Accepted.

Every request gets `request_id`; client `X-Correlation-ID` is preserved only if
≤128 chars and charset `[A-Za-z0-9-_:.]`, else regenerated. `RequestContext`
carries server-derived identity only (never raw framework objects downstream)
and propagates to logs/audit/provider/retrieval/Professor/jobs. `X-Request-ID`
echoed on all responses including errors.
