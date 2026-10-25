"""Local citation-capable OpenAI-compatible fixture for the PRD26 lab (not production).

It parses the authorized SOURCE id from the Professor prompt and returns a
single grounded citation marker. It is a development fixture, not a model or
quality claim.
"""
from __future__ import annotations
import json, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def _json(self, payload, status=200):
        data=json.dumps(payload).encode()
        self.send_response(status); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(data))); self.send_header("Connection","close"); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        if self.path.endswith("/models"):
            self._json({"object":"list","data":[{"id":"chat-test"}]}); return
        self.send_response(404); self.end_headers()
    def do_POST(self):
        n=int(self.headers.get("Content-Length","0")); body=json.loads(self.rfile.read(n) or b"{}")
        if self.path.endswith("/embeddings"):
            texts=body.get("input") or [""]
            if isinstance(texts,str): texts=[texts]
            self._json({"data":[{"embedding":[0.1,0.2],"index":i} for i,_ in enumerate(texts)],"model":body.get("model")}); return
        if self.path.endswith("/chat/completions"):
            text=json.dumps(body)
            m=re.search(r"SOURCE\s+(ev[A-Za-z0-9_.:-]+)", text)
            marker=m.group(1) if m else "ev-missing"
            open(".runtime/citation-provider-debug.log","a").write("MARKER="+marker+" COUNT="+str(text.count("SOURCE"))+"\nTAIL="+text[-1500:]+"\n")
            content=f"Segundo a fonte autorizada, o documento confirma o laboratório local. [cite:{marker}]"
            self._json({"model":body.get("model","chat-test"),"choices":[{"message":{"role":"assistant","content":content},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}); return
        self.send_response(404); self.end_headers()
    def log_message(self,*a): return
if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1",58000),Handler).serve_forever()
