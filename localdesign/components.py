"""Spec → HTML renderer with a built-in component library.

Small local models can't write 30 KB of coherent HTML, but they can fill in a compact JSON
layout spec. This module turns that spec into a finished, self-contained HTML document with
consistent styling, so a 7B model produces output that looks designed.

Spec shape (all keys optional except sections):
{
  "title": "Fleet overview",
  "tokens": {"primary": "#1f6feb", "theme": "light|dark", "radius": 10, "font": "system-ui", "density": "normal|compact"},
  "layout": "sidebar|topnav|plain|centered|mobile",
  "nav": {"brand": "Helios", "logo": "/assets/p/logo.svg", "items": ["Overview", "Sites"], "active": "Overview", "user": "Mara L."},
  "sections": [ {"type": "heading", ...}, {"type": "stats", ...}, ... ]
}
See NODE_DOCS for every node type and its props (that text is also what the model is shown).
"""
from __future__ import annotations

import html as _html
import json
import math
import re

# --------------------------------------------------------------------------- docs shown to the model
NODE_DOCS = """Node types and props (strings unless noted; omit what you don't need):
heading {text, sub, actions:[{label, primary:bool, link}]}
stats {items:[{label, value, delta, trend:"up|down"}]}            # KPI cards row
grid {cols:2|3|4, children:[node]}
split {ratio:"2:1"|"1:1"|"1:2", children:[node, node]}
card {title, sub, body, children:[node], actions:[{label, primary, link}]}
text {text, size:"sm|md|lg", muted:bool}
table {title, columns:[..], rows:[[..]], badge_col:int, data:"source-name"}
list {title, items:[{title, sub, meta, badge, icon}]}
chart {kind:"line|bar|area|donut", title, labels:[..], series:[{name, values:[numbers]}], height:int}
form {title, fields:[{label, type:"text|email|password|number|date|select|textarea|checkbox|toggle", placeholder, options:[..], value}], submit, secondary}
buttons {items:[{label, primary, link}], align:"left|right|center"}
tabs {items:[..], active}
chips {items:[..], active}
steps {items:[..], active:int}
pricing {tiers:[{name, price, period, tagline, features:[..], cta, highlight:bool}]}
hero {title, sub, cta, secondary, image:bool, image_src, align:"left|center"}
features {items:[{icon, title, text}], cols:2|3|4}
image {label, src, ratio:"16:9|4:3|1:1|3:4", height:int}                   # src: an asset URL from the list you were given
timeline {items:[{time, title, text}]}
chat {messages:[{from:"me|them|bot", text}], placeholder}
kv {title, items:[{k, v}]}
settings {title, items:[{label, sub, on:bool}]}
progress {label, value:0-100, sub}
alert {kind:"info|success|warning|error", text}
search {placeholder}
breadcrumbs {items:[..]}
avatars {items:[names], label}
calendar {month, highlight:[days]}
tabbar {items:[{icon, label, link}], active}                        # mobile bottom bar
divider {}
footer {text, links:[..]}
Icons: use an emoji or a short word; link: title of another screen this element navigates to."""

EXAMPLE_SPEC = {
    "title": "Fleet overview",
    "tokens": {"primary": "#2f6f3e", "theme": "light", "radius": 12, "density": "normal"},
    "layout": "sidebar",
    "nav": {"brand": "Helios", "items": ["Overview", "Sites", "Alerts", "Reports"], "active": "Overview", "user": "Mara Lindqvist"},
    "sections": [
        {"type": "heading", "text": "Good afternoon, Mara", "sub": "Thursday 12 June · 46 sites reporting", "actions": [{"label": "Export", "primary": False}, {"label": "New site", "primary": True}]},
        {"type": "stats", "items": [{"label": "Output today", "value": "412.6 MWh", "delta": "+8.4%", "trend": "up"}, {"label": "Active alerts", "value": "7", "delta": "3 critical", "trend": "down"}, {"label": "Sites online", "value": "46 / 48"}]},
        {"type": "split", "ratio": "2:1", "children": [
            {"type": "chart", "kind": "area", "title": "Fleet output (MW)", "labels": ["6a", "9a", "12p", "3p", "6p"], "series": [{"name": "Today", "values": [2, 18, 41, 36, 9]}, {"name": "Yesterday", "values": [3, 15, 38, 33, 8]}]},
            {"type": "list", "title": "Alerts", "items": [{"title": "Inverter 4 offline", "sub": "Ridgecrest", "badge": "critical"}, {"title": "String underperforming", "sub": "Mesa Verde", "badge": "warning"}]}
        ]},
        {"type": "table", "title": "Sites", "columns": ["Site", "Capacity", "Today", "Status"], "rows": [["Ridgecrest", "12.4 MW", "71 MWh", "Online"], ["Mesa Verde", "9.8 MW", "58 MWh", "Degraded"]], "badge_col": 3}
    ],
}

# --------------------------------------------------------------------------- CSS
BASE_CSS = """
*{box-sizing:border-box}html,body{margin:0;padding:0}
body{font-family:var(--font);color:var(--text);background:var(--bg);font-size:var(--fs);line-height:1.45;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
.ld-app{display:grid;min-height:100vh}
.ld-app.sidebar{grid-template-columns:240px 1fr}
.ld-app.topnav,.ld-app.plain,.ld-app.centered,.ld-app.mobile{grid-template-columns:1fr}
.ld-side{background:var(--side-bg);color:var(--side-text);padding:20px 14px;display:flex;flex-direction:column;gap:6px;border-right:1px solid var(--line)}
.ld-brand{font-weight:700;font-size:17px;padding:6px 10px 16px;display:flex;align-items:center;gap:10px}
.ld-brand .mark{width:28px;height:28px;border-radius:8px;background:var(--primary);display:inline-block}
.ld-side a{padding:9px 12px;border-radius:var(--r-sm);color:var(--side-muted);font-weight:500}
.ld-side a.on{background:var(--side-active);color:var(--side-text)}
.ld-side .spacer{flex:1}
.ld-user{display:flex;align-items:center;gap:10px;padding:10px 12px;border-top:1px solid var(--line);font-size:var(--fs-sm)}
.ld-top{display:flex;align-items:center;gap:22px;padding:0 var(--pad);height:60px;background:var(--surface);border-bottom:1px solid var(--line);position:sticky;top:0}
.ld-top .ld-brand{padding:0}
.ld-top nav{display:flex;gap:4px}
.ld-top nav a{padding:8px 12px;border-radius:var(--r-sm);color:var(--muted);font-weight:500}
.ld-top nav a.on{color:var(--text);background:var(--bg)}
.ld-top .ld-user{border:0;padding:0;margin-left:auto}
.ld-main{padding:var(--pad);display:flex;flex-direction:column;gap:var(--gap);max-width:100%}
.centered .ld-main{max-width:720px;margin:0 auto;width:100%}
.mobile .ld-main{padding:16px;padding-bottom:84px;gap:16px}
.ld-av{width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg,var(--primary),var(--accent));color:#fff;display:inline-flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;flex:none}
.ld-head{display:flex;align-items:flex-end;justify-content:space-between;gap:16px}
.ld-head h1{font-size:var(--fs-h1);margin:0;letter-spacing:-.02em;font-weight:700}
.ld-head p{margin:4px 0 0;color:var(--muted)}
.ld-actions{display:flex;gap:8px;flex-wrap:wrap}
.ld-btn{display:inline-flex;align-items:center;gap:6px;padding:9px 14px;border-radius:var(--r-sm);border:1px solid var(--line);background:var(--surface);font-weight:600;font-size:var(--fs);cursor:pointer;color:var(--text)}
.ld-btn.primary{background:var(--primary);color:#fff;border-color:var(--primary)}
.ld-btn.sm{padding:6px 10px;font-size:var(--fs-sm)}
.ld-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:var(--gap)}
.ld-stat{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:var(--card-pad)}
.ld-stat .l{color:var(--muted);font-size:var(--fs-sm);text-transform:uppercase;letter-spacing:.06em;font-weight:600}
.ld-stat .v{font-size:var(--fs-stat);font-weight:700;letter-spacing:-.02em;margin:6px 0 2px}
.ld-stat .d{font-size:var(--fs-sm);font-weight:600}.ld-stat .d.up{color:var(--ok)}.ld-stat .d.down{color:var(--bad)}
.ld-grid{display:grid;gap:var(--gap)}
.ld-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:var(--card-pad);display:flex;flex-direction:column;gap:12px}
.ld-card>h3{margin:0;font-size:var(--fs-h3);font-weight:600}.ld-card .sub{color:var(--muted);margin:-8px 0 0;font-size:var(--fs-sm)}
.ld-card .body{color:var(--text)}
.ld-text.sm{font-size:var(--fs-sm)}.ld-text.lg{font-size:var(--fs-lg)}.ld-text.muted{color:var(--muted)}
table.ld-table{width:100%;border-collapse:collapse;font-size:var(--fs-sm)}
.ld-table th{text-align:left;color:var(--muted);font-weight:600;padding:8px 10px;border-bottom:1px solid var(--line);font-size:12px;text-transform:uppercase;letter-spacing:.05em}
.ld-table td{padding:10px;border-bottom:1px solid var(--line)}
.ld-table tr:last-child td{border-bottom:0}
.ld-badge{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600;background:var(--chip);color:var(--text)}
.ld-badge.ok{background:var(--ok-bg);color:var(--ok)}.ld-badge.bad{background:var(--bad-bg);color:var(--bad)}.ld-badge.warn{background:var(--warn-bg);color:var(--warn)}.ld-badge.info{background:var(--info-bg);color:var(--primary)}
.ld-list{display:flex;flex-direction:column}
.ld-list .it{display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--line)}
.ld-list .it:last-child{border-bottom:0}
.ld-list .ic{width:36px;height:36px;border-radius:var(--r-sm);background:var(--chip);display:flex;align-items:center;justify-content:center;flex:none;font-size:16px}
.ld-list .t{font-weight:600}.ld-list .s{color:var(--muted);font-size:var(--fs-sm)}.ld-list .m{margin-left:auto;color:var(--muted);font-size:var(--fs-sm);display:flex;gap:8px;align-items:center}
.ld-chart svg{width:100%;height:auto;display:block}
.ld-legend{display:flex;gap:14px;font-size:var(--fs-sm);color:var(--muted)}
.ld-legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:middle}
.ld-form{display:flex;flex-direction:column;gap:14px}
.ld-field label{display:block;font-size:var(--fs-sm);font-weight:600;margin-bottom:6px}
.ld-field input,.ld-field select,.ld-field textarea{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:var(--r-sm);background:var(--surface);color:var(--text);font:inherit}
.ld-field textarea{min-height:90px}
.ld-field.check{display:flex;align-items:center;gap:10px}.ld-field.check label{margin:0}
.ld-form .ld-actions{margin-top:4px}
.ld-tabs{display:flex;gap:2px;border-bottom:1px solid var(--line)}
.ld-tabs a{padding:10px 14px;color:var(--muted);font-weight:500;border-bottom:2px solid transparent;margin-bottom:-1px}
.ld-tabs a.on{color:var(--text);border-color:var(--primary)}
.ld-chips{display:flex;gap:8px;flex-wrap:wrap}
.ld-chips a{padding:6px 12px;border-radius:999px;border:1px solid var(--line);font-size:var(--fs-sm);font-weight:500}
.ld-chips a.on{background:var(--text);color:var(--bg);border-color:var(--text)}
.ld-steps{display:flex;gap:8px;align-items:center}
.ld-steps .st{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:var(--fs-sm);font-weight:500}
.ld-steps .st i{width:26px;height:26px;border-radius:50%;border:2px solid var(--line);display:inline-flex;align-items:center;justify-content:center;font-style:normal;font-size:12px}
.ld-steps .st.on{color:var(--text)}.ld-steps .st.on i{background:var(--primary);border-color:var(--primary);color:#fff}
.ld-steps .st.done i{border-color:var(--primary);color:var(--primary)}
.ld-steps .ln{flex:1;height:2px;background:var(--line);min-width:16px}
.ld-pricing{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:var(--gap)}
.ld-tier{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:24px;display:flex;flex-direction:column;gap:14px}
.ld-tier.hl{border-color:var(--primary);box-shadow:0 0 0 3px var(--info-bg)}
.ld-tier .n{font-weight:700}.ld-tier .p{font-size:34px;font-weight:700;letter-spacing:-.03em}.ld-tier .p small{font-size:var(--fs-sm);color:var(--muted);font-weight:500}
.ld-tier ul{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:8px;font-size:var(--fs-sm);flex:1}
.ld-tier li::before{content:"✓";color:var(--ok);margin-right:8px;font-weight:700}
.ld-hero{display:grid;grid-template-columns:1fr 1fr;gap:40px;align-items:center;padding:40px 0}
.ld-hero.center{grid-template-columns:1fr;text-align:center;max-width:720px;margin:0 auto}
.ld-hero h1{font-size:var(--fs-hero);line-height:1.08;letter-spacing:-.03em;margin:0 0 16px;font-weight:800}
.ld-hero p{font-size:var(--fs-lg);color:var(--muted);margin:0 0 24px}
.ld-hero .ld-actions{justify-content:inherit}.ld-hero.center .ld-actions{justify-content:center}
.ld-img{background:linear-gradient(135deg,var(--chip),var(--line));border-radius:var(--r);display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:var(--fs-sm);font-weight:500;position:relative;overflow:hidden}
.ld-img::after{content:"";position:absolute;inset:0;background:radial-gradient(circle at 30% 30%,rgba(255,255,255,.5),transparent 60%)}
.ld-feat{display:grid;gap:var(--gap)}
.ld-feat .f{display:flex;flex-direction:column;gap:8px}
.ld-feat .f .ic{width:40px;height:40px;border-radius:var(--r-sm);background:var(--info-bg);color:var(--primary);display:flex;align-items:center;justify-content:center;font-size:18px}
.ld-feat .f h4{margin:0;font-size:var(--fs-h3)}.ld-feat .f p{margin:0;color:var(--muted);font-size:var(--fs-sm)}
.ld-tl{display:flex;flex-direction:column;gap:0}
.ld-tl .e{display:grid;grid-template-columns:80px 20px 1fr;gap:10px;padding-bottom:18px}
.ld-tl .e .tm{color:var(--muted);font-size:var(--fs-sm);text-align:right;padding-top:2px}
.ld-tl .e .dot{width:10px;height:10px;border-radius:50%;background:var(--primary);margin:5px auto;position:relative}
.ld-tl .e .dot::after{content:"";position:absolute;top:12px;left:4px;width:2px;height:40px;background:var(--line)}
.ld-tl .e:last-child .dot::after{display:none}
.ld-tl .e .tt{font-weight:600}.ld-tl .e .tx{color:var(--muted);font-size:var(--fs-sm)}
.ld-chat{display:flex;flex-direction:column;gap:10px}
.ld-chat .msg{max-width:72%;padding:10px 14px;border-radius:16px;background:var(--chip);font-size:var(--fs)}
.ld-chat .msg.me{align-self:flex-end;background:var(--primary);color:#fff;border-bottom-right-radius:4px}
.ld-chat .msg.them,.ld-chat .msg.bot{align-self:flex-start;border-bottom-left-radius:4px}
.ld-chat .in{display:flex;gap:8px;margin-top:6px}.ld-chat .in input{flex:1;padding:10px 14px;border-radius:999px;border:1px solid var(--line);background:var(--surface);font:inherit;color:var(--text)}
.ld-kv{display:grid;grid-template-columns:auto 1fr;gap:8px 20px;font-size:var(--fs-sm)}
.ld-kv .k{color:var(--muted)}.ld-kv .v{font-weight:500}
.ld-set .it{display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid var(--line)}
.ld-set .it:last-child{border-bottom:0}.ld-set .t{font-weight:600}.ld-set .s{color:var(--muted);font-size:var(--fs-sm)}
.ld-tg{margin-left:auto;width:40px;height:24px;border-radius:999px;background:var(--line);position:relative;flex:none}
.ld-tg::after{content:"";position:absolute;top:3px;left:3px;width:18px;height:18px;border-radius:50%;background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.2)}
.ld-tg.on{background:var(--primary)}.ld-tg.on::after{left:19px}
.ld-prog .l{display:flex;justify-content:space-between;font-size:var(--fs-sm);margin-bottom:6px}.ld-prog .l b{font-weight:600}
.ld-prog .bar{height:8px;border-radius:999px;background:var(--line);overflow:hidden}.ld-prog .bar i{display:block;height:100%;background:var(--primary)}
.ld-prog .s{color:var(--muted);font-size:12px;margin-top:4px}
.ld-alert{padding:12px 14px;border-radius:var(--r-sm);font-size:var(--fs-sm);font-weight:500;border:1px solid}
.ld-alert.info{background:var(--info-bg);border-color:var(--primary);color:var(--primary)}
.ld-alert.success{background:var(--ok-bg);border-color:var(--ok);color:var(--ok)}
.ld-alert.warning{background:var(--warn-bg);border-color:var(--warn);color:var(--warn)}
.ld-alert.error{background:var(--bad-bg);border-color:var(--bad);color:var(--bad)}
.ld-search{display:flex;align-items:center;gap:10px;padding:10px 14px;border:1px solid var(--line);border-radius:999px;background:var(--surface);color:var(--muted)}
.ld-crumbs{display:flex;gap:8px;font-size:var(--fs-sm);color:var(--muted)}.ld-crumbs span:last-child{color:var(--text);font-weight:500}
.ld-avs{display:flex;align-items:center}.ld-avs .ld-av{margin-left:-8px;border:2px solid var(--surface)}.ld-avs .ld-av:first-child{margin:0}.ld-avs .lbl{margin-left:12px;color:var(--muted);font-size:var(--fs-sm)}
.ld-cal{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;text-align:center;font-size:var(--fs-sm)}
.ld-cal .h{color:var(--muted);font-size:11px;font-weight:600;padding:4px 0}.ld-cal .d{padding:8px 0;border-radius:var(--r-sm)}.ld-cal .d.hl{background:var(--primary);color:#fff;font-weight:600}.ld-cal .d.pad{color:transparent}
.ld-tabbar{position:fixed;left:0;right:0;bottom:0;display:flex;background:var(--surface);border-top:1px solid var(--line);padding:8px 0 14px}
.ld-tabbar a{flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;font-size:11px;color:var(--muted);font-weight:500}
.ld-tabbar a .i{font-size:20px}.ld-tabbar a.on{color:var(--primary)}
.ld-div{height:1px;background:var(--line)}
.ld-foot{display:flex;justify-content:space-between;gap:16px;padding-top:24px;border-top:1px solid var(--line);color:var(--muted);font-size:var(--fs-sm);margin-top:auto}
.ld-foot nav{display:flex;gap:16px}
"""


def _tokens_css(t: dict, ds: dict | None = None) -> str:
    """CSS variables from spec tokens (+ design-system overrides)."""
    t = {**(t or {})}
    if ds and ds.get("tokens"):
        t = {**t, **{k: v for k, v in ds["tokens"].items() if v}}
    dark = str(t.get("theme", "light")).lower() == "dark"
    primary = _color(t.get("primary"), "#2563eb")
    accent = _color(t.get("accent"), primary)
    radius = int(t.get("radius", 12) or 12)
    compact = str(t.get("density", "normal")) == "compact"
    font = t.get("font") or "-apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', system-ui, sans-serif"
    if dark:
        pal = dict(bg=_color(t.get("bg"), "#0f1115"), surface=_color(t.get("surface"), "#171a21"), text=_color(t.get("text"), "#e8eaf0"), muted="#8b93a7", line="#262b36", chip="#222733",
                   side_bg="#0b0d12", side_text="#e8eaf0", side_muted="#8b93a7", side_active="#1b2030",
                   ok="#3ddc84", ok_bg="rgba(61,220,132,.14)", bad="#ff6b6b", bad_bg="rgba(255,107,107,.14)", warn="#ffb020", warn_bg="rgba(255,176,32,.16)", info_bg="rgba(99,140,255,.18)")
    else:
        pal = dict(bg=_color(t.get("bg"), "#f6f7f9"), surface=_color(t.get("surface"), "#ffffff"), text=_color(t.get("text"), "#121417"), muted="#6b7280", line="#e5e7eb", chip="#f1f3f6",
                   side_bg="#ffffff", side_text="#121417", side_muted="#6b7280", side_active="#eef2ff",
                   ok="#15803d", ok_bg="#dcfce7", bad="#b91c1c", bad_bg="#fee2e2", warn="#b45309", warn_bg="#fef3c7", info_bg="#e0e7ff")
    for k in ("muted", "line", "chip", "ok", "bad", "warn"):
        if t.get(k):
            pal[k] = _color(t[k], pal[k])
    fs = 13 if compact else 14
    return f""":root{{--primary:{primary};--accent:{accent};--bg:{pal['bg']};--surface:{pal['surface']};--text:{pal['text']};--muted:{pal['muted']};--line:{pal['line']};--chip:{pal['chip']};
--side-bg:{pal['side_bg']};--side-text:{pal['side_text']};--side-muted:{pal['side_muted']};--side-active:{pal['side_active']};
--ok:{pal['ok']};--ok-bg:{pal['ok_bg']};--bad:{pal['bad']};--bad-bg:{pal['bad_bg']};--warn:{pal['warn']};--warn-bg:{pal['warn_bg']};--info-bg:{pal['info_bg']};
--font:{font};--fs:{fs}px;--fs-sm:{fs - 1}px;--fs-lg:{fs + 3}px;--fs-h1:{22 if compact else 26}px;--fs-h3:{fs + 1}px;--fs-stat:{24 if compact else 30}px;--fs-hero:{40 if compact else 52}px;
--r:{radius}px;--r-sm:{max(4, radius - 4)}px;--pad:{20 if compact else 32}px;--gap:{14 if compact else 20}px;--card-pad:{14 if compact else 20}px}}"""


_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_NAMED = {"blue": "#2563eb", "green": "#16a34a", "red": "#dc2626", "purple": "#7c3aed", "orange": "#ea580c", "teal": "#0d9488", "pink": "#db2777", "indigo": "#4f46e5", "black": "#111111", "navy": "#1e3a8a", "emerald": "#059669", "amber": "#d97706", "slate": "#475569", "violet": "#8b5cf6", "cyan": "#0891b2", "rose": "#e11d48", "lime": "#65a30d", "yellow": "#ca8a04", "brown": "#92400e", "gray": "#6b7280", "grey": "#6b7280", "white": "#ffffff"}


def _color(v, default: str) -> str:
    if not v or not isinstance(v, str):
        return default
    v = v.strip()
    if _HEX.match(v) or v.startswith(("rgb", "hsl")):
        return v
    return _NAMED.get(v.lower(), default)


# --------------------------------------------------------------------------- helpers
def e(x) -> str:
    return _html.escape("" if x is None else str(x), quote=True)


def _link_attr(n: dict) -> str:
    l = n.get("link")
    return f' data-link="{e(l)}"' if l else ""


def _btns(items, cls="") -> str:
    out = []
    for b in items or []:
        if isinstance(b, str):
            b = {"label": b}
        out.append(f'<a class="ld-btn {"primary" if b.get("primary") else ""} {cls}"{_link_attr(b)}>{e(b.get("label", "Button"))}</a>')
    return "".join(out)


def _badge(text) -> str:
    t = str(text or "")
    low = t.lower()
    kind = "ok" if any(w in low for w in ("online", "active", "ok", "paid", "done", "complete", "healthy", "success", "approved", "live", "good", "on track")) else \
        "bad" if any(w in low for w in ("critical", "error", "fail", "offline", "overdue", "blocked", "rejected", "down", "urgent")) else \
        "warn" if any(w in low for w in ("warn", "degrad", "pending", "review", "late", "medium", "risk", "due")) else \
        "info" if any(w in low for w in ("new", "info", "beta", "draft", "open", "in progress", "scheduled")) else ""
    return f'<span class="ld-badge {kind}">{e(t)}</span>'


def _initials(name) -> str:
    parts = str(name or "?").split()
    return "".join(p[0] for p in parts[:2]).upper() or "?"


def _nums(vals) -> list[float]:
    out = []
    for v in vals or []:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(0.0)
    return out


PALETTE = ["var(--primary)", "var(--accent)", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6"]


def _chart_svg(n: dict) -> str:
    kind = str(n.get("kind", "line"))
    series = [s for s in (n.get("series") or []) if isinstance(s, dict)]
    if not series and n.get("values"):
        series = [{"name": n.get("name", ""), "values": n["values"]}]
    labels = [str(l) for l in (n.get("labels") or [])]
    H = int(n.get("height") or 220)
    W = 600
    if kind == "donut":
        vals = _nums([s.get("values", [0])[0] if isinstance(s.get("values"), list) and s["values"] else s.get("value", 0) for s in series]) or [1]
        total = sum(vals) or 1
        r, cx, cy, sw = 70, 110, 110, 26
        circ = 2 * math.pi * r
        parts, off = [], 0.0
        for i, v in enumerate(vals):
            frac = v / total
            parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{PALETTE[i % len(PALETTE)]}" stroke-width="{sw}" stroke-dasharray="{circ * frac:.1f} {circ:.1f}" stroke-dashoffset="{-off:.1f}" transform="rotate(-90 {cx} {cy})"/>')
            off += circ * frac
        legend = "".join(f'<span><i style="background:{PALETTE[i % len(PALETTE)]}"></i>{e(s.get("name", ""))} {e(vals[i] if i < len(vals) else "")}</span>' for i, s in enumerate(series))
        return f'<div class="ld-chart" style="display:flex;gap:24px;align-items:center"><svg viewBox="0 0 220 220" style="max-width:220px">{"".join(parts)}<text x="{cx}" y="{cy + 6}" text-anchor="middle" font-size="22" font-weight="700" fill="var(--text)">{e(n.get("center", int(total)))}</text></svg><div class="ld-legend" style="flex-direction:column;gap:8px">{legend}</div></div>'
    allv = [v for s in series for v in _nums(s.get("values"))] or [0, 1]
    lo, hi = min(0.0, min(allv)), max(allv) or 1.0
    pad_l, pad_r, pad_t, pad_b = 36, 10, 10, 26
    iw, ih = W - pad_l - pad_r, H - pad_t - pad_b
    npts = max(len(_nums(s.get("values"))) for s in series) if series else 2
    gx = lambda i: pad_l + (i / max(1, npts - 1)) * iw
    gy = lambda v: pad_t + ih - ((v - lo) / (hi - lo or 1)) * ih
    out = []
    for g in range(5):
        y = pad_t + ih * g / 4
        val = hi - (hi - lo) * g / 4
        out.append(f'<line x1="{pad_l}" x2="{W - pad_r}" y1="{y:.1f}" y2="{y:.1f}" stroke="var(--line)"/><text x="{pad_l - 6}" y="{y + 4:.1f}" text-anchor="end" font-size="10" fill="var(--muted)">{val:g}</text>')
    if kind == "bar":
        nser = max(1, len(series))
        slot = iw / max(1, npts)
        bw = slot * 0.7 / nser
        for si, s in enumerate(series):
            for i, v in enumerate(_nums(s.get("values"))):
                x = pad_l + i * slot + slot * 0.15 + si * bw
                out.append(f'<rect x="{x:.1f}" y="{gy(v):.1f}" width="{bw:.1f}" height="{pad_t + ih - gy(v):.1f}" rx="3" fill="{PALETTE[si % len(PALETTE)]}"/>')
        for i, l in enumerate(labels[:npts]):
            out.append(f'<text x="{pad_l + i * slot + slot / 2:.1f}" y="{H - 8}" text-anchor="middle" font-size="10" fill="var(--muted)">{e(l)}</text>')
    else:
        for si, s in enumerate(series):
            vals = _nums(s.get("values"))
            pts = " ".join(f"{gx(i):.1f},{gy(v):.1f}" for i, v in enumerate(vals))
            col = PALETTE[si % len(PALETTE)]
            if kind == "area" and vals:
                out.append(f'<polygon points="{gx(0):.1f},{pad_t + ih} {pts} {gx(len(vals) - 1):.1f},{pad_t + ih}" fill="{col}" opacity="0.12"/>')
            out.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>')
            for i, v in enumerate(vals):
                out.append(f'<circle cx="{gx(i):.1f}" cy="{gy(v):.1f}" r="3" fill="{col}"/>')
        for i, l in enumerate(labels[:npts]):
            out.append(f'<text x="{gx(i):.1f}" y="{H - 8}" text-anchor="middle" font-size="10" fill="var(--muted)">{e(l)}</text>')
    legend = "".join(f'<span><i style="background:{PALETTE[i % len(PALETTE)]}"></i>{e(s.get("name", ""))}</span>' for i, s in enumerate(series) if s.get("name"))
    return f'<div class="ld-chart"><svg viewBox="0 0 {W} {H}">{"".join(out)}</svg>{f"<div class=ld-legend>{legend}</div>" if legend else ""}</div>'


# --------------------------------------------------------------------------- node renderers
def render_node(n, ctx: dict) -> str:
    if not isinstance(n, dict):
        return ""
    t = str(n.get("type", "")).lower().replace("_", "-")
    fn = NODES.get(t)
    if not fn:
        # unknown node: show as text so nothing is silently lost
        txt = n.get("text") or n.get("title") or n.get("label")
        return f'<p class="ld-text">{e(txt)}</p>' if txt else ""
    try:
        return fn(n, ctx)
    except Exception as ex:  # one bad node must not kill the page
        return f'<div class="ld-alert error">{e(t)}: {e(ex)}</div>'


def _children(n, ctx, key="children"):
    return "".join(render_node(c, ctx) for c in (n.get(key) or []))


def r_heading(n, ctx):
    sub = f'<p>{e(n["sub"])}</p>' if n.get("sub") else ""
    return f'<div class="ld-head"><div><h1>{e(n.get("text"))}</h1>{sub}</div><div class="ld-actions">{_btns(n.get("actions"))}</div></div>'


def r_stats(n, ctx):
    items = []
    for it in n.get("items") or []:
        if isinstance(it, str):
            it = {"value": it}
        trend = it.get("trend", "")
        d = f'<div class="d {e(trend)}">{"▲ " if trend == "up" else "▼ " if trend == "down" else ""}{e(it.get("delta"))}</div>' if it.get("delta") else ""
        items.append(f'<div class="ld-stat"><div class="l">{e(it.get("label"))}</div><div class="v">{e(it.get("value"))}</div>{d}</div>')
    return f'<div class="ld-stats">{"".join(items)}</div>'


def r_grid(n, ctx):
    cols = int(n.get("cols") or 3)
    return f'<div class="ld-grid" style="grid-template-columns:repeat({cols},minmax(0,1fr))">{_children(n, ctx)}</div>'


def r_split(n, ctx):
    ratio = str(n.get("ratio") or "1:1").split(":")
    try:
        a, b = int(ratio[0]), int(ratio[1])
    except (ValueError, IndexError):
        a, b = 1, 1
    return f'<div class="ld-grid" style="grid-template-columns:{a}fr {b}fr">{_children(n, ctx)}</div>'


def r_card(n, ctx):
    head = f'<h3>{e(n["title"])}</h3>' if n.get("title") else ""
    sub = f'<p class="sub">{e(n["sub"])}</p>' if n.get("sub") else ""
    body = f'<div class="body">{e(n["body"])}</div>' if n.get("body") else ""
    acts = f'<div class="ld-actions">{_btns(n.get("actions"))}</div>' if n.get("actions") else ""
    return f'<div class="ld-card">{head}{sub}{body}{_children(n, ctx)}{acts}</div>'


def r_text(n, ctx):
    return f'<p class="ld-text {e(n.get("size", "md"))} {"muted" if n.get("muted") else ""}">{e(n.get("text"))}</p>'


def r_table(n, ctx):
    cols = [str(c) for c in (n.get("columns") or [])]
    rows = n.get("rows") or []
    src = n.get("data")
    if src and ctx.get("data", {}).get(src):
        rows_from, cols_from = _rows_from_data(ctx["data"][src], cols)
        rows, cols = rows_from, cols_from
    if not cols and rows and isinstance(rows[0], dict):
        cols = list(rows[0].keys())
    bc = n.get("badge_col")
    th = "".join(f"<th>{e(c)}</th>" for c in cols)
    trs = []
    for r in rows[:50]:
        cells = [r.get(c, "") for c in cols] if isinstance(r, dict) else list(r)
        tds = "".join(f"<td>{_badge(v) if bc is not None and i == int(bc) else e(v)}</td>" for i, v in enumerate(cells))
        trs.append(f"<tr>{tds}</tr>")
    title = f'<h3>{e(n["title"])}</h3>' if n.get("title") else ""
    return f'<div class="ld-card">{title}<table class="ld-table"><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table></div>'


def _rows_from_data(data, cols):
    """data: list[dict] | list[list] | {rows:[...]}  → (rows, columns)"""
    if isinstance(data, dict):
        data = data.get("rows") or data.get("data") or data.get("items") or []
    if not isinstance(data, list) or not data:
        return [], cols
    if isinstance(data[0], dict):
        keys = list(data[0].keys())
        norm = lambda x: re.sub(r"[^a-z0-9]", "", str(x).lower())
        if cols:
            # map each spec column to a data key by normalized name; if fewer than half match, use the data's own keys
            mapping = {c: next((k for k in keys if norm(k) == norm(c)), None) for c in cols}
            if sum(1 for v in mapping.values() if v) < max(1, len(cols) // 2):
                cols, mapping = keys, {k: k for k in keys}
        else:
            cols, mapping = keys, {k: k for k in keys}
        return [[row.get(mapping.get(c) or c, "") for c in cols] for row in data], cols
    return [list(r) for r in data], cols


def r_list(n, ctx):
    items = []
    src = n.get("data")
    data_items = n.get("items") or []
    if src and ctx.get("data", {}).get(src):
        rows, cols = _rows_from_data(ctx["data"][src], [])
        data_items = [{"title": r[0] if r else "", "sub": ", ".join(str(x) for x in r[1:3]), "meta": r[3] if len(r) > 3 else ""} for r in rows[:20]]
    for it in data_items:
        if isinstance(it, str):
            it = {"title": it}
        ic = f'<div class="ic">{e(it.get("icon"))}</div>' if it.get("icon") else ""
        meta = []
        if it.get("badge"):
            meta.append(_badge(it["badge"]))
        if it.get("meta"):
            meta.append(e(it["meta"]))
        sub = f'<div class="s">{e(it["sub"])}</div>' if it.get("sub") else ""
        items.append(f'<div class="it"{_link_attr(it)}>{ic}<div><div class="t">{e(it.get("title"))}</div>{sub}</div><div class="m">{"".join(meta)}</div></div>')
    title = f'<h3>{e(n["title"])}</h3>' if n.get("title") else ""
    return f'<div class="ld-card">{title}<div class="ld-list">{"".join(items)}</div></div>'


def r_chart(n, ctx):
    title = f'<h3>{e(n["title"])}</h3>' if n.get("title") else ""
    return f'<div class="ld-card">{title}{_chart_svg(n)}</div>'


def r_form(n, ctx):
    fields = []
    for f in n.get("fields") or []:
        if isinstance(f, str):
            f = {"label": f}
        ft = str(f.get("type") or "text")
        lab, ph, val = e(f.get("label")), e(f.get("placeholder")), e(f.get("value"))
        if ft in ("checkbox", "toggle"):
            ctl = f'<span class="ld-tg {"on" if f.get("value") or f.get("on") else ""}"></span>' if ft == "toggle" else f'<input type="checkbox" {"checked" if f.get("value") else ""}>'
            fields.append(f'<div class="ld-field check">{ctl}<label>{lab}</label></div>')
            continue
        if ft == "select":
            opts = "".join(f"<option>{e(o)}</option>" for o in (f.get("options") or ["Option A", "Option B"]))
            ctl = f"<select>{opts}</select>"
        elif ft == "textarea":
            ctl = f'<textarea placeholder="{ph}">{val}</textarea>'
        else:
            ctl = f'<input type="{e(ft)}" placeholder="{ph}" value="{val}">'
        fields.append(f'<div class="ld-field"><label>{lab}</label>{ctl}</div>')
    acts = []
    if n.get("secondary"):
        acts.append({"label": n["secondary"]})
    if n.get("submit", True):
        acts.append({"label": n.get("submit") if isinstance(n.get("submit"), str) else "Submit", "primary": True, "link": n.get("link")})
    title = f'<h3>{e(n["title"])}</h3>' if n.get("title") else ""
    return f'<div class="ld-card"><form class="ld-form" onsubmit="return false">{title}{"".join(fields)}<div class="ld-actions">{_btns(acts)}</div></form></div>'


def r_buttons(n, ctx):
    al = {"right": "flex-end", "center": "center"}.get(str(n.get("align", "left")), "flex-start")
    return f'<div class="ld-actions" style="justify-content:{al}">{_btns(n.get("items"))}</div>'


def r_tabs(n, ctx):
    act = n.get("active")
    return '<div class="ld-tabs">' + "".join(f'<a class="{"on" if (t == act or (act is None and i == 0)) else ""}">{e(t)}</a>' for i, t in enumerate(n.get("items") or [])) + "</div>"


def r_chips(n, ctx):
    act = n.get("active")
    return '<div class="ld-chips">' + "".join(f'<a class="{"on" if t == act else ""}">{e(t)}</a>' for t in (n.get("items") or [])) + "</div>"


def r_steps(n, ctx):
    try:
        act = int(n.get("active", 0))
    except (TypeError, ValueError):
        act = 0
    parts = []
    items = n.get("items") or []
    for i, s in enumerate(items):
        cls = "on" if i == act else "done" if i < act else ""
        parts.append(f'<div class="st {cls}"><i>{"✓" if i < act else i + 1}</i>{e(s)}</div>')
        if i < len(items) - 1:
            parts.append('<div class="ln"></div>')
    return f'<div class="ld-steps">{"".join(parts)}</div>'


def r_pricing(n, ctx):
    tiers = []
    for t in n.get("tiers") or []:
        feats = "".join(f"<li>{e(f)}</li>" for f in (t.get("features") or []))
        tag = f'<p style="margin:0;color:var(--muted);font-size:var(--fs-sm)">{e(t["tagline"])}</p>' if t.get("tagline") else ""
        tiers.append(f'<div class="ld-tier {"hl" if t.get("highlight") else ""}"><div class="n">{e(t.get("name"))}</div><div class="p">{e(t.get("price"))}<small> {e(t.get("period", ""))}</small></div>{tag}<ul>{feats}</ul>{_btns([{"label": t.get("cta", "Choose"), "primary": bool(t.get("highlight")), "link": t.get("link")}])}</div>')
    return f'<div class="ld-pricing">{"".join(tiers)}</div>'


def r_hero(n, ctx):
    acts = []
    if n.get("cta"):
        acts.append({"label": n["cta"], "primary": True, "link": n.get("link")})
    if n.get("secondary"):
        acts.append({"label": n["secondary"]})
    center = str(n.get("align", "left")) == "center" or not n.get("image", True)
    img = '' if center else (f'<img src="{e(n["image_src"])}" alt="" style="width:100%;height:320px;object-fit:cover;border-radius:var(--r)">' if n.get("image_src") else f'<div class="ld-img" style="height:320px">{e(n.get("image_label", "Product visual"))}</div>')
    return f'<section class="ld-hero {"center" if center else ""}"><div><h1>{e(n.get("title"))}</h1><p>{e(n.get("sub"))}</p><div class="ld-actions">{_btns(acts)}</div></div>{img}</section>'


def r_features(n, ctx):
    cols = int(n.get("cols") or 3)
    items = "".join(f'<div class="f"><div class="ic">{e(it.get("icon", "✦"))}</div><h4>{e(it.get("title"))}</h4><p>{e(it.get("text"))}</p></div>' for it in (n.get("items") or []) if isinstance(it, dict))
    return f'<div class="ld-feat" style="grid-template-columns:repeat({cols},minmax(0,1fr))">{items}</div>'


def r_image(n, ctx):
    h = n.get("height")
    ratio = str(n.get("ratio") or "16:9").replace(":", "/")
    style = f"height:{int(h)}px" if h else f"aspect-ratio:{ratio}"
    if n.get("src"):
        return f'<img src="{e(n["src"])}" alt="{e(n.get("label", ""))}" style="display:block;width:100%;{style};object-fit:cover;border-radius:var(--r)">'
    return f'<div class="ld-img" style="{style}">{e(n.get("label", "Image"))}</div>'


def r_timeline(n, ctx):
    items = "".join(f'<div class="e"><div class="tm">{e(it.get("time"))}</div><div class="dot"></div><div><div class="tt">{e(it.get("title"))}</div><div class="tx">{e(it.get("text"))}</div></div></div>' for it in (n.get("items") or []) if isinstance(it, dict))
    return f'<div class="ld-card"><div class="ld-tl">{items}</div></div>'


def r_chat(n, ctx):
    msgs = "".join(f'<div class="msg {e(m.get("from", "them"))}">{e(m.get("text"))}</div>' for m in (n.get("messages") or []) if isinstance(m, dict))
    return f'<div class="ld-card"><div class="ld-chat">{msgs}<div class="in"><input placeholder="{e(n.get("placeholder", "Message…"))}"><a class="ld-btn primary">Send</a></div></div></div>'


def r_kv(n, ctx):
    items = "".join(f'<div class="k">{e(it.get("k"))}</div><div class="v">{e(it.get("v"))}</div>' for it in (n.get("items") or []) if isinstance(it, dict))
    title = f'<h3>{e(n["title"])}</h3>' if n.get("title") else ""
    return f'<div class="ld-card">{title}<div class="ld-kv">{items}</div></div>'


def r_settings(n, ctx):
    items = "".join(f'<div class="it"><div><div class="t">{e(it.get("label"))}</div><div class="s">{e(it.get("sub"))}</div></div><span class="ld-tg {"on" if it.get("on") else ""}"></span></div>' for it in (n.get("items") or []) if isinstance(it, dict))
    title = f'<h3>{e(n["title"])}</h3>' if n.get("title") else ""
    return f'<div class="ld-card ld-set">{title}<div>{items}</div></div>'


def r_progress(n, ctx):
    try:
        v = max(0, min(100, float(n.get("value", 0))))
    except (TypeError, ValueError):
        v = 0
    sub = f'<div class="s">{e(n["sub"])}</div>' if n.get("sub") else ""
    return f'<div class="ld-card ld-prog"><div class="l"><b>{e(n.get("label"))}</b><span>{v:g}%</span></div><div class="bar"><i style="width:{v}%"></i></div>{sub}</div>'


def r_alert(n, ctx):
    return f'<div class="ld-alert {e(n.get("kind", "info"))}">{e(n.get("text"))}</div>'


def r_search(n, ctx):
    return f'<div class="ld-search">🔍 <span>{e(n.get("placeholder", "Search…"))}</span></div>'


def r_breadcrumbs(n, ctx):
    return '<div class="ld-crumbs">' + " <span>/</span> ".join(f"<span>{e(i)}</span>" for i in (n.get("items") or [])) + "</div>"


def r_avatars(n, ctx):
    avs = "".join(f'<span class="ld-av">{e(_initials(x))}</span>' for x in (n.get("items") or [])[:6])
    lbl = f'<span class="lbl">{e(n["label"])}</span>' if n.get("label") else ""
    return f'<div class="ld-avs">{avs}{lbl}</div>'


def r_calendar(n, ctx):
    hl = set(int(d) for d in (n.get("highlight") or []) if str(d).isdigit())
    cells = "".join(f'<div class="h">{d}</div>' for d in ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"))
    cells += "".join('<div class="d pad">0</div>' for _ in range(int(n.get("offset", 2))))
    cells += "".join(f'<div class="d {"hl" if d in hl else ""}">{d}</div>' for d in range(1, 31))
    return f'<div class="ld-card"><h3>{e(n.get("month", "This month"))}</h3><div class="ld-cal">{cells}</div></div>'


def r_tabbar(n, ctx):
    act = n.get("active")
    items = []
    for i, it in enumerate(n.get("items") or []):
        if isinstance(it, str):
            it = {"label": it}
        on = it.get("label") == act or (act is None and i == 0)
        items.append(f'<a class="{"on" if on else ""}"{_link_attr(it)}><span class="i">{e(it.get("icon", "•"))}</span>{e(it.get("label"))}</a>')
    return f'<nav class="ld-tabbar">{"".join(items)}</nav>'


def r_divider(n, ctx):
    return '<div class="ld-div"></div>'


def r_footer(n, ctx):
    links = "".join(f"<a>{e(l)}</a>" for l in (n.get("links") or []))
    return f'<footer class="ld-foot"><span>{e(n.get("text"))}</span><nav>{links}</nav></footer>'


NODES = {
    "heading": r_heading, "stats": r_stats, "grid": r_grid, "split": r_split, "card": r_card, "text": r_text, "table": r_table,
    "list": r_list, "chart": r_chart, "form": r_form, "buttons": r_buttons, "tabs": r_tabs, "chips": r_chips, "steps": r_steps,
    "pricing": r_pricing, "hero": r_hero, "features": r_features, "image": r_image, "timeline": r_timeline, "chat": r_chat,
    "kv": r_kv, "settings": r_settings, "progress": r_progress, "alert": r_alert, "search": r_search, "breadcrumbs": r_breadcrumbs,
    "avatars": r_avatars, "calendar": r_calendar, "tabbar": r_tabbar, "divider": r_divider, "footer": r_footer,
    # aliases small models like to use
    "header": r_heading, "title": r_heading, "kpis": r_stats, "metrics": r_stats, "cards": r_grid, "row": r_split, "columns": r_grid,
    "paragraph": r_text, "button": r_buttons, "cta": r_buttons, "graph": r_chart, "input": r_form, "fields": r_form, "nav-tabs": r_tabs,
    "stepper": r_steps, "plans": r_pricing, "banner": r_hero, "feature-grid": r_features, "placeholder": r_image, "messages": r_chat,
    "details": r_kv, "toggles": r_settings, "notice": r_alert, "searchbar": r_search, "bottom-nav": r_tabbar, "separator": r_divider,
}


# --------------------------------------------------------------------------- page
def render(spec: dict, width: int = 1280, ds: dict | None = None, data: dict | None = None) -> str:
    spec = spec if isinstance(spec, dict) else {}
    layout = str(spec.get("layout") or ("mobile" if width <= 480 else "sidebar")).lower()
    if layout not in ("sidebar", "topnav", "plain", "centered", "mobile"):
        layout = "plain"
    if width <= 480:
        layout = "mobile"           # any desktop layout collapses to the phone layout at phone width
    nav = spec.get("nav") or {}
    ctx = {"data": data or {}, "width": width}
    sections = _children(spec, ctx, "sections")
    user = nav.get("user")
    user_html = f'<div class="ld-user"><span class="ld-av">{e(_initials(user))}</span><span>{e(user)}</span></div>' if user else ""
    items = nav.get("items") or []
    active = nav.get("active")
    links = "".join(f'<a class="{"on" if (it == active or (active is None and i == 0)) else ""}" data-link="{e(it)}">{e(it)}</a>' for i, it in enumerate(items))
    mark = f'<img src="{e(nav["logo"])}" alt="" style="height:28px;width:auto;max-width:140px">' if nav.get("logo") else '<span class="mark"></span>'
    brand = f'<div class="ld-brand">{mark}{e(nav.get("brand") or spec.get("title") or "App")}</div>'
    if layout == "sidebar":
        shell = f'<aside class="ld-side">{brand}{links}<div class="spacer"></div>{user_html}</aside><main class="ld-main">{sections}</main>'
    elif layout == "topnav":
        shell = f'<div><header class="ld-top">{brand}<nav>{links}</nav>{user_html}</header><main class="ld-main">{sections}</main></div>'
    elif layout == "mobile":
        top = f'<header class="ld-top" style="height:52px;padding:0 16px">{brand}{user_html}</header>' if nav else ""
        shell = f'<div>{top}<main class="ld-main">{sections}</main></div>'
    else:
        top = f'<header class="ld-top">{brand}<nav>{links}</nav>{user_html}</header>' if nav else ""
        shell = f'<div>{top}<main class="ld-main">{sections}</main></div>'
    extra_css = (ds or {}).get("css") or ""
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{e(spec.get("title") or "Screen")}</title><style>{_tokens_css(spec.get("tokens"), ds)}{BASE_CSS}{extra_css}</style></head>'
            f'<body><div class="ld-app {layout}">{shell}</div></body></html>')


# --------------------------------------------------------------------------- JSON extraction / repair
_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def extract_json(text: str):
    """Parse the model's reply as a spec: tolerates fences, chatter, and truncation."""
    m = _FENCE.search(text)
    if m:
        text = m.group(1)
    i = text.find("{")
    if i < 0:
        raise ValueError("no JSON object in reply")
    text = text[i:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    j = text.rfind("}")
    if j > 0:
        try:
            return json.loads(text[: j + 1])
        except json.JSONDecodeError:
            pass
    return json.loads(repair_json(text))


def repair_json(text: str) -> str:
    """Close an unfinished JSON document so it parses (used for live preview + truncated replies)."""
    i = text.find("{")
    if i < 0:
        return "{}"
    text = text[i:]
    out, stack, in_str, esc = [], [], False, False
    for ch in text:
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack:
                stack.pop()
        out.append(ch)
    s = "".join(out)
    if in_str:
        s += '"'
    s = s.rstrip()
    # dangling key or separator
    if s.endswith(":"):
        s += "null"
    elif s.endswith(","):
        s = s[:-1]
    elif stack and stack[-1] == "}":
        # inside an object, a closed string right after '{' or ',' is a key with no value
        m = re.search(r'[{,]\s*"(?:[^"\\]|\\.)*"\s*$', s)
        if m:
            s += ":null"
    # drop a trailing partial literal (e.g. `tru`, `12.`)
    s = re.sub(r'[:,]\s*[A-Za-z0-9.+-]*$', lambda mm: mm.group(0)[0] + "null" if mm.group(0)[0] == ":" else "", s)
    s += "".join(reversed(stack))
    return s


# --------------------------------------------------------------------------- component library (drag-and-drop palette)
SAMPLES: dict[str, dict] = {
    "heading": {"type": "heading", "text": "Section title", "sub": "Supporting line of context", "actions": [{"label": "Secondary"}, {"label": "Primary", "primary": True}]},
    "stats": {"type": "stats", "items": [{"label": "Revenue", "value": "$18.4k", "delta": "+12%", "trend": "up"}, {"label": "Active", "value": "1,284"}, {"label": "Churn", "value": "2.1%", "delta": "-0.3", "trend": "down"}]},
    "card": {"type": "card", "title": "Card title", "sub": "Subtitle", "body": "Body copy goes here. Short, specific, useful.", "actions": [{"label": "Action", "primary": True}]},
    "table": {"type": "table", "title": "Table", "columns": ["Name", "Owner", "Status"], "rows": [["Alpha", "Mara", "Online"], ["Beta", "Theo", "Degraded"], ["Gamma", "Nadia", "Offline"]], "badge_col": 2},
    "list": {"type": "list", "title": "List", "items": [{"title": "First item", "sub": "Detail", "badge": "new", "icon": "★"}, {"title": "Second item", "sub": "Detail", "meta": "2h"}]},
    "chart-line": {"type": "chart", "kind": "area", "title": "Trend", "labels": ["Mon", "Tue", "Wed", "Thu", "Fri"], "series": [{"name": "This week", "values": [12, 19, 14, 24, 21]}, {"name": "Last week", "values": [10, 14, 12, 18, 17]}]},
    "chart-bar": {"type": "chart", "kind": "bar", "title": "By category", "labels": ["A", "B", "C", "D"], "series": [{"name": "Units", "values": [40, 65, 30, 52]}]},
    "chart-donut": {"type": "chart", "kind": "donut", "title": "Share", "series": [{"name": "Direct", "values": [48]}, {"name": "Organic", "values": [31]}, {"name": "Paid", "values": [21]}]},
    "form": {"type": "form", "title": "Form", "fields": [{"label": "Email", "type": "email", "placeholder": "you@company.com"}, {"label": "Plan", "type": "select", "options": ["Starter", "Team"]}, {"label": "Notify me", "type": "toggle", "on": True}], "submit": "Continue"},
    "buttons": {"type": "buttons", "items": [{"label": "Cancel"}, {"label": "Confirm", "primary": True}]},
    "tabs": {"type": "tabs", "items": ["Overview", "Activity", "Settings"], "active": "Overview"},
    "chips": {"type": "chips", "items": ["All", "Open", "Closed"], "active": "All"},
    "steps": {"type": "steps", "items": ["Plan", "Details", "Review"], "active": 1},
    "pricing": {"type": "pricing", "tiers": [{"name": "Starter", "price": "$9", "period": "/mo", "features": ["1 project", "Email support"], "cta": "Choose"}, {"name": "Team", "price": "$29", "period": "/mo", "features": ["Unlimited", "SSO", "Priority support"], "cta": "Choose", "highlight": True}]},
    "hero": {"type": "hero", "title": "Headline that sells it", "sub": "One sentence on the outcome your customer gets.", "cta": "Get started", "secondary": "See pricing", "align": "center"},
    "features": {"type": "features", "cols": 3, "items": [{"icon": "⚡", "title": "Fast", "text": "Short benefit."}, {"icon": "🔒", "title": "Private", "text": "Short benefit."}, {"icon": "🧩", "title": "Composable", "text": "Short benefit."}]},
    "image": {"type": "image", "label": "Image", "height": 180},
    "timeline": {"type": "timeline", "items": [{"time": "09:00", "title": "Kickoff", "text": "Scope agreed"}, {"time": "11:30", "title": "Review", "text": "Two changes"}]},
    "chat": {"type": "chat", "messages": [{"from": "them", "text": "Can you send the deck?"}, {"from": "me", "text": "On it — 10 min."}]},
    "kv": {"type": "kv", "title": "Details", "items": [{"k": "Owner", "v": "Mara L."}, {"k": "Created", "v": "12 Jun"}, {"k": "Status", "v": "Active"}]},
    "settings": {"type": "settings", "title": "Preferences", "items": [{"label": "Email digest", "sub": "Weekly summary", "on": True}, {"label": "Beta features", "sub": "Early access", "on": False}]},
    "progress": {"type": "progress", "label": "Storage", "value": 64, "sub": "6.4 GB of 10 GB"},
    "alert": {"type": "alert", "kind": "warning", "text": "Heads up — something needs attention."},
    "search": {"type": "search", "placeholder": "Search…"},
    "breadcrumbs": {"type": "breadcrumbs", "items": ["Home", "Projects", "Alpha"]},
    "avatars": {"type": "avatars", "items": ["Mara L", "Theo P", "Nadia O"], "label": "+4 others"},
    "calendar": {"type": "calendar", "month": "June", "highlight": [3, 12, 19]},
    "tabbar": {"type": "tabbar", "items": [{"icon": "🏠", "label": "Home"}, {"icon": "🔍", "label": "Search"}, {"icon": "👤", "label": "Me"}], "active": "Home"},
    "divider": {"type": "divider"},
    "footer": {"type": "footer", "text": "© Acme Inc.", "links": ["Privacy", "Terms", "Status"]},
    "text": {"type": "text", "text": "A paragraph of body text. Replace me."},
}

LIB_STYLE_ID = "ld-lib"


def library(ds: dict | None = None) -> dict:
    """Catalog for the drag-and-drop palette: fragments + the one stylesheet they need."""
    css = _tokens_css((ds or {}).get("tokens") or {}, ds) + BASE_CSS
    ctx = {"data": {}}
    items = [{"id": k, "name": k.replace("-", " "), "html": render_node(v, ctx)} for k, v in SAMPLES.items()]
    return {"css": css, "style_tag": f'<style data-{LIB_STYLE_ID}="1">{css}</style>', "items": items}
