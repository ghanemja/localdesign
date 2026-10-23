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
