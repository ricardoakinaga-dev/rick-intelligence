"""Routing + registry parity + missing-auth detector (default-deny).

Three independent checks, so a route cannot drift in only one of them:

1. parity — every handler the app mounts is registered, and every registered
   entry points at a handler that exists (``app.routes`` is *not* flattened in
   FastAPI 0.141, so parity is resolved through ``routes.ROUTERS``).
2. declaration — declared permissions must exist in the policy catalog, and a
   session route without one must carry an explicit ``scope: "self"`` decision.
3. enforcement — the declared permission set must equal the set the handler
   actually enforces (static walk of the endpoint plus its declared delegation
   targets), and a live request as a session *without* those permissions must
   be denied.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import textwrap

import pytest

from core.security import COMPAT_API_KEY_PATHS, PUBLIC_ALLOWLIST
from rick_authorization import CANONICAL_PERMISSION_IDS
from routes import (
    ROUTE_REGISTRY,
    ROUTERS,
    SELF_SCOPED_PATHS,
    permission_set,
)
from routes.knowledge import ReindexRequest, RetryRequest, UploadRequest


_PROTECTED_ROUTES = [
    entry for entry in ROUTE_REGISTRY
    if (entry["method"], entry["path"]) not in (
        PUBLIC_ALLOWLIST | COMPAT_API_KEY_PATHS | {("POST", "/api/v1/auth/logout")}
    )
]
_PATH_VALUES = {
    "document_id": "doc-stub-1",
    "collection_id": "rag_phase0",
    "user_id": "vet",
    "event_id": "audit-test-1",
    "case_id": "case-test-1",
    "conversation_id": "conversation-test-1",
    "job_id": "job-test-1",
    "operation_id": "operation-test-1",
}
_WRITE_BODIES = {
    ("POST", "/api/v1/auth/sessions/revoke"): {"session_id": "session-test-1"},
    ("POST", "/api/v1/chat"): {"message": "hello"},
    ("POST", "/api/v1/cases"): {"title": "Test record", "summary": "Human record"},
    ("PATCH", "/api/v1/cases/{case_id}"): {"summary": "Updated human record"},
    ("POST", "/api/v1/cases/{case_id}/reviews"): {
        "decision": "needs_revision", "review_note": "Human review",
    },
    ("POST", "/api/v1/cases/{case_id}/feedback"): {
        "kind": "scope_note", "feedback_note": "Human feedback",
    },
    ("POST", "/api/v1/conversations"): {"title": "Test conversation"},
    ("POST", "/api/v1/conversations/{conversation_id}/archive"): None,
    ("POST", "/api/v1/search"): {"query": "reference material"},
    ("POST", "/api/v1/collections"): {"collection_id": "test-collection", "title": "Test collection"},
    ("PATCH", "/api/v1/collections/{collection_id}"): {"title": "Updated collection"},
    ("POST", "/api/v1/collections/{collection_id}/archive"): None,
    ("PUT", "/api/v1/collections/{collection_id}/grants/{user_id}"): {"granted": True},
    ("POST", "/api/v1/documents/upload"): {
        "filename": "reference.txt", "collection_id": "rag_phase0", "content": "Reference material",
    },
    ("POST", "/api/v1/ingestion/reindex"): {
        "document_id": "doc-stub-1", "filename": "reference.txt", "content": "Reference material",
    },
    ("POST", "/api/v1/ingestion/jobs/{job_id}/retry"): {
        "filename": "reference.txt", "content": "Reference material",
    },
    ("POST", "/api/v1/ingestion/jobs/{job_id}/cancel"): None,
    ("POST", "/api/v1/audit/operations/{operation_id}/reconcile"): {
        "resolution": "effect_confirmed", "evidence_ref": "evidence-ref-1",
    },
    ("POST", "/api/v1/admin/users"): {
        "email": "new-user@example.test", "role": "VETERINARIAN",
        "tenant_id": "default", "password": "test-password-123",
    },
    ("PATCH", "/api/v1/admin/users/{user_id}"): {"role": "VETERINARIAN"},
    ("POST", "/api/v1/admin/users/{user_id}/deactivate"): None,
    ("POST", "/api/v1/admin/users/{user_id}/reset-password"): {"password": "test-password-123"},
    ("POST", "/api/v1/admin/audit/{event_id}/retry"): None,
    ("POST", "/api/v1/admin/sessions/revoke"): {"session_id": "session-test-1"},
}


# Routes whose permission is enforced by a collaborator rather than in the
# endpoint body. Each entry is walked as well as the endpoint, so a declared
# permission always has a checked locus. Add a target whenever a route starts
# delegating its authorization check.
_DELEGATED_ENFORCEMENT = {
    ("POST", "/api/v1/chat"): (
        ("services.chat_service", "ChatApplicationService.chat"),
        ("services.chat_service", "ChatApplicationService.stream_events"),
    ),
    ("POST", "/api/v1/audit/operations/{operation_id}/reconcile"): (
        ("services.audit_operations", "reconcile_operation"),
    ),
}


def _mounted_handlers(app) -> dict[tuple[str, str], object]:
    """(method, path) -> route for every handler the application really mounts."""
    included = [r for r in app.routes if hasattr(r, "original_router")]
    mounted_ids = sorted(id(r.original_router) for r in included)
    declared_ids = sorted(id(router) for router in ROUTERS)
    assert mounted_ids == declared_ids, (
        "create_app must mount exactly routes.ROUTERS; policy parity is only "
        "meaningful against the routers that are actually served"
    )
    handlers: dict[tuple[str, str], object] = {}
    for router in ROUTERS:
        for route in router.routes:
            for method in getattr(route, "methods", None) or ():
                handlers[(method, route.path)] = route
    return handlers


def _permission_literals(fn) -> set[str]:
    """Permissions `fn` denies without (has_permission / require_permission)."""
    try:
        source = textwrap.dedent(inspect.getsource(fn))
        tree = ast.parse(source)
    except (OSError, TypeError, SyntaxError):
        raise AssertionError(f"cannot read enforcement source of {fn!r}") from None
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        else:
            continue
        if name not in {"has_permission", "require_permission"}:
            continue
        args = list(node.args)
        if name == "has_permission" and args:
            args = args[1:]  # has_permission(session, "x")
        if args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
            found.add(args[0].value)
        for keyword in node.keywords:
            if keyword.arg == "permission" and isinstance(keyword.value, ast.Constant):
                found.add(str(keyword.value.value))
    return found


def _resolve(module_name: str, qualname: str):
    obj = importlib.import_module(module_name)
    for part in qualname.split("."):
        obj = getattr(obj, part)
    return obj


def _enforced_permissions(key: tuple[str, str], route) -> set[str]:
    enforced = _permission_literals(route.endpoint)
    for module_name, qualname in _DELEGATED_ENFORCEMENT.get(key, ()):
        enforced |= _permission_literals(_resolve(module_name, qualname))
    return enforced


def test_registry_covers_all_app_routes(app):
    handlers = _mounted_handlers(app)
    registered = {(e["method"], e["path"]) for e in ROUTE_REGISTRY}
    mounted = set(handlers)
    missing = mounted - registered
    stale = registered - mounted
    assert not missing, f"routes mounted without registry policy: {sorted(missing)}"
    assert not stale, f"registry entries without a mounted handler: {sorted(stale)}"


def test_auth_class_matches_the_allowlists():
    for entry in ROUTE_REGISTRY:
        key = (entry["method"], entry["path"])
        auth = entry["auth"]
        if auth == "public":
            assert key in PUBLIC_ALLOWLIST, f"{key} is public but not allowlisted"
        elif auth == "api-key":
            assert key in COMPAT_API_KEY_PATHS, f"{key} is api-key but not allowlisted"
        else:
            assert auth == "session", f"{key} has unknown auth class {auth!r}"
            assert key not in PUBLIC_ALLOWLIST | COMPAT_API_KEY_PATHS, (
                f"{key} is allowlisted but declared {auth!r}"
            )


def test_every_non_public_route_has_policy():
    catalog = set(CANONICAL_PERMISSION_IDS)
    for entry in ROUTE_REGISTRY:
        key = (entry["method"], entry["path"])
        if key in PUBLIC_ALLOWLIST or key in COMPAT_API_KEY_PATHS:
            continue
        assert entry["auth"] == "session", f"{key} must require session (default-deny)"
        declared = permission_set(entry)
        unknown = declared - catalog
        assert not unknown, (
            f"{key} declares permissions the policy engine never grants: {sorted(unknown)}"
        )
        if declared:
            assert "scope" not in entry, f"{key} must not mix a permission with a scope"
        else:
            assert entry.get("scope") == "self", (
                f"{key} must declare a permission or an explicit scope='self' decision"
            )
            assert entry["path"] in SELF_SCOPED_PATHS, (
                f"{key} claims self scope but the path is not on SELF_SCOPED_PATHS"
            )


def test_public_allowlist_is_minimal():
    assert ("GET", "/health/live") in PUBLIC_ALLOWLIST
    assert ("POST", "/api/v1/auth/login") in PUBLIC_ALLOWLIST
    # Nothing under /admin may be public.
    assert not any(p.startswith("/api/v1/admin") for _, p in PUBLIC_ALLOWLIST)


def test_protected_route_payloads_match_endpoint_contracts(app):
    expected = {
        (entry["method"], entry["path"]) for entry in _PROTECTED_ROUTES
        if entry["method"] in {"POST", "PUT", "PATCH"}
    }
    assert set(_WRITE_BODIES) == expected
    for key, route in _mounted_handlers(app).items():
        if key not in _WRITE_BODIES:
            continue
        body = _WRITE_BODIES[key]
        field = getattr(route, "body_field", None)
        if field is not None:
            _, errors = field.validate(body, {}, loc=("body",))
            assert not errors, f"{key}: {errors}"
        elif key == ("POST", "/api/v1/documents/upload"):
            UploadRequest.model_validate(body)
        elif key == ("POST", "/api/v1/ingestion/reindex"):
            ReindexRequest.model_validate(body)
        elif key == ("POST", "/api/v1/ingestion/jobs/{job_id}/retry"):
            RetryRequest.model_validate(body)
        else:
            assert body is None, f"{key} has no declared body contract"


@pytest.mark.parametrize("entry", _PROTECTED_ROUTES, ids=lambda entry: f'{entry["method"]} {entry["path"]}')
def test_protected_routes_reject_anonymous(client, entry):
    key = (entry["method"], entry["path"])
    path = entry["path"].format(**_PATH_VALUES)
    body = _WRITE_BODIES.get(key)
    kwargs = {"json": body} if body is not None else {}
    resp = client.request(entry["method"], path, **kwargs)
    assert resp.status_code == 401, f"{entry} anonymous got {resp.status_code}: {resp.text}"


@pytest.mark.parametrize("entry", _PROTECTED_ROUTES, ids=lambda entry: f'{entry["method"]} {entry["path"]}')
def test_declared_permission_is_what_the_handler_enforces(app, entry):
    """The registry and the code must name the same permissions — no more, no less."""
    key = (entry["method"], entry["path"])
    route = _mounted_handlers(app)[key]
    declared = permission_set(entry)
    if entry.get("scope") == "self":
        declared = frozenset()
    enforced = _enforced_permissions(key, route)
    assert declared == enforced, (
        f"{key} declares {sorted(declared)} but the handler enforces {sorted(enforced)}"
    )


@pytest.mark.parametrize("entry", _PROTECTED_ROUTES, ids=lambda entry: f'{entry["method"]} {entry["path"]}')
def test_session_route_denies_a_session_without_its_permission(client, entry):
    """Live proof: the declared permission is required, not merely documented."""
    from conftest import login_as

    key = (entry["method"], entry["path"])
    login_as(client, "vet@example.com")
    held = frozenset(client.get("/api/v1/auth/me").json()["permissions"])
    declared = permission_set(entry)
    if entry.get("scope") == "self":
        declared = frozenset()
    must_deny = bool(declared - held)

    body = _WRITE_BODIES.get(key)
    if key == ("POST", "/api/v1/auth/sessions/revoke"):
        # Self scope: probe the caller's own session, never a foreign one.
        items = client.get("/api/v1/auth/sessions").json()["items"]
        assert items, "the caller must be able to list their own sessions"
        body = {"session_id": items[0]["session_id"]}
    kwargs = {"json": body} if body is not None else {}
    resp = client.request(entry["method"], entry["path"].format(**_PATH_VALUES), **kwargs)
    if must_deny:
        assert resp.status_code == 403, (
            f"{key} must deny {sorted(declared - held)} for this session, got "
            f"{resp.status_code}: {resp.text}"
        )
    else:
        assert resp.status_code != 403, (
            f"{key} declared {sorted(declared)} which this session holds, got 403: {resp.text}"
        )


def test_self_scoped_routes_serve_the_caller_and_refuse_foreign_targets(client):
    """`scope: "self"` is an explicit decision, and the boundary it names is real."""
    from conftest import login_as

    login_as(client, "vet@example.com")
    held = frozenset(client.get("/api/v1/auth/me").json()["permissions"])
    for entry in ROUTE_REGISTRY:
        if entry.get("scope") != "self":
            continue
        key = (entry["method"], entry["path"])
        if key in {("POST", "/api/v1/auth/logout"), ("POST", "/api/v1/auth/sessions/revoke")}:
            continue  # both invalidate the session; covered below
        resp = client.request(entry["method"], entry["path"].format(**_PATH_VALUES))
        assert resp.status_code != 403, f"{key} refused its own caller: {resp.text}"
        assert permission_set(entry) == frozenset()

    # The same route must refuse a target outside the caller's own scope.
    foreign_session = client.post(
        "/api/v1/auth/sessions/revoke", json={"session_id": "session-test-1"}
    )
    assert foreign_session.status_code == 403, foreign_session.text
    foreign_user = client.post("/api/v1/auth/sessions/revoke", json={"user_id": "admin"})
    assert foreign_user.status_code == 403, foreign_user.text
    assert "sessions.revoke" not in held  # the denial is a scope decision, not a role gap


def test_self_service_session_routes_work_for_the_caller(client):
    from conftest import login_as

    login_as(client, "vet@example.com")
    own = client.get("/api/v1/auth/sessions").json()["items"][0]["session_id"]
    revoked = client.post("/api/v1/auth/sessions/revoke", json={"session_id": own})
    assert revoked.status_code != 403, revoked.text
    assert revoked.status_code == 200, revoked.text

    login_as(client, "vet@example.com")
    logout = client.post("/api/v1/auth/logout")
    assert logout.status_code != 403, logout.text
    assert logout.status_code == 200, logout.text
    assert client.get("/api/v1/auth/me").status_code == 401
