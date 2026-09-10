"""Hermetic tests for the provider runtime gate."""

from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[3]
for _package in ("contracts", "providers"):
    source = str(ROOT / "packages" / _package / "src")
    if source not in sys.path:
        sys.path.insert(0, source)

from scripts.phase11 import provider_runtime_gate


class _ProviderHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        if not self.path.endswith("/models"):
            self.send_response(404)
            self.end_headers()
            return
        payload = {"object": "list", "data": [{"id": "chat-test"}]}
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        if self.path.endswith("/chat/completions") and body.get("stream") is True:
            if body.get("tools"):
                events = (
                    {
                        "model": body["model"],
                        "choices": [
                            {
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "id": "call-phase11-stream",
                                            "type": "function",
                                            "function": {
                                                "name": "report_status",
                                                "arguments": '{"sta',
                                            },
                                        }
                                    ]
                                },
                                "finish_reason": None,
                            }
                        ],
                    },
                    {
                        "model": body["model"],
                        "choices": [
                            {
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "function": {"arguments": 'tus":"ok"}'},
                                        }
                                    ]
                                },
                                "finish_reason": "stop",
                            }
                        ],
                    },
                )
            elif body.get("response_format") == {"type": "json_object"}:
                events = (
                    {"model": body["model"], "choices": [{"delta": {"content": '{"status":'}, "finish_reason": None}]},
                    {"model": body["model"], "choices": [{"delta": {"content": '"ok"}'}, "finish_reason": "stop"}]},
                )
            else:
                events = (
                    {"model": body["model"], "choices": [{"delta": {"content": "stream "}, "finish_reason": None}]},
                    {"model": body["model"], "choices": [{"delta": {"content": "acknowledged"}, "finish_reason": None}]},
                    {"model": body["model"], "choices": [{"delta": {}, "finish_reason": "stop"}]},
                )
            encoded = "".join(f"data: {json.dumps(event)}\n\n" for event in events).encode("utf-8") + b"data: [DONE]\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(encoded)
            return
        if self.path.endswith("/chat/completions"):
            if body.get("tools"):
                payload = {
                    "model": body["model"],
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call-phase11",
                                        "type": "function",
                                        "function": {
                                            "name": "report_status",
                                            "arguments": '{"status":"ok"}',
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "stop",
                        }
                    ],
                }
                encoded = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(encoded)
                return
            content = (
                json.dumps({"status": "ok"})
                if body.get("response_format") == {"type": "json_object"}
                else "health acknowledged"
            )
            payload = {
                "model": body["model"],
                "choices": [
                    {
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7},
            }
        elif self.path.endswith("/embeddings"):
            payload = {
                "data": [{"embedding": [0.1, 0.2], "index": 0}],
                "model": body["model"],
            }
        else:
            self.send_response(404)
            self.end_headers()
            return
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        return None


@pytest.fixture()
def provider_url() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProviderHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_missing_provider_authority_is_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "provider.json"
    monkeypatch.setattr(provider_runtime_gate, "ROOT", tmp_path)
    monkeypatch.delenv("RICK_TEST_PROVIDER_URL", raising=False)
    code = provider_runtime_gate.main(["--output", str(output)])

    assert code == 2
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "BLOCKED_EXTERNAL"
    assert payload["production_safe"] is False


def test_real_openai_compatible_endpoint_passes_semantic_checks(provider_url: str, tmp_path: Path) -> None:
    output = tmp_path / "provider.json"
    status, assertions, production_safe, endpoint = asyncio.run(
        provider_runtime_gate._run_checks(
            provider_url,
            api_key=None,
            chat_model="chat-test",
            embedding_model="embedding-test",
            embedding_dimensions=2,
            require_tls=False,
            require_auth=False,
            allow_nonlocal=False,
        )
    )

    assert status == "PASS"
    assert {item.name for item in assertions} >= {
        "provider-health-probe",
        "context-budget-contract",
        "chat-completion-contract",
        "json-response-contract",
        "tool-call-contract",
        "streaming-contract",
        "streaming-json-contract",
        "streaming-tool-call-contract",
        "embedding-contract",
    }
    assert production_safe is False
    assert endpoint["host_scope"] == "loopback"


def test_endpoint_credentials_and_redirect_scope_are_rejected() -> None:
    with pytest.raises(provider_runtime_gate._InvalidConfiguration):
        provider_runtime_gate._parse_endpoint(
            "http://user:secret@127.0.0.1:8080/v1",
            allow_nonlocal=False,
            require_tls=False,
        )
    with pytest.raises(provider_runtime_gate._BlockedExternal):
        provider_runtime_gate._parse_endpoint(
            "http://provider.example/v1",
            allow_nonlocal=False,
            require_tls=False,
        )
