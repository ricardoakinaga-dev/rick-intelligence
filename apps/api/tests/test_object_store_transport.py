"""Local wire transport proof only; these tests are not a live S3 gate."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from services.object_store_transport import ObjectStoreHttpTransportError, StdlibS3HttpTransport
import services.object_store_transport as transport_module


@pytest.fixture
def wire_server():
    requests = []
    release_body = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append((self.command, self.path, dict(self.headers), b""))
            if self.path.endswith("redirect"):
                self.send_response(307)
                self.send_header("Location", "/must-not-follow")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(404 if self.path.endswith("missing") else 200)
            self.send_header("Content-Length", "6")
            self.send_header("ETag", '"opaque"')
            self.end_headers()
            self.wfile.write(b"abc")
            self.wfile.flush()
            if self.path.endswith("stream"):
                release_body.wait(2)
            self.wfile.write(b"def")

        def do_PUT(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            requests.append((self.command, self.path, dict(self.headers), body))
            self.send_response(201)
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/storage"
    try:
        yield endpoint, requests, release_body
    finally:
        release_body.set()
        server.shutdown()
        server.server_close()
        thread.join()


def test_wire_streaming_is_incremental_and_reads_are_bounded(wire_server):
    endpoint, _, release = wire_server
    transport = StdlibS3HttpTransport(endpoint, require_https=False)
    response = transport.request("GET", endpoint + "/stream", headers={})
    try:
        assert response.status_code == 200
        assert response.headers["etag"] == '"opaque"'
        # The server withholds the final bytes until the first read completes.
        assert response.read(3) == b"abc"
        assert not release.is_set()
        for invalid in (-1, 1024 * 1024 + 1, True):
            with pytest.raises(ObjectStoreHttpTransportError, match="bounded"):
                response.read(invalid)
        release.set()
        assert response.read(3) == b"def"
        assert response.read(3) == b""
    finally:
        transport.close()
    with pytest.raises(ObjectStoreHttpTransportError, match="closed"):
        response.read(1)
    transport.close()


def test_wire_preserves_signed_target_body_and_ignores_proxies(wire_server, monkeypatch):
    endpoint, requests, _ = wire_server
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    transport = StdlibS3HttpTransport(endpoint, require_https=False)
    target = "/bucket/a%20b%2Bz?list-type=2&prefix=a%2Fb&continuation-token=x%2By%3D"
    response = transport.request("PUT", endpoint + target,
                                 headers={"Authorization": "test-signature"}, body=b"\x00payload\xff")
    assert response.status_code == 201
    assert requests[0][1] == "/storage" + target
    assert requests[0][2]["Authorization"] == "test-signature"
    assert requests[0][3] == b"\x00payload\xff"
    response.close()
    transport.close()


def test_wire_transport_projects_w3c_trace_identity_without_baggage(wire_server, monkeypatch):
    def inject(headers):
        projected = dict(headers)
        projected["traceparent"] = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
        return projected

    monkeypatch.setattr(transport_module, "inject_w3c_trace_headers", inject)
    endpoint, requests, _ = wire_server
    transport = StdlibS3HttpTransport(endpoint, require_https=False)
    response = transport.request("GET", endpoint + "/trace", headers={})

    assert requests[0][2]["traceparent"].startswith("00-")
    assert "baggage" not in requests[0][2]
    assert "secret" not in repr(requests[0][2])
    response.close()
    transport.close()


def test_wire_status_and_redirect_are_returned_without_following(wire_server):
    endpoint, requests, _ = wire_server
    transport = StdlibS3HttpTransport(endpoint, require_https=False)
    for suffix, status in (("redirect", 307), ("missing", 404)):
        response = transport.request("GET", endpoint + "/" + suffix, headers={})
        assert response.status_code == status
        response.read(6)
        response.close()
    assert [r[1] for r in requests] == ["/storage/redirect", "/storage/missing"]
    transport.close()


@pytest.mark.parametrize("suffix", ["/../escape", "/%2e%2e/escape", "/a\\escape"])
def test_rejects_path_traversal(wire_server, suffix):
    endpoint, requests, _ = wire_server
    transport = StdlibS3HttpTransport(endpoint, require_https=False)
    with pytest.raises(ObjectStoreHttpTransportError):
        transport.request("GET", endpoint + suffix, headers={})
    assert not requests
    transport.close()


def test_origin_path_host_and_closed_confinement(wire_server):
    endpoint, requests, _ = wire_server
    transport = StdlibS3HttpTransport(endpoint, require_https=False)
    for target, headers in (
        ("http://127.0.0.1:1/storage/secret", {}),
        (endpoint.replace("/storage", "/storage-other"), {}),
        (endpoint, {"Host": "attacker.invalid"}),
        (endpoint + "#secret", {}),
    ):
        with pytest.raises(ObjectStoreHttpTransportError) as caught:
            transport.request("GET", target, headers=headers)
        assert str(caught.value) == "Object store HTTP request failed"
    transport.close()
    with pytest.raises(ObjectStoreHttpTransportError):
        transport.request("GET", endpoint, headers={})
    assert not requests


@pytest.mark.parametrize("kwargs", [{"timeout_seconds": 0}, {"timeout_seconds": float("inf")},
                                    {"timeout_seconds": float("nan")}, {"timeout_seconds": True}])
def test_invalid_configuration_is_redacted(kwargs):
    with pytest.raises(ObjectStoreHttpTransportError, match="Invalid object store transport configuration"):
        StdlibS3HttpTransport("https://example.com", **kwargs)


def test_https_required_and_endpoint_credentials_rejected():
    for endpoint in ("http://example.com", "https://user:secret@example.com", "https://example.com?secret"):
        with pytest.raises(ObjectStoreHttpTransportError) as caught:
            StdlibS3HttpTransport(endpoint)
        assert "secret" not in str(caught.value)


def test_existing_s3_adapter_signs_request_over_local_wire(wire_server):
    from rick_storage import AwsCredentials, ObjectScope, S3ObjectStore

    endpoint, requests, _ = wire_server
    transport = StdlibS3HttpTransport(endpoint, require_https=False)
    store = S3ObjectStore(endpoint, "rick-test", "us-east-1",
                          AwsCredentials("test-access", "test-secret"), transport)
    try:
        store.put(ObjectScope("tenant", "workspace", "source"), "a b.txt", b"example")
        method, target, headers, body = requests[0]
        assert method == "PUT"
        assert target.endswith("/a%20b.txt")
        assert headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=test-access/")
        assert body == b"example"
    finally:
        store.close()


def test_socket_read_timeout_is_sanitized_and_closes_response(wire_server):
    endpoint, _, release = wire_server
    transport = StdlibS3HttpTransport(endpoint, require_https=False, timeout_seconds=0.05)
    response = transport.request("GET", endpoint + "/stream", headers={"Authorization": "secret"})
    try:
        with pytest.raises(ObjectStoreHttpTransportError) as caught:
            response.read(6)
        assert str(caught.value) == "Object store response read failed"
        assert caught.value.__suppress_context__
        with pytest.raises(ObjectStoreHttpTransportError, match="closed"):
            response.read(1)
    finally:
        release.set()
        transport.close()
