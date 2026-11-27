"""UI kits: browsable collections of ready-made UI elements (open-source packs from GitHub, or your own) to drop onto screens.

A kit lives in ~/.localdesign/kits/<id>.json:
  {id, name, source: {repo, url, license, license_text}, css (shared, scoped), scope, categories: {cat: n}, skipped: {...},
   items: [{id, name, category, tags, author, html, css, scope}]}

Every element is *scoped* when imported: its root elements get a unique class, every selector is prefixed with it,
:root/html/body rules map onto the element (custom properties only), @keyframes are renamed, @import is dropped.
So an element dropped onto a screen styles itself and nothing else, and two elements' animations never collide.
"""
from __future__ import annotations

import hashlib
import io
import json
import posixpath
import re
import threading
import time
import urllib.error
import urllib.request
import zipfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

from . import config, effects

# Open-source packs the app knows how to import. All pure HTML/CSS (work offline once imported), all MIT.
CATALOG = {
    "uiverse": {"name": "Uiverse Galaxy", "repo": "uiverse-io/galaxy", "branch": "main", "license": "MIT", "url": "https://github.com/uiverse-io/galaxy",
                "desc": "3,000+ community-made buttons, loaders, toggles, cards, inputs, checkboxes, radios, tooltips, notifications and patterns. Many animated. Pure HTML + CSS.", "size": "≈ 20 MB download"},
    "spinkit": {"name": "SpinKit", "repo": "tobiasahlin/SpinKit", "branch": "master", "license": "MIT", "url": "https://github.com/tobiasahlin/SpinKit",
                "desc": "12 classic animated CSS loading spinners.", "size": "≈ 60 KB"},
    "three-dots": {"name": "three-dots", "repo": "nzbin/three-dots", "branch": "master", "license": "MIT", "url": "https://github.com/nzbin/three-dots",
                   "desc": "20 single-element animated dot loaders.", "size": "≈ 300 KB"},
}
MINE = "mine"           # the kit "Save to library" writes into
# Always-available, built-in kits (original effects; not stored on disk, cannot be removed)
BUILTIN = {"fx-shaders": ("Shader backgrounds", "Shaders"), "fx-ascii": ("ASCII effects", "ASCII")}


def _builtin(kit_id: str) -> dict | None:
    if kit_id not in BUILTIN:
        return None
    items = effects.kit_items()[kit_id]
    name, cat = BUILTIN[kit_id]
    return {"id": kit_id, "name": name, "source": {"license": "MIT (localdesign originals)"}, "css": "", "builtin": True,
            "categories": {cat: len(items)}, "skipped": {}, "count": len(items), "items": items}
MAX_ZIP = 120 * 1024 * 1024
MAX_TEXT = 60 * 1024 * 1024
MAX_FILE = 200_000
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def kits_dir() -> Path:
    return config.HOME / "kits"


# ------------------------------------------------------------------ CSS scoping
_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _blocks(css: str):
    """Top-level (prelude, body|None) pairs; body None for statement at-rules (`@import …;`). Quote/paren aware."""
    out, i, n = [], 0, len(css)
    while i < n:
        j, depth, quote = i, 0, None
        while j < n:
            c = css[j]
            if quote:
                if c == "\\":
                    j += 2
                    continue
                if c == quote:
                    quote = None
            elif c in "\"'":
                quote = c
            elif c == "(":
                depth += 1
            elif c == ")":
                depth = max(0, depth - 1)
            elif depth == 0 and c in "{;}":
                break
            j += 1
        pre = css[i:j].strip()
        if j >= n:
            if pre:
                out.append((pre, None))
            break
        if css[j] == ";":
            if pre:
                out.append((pre, None))
            i = j + 1
            continue
        if css[j] == "}":           # stray closer
            i = j + 1
            continue
        k, d, quote = j + 1, 1, None
        while k < n and d:
            c = css[k]
            if quote:
                if c == "\\":
                    k += 2
                    continue
                if c == quote:
                    quote = None
            elif c in "\"'":
                quote = c
            elif c == "{":
                d += 1
            elif c == "}":
                d -= 1
            k += 1
        out.append((pre, css[j + 1:k - 1] if d == 0 else css[j + 1:]))
        i = k
    return out


def _split_top(s: str, sep: str) -> list[str]:
    """Split on `sep` outside (), [] and quotes."""
    parts, cur, depth, quote, i = [], [], 0, None, 0
    while i < len(s):
        c = s[i]
        if quote:
            if c == "\\" and i + 1 < len(s):
                cur.append(s[i:i + 2]); i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c in "([":
            depth += 1
        elif c in ")]":
            depth = max(0, depth - 1)
        elif c == sep and depth == 0:
            parts.append("".join(cur)); cur = []; i += 1
            continue
        cur.append(c); i += 1
    parts.append("".join(cur))
    return parts


def _first_compound(sel: str) -> int:
    """Index where the first compound selector ends (first top-level combinator or whitespace)."""
    depth, quote = 0, None
    for i, c in enumerate(sel):
        if quote:
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif depth == 0 and (c.isspace() or c in ">+~"):
            return i
    return len(sel)


def _with_class(compound: str, cls: str) -> str:
    """'.cta:hover::before' + x → '.cta.x:hover::before' (the class goes before the first pseudo, outside brackets)."""
    depth, quote = 0, None
    for i, c in enumerate(compound):
        if quote:
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif depth == 0 and c == ":":
            return compound[:i] + "." + cls + compound[i:]
    return compound + "." + cls


_ROOTISH = re.compile(r"^(?::root|html|body)(?![\w-])(?:\s+body(?![\w-]))?", re.I)


def _scope_selector(sel: str, cls: str) -> str:
    s = sel.strip()
    if not s:
        return ""
    m = _ROOTISH.match(s)
    if m:                                   # body.dark .x → .cls.dark .x (the dropped element plays the page's role)
        return "." + cls + s[m.end():]
    if s == "*":
        return f".{cls}, .{cls} *"
    k = _first_compound(s)
    return f".{cls} {s}, {_with_class(s[:k], cls)}{s[k:]}"   # inside one of the element's roots, or the root itself


def _decls(body: str) -> list[str]:
    return [d.strip() for d in _split_top(body, ";") if d.strip()]


def _rename_anim(body: str, ren: dict) -> str:
    if not ren:
        return body
    def fix(m):
        v = m.group(2)
        for a, b in ren.items():
            v = re.sub(rf"(?<![\w-]){re.escape(a)}(?![\w-])", b, v)
        return m.group(1) + v
    return re.sub(r"((?:-webkit-|-moz-)?animation(?:-name)?\s*:)([^;}]*)", fix, body, flags=re.I)


def _scope_blocks(css: str, cls: str, root_vars: str, ren: dict) -> str:
    out = []
    for pre, body in _blocks(css):
        low = pre.lower()
        if body is None:
            if not low.startswith(("@import", "@charset", "@tailwind", "@namespace")) and low.startswith("@"):
                out.append(pre + ";")
            continue
        if low.startswith("@"):
            m = re.match(r"@(-webkit-|-moz-)?keyframes\s+([\w-]+)", pre, re.I)
            if m:
                out.append(f"@{m.group(1) or ''}keyframes {ren.get(m.group(2), m.group(2))}{{{body}}}")
            elif re.match(r"@(media|supports|container|layer|document|scope)\b", low):
                out.append(f"{pre}{{{_scope_blocks(body, cls, root_vars, ren)}}}")
            elif not low.startswith(("@tailwind", "@apply", "@import")):
                out.append(f"{pre}{{{body}}}")        # @font-face, @property, @page, @counter-style …
            continue
        body = _rename_anim(body, ren)
        plain, rootish = [], []
        for s in _split_top(pre, ","):
            st = s.strip()
            if not st:
                continue
            (rootish if _ROOTISH.fullmatch(st) else plain).append(st)
        if rootish:   # page-level rules: keep custom properties only (centering, backgrounds, heights are demo scaffolding)
            vars_ = ";".join(d for d in _decls(body) if d.startswith("--"))
            if vars_:
                out.append((":where(:root)" if root_vars == "global" else "." + cls) + "{" + vars_ + "}")
        if plain:
            out.append(", ".join(_scope_selector(s, cls) for s in plain) + "{" + body + "}")
    return "\n".join(out)


def scope_css(css: str, cls: str, root_vars: str = "scope") -> str:
    """Scope a stylesheet to elements carrying `cls`. root_vars='global' keeps :root variables global at zero specificity
    (defaults the page's own variables override), 'scope' moves them onto the element."""
    css = _COMMENT.sub("", css or "")
    names = set(re.findall(r"@(?:-webkit-|-moz-)?keyframes\s+([\w-]+)", css, re.I))
    return _scope_blocks(css, cls, root_vars, {n: f"{n}-{cls}" for n in names})


# ------------------------------------------------------------------ HTML: tag the root elements
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Roots(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.depth, self.roots = 0, []

    def _abs(self):
        line, col = self.getpos()
        return self.line_starts[line - 1] + col

    def handle_starttag(self, tag, attrs):
        if self.depth == 0:
            self.roots.append((self._abs(), self.get_starttag_text()))
        if tag not in _VOID:
            self.depth += 1

    def handle_startendtag(self, tag, attrs):
        if self.depth == 0:
            self.roots.append((self._abs(), self.get_starttag_text()))

    def handle_endtag(self, tag):
        if tag not in _VOID:
            self.depth = max(0, self.depth - 1)


def add_root_class(html: str, cls: str) -> str:
    """Add `cls` to every top-level element (wrap bare text in a span)."""
    p = _Roots()
    p.line_starts = [0] + [m.end() for m in re.finditer(r"\n", html)]
    try:
        p.feed(html); p.close()
    except Exception:  # noqa: BLE001 — malformed markup: fall back to a wrapper
        p.roots = []
    if not p.roots:
        return f'<span class="{cls}">{html}</span>'
    out = html
    for pos, tag in sorted(p.roots, reverse=True):
        if not tag or out[pos:pos + len(tag)] != tag:
            continue
        m = re.search(r"""\sclass\s*=\s*(["'])(.*?)\1""", tag, re.I | re.S)
        if m:
            new = tag[:m.start(2)] + (m.group(2) + " " + cls).strip() + tag[m.end(2):]
        else:
            m2 = re.match(r"<[\w:-]+", tag)
            new = tag[:m2.end()] + f' class="{cls}"' + tag[m2.end():]
        out = out[:pos] + new + out[pos + len(tag):]
    return out


# ------------------------------------------------------------------ reading a pack
def _scope_id(*parts) -> str:
    return "ldk-" + hashlib.sha1("/".join(parts).encode()).hexdigest()[:8]


def fetch_repo(repo: str, branch: str = "", timeout: float = 60) -> dict[str, str]:
    """Download a public GitHub repo's zip (codeload) → {path: text} for .html/.htm/.css/LICENSE files."""
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo or ""):
        raise ValueError("repo must look like owner/name")
    last = None
    for br in [b for b in (branch, "main", "master") if b]:
        url = f"{CODELOAD}/{repo}/zip/refs/heads/{br}"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "localdesign"}), timeout=timeout) as r:
                data = r.read(MAX_ZIP + 1)
            if len(data) > MAX_ZIP:
                raise ValueError(f"{repo} is larger than {MAX_ZIP // 1024 // 1024} MB")
            return read_zip(data)
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} for {url}"
            if e.code != 404:
                break
        except (urllib.error.URLError, OSError) as e:
            raise ValueError(f"cannot download {repo} from GitHub ({getattr(e, 'reason', e)}). Offline? Download the repo zip elsewhere, unzip it, and import the folder.") from None
    raise ValueError(f"cannot download {repo}: {last}")


def _keep_file(name: str) -> bool:
    low = name.lower()
    return low.endswith((".html", ".htm", ".css")) or PurePosixPath(low).name.startswith(("license", "licence", "copying"))


def read_zip(data: bytes) -> dict[str, str]:
    files, total = {}, 0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [i for i in z.infolist() if not i.is_dir()]
        prefix = names[0].filename.split("/")[0] + "/" if names and all(i.filename.startswith(names[0].filename.split("/")[0] + "/") for i in names) else ""
        for i in names:
            if i.file_size > MAX_FILE or not _keep_file(i.filename) or "node_modules/" in i.filename:
                continue
            total += i.file_size
            if total > MAX_TEXT:
                break
            files[i.filename[len(prefix):]] = z.read(i).decode("utf-8", "replace")
    return files


def read_folder(path: str) -> dict[str, str]:
    root = Path(path).expanduser()
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("folder must be an absolute path to an existing directory")
    files, total = {}, 0
    for f in sorted(root.rglob("*")):
        rel = f.relative_to(root).as_posix()
        if not f.is_file() or "node_modules/" in rel or "/." in "/" + rel or not _keep_file(rel) or f.stat().st_size > MAX_FILE:
            continue
        total += f.stat().st_size
        if total > MAX_TEXT:
            break
        files[rel] = f.read_text("utf-8", "replace")
    return files


def from_upload(items: list) -> dict[str, str]:
    files = {}
    for it in items if isinstance(items, list) else []:
        p, c = (it.get("path"), it.get("content")) if isinstance(it, dict) else (None, None)
        if isinstance(p, str) and isinstance(c, str) and _keep_file(p) and len(c) <= MAX_FILE and ".." not in p.split("/"):
            files[p.strip("/")] = c
    first = {p.split("/")[0] for p in files}
    if len(first) == 1 and all("/" in p for p in files):           # a picked folder: drop its own name
        files = {p.split("/", 1)[1]: c for p, c in files.items()}
    return files


# ------------------------------------------------------------------ parsers → items
_UIVERSE = re.compile(r"From Uiverse\.io by\s+(\S+?)\s*-\s*Tags:\s*(.*?)\s*(?:\*/|-->)", re.S)   # authors can contain '-'
CODELOAD = "https://codeload.github.com"
_TW = re.compile(r'class="[^"]*(?<![\w-])(?:flex|grid|bg-[a-z]|text-[a-z]|px-\d|py-\d|p-\d|m[xy]?-\d|rounded(?:-|\b)|w-\d|h-\d|shadow-)')


def _title(s: str) -> str:
    return re.sub(r"[-_]+", " ", s).strip()


def _item(kit_id: str, path: str, html: str, css: str, category: str, name: str, author: str = "", tags=()) -> dict:
    sid = _scope_id(kit_id, path)
    return {"id": sid[4:], "name": name[:60], "category": category, "author": author[:60], "tags": [t for t in tags if t][:12],
            "html": add_root_class(html.strip(), sid), "css": scope_css(css, sid), "scope": sid}


def parse_html_kit(kit_id: str, files: dict[str, str]) -> tuple[list, str, dict]:
    """One element per .html file (inline <style>, or <link> to a stylesheet in the kit). Category = first folder.
    Reads Uiverse's 'From Uiverse.io by <author> - Tags: …' comments. Tailwind-only elements are skipped (need a build)."""
    items, skipped, linked = [], {"tailwind": 0, "empty": 0}, {}
    for path in sorted(p for p in files if p.lower().endswith((".html", ".htm"))):
        text = files[path]
        if PurePosixPath(path).name.lower() in ("index.html", "readme.html") and text.count("<") > 400:
            continue                                     # a demo/index page, not an element
        meta = _UIVERSE.search(text)
        styles = re.findall(r"<style[^>]*>(.*?)</style>", text, re.S | re.I)
        for href in re.findall(r"""<link[^>]+rel=["']?stylesheet[^>]*href=["']([^"']+)""", text, re.I):
            p = "" if href.startswith(("http:", "https:", "//", "/")) else posixpath.normpath(posixpath.join(posixpath.dirname(path), href.split("?")[0]))
            if p in files:
                linked[p] = files[p]
        body = re.sub(r"<style[^>]*>.*?</style>|<script\b.*?</script>|<link[^>]*>|<!--.*?-->", "", text, flags=re.S | re.I)
        m = re.search(r"<body[^>]*>(.*)</body>", body, re.S | re.I)
        body = (m.group(1) if m else re.sub(r"</?(?:html|head|body|!doctype)[^>]*>|<(?:meta|title)[^>]*>.*?(?:</title>)?", "", body, flags=re.S | re.I)).strip()
        if not body:
            skipped["empty"] += 1
            continue
        if not styles and not linked and _TW.search(body):
            skipped["tailwind"] += 1
            continue
        parts = PurePosixPath(path).parts
        category = _title(parts[0]).capitalize() if len(parts) > 1 else "Elements"
        stem = PurePosixPath(path).stem
        author, slug = (stem.split("_", 1) if meta and "_" in stem else ("", stem))
        if meta:
            author = meta.group(1).strip()
        tags = [t.strip() for t in meta.group(2).split(",")] if meta else []
        items.append(_item(kit_id, path, body, "\n".join(styles), category, _title(re.sub(r"-\d+$", "", slug)) or stem, author, tags))
    kit_cls = _scope_id(kit_id, "__kit__")
    shared = scope_css("\n".join(linked.values()), kit_cls) if linked else ""
    if shared:
        for it in items:
            it["html"] = add_root_class(it["html"], kit_cls) if f'class="{kit_cls}' not in it["html"] else it["html"]
    return items, shared, skipped


def parse_css_kit(kit_id: str, css: str, items_html: list[tuple[str, str]], category: str) -> tuple[list, str, dict]:
    """A kit that is one stylesheet + markup per element (SpinKit, three-dots): the stylesheet is scoped once, shared."""
    cls = _scope_id(kit_id, "__kit__")
    items = [{"id": _scope_id(kit_id, name)[4:], "name": name, "category": category, "author": "", "tags": [category.lower()],
              "html": add_root_class(html, cls), "css": "", "scope": cls} for name, html in items_html]
    return items, scope_css(css, cls), {}


def parse(kit_id: str, files: dict[str, str]) -> tuple[list, str, dict]:
    if "spinkit.css" in files:
        css = files["spinkit.css"]
        found = re.findall(r"/\*\s*([A-Z][\w ]+?)\s*\n\s*(<div class=\"sk-.*?)\s*\*/", css, re.S)
        return parse_css_kit(kit_id, css, [(n.strip(), re.sub(r"\n\s+", "", h)) for n, h in found], "Loaders")
    if "dist/three-dots.css" in files:
        css = files["dist/three-dots.css"]
        names = sorted(set(re.findall(r"(?m)^\.(dot-[a-z-]+)\s*\{", css)))
        return parse_css_kit(kit_id, css, [(_title(n), f'<div class="{n}" style="margin:12px 28px"></div>') for n in names], "Loaders")
    return parse_html_kit(kit_id, files)


def detect(files: dict[str, str]) -> str | None:
    """Which catalog pack a downloaded/unzipped folder is (so an offline import is the same kit as a download)."""
    if "spinkit.css" in files:
        return "spinkit"
    if "dist/three-dots.css" in files:
        return "three-dots"
    html = [c for p, c in files.items() if p.lower().endswith(".html")]
    if html and sum("From Uiverse.io" in c for c in html[:200]) > min(len(html), 200) // 2:
        return "uiverse"
    return None


def _license(files: dict[str, str]) -> str:
    for p, c in files.items():
        if "/" not in p and PurePosixPath(p).name.lower().startswith(("license", "licence", "copying")):
            return c[:4000]
    return ""


# ------------------------------------------------------------------ store + query
_CACHE: dict[str, tuple[tuple[int, int], dict]] = {}
_LOCK = threading.Lock()


def install(kit_id: str, name: str, files: dict[str, str], source: dict) -> dict:
    if not _ID.match(kit_id):
        raise ValueError("bad kit id")
    items, shared, skipped = parse(kit_id, files)
    if not items:
        raise ValueError("no usable elements found (expects .html files with inline <style>, or a supported pack)"
                         + (f"; {skipped.get('tailwind')} Tailwind-only files skipped" if skipped.get("tailwind") else ""))
    cats: dict[str, int] = {}
    for it in items:
        cats[it["category"]] = cats.get(it["category"], 0) + 1
    kit = {"id": kit_id, "name": name, "source": {**source, "license_text": _license(files)}, "css": shared,
           "categories": dict(sorted(cats.items())), "skipped": skipped, "count": len(items), "installed": time.time(), "items": items}
    _save(kit_id, kit)
    return summary(kit)


def _save(kit_id: str, kit: dict) -> None:
    """Write a kit and drop its cache entry (mtimes can repeat on coarse clocks, e.g. Windows, so never rely on them alone)."""
    kits_dir().mkdir(parents=True, exist_ok=True)
    (kits_dir() / f"{kit_id}.json").write_text(json.dumps(kit))
    with _LOCK:
        _CACHE.pop(kit_id, None)


def summary(kit: dict) -> dict:
    return {k: v for k, v in kit.items() if k != "items" and k != "css"} | {"source": {k: v for k, v in kit.get("source", {}).items() if k != "license_text"}}


def load(kit_id: str) -> dict | None:
    if kit_id in BUILTIN:
        return _builtin(kit_id)
    if not _ID.match(kit_id or ""):
        return None
    f = kits_dir() / f"{kit_id}.json"
    try:
        st = f.stat()
        mt = (st.st_mtime_ns, st.st_size)
    except OSError:
        return None
    with _LOCK:
        hit = _CACHE.get(kit_id)
        if hit and hit[0] == mt:
            return hit[1]
        try:
            kit = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        _CACHE[kit_id] = (mt, kit)
        return kit


def installed() -> list[dict]:
    d = kits_dir()
    out = [summary(k) for f in sorted(d.glob("*.json")) if f.stem not in BUILTIN and (k := load(f.stem))] if d.is_dir() else []
    return sorted(out, key=lambda k: (k["id"] != MINE, -k.get("count", 0))) + [summary(_builtin(b)) for b in BUILTIN]


def delete(kit_id: str) -> bool:
    if kit_id in BUILTIN or not _ID.match(kit_id or ""):
        return False
    with _LOCK:
        _CACHE.pop(kit_id, None)
    try:
        (kits_dir() / f"{kit_id}.json").unlink()
        return True
    except FileNotFoundError:
        return False


def query(kit_id: str = "", q: str = "", category: str = "", offset: int = 0, limit: int = 48) -> dict:
    kits = [k for k in ([load(kit_id)] if kit_id else [load(s["id"]) for s in installed()]) if k]
    words = [w for w in re.split(r"\s+", (q or "").lower()) if w]
    hits = []
    for k in kits:
        for it in k["items"]:
            if category and it["category"] != category:
                continue
            if words:
                hay = " ".join([it["name"], it["category"], it.get("author", ""), " ".join(it.get("tags", []))]).lower()
                if not all(w in hay for w in words):
                    continue
            hits.append((k, it))
    page = hits[max(0, offset): max(0, offset) + max(1, min(limit, 200))]
    return {"total": len(hits), "items": [{**it, "kit": k["id"], "kit_name": k["name"], "license": it.get("license") or k.get("source", {}).get("license", ""),
                                           "repo": k.get("source", {}).get("repo", ""), "shared_css": k.get("css", ""), "kit_scope": _scope_id(k["id"], "__kit__")}
                                          for k, it in page]}


def add_mine(name: str, html: str, category: str = "Saved") -> dict:
    """'Save to library' from the canvas: the element's markup with computed styles inlined, into the 'My components' kit."""
    if "<" not in (html or "") or len(html) > MAX_FILE:
        raise ValueError("need the element's HTML (under 200 KB)")
    kit = load(MINE) or {"id": MINE, "name": "My components", "source": {"license": "yours"}, "css": "", "categories": {}, "skipped": {}, "items": []}
    kit = json.loads(json.dumps(kit))   # don't mutate the cache
    sid = _scope_id(MINE, str(time.time()), name)
    html = re.sub(r"<script\b.*?</script>", "", html, flags=re.S | re.I)
    kit["items"].insert(0, {"id": sid[4:], "name": (name or "component").strip()[:60], "category": category[:40] or "Saved", "author": "", "tags": [],
                            "html": add_root_class(html.strip(), sid), "css": "", "scope": sid})
    kit["categories"] = {}
    for it in kit["items"]:
        kit["categories"][it["category"]] = kit["categories"].get(it["category"], 0) + 1
    kit["count"] = len(kit["items"])
    _save(MINE, kit)
    return kit["items"][0]


def add_shader(name: str, glsl: str, author: str = "", source_url: str = "", license_: str = "") -> dict:
    """A shader the user pasted (e.g. from Shadertoy) → My components, with its credit and license kept in the markup."""
    if "mainImage" not in (glsl or "") or len(glsl) > 60_000:
        raise ValueError("paste a Shadertoy-style shader: it needs a mainImage(out vec4, in vec2) function (single pass, under 60 KB)")
    lic = (license_ or "").strip() or effects.detect_license(glsl)
    credit = " · ".join(x for x in [name.strip(), f"by {author.strip()}" if author.strip() else "", source_url.strip(), lic] if x)
    kit = json.loads(json.dumps(load(MINE) or {"id": MINE, "name": "My components", "source": {"license": "yours"}, "css": "", "categories": {}, "skipped": {}, "items": []}))
    item = {"id": _scope_id(MINE, "shader", str(time.time()))[4:], "name": (name or "My shader").strip()[:60], "category": "Shaders", "author": author.strip()[:60],
            "tags": ["shader", "shadertoy"] + (["non-commercial"] if "NC" in lic else []), "license": lic, "source_url": source_url.strip()[:300],
            "html": effects.custom_shader_html(glsl, (name or "My shader").strip()[:60], credit) + effects.RUNTIME_TAG, "css": "", "scope": "", "fx": True,
            "uses_channels": bool(re.search(r"\biChannel\d", glsl))}
    kit["items"].insert(0, item)
    kit["categories"] = {}
    for it in kit["items"]:
        kit["categories"][it["category"]] = kit["categories"].get(it["category"], 0) + 1
    kit["count"] = len(kit["items"])
    _save(MINE, kit)
    return item


def remove_item(kit_id: str, item_id: str) -> bool:
    kit = load(kit_id)
    if not kit or kit.get("builtin"):
        return False
    kit = json.loads(json.dumps(kit))
    n = len(kit["items"])
    kit["items"] = [it for it in kit["items"] if it["id"] != item_id]
    if len(kit["items"]) == n:
        return False
    kit["count"] = len(kit["items"])
    kit["categories"] = {}
    for it in kit["items"]:
        kit["categories"][it["category"]] = kit["categories"].get(it["category"], 0) + 1
    _save(kit_id, kit)
    return True
