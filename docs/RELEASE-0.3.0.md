# localdesign 0.3.0 — GitHub release notes

_Paste as the body of the v0.3.0 release (`gh release create v0.3.0 dist/* --title "localdesign 0.3.0" --notes-file docs/RELEASE-0.3.0.md`)._

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

### DESIGN.md
Import a DESIGN.md (Google Labs / Stitch format: front matter tokens + fixed sections, `{token}` references resolved) as a design system, and export yours as DESIGN.md. The pack ships one. `verify.sh` in the pack runs every VERIFY.md check and exits with the fail count.

### Also
- Settings → **Test**: one tiny model call proves endpoint, key and model; first run opens Settings with a 3-step hint when no model is set.
- Design system → **Fetch** from a running site URL (page + same-origin stylesheets → tokens, palette, CSS).
- Implementation pack → write into a folder (`<repo>/design`) instead of downloading.
- Spec renderer tolerates CSS-length tokens (`"radius": "10px"`).
- Design-system import (CSS vars / `tailwind.config.js` / tokens JSON / HTML page) and real data sources (JSON / CSV).
- Device buttons resize the selected screen; spec screens re-render per device.
- Exports: design-spec Markdown, React (.jsx + .css, deterministic), React + Tailwind (AI), self-contained HTML, project JSON.
- Security: Origin/Host guard, audit log of every model call, no CDN unless enabled.
- 129 tests against a mock model server; CI on Linux/Windows/macOS × Python 3.10/3.12/3.13.

```bash
uv tool install localdesign   # or pipx / pip
lde
```
