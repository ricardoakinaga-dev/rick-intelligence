"""Routing + registry parity + missing-auth detector (default-deny)."""

from core.security import COMPAT_API_KEY_PATHS, PUBLIC_ALLOWLIST
from routes import ROUTE_REGISTRY


def test_registry_covers_all_app_routes(app):
    paths = {(r.methods and sorted(r.methods)[0], r.path) for r in app.routes if hasattr(r, "path") and r.path.startswith(("/api/", "/health", "/v1/"))}
    registered = {(e["method"], e["path"]) for e in ROUTE_REGISTRY}
    missing = paths - registered
    assert not missing, f"routes mounted without registry policy: {missing}"


def test_every_non_public_route_has_policy():
    for entry in ROUTE_REGISTRY:
        key = (entry["method"], entry["path"])
        if key in PUBLIC_ALLOWLIST or key in COMPAT_API_KEY_PATHS:
            continue
        assert entry["auth"] == "session", f"{key} must require session (default-deny)"
        assert entry["permission"], f"{key} must declare a permission"


def test_public_allowlist_is_minimal():
    assert ("GET", "/health/live") in PUBLIC_ALLOWLIST
    assert ("POST", "/api/v1/auth/login") in PUBLIC_ALLOWLIST
    # Nothing under /admin may be public.
    assert not any(p.startswith("/api/v1/admin") for _, p in PUBLIC_ALLOWLIST)


def test_protected_routes_reject_anonymous(client):
    # POST /api/v1/auth/logout is intentionally idempotent (safe exception):
    # it clears any cookie and returns signed_out even without a session.
    safe_idempotent = {("POST", "/api/v1/auth/logout")}
    for entry in ROUTE_REGISTRY:
        if (entry["method"], entry["path"]) in PUBLIC_ALLOWLIST or (entry["method"], entry["path"]) in COMPAT_API_KEY_PATHS:
            continue
        if (entry["method"], entry["path"]) in safe_idempotent:
            continue
        path = entry["path"].replace("{document_id}", "doc-stub-1")
        method = entry["method"].lower()
        kwargs = {}
        if method in ("post", "put", "patch"):
            kwargs["json"] = {"message": "hi", "filename": "x.pdf", "collection_id": "rag_phase0",
                              "email": "a@b.c", "role": "VETERINARIAN"}
        resp = getattr(client, method)(path, **kwargs)
        assert resp.status_code in (401, 403, 422), f"{entry} anonymous got {resp.status_code}"
