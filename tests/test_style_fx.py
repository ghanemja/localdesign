import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from localdesign import components, effects, kits, pdimages, style
from tests.helpers import get, post, sse_events


# ----------------------------------------------------------------------------- effects
def test_inject_adds_the_runtime_once_and_only_when_used():
    page = '<html><body><section data-ld-shader="aurora">Hi</section></body></html>'
    out = effects.inject(page)
    assert out.count('data-ld-lib="fx-runtime"') == 1 and out.index("fx-runtime") < out.index("</body>")
    assert effects.inject(out) == out and effects.inject("<html><body>plain</body></html>") == "<html><body>plain</body></html>"
    assert "data-ld-ascii" in effects.RUNTIME_TAG and all(k in effects.RUNTIME_TAG for k in effects.SHADERS)


def test_effect_kits_prompt_and_licenses():
    items = effects.kit_items()
    assert len(items["fx-shaders"]) == 12 and len(items["fx-ascii"]) == 4 and all(i["fx"] and "fx-runtime" in i["html"] for i in items["fx-shaders"])
    block = effects.prompt_block()
    assert "data-ld-shader" in block and "aurora" in block and "data-ld-ascii" in block and "never write your own canvas/WebGL" in block
    assert effects.detect_license("// License: MIT\nvoid mainImage(){}") == "MIT"
    assert effects.detect_license("// Creative Commons Attribution-NonCommercial-ShareAlike 3.0") == "CC BY-NC-SA"
    assert effects.detect_license("void mainImage(out vec4 o, in vec2 p){}") == effects.SHADERTOY_LICENSE
    html = effects.custom_shader_html("void mainImage(out vec4 o,in vec2 p){} </script><script>x()", "<b>x</b>", "a\nb")
    assert "</script><script>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html and "// a b\n" in html


def test_spec_effect_node():
    h = components.render_node({"type": "effect", "effect": "aurora", "colors": ["#000", "#0f0", "red"], "title": "Hi <x>", "actions": [{"label": "Go"}]}, {"data": {}})
    assert 'data-ld-shader="aurora"' in h and 'data-ld-colors="#000,#0f0,#dc2626"' in h and "Hi &lt;x&gt;" in h and "Go" in h
    assert 'data-ld-ascii="rain"' in components.render_node({"type": "effect", "ascii": "rain"}, {"data": {}})
    page = effects.inject(components.render({"sections": [{"type": "effect", "effect": "grid", "title": "T"}]}))
    assert "fx-runtime" in page and "effect {" in components.NODE_DOCS


def test_add_shader_to_mine(tmp_path, monkeypatch):
    monkeypatch.setattr(kits.config, "HOME", tmp_path); kits._CACHE.clear()
    it = kits.add_shader("Pulse", "void mainImage(out vec4 o, in vec2 p){ o = texture(iChannel0, p); }", "someone", "https://www.shadertoy.com/view/x")
    assert it["license"] == effects.SHADERTOY_LICENSE and it["uses_channels"] and "non-commercial" in it["tags"] and "shadertoy.com/view/x" in it["html"]
    assert kits.query("mine")["items"][0]["license"] == effects.SHADERTOY_LICENSE
    with pytest.raises(ValueError):
        kits.add_shader("x", "void main(){}")
    assert kits.query("fx-ascii")["total"] == 4 and not kits.delete("fx-ascii") and not kits.remove_item("fx-shaders", "shader-aurora")
    kits._CACHE.clear()


# ----------------------------------------------------------------------------- style
STYLE = {"directions": ["editorial", "shader", "nope"], "prefs": {"theme": "dark", "motion": "subtle", "density": "auto", "bogus": "x"},
         "references": [{"url": "https://example.org", "title": "Example", "palette": ["#111111", "#ff5a1f"], "fonts": ["Fraunces"], "traits": ["serif display", "heavy motion"], "note": "the big serif"}],
         "notes": "No stock photos."}


def test_style_prompt_and_variant_directions():
    p = style.style_prompt(STYLE)
    assert "Editorial / print" in p and "Generative shader" in p and "nope" not in p
    assert "theme dark, motion subtle" in p and "density auto" not in p and "bogus" not in p
    assert 'Example (https://example.org) — the user says: "the big serif"; palette #111111, #ff5a1f; fonts Fraunces; serif display, heavy motion' in p
    assert "never copy their content" in p and "No stock photos." in p
    assert "example.org" not in style.style_prompt(STYLE, compact=True)
    assert style.style_prompt({}) == "" and style.style_prompt(None) == "" and style.variant_directions(None) is None
    v = style.variant_directions(STYLE)
    assert len(v) == 2 and v[0].startswith("Design direction for this variant: editorial print")
    assert style.wants_fx(STYLE) and not style.wants_fx({"directions": ["minimal"]}) and style.wants_fx({}, "an animated shader background")
    assert style.wants_fx({"prefs": {"imagery": "ASCII"}})


def test_site_traits_fonts_and_palette():
    html = ('<html><head><title>Studio &amp; Co</title><meta property="og:image" content="/og.png"><link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700">'
            '<script src="/three.module.js"></script></head><body><canvas></canvas><video autoplay muted></video></body></html>')
    css = ".x{font-family:__Geist_a1b2c3,__Geist_Fallback_a1b2c3}body{font-family:'Inter Fallback',Inter,sans-serif;background:#0b0b0f}.g{backdrop-filter:blur(8px)} .a{animation:x 1s}" + "@keyframes k{}" * 6
    parsed = {"tokens": {"bg": "#0b0b0f", "radius": 16}, "palette": [{"value": "#0b0b0f"}, {"value": "color(display-p3 1 0 0)"}, {"value": "#FFFFFF"}, {"value": "#0b0b0f"}]}
    a = style.analysis("https://studio.example/", "Studio &amp; Co", html, css, "import * as THREE from 'three'; gsap.to()", parsed)
    assert a["title"] == "Studio & Co" and a["image"] == "https://studio.example/og.png" and a["palette"] == ["#0b0b0f", "#ffffff"]
    assert a["fonts"][:3] == ["Geist", "Inter", "Playfair Display"]
    for t in ["WebGL / shader graphics", "3D scenes", "heavy motion", "video background", "glass / blur", "dark", "rounded"]:
        assert t in a["traits"], t
    cat = style.catalog()
    assert len(cat["directions"]) == 12 and all("<!doctype html>" in d["preview"] for d in cat["directions"]) and "fx-runtime" in cat["fx_runtime"]
    assert any(i["url"].startswith("https://www.shadertoy.com") for i in cat["inspiration"]) and any("pdimagearchive" in i["url"] for i in cat["inspiration"])


# ----------------------------------------------------------------------------- endpoints
def _serve(routes):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            body, ctype = routes.get(self.path, (b"nope", "text/plain"))
            self.send_response(200 if body != b"nope" else 404); self.send_header("Content-Type", ctype); self.end_headers(); self.wfile.write(body)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_style_endpoints(app):
    st, cat = get(app + "/api/style/catalog")
    assert st == 200 and len(json.loads(cat)["directions"]) == 12
    srv, base = _serve({"/": (b'<html><head><title>Night Studio</title><link rel="stylesheet" href="/s.css"><script src="/app.js"></script></head><body><pre>.</pre><pre>.</pre></body></html>', "text/html"),
                        "/s.css": (b":root{--bg:#05050a;--brand:#ff5a1f}body{font-family:'JetBrains Mono',monospace}", "text/css"),
                        "/app.js": (b"const gl=c.getContext('webgl2');", "application/javascript")})
    try:
        st, d = post(app + "/api/style/analyze", {"url": base + "/"})
        assert st == 200 and d["title"] == "Night Studio" and "#ff5a1f" in d["palette"] and d["fonts"] == ["JetBrains Mono"]
        assert {"WebGL / shader graphics", "ASCII / monospace art", "dark", "monospace type"} <= set(d["traits"])
    finally:
        srv.shutdown()
    st, d = post(app + "/api/style/analyze", {"url": "http://127.0.0.1:9/"})
    assert st == 200 and d["error"] and "kept as a link" in d["error"] and d["traits"] == []
    assert post(app + "/api/style/analyze", {"url": ""})[0] == 400


def test_generate_uses_the_style(app):
    from tests.conftest import FakeLLM
    n = len(FakeLLM.calls)
    evs = sse_events(app + "/api/generate", {"brief": "a landing page", "variants": 3, "mode": "html", "style": STYLE})
    assert len([e for e in evs if e["type"] == "done"]) == 3
    calls = FakeLLM.calls[n:]
    systems = sorted(c["messages"][0]["content"].split("Design direction for this variant: ")[1][:9] for c in calls)
    assert systems == ["editorial", "editorial", "generativ"]                       # two chosen directions rotate over three variants
    users = [c["messages"][-1]["content"] for c in calls]
    assert all("Style profile the user chose" in u and "the big serif" in u and "Visual effects available" in u for u in users)
    n = len(FakeLLM.calls)
    sse_events(app + "/api/generate", {"brief": "a page", "variants": 2, "mode": "html"})
    assert all("Style profile" not in c["messages"][-1]["content"] and "Visual effects" not in c["messages"][-1]["content"] for c in FakeLLM.calls[n:])
    assert "clean and minimal" in FakeLLM.calls[n]["messages"][0]["content"] or "clean and minimal" in FakeLLM.calls[n + 1]["messages"][0]["content"]


def test_shader_and_public_domain_endpoints(app, monkeypatch):
    st, d = post(app + "/api/kits/shader", {"name": "Pulse", "glsl": "// MIT\nvoid mainImage(out vec4 o, in vec2 p){o=vec4(1.0);}"})
    assert st == 200 and d["license"] == "MIT" and d["fx"]
    assert post(app + "/api/kits/shader", {"glsl": "nope"})[0] == 400
    import urllib.request
    urllib.request.urlopen(urllib.request.Request(app + f"/api/kits/mine/items/{d['id']}", method="DELETE"))
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    srv, base = _serve({"/fern.png": (png, "image/png"), "/page.html": (b"<html></html>", "text/html")})
    try:
        st, a = post(app + "/api/pd/import", {"project": "pdproj1", "url": base + "/fern.png", "title": "Bird's Nest and Ferns", "artist": "Fidelia Bridges", "date": "1863",
                                              "source": "Art Institute of Chicago", "license": "Public domain (CC0)", "page": "https://www.artic.edu/artworks/1"})
        assert st == 200 and a["url"].startswith("/assets/pdproj1/Bird-s-Nest-and-Ferns") and a["type"] == "image/png"
        assert a["note"].startswith("“Bird's Nest and Ferns” — Fidelia Bridges, 1863; Public domain (CC0); Art Institute of Chicago")
        assert get(app + a["url"])[1] == png
        st, e = post(app + "/api/pd/import", {"project": "pdproj1", "url": base + "/page.html"})
        assert st == 400 and "not a JPEG/PNG" in e["error"]
        assert post(app + "/api/pd/import", {"project": "../x", "url": base + "/fern.png"})[0] == 400
    finally:
        srv.shutdown()
    assert get(app + "/api/pd/thumb?u=" + "https://evil.example/x.jpg")[0] == 404          # only the museums' image hosts

    def fake_json(url, timeout=15):
        if "artic.edu" in url:
            return {"pagination": {"total": 2}, "config": {"iiif_url": "https://www.artic.edu/iiif/2"},
                    "data": [{"id": 7, "title": "Fern", "image_id": "abc", "artist_title": "A", "date_display": "1850", "thumbnail": {"width": 10, "height": 20}}, {"id": 8, "title": "No image"}]}
        return {"info": {"total": 1}, "data": [{"id": 9, "title": "Moth", "creators": [{"description": "B"}], "creation_date": "1900", "url": "https://clevelandart.org/art/9",
                                                "images": {"web": {"url": "https://openaccess-cdn.clevelandart.org/9_web.jpg", "width": 5, "height": 5}}}]}
    monkeypatch.setattr(pdimages, "_get_json", fake_json)
    st, r = get(app + "/api/pd/search?q=fern")
    r = json.loads(r)
    assert st == 200 and r["total"] == 3 and [i["id"] for i in r["items"]] == ["aic-7", "cma-9"]
    assert r["items"][0]["full"] == "https://www.artic.edu/iiif/2/abc/full/1686,/0/default.jpg" and r["items"][1]["license"] == "CC0"
    assert [i["source"] for i in json.loads(get(app + "/api/pd/search?q=fern&source=cma")[1])["items"]] == ["cma"]
