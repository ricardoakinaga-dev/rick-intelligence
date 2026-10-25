"""Owned loopback network faults; no browser interception or shared shutdown."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import ipaddress
import select
import socket
import socketserver
import struct
from threading import Lock, Thread
import time


class TCPProxy:
    def __init__(self, host, port):
        self.target = (host, port)
        self.paused = False
        self.delay_seconds = 0.
        self.reset_next = False
        self.stopping = False
        self.sockets = set()
        self.lock = Lock()
        self.forwarded_bytes = self.accepts = self.resets = 0
        proxy = self
        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True
            request_queue_size = 128
            def handle_error(self, *_args):
                pass
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                downstream = self.request
                with proxy.lock:
                    proxy.accepts += 1
                    reset = proxy.paused or proxy.reset_next
                    proxy.reset_next = False
                if reset:
                    downstream.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                    with proxy.lock:
                        proxy.resets += 1
                    # Close with SO_LINGER before socketserver can issue its
                    # normal SHUT_WR, which would turn the intended RST into
                    # an ordinary EOF on some kernels.
                    downstream.close()
                    return
                upstream = None
                try:
                    upstream = socket.create_connection(proxy.target, timeout=3)
                    with proxy.lock:
                        proxy.sockets.update((downstream, upstream))
                    while not proxy.stopping and not proxy.paused:
                        readable, _, _ = select.select((downstream, upstream), (), (), .1)
                        for source in readable:
                            data = source.recv(65536)
                            if not data:
                                return
                            if proxy.delay_seconds:
                                time.sleep(proxy.delay_seconds)
                            (upstream if source is downstream else downstream).sendall(data)
                            with proxy.lock:
                                proxy.forwarded_bytes += len(data)
                except OSError:
                    pass
                finally:
                    with proxy.lock:
                        proxy.sockets.discard(downstream)
                        proxy.sockets.discard(upstream)
                    if upstream:
                        upstream.close()
        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def pause(self):
        self.paused = True
        with self.lock:
            clients = tuple(self.sockets)
        for client in clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def close(self):
        self.stopping = True
        self.pause()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        if self.thread.is_alive():
            raise RuntimeError("owned_proxy_cleanup_failed")


class StreamingHTTPProxy:
    """Forward actual API responses; fault mode ends one SSE after a delta.

    The upstream performs its own generation/publication checks. The fault
    simulates losing a response after delivery starts, without fabricating a
    provider output or exposing provider deltas before product validation.
    """
    def __init__(self, upstream, *, bind_host="127.0.0.1", bind_port=0):
        address = ipaddress.ip_address(bind_host)
        if address.version != 4 or not (address.is_loopback or address.is_private) or address.is_unspecified or address.is_multicast:
            raise ValueError("owned_proxy_requires_local_private_bind")
        self.bind_host = bind_host
        self.upstream = upstream.rstrip("/")
        self.truncate_stream = False
        self.truncations = 0
        proxy = self
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"
            def do_GET(self):
                self.forward()
            def do_POST(self):
                self.forward()
            def do_DELETE(self):
                self.forward()
            def do_PATCH(self):
                self.forward()
            def do_PUT(self):
                self.forward()
            def forward(self):
                import httpx
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 <= size <= 50 * 1024 * 1024:
                        raise ValueError("bounded_proxy_body_required")
                    data = self.rfile.read(size) if size else b""
                    headers = {key: value for key, value in self.headers.items()
                               if key.lower() not in {"host", "connection", "transfer-encoding"}}
                    # Per-request client: no shared proxy cookie jar can lend
                    # a different browser's identity to a cookieless request.
                    with httpx.Client(trust_env=False, timeout=90) as client:
                        with client.stream(self.command, proxy.upstream + self.path, headers=headers, content=data) as response:
                            streaming = response.headers.get("Content-Type", "").startswith("text/event-stream")
                            self.send_response(response.status_code)
                            for key, value in response.headers.multi_items():
                                if key.lower() not in {"connection", "transfer-encoding"} and not (streaming and key.lower() == "content-length"):
                                    self.send_header(key, value)
                            self.send_header("Connection", "close")
                            self.end_headers()
                            pending = b""
                            for part in response.iter_raw():
                                if not streaming or not proxy.truncate_stream or not self.path.endswith("/api/v1/chat"):
                                    self.wfile.write(part)
                                    self.wfile.flush()
                                    continue
                                pending += part
                                if len(pending) > 512 * 1024:
                                    raise ValueError("bounded_sse_frame_required")
                                while b"\n\n" in pending:
                                    frame, pending = pending.split(b"\n\n", 1)
                                    self.wfile.write(frame + b"\n\n")
                                    self.wfile.flush()
                                    if frame.startswith(b"data: "):
                                        event = json.loads(frame[6:])
                                        if isinstance(event, dict) and event.get("type") == "delta":
                                            proxy.truncations += 1
                                            self.close_connection = True
                                            return
                            if pending:
                                self.wfile.write(pending)
                except (OSError, ValueError, httpx.HTTPError):
                    self.close_connection = True
            def log_message(self, *_args):
                pass
        self.server = ThreadingHTTPServer((bind_host, bind_port), Handler)
        self.port = self.server.server_port
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"http://{self.bind_host}:{self.port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        if self.thread.is_alive():
            raise RuntimeError("owned_proxy_cleanup_failed")
