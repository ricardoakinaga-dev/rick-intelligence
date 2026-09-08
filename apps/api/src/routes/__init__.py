"""Single explicit route registry — no import-side-effect registration elsewhere.

Tests enumerate this registry to enforce default-deny + explicit public allowlist.
"""

from __future__ import annotations

from routes import admin, auth, cases, chat, compatibility_openai, health, knowledge, search, sessions

ROUTERS = [health.router, auth.router, sessions.router, chat.router, cases.router, knowledge.router, search.router, admin.router, compatibility_openai.router]

# (method, path) -> policy. Public entries require no session; compat entries require API key.
ROUTE_REGISTRY: list[dict] = [
    {"method": "GET", "path": "/health/live", "auth": "public", "permission": None},
    {"method": "GET", "path": "/health/ready", "auth": "public", "permission": None},
    {"method": "POST", "path": "/api/v1/auth/login", "auth": "public", "permission": None},
    {"method": "POST", "path": "/api/v1/auth/recovery", "auth": "public", "permission": None},
    {"method": "POST", "path": "/api/v1/auth/request-password-reset", "auth": "public", "permission": None},
    {"method": "POST", "path": "/api/v1/auth/confirm-password-reset", "auth": "public", "permission": None},
    {"method": "POST", "path": "/api/v1/auth/logout", "auth": "session", "permission": "session:self"},
    {"method": "GET", "path": "/api/v1/auth/me", "auth": "session", "permission": "session:self"},
    {"method": "GET", "path": "/api/v1/session", "auth": "session", "permission": "session:self"},
    {"method": "GET", "path": "/api/v1/auth/sessions", "auth": "session", "permission": "session:self"},
    {"method": "POST", "path": "/api/v1/auth/sessions/revoke", "auth": "session", "permission": "session:self"},
    {"method": "POST", "path": "/api/v1/chat", "auth": "session", "permission": "chat.query"},
    {"method": "GET", "path": "/api/v1/cases/catalog/agents", "auth": "session", "permission": "cases.read"},
    {"method": "POST", "path": "/api/v1/cases", "auth": "session", "permission": "cases.manage"},
    {"method": "GET", "path": "/api/v1/cases", "auth": "session", "permission": "cases.read"},
    {"method": "GET", "path": "/api/v1/cases/{case_id}", "auth": "session", "permission": "cases.read"},
    {"method": "PATCH", "path": "/api/v1/cases/{case_id}", "auth": "session", "permission": "cases.manage"},
    {"method": "POST", "path": "/api/v1/cases/{case_id}/reviews", "auth": "session", "permission": "cases.review"},
    {"method": "POST", "path": "/api/v1/cases/{case_id}/feedback", "auth": "session", "permission": "cases.feedback"},
    {"method": "POST", "path": "/api/v1/conversations", "auth": "session", "permission": "history.read"},
    {"method": "GET", "path": "/api/v1/conversations", "auth": "session", "permission": "history.read"},
    {"method": "GET", "path": "/api/v1/conversations/{conversation_id}", "auth": "session", "permission": "history.read"},
    {"method": "POST", "path": "/api/v1/conversations/{conversation_id}/archive", "auth": "session", "permission": "history.read"},
    {"method": "POST", "path": "/api/v1/search", "auth": "session", "permission": "sources.read"},
    {"method": "GET", "path": "/api/v1/history", "auth": "session", "permission": "history.read"},
    {"method": "GET", "path": "/api/v1/sources", "auth": "session", "permission": "sources.read"},
    {"method": "GET", "path": "/api/v1/collections", "auth": "session", "permission": "collections.read"},
    {"method": "POST", "path": "/api/v1/collections", "auth": "session", "permission": "collections.manage"},
    {"method": "PATCH", "path": "/api/v1/collections/{collection_id}", "auth": "session", "permission": "collections.manage"},
    {"method": "POST", "path": "/api/v1/collections/{collection_id}/archive", "auth": "session", "permission": "collections.manage"},
    {"method": "PUT", "path": "/api/v1/collections/{collection_id}/grants/{user_id}", "auth": "session", "permission": "collections.manage"},
    {"method": "GET", "path": "/api/v1/documents", "auth": "session", "permission": "documents.read"},
    {"method": "GET", "path": "/api/v1/documents/{document_id}", "auth": "session", "permission": "documents.read"},
    {"method": "DELETE", "path": "/api/v1/documents/{document_id}", "auth": "session", "permission": "documents.manage"},
    {"method": "POST", "path": "/api/v1/documents/upload", "auth": "session", "permission": "documents.upload"},
    {"method": "POST", "path": "/api/v1/ingestion/reindex", "auth": "session", "permission": "reindex.run"},
    {"method": "GET", "path": "/api/v1/ingestion/jobs/{job_id}", "auth": "session", "permission": "ingestion.run"},
    {"method": "POST", "path": "/api/v1/ingestion/jobs/{job_id}/retry", "auth": "session", "permission": "ingestion.run"},
    {"method": "POST", "path": "/api/v1/ingestion/jobs/{job_id}/cancel", "auth": "session", "permission": "ingestion.run"},
    {"method": "GET", "path": "/api/v1/admin/users", "auth": "session", "permission": "users.manage"},
    {"method": "POST", "path": "/api/v1/admin/users", "auth": "session", "permission": "users.manage"},
    {"method": "PATCH", "path": "/api/v1/admin/users/{user_id}", "auth": "session", "permission": "users.manage"},
    {"method": "POST", "path": "/api/v1/admin/users/{user_id}/deactivate", "auth": "session", "permission": "users.manage"},
    {"method": "POST", "path": "/api/v1/admin/users/{user_id}/reset-password", "auth": "session", "permission": "users.manage"},
    {"method": "GET", "path": "/api/v1/admin/sessions", "auth": "session", "permission": "sessions.revoke"},
    {"method": "POST", "path": "/api/v1/admin/sessions/revoke", "auth": "session", "permission": "sessions.revoke"},
    {"method": "GET", "path": "/api/v1/admin/roles", "auth": "session", "permission": "users.manage"},
    {"method": "GET", "path": "/api/v1/admin/jobs", "auth": "session", "permission": "runtime.manage"},
    {"method": "GET", "path": "/api/v1/admin/audit", "auth": "session", "permission": "audit.read"},
    {"method": "GET", "path": "/api/v1/admin/health", "auth": "session", "permission": "observability.read"},
    {"method": "GET", "path": "/api/v1/admin/metrics", "auth": "session", "permission": "observability.read"},
    {"method": "GET", "path": "/api/v1/admin/metrics/prometheus", "auth": "session", "permission": "observability.read"},
    {"method": "GET", "path": "/api/v1/admin/system", "auth": "session", "permission": "runtime.manage"},
    {"method": "GET", "path": "/v1/models", "auth": "api-key", "permission": None},
    {"method": "POST", "path": "/v1/chat/completions", "auth": "api-key", "permission": None},
]
