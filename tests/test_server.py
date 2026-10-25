import json
from tests.helpers import get, post, sse_events


def test_static_app_and_shim(app):
    assert get(app + "/")[0] == 200
    s, body = get(app + "/static/editor.js")
    assert s == 200 and b"__ldEditor" in body
    assert get(app + "/favicon.ico")[0] == 204
    assert get(app + "/static/../server.py")[0] == 404


def test_host_and_origin_guards(app):
    assert get(app + "/", {"Host": "evil.com"})[0] == 403
    s, body = post(app + "/api/config", {"base_url": "https://evil.example/v1"}, {"Origin": "https://evil.com"})
    assert s == 403
    assert post(app + "/api/config", {}, {"Origin": app})[0] == 200
    assert post(app + "/api/config", {})[0] == 200          # no Origin (curl) is allowed


def test_config_roundtrip_masks_key(app):
    s, c = get(app + "/api/config")
    c = json.loads(c)
    assert c["model"] == "mock-a" and c["api_key_set"] is True and "x" not in c["api_key"][:0] and "presets" in c and c["resolved_mode"] in ("html", "spec")
    s, c2 = post(app + "/api/config", {"variants": 2, "effort": "medium", "audit": False})
    assert c2["variants"] == 2 and c2["effort"] == "medium" and c2["audit"] is False
    post(app + "/api/config", {"audit": True})


def test_models_endpoint(app):
    s, body = get(app + "/api/models")
    assert s == 200 and json.loads(body)["models"] == ["mock-a", "mock-b"]


def test_projects_crud(app):
    s, d = post(app + "/api/projects", {"name": "T", "screens": []})
    pid = d["id"]
    s, lst = get(app + "/api/projects")
    assert any(p["id"] == pid for p in json.loads(lst)["projects"])
    s, one = get(app + f"/api/projects/{pid}")
    assert json.loads(one)["name"] == "T"
    assert post(app + "/api/projects", {"id": "../evil"})[0] == 400
    import urllib.request
    req = urllib.request.Request(app + f"/api/projects/{pid}", method="DELETE")
    assert urllib.request.urlopen(req).status == 200
    assert get(app + f"/api/projects/{pid}")[0] == 404


def test_generate_html_mode_streams_partials_then_done(app):
    evs = sse_events(app + "/api/generate", {"brief": "a page", "variants": 2, "width": 1280, "mode": "html"})
    done = [e for e in evs if e["type"] == "done"]
    assert len(done) == 2 and {e["i"] for e in done} == {0, 1}
    assert all(e["mode"] == "html" and e["html"].startswith("<!DOCTYPE html>") and e["html"].endswith("</html>") for e in done)
    assert any(e["type"] == "partial" for e in evs) and evs[-1]["type"] == "end"


def test_generate_spec_mode_renders_spec_with_data_and_design_system(app):
    evs = sse_events(app + "/api/generate", {"brief": "orders", "variants": 1, "width": 1280, "mode": "spec",
                                              "design_system": {"tokens": {"primary": "#5b4bff"}}, "data": {"orders": [{"order": "#1", "status": "Paid"}]}})
    done = [e for e in evs if e["type"] == "done"][0]
    assert done["mode"] == "spec" and done["spec"]["title"] == "Mock"
    assert "--primary:#5b4bff" in done["html"] and "#1" in done["html"] and 'data-link="Second"' in done["html"]


def test_generate_rejects_empty_brief(app):
    assert post(app + "/api/generate", {"brief": "  "})[0] == 400


def test_iterate_html_and_spec(app):
    evs = sse_events(app + "/api/iterate", {"html": "<html></html>", "instruction": "darker", "width": 1280})
    assert [e for e in evs if e["type"] == "done"][0]["mode"] == "html"
    evs = sse_events(app + "/api/iterate", {"html": "<html></html>", "instruction": "darker", "width": 390, "spec": {"sections": []}})
    d = [e for e in evs if e["type"] == "done"][0]
    assert d["mode"] == "spec" and 'class="ld-app mobile"' in d["html"]


def test_iterate_element_returns_fragment(app):
    evs = sse_events(app + "/api/iterate-element", {"html": "<h1>Old</h1>", "css": ":root{}", "instruction": "change", "width": 1280})
    d = [e for e in evs if e["type"] == "done"][0]
    assert d["mode"] == "element" and d["html"] == '<h1 class="x">Changed</h1>'


def test_plan_filters_dangling_links(app):
    s, d = post(app + "/api/plan", {"text": "checkout flow", "max": 5})
    assert s == 200
    titles = [x["title"] for x in d["screens"]]
    assert titles == ["First", "Second", "Ghost"]
    assert d["screens"][0]["links"] == ["Second"] and d["screens"][2]["links"] == []


def test_render_endpoint(app):
    s, d = post(app + "/api/render", {"spec": {"sections": [{"type": "text", "text": "re-rendered"}]}, "width": 768})
    assert s == 200 and "re-rendered" in d["html"]
    assert post(app + "/api/render", {"spec": "nope"})[0] == 400


def test_ds_parse_endpoint(app):
    s, d = post(app + "/api/ds/parse", {"text": ":root{--brand:#5b4bff}", "kind": "auto"})
    assert s == 200 and d["kind"] == "css" and d["tokens"]["primary"] == "#5b4bff"
    assert post(app + "/api/ds/parse", {"text": "{bad", "kind": "tokens"})[0] == 400


def test_export_endpoints(app):
    s, d = post(app + "/api/export/react", {"html": "<html><body><div class='a'>x</div></body></html>", "title": "My Screen"})
    assert d["name"] == "MyScreen" and 'className="a"' in d["jsx"]
    s, d = post(app + "/api/export/spec", {"project": {"name": "P", "screens": []}})
    assert "# P — design spec" in d["markdown"]
    evs = sse_events(app + "/api/export/react-ai", {"html": "<html><body>x</body></html>", "title": "Mock"})
    d = [e for e in evs if e["type"] == "done"][0]
    assert d["mode"] == "text" and d["text"].startswith("export default function Mock")


def test_audit_log_written(app):
    from localdesign import config
    assert config.AUDIT_PATH.exists()
    last = json.loads(config.AUDIT_PATH.read_text().strip().splitlines()[-1])
    assert "kind" in last and "model" in last and "ts" in last


# ----------------------------------------------------------------------------- connection test + design system from a URL
def test_connection_test_endpoint(app):
    from tests.helpers import post
    st, d = post(app + "/api/test", {})
    assert st == 200 and d["ok"] is True and d["reply"] == "OK" and d["mode"] in ("html", "spec") and "secs" in d


def test_ds_fetch_from_site(app):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from tests.helpers import post
    PAGE = b'<html><head><title>Acme Portal</title><link rel="stylesheet" href="/static/site.css"><link rel="stylesheet" href="https://fonts.example/css"><style>:root{--radius:12px}</style></head><body><h1>Hi</h1></body></html>'
    CSS = b':root{--brand:#5b4bff;--bg:#f7f7fb;--text:#121417}body{font-family:Inter,sans-serif}'
    hits = []
    class Site(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            hits.append(self.path)
            body, ct = (PAGE, "text/html") if self.path == "/" else (CSS, "text/css") if self.path == "/static/site.css" else (b"nope", "text/plain")
            self.send_response(200 if body != b"nope" else 404); self.send_header("Content-Type", ct); self.end_headers(); self.wfile.write(body)
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Site); srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        st, d = post(app + "/api/ds/fetch", {"url": f"http://127.0.0.1:{port}/"})
        assert st == 200, d
        assert d["title"] == "Acme Portal" and d["sheets"] == [f"http://127.0.0.1:{port}/static/site.css"]     # same-origin only
        assert d["tokens"].get("primary") == "#5b4bff" and d["tokens"].get("bg") == "#f7f7fb" and "--brand:#5b4bff" in d["source_css"]
        assert "/static/site.css" in hits and not any("fonts.example" in h for h in hits)
        st, d = post(app + "/api/ds/fetch", {"url": f"http://127.0.0.1:{port}/static/site.css"})     # a bare stylesheet works too
        assert st == 200 and d["tokens"].get("primary") == "#5b4bff"
        assert post(app + "/api/ds/fetch", {"url": f"http://127.0.0.1:{port}/missing"})[0] == 400
        assert post(app + "/api/ds/fetch", {"url": "ftp://x/y"})[0] == 400
        assert post(app + "/api/ds/fetch", {"url": ""})[0] == 400
    finally:
        srv.shutdown()


def test_export_design_md_endpoint(app):
    from tests.helpers import post
    st, d = post(app + "/api/export/designmd", {"project": {"name": "Z", "designSystem": {"tokens": {"primary": "#010203"}}}})
    assert st == 200 and d["markdown"].startswith("---") and 'primary: "#010203"' in d["markdown"] and "## Do's and Don'ts" in d["markdown"]
    assert post(app + "/api/export/designmd", {"project": 1})[0] == 400
