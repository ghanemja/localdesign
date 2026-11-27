import pytest

from localdesign import codebase


def test_clean_path_normalises_and_rejects_escapes():
    assert codebase.clean_path("./src\\pages//a.tsx") == "src/pages/a.tsx"
    assert codebase.clean_path("/src/a.ts") == "src/a.ts"
    assert codebase.clean_path("src/../../etc/passwd") is None
    assert codebase.clean_path("C:/Users/x.ts") is None
    assert codebase.clean_path("") is None and codebase.clean_path(None) is None


@pytest.mark.parametrize("path,ok", [
    ("src/App.tsx", True), ("styles/main.scss", True), ("Dockerfile", True), (".env.example", True), ("api/schema.graphql", True),
    ("node_modules/react/index.js", False), ("web/dist/app.js", False), ("a/.git/config", False), ("package-lock.json", False),
    ("public/app.min.js", False), ("app.js.map", False), (".env", False), (".env.local", False), ("certs/server.key", False),
    ("public/logo.png", False), ("docs/manual.pdf", False), ("py/.venv/lib/x.py", False), ("credentials.json", False),
])
def test_keep_filter(path, ok):
    assert codebase.keep(path) is ok


def test_mentions_resolve_exact_folder_basename_and_stem():
    paths = ["src/pages/Settings.tsx", "src/pages/Schedule.tsx", "src/components/Button.tsx", "src/components/Card.tsx", "README.md"]
    got, bad = codebase.mentions("Redo @src/pages/Settings.tsx.", paths)
    assert got == ["src/pages/Settings.tsx"] and bad == []                       # trailing sentence punctuation ignored
    got, _ = codebase.mentions("use @src/components/ please", paths)
    assert got == ["src/components/Button.tsx", "src/components/Card.tsx"]       # a folder = every file under it
    got, _ = codebase.mentions("like (@Card.tsx) and @button", paths)
    assert got == ["src/components/Card.tsx", "src/components/Button.tsx"]       # basename, and stem case-insensitively
    got, bad = codebase.mentions("email ops@example.com, see @Nope.tsx and @src/pages", paths)
    assert got == ["src/pages/Settings.tsx", "src/pages/Schedule.tsx"] and bad == ["Nope.tsx"]   # emails are not mentions


def test_context_orders_mentions_before_pins_and_respects_budget():
    store = {"name": "app", "files": {"a.ts": "A" * 900, "b.css": ":root{--x:1}", "c.ts": "C" * 5000, "d.ts": "D" * 50}}
    block, info = codebase.context(store, "see @a.ts and @c.ts", ["b.css", "missing.ts"], budget=2500)
    assert block.startswith("Reference material") and block.rstrip().endswith("---")
    assert [f["path"] for f in info["files"]] == ["a.ts", "c.ts"][: len(info["files"])]
    assert info["files"][0]["path"] == "a.ts" and not info["files"][0]["truncated"]
    names = [f["path"] for f in info["files"]] + info["omitted"]
    assert names == ["a.ts", "c.ts", "b.css"]                                     # mentions first, then pins; unknown pins ignored
    assert any(f.get("truncated") for f in info["files"]) or "c.ts" in info["omitted"]
    assert "D" * 50 not in block                                                  # unreferenced files never go in
    assert "Files in the codebase:" in block and "(root): a.ts, b.css, c.ts, d.ts" in block
    assert len(block) < 2500 + 200


def test_tree_text_groups_by_folder_and_caps():
    t = codebase.tree_text([f"src/c/C{i}.tsx" for i in range(200)] + ["package.json"], 2000)
    assert t.startswith("(root): package.json\nsrc/c/: C0.tsx, C1.tsx") and "(+200 total)" in t       # one long folder line is cut short
    t = codebase.tree_text(["package.json"] + [f"pkg{i}/x.ts" for i in range(100)], 600)
    assert t.startswith("(root): package.json") and len(t) <= 650 and t.endswith("more folders")     # shallow folders first, then capped


def test_style_files_prefer_tailwind_then_tokens_then_css_with_variables():
    store = {"files": {"tailwind.config.js": "module.exports={}", "src/theme.ts": "export const t={}", "src/index.css": ":root{--a:#fff}",
                       "src/app.css": "body{margin:0}", "deep/x/tailwind.config.ts": "x"}}
    assert codebase.style_files(store) == ["tailwind.config.js", "deep/x/tailwind.config.ts", "src/theme.ts"]
    store["files"].pop("deep/x/tailwind.config.ts")
    assert codebase.style_files(store) == ["tailwind.config.js", "src/theme.ts", "src/index.css"]   # app.css has no variables


def test_save_load_add_and_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(codebase.config, "CODE_DIR", tmp_path)
    idx = codebase.save("p1", "app", [{"path": "src/a.ts", "content": "a"}, {"path": ".env", "content": "SECRET=1"},
                                      {"path": "bin.dat", "content": "x"}, {"path": "../x.ts", "content": "x"}, {"path": "b.ts", "content": "b\x00"}])
    assert [f["path"] for f in idx["files"]] == ["src/a.ts"] and idx["skipped"] == 4
    idx = codebase.save("p1", "ignored", [{"path": "src/b.ts", "content": "bb"}], add=True)
    assert idx["name"] == "app" and [f["path"] for f in idx["files"]] == ["src/a.ts", "src/b.ts"] and idx["bytes"] == 3
    idx = codebase.save("p1", "new", [{"path": "c.ts", "content": "c"}])                   # replace
    assert [f["path"] for f in idx["files"]] == ["c.ts"] and idx["name"] == "new"
    with pytest.raises(ValueError):
        codebase.save("p2", "x", [{"path": "node_modules/a.js", "content": "x"}])
    assert codebase.delete("p1") and codebase.load("p1") is None and not codebase.delete("p1")
