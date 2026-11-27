"""Style profile: what a project should feel like, chosen up front (directions, example sites, preferences).

project.style = {
  "directions": ["editorial", "shader"],             # ids from DIRECTIONS, in order (variant A, B, C… use them)
  "prefs": {"theme": "dark", "motion": "subtle", …},  # PREFS keys
  "references": [{"url", "title", "palette", "fonts", "traits", "note", "image"}],
  "notes": "free text",
}
Every generation gets style_prompt(); variants get one chosen direction each (variant_directions()).
"""
from __future__ import annotations

import html as _html
import re

from . import effects

# id → name, blurb (UI), prompt (what the model is told), fx (unlocks effects), preview (original HTML for the card)
DIRECTIONS: dict[str, dict] = {
    "minimal": {"name": "Minimal & precise", "blurb": "Whitespace, one accent, exact type",
                "prompt": "minimal and precise — generous whitespace, a restrained neutral palette with a single accent, precise typographic hierarchy, hairline rules, no decoration",
                "preview": '<div style="height:100%;background:#fff;padding:22px;font-family:system-ui;color:#111"><div style="font-size:10px;letter-spacing:.2em;color:#999">STUDIO</div><div style="font-size:22px;font-weight:500;margin:22px 0 8px;letter-spacing:-.02em">Quiet confidence.</div><div style="height:1px;background:#e5e5e5;margin:12px 0"></div><span style="font-size:11px;color:#2563eb">Read more →</span></div>'},
    "bold": {"name": "Bold & expressive", "blurb": "Huge type, saturated colour",
             "prompt": "bold and expressive — oversized display type, strong saturated colour blocks, confident asymmetric layout, high contrast",
             "preview": '<div style="height:100%;background:#facc15;padding:16px;font-family:Impact,Haettenschweiler,system-ui;color:#111;overflow:hidden"><div style="font-size:44px;line-height:.9;font-weight:900">BIG<br>IDEAS.</div><div style="position:absolute;right:-20px;bottom:-20px;width:110px;height:110px;border-radius:50%;background:#ef4444"></div></div>'},
    "editorial": {"name": "Editorial / print", "blurb": "Serif headlines, engravings",
                  "prompt": "editorial print — magazine grid, serif display headings, refined body copy, generous margins, captions, vintage engraving-style illustration (use public-domain images from the brand assets when provided)",
                  "preview": '<div style="height:100%;background:#f5f0e6;padding:16px;font-family:Georgia,serif;color:#222;display:grid;grid-template-columns:1.3fr 1fr;gap:12px"><div><div style="font-size:9px;letter-spacing:.2em">VOL. XII</div><div style="font-size:22px;line-height:1.05;margin-top:6px;font-style:italic">On the Nature of Ferns</div><div style="font-size:8px;line-height:1.5;margin-top:8px;color:#555">A measured column of text about the woods, the fronds and the light.</div></div><div style="background:repeating-linear-gradient(45deg,#cfc6b4 0 1px,transparent 1px 4px),repeating-linear-gradient(-45deg,#cfc6b4 0 1px,transparent 1px 5px);border:1px solid #bdb3a0"></div></div>'},
    "shader": {"name": "Generative shader", "blurb": "Animated GPU backgrounds", "fx": True,
               "prompt": "generative — an animated GPU shader background (data-ld-shader) behind the hero or key section, content on calm translucent panels on top",
               "preview": re.sub(r"<p .*?</p>|<h2.*?</h2>", "", effects.demo("shader", "mesh").replace("min-height:320px", "height:100%;min-height:0").replace("font-size:34px", "font-size:20px"))},
    "ascii": {"name": "ASCII / terminal", "blurb": "Monospace, character art", "fx": True,
              "prompt": "ASCII / terminal — monospace type, character-based ornaments and dividers, an animated ASCII art element (data-ld-ascii), terminal palette",
              "preview": '<div data-ld-ascii="orb" data-ld-size="9" style="height:100%;background:#0a0a0a;color:#4ade80"></div>'},
    "motion": {"name": "Motion-rich", "blurb": "Staggered entrances, tickers",
               "prompt": "motion-rich — purposeful CSS animation: staggered entrances, hover micro-interactions, a marquee/ticker, animated gradients; wrap it all in @media (prefers-reduced-motion: no-preference)",
               "preview": '<style>@keyframes ldm{0%,100%{transform:translateY(0)}50%{transform:translateY(-10px)}}@keyframes ldt{to{transform:translateX(-50%)}}</style><div style="height:100%;background:#111;color:#fff;font-family:system-ui;overflow:hidden;position:relative"><div style="display:flex;gap:8px;padding:22px 16px">' + "".join(f'<div style="width:28px;height:28px;border-radius:8px;background:hsl({h},90%,60%);animation:ldm 1.6s {d}s ease-in-out infinite"></div>' for h, d in [(330, 0), (40, .15), (160, .3), (210, .45)]) + '</div><div style="position:absolute;bottom:10px;white-space:nowrap;font-size:13px;font-weight:700;animation:ldt 6s linear infinite">NEW DROP ✦ NEW DROP ✦ NEW DROP ✦ NEW DROP ✦ NEW DROP ✦ NEW DROP ✦</div></div>'},
    "dark": {"name": "Dark & luminous", "blurb": "Deep backgrounds, glow",
             "prompt": "dark and luminous — deep near-black background, luminous accent gradients and soft glows, high-contrast text",
             "preview": '<div style="height:100%;background:radial-gradient(circle at 70% 30%,#312e81 0,#05050a 60%);padding:20px;font-family:system-ui;color:#fff"><div style="font-size:24px;font-weight:700;background:linear-gradient(90deg,#a78bfa,#22d3ee);-webkit-background-clip:text;color:transparent">Night mode</div><div style="margin-top:14px;width:90px;height:26px;border-radius:999px;background:#22d3ee;box-shadow:0 0 24px #22d3ee"></div></div>'},
    "soft": {"name": "Soft & friendly", "blurb": "Pastels, big radii",
             "prompt": "soft and friendly — pastel palette, large radii, gentle shadows, rounded friendly type, warm approachable copy",
             "preview": '<div style="height:100%;background:#fdf2f8;padding:14px;font-family:ui-rounded,system-ui;display:grid;grid-template-columns:1fr 1fr;gap:10px"><div style="background:#fff;border-radius:18px;box-shadow:0 6px 16px #f9a8d455;padding:10px;font-size:12px">Hi there 👋</div><div style="background:#e0f2fe;border-radius:18px"></div><div style="background:#ecfccb;border-radius:18px;grid-column:span 2"></div></div>'},
    "dense": {"name": "Dense & data-rich", "blurb": "Compact tables, dashboards",
              "prompt": "dense and data-rich — compact spacing, tables, small multiples and sparklines, dashboard feel, tabular numbers",
              "preview": '<div style="height:100%;background:#fff;padding:10px;font:10px/1.4 system-ui;color:#333">' + "".join(f'<div style="display:grid;grid-template-columns:2fr 1fr 1fr;border-bottom:1px solid #eee;padding:3px 0"><span>Region {c}</span><span style="font-variant-numeric:tabular-nums">{v}</span><span style="color:{col}">{d}</span></div>' for c, v, d, col in [("A", "12,480", "+4.2%", "#16a34a"), ("B", "9,113", "−1.1%", "#dc2626"), ("C", "7,902", "+0.8%", "#16a34a"), ("D", "5,441", "+2.0%", "#16a34a"), ("E", "3,005", "−3.4%", "#dc2626")]) + '</div>'},
    "brutalist": {"name": "Brutalist", "blurb": "Raw grids, hard edges",
                  "prompt": "brutalist — raw visible structure, thick borders and grid lines, monospace or grotesque type, unexpected layout, flat harsh colours, no shadows or gradients",
                  "preview": '<div style="height:100%;background:#fff;font-family:ui-monospace,monospace;display:grid;grid-template-columns:1fr 1fr;border:3px solid #000"><div style="border-right:3px solid #000;padding:8px;font-size:18px;font-weight:700">INDEX</div><div style="background:#0000ff;color:#fff;padding:8px;font-size:11px">01 / WORK<br>02 / INFO</div><div style="grid-column:span 2;border-top:3px solid #000;padding:8px;font-size:11px;background:#ff0">→ CONTACT</div></div>'},
    "retro": {"name": "Retro", "blurb": "80s / Y2K nostalgia", "fx": True,
              "prompt": "retro — a period palette and type that fits the brief (70s, 80s synthwave or Y2K), grain and texture, nostalgic ornaments; an effect such as data-ld-shader=\"sunset\" or \"grid\" may set the mood",
              "preview": re.sub(r"<p .*?</p>|<h2.*?</h2>", "", effects.demo("shader", "sunset").replace("min-height:320px", "height:100%;min-height:0"))},
    "glass": {"name": "Glass & gradients", "blurb": "Frosted panels, vivid mesh", "fx": True,
              "prompt": "glass and gradients — a vivid mesh-gradient background (data-ld-shader=\"mesh\" or CSS), frosted translucent panels (backdrop-filter: blur), thin light borders",
              "preview": '<section data-ld-shader="mesh" style="height:100%;display:grid;place-items:center"><div style="padding:14px 18px;border-radius:16px;background:rgba(255,255,255,.18);backdrop-filter:blur(12px);border:1px solid rgba(255,255,255,.45);color:#fff;font:600 15px system-ui">Frosted panel</div></section>'},
}

PREFS = {
    "theme": ["auto", "light", "dark"],
    "motion": ["none", "subtle", "rich"],
    "density": ["airy", "balanced", "dense"],
    "shape": ["sharp", "rounded", "pill"],
    "type": ["sans", "serif", "mono", "mixed"],
    "imagery": ["minimal", "photography", "engravings", "generative", "ASCII"],
}

# Where to find references. Shown as links: localdesign does not copy content from them.
INSPIRATION = [
    {"name": "Shadertoy", "url": "https://www.shadertoy.com/", "hint": "Find a shader you like, copy its code, then UI kits → Shader backgrounds → Paste a shader. Shaders are non-commercial unless the author says otherwise."},
    {"name": "MotionSites", "url": "https://motionsites.ai/", "hint": "Motion-heavy landing pages. Paste a site URL below, or a prompt you have licensed there as your brief."},
    {"name": "kibitz.art", "url": "https://kibitz.art/", "hint": "Paste the URL of anything you like there below."},
    {"name": "ASCII Magic", "url": "https://ascii-magic.com/app", "hint": "Image → ASCII editor. localdesign has ASCII effects and image → ASCII built in (UI kits → ASCII, and ⌗ on an asset)."},
    {"name": "Public Domain Image Archive", "url": "https://pdimagearchive.org/", "hint": "Out-of-copyright artwork. Copy an image's address and import it under Library → Public domain."},
    {"name": "Godly", "url": "https://godly.website/", "hint": "Curated web design. Paste any site you like below."},
    {"name": "SiteInspire", "url": "https://www.siteinspire.com/", "hint": "Web design showcase by style and type."},
]

_SERIF = re.compile(r"(?<!sans )serif(?!-)|alegreya|crimson|cormorant|libre caslon|eb garamond|source serif|pt serif|garamond|playfair|tiempos|canela|caslon|baskerville|didot|bodoni|sectra|freight|georgia|merriweather|lora|fraunces|newsreader|instrument serif|editorial", re.I)
_MONO = re.compile(r"mono|courier|consolas|menlo|jetbrains|ibm plex mono|space mono|fira code", re.I)
_GENERIC = {"sans-serif", "serif", "monospace", "system-ui", "inherit", "initial", "ui-sans-serif", "ui-serif", "ui-monospace", "-apple-system", "blinkmacsystemfont",
            "segoe ui", "roboto", "helvetica neue", "arial", "helvetica", "apple color emoji", "segoe ui emoji", "segoe ui symbol", "noto color emoji", "var", "emoji", "cursive"}


def _lum(hexcol: str) -> float | None:
    m = re.fullmatch(r"#?([0-9a-f]{6}|[0-9a-f]{3})", (hexcol or "").strip().lower())
    if not m:
        return None
    h = m.group(1)
    h = "".join(c * 2 for c in h) if len(h) == 3 else h
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def fonts_of(css: str, html: str) -> list[str]:
    """First real family of each font-family declaration (skips generics, '… Fallback' and Next.js hashes: __Inter_d65c78 → Inter)."""
    out: list[str] = []
    for decl in re.findall(r"font-family\s*:\s*([^;}]+)", css or "", re.I) + re.findall(r"fonts\.googleapis\.com/css2?\?family=([^\"'&>]+)", html or "", re.I):
        for fam in decl.replace("+", " ").split(","):
            name = fam.strip().strip("\"'").split(":")[0].strip()
            name = re.sub(r"^_+|_[0-9a-f]{5,}$", "", name).replace("_", " ").strip()
            low = name.lower()
            if not name or low in _GENERIC or low.startswith(("var(", "--")) or low.endswith("fallback") or len(name) >= 40:
                continue
            if name not in out:
                out.append(name)
            break
    return out[:6]


def traits_of(html: str, css: str, scripts: str, tokens: dict) -> list[str]:
    blob = (html or "") + "\n" + (scripts or "")
    low, cl = blob.lower(), (css or "").lower()
    t = []
    if re.search(r"getcontext\(\s*['\"]webgl|three(?:\.module)?(?:\.min)?\.js|\bogl\b|\bregl\b|pixi|gl_fragcolor|uniform\s+(?:float|vec)|shadertoy|data-ld-shader", low):
        t.append("WebGL / shader graphics")
    if re.search(r"three(?:\.module)?|@react-three|spline\.design|splinetool|\.glb\b|\.gltf\b", low):
        t.append("3D scenes")
    if "<canvas" in low and not t:
        t.append("canvas animation")
    if re.search(r"gsap|scrolltrigger|framer-motion|motion\.dev|lottie|anime(?:\.min)?\.js|\baos\b|data-aos|barba", low) or cl.count("@keyframes") >= 6:
        t.append("heavy motion")
    if re.search(r"lenis|locomotive-scroll|smooth-scroll", low):
        t.append("smooth scrolling")
    if re.search(r"<video[^>]+autoplay", low):
        t.append("video background")
    if "backdrop-filter" in cl:
        t.append("glass / blur")
    if cl.count("gradient(") >= 4:
        t.append("gradients")
    if re.search(r"noise|grain", cl) or re.search(r"feturbulence", low):
        t.append("grain / noise texture")
    if low.count("<pre") >= 2 or re.search(r"ascii", low):
        t.append("ASCII / monospace art")
    bg = _lum(str(tokens.get("bg", "")))
    if bg is not None:
        t.append("dark" if bg < 0.3 else "light")
    r = tokens.get("radius")
    if isinstance(r, (int, float)):
        t.append("sharp corners" if r <= 2 else "rounded" if r >= 12 else "")
    return [x for x in t if x]


def analysis(url: str, title: str, html: str, css: str, scripts: str, parsed: dict) -> dict:
    tokens = parsed.get("tokens") or {}
    fonts = fonts_of(css, html)
    traits = traits_of(html, css, scripts, tokens)
    if any(_SERIF.search(f) for f in fonts[:2]):
        traits.append("serif display")
    if any(_MONO.search(f) for f in fonts[:2]):
        traits.append("monospace type")
    og = re.search(r"""<meta[^>]+property=["']og:image["'][^>]+content=["']([^"']+)""", html or "", re.I) or re.search(r"""<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:image""", html or "", re.I)
    desc = re.search(r"""<meta[^>]+name=["']description["'][^>]+content=["']([^"']+)""", html or "", re.I)
    from urllib.parse import urljoin
    palette = []
    for c in parsed.get("palette") or []:   # plain opaque colours only, no near-duplicates
        v = str(c.get("value") or "").strip().lower()
        if re.fullmatch(r"#[0-9a-f]{6}|#[0-9a-f]{3}", v) and v not in palette:
            palette.append(v)
    return {"url": url, "title": _html.unescape(title or url)[:120], "description": _html.unescape(desc.group(1) if desc else "")[:200],
            "image": urljoin(url, _html.unescape(og.group(1))) if og else "", "palette": palette[:8], "tokens": tokens, "fonts": fonts, "traits": traits}


def style_prompt(style: dict | None, compact: bool = False) -> str:
    """The style profile as prompt text (empty when nothing was chosen)."""
    if not isinstance(style, dict):
        return ""
    dirs = [DIRECTIONS[d] for d in style.get("directions") or [] if d in DIRECTIONS]
    prefs = {k: v for k, v in (style.get("prefs") or {}).items() if k in PREFS and v and v != "auto"}
    refs = [r for r in style.get("references") or [] if isinstance(r, dict) and r.get("url")]
    notes = str(style.get("notes") or "").strip()
    if not (dirs or prefs or refs or notes):
        return ""
    L = ["Style profile the user chose for this project (follow it unless the request says otherwise; an explicit design system's tokens take priority):"]
    if dirs:
        L.append("- Directions: " + "; ".join(f"{d['name']} ({d['prompt']})" for d in dirs) + ("." if len(dirs) == 1 else ". Blend them, or use the one this variant is assigned."))
    if prefs:
        L.append("- Preferences: " + ", ".join(f"{k} {v}" for k, v in prefs.items()) + ".")
    if refs and not compact:
        L.append("- Sites the user likes — match their feel (palette, type, density, motion); never copy their content, copy, logos or branding:")
        for r in refs[:6]:
            bits = [f"palette {', '.join(r.get('palette') or [])}" if r.get("palette") else "", f"fonts {', '.join(r.get('fonts') or [])}" if r.get("fonts") else "",
                    ", ".join(r.get("traits") or [])]
            note = f' — the user says: "{str(r.get("note"))[:200]}"' if r.get("note") else ""
            L.append(f"  • {r.get('title') or r['url']} ({r['url']}){note}" + (f"; {'; '.join(b for b in bits if b)}" if any(bits) else ""))
    if notes:
        L.append(f"- Notes: {notes[:600]}")
    return "\n".join(L)


def wants_fx(style: dict | None, brief: str = "") -> bool:
    s = style if isinstance(style, dict) else {}
    if any(DIRECTIONS.get(d, {}).get("fx") for d in s.get("directions") or []):
        return True
    if (s.get("prefs") or {}).get("imagery") in ("generative", "ASCII"):
        return True
    if any("shader" in " ".join(r.get("traits") or []).lower() or "ascii" in " ".join(r.get("traits") or []).lower() for r in s.get("references") or [] if isinstance(r, dict)):
        return True
    return bool(re.search(r"shader|webgl|generative|ascii|aurora|plasma|starfield|animated background", brief or "", re.I))


def variant_directions(style: dict | None) -> list[str] | None:
    """One 'Design direction for this variant' line per chosen direction (variants rotate through them)."""
    ids = [d for d in (style or {}).get("directions") or [] if d in DIRECTIONS] if isinstance(style, dict) else []
    return [f"Design direction for this variant: {DIRECTIONS[d]['prompt']}." for d in ids] or None


def catalog() -> dict:
    """Everything the onboarding dialog needs; previews are complete HTML documents (effects runtime included)."""
    def doc(body: str) -> str:
        return ("<!doctype html><html><head><meta charset='utf-8'><style>html,body{margin:0;height:100%;overflow:hidden}body>*{position:relative}</style></head><body>"
                + body + effects.RUNTIME_TAG + "</body></html>")
    return {"directions": [{"id": k, "name": v["name"], "blurb": v["blurb"], "fx": bool(v.get("fx")), "preview": doc(v["preview"])} for k, v in DIRECTIONS.items()],
            "prefs": PREFS, "inspiration": INSPIRATION, "fx_runtime": effects.RUNTIME_TAG}
