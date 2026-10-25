"""Local citation-capable OpenAI-compatible fixture for the PRD26 lab (not production).

It parses the authorized SOURCE id from the Professor prompt and returns a
single grounded citation marker. It is a development fixture, not a model or
quality claim.
"""
from __future__ import annotations
import json, re
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def _json(self, payload, status=200):
        data=json.dumps(payload).encode()
        self.send_response(status); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(data))); self.send_header("Connection","close"); self.end_headers()
        try: self.wfile.write(data)
        except OSError: pass
    def do_GET(self):
        if self.path.endswith("/models"):
            models = getattr(self.server, "supported_models", {"chat-test", "embedding-test"})
            self._json({"object":"list","data":[{"id": model} for model in sorted(models)]}); return
        self.send_response(404); self.end_headers()
    def do_POST(self):
        started = time.perf_counter()
        n=int(self.headers.get("Content-Length","0")); body=json.loads(self.rfile.read(n) or b"{}")
        if self.path.endswith("/embeddings"):
            time.sleep(getattr(self.server, "embedding_delay", 0))
            texts=body.get("input") or [""]
            if isinstance(texts,str): texts=[texts]
            self._json({"data":[{"embedding":[0.1,0.2],"index":i} for i,_ in enumerate(texts)],"model":body.get("model")})
            observations = getattr(self.server, "embedding_observations", None)
            if observations is not None:
                observations.append({"vectors": len(texts), "duration_seconds": time.perf_counter() - started})
                del observations[:-256]
            return
        if self.path.endswith("/chat/completions"):
            mode = getattr(self.server, "fault_mode", "normal")
            counts = getattr(self.server, "fault_counts", None)
            if counts is not None:
                counts[mode] = counts.get(mode, 0) + 1
            if mode == "unavailable":
                self._json({"error": {"code": "fixture_unavailable", "message": "Synthetic unavailable"}}, 503)
                return
            if mode in {"rate-limit", "server-error"}:
                self._json({"error": {"code": "fixture_fault", "message": "Synthetic provider fault"}},
                           429 if mode == "rate-limit" else 500)
                return
            if mode == "timeout":
                time.sleep(2)
            if mode == "slow":
                time.sleep(2)
            text=json.dumps(body)
            m=re.search(r"SOURCE\s+(ev[A-Za-z0-9_.:-]+)", text)
            marker=m.group(1) if m else "ev-missing"
            content=f"Segundo a fonte autorizada, o documento confirma o laboratório local. [cite:{marker}]"
            if body.get("stream") is True:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                model = body.get("model", "chat-test")
                try:
                    for index, part in enumerate((content[:55], content[55:])):
                        chunk = {"id": "local-fixture", "object": "chat.completion.chunk", "created": 0,
                            "model": model, "choices": [{"index": 0, "delta": {"content": part}, "finish_reason": None}]}
                        self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                        self.wfile.flush()
                        if mode == "stream-interruption" and index == 0:
                            self.connection.shutdown(socket.SHUT_RDWR)
                            self.close_connection = True
                            return
                    terminal = {"id": "local-fixture", "object": "chat.completion.chunk", "created": 0,
                        "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
                    self.wfile.write(("data: " + json.dumps(terminal) + "\n\ndata: [DONE]\n\n").encode())
                    self.wfile.flush()
                except OSError:
                    pass  # Expected when the owned browser cancels its query.
                self.close_connection = True
                observations = getattr(self.server, "provider_observations", None)
                if observations is not None:
                    observations.append({"completion_tokens": 5, "duration_seconds": time.perf_counter() - started,
                                         "source": "synthetic-provider-reported-usage"})
                    del observations[:-256]
                return
            self._json({"model":body.get("model","chat-test"),"choices":[{"message":{"role":"assistant","content":content},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}})
            observations = getattr(self.server, "provider_observations", None)
            if observations is not None:
                observations.append({"completion_tokens": 5, "duration_seconds": time.perf_counter() - started,
                                     "source": "synthetic-provider-reported-usage"})
                del observations[:-256]
            return
        self.send_response(404); self.end_headers()
    def log_message(self,*a): return
if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1",58000),Handler).serve_forever()
