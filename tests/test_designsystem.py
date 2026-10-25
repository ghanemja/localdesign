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


# ----------------------------------------------------------------------------- DESIGN.md (Stitch format)
DMD = '''---
version: alpha
name: Heritage
colors:
  primary: "#1A1C1E"
  secondary: "#6C7278"
  tertiary: "#B8422E"
  neutral: "#F7F5F2"
  on-surface: "#121417"
  outline: "#DDD8D0"
typography:
  h1:
    fontFamily: Public Sans
    fontSize: 3rem
  body-md:
    fontFamily: Public Sans
    fontSize: 1rem
rounded:
  sm: 4px
  md: 8px
spacing:
  scale: [4, 8, 16]
omitted:
  - section: Elevation & Depth
    reason: flat
components:
  button:
    backgroundColor: "{colors.tertiary}"
    rounded: "{rounded.sm}"
---

# Heritage

## Overview

Architectural Minimalism meets Journalistic Gravitas.

## Colors

- **Primary (#1A1C1E):** Deep ink.

## Do's and Don'ts

- Don't use gradients.
'''


def test_yaml_subset():
    y = D.yaml_subset(DMD.split("---")[1])
    assert y["name"] == "Heritage" and y["colors"]["tertiary"] == "#B8422E" and y["typography"]["h1"]["fontSize"] == "3rem"
    assert y["spacing"]["scale"] == [4, 8, 16] and y["omitted"] == [{"section": "Elevation & Depth", "reason": "flat"}]
    assert y["components"]["button"]["backgroundColor"] == "{colors.tertiary}"


def test_design_md_import():
    assert D.detect_kind(DMD) == "designmd"
    r = D.parse(DMD)
    t = r["tokens"]
    assert r["kind"] == "designmd" and r["name"] == "Heritage"
    assert t["primary"] == "#1A1C1E" and t["accent"] == "#6C7278" and t["bg"] == "#F7F5F2" and t["text"] == "#121417" and t["line"] == "#DDD8D0"
    assert t["font"] == "Public Sans" and t["radius"] == 8 and "theme" not in t
    assert r["components"] == [{"name": "button", "props": {"backgroundColor": "#B8422E", "rounded": "4px"}}]      # references resolved
    assert r["notes"].startswith("Architectural Minimalism") and "Don't use gradients." in r["notes"]
    assert {c["value"] for c in r["palette"]} >= {"#1A1C1E", "#B8422E"}
    # yaml in a section code block instead of front matter also counts
    alt = "## Colors\n\n```yaml\ncolors:\n  primary: \"#ff0000\"\n```\n\n## Overview\n\nRed.\n"
    assert D.detect_kind(alt) == "designmd" and D.parse(alt)["tokens"]["primary"] == "#ff0000"


def test_design_md_export_round_trip():
    ds = {"name": "Acme", "tokens": {"primary": "#5b4bff", "bg": "#0b1020", "theme": "dark", "radius": 10, "font": "Inter, sans-serif"}, "notes": "Round everything.",
          "components": [{"name": "Pill", "description": "status", "html": "<span class=pill>ok</span>"}]}
    md = D.to_design_md(ds)
    assert md.startswith("---\nversion: alpha\nname: \"Acme\"\ncolors:\n  primary: \"#5b4bff\"")
    for h in ("## Overview", "## Colors", "## Typography", "## Layout", "## Elevation & Depth", "## Shapes", "## Components", "## Do's and Don'ts"):
        assert h in md
    assert md.index("## Overview") < md.index("## Colors") < md.index("## Typography") < md.index("## Layout") < md.index("## Shapes") < md.index("## Components") < md.index("## Do's and Don'ts")
    assert "Round everything." in md and "<span class=pill>ok</span>" in md and "{colors.primary}" in md
    back = D.parse(md)["tokens"]
    assert back["primary"] == "#5b4bff" and back["bg"] == "#0b1020" and back["theme"] == "dark" and back["radius"] == 10 and back["font"] == "Inter, sans-serif"
    # no design system: falls back to the first spec screen's tokens
    md2 = D.to_design_md(None, {"name": "P", "screens": [{"spec": {"tokens": {"primary": "#123456"}}}]})
    assert 'primary: "#123456"' in md2 and 'name: "P"' in md2
