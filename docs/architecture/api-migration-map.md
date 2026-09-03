# API Migration Map (Phase 1.3)

States: `LEGACY_ONLY` | `DUAL` | `ROOT_CANONICAL` | `DEPRECATED_LEGACY` | `REMOVED`.
Rollback: re-point callers to the legacy path; no legacy code is deleted in 1.3.

| Legacy endpoint | New endpoint | Owner | Adapter | Auth | Permission | Compat | State |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `POST /auth/login` (CVG) | `POST /api/v1/auth/login` | identity | InMemory / LegacyCVGIdentity (opt-in) | public+rate-limit | — | same semantics, bearer stays cookie-only | DUAL |
| `GET /session`, `GET /auth/me` | `GET /api/v1/session`, `GET /api/v1/auth/me` | identity | same | session | session:self | `session_token:null` preserved | DUAL |
| `GET /health` (CVG, auth) | `GET /health/live`, `GET /health/ready` | kernel | health checks | public minimal | — | legacy full payload stays legacy-only | DUAL |
| `GET /admin/users` etc. | `GET /api/v1/admin/users` (+roles/sessions/jobs/audit/system) | admin | skeleton → legacy (1.4) | session | users.manage / sessions.revoke / runtime.manage / audit.read | list shapes simplified | DUAL |
| `GET /admin/runtime` | `GET /api/v1/admin/system`, `GET /api/v1/admin/health` | admin | skeleton | session | runtime.manage / observability.read | executive score deferred | DUAL |
| `GET /documents`, `GET /documents/{id}` | `GET /api/v1/documents*` | knowledge | skeleton + LegacyCVGDocument (opt-in) | session | documents.read | ACL-filtered; upload/reindex queued stubs | DUAL |
| `POST /documents/upload` | `POST /api/v1/documents/upload` | knowledge | skeleton (heavy behavior legacy) | session | documents.upload | validation only in 1.3 | DUAL |
| `POST /search`, `POST /query` | `POST /api/v1/chat` (+history/sources) | chat | StubChat / LegacyProfessor (opt-in) | session | chat.query/sources.read | platform contract frozen (`packages/contracts`) | DUAL |
| `POST /v1/chat/completions` (Professor) | `POST /v1/chat/completions` (canonical adapter) | compat | ChatApplicationService | api-key | — | stream true/false, model mapping, `usage:null` (documented) | DUAL |
| `POST /webhook/telegram` | LEGACY_ONLY (surfaced later w/ secret+idempotency+limits) | — | — | webhook secret | — | unchanged | LEGACY_ONLY |
| `POST /lock|/unlock|/renew` (Locker) | LEGACY_ONLY (internal service) | — | — | private net | — | unchanged | LEGACY_ONLY |
| `POST /external/chat` (X-API-Key) | DUAL via compat key domain (server-bound scope) | compat | ChatApplicationService | api-key | server scope | collection allowlist enforced | DUAL |

Low-risk-first order followed: health → auth/session → collections → admin skeletons →
chat/compat; upload/ingestion migrated last (stubs in 1.3).
