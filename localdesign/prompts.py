"""Prompts for screen generation and iteration."""
from __future__ import annotations

import json
import re

from .components import NODE_DOCS, EXAMPLE_SPEC

# Shared craft rules: what makes a screen read as "AI-generated", and what to do instead.
# Kept brace-free because SYSTEM goes through str.format.
CRAFT_RULES = """Craft rules — the screen must look like a real team shipped it, not like generated UI:
- No purple/indigo/violet-to-blue gradients, no gradient text, no glassmorphism, no glows, no decorative blobs or noise. Flat surfaces; at most one subtle gradient on the whole page, and only if the brand calls for it.
- One accent colour, used sparingly (primary action, active nav item, selected state, one key data series). Everything else is neutrals. Status colours (red/amber/green) only for actual status.
- Do not wrap every section in an identical rounded, shadowed card. Mix treatments: some content sits directly on the page with a heading and a divider; cards only where grouping helps. Never put cards inside cards. Shadows light or none; radius modest (4–10px) and consistent.
- No emoji as icons. Use simple, consistent inline SVG line icons (one stroke width, 16–20px) or no icon at all. No ✨, 🚀, 👋. Not every list item or heading needs an icon.
- No row of three identical icon + title + blurb feature cards; no coloured left-border accent cards; no badges or pills on everything.
- Labels in sentence case. Avoid tiny uppercase letter-spaced labels except for at most one deliberate eyebrow. No exclamation marks.
- Copy is plain and specific, the way the product's own team would write it: "Export CSV", "3 invoices overdue", not "Unlock insights", "Seamless", "Elevate", "Supercharge", "Effortlessly". No welcome greetings ("Good morning, Alex 👋") unless the brief asks for one; lead with the page's job.
- Data looks real: uneven numbers (1,284 not 1,000; 97.3% not 99.9%), plausible dates, varied names (not John Doe / Jane Smith / Acme), a few rows that are empty, long or in an error state. Right-align numeric columns and use tabular figures (font-variant-numeric: tabular-nums).
- Hierarchy from size, weight and spacing, not colour. Two or three type sizes per screen, weights 400/500/600 (avoid 800–900). Left-align by default; centre only short, standalone content.
- Density fits the job: operational tools are compact and information-dense; don't pad a dashboard like a landing page. Align everything to one spacing scale (4/8px) and one grid.
- Include the unglamorous parts real products have: filters, sort, pagination or "Show 20 more", empty and loading states where relevant, secondary actions, timestamps, owners."""

SPEC_CRAFT_RULES = """Craft rules — make it look like a real product, not generated UI:
- Plain, specific copy ("Export CSV", "3 invoices overdue"). No hype words (unlock, seamless, elevate, supercharge), no exclamation marks, no emoji, no welcome greetings; the heading says what the page is.
- Realistic, uneven numbers (1,284; 97.3%), varied real-sounding names (not John Doe / Acme), dates and timestamps; include one or two rows in a warning or empty state.
- Fewer, better sections: no filler feature cards, no badge on every item. Use badges only for real status.
- One primary action per screen; other actions secondary. Pick a calm primary colour (not purple/indigo by default) and keep density "compact" for data-heavy tools."""

SYSTEM = """You are a senior product designer who designs by writing HTML. You produce finished, high-craft UI screens as a single self-contained HTML document.

Output rules (strict):
- Output ONLY the HTML document, starting with <!DOCTYPE html> and ending with </html>. No explanation, no markdown fences.
- Everything inline: a single <style> block in <head>, no external stylesheets, scripts, fonts or images{cdn_rule}.
- For imagery use CSS gradients, solid color blocks, inline SVG icons, or emoji. Never reference image URLs, except the brand assets listed in the request (use those exact URLs with <img>).
- Use realistic, specific content (real-sounding names, numbers, copy). No "Lorem ipsum", no "Heading 1".
- Design for a viewport {width}px wide. Set body margin 0 and make the layout fill that width. Do not add outer device frames.
- Use a coherent design system: a limited palette defined as CSS variables on :root, one or two font stacks (system-ui is fine), consistent spacing scale and radii, clear type hierarchy, generous whitespace.
- Interactive states are static (no JS needed), but you may add small amounts of inline JS for tabs/toggles if it helps the demo.
- Accessibility basics: sufficient contrast, semantic elements, labels on inputs.

{craft}
{direction}"""

DIRECTIONS = [
    "Design direction for this variant: clean and minimal — lots of whitespace, a neutral palette with one accent, precise typography, almost no shadows.",
    "Design direction for this variant: bold — one strong brand colour used in large, confident blocks (not gradients), large type, clear hierarchy.",
    "Design direction for this variant: warm and friendly — warm neutrals, softer corners, approachable plain-spoken copy; still no emoji or gradients.",
    "Design direction for this variant: dense and data-rich — compact spacing, tables over cards, tabular numbers, the feel of a tool used eight hours a day.",
    "Design direction for this variant: editorial — magazine-like layout, serif headings, strong grid, rules and whitespace instead of cards.",
    "Design direction for this variant: dark mode — near-black neutral background (not navy or purple), restrained accent, high contrast text, no glows.",
]

ITERATE = """Here is the current screen HTML:

```html
{html}
```

Apply this change: {instruction}

Keep everything else the same (same design system, same content) unless the change requires otherwise. Do not introduce generated-UI clichés while you are at it: no new gradients, glows, emoji icons, hype copy or extra badges. Return the complete updated HTML document only."""

ELEMENT_ITERATE = """You are editing ONE element inside an existing screen. The page's CSS (variables and relevant rules) is:

```css
{css}
```

The element to change:

```html
{html}
```

Apply this change: {instruction}

Return ONLY the replacement HTML for this element (the same element, modified, or what should take its place). Keep its classes and structure unless the change requires otherwise. If you need new CSS rules, put them in a <style> tag immediately before the element. No explanation, no markdown fences, no full-page HTML."""

CDN_RULE_ALLOWED = ". Exception: you MAY load Tailwind via <script src=\"https://cdn.tailwindcss.com\"></script> and Google Fonts via <link>"


def system_prompt(width: int, direction: str | None, allow_cdn: bool) -> str:
    return SYSTEM.format(width=width, direction=direction or "", cdn_rule=CDN_RULE_ALLOWED if allow_cdn else "", craft=CRAFT_RULES)


def generate_user_prompt(brief: str, context: str | None, verb: str | None = None) -> str:
    out = f"{verb or 'Design this screen:'}\n\n{brief}"
    if context:
        out += f"\n\nProject context (keep consistent with it):\n{context}"
    return out


_FENCE = re.compile(r"```(?:html)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_html(text: str) -> str:
    """Pull the HTML document out of a model reply (tolerates fences and chatter)."""
    m = _FENCE.search(text)
    if m and "<" in m.group(1):
        text = m.group(1)
    low = text.lower()
    start = low.find("<!doctype")
    if start < 0:
        start = low.find("<html")
    if start > 0:
        text = text[start:]
    end = text.lower().rfind("</html>")
    if end >= 0:
        text = text[: end + len("</html>")]
    return text.strip()


def partial_html(text: str) -> str:
    """Best-effort HTML for live preview while streaming (strip leading fence/chatter)."""
    i = text.find("```")
    if i >= 0:
        nl = text.find("\n", i)
        text = text[nl + 1:] if nl >= 0 else ""
    low = text.lower()
    start = low.find("<!doctype")
    if start < 0:
        start = low.find("<html")
    if start < 0:
        start = low.find("<style")
    return text[start:] if start >= 0 else ""


# --------------------------------------------------------------------------- spec mode (small models)
SPEC_SYSTEM = """You are a product designer. You design screens by writing a compact JSON layout spec; a renderer turns it into a polished UI. Do not write HTML.

Output rules (strict):
- Output ONLY one JSON object. No prose, no markdown fences, no comments.
- Top level: {"title", "tokens":{"primary":"#hex","theme":"light|dark","radius":int,"density":"normal|compact"}, "layout":"sidebar|topnav|plain|centered|mobile", "nav":{"brand","items":[..],"active","user"}, "sections":[node, ...]}
- Use realistic, specific content: real-sounding names, numbers, dates, copy. Never "Lorem ipsum" or placeholder text.
- Aim for 4-8 sections that together make a complete, believable screen. Use grid/split to put things side by side on wide screens.
- Viewport is {width}px wide{mobile_hint}.

{craft}
{direction}
{nodes}

Example of a complete spec:
{example}"""

SPEC_ITERATE = """Current screen spec:
{spec}

Apply this change: {instruction}

Return the complete updated spec as one JSON object only. Keep everything else the same unless the change requires otherwise."""


def spec_system_prompt(width: int, direction: str | None) -> str:
    mobile = ", a phone: prefer layout \"mobile\", single-column sections and a tabbar" if width <= 480 else ""
    return (SPEC_SYSTEM.replace("{width}", str(width)).replace("{mobile_hint}", mobile)
            .replace("{craft}", SPEC_CRAFT_RULES).replace("{direction}", direction or "").replace("{nodes}", NODE_DOCS)
            .replace("{example}", json.dumps(EXAMPLE_SPEC, separators=(",", ":"))))


def design_system_prompt(ds: dict | None, for_spec: bool) -> str:
    """Design-system constraints appended to the user prompt (tokens + component snippets)."""
    if not ds:
        return ""
    parts = []
    tk = ds.get("tokens") or {}
    if tk:
        parts.append("Design tokens (use these exactly): " + json.dumps({k: v for k, v in tk.items() if v}, separators=(",", ":")))
    if ds.get("name"):
        parts.insert(0, f"Design system: {ds['name']}.")
    if ds.get("notes"):
        parts.append("Guidelines: " + str(ds["notes"])[:1500])
    if not for_spec:
        comps = ds.get("components") or []
        if comps:
            parts.append("Component library — reuse this exact markup and class names for these components instead of inventing your own:")
            for c in comps[:20]:
                parts.append(f"<!-- {c.get('name')}: {c.get('description', '')} -->\n{str(c.get('html', ''))[:1500]}")
        if ds.get("css"):
            parts.append("Include this CSS verbatim in the <style> block before your own rules:\n" + str(ds["css"])[:6000])
    return "\n\n".join(parts)


def data_prompt(data: dict | None, for_spec: bool) -> str:
    """Real data sources the screen must use (name → rows)."""
    if not data:
        return ""
    parts = ["Real data to use literally in the UI (do not invent different values):"]
    for name, rows in list(data.items())[:6]:
        if isinstance(rows, dict):
            rows = rows.get("rows") or rows.get("data") or rows.get("items") or rows
        sample = rows[:12] if isinstance(rows, list) else rows
        parts.append(f"Source \"{name}\" ({len(rows) if isinstance(rows, list) else 1} rows): " + json.dumps(sample, separators=(",", ":"), default=str)[:3000])
    if for_spec:
        parts.append('In table/list nodes you may set "data": "<source name>" to have all rows filled in automatically.')
    return "\n".join(parts)


def extract_fragment(text: str) -> str:
    """Pull an HTML fragment (one or more elements) out of a reply."""
    m = _FENCE.search(text)
    if m and "<" in m.group(1):
        text = m.group(1)
    i, j = text.find("<"), text.rfind(">")
    if i < 0 or j < 0:
        return ""
    frag = text[i: j + 1].strip()
    # the model sometimes wraps in a full document anyway
    b = re.search(r"<body[^>]*>(.*)</body>", frag, re.S | re.I)
    if b:
        st = re.findall(r"<style[^>]*>.*?</style>", frag, re.S | re.I)
        frag = "".join(st) + b.group(1).strip()
    return frag


PLAN_SYSTEM = """You are a product designer planning the screens of a product. Given a description (a user journey, a feature request, or a full PRD), list the distinct screens needed.

Output ONLY a JSON array, no prose:
[{"title": "Short screen name", "brief": "2-4 sentences describing exactly what is on this screen: sections, key content, primary action", "links": ["Title of screen the primary action leads to", ...]}]

Rules: {max_screens} screens at most; order them in the sequence a user encounters them; titles must be unique and short (2-4 words); every "links" entry must exactly match another screen's title; the first screen is the entry point."""

FLOW_CONTEXT = """This screen is part of a flow with these screens: {titles}.
Navigation: elements that lead to another screen must carry data-link="<exact screen title>" (buttons, nav items, cards, list rows). This screen should link to: {links}."""


def plan_user_prompt(text: str) -> str:
    return "Plan the screens for this:\n\n" + text.strip()[:12000]


def extract_json_array(text: str):
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    if m:
        text = m.group(1)
    i, j = text.find("["), text.rfind("]")
    if i < 0:
        raise ValueError("no JSON array in reply")
    try:
        return json.loads(text[i: j + 1] if j > i else text[i:])
    except json.JSONDecodeError:
        from .components import repair_json
        inner = repair_json("{" + '"a":' + text[i:] + "}")
        return json.loads(inner)["a"]


REACT_TAILWIND = """Convert this screen into a production-quality React component using Tailwind CSS utility classes (no custom CSS unless unavoidable; CSS variables from the page may be mapped to Tailwind arbitrary values or a small theme comment). Keep the visual design, content and structure. Use semantic JSX, extract obvious repeated pieces into small inner components in the same file, keep data as plain constants at the top so it is easy to replace with props. Export the main component as default. Output ONLY the .jsx file contents, no fences, no commentary.

Component name: {name}

```html
{html}
```"""


ARTIFACT_SYSTEM = """You are an expert front-end engineer and designer. You build complete, working, self-contained interactive artifacts as a single HTML file: small apps, tools, calculators, games, data visualizations, interactive documents, simulations, slides.

Output rules (strict):
- Output ONLY the HTML document, starting with <!DOCTYPE html> and ending with </html>. No explanation, no markdown fences.
- Everything inline: one <style> block and one <script> block. No external scripts, stylesheets, fonts, or images{cdn_rule}. Brand assets listed in the request may be used by their exact URL.
- It must actually work: wire up all interactions in plain JavaScript (no frameworks), handle edge cases, no console errors. Use <canvas> or inline SVG for graphics. State lives in JS variables; persist to localStorage only if useful.
- Make it feel finished: clear layout for a {width}px-wide viewport, sensible defaults and sample data so it is useful immediately, keyboard support where natural, responsive enough to not break when narrower.
- Keep it reasonably compact; prefer clarity over cleverness. No comments longer than a line.
- Visual style: flat surfaces, one accent colour, neutral greys, sentence-case labels, plain copy. No purple-to-blue gradients, gradient text, glows, glassmorphism or emoji icons.
"""


def artifact_system_prompt(width: int, allow_cdn: bool) -> str:
    return ARTIFACT_SYSTEM.replace("{width}", str(width)).replace("{cdn_rule}", CDN_RULE_ALLOWED if allow_cdn else "")


def assets_prompt(assets: list | None) -> str:
    """Company/brand assets the model may reference by URL."""
    if not assets:
        return ""
    lines = ["Brand assets available (use these exact URLs in <img src>; do not invent other image URLs):"]
    for a in assets[:30]:
        dims = f" {a['w']}×{a['h']}" if a.get("w") and a.get("h") else ""
        lines.append(f"- {a.get('name')}: {a.get('url')}{dims}" + (f" — {a['note']}" if a.get("note") else ""))
    return "\n".join(lines)


PACK_NARRATIVE = """Write the overview section of an architecture document for the product designed below, for the engineer or coding agent who will build it.

Write 250-450 words of plain Markdown prose (short paragraphs, `###` sub-headings allowed, no code, no tables, no top-level headings). Cover, in this order: what the product is and who uses it; the core loop a user goes through, naming the screens in the order they are visited; what the key data is and where it comes from; the three to five implementation decisions that matter most (shell/navigation, shared components, state, data loading); and open questions or risks you can see in the designs. Ground every claim in the material below — do not invent screens, fields or features that are not there. Output only the prose.

Product: {name}

{architecture}

{flows}

Screen briefs:
{briefs}"""
