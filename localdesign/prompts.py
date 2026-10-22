"""Prompts for screen generation and iteration."""
from __future__ import annotations

import re

SYSTEM = """You are a senior product designer who designs by writing HTML. You produce finished, high-craft UI screens as a single self-contained HTML document.

Output rules (strict):
- Output ONLY the HTML document, starting with <!DOCTYPE html> and ending with </html>. No explanation, no markdown fences.
- Everything inline: a single <style> block in <head>, no external stylesheets, scripts, fonts or images{cdn_rule}.
- For imagery use CSS gradients, solid color blocks, inline SVG icons, or emoji. Never reference image URLs.
- Use realistic, specific content (real-sounding names, numbers, copy). No "Lorem ipsum", no "Heading 1".
- Design for a viewport {width}px wide. Set body margin 0 and make the layout fill that width. Do not add outer device frames.
- Use a coherent design system: a limited palette defined as CSS variables on :root, one or two font stacks (system-ui is fine), consistent spacing scale and radii, clear type hierarchy, generous whitespace.
- Interactive states are static (no JS needed), but you may add small amounts of inline JS for tabs/toggles if it helps the demo.
- Accessibility basics: sufficient contrast, semantic elements, labels on inputs.
{direction}"""

DIRECTIONS = [
    "Design direction for this variant: clean and minimal — lots of whitespace, restrained palette, precise typography.",
    "Design direction for this variant: bold and expressive — strong color, large type, confident hierarchy.",
    "Design direction for this variant: warm and friendly — soft shapes, rounded corners, approachable tone.",
    "Design direction for this variant: dense and data-rich — compact spacing, tables/cards, dashboard feel.",
    "Design direction for this variant: editorial — magazine-like layout, serif headings, strong grid.",
    "Design direction for this variant: dark mode — deep background, luminous accents, high contrast.",
]

ITERATE = """Here is the current screen HTML:

```html
{html}
```

Apply this change: {instruction}

Keep everything else the same (same design system, same content) unless the change requires otherwise. Return the complete updated HTML document only."""

CDN_RULE_ALLOWED = ". Exception: you MAY load Tailwind via <script src=\"https://cdn.tailwindcss.com\"></script> and Google Fonts via <link>"


def system_prompt(width: int, direction: str | None, allow_cdn: bool) -> str:
    return SYSTEM.format(width=width, direction=direction or "", cdn_rule=CDN_RULE_ALLOWED if allow_cdn else "")


def generate_user_prompt(brief: str, context: str | None) -> str:
    out = f"Design this screen:\n\n{brief}"
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
