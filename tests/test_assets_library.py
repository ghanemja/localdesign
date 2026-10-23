import base64
import json
from tests.helpers import get, post, sse_events
from localdesign import components as C

PNG = base64.b64encode(bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")).decode()


def test_library_catalog_renders_every_sample(app):
    s, d = post(app + "/api/library", {})
    assert s == 200 and len(d["items"]) == len(C.SAMPLES) and d["style_tag"].startswith('<style data-ld-lib="1">')
    assert all("ld-alert error" not in it["html"] for it in d["items"])
    s, d2 = post(app + "/api/library", {"design_system": {"tokens": {"primary": "#5b4bff"}}})
    assert "--primary:#5b4bff" in d2["css"]


def test_asset_upload_serve_inline_delete(app):
    s, d = post(app + "/api/assets", {"project": "proj1", "name": "Acme Logo!.png", "type": "image/png", "data": PNG})
    assert s == 200 and d["url"].startswith("/assets/proj1/Acme-Logo") and d["url"].endswith(".png")
    s, body = get(app + d["url"])
    assert s == 200 and body[:4] == b"\x89PNG"
    s, inl = post(app + "/api/inline", {"html": f'<img src="{d["url"]}"> <div style="background:url({d["url"]})"></div> <img src="/assets/proj1/missing.png">'})
    assert inl["html"].count("data:image/png;base64,") == 2 and "/assets/proj1/missing.png" in inl["html"]
    import urllib.request
    assert urllib.request.urlopen(urllib.request.Request(app + d["url"], method="DELETE")).status == 200
    assert get(app + d["url"])[0] == 404


def test_asset_validation(app):
    assert post(app + "/api/assets", {"project": "../x", "name": "a", "type": "image/png", "data": PNG})[0] == 400
    assert post(app + "/api/assets", {"project": "proj1", "name": "a.exe", "type": "application/x-msdownload", "data": PNG})[0] == 400
    assert get(app + "/assets/proj1/../../config.json")[0] in (400, 404)


def test_artifact_kind_uses_artifact_prompt(app):
    from tests.conftest import FakeLLM
    FakeLLM.calls.clear()
    evs = sse_events(app + "/api/generate", {"brief": "tip calculator", "variants": 1, "width": 1280, "kind": "artifact", "mode": "spec",
                                              "assets": [{"name": "logo", "url": "/assets/p/logo.png", "w": 120, "h": 40}]})
    done = [e for e in evs if e["type"] == "done"][0]
    assert done["mode"] == "html"                     # artifacts never use the spec engine
    sent = FakeLLM.calls[-1]["messages"]
    assert "interactive artifacts" in sent[0]["content"] and "Build this artifact:" in sent[1]["content"]
    assert "/assets/p/logo.png 120×40" in sent[1]["content"]


def test_spec_image_and_logo_sources():
    html = C.render({"nav": {"brand": "Acme", "logo": "/assets/p/logo.svg", "items": ["A"]},
                     "sections": [{"type": "image", "src": "/assets/p/hero.png", "label": "Hero"}, {"type": "hero", "title": "T", "image_src": "/assets/p/h.png"}]}, 1280)
    assert 'src="/assets/p/logo.svg"' in html and 'src="/assets/p/hero.png"' in html and 'src="/assets/p/h.png"' in html


def test_phone_width_collapses_any_layout():
    for layout in ("sidebar", "topnav", "plain", "centered"):
        assert 'class="ld-app mobile"' in C.render({"layout": layout, "sections": []}, 390)
