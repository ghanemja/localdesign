from localdesign import designsystem as D

CSS = """:root{--brand-primary:#5b4bff;--color-bg:#f7f7fb;--color-surface:#fff;--color-text:#1a1a2e;--color-muted:#6b6b80;--color-border:#e4e4ef;--radius-md:0.75rem;--font-sans:"Inter",system-ui}"""
TW = """module.exports={theme:{extend:{colors:{primary:{DEFAULT:'#0ea5e9',600:'#0284c7'},secondary:'#f97316',surface:'#ffffff',background:'#0b1220',border:'#1f2937',danger:'#ef4444'},fontFamily:{sans:['Manrope','sans-serif']},borderRadius:{lg:'14px'}}}}"""
TOK = '{"color":{"brand":{"primary":{"$value":"#16a34a","$type":"color"}},"neutral":{"background":{"$value":"#fafaf9"},"text":{"$value":"#111827"}}},"radius":{"base":{"$value":"8px"}},"font":{"family":{"$value":"IBM Plex Sans"}}}'


def test_detect_kind():
    assert D.detect_kind(CSS) == "css" and D.detect_kind(TW) == "tailwind" and D.detect_kind(TOK) == "tokens" and D.detect_kind("<div>x</div>") == "html"


def test_css_variables():
    r = D.parse(CSS)
    t = r["tokens"]
    assert t["primary"] == "#5b4bff" and t["bg"] == "#f7f7fb" and t["text"] == "#1a1a2e" and t["line"] == "#e4e4ef"
    assert t["radius"] == 12 and "Inter" in t["font"]
    assert r["css"].startswith(":root{") and len(r["palette"]) == 6


def test_tailwind_config():
    t = D.parse(TW)["tokens"]
    assert t["primary"] == "#0ea5e9" and t["accent"] == "#f97316" and t["bad"] == "#ef4444"
    assert t["theme"] == "dark" and t["radius"] == 14 and "Manrope" in t["font"]


def test_design_tokens_json():
    t = D.parse(TOK)["tokens"]
    assert t["primary"] == "#16a34a" and t["bg"] == "#fafaf9" and t["radius"] == 8 and t["font"] == "IBM Plex Sans"


def test_html_page_harvests_style_block():
    r = D.parse("<html><head><style>:root{--accent:#ff0066;--bg:#fff}</style></head><body></body></html>", "html")
    assert r["kind"] == "html" and r["tokens"].get("accent") == "#ff0066"


def test_invalid_tokens_json_raises():
    import pytest
    with pytest.raises(ValueError):
        D.parse("{not json", "tokens")


def test_px_conversion():
    assert D._px("0.5rem") == 8 and D._px("12px") == 12 and D._px("garbage") == 12
