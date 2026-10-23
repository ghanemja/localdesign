import re
from localdesign import export as X, components as C

HTML = """<!DOCTYPE html><html><head><title>T</title><style>.a{color:red}</style><script>alert(1)</script></head>
<body><div class="a" style="padding: 4px; --x: 1; background-color: red" onclick="x()"><label for="e">E</label><input id="e" type="email" disabled><br>
<svg viewBox="0 0 10 10" stroke-width="2"><path d="M0 0"/></svg>Text with {braces} &amp; entity<!-- note --></div></body></html>"""


def test_html_to_react_shape():
    r = X.html_to_react(HTML, "Plan selection 2")
    assert r["name"] == "PlanSelection2"
    jsx = r["jsx"]
    assert jsx.startswith('import "./PlanSelection2.css"') and "export default function PlanSelection2()" in jsx
    assert 'className="a"' in jsx and "htmlFor" in jsx and "onclick" not in jsx and "<script" not in jsx and "<style" not in jsx
    assert 'style={{padding: "4px", "--x": "1", backgroundColor: "red"}}' in jsx
    assert "<input" in jsx and "disabled" in jsx and "<br />" in jsx
    assert "viewBox" in jsx and "strokeWidth" in jsx
    assert "{'{'}braces{'}'}" in jsx and "&amp;" in jsx and "{/* note */}" in jsx
    assert r["css"] == ".a{color:red}"


def test_jsx_tags_balance_on_rendered_spec():
    html = C.render(C.EXAMPLE_SPEC, 1280)
    jsx = X.html_to_react(html, "Fleet")["jsx"]
    opens = len(re.findall(r"<([a-z][a-z0-9]*)(?![^>]*/>)[^>]*>", jsx))
    closes = len(re.findall(r"</[a-z][a-z0-9]*>", jsx))
    assert opens == closes


def test_component_name_sanitizes():
    assert X.component_name("123 weird-name!") == "S123WeirdName" and X.component_name("") == "Screen"


def test_design_spec_markdown():
    proj = {"name": "Demo", "designSystem": {"name": "Acme", "tokens": {"primary": "#5b4bff"}, "notes": "Round things", "components": [{"name": "Button", "description": "primary action"}]},
            "data": {"orders": [{"a": 1, "b": 2}]},
            "screens": [{"title": "Home", "width": 1280, "versions": ["x"], "html": '<main><h1>Welcome</h1><a data-link="Pricing">go</a></main>', "brief": "home page"},
                        {"title": "Pricing", "width": 1280, "versions": ["y"], "html": "<p>x</p>", "spec": {"sections": [{"type": "pricing", "tiers": []}, {"type": "stats", "items": [{"label": "MRR"}]}]}}]}
    md = X.design_spec_md(proj)
    assert "# Demo — design spec" in md and "**Acme**" in md and "`primary` | `#5b4bff`" in md
    assert "- Home → Pricing" in md and "**pricing**" in md and "(MRR)" in md and "Welcome" in md
    assert "**orders** — 1 rows" in md and "Round things" in md and "**Button**" in md
