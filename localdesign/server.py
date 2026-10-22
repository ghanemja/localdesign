"""HTTP server: static app + JSON/SSE API. Stdlib only."""
from __future__ import annotations

import argparse
import json
import os
import queue
import re
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from . import __version__, config, llm, prompts

STATIC = Path(__file__).parent / "static"
CFG = config.load()
CFG_LOCK = threading.Lock()
SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _json(h, obj, status=200):
    data = json.dumps(obj).encode()
    h.send_response(status)
    h.send_header("Content-Type", "application/json")
    h.send_header("Content-Length", str(len(data)))
    h.end_headers()
    h.wfile.write(data)


def _read_json(h) -> dict:
    n = int(h.headers.get("Content-Length") or 0)
    return json.loads(h.rfile.read(n) or b"{}")


# ------------------------------------------------------------------ generation
def _run_variant(cfg, idx, brief, context, width, direction, q: queue.Queue):
    sys_p = prompts.system_prompt(width, direction, cfg.get("allow_cdn", False))
    msgs = [{"role": "user", "content": prompts.generate_user_prompt(brief, context)}]
    _stream_to_queue(cfg, idx, sys_p, msgs, q)


def _run_iterate(cfg, idx, html, instruction, width, q: queue.Queue):
    sys_p = prompts.system_prompt(width, None, cfg.get("allow_cdn", False))
    msgs = [{"role": "user", "content": prompts.ITERATE.format(html=html, instruction=instruction)}]
    _stream_to_queue(cfg, idx, sys_p, msgs, q, temperature=0.4)


def _stream_to_queue(cfg, idx, sys_p, msgs, q, temperature=None):
    buf = ""
    last = 0.0
    try:
        thinking_sent = False
        for delta in llm.stream(cfg, sys_p, msgs, temperature=temperature):
            if isinstance(delta, dict):
                if not thinking_sent:
                    q.put({"type": "status", "i": idx, "status": delta.get("status", "")})
                    thinking_sent = True
                continue
            buf += delta
            now = time.time()
            if now - last > 0.25:
                q.put({"type": "partial", "i": idx, "html": prompts.partial_html(buf)})
                last = now
        _finish(q, idx, buf)
    except llm.Truncated as e:
        _finish(q, idx, buf, warning=str(e))
    except llm.LLMError as e:
        q.put({"type": "error", "i": idx, "message": str(e)})
    except Exception as e:  # noqa: BLE001
        q.put({"type": "error", "i": idx, "message": f"{type(e).__name__}: {e}"})


def _finish(q, idx, buf, warning=None):
    html = prompts.extract_html(buf)
    if "<" not in html:
        q.put({"type": "error", "i": idx, "message": (warning + "\n\n" if warning else "") + "Model returned no HTML:\n" + buf[:500]})
        return
    ev = {"type": "done", "i": idx, "html": html}
    if warning:
        ev["warning"] = warning
    q.put(ev)


def _sse_multiplex(h, q: queue.Queue, n: int):
    h.send_response(200)
    h.send_header("Content-Type", "text/event-stream")
    h.send_header("Cache-Control", "no-cache")
    h.send_header("X-Accel-Buffering", "no")
    h.end_headers()
    finished = 0
    while finished < n:
        try:
            ev = q.get(timeout=15)
        except queue.Empty:
            h.wfile.write(b": ping\n\n")
            h.wfile.flush()
            continue
        if ev["type"] in ("done", "error"):
            finished += 1
        try:
            h.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
            h.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
    h.wfile.write(b"data: {\"type\": \"end\"}\n\n")
    h.wfile.flush()


# ------------------------------------------------------------------- projects
def _project_path(pid: str) -> Path:
    if not SAFE_ID.match(pid):
        raise ValueError("bad project id")
    return config.PROJECTS_DIR / f"{pid}.json"


class Handler(BaseHTTPRequestHandler):
    server_version = f"localdesign/{__version__}"

    def log_message(self, fmt, *args):  # quieter log: skip routine GETs
        line = fmt % args
        if line.startswith('"GET') and (" 200 " in line or " 204 " in line or " 304 " in line):
            return
        sys.stderr.write("  " + line + "\n")

    # ---- GET
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/" or u.path == "/index.html":
            return self._static("index.html")
        if u.path.startswith("/static/"):
            return self._static(u.path[len("/static/"):])
        if u.path == "/favicon.ico":  # srcdoc iframes ask for this
            self.send_response(204); self.end_headers(); return
        if u.path == "/api/config":
            with CFG_LOCK:
                return _json(self, config.public(CFG))
        if u.path == "/api/models":
            try:
                with CFG_LOCK:
                    cfg = dict(CFG)
                return _json(self, {"models": llm.list_models(cfg)})
            except llm.LLMError as e:
                return _json(self, {"error": str(e)}, 502)
        if u.path == "/api/projects":
            config.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
            items = []
            for p in sorted(config.PROJECTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    d = json.loads(p.read_text())
                    items.append({"id": p.stem, "name": d.get("name", p.stem), "updated": p.stat().st_mtime, "screens": len(d.get("screens", []))})
                except (OSError, json.JSONDecodeError):
                    continue
            return _json(self, {"projects": items})
        if u.path.startswith("/api/projects/"):
            try:
                p = _project_path(u.path.rsplit("/", 1)[1])
                return _json(self, json.loads(p.read_text()))
            except (ValueError, FileNotFoundError):
                return _json(self, {"error": "not found"}, 404)
        self.send_error(404)

    def _static(self, name: str):
        p = (STATIC / name).resolve()
        if not str(p).startswith(str(STATIC.resolve())) or not p.is_file():
            return self.send_error(404)
        ctype = {".html": "text/html; charset=utf-8", ".js": "application/javascript", ".css": "text/css", ".svg": "image/svg+xml"}.get(p.suffix, "application/octet-stream")
        data = p.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    # ---- POST / PUT / DELETE
    def do_POST(self):
        u = urlparse(self.path)
        try:
            body = _read_json(self)
        except json.JSONDecodeError:
            return _json(self, {"error": "bad json"}, 400)
        if u.path == "/api/config":
            with CFG_LOCK:
                if body.get("provider") and body["provider"] != CFG.get("provider"):
                    config.apply_preset(CFG, body["provider"])
                for k in ("base_url", "model", "variants", "temperature", "max_tokens", "allow_cdn", "api", "effort"):
                    if k in body and body[k] not in (None, ""):
                        CFG[k] = body[k]
                if body.get("api_key"):
                    CFG["api_key"] = body["api_key"]
                if "base_url" in body:
                    CFG["_custom_base_url"] = True
                config.save(CFG)
                return _json(self, config.public(CFG))
        if u.path == "/api/generate":
            brief = (body.get("brief") or "").strip()
            if not brief:
                return _json(self, {"error": "empty brief"}, 400)
            with CFG_LOCK:
                cfg = dict(CFG)
            n = max(1, min(int(body.get("variants") or cfg.get("variants", 3)), 6))
            width = int(body.get("width") or 1280)
            context = body.get("context") or None
            q: queue.Queue = queue.Queue()
            for i in range(n):
                direction = prompts.DIRECTIONS[i % len(prompts.DIRECTIONS)] if n > 1 else None
                threading.Thread(target=_run_variant, args=(cfg, i, brief, context, width, direction, q), daemon=True).start()
            return _sse_multiplex(self, q, n)
        if u.path == "/api/iterate":
            html, instruction = body.get("html") or "", (body.get("instruction") or "").strip()
            if not html or not instruction:
                return _json(self, {"error": "need html and instruction"}, 400)
            with CFG_LOCK:
                cfg = dict(CFG)
            width = int(body.get("width") or 1280)
            q: queue.Queue = queue.Queue()
            threading.Thread(target=_run_iterate, args=(cfg, 0, html, instruction, width, q), daemon=True).start()
            return _sse_multiplex(self, q, 1)
        if u.path == "/api/projects":
            pid = body.get("id") or uuid.uuid4().hex[:10]
            try:
                p = _project_path(pid)
            except ValueError:
                return _json(self, {"error": "bad id"}, 400)
            config.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
            body["id"] = pid
            body["updated"] = time.time()
            p.write_text(json.dumps(body))
            return _json(self, {"id": pid, "updated": body["updated"]})
        self.send_error(404)

    def do_DELETE(self):
        u = urlparse(self.path)
        if u.path.startswith("/api/projects/"):
            try:
                _project_path(u.path.rsplit("/", 1)[1]).unlink()
                return _json(self, {"ok": True})
            except (ValueError, FileNotFoundError):
                return _json(self, {"error": "not found"}, 404)
        self.send_error(404)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ld", description="localdesign — prompt → UI mockups on a canvas, any LLM.")
    ap.add_argument("--port", type=int, default=int(os.environ.get("LD_PORT", 7878)))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-open", action="store_true", help="Don't open the browser")
    ap.add_argument("--provider", help="Preset: " + ", ".join(config.PRESETS))
    ap.add_argument("--base-url")
    ap.add_argument("--model", "-m")
    ap.add_argument("--api-key")
    ap.add_argument("--version", action="version", version=f"localdesign {__version__}")
    a = ap.parse_args(argv)
    with CFG_LOCK:
        if a.provider:
            config.apply_preset(CFG, a.provider)
        if a.base_url:
            CFG["base_url"] = a.base_url
            CFG["_custom_base_url"] = True
        if a.model:
            CFG["model"] = a.model
        if a.api_key:
            CFG["api_key"] = a.api_key
    url = f"http://{a.host}:{a.port}"
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.daemon_threads = True
    print(f"localdesign v{__version__} · {url}\n  provider {CFG['provider']} · model {CFG['model'] or '(none — set in Settings)'} · {CFG['base_url']}\n  projects in {config.PROJECTS_DIR}\n  Ctrl-C to stop")
    if not a.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
