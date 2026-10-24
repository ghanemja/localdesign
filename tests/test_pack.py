import io
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
