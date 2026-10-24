#!/usr/bin/env python3
"""Disposable Qdrant fault/timeout HTTP endpoints for the runtime gate.

- fault port returns HTTP 500 for every request (retry/circuit evidence);
- timeout port sleeps beyond the gate's bounded timeout (typed timeout).

This is a real network boundary, not a monkeypatched transport. It listens only
on loopback and is intended to be started/stopped around one gate run.
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time


class _Handler(BaseHTTPRequestHandler):
    mode = "fault"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        if self.mode == "timeout":
            time.sleep(1.0)
            body = b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = b'{"status":"unavailable"}'
        self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fault-port", type=int, default=56334)
    parser.add_argument("--timeout-port", type=int, default=56335)
    args = parser.parse_args()
    fault = ThreadingHTTPServer(("127.0.0.1", args.fault_port), type("Fault", (_Handler,), {"mode": "fault"}))
    timeout = ThreadingHTTPServer(("127.0.0.1", args.timeout_port), type("Timeout", (_Handler,), {"mode": "timeout"}))
    threading.Thread(target=fault.serve_forever, daemon=True).start()
    threading.Thread(target=timeout.serve_forever, daemon=True).start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0
    finally:
        fault.shutdown()
        timeout.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
