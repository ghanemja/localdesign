import io
import sys
import pytest
import json
import zipfile
from localdesign import pack, components as C
from tests.helpers import post

PROJ = {"id": "p1", "name": "Meal Kit", "designSystem": {"name": "Acme", "tokens": {"primary": "#5b4bff"}, "notes": "Round", "components": [{"name": "Btn", "description": "primary", "html": "<button class=btn>Go</button>"}]},
        "data": {"orders": [{"order": "#1", "total": "$10.00", "when": "2026-01-02"}]},
        "screens": [
            {"title": "Plan Selection", "width": 1280, "brief": "pick a plan", "versions": ["x"], "spec": {"layout": "topnav", "nav": {"brand": "Kit", "items": ["Plans"]}, "sections": [{"type": "heading", "text": "Choose"}, {"type": "table", "title": "Compare", "columns": ["Plan", "Price"], "rows": [["A", "$1"]]}, {"type": "buttons", "items": [{"label": "Continue", "link": "Recipes"}]}]}},
            {"title": "Recipes", "width": 1280, "versions": ["y"], "html": "<html><head><style>:root{--primary:#5b4bff}</style></head><body><nav><a>Plans</a></nav><h1>Pick 3</h1><p>Rotates weekly.</p><form><label>Email</label><input type=email placeholder=you@x></form><button data-link=\"Plan Selection\">Back</button><table><tr><th>Dish</th><th>Time</th></tr><tr><td>Tacos</td><td>20</td></tr></table></body></html>"},
            {"title": "Tip calc", "width": 1280, "kind": "artifact", "versions": ["z"], "html": "<html><body><script>let x=1</script><h1>Tip</h1></body></html>"},
        ]}
PROJ["screens"][0]["html"] = C.render(PROJ["screens"][0]["spec"], 1280)


def test_pack_contents_and_order():
    z = zipfile.ZipFile(io.BytesIO(pack.build_pack(PROJ)))
    names = set(z.namelist())
    for f in ("README.md", "AGENTS.md", "ARCHITECTURE.md", "DESIGN_SYSTEM.md", "FLOWS.md", "DATA.md", "IMPLEMENTATION_PLAN.md", "tokens.css", "components.css",
              "screens/plan-selection.md", "screens/plan-selection.html", "screens/plan-selection.spec.json", "screens/recipes.md", "screens/tip-calc.md", "data/orders.json"):
        assert f in names, f
    arch = z.read("ARCHITECTURE.md").decode()
    assert "Plan Selection" in arch and "flowchart LR" in arch and 'n_Plan_Selection["Plan Selection"] --> n_Recipes["Recipes"]' in arch
    assert "### `orders`" in arch and "`total` | number (formatted)" in arch and "`when` | date" in arch
    assert "### `compare`" in arch                                   # spec table became an entity
    plan = z.read("IMPLEMENTATION_PLAN.md").decode()
    i_plan, i_rec, i_tip = plan.index("**Plan Selection**"), plan.index("**Recipes**"), plan.index("**Tip calc**")
    assert i_plan < i_rec < i_tip                                     # flow order, artifacts last
    assert "screens/plan-selection.md" in plan.split("Prompts you can paste")[1]
    sc = z.read("screens/plan-selection.md").decode()
    assert "### 2. `table`" in sc and '"columns"' in sc and 'class="ld-table"' in sc and "Choose" in sc
    rec = z.read("screens/recipes.md").decode()
    assert "- # Pick 3" in rec and "- Rotates weekly." in rec and "Email — `email`" in rec and "Dish, Time" in rec and "→ Plan Selection" in rec
    tip = z.read("screens/tip-calc.md").decode()
    assert "working artifact" in tip
    ds = z.read("DESIGN_SYSTEM.md").decode()
    assert "`--primary` | `#5b4bff`" in ds and "<button class=btn>Go</button>" in ds and "`table` × 1" in ds
    assert "--primary:#5b4bff" in z.read("tokens.css").decode() and ".ld-card{" in z.read("components.css").decode()
    assert "AGENTS.md" in z.read("README.md").decode()


def test_pack_endpoint(app):
    import urllib.request
    req = urllib.request.Request(app + "/api/export/pack", data=json.dumps({"project": PROJ}).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        assert r.headers["Content-Type"] == "application/zip" and "Meal-Kit-pack.zip" in r.headers["Content-Disposition"]
        z = zipfile.ZipFile(io.BytesIO(r.read()))
        assert "ARCHITECTURE.md" in z.namelist()
    assert post(app + "/api/export/pack", {"project": "nope"})[0] == 400


def test_scan_html_robust_to_garbage():
    out = pack.scan_html("<div><<b>unclosed <table><tr><th>A</th></tr><tr><td>1</td>")
    assert isinstance(out["tables"], list)


# ----------------------------------------------------------------------------- pack v2: VERIFY.md, screenshots, narrative
PNG1 = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8ffff3f0005fe02fea7369d900000000049454e44ae426082")


def test_verify_md_checks():
    v = pack.verify_md(PROJ)
    assert "grep -rqF -- 'var(--primary)' src/" in v                      # tokens referenced, not copied
    assert "the default route `/` renders **Plan Selection**" in v        # no trivial grep for "/"
    assert "grep -rqF -- '/recipes' src/" in v
    assert "grep -rqF -- 'Rotates weekly.' src/" in v and "copy present verbatim" in v
    assert "action “Continue” exists and navigates to **Recipes** (`/recipes`)" in v
    assert "field “Email” (`email`)" in v and "table column “Dish”" in v
    assert "`buttons`, `heading`, `table`" in v                           # spec component types
    assert "fixture `data/orders.json`" in v and "`total`" in v
    assert "reference `<script>` was ported" in v                         # artifact
    assert "## Report format" in v
    z = zipfile.ZipFile(io.BytesIO(pack.build_pack(PROJ)))
    assert "VERIFY.md" in z.namelist() and "VERIFY.md" in z.read("README.md").decode() and "VERIFY.md" in z.read("AGENTS.md").decode()


def test_fonts_skip_var():
    assert pack.fonts_of({"screens": [{"html": "<style>body{font-family:var(--font)} h1{font-family:'Inter',sans-serif}</style>"}]}) == ["Inter,sans-serif"] or \
           pack.fonts_of({"screens": [{"html": "<style>body{font-family:var(--font)} h1{font-family:'Inter',sans-serif}</style>"}]})[0].startswith("Inter")


def test_verify_md_quotes_shell_safely():
    v = pack.verify_md({"name": "q", "screens": [{"title": "It's", "width": 1280, "html": "<h1>Don't \"panic\" $(x)</h1>"}]})
    assert "'Don'\\''t \"panic\" $(x)'" in v


def test_architecture_narrative_section():
    a = pack.architecture_md(PROJ, "Meal Kit is a subscription.\n\n### Loop\nPlan → Recipes.")
    assert a.index("## Narrative") < a.index("## Product overview") and "Meal Kit is a subscription." in a and "Written by the model" in a
    assert "## Narrative" not in pack.architecture_md(PROJ) and "## Narrative" not in pack.architecture_md(PROJ, "  ")


def _fake_chrome(tmp_path, body):
    import os, stat
    p = tmp_path / "chrome"
    p.write_text("#!/usr/bin/env python3\nimport sys\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return str(p)


@pytest.mark.skipif(sys.platform == "win32", reason="fake browser is a shebang script")
def test_screenshot_with_fake_browser(tmp_path, monkeypatch):
    writes_png = _fake_chrome(tmp_path, "out=[a for a in sys.argv if a.startswith('--screenshot=')][0][13:]\n"
                                        "src=[a for a in sys.argv if a.startswith('file://')][0][7:]\nassert '<' in open(src).read()\n"
                                        "assert any(a.startswith('--window-size=') for a in sys.argv)\nopen(out,'wb').write(bytes.fromhex('%s'))\n" % PNG1.hex())
    monkeypatch.setenv("LD_CHROME", writes_png)
    assert pack.find_chrome() == writes_png
    assert pack.screenshot("<h1>hi</h1>", 390) == PNG1
    z = zipfile.ZipFile(io.BytesIO(pack.build_pack(PROJ, screenshot_fn=lambda h, w: pack.screenshot(h, w))))
    assert z.read("screens/plan-selection.png") == PNG1 and z.read("screens/recipes.png") == PNG1
    assert "![Plan Selection — reference screenshot](plan-selection.png)" in z.read("screens/plan-selection.md").decode()
    broken = _fake_chrome(tmp_path, "pass\n")                          # browser exits without writing anything
    monkeypatch.setenv("LD_CHROME", broken)
    assert pack.screenshot("<h1>hi</h1>", 1280) is None
    z = zipfile.ZipFile(io.BytesIO(pack.build_pack(PROJ, screenshot_fn=lambda h, w: pack.screenshot(h, w))))
    assert not [n for n in z.namelist() if n.endswith(".png")] and "reference screenshot" not in z.read("screens/recipes.md").decode()
    monkeypatch.setenv("LD_CHROME", str(tmp_path / "nope"))
    assert pack.find_chrome() is None and pack.screenshot("<h1>hi</h1>", 1280) is None


def test_pack_endpoint_options(app, monkeypatch):
    import urllib.request
    monkeypatch.setenv("LD_CHROME", "/definitely/not/a/browser")
    req = urllib.request.Request(app + "/api/export/pack", data=json.dumps({"project": PROJ, "screenshots": True, "narrative": True}).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        assert "no headless browser" in r.headers["X-LD-Warning"]
        z = zipfile.ZipFile(io.BytesIO(r.read()))
    arch = z.read("ARCHITECTURE.md").decode()
    assert "## Narrative" in arch and "Meal Kit lets a household pick a plan" in arch and "### Core loop" in arch
    assert not [n for n in z.namelist() if n.endswith(".png")]
    from tests.conftest import FakeLLM
    call = FakeLLM.calls[-1]
    assert call["temperature"] == 0.3 and "Plan Selection" in call["messages"][-1]["content"] and "flowchart" in call["messages"][-1]["content"]
    # without the flags: deterministic, no model call, no warning
    n = len(FakeLLM.calls)
    req = urllib.request.Request(app + "/api/export/pack", data=json.dumps({"project": PROJ}).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        assert r.headers.get("X-LD-Warning") is None
        assert "## Narrative" not in zipfile.ZipFile(io.BytesIO(r.read())).read("ARCHITECTURE.md").decode()
    assert len(FakeLLM.calls) == n


def test_config_reports_chrome(app, monkeypatch):
    import urllib.request
    monkeypatch.setenv("LD_CHROME", "/definitely/not/a/browser")
    assert json.loads(urllib.request.urlopen(app + "/api/config").read())["chrome"] is False
