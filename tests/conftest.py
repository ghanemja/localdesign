"""Shared fixtures: isolated LD_HOME, a fake OpenAI-compatible model server, and the app server in a thread."""
import json
import os
import socket
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

_TMP = tempfile.mkdtemp(prefix="ldtest-")
os.environ["LD_HOME"] = _TMP


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


# ----------------------------------------------------------------------------- fake model
SPEC = {"title": "Mock", "tokens": {"primary": "#123456"}, "layout": "sidebar", "nav": {"brand": "Mock", "items": ["A", "B"]},
        "sections": [{"type": "heading", "text": "Hello"}, {"type": "table", "columns": ["Order", "Status"], "data": "orders", "badge_col": 1},
                     {"type": "buttons", "items": [{"label": "Next", "link": "Second"}]}]}
HTML_DOC = "<!DOCTYPE html><html><head><style>:root{--primary:#abcdef}</style></head><body><main><h1>Mock page</h1><button data-link=\"Second\">Go</button></main></body></html>"


class FakeLLM(BaseHTTPRequestHandler):
    """Answers like an OpenAI-compatible /chat/completions endpoint, choosing a reply from the prompt."""
    calls = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.endswith("/models"):
            body = json.dumps({"data": [{"id": "mock-a"}, {"id": "mock-b"}]}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        req = json.loads(self.rfile.read(n))
        FakeLLM.calls.append(req)
        text = "\n".join(m.get("content", "") for m in req["messages"])
        if "JSON layout spec" in text:
            reply = "```json\n" + json.dumps(SPEC) + "\n```"
        elif "editing ONE element" in text:
            reply = '<h1 class="x">Changed</h1>'
        elif "Plan the screens" in text:
            reply = json.dumps([{"title": "First", "brief": "b1", "links": ["Second"]}, {"title": "Second", "brief": "b2", "links": []}, {"title": "Ghost", "brief": "x", "links": ["Nope"]}])
        elif "Convert this screen" in text:
            reply = "```jsx\nexport default function Mock(){ return <div className=\"p-4\">hi</div> }\n```"
        elif "say TRUNCATE" in text:
            reply = "partial"
        else:
            reply = "Here you go:\n```html\n" + HTML_DOC + "\n```"
        finish = "length" if "say TRUNCATE" in text else "stop"
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        if "think first" in text:
            self.wfile.write(b'data: ' + json.dumps({"choices": [{"delta": {"reasoning_content": "hmm"}}]}).encode() + b"\n\n")
        for i in range(0, len(reply), 40):
            self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": {"content": reply[i:i + 40]}}]}).encode() + b"\n\n")
        self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": finish}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}}).encode() + b"\n\n")
        self.wfile.write(b"data: [DONE]\n\n")


@pytest.fixture(scope="session")
def fake_llm():
    port = _free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), FakeLLM); srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}/v1"
    srv.shutdown()


@pytest.fixture(scope="session")
def app(fake_llm):
    """The localdesign server, configured against the fake model."""
    os.environ.update({"LD_PROVIDER": "custom", "LD_BASE_URL": fake_llm, "LD_MODEL": "mock-a", "LD_API_KEY": "x"})
    from localdesign import server, config
    server.CFG.clear(); server.CFG.update(config.load()); server.CFG["mode"] = "html"
    port = _free_port()
    server.ALLOWED_HOSTS.update({"localhost", "127.0.0.1", "::1"})
    srv = ThreadingHTTPServer(("127.0.0.1", port), server.Handler); srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()
