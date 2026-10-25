"""Design-system import: turn pasted CSS variables, a tailwind.config.js, or a tokens JSON
into localdesign tokens (+ raw CSS to include verbatim). Heuristic, dependency-free.
"""
from __future__ import annotations

import json
import re

HEX = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
COLOR_FN = re.compile(r"\b(?:rgba?|hsla?|oklch|oklab|color)\([^)]*\)")

# token name → list of substrings that identify it in a variable/key name (first match wins, in order)
ROLE_HINTS = {
    "primary": ["primary", "brand", "accent-primary", "main", "interactive", "blue-600", "blue-500", "indigo-600"],
    "accent": ["accent", "secondary", "highlight"],
    "bg": ["background", "bg-base", "bg-page", "page", "canvas", "bg-default", "surface-0", "neutral-0", "gray-50", "grey-50", "bg"],
    "surface": ["surface", "card", "panel", "elevated", "bg-elevated", "white"],
    "text": ["foreground", "text-primary", "text-default", "ink", "on-surface", "text", "fg", "gray-900", "grey-900", "neutral-900"],
    "muted": ["text-muted", "text-secondary", "muted", "subtle", "secondary-text", "gray-500", "grey-500", "neutral-500"],
    "line": ["border", "divider", "line", "stroke", "outline", "gray-200", "grey-200", "neutral-200"],
    "ok": ["success", "positive", "green"],
    "bad": ["danger", "error", "destructive", "negative", "red"],
    "warn": ["warning", "caution", "amber", "yellow", "orange"],
}


def detect_kind(text: str) -> str:
    t = text.strip()
    if (t.startswith("---") and re.search(r"^colors:", t, re.M)) or ("## Colors" in t and ("## Overview" in t or "## Typography" in t)):
        return "designmd"
    if t.startswith(("{", "[")):
        return "tokens"
    if "module.exports" in t or "export default" in t or re.search(r"\btheme\s*:", t) or "tailwind" in t.lower():
        return "tailwind"
    if "--" in t and "{" in t:
        return "css"
    if "<" in t and ">" in t:
        return "html"
    return "css"


def parse(text: str, kind: str = "auto") -> dict:
    kind = detect_kind(text) if kind in ("auto", "", None) else kind
    if kind == "css":
        return _from_css(text)
    if kind == "tailwind":
        return _from_tailwind(text)
    if kind == "tokens":
        return _from_tokens(text)
    if kind == "html":
        return _from_html(text)
    if kind == "designmd":
        return _from_design_md(text)
    return {"kind": kind, "tokens": {}, "palette": [], "css": "", "font": None}


# ----------------------------------------------------------------------------- css
_VAR = re.compile(r"--([a-zA-Z0-9_-]+)\s*:\s*([^;}]+);?")
_ROOT = re.compile(r":root\s*\{([^}]*)\}", re.S)
_FONT_FAMILY = re.compile(r"font-family\s*:\s*([^;}]+)")


def _from_css(text: str) -> dict:
    vars_: dict[str, str] = {}
    blocks = _ROOT.findall(text) or [text]
    for b in blocks:
        for name, val in _VAR.findall(b):
            vars_[name.lower()] = val.strip()
    # resolve var(--x) references one level
    for k, v in list(vars_.items()):
        m = re.fullmatch(r"var\(--([a-zA-Z0-9_-]+)\)", v)
        if m and m.group(1).lower() in vars_:
            vars_[k] = vars_[m.group(1).lower()]
    colors = {k: v for k, v in vars_.items() if HEX.search(v) or COLOR_FN.search(v)}
    tokens = _assign_roles(colors)
    font = next((vars_[k] for k in vars_ if "font" in k and "size" not in k and "weight" not in k and not HEX.search(vars_[k])), None)
    if not font:
        m = _FONT_FAMILY.search(text)
        font = m.group(1).strip() if m else None
    radius = next((vars_[k] for k in vars_ if "radius" in k), None)
    if font:
        tokens["font"] = font
    if radius:
        tokens["radius"] = _px(radius)
    root_css = "\n".join(f":root{{{b.strip()}}}" for b in _ROOT.findall(text)) if _ROOT.search(text) else ""
    return {"kind": "css", "tokens": tokens, "palette": _palette(colors), "css": root_css, "variables": vars_}


# ------------------------------------------------------------------------ tailwind
_KV = re.compile(r"""['"]?([a-zA-Z0-9_-]+)['"]?\s*:\s*['"](#[0-9a-fA-F]{3,8}|(?:rgba?|hsla?|oklch)\([^'"]*\))['"]""")
_NESTED = re.compile(r"""['"]?([a-zA-Z0-9_-]+)['"]?\s*:\s*\{""")


def _from_tailwind(text: str) -> dict:
    # flatten nested color objects: primary: { DEFAULT: '#..', 500: '#..' } -> primary, primary-500
    colors: dict[str, str] = {}
    stack: list[str] = []
    i = 0
    tokens_re = re.compile(r"""(['"]?[a-zA-Z0-9_-]+['"]?\s*:\s*\{)|(\})|(['"]?[a-zA-Z0-9_-]+['"]?\s*:\s*['"][^'"]*['"])""")
    for m in tokens_re.finditer(text):
        if m.group(1):
            name = re.match(r"""['"]?([a-zA-Z0-9_-]+)""", m.group(1)).group(1)
            stack.append(name)
        elif m.group(2):
            if stack:
                stack.pop()
        else:
            kv = _KV.match(m.group(3))
            if kv:
                key, val = kv.group(1), kv.group(2)
                path = [p for p in stack if p not in ("theme", "extend", "colors", "module", "exports", "default")]
                name = "-".join(path + ([] if key.upper() == "DEFAULT" else [key])) or key
                colors[name.lower()] = val
    tokens = _assign_roles(colors)
    fm = re.search(r"""fontFamily\s*:\s*\{[^}]*?['"]?(?:sans|body|base|display)['"]?\s*:\s*\[([^\]]*)\]""", text, re.S)
    if fm:
        fam = ", ".join(re.findall(r"""['"]([^'"]+)['"]""", fm.group(1)))
        if fam:
            tokens["font"] = fam
    rm = re.search(r"""borderRadius\s*:\s*\{[^}]*?['"]?(?:DEFAULT|md|lg)['"]?\s*:\s*['"]([^'"]+)['"]""", text, re.S)
    if rm:
        tokens["radius"] = _px(rm.group(1))
    return {"kind": "tailwind", "tokens": tokens, "palette": _palette(colors), "css": "", "variables": colors}


# -------------------------------------------------------------------------- tokens
def _from_tokens(text: str) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"tokens JSON invalid: {e}")
    colors: dict[str, str] = {}
    fonts: list[str] = []
    radii: list[str] = []

    def walk(node, path):
        if isinstance(node, dict):
            if "$value" in node or "value" in node:
                v = node.get("$value", node.get("value"))
                t = str(node.get("$type", node.get("type", ""))).lower()
                name = "-".join(path).lower()
                if isinstance(v, str) and (HEX.search(v) or COLOR_FN.search(v) or t == "color"):
                    colors[name] = v
                elif t in ("fontfamily", "fontfamilies") or "font" in name and isinstance(v, (str, list)):
                    fonts.append(", ".join(v) if isinstance(v, list) else str(v))
                elif "radius" in name:
                    radii.append(str(v))
                return
            for k, v in node.items():
                walk(v, path + [str(k)])
        elif isinstance(node, str):
            name = "-".join(path).lower()
            if HEX.search(node) or COLOR_FN.search(node):
                colors[name] = node
            elif "font" in name:
                fonts.append(node)
            elif "radius" in name:
                radii.append(node)

    walk(data, [])
    tokens = _assign_roles(colors)
    if fonts:
        tokens["font"] = fonts[0]
    if radii:
        tokens["radius"] = _px(radii[0])
    return {"kind": "tokens", "tokens": tokens, "palette": _palette(colors), "css": "", "variables": colors}


# ---------------------------------------------------------------------------- html
def _from_html(text: str) -> dict:
    """A pasted page/component: harvest its <style> colors + font as a starting point."""
    styles = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", text, re.S | re.I))
    out = _from_css(styles) if styles else {"kind": "html", "tokens": {}, "palette": [], "css": "", "variables": {}}
    if not out["tokens"]:
        colors = {f"c{i}": c for i, c in enumerate(dict.fromkeys(HEX.findall(styles or text)))}
        out["palette"] = _palette(colors)
        if colors:
            out["tokens"]["primary"] = list(colors.values())[0]
    out["kind"] = "html"
    return out


# -------------------------------------------------------------------------- helpers
def _assign_roles(colors: dict[str, str]) -> dict:
    tokens: dict = {}
    for role, hints in ROLE_HINTS.items():
        for h in hints:
            hit = next((v for k, v in colors.items() if h in k and ("-" + h in k or k.startswith(h) or k == h or h in k.split("-"))), None)
            if hit:
                tokens[role] = hit
                break
    if "primary" not in tokens and colors:
        # first saturated-looking hex that isn't near white/black
        for v in colors.values():
            m = HEX.search(v)
            if m and _saturated(m.group(0)):
                tokens["primary"] = v
                break
    if "bg" in tokens and "surface" not in tokens and _is_light(tokens["bg"]):
        tokens["surface"] = "#ffffff"
    if "bg" in tokens and not _is_light(tokens["bg"]):
        tokens["theme"] = "dark"
    return tokens


def _hex_rgb(v: str):
    m = HEX.search(v or "")
    if not m:
        return None
    h = m.group(0)[1:]
    if len(h) in (3, 4):
        h = "".join(c * 2 for c in h[:3])
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None


def _is_light(v: str) -> bool:
    rgb = _hex_rgb(v)
    if not rgb:
        return True
    r, g, b = rgb
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) > 140


def _saturated(v: str) -> bool:
    rgb = _hex_rgb(v)
    if not rgb:
        return False
    return (max(rgb) - min(rgb)) > 60 and 30 < sum(rgb) / 3 < 225


def _px(v: str) -> int:
    m = re.search(r"([0-9.]+)\s*(px|rem|em)?", str(v))
    if not m:
        return 12
    n = float(m.group(1))
    return int(round(n * 16)) if m.group(2) in ("rem", "em") else int(round(n))


def _palette(colors: dict[str, str]) -> list[dict]:
    seen, out = set(), []
    for k, v in colors.items():
        m = HEX.search(v)
        key = (m.group(0).lower() if m else v)
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": k, "value": v})
    return out[:40]


# ------------------------------------------------------------------------ DESIGN.md (Google Labs / Stitch format, alpha)
# YAML front matter with colors / typography / rounded / spacing / components, then fixed `##` sections.
# We read it with a small YAML-subset parser (maps, scalars, inline + block lists) — no PyYAML, no dependencies.
_DMD_SECTIONS = ["Overview", "Colors", "Typography", "Layout", "Elevation & Depth", "Shapes", "Components", "Do's and Don'ts"]


def _yaml_scalar(v: str):
    v = v.strip()
    if not v:
        return ""
    if v[0] in "\"'" and v[-1] == v[0] and len(v) >= 2:
        return v[1:-1]
    if v.startswith("[") and v.endswith("]"):
        return [_yaml_scalar(x) for x in re.split(r",\s*", v[1:-1].strip()) if x.strip()]
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d*\.\d+", v):
        return float(v)
    return v.split(" #")[0].strip() if not v.startswith("#") else v


def yaml_subset(text: str) -> dict:
    """Parse indented `key: value` maps with nested maps and lists. Enough for DESIGN.md front matter."""
    lines = [l.rstrip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
    root: dict = {}
    stack: list[tuple[int, object]] = [(-1, root)]

    def parent_for(indent):
        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()
        return stack[-1][1]

    for raw in lines:
        indent = len(raw) - len(raw.lstrip(" "))
        s = raw.strip()
        par = parent_for(indent)
        if s.startswith("- "):
            item = s[2:].strip()
            if isinstance(par, dict):   # list under a key whose value we have not materialised yet
                key, holder = stack[-1][1], None
                # find the key in grandparent pointing at this empty dict and replace with list
                gp = stack[-2][1] if len(stack) > 1 else root
                if isinstance(gp, dict):
                    for k, v in gp.items():
                        if v is par:
                            gp[k] = holder = []
                            break
                if holder is None:
                    continue
                stack[-1] = (stack[-1][0], holder)
                par = holder
            if isinstance(par, list):
                if ":" in item and not item.startswith(("'", '"', "{")):
                    k, _, v = item.partition(":")
                    d = {k.strip(): _yaml_scalar(v)} if v.strip() else {k.strip(): {}}
                    par.append(d)
                    stack.append((indent, d))
                else:
                    par.append(_yaml_scalar(item))
            continue
        if ":" not in s:
            continue
        k, _, v = s.partition(":")
        k = k.strip().strip("\"'")
        if not isinstance(par, dict):
            continue
        if v.strip():
            par[k] = _yaml_scalar(v)
        else:
            par[k] = {}
            stack.append((indent, par[k]))
    return root


def split_design_md(text: str) -> tuple[dict, dict]:
    """→ (front_matter, {section_title: body}). Also harvests ```yaml blocks inside sections (the spec allows both)."""
    fm: dict = {}
    body = text
    m = re.match(r"\s*---\s*\n(.*?)\n---\s*\n?", text, re.S)
    if m:
        fm = yaml_subset(m.group(1))
        body = text[m.end():]
    for block in re.findall(r"```ya?ml\s*\n(.*?)```", body, re.S | re.I):
        for k, v in yaml_subset(block).items():
            fm.setdefault(k, v)
    sections: dict = {}
    cur = None
    for line in body.splitlines():
        h = re.match(r"^##\s+(.+?)\s*$", line)
        if h:
            cur = h.group(1).strip()
            sections[cur] = []
        elif cur:
            sections[cur].append(line)
    return fm, {k: re.sub(r"```ya?ml.*?```", "", "\n".join(v), flags=re.S | re.I).strip() for k, v in sections.items()}


def _resolve_ref(v, fm: dict):
    """{colors.primary} → value."""
    if isinstance(v, str):
        m = re.fullmatch(r"\{([a-zA-Z0-9_.-]+)\}", v.strip())
        if m:
            cur = fm
            for part in m.group(1).split("."):
                cur = cur.get(part) if isinstance(cur, dict) else None
            return cur if isinstance(cur, (str, int, float)) else v
    return v


def _from_design_md(text: str) -> dict:
    fm, sections = split_design_md(text)
    colors = {str(k).lower(): str(_resolve_ref(v, fm)) for k, v in (fm.get("colors") or {}).items() if isinstance(v, (str, int))} if isinstance(fm.get("colors"), dict) else {}
    tokens = _assign_roles(colors)
    for role, names in (("primary", ("primary",)), ("accent", ("secondary", "tertiary", "accent")), ("bg", ("background", "neutral", "surface-dim", "canvas")),
                        ("surface", ("surface", "surface-container", "card")), ("text", ("on-surface", "on-background", "text", "foreground", "ink")),
                        ("muted", ("on-surface-variant", "muted", "secondary-text")), ("line", ("outline", "outline-variant", "border", "line"))):
        if role not in tokens:
            hit = next((colors[n] for n in names if n in colors), None)
            if hit:
                tokens[role] = hit
    if "bg" in tokens and not _is_light(tokens["bg"]):
        tokens["theme"] = "dark"
    typ = fm.get("typography") if isinstance(fm.get("typography"), dict) else {}
    fam = None
    for key in ("body", "body-md", "body-medium", "base", "text", *typ.keys()):
        t = typ.get(key)
        if isinstance(t, dict) and t.get("fontFamily"):
            fam = str(_resolve_ref(t["fontFamily"], fm)); break
    if fam:
        tokens["font"] = fam
    rounded = fm.get("rounded") if isinstance(fm.get("rounded"), dict) else {}
    for key in ("md", "medium", "DEFAULT", "default", "base", "lg", "sm", *rounded.keys()):
        if key in rounded and isinstance(rounded[key], (str, int, float)):
            tokens["radius"] = _px(str(_resolve_ref(rounded[key], fm))); break
    notes = "\n\n".join(x for x in (sections.get("Overview") or sections.get("Brand & Style") or "", sections.get("Do's and Don'ts") or "") if x).strip()
    comps = []
    for name, props in (fm.get("components") or {}).items() if isinstance(fm.get("components"), dict) else []:
        if isinstance(props, dict):
            comps.append({"name": str(name), "props": {k: _resolve_ref(v, fm) for k, v in props.items()}})
    return {"kind": "designmd", "name": str(fm.get("name") or ""), "tokens": tokens, "palette": _palette(colors), "css": "", "notes": notes[:4000],
            "components": comps, "sections": {k: v[:4000] for k, v in sections.items()}}


def to_design_md(ds: dict | None, project: dict | None = None) -> str:
    """Our design system (+ what the screens use) → a DESIGN.md other agents and tools can read."""
    ds = ds or {}
    t = dict(ds.get("tokens") or {})
    if project and not t:
        for s in project.get("screens") or []:
            if s.get("spec") and s["spec"].get("tokens"):
                t = dict(s["spec"]["tokens"]); break
    dark = str(t.get("theme", "")).lower() == "dark"
    primary = t.get("primary") or "#2563eb"
    colors = {"primary": primary, "secondary": t.get("accent") or primary, "background": t.get("bg") or ("#0f1115" if dark else "#f6f7f9"),
              "surface": t.get("surface") or ("#171a21" if dark else "#ffffff"), "on-surface": t.get("text") or ("#e8eaf0" if dark else "#121417"),
              "on-surface-variant": t.get("muted") or ("#8b93a7" if dark else "#6b7280"), "outline": t.get("line") or ("#262b36" if dark else "#e5e7eb")}
    for k in ("ok", "warn", "bad"):
        if t.get(k):
            colors[{"ok": "success", "warn": "warning", "bad": "error"}[k]] = t[k]
    font = t.get("font") or "system-ui, sans-serif"
    r = int(t.get("radius") or 12) if str(t.get("radius") or 12).strip().isdigit() else _px(str(t.get("radius")))
    name = ds.get("name") or (project or {}).get("name") or "Design system"
    q = lambda v: '"' + str(v).replace('"', '\\"') + '"'
    L = ["---", "version: alpha", f"name: {q(name)}", "colors:"] + [f"  {k}: {q(v)}" for k, v in colors.items()]
    L += ["typography:", "  h1:", f"    fontFamily: {q(font)}", "    fontSize: 26px", "    fontWeight: 700", "    letterSpacing: -0.02em",
          "  h3:", f"    fontFamily: {q(font)}", "    fontSize: 15px", "    fontWeight: 600",
          "  body-md:", f"    fontFamily: {q(font)}", "    fontSize: 14px", "    fontWeight: 400", "    lineHeight: 1.5",
          "  label-sm:", f"    fontFamily: {q(font)}", "    fontSize: 12px", "    fontWeight: 600", "    letterSpacing: 0.04em"]
    L += ["rounded:", f"  sm: {max(4, r - 4)}px", f"  md: {r}px", f"  lg: {r + 6}px", "  full: 999px"]
    L += ["spacing:", "  xs: 4px", "  sm: 8px", "  md: 16px", "  lg: 20px", "  xl: 32px"]
    L += ["components:", "  button-primary:", "    backgroundColor: \"{colors.primary}\"", "    textColor: \"#ffffff\"", "    typography: \"{typography.label-sm}\"", "    rounded: \"{rounded.sm}\"", "    padding: 9px 14px",
          "  card:", "    backgroundColor: \"{colors.surface}\"", "    textColor: \"{colors.on-surface}\"", "    rounded: \"{rounded.md}\"", "    padding: 20px",
          "  input:", "    backgroundColor: \"{colors.surface}\"", "    textColor: \"{colors.on-surface}\"", "    rounded: \"{rounded.sm}\"", "    height: 36px", "---", ""]
    theme = "Dark" if dark else "Light"
    L += ["## Overview", "", (ds.get("notes") or "").strip() or f"{theme} interface built from a small token set: one primary colour for interaction, neutral surfaces with 1px outlines, {font.split(',')[0].strip()} throughout. Calm, dense enough for real data, no decorative gradients.", ""]
    L += ["## Colors", ""] + [f"- **{k} ({v}):** " + {"primary": "the single interaction colour — primary buttons, active nav, links, focus rings.", "secondary": "accent for highlights, charts' second series, badges.",
          "background": "page canvas.", "surface": "cards, panels, inputs sit on this.", "on-surface": "body text and headings.", "on-surface-variant": "muted text: captions, metadata, placeholders.",
          "outline": "1px borders and dividers.", "success": "positive states and deltas.", "warning": "attention states.", "error": "destructive actions and failures."}.get(k, "") for k, v in colors.items()] + [""]
    L += ["## Typography", "", f"- Font stack: `{font}`.", "- h1 26px/700 with −0.02em tracking; h3 15px/600; body 14px/400 at 1.5 line height; labels 12px/600 uppercase-ish with 0.04em tracking.", "- Numbers in stats: 30px/700, tabular figures.", ""]
    L += ["## Layout", "", "- Page padding 32px on desktop, 16px on phone; grid gap 20px; card padding 20px.", "- Desktop shells: left sidebar 240px or a top nav; content max-width 1200px. Phone: single column with a bottom tab bar.", ""]
    L += ["## Elevation & Depth", "", "- Flat. Depth comes from surface-on-background contrast and 1px outlines, not shadows. At most one soft shadow for popovers.", ""]
    L += ["## Shapes", "", f"- Radius scale: controls {max(4, r - 4)}px, cards {r}px, large containers {r + 6}px, pills 999px.", ""]
    L += ["## Components", ""]
    for c in ds.get("components") or []:
        L += [f"### {c.get('name')}", "", (c.get("description") or "").strip(), "", "```html", (c.get("html") or "").strip(), "```", ""]
    L += ["- **Button (primary):** primary background, white label, small radius, 9px 14px padding. Secondary buttons: surface background with outline.",
          "- **Card:** surface background, outline border, medium radius, 20px padding, 12px internal gap.",
          "- **Input:** 36px tall, outline border, small radius; focus ring in primary.",
          "- **Table:** header labels in on-surface-variant 12px uppercase; rows separated by outline; status cells as pills.", ""]
    L += ["## Do's and Don'ts", "", "- Do take every colour, radius and font from the tokens above; never hard-code a hex in a component.",
          "- Do keep one primary action per view.", "- Don't add gradients, drop shadows or decorative illustration.", "- Don't load fonts or scripts from a CDN; the product must run offline.", ""]
    return "\n".join(L)
