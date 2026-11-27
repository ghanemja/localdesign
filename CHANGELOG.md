# Changelog

## Unreleased

### Start from taste: ◎ Style
A new project opens by asking what it should feel like (Skip is fine; ◎ Style in the top bar any time): up to three
**directions** with live previews (Minimal, Bold, Editorial / print, Generative shader, ASCII / terminal, Motion-rich, Dark &
luminous, Soft, Dense, Brutalist, Retro, Glass) — variants A/B/C each take one; **sites you like** — read into palette, fonts
and traits (WebGL / shader, 3D, heavy motion, ASCII, glass, serif display, dark…), with your note on what you like and *Use
its colours* for the design system; **preferences** (theme, motion, density, shape, type, imagery) and notes. Every
generation, change and element edit gets the profile; the model is told never to copy a reference's content or branding.
Links to inspiration sources (Shadertoy, MotionSites, kibitz.art, ASCII Magic, Public Domain Image Archive, Godly,
SiteInspire) — nothing is copied from them.

### Effects, Shadertoy shaders, ASCII, public-domain art
- 12 original animated shader backgrounds and 4 ASCII animations (UI kits → Shader backgrounds / ASCII effects), usable by
  the model with one attribute (`data-ld-shader`, `data-ld-ascii`) and by the spec engine (`effect` node); a small runtime is
  added to pages that use them (pauses off-screen, honours reduced motion, never saved into the HTML).
- ✎ Paste a shader: single-pass Shadertoy-style shaders run as backgrounds, with live preview, compile errors, and the
  author/source/license kept with them (Shadertoy's default CC BY-NC-SA 3.0 is flagged as non-commercial).
- Library → Public domain: search the Art Institute of Chicago and Cleveland Museum of Art open-access collections; ＋ imports
  the image with its credit line and drops it on the selected screen; import any public-domain image by URL
  (e.g. from pdimagearchive.org). ⌗ on an asset turns it into ASCII art.

### UI kits: browse thousands of open-source elements, or your own
Library → **UI kits** browses element collections with live previews (hover to animate, dark-background toggle), search over
names/tags/authors, kit and category filters and infinite scroll. **+ Add kit** imports an open-source pack from GitHub once —
Uiverse Galaxy (3,373 HTML/CSS elements), SpinKit (12 spinners), three-dots (20 loaders), all MIT — or your own kit from a folder
or any GitHub repo of `.html` files. Drag an element (straight from its preview) onto a screen, or click ＋; ★ adds it to the
design system so HTML-engine screens reuse it; ⊕ in the element toolbar saves anything on a screen into *My components*.
Every element's CSS is scoped on import (per-element class on its roots, prefixed selectors, `:root/html/body` → custom
properties on the element, renamed `@keyframes`, no `@import`/scripts), so it never restyles the screen. Inserted CSS carries
an attribution comment. An unzipped copy of a known pack (air-gapped) is recognised as that pack.

### Code context: attach your existing source, reference files with @
📎 **Code** in the prompt bar (or drop a folder anywhere on the window) attaches a source folder. Type `@` in the prompt
for completion over its files and folders: `@src/pages/Settings.tsx`, `@Button`, `@src/components/`. Mentioned files, plus
**pinned** ones (style files such as `tailwind.config.*`, theme/tokens and a global stylesheet with variables are pinned on
attach), go into the prompt with a compact list of file names, for new screens, iterations, element edits, flow plans and flows.
The amount per prompt is capped by model size (Settings → *Attached code per prompt*). The status line says how many files were
sent; unknown `@names` and files that did not fit are reported. The audit log records `code_files` per call. Only text sources
are read; `node_modules`, build output, lockfiles, binaries, `.env` and key files are skipped. Stored in `~/.localdesign/code/`.

### Fixed
- Dragging a built-in Library component onto a screen restyled the whole screen (its stylesheet redefined `:root` variables and
  `body`). It is now scoped to the component, whose token defaults yield to the screen's own.
- Dragging an element from one screen to another did nothing with a real mouse and left the drag stuck (all screens unclickable
  until Esc): the source frame keeps the mouse captured, so it now forwards the pointer to the canvas.
- Selecting an element pushed the whole screen down (the element toolbar was in the layout); it now floats above the frame.
- Elements dragged between screens or saved to the library no longer carry their source width/height in px.
- ↻ Regenerating a flow screen dropped its navigation links; it now keeps planned and existing links.
- Renaming a screen broke every link to it (links are by title); renames now update `data-link`s, spec links and flow plans.
- While waiting for the model, a new screen showed the red *"No result saved (page was closed mid-generation?)"* error over the
  frame instead of a loading state. Frames now show a progress card: *Waiting for &lt;model&gt;… 12s* → *Model is thinking…* →
  *Writing… 4 KB* (docked while the preview streams in), *Queued* for later screens of a flow. It stays readable when zoomed out.
- Clicking the empty part of a screen's title bar now selects it (it only started a drag).
- The prompt bar's status moved to its own line, so it no longer squeezes the controls while generating.

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

## 0.2.0
Spec engine for small local models, design systems, data sources, editor, flows, exports, tests and CI.

## 0.1.0
Prompt → UI mockups on a canvas, any OpenAI-compatible endpoint or Anthropic.
