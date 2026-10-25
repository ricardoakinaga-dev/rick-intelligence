"""Owned, disposable product scopes and HTTP processes for formal lab gates.

All persistence is real. The only fixture is the explicitly selected local
embedding/citation provider. No production capability or identity-policy
approval is inferred from using the native PostgreSQL identity implementation.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
from threading import Thread
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.phase13.pyenv import source_paths, pythonpath
for source in reversed(source_paths()):
    sys.path.insert(0, str(source))

from scripts.phase11.local_product_probe import create_graph, close_graph, build_graph


class LabResources:
    def __init__(self, run_id: str, *, environment_overrides: dict | None = None, isolated_postgres: bool = False):
        if os.environ.get("RICK_FORMAL_LAB_AUTHORIZED") != "1":
            raise ValueError("explicit_formal_lab_authority_required")
        from scripts.phase11.local_lab_environment import from_dev_compose
        from scripts.phase11.local_citation_provider import Handler
        self.graphs = []
        self.processes = []
        self.clients = []
        self.server = None
        self.thread = None
        self.closed = False
        self.postgres = None
        try:
            environment = from_dev_compose(ROOT, provider_container=os.environ.get(
                "RICK_LOCAL_PROVIDER_CONTAINER", "rick-dev-provider"))
            if isolated_postgres:
                from scripts.phase11.owned_lab_postgres import OwnedPostgres
                self.postgres = OwnedPostgres(run_id)
                environment["RICK_EXTERNAL_DATABASE_DSN"] = self.postgres.start()
            if environment_overrides:
                allowed = {"RICK_EXTERNAL_DATABASE_DSN", "RICK_REDIS_URL", "RICK_QDRANT_URL",
                           "RICK_QDRANT_API_KEY", "RICK_QDRANT_COLLECTION", "RICK_OBJECT_STORE_ENDPOINT"}
                if set(environment_overrides) - allowed:
                    raise ValueError("unsupported_owned_environment_override")
                environment.update(environment_overrides)
            os.environ.update(environment)
            server_type = type("OwnedProviderServer", (ThreadingHTTPServer,), {"request_queue_size": 128})
            self.server = server_type(("127.0.0.1", 0), Handler)
            self.thread = Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            os.environ.update(RICK_LOCAL_PROBES_AUTHORIZED="1", RICK_LOCAL_PROVIDER_FIXTURE="1",
                RICK_LOCAL_PROBE_ALLOW_PRIVATE="1",
                RICK_LOCAL_MANAGED_FIXTURE_URL=f"http://127.0.0.1:{self.server.server_port}/v1")
            self.run_id = run_id
        except BaseException:
            if self.server:
                self.server.shutdown()
                self.server.server_close()
            if self.postgres:
                self.postgres.close()
            raise

    def graph(self, suffix: str = "", *, scope: dict | None = None):
        graph, scope, user_id = create_graph(self.run_id + suffix, scope=scope)
        self.graphs.append(graph)
        self.server.supported_models = {graph.settings.provider_chat_model, graph.settings.provider_embedding_model}
        return graph, scope, user_id

    def serve_api(self, graph, scope: dict, user_id: str, *, password: str | None = None, provision: bool = True):
        """Start canonical FastAPI in another process, with persisted identity."""
        import httpx
        import psycopg
        from rick_identity import PostgresUserStore, hash_password

        password = password or secrets.token_urlsafe(24)
        email = f"{user_id}@runtime.invalid"
        factory = lambda: psycopg.connect(graph.settings.external_database_dsn, connect_timeout=5)
        if provision:
            PostgresUserStore(factory).save({**scope, "user_id": user_id, "email": email,
                "role": "KNOWLEDGE_MANAGER", "authorized_collection_ids": [scope["collection_id"]],
                "password_hash": hash_password(password)})
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        fd = listener.fileno()
        port = listener.getsockname()[1]
        # Configuration travels over stdin/environment, never argv or a secret
        # file. No access logs, response payloads or credentials are recorded.
        env = {**os.environ, "PYTHONPATH": pythonpath(), "PYTHONDONTWRITEBYTECODE": "1"}
        proc = subprocess.Popen([sys.executable, str(Path(__file__)), "serve", str(fd)],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=env, pass_fds=(fd,), start_new_session=True, text=True)
        self.processes.append(proc)
        try:
            proc.stdin.write(json.dumps({"scope": scope, "user_id": user_id}))
            proc.stdin.close()
        finally:
            listener.close()
        client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=8, follow_redirects=False)
        self.clients.append(client)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError("owned_api_start_failed")
            try:
                if client.get("/health/live").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(.05)
        else:
            raise RuntimeError("owned_api_readiness_timeout")
        response = client.post("/api/v1/auth/login", json={
            "email": email, "password": password, "tenant_id": scope["tenant_id"],
            "workspace_id": scope["workspace_id"]})
        if response.status_code != 200:
            raise RuntimeError("persistent_identity_positive_control_failed")
        client.headers[graph.settings.csrf_header_name] = client.cookies.get(graph.settings.csrf_cookie_name)
        return client

    def start_worker(self, scope: dict, user_id: str, *, continuous: bool = False, duration_seconds: int = 45,
                     max_concurrency: int = 4):
        if type(duration_seconds) is not int or not 1 <= duration_seconds <= 1800:
            raise ValueError("invalid_owned_worker_duration")
        if type(max_concurrency) is not int or not 1 <= max_concurrency <= 4:
            raise ValueError("invalid_owned_worker_concurrency")
        worker_id = user_id + "-" + uuid.uuid4().hex[:8]
        proc = subprocess.Popen([sys.executable, str(Path(__file__)), "worker"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={**os.environ, "PYTHONPATH": pythonpath(), "PYTHONDONTWRITEBYTECODE": "1"},
            start_new_session=True, text=True)
        self.processes.append(proc)
        proc.owned_worker_id = worker_id
        proc.stdin.write(json.dumps({"scope": scope, "user_id": user_id,
            "continuous": continuous, "duration_seconds": duration_seconds,
            "max_concurrency": max_concurrency,
            "worker_id": worker_id}))
        proc.stdin.close()
        return proc

    async def close(self):
        if self.closed:
            return
        errors = []
        for client in self.clients:
            try:
                client.close()
            except Exception:
                errors.append("http_client")
        for proc in self.processes:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.to_thread(proc.wait, timeout=8)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await asyncio.to_thread(proc.wait, timeout=5)
            if getattr(proc, "stdout", None):
                proc.stdout.close()
        for graph in self.graphs:
            try:
                await close_graph(graph)
            except Exception:
                errors.append("product_graph")
        if self.server:
            await asyncio.to_thread(self.server.shutdown)
            self.server.server_close()
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                errors.append("provider_fixture")
        self.closed = True
        if getattr(self, "postgres", None):
            try:
                await asyncio.to_thread(self.postgres.close)
            except Exception:
                errors.append("owned_postgres")
        if errors:
            raise RuntimeError("owned_runtime_cleanup_incomplete")


def publish(graph, scope: dict, *, key: str, content: bytes, filename: str = "fixture.txt"):
    uploaded = graph.ingestion.submit_upload(content, **scope, filename=filename, idempotency_key=key)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        graph.worker.run_once(wait=True)
        job = graph.queue.get_by_idempotency(**scope, idempotency_key=key)
        if job is not None and job.status in {"published", "failed", "dead", "cancelled"}:
            return job
        time.sleep(.02)
    raise RuntimeError("owned_worker_deadline")


def serve(fd: int):
    from core.config import ApiSettings
    from app import create_app
    from services.postgres_identity import PostgresIdentityProvider
    import psycopg
    import uvicorn
    config = json.loads(sys.stdin.read(16384))
    settings = ApiSettings.from_env()
    settings = replace(settings, provider_base_url=os.environ["RICK_LOCAL_MANAGED_FIXTURE_URL"],
                       provider_embedding_dimensions=2, external_chat_api_key="local-fixture",
                       embedding_base_url="", embedding_api_key="", embedding_provider_kind="",
                       session_cookie_secure=False, identity_mode="production")
    identity = PostgresIdentityProvider(lambda: psycopg.connect(settings.external_database_dsn, connect_timeout=5))
    graph = build_graph(settings, config["scope"], config["user_id"], identity=identity)
    application = create_app(settings, graph)
    original_lifespan = application.router.lifespan_context

    @asynccontextmanager
    async def owned_lifespan(app):
        # Explicit DI keeps graph ownership with this harness. Close async
        # provider clients during ASGI shutdown on their original event loop,
        # before Uvicorn disposes it or re-raises its captured signal.
        try:
            async with original_lifespan(app):
                yield
        finally:
            await close_graph(graph)

    application.router.lifespan_context = owned_lifespan
    uvicorn.run(application, fd=fd, access_log=False, log_level="critical")


def worker():
    from core.config import ApiSettings
    from core.otel import configure_process_otel
    config = json.loads(sys.stdin.read(16384))
    settings = replace(ApiSettings.from_env(), provider_base_url=os.environ["RICK_LOCAL_MANAGED_FIXTURE_URL"],
                       provider_embedding_dimensions=2, external_chat_api_key="local-fixture",
                       embedding_base_url="", embedding_api_key="", embedding_provider_kind="")
    runtime = configure_process_otel(service_name="rick-formal-worker")
    duration = config.get("duration_seconds", 45)
    if type(duration) is not int or not 1 <= duration <= 1800:
        raise ValueError("invalid_owned_worker_duration")
    continuous = config.get("continuous") is True
    concurrency = config.get("max_concurrency", 4)
    if type(concurrency) is not int or not 1 <= concurrency <= 4:
        raise ValueError("invalid_owned_worker_concurrency")
    graph = build_graph(settings, config["scope"], config["user_id"], worker_id=config.get("worker_id"),
                        worker_max_concurrency=concurrency)
    deadline = time.monotonic() + duration
    try:
        while time.monotonic() < deadline:
            graph.worker.run_once(wait=True)
            if not continuous:
                scope = config["scope"]
                documents = graph.knowledge.list_documents(scope["workspace_id"], tenant_id=scope["tenant_id"])
                if any(document.status == "published" for document in documents):
                    return
            time.sleep(.05)
        if not continuous:
            raise RuntimeError("owned_worker_deadline")
    finally:
        asyncio.run(close_graph(graph))
        runtime.close()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "serve":
        serve(int(sys.argv[2]))
    elif sys.argv[1:] == ["worker"]:
        try:
            worker()
        except Exception as error:
            import traceback
            print(json.dumps({"error": type(error).__name__, "frames": [
                {"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                for frame in traceback.extract_tb(error.__traceback__)]}), flush=True)
            raise SystemExit(1)
    else:
        raise SystemExit(2)
