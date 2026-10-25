# Changelog

## 0.3.0 — 2026-10-25

First PyPI release. `pip install localdesign` (or `uv tool install localdesign`), then `lde`.

### Implementation pack (Export ▾ → Implementation pack)
A zip an engineer or a small local model can build the product from, derived deterministically from the designs:
`ARCHITECTURE.md` (inventory, navigation graph, inferred data model, routes), `DESIGN_SYSTEM.md`, `FLOWS.md`, `DATA.md`,
`IMPLEMENTATION_PLAN.md` (ordered checklist + paste-able prompts), `AGENTS.md` (rules for the agent), **`VERIFY.md`**
(grep-able checks the agent runs against its own work: copy present verbatim, actions and fields exist, routes wired,
tokens referenced, no hard-coded colours, no CDN), per-screen docs with props, exact markup and verbatim copy,
reference HTML, `tokens.css`, `components.css`, assets, data fixtures.
Options: **per-screen PNG screenshots** (headless Chrome / Chromium / Edge if installed; `LD_CHROME` to point at one) and a
**model-written overview** at the top of `ARCHITECTURE.md` (the only part that calls the model; audit-logged).

### Library panel
30+ built-in components rendered live, your uploaded assets (logos, icons, images, fonts) and brand HTML snippets.
Drag onto any screen, or click to insert into the selected screen. Generated screens are told about your assets; exports inline them.

### Artifacts
Prompt-bar toggle: working single-file apps, calculators, charts, games, interactive documents (plain JS, no CDN). Same canvas, editor and exports.

### In-screen editor
Hover/select, inline text edit, style popover, reorder, duplicate, delete, link, element-scoped AI edits, cross-frame drag & drop, undo.

### Flows & prototype player
Journey or PRD → planned screens → generated with navigation links → arrows on the canvas → ▶ Play.

### Also
- Design-system import (CSS vars / `tailwind.config.js` / tokens JSON / HTML page) and real data sources (JSON / CSV).
- Device buttons resize the selected screen; spec screens re-render per device.
- Exports: design-spec Markdown, React (.jsx + .css, deterministic), React + Tailwind (AI), self-contained HTML, project JSON.
- Security: Origin/Host guard, audit log of every model call, no CDN unless enabled.
- 129 tests against a mock model server; CI on Linux/Windows/macOS × Python 3.10/3.12/3.13.

## 0.2.0
Spec engine for small local models, design systems, data sources, editor, flows, exports, tests and CI.

## 0.1.0
Prompt → UI mockups on a canvas, any OpenAI-compatible endpoint or Anthropic.
