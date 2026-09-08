"""Differential equivalence: legacy CVG auth vs canonical root vs observed API.

Legacy files stay byte-identical; tests import the legacy module read-only
(tests are an allowed legacy consumer) and compare decisions on identical inputs.
"""

import importlib.util as _importlib_util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for _pkg in ("contracts", "authorization", "identity"):
    _p = ROOT / "packages" / _pkg / "src"
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load_legacy_authorization():
    """Load the preserved legacy module read-only by file path (never alters it).

    importlib file loading avoids the `services` package-name collision with
    apps/api/src/services on sys.path. The legacy module's own
    `from services.rag_contract import ...` is satisfied by briefly giving the
    legacy src priority while purging the app-side `services` package from the
    import cache (restored afterwards).
    """
    name = "legacy_cvg_authorization_ro"
    if name in sys.modules:
        return sys.modules[name]
    legacy_src = str(ROOT / "cvg-master-rag-v2" / "src")
    saved_path = list(sys.path)
    saved_services = {key: value for key, value in sys.modules.items()
                      if key == "services" or key.startswith("services.")}
    sys.modules.pop("services", None)
    sys.modules.pop("services.rag_contract", None)
    try:
        sys.path.insert(0, legacy_src)
        spec = _importlib_util.spec_from_file_location(
            name, ROOT / "cvg-master-rag-v2" / "src" / "services" / "authorization.py")
        module = _importlib_util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = saved_path
        for key in [k for k in sys.modules if k == "services" or k.startswith("services.")]:
            if key not in (name,):
                sys.modules.pop(key, None)
        # Restore the entire prior package cache, not just its root. Otherwise
        # later tests import new class identities while routes keep old ones.
        sys.modules.update(saved_services)


legacy = _load_legacy_authorization()
CASE_PERMISSION_EXTENSION = {"cases.feedback", "cases.manage", "cases.read", "cases.review"}


def _legacy_compatible_permissions(value):
    """The canonical policy may add new bounded scopes absent from the frozen legacy module."""
    return sorted(set(value) - CASE_PERMISSION_EXTENSION)

import rick_authorization as canonical  # noqa: E402


def test_legacy_loader_preserves_existing_service_modules(monkeypatch):
    from types import ModuleType
    sentinel = ModuleType("services._preservation_probe")
    monkeypatch.setitem(sys.modules, "services._preservation_probe", sentinel)
    monkeypatch.delitem(sys.modules, "legacy_cvg_authorization_ro", raising=False)
    before = {key: value for key, value in sys.modules.items()
              if key == "services" or key.startswith("services.")}
    _load_legacy_authorization()
    after = {key: value for key, value in sys.modules.items()
             if key == "services" or key.startswith("services.")}
    assert after == before


def test_role_alias_parity():
    aliases = ["admin", "super_admin", "platform_admin", "admin_rag", "operator",
               "knowledge_manager", "viewer", "veterinarian", "auditor",
               "ADMIN", " Viewer ", None, "nonsense"]
    for alias in aliases:
        assert canonical.canonical_role(alias) == legacy.canonical_role(alias), alias


def test_base_permission_parity():
    for role in ("PLATFORM_ADMIN", "KNOWLEDGE_MANAGER", "VETERINARIAN",
                 "admin", "operator", "viewer"):
        assert _legacy_compatible_permissions(canonical.permissions_for_role(role)) == \
            _legacy_compatible_permissions(legacy.permissions_for_role(role)), role


def test_override_and_wildcard_parity():
    cases = [
        {"add": ["documents.read"], "remove": []},
        {"add": [], "remove": ["documents.read"]},
        {"add": ["documents.read"], "remove": ["documents.read"]},
        {"add": [], "remove": ["*"]},
        {"add": ["chat.query"], "remove": ["*"]},
        {"add": ["search.execute"], "remove": ["users.manage", "users.manage"]},
        {"add": "chat.query", "remove": "documents.read"},
        None, "garbage", {},
    ]
    roles = ["PLATFORM_ADMIN", "KNOWLEDGE_MANAGER", "VETERINARIAN", "viewer"]
    for role in roles:
        for overrides in cases:
            assert _legacy_compatible_permissions(canonical.permissions_for_role(role, overrides)) == \
                    _legacy_compatible_permissions(legacy.permissions_for_role(role, overrides)), (role, overrides)


def test_authoritative_check_parity():
    snapshots = [[], ["chat.query"], ["*"], ["chat.query", "sources.read"]]
    for role in ("PLATFORM_ADMIN", "KNOWLEDGE_MANAGER", "VETERINARIAN"):
        for snap in snapshots:
            for required in ("chat.query", "documents.read", "users.manage", "sources.read"):
                assert canonical.permission_granted(role=role, permissions=snap, required=required, authoritative=True) == \
                    legacy.permission_granted(role=role, permissions=snap, required=required, authoritative=True), \
                    (role, snap, required)


def test_collection_grant_parity():
    users = [
        {"role": "VETERINARIAN"},
        {"role": "viewer", "authorized_collection_ids": ["rag_phase0"]},
        {"role": "KNOWLEDGE_MANAGER"},
        {"role": "PLATFORM_ADMIN", "authorized_collection_ids": ["a", "b"]},
        {"role": "admin", "authorized_collection_ids": ["*"]},
        {"role": "veterinarian", "authorized_collection_ids": ["rickvet_documents"]},
    ]
    for user in users:
        assert canonical.allowed_collection_ids_for_user(user) == \
            legacy.allowed_collection_ids_for_user(user), user


def test_observed_api_matches_canonical():
    """Spot-check the running API against the canonical engine (same inputs, same decision)."""
    from conftest import login_as

    from fastapi.testclient import TestClient

    from app import create_app
    from conftest import make_settings
    from dependencies.services import Providers
    from services.audit import InMemoryAuditSink
    from services.chat_service import StubChatBackend
    from services.identity_service import InMemoryIdentityProvider

    settings = make_settings()
    providers = Providers(settings=settings, identity=InMemoryIdentityProvider(),
                          chat_backend=StubChatBackend(), health_checks={}, audit_sink=InMemoryAuditSink())
    client = TestClient(create_app(settings, providers), raise_server_exceptions=False)
    login_as(client, "vet@example.com")
    # VET: sources allowed, documents denied — matches canonical engine directly.
    assert client.get("/api/v1/sources").status_code == 200
    assert client.get("/api/v1/documents").status_code == 403
    assert canonical.permission_granted(role=None, permissions=["chat.query", "history.read", "sources.read", "collections.read"],
                                        required="sources.read", authoritative=True)
    assert not canonical.permission_granted(role=None, permissions=["chat.query", "history.read", "sources.read", "collections.read"],
                                            required="documents.read", authoritative=True)
