import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
import socket
import socketserver
from threading import Thread
from types import SimpleNamespace

import httpx
import pytest

from scripts.phase11.formal_lab_resources import LabResources
from scripts.phase11 import local_operational_harness as ops
from scripts.phase11.local_chaos_harness import OwnedBackends
from scripts.phase11.owned_lab_network import TCPProxy, StreamingHTTPProxy
from scripts.phase11.owned_lab_postgres import OwnedPostgres
from scripts.phase11 import local_frontend_runtime as frontend


@pytest.mark.parametrize("network", [False, True])
def test_image_browser_cannot_delete_a_foreign_web_container(monkeypatch, network):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=json.dumps([{"Config": {"Labels": {
            "rick.phase3.owned-run": "other"}}, "Labels": {"rick.phase3.owned-run": "other"}}]), stderr="")
    monkeypatch.setattr(frontend.subprocess, "run", run)
    with pytest.raises(ValueError, match="refusing_nonowned_web_cleanup"):
        frontend.close_owned_web("foreign", "test", network=network)
    assert len(calls) == 1 and "inspect" in calls[0]


@pytest.mark.parametrize("address", ["0.0.0.0", "8.8.8.8", "224.0.0.1", "::1"])
def test_stream_proxy_rejects_unsupported_or_public_bind_before_opening_a_server(monkeypatch, address):
    from scripts.phase11 import owned_lab_network
    monkeypatch.setattr(owned_lab_network, "ThreadingHTTPServer", lambda *a, **kw: pytest.fail("unvalidated listener"))
    with pytest.raises(ValueError):
        StreamingHTTPProxy("http://127.0.0.1:1", bind_host=address)


@pytest.mark.parametrize("damage", ["unlisted_image", "tampered_sbom"])
def test_image_browser_refuses_unbound_or_tampered_supply_before_docker(tmp_path, monkeypatch, damage):
    monkeypatch.setattr(frontend, "ROOT", tmp_path)
    reference = "127.0.0.1:5000/rick-web@sha256:" + "a" * 64
    sbom = tmp_path / "sbom.json"
    sbom.write_text('{"changed":true}')
    output = tmp_path / ".runtime/phase-3/supply-local/current.json"
    output.parent.mkdir(parents=True)
    output.write_text(json.dumps({"status": "PASS", "images": [{"service": "web", "image_ref": reference,
        "sbom": {"path": "sbom.json", "sha256": "0" * 64}}]}))
    monkeypatch.setattr(frontend.subprocess, "check_output", lambda *a, **kw: pytest.fail("unverified Docker access"))
    with pytest.raises(ValueError, match="web_image_not_in_local_supply|local_web_artifact_hash_mismatch"):
        frontend.verified_web_image(reference if damage == "tampered_sbom" else reference + "other")


def test_owned_postgres_cleanup_cannot_remove_another_runs_container(monkeypatch):
    monkeypatch.setenv("RICK_FORMAL_LAB_AUTHORIZED", "1")
    owner = OwnedPostgres("test-run")
    owner.created = True
    calls = []
    def docker(*args, **kwargs):
        calls.append(args)
        return "existing" if args[0] == "ps" else json.dumps([{"Config": {"Labels": {"rick.phase3.owned-run": "foreign"}}}])
    monkeypatch.setattr(owner, "docker", docker)
    with pytest.raises(ValueError, match="refusing_nonowned_postgres"):
        owner.close()
    assert not any(call[0] == "rm" for call in calls)


def test_postgres_setup_failure_keeps_and_closes_partial_ownership(monkeypatch):
    from scripts.phase11 import local_lab_environment, owned_lab_postgres
    monkeypatch.setenv("RICK_FORMAL_LAB_AUTHORIZED", "1")
    monkeypatch.setattr(local_lab_environment, "from_dev_compose", lambda *a, **kw: {})
    closed = []
    class Partial:
        def __init__(self, run_id):
            pass
        def start(self):
            raise RuntimeError("synthetic-migration-failure")
        def close(self):
            closed.append(True)
    monkeypatch.setattr(owned_lab_postgres, "OwnedPostgres", Partial)
    with pytest.raises(RuntimeError, match="synthetic-migration-failure"):
        LabResources("test-run", isolated_postgres=True)
    assert closed == [True]


@pytest.mark.parametrize("values,quantile", [([], .5), ([float("nan")], .5), ([-1], .5), ([1], 2)])
def test_percentiles_reject_missing_nonfinite_or_invalid_observations(values, quantile):
    with pytest.raises(ValueError):
        ops.percentile(values, quantile)


def test_owned_resource_sample_is_observed_and_does_not_double_count_roots():
    observed = ops.process_sample([os.getpid(), os.getpid()])
    assert observed["memory_bytes"] > 0
    assert observed["processes"] >= 1 and observed["threads"] >= 1
    assert observed["file_descriptors"] >= 3
    with pytest.raises(ValueError):
        ops.process_sample([999999999])


@pytest.mark.parametrize("duration,concurrency", [(0, 1), (1801, 1), (True, 1), (10, 0), (10, 5)])
def test_invalid_worker_limits_never_start_a_process(monkeypatch, duration, concurrency):
    import scripts.phase11.formal_lab_resources as resources
    monkeypatch.setattr(resources.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("unvalidated process start"))
    owner = LabResources.__new__(LabResources)
    with pytest.raises(ValueError):
        owner.start_worker({}, "user", duration_seconds=duration, max_concurrency=concurrency)


def test_each_worker_has_its_own_durable_owner_identity(monkeypatch):
    import scripts.phase11.formal_lab_resources as resources
    class Input(io.StringIO):
        def close(self):
            self.saved = self.getvalue()
            super().close()
    children = []
    def spawn(*args, **kwargs):
        child = SimpleNamespace(stdin=Input())
        children.append(child)
        return child
    monkeypatch.setattr(resources.subprocess, "Popen", spawn)
    owner = LabResources.__new__(LabResources)
    owner.processes = []
    for _ in range(2):
        owner.start_worker({"tenant_id": "test"}, "user", continuous=True, duration_seconds=100, max_concurrency=1)
    configs = [json.loads(child.stdin.saved) for child in children]
    assert configs[0]["worker_id"] != configs[1]["worker_id"]
    assert all(config["max_concurrency"] == 1 and config["continuous"] for config in configs)


def test_chaos_cannot_mutate_a_container_without_its_ownership_label(monkeypatch):
    monkeypatch.setenv("RICK_FORMAL_LAB_AUTHORIZED", "1")
    owner = OwnedBackends("synthetic-run")
    owner.names["redis"] = "some-other-container"
    calls = []
    def docker(*args, **kwargs):
        calls.append(args)
        return json.dumps([{"Config": {"Labels": {"rick.phase3.owned-run": "other-run"}}}])
    monkeypatch.setattr(owner, "docker", docker)
    with pytest.raises(ValueError, match="nonowned_container"):
        owner.change("redis", "kill")
    assert calls == [("inspect", "some-other-container")]


def test_native_chat_http_200_without_authoritative_publication_is_an_error():
    lab = ops.NativeLab.__new__(ops.NativeLab)
    lab.scope = {"tenant_id": "tenant", "workspace_id": "workspace", "collection_id": "collection"}
    async def post(*args, **kwargs):
        return httpx.Response(200, json={"metadata": {"publication_validation": "unverified"}})
    with pytest.raises(ops.ObservationFailure, match="http_200_unverified"):
        asyncio.run(lab.operation(SimpleNamespace(post=post), "chat", "probe"))


def test_verified_abstention_cannot_stand_in_for_generation_throughput():
    lab = ops.NativeLab.__new__(ops.NativeLab)
    lab.scope = {"tenant_id": "tenant", "workspace_id": "workspace", "collection_id": "collection"}
    async def post(*args, **kwargs):
        return httpx.Response(200, json={"metadata": {"publication_validation": "verified", "decision_action": "ABSTAIN"},
                                       "citations": []})
    with pytest.raises(ops.ObservationFailure):
        asyncio.run(lab.operation(SimpleNamespace(post=post), "chat", "probe"))


def test_concurrent_job_observation_coalesces_postgres_snapshots():
    lab = ops.NativeLab.__new__(ops.NativeLab)
    snapshots = []
    def facts():
        snapshots.append(True)
        return {f"job-{index}": {"state": "SUCCEEDED", "document_id": f"doc-{index}"} for index in range(100)}
    lab.queue_facts = facts
    async def observed():
        return await asyncio.gather(*(lab.wait_job(f"job-{index}") for index in range(100)))
    assert len(asyncio.run(observed())) == 100
    assert len(snapshots) == 1, "the measurement must not open a DB connection for each waiting actor"


def test_operational_setup_failure_closes_already_owned_resources(tmp_path, monkeypatch):
    calls = []
    class FailingLab:
        def __init__(self, *args, **kwargs):
            async def close():
                calls.append("closed")
            self.owner = SimpleNamespace(close=close, closed=True)
            raise RuntimeError("synthetic-setup-failure")
    monkeypatch.setattr(ops, "NativeLab", FailingLab)
    monkeypatch.setattr(ops, "ROOT", tmp_path)
    report = asyncio.run(ops.run("performance", (10, 20)))
    assert calls == ["closed"]
    assert report["status"] == "FAIL"
    assert report["measurements"] == {}
    assert report["production_safe"] is False


def test_owned_tcp_reset_and_outage_do_not_change_the_upstream():
    class Echo(socketserver.BaseRequestHandler):
        def handle(self):
            while data := self.request.recv(32):
                self.request.sendall(data)
    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
    upstream = Server(("127.0.0.1", 0), Echo)
    thread = Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    proxy = TCPProxy("127.0.0.1", upstream.server_address[1])
    def echo(port):
        with socket.create_connection(("127.0.0.1", port), timeout=1) as client:
            client.sendall(b"probe")
            return client.recv(32)
    try:
        assert echo(proxy.port) == b"probe"
        proxy.reset_next = True
        with pytest.raises(OSError):
            echo(proxy.port)
        assert proxy.resets == 1 and echo(proxy.port) == b"probe"
        proxy.pause()
        try:
            denied = echo(proxy.port)
        except OSError:
            denied = b""
        assert denied != b"probe"
        assert echo(upstream.server_address[1]) == b"probe"
        proxy.paused = False
        assert echo(proxy.port) == b"probe"
    finally:
        proxy.close()
        upstream.shutdown()
        upstream.server_close()
        thread.join(2)


def test_stream_proxy_truncates_a_real_response_without_lending_cookies():
    class Upstream(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/v1/chat":
                body = b'data: {"type": "delta", "delta": "verified text"}\n\ndata: {"type": "completion"}\n\n'
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
            else:
                body = json.dumps({"cookie": self.headers.get("Cookie")}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Set-Cookie", "identity=synthetic-actor; Path=/")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *_args):
            pass
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    thread = Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    proxy = StreamingHTTPProxy(f"http://127.0.0.1:{upstream.server_port}")
    try:
        assert "completion" in httpx.get(proxy.url + "/api/v1/chat").text
        proxy.truncate_stream = True
        response = httpx.get(proxy.url + "/api/v1/chat")
        assert response.status_code == 200 and "delta" in response.text and "completion" not in response.text
        assert proxy.truncations == 1
        assert httpx.get(proxy.url + "/identity", headers={"Cookie": "identity=actor-A"}).json()["cookie"] == "identity=actor-A"
        assert httpx.get(proxy.url + "/identity").json()["cookie"] is None
    finally:
        proxy.close()
        upstream.shutdown()
        upstream.server_close()
        thread.join(2)
