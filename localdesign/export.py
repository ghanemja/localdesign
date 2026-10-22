"""Exports: HTML → React (JSX + CSS) deterministically, and project → design spec (Markdown).
No model calls, no dependencies."""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
ATTR_MAP = {"class": "className", "for": "htmlFor", "tabindex": "tabIndex", "readonly": "readOnly", "maxlength": "maxLength",
            "colspan": "colSpan", "rowspan": "rowSpan", "autocomplete": "autoComplete", "autofocus": "autoFocus", "srcset": "srcSet",
            "contenteditable": "contentEditable", "spellcheck": "spellCheck", "crossorigin": "crossOrigin", "enctype": "encType",
            "viewbox": "viewBox", "stroke-width": "strokeWidth", "stroke-linecap": "strokeLinecap", "stroke-linejoin": "strokeLinejoin",
            "fill-rule": "fillRule", "clip-rule": "clipRule", "stroke-dasharray": "strokeDasharray", "stroke-dashoffset": "strokeDashoffset",
            "font-size": "fontSize", "font-weight": "fontWeight", "text-anchor": "textAnchor", "stop-color": "stopColor", "xlink:href": "xlinkHref"}
BOOL_ATTRS = {"checked", "disabled", "selected", "readonly", "required", "autofocus", "hidden", "multiple", "open"}


def _style_obj(css: str) -> str:
    parts = []
    for decl in css.split(";"):
        if ":" not in decl:
            continue
        k, v = decl.split(":", 1)
        k, v = k.strip(), v.strip()
        if not k:
            continue
        if k.startswith("--"):
            key = json.dumps(k)
        else:
            key = re.sub(r"-([a-z])", lambda m: m.group(1).upper(), k)
            if k.startswith("-"):
                key = key[0].upper() + key[1:] if key else key
        parts.append(f"{key}: {json.dumps(v)}")
    return "{{" + ", ".join(parts) + "}}"


class _JSX(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.out: list[str] = []
        self.styles: list[str] = []
        self.skip = 0           # inside <style>/<script>/<head>
        self.in_body = False
        self.in_style = False
        self.depth = 0
        self.title = ""

    def handle_starttag(self, tag, attrs):
        if tag in ("script",):
            self.skip += 1; return
        if tag == "style":
            self.in_style = True; return
        if tag in ("html", "head", "meta", "link", "title"):
            if tag == "title":
                self.skip += 1
            return
        if tag == "body":
            self.in_body = True; return
        if not self.in_body or self.skip:
            return
        a = []
        for k, v in attrs:
            kl = k.lower()
            if kl.startswith("on"):
                continue
            if kl == "style":
                a.append(f"style={_style_obj(v or '')}"); continue
            name = ATTR_MAP.get(kl, kl)
            if "-" in name and not name.startswith("data-") and not name.startswith("aria-"):
                name = re.sub(r"-([a-z])", lambda m: m.group(1).upper(), name)
            if v is None or (kl in BOOL_ATTRS and v == ""):
                a.append(name if kl in BOOL_ATTRS else f'{name}=""')
            else:
                a.append(f"{name}={json.dumps(v)}")
        attr_s = (" " + " ".join(a)) if a else ""
        self.out.append(f"<{tag}{attr_s}{' /' if tag in VOID else ''}>")
        if tag not in VOID:
            self.depth += 1

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.in_body and not self.skip and tag not in ("html", "head", "meta", "link", "title", "body", "style", "script"):
            self.out.append(f"</{tag}>"); self.depth -= 1

    def handle_endtag(self, tag):
        if tag == "script":
            self.skip = max(0, self.skip - 1); return
        if tag == "title":
            self.skip = max(0, self.skip - 1); return
        if tag == "style":
            self.in_style = False; return
        if tag == "body":
            self.in_body = False; return
        if not self.in_body or self.skip or tag in VOID or tag in ("html", "head", "meta", "link"):
            return
        self.out.append(f"</{tag}>"); self.depth -= 1

    def handle_data(self, data):
        if self.in_style:
            self.styles.append(data); return
        if not self.in_body or self.skip:
            return
        if not data.strip():
            if "\n" in data:
                self.out.append("\n")
            return
        txt = data.replace("{", "{'{'}").replace("}", "{'}'}")
        self.out.append(txt)

    def handle_entityref(self, name):
        if self.in_body and not self.skip and not self.in_style:
            self.out.append(f"&{name};")

    def handle_charref(self, name):
        if self.in_body and not self.skip and not self.in_style:
            self.out.append(f"&#{name};")

    def handle_comment(self, data):
        if self.in_body and not self.skip:
            self.out.append(f"{{/* {data.strip()} */}}")


def component_name(title: str) -> str:
    words = re.sub(r"[^A-Za-z0-9 ]+", " ", title or "Screen").split()
    name = "".join(w[:1].upper() + w[1:] for w in words)[:40] or "Screen"
    return name if not name[0].isdigit() else "S" + name


def html_to_react(html: str, title: str) -> dict:
    p = _JSX()
    p.feed(html)
    name = component_name(title)
    body = "".join(p.out).strip()
    body = re.sub(r"\n{3,}", "\n\n", body)
    css = "\n".join(s.strip() for s in p.styles if s.strip())
    jsx = (f'import "./{name}.css";\n\n'
           f"export default function {name}() {{\n  return (\n    <>\n{_indent(body, 6)}\n    </>\n  );\n}}\n")
    return {"name": name, "jsx": jsx, "css": css}


def _indent(s: str, n: int) -> str:
    pad = " " * n
    return "\n".join(pad + line if line.strip() else line for line in s.splitlines())


# ----------------------------------------------------------------------------- design spec
_ROOT_VARS = re.compile(r":root\s*\{([^}]*)\}", re.S)
_VAR = re.compile(r"--([a-zA-Z0-9_-]+)\s*:\s*([^;]+);")
_HEAD = re.compile(r"<h([1-3])[^>]*>(.*?)</h\1>", re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")


def design_spec_md(project: dict) -> str:
    screens = project.get("screens") or []
    ds = project.get("designSystem") or {}
    L = [f"# {project.get('name') or 'Untitled'} — design spec", "", f"_Generated by localdesign · {len(screens)} screens_", ""]
    # tokens
    L += ["## Design tokens", ""]
    tokens = dict(ds.get("tokens") or {})
    if not tokens:
        for s in screens:
            m = _ROOT_VARS.search(s.get("html") or "")
            if m:
                tokens = {k: v.strip() for k, v in _VAR.findall(m.group(1))}
                break
    if tokens:
        L += ["| Token | Value |", "|---|---|"] + [f"| `{k}` | `{v}` |" for k, v in tokens.items()] + [""]
    else:
        L += ["_No explicit tokens; screens define their own styles._", ""]
    if ds.get("name"):
        L.insert(3, f"Design system: **{ds['name']}**")
    if ds.get("notes"):
        L += ["### Guidelines", "", ds["notes"], ""]
    if ds.get("components"):
        L += ["### Components", ""] + [f"- **{c.get('name')}** — {c.get('description', '')}" for c in ds["components"]] + [""]
    # flows
    links = [(s["title"], t) for s in screens for t in sorted(set(re.findall(r'data-link="([^"]*)"', s.get("html") or ""))) if t and t != s["title"]]
    if links:
        L += ["## Flow", ""] + [f"- {a} → {b}" for a, b in links] + [""]
    # screens
    L += ["## Screens", ""]
    for i, s in enumerate(screens, 1):
        L += [f"### {i}. {s.get('title')}", "", f"- Width: {s.get('width')}px · versions: {len(s.get('versions') or [])}" + (" · engine: spec" if s.get("spec") else "")]
        if s.get("brief"):
            L += [f"- Brief: {s['brief']}"]
        spec = s.get("spec")
        if spec and spec.get("sections"):
            L += ["- Sections:"] + [f"  - {_describe_node(n)}" for n in spec["sections"]]
        else:
            heads = [_TAGS.sub("", h[1]).strip() for h in _HEAD.findall(s.get("html") or "")][:12]
            if heads:
                L += ["- Headings: " + " · ".join(h for h in heads if h)]
        L += [""]
    data = project.get("data") or {}
    if data:
        L += ["## Data sources", ""] + [f"- **{k}** — {len(v) if isinstance(v, list) else 1} rows" + (f" · columns: {', '.join(list(v[0].keys())[:8])}" if isinstance(v, list) and v and isinstance(v[0], dict) else "") for k, v in data.items()] + [""]
    return "\n".join(L)


def _describe_node(n: dict) -> str:
    t = n.get("type", "?")
    label = n.get("title") or n.get("text") or n.get("label") or ""
    kids = n.get("children") or []
    extra = ""
    if t in ("grid", "split") and kids:
        extra = " [" + ", ".join(k.get("type", "?") for k in kids if isinstance(k, dict)) + "]"
    elif t == "stats":
        extra = " (" + ", ".join(str(i.get("label", "")) for i in (n.get("items") or []) if isinstance(i, dict)) + ")"
    elif t == "table":
        extra = " columns: " + ", ".join(str(c) for c in (n.get("columns") or []))
    elif t == "form":
        extra = " fields: " + ", ".join(str(f.get("label", "")) for f in (n.get("fields") or []) if isinstance(f, dict))
    return f"**{t}**" + (f" — {label}" if label else "") + extra
