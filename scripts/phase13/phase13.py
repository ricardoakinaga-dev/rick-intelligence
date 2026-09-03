#!/usr/bin/env python3
"""Phase 1.3 API lanes: test / contract(OpenAPI) / security / dev / benchmark."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
API_TESTS = ROOT / "apps" / "api" / "tests"
CONTRACTS_SRC = ROOT / "packages" / "contracts" / "src"


def _env():
    import os

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{API_SRC}{os.pathsep}{CONTRACTS_SRC}{os.pathsep}{env.get('PYTHONPATH', '')}"
    env.setdefault("RAG_SKIP_QDRANT_BOOTSTRAP", "1")
    env.setdefault("SESSION_COOKIE_SECURE", "false")
    return env


def _run(cmd, **kwargs):
    print(f"==> {' '.join(cmd)}", flush=True)
    completed = subprocess.run(cmd, cwd=ROOT, env=_env(), **kwargs)
    print(f"<== exit {completed.returncode}", flush=True)
    return completed.returncode


def mode_test() -> int:
    return _run([sys.executable, "-m", "pytest", "-q", str(API_TESTS)])


def mode_security() -> int:
    return _run([sys.executable, "-m", "pytest", "-q",
                 str(API_TESTS / "test_route_policy.py"), str(API_TESTS / "test_negative_security.py"),
                 str(API_TESTS / "test_import_boundary.py"), str(API_TESTS / "test_http_contract.py")])


def mode_contract() -> int:
    code = _run([sys.executable, "scripts/phase13/generate_openapi.py"])
    if code != 0:
        return code
    schema = ROOT / "apps" / "api" / "openapi.json"
    if not schema.is_file():
        print("openapi.json not generated", flush=True)
        return 1
    data = json.loads(schema.read_text())
    paths = data.get("paths", {})
    required = ["/health/live", "/health/ready", "/api/v1/auth/login", "/api/v1/chat", "/v1/chat/completions"]
    missing = [p for p in required if p not in paths]
    if missing:
        print(f"OpenAPI missing paths: {missing}", flush=True)
        return 1
    print(f"OpenAPI OK: {len(paths)} paths", flush=True)
    return 0


def mode_dev() -> int:
    print("RICK API dev: PYTHONPATH=apps/api/src:packages/contracts/src", flush=True)
    print("Hermetic default; legacy mode: RICK_API_USE_LEGACY=1 (needs Qdrant/Redis/provider).", flush=True)
    return _run([sys.executable, "-m", "uvicorn", "main:app", "--app-dir", str(API_SRC), "--port", "8000"])


def mode_benchmark() -> int:
    """Kernel-overhead observation: direct service vs HTTP adapter (stub backend, local)."""
    import os

    sys.path.insert(0, str(API_SRC))
    sys.path.insert(0, str(CONTRACTS_SRC))
    import asyncio

    from fastapi.testclient import TestClient

    from app import create_app
    from core.config import ApiSettings
    from dependencies.services import Providers
    from services.audit import InMemoryAuditSink
    from services.chat_service import ChatApplicationService, StubChatBackend
    from services.identity_service import InMemoryIdentityProvider

    settings = ApiSettings(cors_allowed_origins=("http://localhost:3000",), session_cookie_secure=False)
    providers = Providers(settings=settings, identity=InMemoryIdentityProvider(), chat_backend=StubChatBackend(),
                          health_checks={}, audit_sink=InMemoryAuditSink())
    app = create_app(settings, providers)
    client = TestClient(app, raise_server_exceptions=False)
    client.post("/api/v1/auth/login", json={"email": "vet@example.com", "password": "password123", "tenant_id": "default"})

    service = ChatApplicationService(StubChatBackend())
    # Warm up through HTTP to resolve session cookie path.
    lat_http: list[float] = []
    for _ in range(20):
        start = time.perf_counter()
        resp = client.post("/api/v1/chat", json={"message": "benchmark probe"})
        assert resp.status_code == 200
        lat_http.append((time.perf_counter() - start) * 1000)

    async def direct_once():
        identity = providers.identity
        token = next(iter(identity._sessions))
        sess = identity.validate_token(token)
        t0 = time.perf_counter()
        await service.chat(session=sess, message="benchmark probe", conversation_id=None,
                           collection_id=None, workspace_id="default", mode="grounded")
        return (time.perf_counter() - t0) * 1000

    lat_direct = sorted([asyncio.run(direct_once()) for _ in range(20)])
    lat_http_sorted = sorted(lat_http)

    def pct(data, p):
        return data[min(len(data) - 1, int(p * len(data)))]

    result = {
        "http_adapter_ms": {"p50": round(pct(lat_http_sorted, 0.5), 3), "p95": round(pct(lat_http_sorted, 0.95), 3)},
        "direct_service_ms": {"p50": round(pct(lat_direct, 0.5), 3), "p95": round(pct(lat_direct, 0.95), 3)},
        "note": "stub backend, local, hermetic; provider/Qdrant excluded",
    }
    out = ROOT / "docs" / "baselines" / "phase-1.3-api-overhead.json"
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2), flush=True)
    return 0


MODES = {"test": mode_test, "security": mode_security, "contract": mode_contract, "dev": mode_dev, "benchmark": mode_benchmark}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in MODES:
        print(f"usage: phase13.py <{'|'.join(sorted(MODES))}>", flush=True)
        return 2
    return MODES[argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
