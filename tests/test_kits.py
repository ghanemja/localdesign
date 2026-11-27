import io
import json
import re
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from localdesign import components, kits
from tests.helpers import get, post


# ----------------------------------------------------------------------------- scoping
def test_scope_css_prefixes_selectors_both_ways_and_keeps_pseudos_last():
    out = kits.scope_css(".cta:hover::before, .wrap > input[type='checkbox']:checked + label { color: red }", "k1")
    assert ".k1 .cta:hover::before, .cta.k1:hover::before" in out
    assert ".k1 .wrap > input[type='checkbox']:checked + label, .wrap.k1 > input[type='checkbox']:checked + label" in out


def test_scope_css_renames_keyframes_drops_imports_and_page_scaffolding():
    css = """@import url("https://fonts.example/x.css"); @charset "utf-8";
    :root { --brand: #5b4bff; color-scheme: dark }
    body { margin: 0; display: grid; place-items: center; min-height: 100vh; background: #000; --gap: 4px }
    * { box-sizing: border-box }
    .spin { animation: spin 1s linear infinite, fade 2s } .x { animation-name: spin }
    @keyframes spin { to { transform: rotate(360deg) } } @-webkit-keyframes fade { from { opacity: 0 } }
    @media (max-width: 600px) { body .spin { width: 10px } }"""
    out = kits.scope_css(css, "k2")
    assert "@import" not in out and "@charset" not in out and "fonts.example" not in out
    assert ".k2{--brand: #5b4bff}" in out and "color-scheme" not in out           # :root → the element, variables only
    assert ".k2{--gap: 4px}" in out and "place-items" not in out and "#000" not in out   # body scaffolding dropped
    assert ".k2, .k2 *{" in out
    assert "animation: spin-k2 1s linear infinite, fade-k2 2s" in out and "animation-name: spin-k2" in out
    assert "@keyframes spin-k2" in out and "@-webkit-keyframes fade-k2" in out
    assert "@media (max-width: 600px){.k2 .spin{" in out                         # 'body .spin' → descendant of the element


def test_scope_css_global_root_vars_for_the_builtin_library():
    out = kits.scope_css(":root{--primary:#2563eb} body{font-family:var(--font)} .ld-card{padding:4px}", "ldk-builtin", root_vars="global")
    assert ":where(:root){--primary:#2563eb}" in out and "font-family" not in out
    lib = components.library(None)
    assert 'data-ld-lib="builtin"' in lib["style_tag"] and ":where(:root){" in lib["style_tag"]
    assert not re.search(r"(^|[\s}>])(:root|body)\s*\{", lib["style_tag"].split(">", 1)[1])   # nothing global left
    assert all('ldk-builtin' in it["html"] for it in lib["items"])


def test_add_root_class_tags_every_top_level_element():
    html = '<!-- c --><input type="checkbox" id="a"><label for="a" class="lbl">x <b>y</b></label>\n<svg viewBox="0 0 1 1"><path d="M0 0"/></svg>'
    out = kits.add_root_class(html, "k3")
    assert '<input class="k3" type="checkbox" id="a">' in out and 'class="lbl k3"' in out and '<svg class="k3" viewBox' in out
    assert "<b>y</b>" in out and out.count("k3") == 3
    assert kits.add_root_class("just text", "k4") == '<span class="k4">just text</span>'


# ----------------------------------------------------------------------------- packs
UIVERSE = {
    "Buttons/0x-Ab_cool-penguin-3.html": '<button class="cta"><span>Go</span></button>\n<style>\n/* From Uiverse.io by 0x-Ab - Tags: button, animated, glow */\n.cta{animation:pulse 1s}@keyframes pulse{50%{opacity:.5}}\n</style>',
    "loaders/b_quiet-dog-1.html": '<div class="loader"></div>\n<style>\n/* From Uiverse.io by b - Tags: loader */\n.loader{width:9px}\n</style>',
    "Buttons/tw_only.html": '<!-- From Uiverse.io by tw - Tags: button -->\n<button class="flex bg-purple-300 px-4 rounded-full">x</button>',
    "LICENSE": "MIT License\n\nCopyright (c) 2023 Uiverse.io",
}
SPINKIT = {"spinkit.css": ':root{--sk-size:40px}\n/*  Plane\n\n      <div class="sk-plane"></div>\n */\n.sk-plane{width:var(--sk-size);animation:sk-plane 1s}\n@keyframes sk-plane{to{opacity:0}}\n'
                          '/*  Chase\n\n      <div class="sk-chase">\n        <div class="sk-chase-dot"></div>\n      </div>\n */\n.sk-chase{width:4px}', "LICENSE": "MIT"}


def test_parse_uiverse_pack():
    assert kits.detect(UIVERSE) == "uiverse" and kits.detect(SPINKIT) == "spinkit" and kits.detect({"a.html": "<b>x</b>"}) is None
    items, shared, skipped = kits.parse("uiverse", UIVERSE)
    assert skipped["tailwind"] == 1 and shared == "" and len(items) == 2
    btn = next(i for i in items if i["category"] == "Buttons")
    assert btn["author"] == "0x-Ab" and btn["name"] == "cool penguin" and btn["tags"] == ["button", "animated", "glow"]
    assert f'class="cta {btn["scope"]}"' in btn["html"] and f"pulse-{btn['scope']}" in btn["css"]
    assert next(i for i in items if i["category"] == "Loaders")["name"] == "quiet dog"


def test_parse_css_pack_shares_one_scoped_stylesheet():
    items, shared, _ = kits.parse("spinkit", SPINKIT)
    assert [i["name"] for i in items] == ["Plane", "Chase"] and items[1]["html"].startswith('<div class="sk-chase ldk-')
    scope = items[0]["scope"]
    assert all(i["scope"] == scope and i["css"] == "" for i in items)
    assert f".{scope}{{--sk-size:40px}}" in shared and f"sk-plane-{scope}" in shared


def test_own_kit_with_linked_stylesheet_and_scripts(tmp_path):
    (tmp_path / "Buttons").mkdir()
    (tmp_path / "theme.css").write_text("body{background:#000}.btn{color:teal;animation:a 1s}@keyframes a{to{opacity:1}}")
    (tmp_path / "Buttons" / "primary.html").write_text('<html><head><link rel="stylesheet" href="../theme.css"></head><body><button class="btn">Go</button><script>alert(1)</script></body></html>')
    (tmp_path / "logo.png").write_bytes(b"\x89PNG")
    files = kits.read_folder(str(tmp_path))
    assert set(files) == {"theme.css", "Buttons/primary.html"}
    items, shared, _ = kits.parse("acme", files)
    assert len(items) == 1 and "alert" not in items[0]["html"] and "#000" not in shared and "color:teal" in shared
    kit_cls = kits._scope_id("acme", "__kit__")
    assert kit_cls in items[0]["html"] and f"a-{kit_cls}" in shared
    with pytest.raises(ValueError):
        kits.read_folder("relative/path")


@pytest.fixture()
def kithome(tmp_path, monkeypatch):
    monkeypatch.setattr(kits.config, "HOME", tmp_path)
    kits._CACHE.clear()
    yield tmp_path
    kits._CACHE.clear()


def test_install_query_delete_and_mine(kithome):
    s = kits.install("uiverse", "Uiverse Galaxy", UIVERSE, {"repo": "uiverse-io/galaxy", "license": "MIT"})
    assert s["count"] == 2 and s["categories"] == {"Buttons": 1, "Loaders": 1} and "items" not in s and "license_text" not in s["source"]
    kits.install("spinkit", "SpinKit", SPINKIT, {"license": "MIT"})
    assert kits.query()["total"] == 4 + 16                     # + the built-in shader (12) and ASCII (4) effects
    r = kits.query(q="glow button")
    assert r["total"] == 1 and r["items"][0]["kit"] == "uiverse" and r["items"][0]["license"] == "MIT"
    assert kits.query("uiverse", category="Loaders")["total"] == 1 and kits.query(category="Loaders")["total"] == 3 and kits.query("spinkit")["items"][0]["shared_css"]
    assert [i["name"] for i in kits.query("spinkit", offset=1, limit=1)["items"]] == ["Chase"]
    mine = kits.add_mine("Hero card", '<div style="padding:8px">Hi<script>x()</script></div>')
    assert "script" not in mine["html"] and [k["id"] for k in kits.installed()][0] == "mine"
    assert kits.remove_item("mine", mine["id"]) and kits.load("mine")["count"] == 0
    with pytest.raises(ValueError):
        kits.add_mine("x", "no markup")
    assert kits.delete("spinkit") and kits.query()["total"] == 2 + 16 and not kits.delete("spinkit") and not kits.delete("fx-shaders")
    with pytest.raises(ValueError):
        kits.install("x", "x", {"a.html": '<button class="flex bg-red-500">x</button>'}, {})


def test_fetch_repo_downloads_the_zip_with_branch_fallback(monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p, c in SPINKIT.items():
            z.writestr(f"SpinKit-master/{p}", c)
        z.writestr("SpinKit-master/node_modules/x/y.css", "x")
        z.writestr("SpinKit-master/img.png", "x")
    data, hits = buf.getvalue(), []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            hits.append(self.path)
            ok = self.path.endswith("/master")
            self.send_response(200 if ok else 404); self.end_headers()
            if ok:
                self.wfile.write(data)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(kits, "CODELOAD", f"http://127.0.0.1:{srv.server_address[1]}")
    try:
        files = kits.fetch_repo("tobiasahlin/SpinKit", "")
        assert set(files) == {"spinkit.css", "LICENSE"} and hits == ["/tobiasahlin/SpinKit/zip/refs/heads/main", "/tobiasahlin/SpinKit/zip/refs/heads/master"]
        with pytest.raises(ValueError):
            kits.fetch_repo("not a repo")
    finally:
        srv.shutdown()


# ----------------------------------------------------------------------------- endpoints
def test_kit_endpoints(app):
    import urllib.request
    st, d = get(app + "/api/kits")
    d = json.loads(d)
    assert {c["id"] for c in d["catalog"]} == {"uiverse", "spinkit", "three-dots"} and all(c["license"] == "MIT" for c in d["catalog"])
    st, k = post(app + "/api/kits/install", {"files": [{"path": "acme/Badges/ok.html", "content": '<span class="b">OK</span><style>.b{color:green}</style>'},
                                                       {"path": "acme/notes.txt", "content": "x"}], "name": "Acme UI"})
    assert st == 200 and k["id"] == "acme-ui" and k["count"] == 1 and k["categories"] == {"Badges": 1}
    st, k2 = post(app + "/api/kits/install", {"files": [{"path": f"galaxy/{p}", "content": c} for p, c in UIVERSE.items()], "name": "whatever"})
    assert st == 200 and k2["id"] == "uiverse" and k2["name"] == "Uiverse Galaxy" and k2["source"]["repo"] == "uiverse-io/galaxy"   # offline copy = the catalog pack
    st, r = get(app + "/api/kits/items?kit=acme-ui&q=ok")
    r = json.loads(r)
    assert r["total"] == 1 and "color:green" in r["items"][0]["css"] and r["items"][0]["kit_name"] == "Acme UI"
    st, m = post(app + "/api/kits/mine", {"name": "Lead", "html": "<p style='margin:0'>Lead</p>"})
    assert st == 200 and m["name"] == "Lead"
    assert urllib.request.urlopen(urllib.request.Request(app + f"/api/kits/mine/items/{m['id']}", method="DELETE")).status == 200
    assert urllib.request.urlopen(urllib.request.Request(app + "/api/kits/acme-ui", method="DELETE")).status == 200
    assert get(app + "/api/kits/items?offset=x")[0] == 400
    assert post(app + "/api/kits/install", {"source": "nope"})[0] == 400
    assert post(app + "/api/kits/install", {"path": "relative/dir"})[0] == 400
    assert post(app + "/api/kits/install", {})[0] == 400
    assert post(app + "/api/kits/install", {"files": []}, {"Origin": "https://evil.com"})[0] == 403
    urllib.request.urlopen(urllib.request.Request(app + "/api/kits/uiverse", method="DELETE"))


def test_cache_never_serves_a_stale_kit_after_a_write(kithome):
    """Windows mtimes are coarse: a write right after another can keep the same mtime. Writes must invalidate the cache."""
    import os
    kits.add_mine("A", "<p>a</p>")
    f = kits.kits_dir() / "mine.json"
    st = f.stat()
    assert kits.load("mine")["count"] == 1                       # cached
    item = kits.add_mine("B", "<p>b</p>")
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))            # same mtime as before, like a coarse clock
    assert kits.load("mine")["count"] == 2
    assert kits.remove_item("mine", item["id"])
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert kits.load("mine")["count"] == 1
