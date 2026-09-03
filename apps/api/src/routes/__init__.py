"""Single explicit route registry — no import-side-effect registration elsewhere.

Tests enumerate this registry to enforce default-deny + explicit public allowlist.
"""

from __future__ import annotations

from routes import admin, auth, chat, compatibility_openai, health, knowledge, sessions

ROUTERS = [health.router, auth.router, sessions.router, chat.router, knowledge.router, admin.router, compatibility_openai.router]

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
    {"method": "GET", "path": "/api/v1/history", "auth": "session", "permission": "history.read"},
    {"method": "GET", "path": "/api/v1/sources", "auth": "session", "permission": "sources.read"},
    {"method": "GET", "path": "/api/v1/collections", "auth": "session", "permission": "collections.read"},
    {"method": "GET", "path": "/api/v1/documents", "auth": "session", "permission": "documents.read"},
    {"method": "GET", "path": "/api/v1/documents/{document_id}", "auth": "session", "permission": "documents.read"},
    {"method": "POST", "path": "/api/v1/documents/upload", "auth": "session", "permission": "documents.upload"},
    {"method": "POST", "path": "/api/v1/ingestion/reindex", "auth": "session", "permission": "reindex.run"},
    {"method": "GET", "path": "/api/v1/admin/users", "auth": "session", "permission": "users.manage"},
    {"method": "POST", "path": "/api/v1/admin/users", "auth": "session", "permission": "users.manage"},
    {"method": "GET", "path": "/api/v1/admin/sessions", "auth": "session", "permission": "sessions.revoke"},
    {"method": "POST", "path": "/api/v1/admin/sessions/revoke", "auth": "session", "permission": "sessions.revoke"},
    {"method": "GET", "path": "/api/v1/admin/roles", "auth": "session", "permission": "users.manage"},
    {"method": "GET", "path": "/api/v1/admin/jobs", "auth": "session", "permission": "runtime.manage"},
    {"method": "GET", "path": "/api/v1/admin/audit", "auth": "session", "permission": "audit.read"},
    {"method": "GET", "path": "/api/v1/admin/health", "auth": "session", "permission": "observability.read"},
    {"method": "GET", "path": "/api/v1/admin/system", "auth": "session", "permission": "runtime.manage"},
    {"method": "GET", "path": "/v1/models", "auth": "api-key", "permission": None},
    {"method": "POST", "path": "/v1/chat/completions", "auth": "api-key", "permission": None},
]
