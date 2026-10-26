"""Implementation pack: the project as a set of Markdown files a coding agent (or human) can build from.

Deterministic — derived from the screens' HTML/specs, links, design system, data sources and assets.
Produces a zip:
  README.md                 how to use the pack with an LLM / agent
  ARCHITECTURE.md           product overview, screen inventory, navigation graph, inferred data model, routes, state
  DESIGN_SYSTEM.md          tokens, typography, components, guidelines
  FLOWS.md                  user journeys from the links
  DATA.md                   data sources: schema + sample rows
  IMPLEMENTATION_PLAN.md    ordered, checkbox tasks for an agent, with copy-paste prompts
  VERIFY.md                 checks an agent can run against its implementation (grep-able copy, routes, tokens)
  screens/<slug>.png        optional screenshot of the reference rendering (headless Chrome/Chromium/Edge, if installed)
  screens/<slug>.md         per screen: purpose, layout, content inventory, interactions, acceptance criteria
  screens/<slug>.html       the reference rendering (self-contained)
  assets/…                  uploaded brand assets
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from html.parser import HTMLParser

from . import export as X

ROOT_VARS = re.compile(r":root\s*\{([^}]*)\}", re.S)
VAR = re.compile(r"--([a-zA-Z0-9_-]+)\s*:\s*([^;}]+);?")
FONT = re.compile(r"font-family\s*:\s*([^;}]+)")


def slug(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (t or "screen").lower()).strip("-")[:60] or "screen"


# ----------------------------------------------------------------------------- HTML structure extraction
class _Scan(HTMLParser):
    """Pulls the content inventory out of a screen: headings, nav, buttons/links, fields, tables, links."""
    INTERACTIVE = {"button", "a", "input", "select", "textarea"}

    def __init__(self):
        super().__init__()
        self.headings, self.buttons, self.fields, self.tables, self.nav, self.links, self.images, self.copy = [], [], [], [], [], [], [], []
        self.text_words = 0
        self._stack: list[tuple[str, dict]] = []
        self._cur_table: dict | None = None
        self._in_th = self._in_nav = False
        self._skip = 0
        self._label = ""
        self._buf = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "head", "title"):
            self._skip += 1
        self._stack.append((tag, a))
        if tag == "nav":
            self._in_nav = True
        if tag == "table":
            self._cur_table = {"columns": [], "rows": 0}
            self.tables.append(self._cur_table)
        if tag == "th":
            self._in_th = True
        if tag == "tr" and self._cur_table is not None:
            self._cur_table["rows"] += 1
        if tag == "input" and a.get("type") not in ("hidden", "submit", "button"):
            self.fields.append({"label": self._label or a.get("placeholder") or a.get("name") or a.get("id") or "", "type": a.get("type", "text"), "placeholder": a.get("placeholder", "")})
            self._label = ""
        if tag in ("select", "textarea"):
            self.fields.append({"label": self._label or a.get("name") or "", "type": tag, "placeholder": a.get("placeholder", "")})
            self._label = ""
        if tag == "img":
            self.images.append(a.get("src", ""))
        if a.get("data-link"):
            self.links.append({"target": a["data-link"], "tag": tag})
        self._buf = ""

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head", "title"):
            self._skip = max(0, self._skip - 1)
        txt = re.sub(r"\s+", " ", self._buf).strip()
        if tag in ("h1", "h2", "h3", "h4") and txt:
            self.headings.append((int(tag[1]), txt[:120]))
        elif tag == "label" and txt:
            self._label = txt[:60]
            self.copy.append(txt)
        elif tag in ("p", "li", "td", "span", "small", "dd", "dt", "figcaption") and txt and 2 <= len(txt) <= 200:
            self.copy.append(txt)
        elif tag == "th" and txt and self._cur_table is not None:
            self._cur_table["columns"].append(txt[:40])
        elif tag in ("button", "a") and txt and len(txt) < 60:
            link = next((a.get("data-link") for t, a in reversed(self._stack) if t == tag), None)
            if self._in_nav:
                self.nav.append(txt)
            else:
                self.buttons.append({"text": txt, "link": link})
        if tag == "nav":
            self._in_nav = False
        if tag == "table":
            self._cur_table = None
            if self.tables:
                self.tables[-1]["rows"] = max(0, self.tables[-1]["rows"] - 1)   # header row
        if tag == "th":
            self._in_th = False
        while self._stack and self._stack[-1][0] != tag:
            self._stack.pop()
        if self._stack:
            self._stack.pop()
        self._buf = ""

    def handle_data(self, data):
        if self._skip:
            return
        self._buf += data
        self.text_words += len(data.split())


def scan_html(html: str) -> dict:
    p = _Scan()
    try:
        p.feed(html or "")
    except Exception:  # never fail an export over odd markup
        pass
    seen = set()
    buttons = [b for b in p.buttons if not (b["text"] in seen or seen.add(b["text"]))]
    return {"headings": p.headings[:40], "buttons": buttons[:40], "fields": p.fields[:40], "tables": p.tables[:10], "nav": list(dict.fromkeys(p.nav))[:20],
            "links": p.links, "images": p.images[:20], "words": p.text_words, "copy": list(dict.fromkeys(p.copy))[:120]}


def tokens_of(project: dict) -> dict:
    ds = project.get("designSystem") or {}
    t = {k: v for k, v in (ds.get("tokens") or {}).items() if v}
    if not t:
        for s in project.get("screens") or []:
            m = ROOT_VARS.search(s.get("html") or "")
            if m:
                t = {k: v.strip() for k, v in VAR.findall(m.group(1))}
                break
    return t


def fonts_of(project: dict) -> list[str]:
    out = []
    for s in project.get("screens") or []:
        for f in FONT.findall(s.get("html") or ""):
            f = f.strip().strip("'\"")
            if f and not f.startswith("var(") and f not in out:
                out.append(f)
    return out[:5]


# ----------------------------------------------------------------------------- per-screen doc
def screen_md(s: dict, project: dict, index: int, png: bool = False) -> str:
    scan = scan_html(s.get("html") or "")
    spec = s.get("spec")
    kind = "Interactive artifact" if s.get("kind") == "artifact" else "Screen"
    L = [f"# {s.get('title')}", "", f"_{kind} {index} · {s.get('width')}px wide · reference rendering: `screens/{slug(s.get('title'))}.html`_", ""]
    if png:
        L += [f"![{s.get('title')} — reference screenshot]({slug(s.get('title'))}.png)", ""]
    if s.get("brief"):
        L += ["## Purpose", "", s["brief"].strip(), ""]
    L += ["## Layout", ""]
    if spec and spec.get("sections"):
        layout = spec.get("layout", "plain")
        nav = spec.get("nav") or {}
        L.append(f"- Shell: **{layout}**" + (f" — brand “{nav.get('brand')}”, nav items: {', '.join(nav.get('items') or [])}, active: {nav.get('active')}" if nav else ""))
        L.append("- Sections, top to bottom:")
        for n in spec["sections"]:
            L += ["  - " + line for line in _spec_lines(n)]
    else:
        if scan["nav"]:
            L.append(f"- Navigation: {', '.join(scan['nav'])}")
        if scan["headings"]:
            L.append("- Structure (headings):")
            for lvl, txt in scan["headings"]:
                L.append(f"  {'  ' * (lvl - 1)}- {txt}")
        if not scan["nav"] and not scan["headings"]:
            L.append("- See the reference HTML; no explicit section structure was detected.")
    L.append("")
    if spec and spec.get("sections"):
        L += ["## Sections — exact content and reference markup", "",
              "Each section below gives the content as structured data (`props`) and the exact HTML the designer saw. Build a component per section type; feed it the props. The CSS classes are defined in `components.css`.", ""]
        from . import components as C
        ctx = {"data": project.get("data") or {}}
        for i, n in enumerate(spec["sections"], 1):
            t = n.get("type", "?")
            props = {k: v for k, v in n.items() if k != "type"}
            frag = C.render_node(n, ctx)
            L += [f"### {i}. `{t}`", "", "props:", "", "```json", json.dumps(props, indent=2, ensure_ascii=False)[:4000], "```", "", "reference markup:", "", "```html", frag[:6000] + ("\n<!-- truncated -->" if len(frag) > 6000 else ""), "```", ""]
    # content inventory
    L += ["## Content inventory", ""]
    if scan["tables"]:
        for t in scan["tables"]:
            L.append(f"- Table: columns {', '.join(t['columns']) or '(no header)'} · {t['rows']} sample rows")
    if scan["fields"]:
        L.append("- Form fields:")
        for f in scan["fields"]:
            L.append(f"  - {f['label'] or '(unlabelled)'} — `{f['type']}`" + (f", placeholder “{f['placeholder']}”" if f["placeholder"] else ""))
    if scan["buttons"]:
        L.append("- Actions: " + " · ".join(f"**{b['text']}**" + (f" → {b['link']}" if b["link"] else "") for b in scan["buttons"][:20]))
    if scan["images"]:
        L.append("- Images/assets: " + ", ".join(f"`{i}`" for i in scan["images"][:8]))
    L.append(f"- Copy volume: ~{scan['words']} words")
    L.append("")
    if scan["copy"] or scan["headings"]:
        L += ["## Copy (all visible text, use verbatim)", ""]
        seen = set()
        for lvl, h in scan["headings"]:
            if h not in seen:
                seen.add(h); L.append(f"- {'#' * lvl} {h}")
        for c in scan["copy"]:
            if c not in seen:
                seen.add(c); L.append(f"- {c}")
        L.append("")
    # interactions
    links = sorted({l["target"] for l in scan["links"]})
    L += ["## Interactions & navigation", ""]
    if links:
        L += [f"- Navigates to: {', '.join(links)} (elements carry `data-link=\"<screen title>\"` in the reference HTML)"]
    else:
        L += ["- No outgoing navigation defined. Treat buttons as local actions or wire them in the flow."]
    if s.get("kind") == "artifact":
        L += ["- This is a working artifact: the reference HTML contains the behaviour in its `<script>`; port the logic, do not just copy the markup."]
    L.append("")
    L += ["## Acceptance criteria", ""]
    L += [f"- [ ] Matches the reference rendering at {s.get('width')}px (layout, hierarchy, spacing, colour) and degrades sensibly at other widths"]
    for t in scan["tables"]:
        L.append(f"- [ ] Table renders the real data source (columns: {', '.join(t['columns'])}) with sorting/empty state")
    if scan["fields"]:
        L.append("- [ ] Form validates required fields and shows inline errors; submit is disabled while pending")
    for t in links:
        L.append(f"- [ ] “{t}” navigation works and is reachable by keyboard")
    L += ["- [ ] All text comes from a copy file / i18n, not hard-coded", "- [ ] Accessible names on controls; colour contrast ≥ 4.5:1 for text", ""]
    return "\n".join(L)


def _spec_lines(n: dict, depth: int = 0) -> list[str]:
    if not isinstance(n, dict):
        return []
    t = n.get("type", "?")
    label = n.get("title") or n.get("text") or n.get("label") or ""
    detail = ""
    if t == "stats":
        detail = ": " + ", ".join(f"{i.get('label')} = {i.get('value')}" for i in (n.get("items") or []) if isinstance(i, dict))
    elif t == "table":
        detail = f": columns {', '.join(map(str, n.get('columns') or []))}" + (f" · from data source `{n['data']}`" if n.get("data") else f" · {len(n.get('rows') or [])} rows")
    elif t == "form":
        detail = ": fields " + ", ".join(f"{f.get('label')} ({f.get('type', 'text')})" for f in (n.get("fields") or []) if isinstance(f, dict)) + (f" · submit “{n.get('submit')}”" if n.get("submit") else "")
    elif t == "chart":
        detail = f": {n.get('kind', 'line')} chart, series {', '.join(s.get('name', '') for s in (n.get('series') or []) if isinstance(s, dict))}"
    elif t in ("list", "timeline", "chat", "settings", "kv"):
        detail = f": {len(n.get('items') or n.get('messages') or [])} items"
    elif t == "buttons":
        detail = ": " + ", ".join(f"{b.get('label')}" + (f" → {b['link']}" if b.get("link") else "") for b in (n.get("items") or []) if isinstance(b, dict))
    elif t == "pricing":
        detail = ": tiers " + ", ".join(f"{x.get('name')} {x.get('price')}" for x in (n.get("tiers") or []) if isinstance(x, dict))
    elif t in ("grid", "split"):
        detail = f" ({n.get('cols') or n.get('ratio') or ''})".replace(" ()", "")
    out = [f"**{t}**" + (f" — {label}" if label else "") + detail]
    for c in n.get("children") or []:
        out += ["  " + l for l in _spec_lines(c, depth + 1)]
    return out


# ----------------------------------------------------------------------------- project-level docs
def _graph(project: dict) -> list[tuple[str, str]]:
    edges = []
    for s in project.get("screens") or []:
        for t in sorted(set(re.findall(r'data-link="([^"]*)"', s.get("html") or ""))):
            if t and t != s["title"] and any(o["title"].strip().lower() == t.strip().lower() for o in project["screens"]):
                edges.append((s["title"], t))
    return edges


def _data_model(project: dict) -> list[dict]:
    """Entities inferred from data sources, spec tables and HTML tables/forms."""
    ents: dict[str, dict] = {}
    for name, rows in (project.get("data") or {}).items():
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            ents[name] = {"fields": [{"name": k, "type": _guess_type(rows[0][k]), "example": rows[0][k]} for k in rows[0]], "source": "data source", "rows": len(rows)}
    for s in project.get("screens") or []:
        spec = s.get("spec")
        nodes = _walk(spec.get("sections")) if spec else []
        for n in nodes:
            if n.get("type") == "table" and n.get("columns") and not n.get("data"):
                key = slug(n.get("title") or s["title"]).replace("-", "_")
                ents.setdefault(key, {"fields": [{"name": slug(c).replace("-", "_"), "type": "string", "example": ""} for c in n["columns"]], "source": f"table on “{s['title']}”", "rows": len(n.get("rows") or [])})
            if n.get("type") == "form" and n.get("fields"):
                key = slug(n.get("title") or s["title"] + " form").replace("-", "_")
                ents.setdefault(key, {"fields": [{"name": slug(f.get("label", "field")).replace("-", "_"), "type": f.get("type", "text"), "example": f.get("value", "")} for f in n["fields"] if isinstance(f, dict)], "source": f"form on “{s['title']}”", "rows": 0})
        if not spec:
            sc = scan_html(s.get("html") or "")
            for t in sc["tables"]:
                if t["columns"]:
                    key = slug(s["title"]).replace("-", "_") + "_rows"
                    ents.setdefault(key, {"fields": [{"name": slug(c).replace("-", "_"), "type": "string", "example": ""} for c in t["columns"]], "source": f"table on “{s['title']}”", "rows": t["rows"]})
            if sc["fields"]:
                key = slug(s["title"]).replace("-", "_") + "_form"
                ents.setdefault(key, {"fields": [{"name": slug(f["label"] or f["type"]).replace("-", "_"), "type": f["type"], "example": f["placeholder"]} for f in sc["fields"]], "source": f"form on “{s['title']}”", "rows": 0})
    return [{"name": k, **v} for k, v in ents.items()]


def _walk(nodes):
    out = []
    for n in nodes or []:
        if isinstance(n, dict):
            out.append(n)
            out += _walk(n.get("children"))
    return out


def _guess_type(v) -> str:
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    s = str(v)
    if re.fullmatch(r"[$€£]?\s?-?[\d,]+(\.\d+)?%?", s):
        return "number (formatted)"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", s):
        return "date"
    if "@" in s and "." in s:
        return "email"
    return "string"


def architecture_md(project: dict, narrative: str | None = None) -> str:
    screens = project.get("screens") or []
    edges = _graph(project)
    entry = screens[0]["title"] if screens else "—"
    L = [f"# {project.get('name') or 'Untitled'} — architecture", "",
         "This document describes a product designed in localdesign. It is written for an implementing engineer or coding agent.",
         "Read it first, then `IMPLEMENTATION_PLAN.md`, then each `screens/*.md` as you build it. The `.html` files beside them are the visual source of truth.", ""]
    if narrative and narrative.strip():
        L += ["## Narrative", "", "_Written by the model from the designs below. Everything after this section is derived deterministically from the screens; where the two disagree, the derived sections and the HTML win._", "",
              narrative.strip(), ""]
    L += ["## Product overview", ""]
    kinds = {"screen": sum(1 for s in screens if s.get("kind") != "artifact"), "artifact": sum(1 for s in screens if s.get("kind") == "artifact")}
    L += [f"- {kinds['screen']} screens" + (f" and {kinds['artifact']} interactive artifacts" if kinds["artifact"] else "") + f"; entry point: **{entry}**."]
    widths = sorted({s.get("width") for s in screens})
    L += [f"- Target widths designed: {', '.join(f'{w}px' for w in widths)}. Implement responsively; the designs are the reference at those widths."]
    if project.get("designSystem", {}) and project["designSystem"].get("name"):
        L += [f"- Design system: **{project['designSystem']['name']}** (see `DESIGN_SYSTEM.md`)."]
    briefs = [s.get("brief") for s in screens if s.get("brief")]
    if briefs:
        L += ["", "What the screens are for, in the designer's words:", ""] + [f"- **{s['title']}** — {s['brief'].strip()}" for s in screens if s.get("brief")]
    L += ["", "## Screen inventory", "", "| # | Screen | Width | Kind | Links to | Doc |", "|---|---|---|---|---|---|"]
    for i, s in enumerate(screens, 1):
        outs = [b for a, b in edges if a == s["title"]]
        L.append(f"| {i} | {s['title']} | {s.get('width')}px | {'artifact' if s.get('kind') == 'artifact' else 'screen'} | {', '.join(outs) or '—'} | `screens/{slug(s['title'])}.md` |")
    L += ["", "## Navigation graph", ""]
    if edges:
        L += ["```mermaid", "flowchart LR"] + [f'  {_mid(a)}["{a}"] --> {_mid(b)}["{b}"]' for a, b in edges] + ["```", ""]
        L += ["Suggested routes:", ""] + [f"- `/{slug(s['title'])}` → {s['title']}" + ("  (default route)" if i == 0 else "") for i, s in enumerate(screens)]
    else:
        L += ["No navigation links were defined between screens. Treat each screen as its own route:", ""] + [f"- `/{slug(s['title'])}` → {s['title']}" for s in screens]
    L += ["", "## Data model (inferred)", "", "Derived from data sources, tables and forms in the designs. Rename freely; keep the fields.", ""]
    ents = _data_model(project)
    if not ents:
        L += ["_No tables, forms or data sources — the screens are static content._"]
    for e in ents:
        L += [f"### `{e['name']}`", "", f"_From: {e['source']}" + (f" · {e['rows']} sample rows_" if e.get("rows") else "_"), "", "| field | type | example |", "|---|---|---|"]
        L += [f"| `{f['name']}` | {f['type']} | {str(f.get('example', ''))[:40]} |" for f in e["fields"]]
        L.append("")
    L += ["## State & behaviour", ""]
    forms = [s["title"] for s in screens if scan_html(s.get("html") or "")["fields"]]
    tables = [s["title"] for s in screens if scan_html(s.get("html") or "")["tables"]]
    if forms:
        L.append(f"- Forms on: {', '.join(forms)} — client-side validation, pending/disabled submit, error states.")
    if tables:
        L.append(f"- Data tables on: {', '.join(tables)} — loading skeleton, empty state, sort by column; pagination if > 50 rows.")
    arts = [s for s in screens if s.get("kind") == "artifact"]
    for a in arts:
        L.append(f"- Artifact **{a['title']}**: behaviour is specified by the `<script>` in `screens/{slug(a['title'])}.html`; port it faithfully.")
    if not (forms or tables or arts):
        L.append("- Mostly static screens; state is navigation only.")
    L += ["", "## Suggested structure", "", "```", "src/", "  app/            routes, one per screen", "  components/     shared UI (see DESIGN_SYSTEM.md → Components)", "  styles/         tokens.css generated from DESIGN_SYSTEM.md", "  data/           types + mock data from DATA.md", "  assets/         copied from assets/", "```", ""]
    L += ["## Non-goals / open questions", "", "- Auth, permissions and backend persistence are not in the designs — confirm before building.", "- Copy is sample text unless `DATA.md` lists a real source for it.", ""]
    return "\n".join(L)


def _mid(t: str) -> str:
    return "n_" + re.sub(r"[^a-zA-Z0-9]", "_", t)[:30]


def design_system_md(project: dict) -> str:
    ds = project.get("designSystem") or {}
    tk = tokens_of(project)
    L = [f"# Design system" + (f": {ds['name']}" if ds.get("name") else ""), ""]
    L += ["## Tokens", "", "Generate `tokens.css` from this table. Every colour, radius and font in the screens maps to one of these.", "", "| token | value |", "|---|---|"]
    L += [f"| `--{k}` | `{v}` |" for k, v in tk.items()] or ["| _none captured_ | the screens define inline styles; extract from the reference HTML |"]
    fonts = fonts_of(project)
    if fonts or tk.get("font"):
        L += ["", "## Typography", ""] + [f"- Font stack: `{f}`" for f in ([tk["font"]] if tk.get("font") else fonts)]
        L += ["- Scale (from the screens): h1 ≈ 26px/700, h3 ≈ 15px/600, body 14px/400, small 13px, stat numbers 30px/700. Letter-spacing −0.02em on large headings."]
    L += ["", "## Spacing & shape", "", f"- Base radius `{tk.get('radius', 12)}px` for cards, `{max(4, int(tk.get('radius', 12)) - 4) if str(tk.get('radius', 12)).isdigit() else 8}px` for controls.", "- Page padding 32px desktop / 16px phone; grid gap 20px; card padding 20px.", "- Cards: surface colour, 1px line border, radius; no heavy shadows."]
    if ds.get("notes"):
        L += ["", "## Guidelines", "", ds["notes"]]
    comps = ds.get("components") or []
    L += ["", "## Components", ""]
    if comps:
        L += ["Reuse this exact markup/classes (from the design system):", ""]
        for c in comps:
            L += [f"### {c.get('name')}", "", c.get("description", ""), "", "```html", (c.get("html") or "").strip(), "```", ""]
    # built-in components used by spec screens
    used = {}
    for s in project.get("screens") or []:
        if s.get("spec"):
            for n in _walk(s["spec"].get("sections")):
                used[n.get("type")] = used.get(n.get("type"), 0) + 1
    if used:
        L += ["Components used across the spec-rendered screens (build these once, reuse everywhere):", ""]
        L += [f"- `{k}` × {v}" for k, v in sorted(used.items(), key=lambda x: -x[1])]
        L += ["", "Their reference CSS classes are `.ld-*` in the screens' `<style>` blocks (e.g. `.ld-card`, `.ld-stat`, `.ld-table`, `.ld-btn.primary`)."]
    if ds.get("css"):
        L += ["", "## Base CSS (include verbatim)", "", "```css", ds["css"].strip(), "```"]
    L.append("")
    return "\n".join(L)


def flows_md(project: dict) -> str:
    screens = project.get("screens") or []
    edges = _graph(project)
    L = ["# Flows", ""]
    if not edges:
        L += ["No links between screens were defined. If the product has journeys, add links in localdesign (⇢ on an element) and re-export.", ""]
        return "\n".join(L)
    # walk journeys from entry points (screens with no incoming edges)
    incoming = {b for _, b in edges}
    starts = [s["title"] for s in screens if s["title"] not in incoming] or [screens[0]["title"]]
    for st in starts:
        path, seen = [st], {st}
        cur = st
        while True:
            nxt = [b for a, b in edges if a == cur and b not in seen]
            if not nxt:
                break
            cur = nxt[0]; path.append(cur); seen.add(cur)
        L += [f"## {st} journey", "", " → ".join(path), ""]
        for a, b in edges:
            if a in seen:
                L.append(f"- From **{a}** to **{b}**: elements with `data-link=\"{b}\"` in `screens/{slug(a)}.html`")
        L.append("")
    L += ["## All transitions", ""] + [f"- {a} → {b}" for a, b in edges] + [""]
    return "\n".join(L)


def data_md(project: dict) -> str:
    data = project.get("data") or {}
    L = ["# Data", ""]
    if not data:
        L += ["No real data sources were attached. Table and list contents in the screens are illustrative sample values.", ""]
        return "\n".join(L)
    L += ["These sources were attached in localdesign and the screens use their real rows. Use them as fixtures/mocks and as the schema.", ""]
    for name, rows in data.items():
        if not isinstance(rows, list):
            continue
        L += [f"## `{name}` ({len(rows)} rows)", ""]
        if rows and isinstance(rows[0], dict):
            cols = list(rows[0].keys())
            L += ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
            L += ["| " + " | ".join(str(r.get(c, "")).replace("|", "\\|")[:40] for c in cols) + " |" for r in rows[:15]]
            if len(rows) > 15:
                L.append(f"| … {len(rows) - 15} more rows (full data in `data/{name}.json`) |")
        L.append("")
    return "\n".join(L)


def plan_md(project: dict) -> str:
    screens = project.get("screens") or []
    edges = _graph(project)
    order = _topo(screens, edges)
    L = ["# Implementation plan", "", "Work top to bottom. Each task is self-contained; tick it when its acceptance criteria in the screen doc pass.", ""]
    L += ["## 0. Setup", "", "- [ ] Read `ARCHITECTURE.md` and `DESIGN_SYSTEM.md`", "- [ ] Scaffold the app (framework of your choice); add routes from ARCHITECTURE → Navigation graph", "- [ ] Create `tokens.css` from DESIGN_SYSTEM → Tokens; load the font stack", "- [ ] Copy `assets/` into the project", ""]
    L += ["## 1. Shared components", "", "- [ ] Build the components listed in DESIGN_SYSTEM → Components (one file each, props = the content in the screen docs)", "- [ ] Add mock data types + fixtures from `DATA.md` / `data/*.json`", ""]
    L += ["## 2. Screens (in flow order)", ""]
    for i, s in enumerate(order, 1):
        L += [f"- [ ] **{s['title']}** — `screens/{slug(s['title'])}.md` + `.html`" + ("  _(interactive artifact: port the script logic)_" if s.get("kind") == "artifact" else "")]
    L += ["", "## 3. Navigation & states", ""]
    L += [f"- [ ] Wire {len(edges)} transitions from `FLOWS.md`" if edges else "- [ ] Add navigation (none specified)", "- [ ] Loading, empty and error states for every table/list", "- [ ] Keyboard navigation and focus order on each screen", ""]
    L += ["## 4. Verify", "", "- [ ] Side-by-side with each `screens/*.html` at its width", "- [ ] Run the acceptance checklists in every screen doc", ""]
    L += ["## Prompts you can paste into a coding agent", "", "```text", "You are implementing a product from a design pack. Read ARCHITECTURE.md, DESIGN_SYSTEM.md and IMPLEMENTATION_PLAN.md in this folder.",
          "Start with section 0 and 1 of the plan. For each screen, open screens/<name>.md and the matching .html (the visual reference), implement it as a route, and make every acceptance criterion pass. Keep tokens in tokens.css; never hard-code colours. Ask before inventing backend behaviour that is not in the docs.", "```", ""]
    first = slug(order[0]['title']) if order else 'screen'
    L += ["```text", f"Implement the screen described in screens/{first}.md to match screens/{first}.html at {order[0].get('width') if order else 1280}px, using the components from DESIGN_SYSTEM.md and the classes in components.css. Use the Copy section verbatim. Then run its acceptance checklist and report what fails.", "```", ""]
    L += ["For small local models, one section at a time:", "", "```text", f"Open screens/{first}.md. Implement section 1 only, as a component that takes the props shown, producing the reference markup. Show me the component code and nothing else.", "```", ""]
    return "\n".join(L)


def _topo(screens, edges):
    """Flow order: screens first (entry points by canvas order, then their successors), artifacts last."""
    arts = [s for s in screens if s.get("kind") == "artifact"]
    screens = [s for s in screens if s.get("kind") != "artifact"]
    return _topo_screens(screens, edges) + arts


def _topo_screens(screens, edges):
    titles = [s["title"] for s in screens]
    incoming = {t: 0 for t in titles}
    for a, b in edges:
        if b in incoming:
            incoming[b] += 1
    ordered, seen = [], set()
    queue = [t for t in titles if incoming[t] == 0] or titles[:1]
    while queue:
        t = queue.pop(0)
        if t in seen:
            continue
        seen.add(t); ordered.append(t)
        for a, b in edges:
            if a == t and b not in seen:
                queue.append(b)
    ordered += [t for t in titles if t not in seen]
    by = {s["title"]: s for s in screens}
    return [by[t] for t in ordered]


def agents_md(project: dict) -> str:
    screens = project.get("screens") or []
    first = slug(screens[0]["title"]) if screens else "screen"
    return f"""# AGENTS.md — instructions for the implementing agent

You are implementing **{project.get('name') or 'this product'}** from the design pack in this folder. Follow these rules exactly.

## Ground truth, in priority order
1. `screens/<name>.html` — what the screen must look like. Open it in a browser. When text and docs disagree, the HTML wins.
2. `screens/<name>.md` — content, props, interactions, acceptance criteria for that screen.
3. `DESIGN_SYSTEM.md` + `tokens.css` + `components.css` — colours, type, spacing, component classes. (`DESIGN.md` is the same system in the Stitch DESIGN.md format, if your tooling prefers that.)
4. `ARCHITECTURE.md`, `FLOWS.md`, `DATA.md` — how screens connect and what data they show.

## Rules
- Do not invent features, fields, screens or copy that are not in the pack. If something is missing, write it under **Open questions** in your report and pick the simplest reasonable default.
- Use the exact copy from each screen doc's **Copy** section. Do not paraphrase labels.
- Every colour, radius and font comes from `tokens.css`. Never hard-code a hex value in a component.
- Build each section type once as a reusable component (see the `props` JSON in the screen docs) and reuse it on every screen.
- Keep the HTML structure and class names close to the reference markup; it makes side-by-side comparison trivial.
- Navigation: an element with `data-link="X"` in the reference goes to the route for screen X (routes are listed in `ARCHITECTURE.md`).
- Data: use `data/*.json` as fixtures. Types and field names are in `ARCHITECTURE.md → Data model`.
- No external network calls, CDNs or fonts unless `DESIGN_SYSTEM.md` names them. The result must run offline.

## Work in this order
1. Read `ARCHITECTURE.md` and `DESIGN_SYSTEM.md` fully.
2. Do `IMPLEMENTATION_PLAN.md` sections 0 and 1 (scaffold, tokens, shared components).
3. Implement screens in the order listed in the plan, one at a time: `screens/{first}.md` first.
4. After each screen, run its acceptance checklist and report pass/fail per item before moving on.
5. When all screens exist, run `sh verify.sh <your-src-dir>` (it executes every check in `VERIFY.md`) and fix every FAIL before you report.

## How to report
For each task: what you built (files), what you verified, and any **Open questions**. Keep it short.

## If you are a small model
Work on exactly one screen per session. Copy the reference markup for a section, replace its content with the props, and move to the next section. Do not refactor across screens until all of them exist.
"""


def readme_md(project: dict) -> str:
    n = len(project.get("screens") or [])
    return f"""# {project.get('name') or 'Untitled'} — implementation pack

Exported from localdesign. {n} screen(s). Everything an engineer or coding agent needs to build this:

| file | what it is |
|---|---|
| `ARCHITECTURE.md` | overview, screen inventory, navigation graph, inferred data model, suggested structure |
| `DESIGN_SYSTEM.md` | tokens, typography, spacing, components (with markup), guidelines |
| `FLOWS.md` | user journeys derived from the screen links |
| `DATA.md` | attached data sources: schema and sample rows (`data/*.json` has the full rows) |
| `AGENTS.md` | rules for the implementing agent (read first if you are an LLM) |
| `IMPLEMENTATION_PLAN.md` | ordered checklist + prompts to paste into an agent |
| `VERIFY.md` | checks to run against the implementation: copy present, routes wired, tokens used, no hard-coded colours |
| `verify.sh` | runs every command in `VERIFY.md` and prints the report: `sh design/verify.sh src/` |
| `DESIGN.md` | the design system in the DESIGN.md format (Google Labs / Stitch), for agents and tools that read that |
| `tokens.css`, `components.css` | the design tokens and the component CSS the reference screens use — include as-is |
| `screens/<name>.md` | one per screen: purpose, layout, content inventory, interactions, acceptance criteria |
| `screens/<name>.html` | the reference rendering, self-contained — open it in a browser; it is the visual source of truth |
| `screens/<name>.png` | screenshot of that rendering (present when a headless browser was available at export time) |
| `assets/` | brand assets used by the screens |

## Using it with an LLM / coding agent

1. Drop this folder into the repo (e.g. `design/`).
2. Tell the agent: *"Read design/AGENTS.md and follow it."* (It points to everything else in order.)
3. For a single screen: *"Implement design/screens/<name>.md to match design/screens/<name>.html."*
4. When it says it is done: *"Run `sh design/verify.sh src/` and fix every FAIL."* (or go through `VERIFY.md` by hand)

The Markdown is deterministic and derived from the designs; the HTML is what the designer actually saw.
"""


# ----------------------------------------------------------------------------- VERIFY.md
_HEX = r"#[0-9a-fA-F]{3}([0-9a-fA-F]{3}([0-9a-fA-F]{2})?)?\b"


def _grep(needle: str) -> str:
    """A grep -rF command for one literal string, quoted for sh."""
    return "grep -rqF -- " + _sh(needle) + " src/"


def _sh(t: str) -> str:
    return "'" + t.replace("'", "'\\''") + "'"


def verify_md(project: dict) -> str:
    """Checks an agent (or a human with a terminal) can run against its implementation. Each line is a command whose exit status is the verdict."""
    screens = project.get("screens") or []
    tokens = tokens_of(project)
    L = ["# VERIFY.md — checks to run against the implementation", "",
         "Run from the repo root. `src/` is where the implementation lives — change the path if yours differs. A line **passes** when the command exits 0.",
         "Report the result per line (`PASS`/`FAIL` + the line) and fix every FAIL before you call the work done. These checks are mechanical; the visual check at the end still matters most.", "",
         "## 0. Setup", "",
         "- [ ] `test -f src/tokens.css || test -f src/styles/tokens.css` — `tokens.css` from the pack is included unchanged",
         "- [ ] `! grep -rnE " + _sh(_HEX) + " src/ --include='*.css' --include='*.jsx' --include='*.tsx' --include='*.vue' --include='*.svelte' | grep -v tokens.css | grep -q .` — no hard-coded colours outside `tokens.css`",
         ]
    for k in list(tokens)[:12]:
        L.append(f"- [ ] `{_grep(f'var(--{k})')}` — token `--{k}` is referenced (not copied as a literal value)")
    fonts = fonts_of(project)
    if fonts:
        L.append(f"- [ ] `{_grep(fonts[0])}` — primary font family `{fonts[0]}` is used")
    L.append("- [ ] `! grep -rnE 'https?://(cdn|unpkg|cdnjs|fonts\\.googleapis)' src/ | grep -q .` — no CDN or remote font (must run offline)")
    L.append("")
    routes = {s["title"]: "/" + (slug(s["title"]) if i else "") for i, s in enumerate(screens)}   # same convention as ARCHITECTURE.md
    L += ["## 1. Routes", ""]
    for s in screens:
        r = routes[s["title"]]
        L.append(f"- [ ] `{_grep(r)}` — route for **{s['title']}** exists (`{r}`)" if r != "/" else f"- [ ] the default route `/` renders **{s['title']}**")
    L.append("")
    for s in screens:
        scan = scan_html(s.get("html") or "")
        name = slug(s.get("title"))
        L += [f"## {s.get('title')}  (`screens/{name}.md`)", ""]
        seen = set()
        strings = [h for _, h in scan["headings"]] + [c for c in scan["copy"] if len(c) >= 4]
        strings = [t for t in strings if not (t in seen or seen.add(t))][:12]
        for t in strings:
            L.append(f"- [ ] `{_grep(t)}` — copy present verbatim: “{t}”")
        for b in scan["buttons"][:8]:
            if b["text"]:
                L.append(f"- [ ] `{_grep(b['text'])}` — action “{b['text']}” exists" + (f" and navigates to **{b['link']}** (`{routes.get(b['link'], '?')}`)" if b.get("link") else ""))
        for f in scan["fields"][:8]:
            if f["label"]:
                L.append(f"- [ ] `{_grep(f['label'])}` — field “{f['label']}” (`{f['type']}`) exists")
        for t in scan["tables"][:4]:
            for col in t["columns"][:6]:
                L.append(f"- [ ] `{_grep(col)}` — table column “{col}”")
        if s.get("spec"):
            types = sorted({n.get("type", "?") for n in s["spec"].get("sections") or []})
            if types:
                L.append(f"- [ ] components used on this screen exist as reusable units: {', '.join(f'`{t}`' for t in types)} (one file or export per type)")
        if s.get("kind") == "artifact":
            L.append("- [ ] the behaviour in the reference `<script>` was ported: exercise it by hand once and describe the result")
        L.append("")
    data = project.get("data") or {}
    if data:
        L += ["## Data", ""]
        for k, rows in data.items():
            cols = list(rows[0].keys()) if isinstance(rows, list) and rows and isinstance(rows[0], dict) else []
            L.append(f"- [ ] `{_grep(slug(k))}` — fixture `data/{slug(k)}.json` is loaded" + (f"; fields rendered: {', '.join(f'`{c}`' for c in cols[:8])}" if cols else ""))
            for c in cols[:4]:
                L.append(f"- [ ] `{_grep(c)}` — field `{c}` is referenced")
        L.append("")
    L += ["## Visual (manual, decisive)", ""]
    for s in screens:
        name = slug(s.get("title"))
        L.append(f"- [ ] Open `screens/{name}.html` (or `screens/{name}.png`) beside the running app at {s.get('width')}px: same hierarchy, spacing, colours and copy; nothing missing, nothing invented")
    L += ["- [ ] Keyboard: every control reachable with Tab; `data-link` targets reachable with Enter", "- [ ] Text contrast ≥ 4.5:1 against its background (spot-check headings, body, muted text)", ""]
    L += ["## Report format", "", "```", "VERIFY  <n> pass / <m> fail", "FAIL  <section> — <line text>  → <what you changed, or why it cannot pass>", "```", ""]
    return "\n".join(L)


VERIFY_SH = r"""#!/bin/sh
# Runs every check in VERIFY.md (each `command` in a "- [ ] `…`" line) and prints PASS/FAIL per line plus a summary.
# Usage: sh verify.sh [src-dir]      (default src/; the commands in VERIFY.md say src/, we substitute your path)
# Exit status: number of failures (0 = all mechanical checks pass). Manual lines (no command) are listed as TODO.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${1:-src/}
case "$SRC" in */) ;; *) SRC="$SRC/";; esac
pass=0; fail=0; todo=0; section=""
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    "## "*) section=${line#\#\# }; printf '\n%s\n' "$section" ;;
    "- [ ] "*)
      rest=${line#- \[ \] }
      case "$rest" in
        \`*)
          cmd=${rest#\`}; cmd=${cmd%%\`*}
          desc=${rest#*\` — }; [ "$desc" = "$rest" ] && desc=""
          cmd=$(printf '%s' "$cmd" | sed "s#src/#$SRC#g")
          if (cd "$HERE/.." 2>/dev/null || cd "$HERE"; sh -c "$cmd") >/dev/null 2>&1; then pass=$((pass+1)); printf '  PASS  %s\n' "$desc"
          else fail=$((fail+1)); printf '  FAIL  %s\n        $ %s\n' "$desc" "$cmd"; fi ;;
        *) todo=$((todo+1)); printf '  TODO  %s\n' "$rest" ;;
      esac ;;
  esac
done < "$HERE/VERIFY.md"
printf '\nVERIFY  %d pass / %d fail / %d manual\n' "$pass" "$fail" "$todo"
exit $fail
"""


# ----------------------------------------------------------------------------- screenshots (optional; needs a headless browser on this machine)
_CHROME_NAMES = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge", "microsoft-edge", "brave-browser"]
_CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]
HEIGHTS = {1280: 900, 768: 1024, 390: 844}


def find_chrome() -> str | None:
    """Path to a Chromium-based browser for `--headless --screenshot`, or None. `LD_CHROME` overrides."""
    env = os.environ.get("LD_CHROME")
    if env:
        return env if os.path.isfile(env) or shutil.which(env) else None
    for n in _CHROME_NAMES:
        p = shutil.which(n)
        if p:
            return p
    import glob
    pw = [os.path.expanduser("~/.cache/ms-playwright"), os.path.expanduser("~/Library/Caches/ms-playwright"), os.path.expanduser("~/AppData/Local/ms-playwright"), "/opt/pw-browsers"]
    bundled = [f for base in pw for pat in ("chromium_headless_shell-*/*/chrome-headless-shell", "chromium_headless_shell-*/*/chrome-headless-shell.exe", "chromium-*/chrome-*/chrome", "chromium-*/chrome-*/chrome.exe", "chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium")
               for f in sorted(glob.glob(os.path.join(base, pat)), reverse=True)]
    for p in _CHROME_PATHS + bundled:
        if os.path.isfile(p):
            return p
    return None


def screenshot(html: str, width: int, chrome: str | None = None, timeout: float = 30.0, height: int | None = None) -> bytes | None:
    """Render self-contained HTML with a headless Chromium at `width` and return PNG bytes (None if no browser or it failed)."""
    chrome = chrome or find_chrome()
    if not chrome or not html:
        return None
    width = int(width or 1280)
    height = height or HEIGHTS.get(width, 900)
    d = tempfile.mkdtemp(prefix="ldshot-")
    src, out = os.path.join(d, "screen.html"), os.path.join(d, "screen.png")
    try:
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(html)
        cmd = [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--disable-extensions", "--disable-background-networking",
               "--disable-dev-shm-usage", "--disable-sync", "--no-default-browser-check", "--mute-audio",
               f"--user-data-dir={os.path.join(d, 'profile')}", f"--window-size={width},{height}", f"--screenshot={out}",
               "--virtual-time-budget=3000", "file://" + src.replace(os.sep, "/")]
        if sys.platform != "win32" and hasattr(os, "geteuid") and os.geteuid() == 0:
            cmd.insert(1, "--no-sandbox")
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout, check=False)
        if os.path.exists(out):
            with open(out, "rb") as fh:
                data = fh.read()
            return data if data[:4] == b"\x89PNG" else None
        return None
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ----------------------------------------------------------------------------- UIX Bench (optional scoring of the screens)
# The standard persona panel (uixbench/v0 presets), inlined so the pack needs no uixbench install to carry the spec.
UIXBENCH_PANEL = [
    {"id": "typical", "label": "Typical desktop user", "axes": {}},
    {"id": "low-vision", "label": "Low vision, zooms to 400%", "axes": {"vision": 0.8}, "viewport": [320, 640]},
    {"id": "motor", "label": "Limited dexterity, touch", "axes": {"motor": 0.8}, "modality": "touch", "viewport": [390, 844]},
    {"id": "keyboard", "label": "Keyboard-only user", "axes": {}, "modality": "keyboard"},
    {"id": "novice", "label": "Novice, low reading level", "axes": {"literacy": 0.8, "attention": 0.6}},
]


def _screen_names(project: dict) -> list[tuple[dict, str]]:
    """(screen, file stem) pairs, unique, in project order: the names used under screens/."""
    out, used = [], set()
    for i, s in enumerate(project.get("screens") or [], 1):
        name = slug(s.get("title"))
        while name in used:
            name += f"-{i}"
        used.add(name)
        out.append((s, name))
    return out


def uixbench_spec(project: dict) -> dict | None:
    """uixbench.json for the pack's screens: one task per flow end (a screen reachable from the first screen with no
    way onward), the standard persona panel with equal goals. `uixbench score screens/` uses it. None without flows."""
    named = [(s, n) for s, n in _screen_names(project) if s.get("html") and s.get("kind") != "artifact"]
    if len(named) < 2:
        return None
    by_title = {s["title"].strip().lower(): n for s, n in named}
    edges = {}
    for a, b in _graph(project):
        if a.strip().lower() in by_title and b.strip().lower() in by_title:
            edges.setdefault(by_title[a.strip().lower()], set()).add(by_title[b.strip().lower()])
    start = named[0][1]
    seen, todo = {start}, [start]
    while todo:
        for nxt in edges.get(todo.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    ends = [n for _, n in named if n in seen and n != start and not (edges.get(n, set()) - {start})]
    if not ends:
        return None
    titles = {n: s["title"] for s, n in named}
    tasks = [{"id": n, "label": f"Reach {titles[n]}", "start": f"{start}.html", "done": {"screen": f"{n}.html"}} for n in ends]
    return {"uixbench_version": "uixbench/v0", "name": project.get("name") or "design",
            "services": [{"id": "flows", "label": "Flows", "tasks": tasks}], "personas": UIXBENCH_PANEL}


# ----------------------------------------------------------------------------- zip
def build_pack(project: dict, inline_assets=None, asset_files=None, screenshot_fn=None, narrative: str | None = None,
               uixbench_fn=None) -> bytes:
    """inline_assets: fn(html)->html making asset URLs self-contained; asset_files: list of (name, bytes);
    screenshot_fn: fn(html, width)->png bytes|None adds screens/<name>.png; narrative: model-written overview for ARCHITECTURE.md;
    uixbench_fn: fn({file: html}, spec)->{file: bytes} adds a UIX Bench report under uixbench/."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.md", readme_md(project))
        z.writestr("ARCHITECTURE.md", architecture_md(project, narrative))
        z.writestr("VERIFY.md", verify_md(project))
        z.writestr("verify.sh", VERIFY_SH)
        from . import designsystem as DS
        z.writestr("DESIGN.md", DS.to_design_md(project.get("designSystem"), project))
        z.writestr("DESIGN_SYSTEM.md", design_system_md(project))
        z.writestr("FLOWS.md", flows_md(project))
        z.writestr("DATA.md", data_md(project))
        z.writestr("IMPLEMENTATION_PLAN.md", plan_md(project))
        z.writestr("AGENTS.md", agents_md(project))
        from . import components as C
        z.writestr("components.css", "/* Component CSS used by the reference screens (localdesign). Tokens come from tokens.css. */\n" + C.BASE_CSS.strip() + "\n")
        from . import components as C2
        ds = project.get("designSystem") or None
        spec_tokens = next((s["spec"].get("tokens") for s in (project.get("screens") or []) if s.get("spec") and s["spec"].get("tokens")), {})
        z.writestr("tokens.css", "/* Design tokens. Edit values here, never in components. */\n" + C2._tokens_css(spec_tokens or {}, ds).replace(";--", ";\n  --").replace("{--", "{\n  --").replace("}", "\n}") + "\n")
        for i, (s, name) in enumerate(_screen_names(project), 1):
            html = s.get("html") or ""
            html = inline_assets(html) if inline_assets else html
            png = screenshot_fn(html, s.get("width") or 1280) if (screenshot_fn and html) else None
            z.writestr(f"screens/{name}.md", screen_md(s, project, i, png=bool(png)))
            z.writestr(f"screens/{name}.html", html)
            if png:
                z.writestr(f"screens/{name}.png", png)
            if s.get("spec"):
                z.writestr(f"screens/{name}.spec.json", json.dumps(s["spec"], indent=2))
        spec = uixbench_spec(project)
        if spec:
            z.writestr("screens/uixbench.json", json.dumps(spec, indent=2))
        if uixbench_fn:
            screens = {f"{name}.html": (inline_assets(s.get("html") or "") if inline_assets else s.get("html") or "")
                       for s, name in _screen_names(project) if s.get("html")}
            for fname, data in (uixbench_fn(screens, spec) or {}).items():
                z.writestr(f"uixbench/{fname}", data)
        for k, rows in (project.get("data") or {}).items():
            z.writestr(f"data/{slug(k)}.json", json.dumps(rows, indent=2, default=str))
        for fname, data in asset_files or []:
            z.writestr(f"assets/{fname}", data)
    return buf.getvalue()
