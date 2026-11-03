# HANDOFF.md — state of localdesign for the next session

_Last updated 2026-10-25 (session 2, part 2). Repo: https://github.com/ghanemja/localdesign, branch `main`, CI green at `e556341`+. Everything below is pushed to `main`._

## What this is

A local, provider-agnostic Claude Design alternative, positioned for teams that can't use frontier/cloud tooling
(government, healthcare, air-gapped). Prompt → UI screens on an infinite canvas · edit by hand or by chat ·
works with any OpenAI-compatible endpoint or Anthropic · generates in the user's design system · zero runtime
dependencies · exports an **implementation pack** (Markdown + reference HTML) that a human or a small local
model can build the product from.

Sibling project: `../localcode` — a zero-dep Claude Code clone (`lc`). Built first by mistake, kept as a bonus. Not the focus.

## Run / develop

```bash
cd localdesign
uv tool install --editable . --force      # installs `lde` (editable: code changes apply on restart; static files apply on reload)
lde                                        # http://127.0.0.1:7878  (config in ~/.localdesign/config.json)
uv run --with pytest pytest                # 139 tests, ~2 s, no API key needed (mock model server in tests/conftest.py)
```

Useful flags: `--port`, `--no-open`, `--provider ollama -m qwen2.5-coder:14b`, `--base-url … --api-key …`, `--no-audit`, `--host 0.0.0.0 --allow-host <name>`.
Env: `LD_PROVIDER`, `LD_BASE_URL`, `LD_MODEL`, `LD_API_KEY`, `LD_HOME`.

Machine facts: user's `ANTHROPIC_API_KEY` is set (saved config currently points at `anthropic` / `claude-opus-5`).
Ollama has only `gemma3:4b` (slow: ~10 tok/s, 3-minute cold load; use the spec engine with it).
The Claude desktop app's browser pane can drive the UI; screenshots there lag iframe paints by a few seconds.
Headless Chrome (`/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --headless=new --screenshot=…`)
works for docs screenshots via `http://127.0.0.1:7878/?project=<id>&fit=1`, but heavy HTML-engine iframes don't paint
inside its virtual time budget — screenshot the screen HTML files directly and stitch with `ffmpeg hstack`.

## Architecture (all stdlib Python + vanilla JS, no build step)

```
localdesign/
  server.py        ThreadingHTTPServer. Static app, SSE generation, projects, config, assets, exports, Origin/Host guard, audit log
  llm.py           urllib streaming: OpenAI-compatible + Anthropic Messages API; thinking status events; Truncated on max_tokens/length
  prompts.py       html / spec / artifact / element / plan / export prompts; design-system, data and asset context blocks
  components.py    spec engine: JSON layout → HTML via a 30-node component library; BASE_CSS; JSON repair; SAMPLES + library()
  designsystem.py  CSS vars / tailwind.config.js / tokens JSON / HTML → tokens (+ palette, raw CSS)
  export.py        HTML → React (.jsx + .css) deterministic; project → design-spec Markdown
  pack.py          implementation pack (zip or folder): ARCHITECTURE(+narrative)/DESIGN_SYSTEM/FLOWS/DATA/PLAN/AGENTS/VERIFY + per-screen docs + HTML + PNG + css + assets; find_chrome/screenshot
  config.py        presets, ~/.localdesign/config.json, LD_* env, paths (projects/, assets/, audit.jsonl)
  static/
    index.html     app shell: topbar, library panel, canvas, prompt bar, dialogs (settings, projects, design system, data, flow, pack options), player
    app.css
    app.js         the canvas app (~900 lines): camera, frames, generate/iterate/regenerate, editor bridge, library, DS/data dialogs, flows, player, exports
    editor.js      shim injected into every screen iframe at display time (never saved): hover/select, text edit, style, reorder, drag/drop, serialize
tests/             pytest; conftest.py has FakeLLM (OpenAI-compatible mock that answers by prompt content) + the app on a free port
.github/workflows/ci.yml   Linux/Windows/macOS × Python 3.10/3.12/3.13 + wheel check — green
docs/              README screenshots (app.png: spec-rendered project + Playwright, no model needed — see below)
```

### Key mechanics
- **Engines**: `html` (model writes the page) / `spec` (model writes JSON, `components.render` renders it) / `auto` (spec for local providers under ~30B; `server.resolve_mode`). Artifacts (`kind: "artifact"`) always use html with `ARTIFACT_SYSTEM`.
- **Streaming**: `/api/generate`, `/api/iterate`, `/api/iterate-element`, `/api/export/react-ai` are SSE; events `status` (thinking), `partial` (html + chars), `done` (html, spec?, mode, warning?), `error`, `end`. Spec partials come from `components.repair_json` + render.
- **Project JSON** (`~/.localdesign/projects/<id>.json`): `{id, name, device, camera, designSystem, data, assets, screens:[{id,title,brief,x,y,width,kind,html,versions[],spec,specVersions[]}]}`. Autosaved by the client (debounced POST `/api/projects`). `?project=<id>&fit=1` deep-links.
- **Editor protocol** (parent ↔ iframe via postMessage, `{ld:true,type:…}`): parent sends `mode|select|deselect|delete|dup|move|style|text|edit|replace|link|drop|dragcancel|dragout-request|play`; shim sends `ready|select|deselect|html|undo|dragstart|dragout|dragback|dragend|navigate`. Manual edits set `spec=null` (screen becomes plain HTML).
- **Links/flows**: `data-link="<screen title>"` attributes in HTML (spec `link` props render to them). Arrows drawn from them; ▶ Play swaps iframes on `navigate`.
- **Assets**: `POST /api/assets {project,name,type,data(base64)}` → `~/.localdesign/assets/<project>/…`, served at `/assets/<project>/<file>`; `POST /api/inline` makes HTML self-contained (data URIs). Prompts list assets so the model uses them.
- **Security**: all requests need a `Host` in `ALLOWED_HOSTS`; mutating requests need a same-origin `Origin`/`Referer` (or none, for curl). Keys stored plaintext in config.json (documented). Audit log `~/.localdesign/audit.jsonl` records every model call (kinds: generate, artifact, iterate, element, plan, export, test).
- **Pack v2** (`POST /api/export/pack {project, screenshots?, narrative?, dest?, replace?}`): zip download, or JSON `{dest, files, warning}` when `dest` is an absolute folder (refuses non-empty unless `replace`; never deletes). `screenshots` runs `pack.screenshot` = `chrome --headless=new --screenshot --window-size=W,H --virtual-time-budget=3000 file://…` per screen (browser from `LD_CHROME`, PATH names, macOS/Windows app paths, Playwright bundles incl. `chrome-headless-shell`); one failure skips the rest. `narrative` = one blocking model call (`prompts.PACK_NARRATIVE`, temp 0.3) inserted as `## Narrative` under the ARCHITECTURE.md H1. Problems honouring an option go in the `X-LD-Warning` response header; the client toasts them. `GET /api/config` has `chrome: bool`.
- **VERIFY.md** (`pack.verify_md`): every line is a shell command (grep -rqF over `src/`) whose exit status is the verdict — copy verbatim, actions, fields, table columns, routes (same `/slug` convention as ARCHITECTURE.md), `var(--token)` references, no hex outside tokens.css, no CDN, data fixtures; plus manual visual/keyboard/contrast lines and a report format.
- **Other new endpoints**: `POST /api/test` (tiny model call → `{ok, reply, secs, mode}` / 502 `{error}`), `POST /api/ds/fetch {url}` (page + same-origin stylesheets, 2 MB/1 MB caps, 10 s → `designsystem.parse` result + `source_css`, `sheets`, `title`; falls back to HTML parsing when CSS yields < 2 tokens).

## Status

Done and verified (browser + tests): generation (both engines), variants/directions, iterate, regenerate, versions, device resize,
design-system import (paste or **from a site URL**), data sources, library (components/assets/snippets; drag or click-to-insert), in-screen editor incl. element AI edits and
cross-frame drag, flows (plan → generate → arrows → player), artifacts, exports (JSON, spec .md, HTML, React jsx+css, AI React+Tailwind,
implementation pack v2: VERIFY.md, per-screen PNGs, model narrative, write-to-folder), Settings → Test, first-run hint.

Session 2 verified the whole pack v2 chain in headless Chromium with Playwright (dialog → options → download / folder; zip inspected) and recorded `docs/demo.gif` the same way
(`scratchpad/gif/{demo_llm.py,record.js,run.sh}` were throw-away; the recipe: a fake OpenAI-compatible server that streams three solar-fleet specs by design direction, Playwright `recordVideo` 1600×1000, then
`ffmpeg -vf "setpts=0.8*PTS,fps=8,scale=800:-1,palettegen/paletteuse"` → 2.4 MB, ~19 s).

**Not verified**: a real mouse in Safari/Chrome on the editor and library drag — everything was driven through the postMessage protocol
and synthetic pointer events. The user reported "can't see how to drag" before the Safari fix + click-to-insert; needs a real check. Also not seen by a human: the new pack dialog, Settings Test button and DS URL field (only Playwright).

**Bug fixed in session 2**: a spec token `"radius": "10px"` (what small models and DS imports emit) crashed the whole render (`int("10px")`); `components._px` now tolerates px/rem/em strings.

**Not done**
- PyPI publish + tag. `pyproject`/`__init__` are at **0.3.0**, `CHANGELOG.md` holds the release notes, `uv build` output was verified in a clean venv (`lde --version` → 0.3.0, static files in the wheel, no tests in the wheel). No PyPI token in the cloud session — see the checklist below.
- Firefox untested. Linux/Windows only via CI (tests), not the UI. CI runs only on `main` pushes/PRs, so the session-2 branch has **not** been through the 9-job matrix yet (local run: 133 pass on Linux/py3.13).
- Headless *full* Chrome's `--screenshot` hung in the cloud container (the Playwright `chrome-headless-shell` worked, so it is preferred when bundled). On the user's Mac, Chrome.app `--headless=new --screenshot` worked last session; if PNGs come back missing, the toast says so and `LD_CHROME` can point at another binary.
- Spec engine: no progressive *section-level* streaming beyond JSON repair; `tabbar` not always emitted by small models on phone layouts.
- Editor: no redo; resize handles are style-popover only (no drag handles); undo is whole-screen version pop.
- Library: no search/filter; no user-defined component *categories*; assets limited to images/fonts, 8 MB.
- Multi-user: single process, single global config; fine for one person or a trusted LAN only.
- `/api/ds/fetch` and pack `dest` are same-origin-guarded like every POST, but they do let the browser tab make the server fetch a URL / write a folder on the user's machine. Acceptable for a local single-user tool; document if `--host 0.0.0.0` becomes common.

## Release checklist (v0.3.0) — the cloud session could not do these (tag push, release creation and PyPI are blocked for that session type)

```bash
git checkout main && git pull
git tag -a v0.3.0 -m "localdesign 0.3.0" && git push origin v0.3.0
rm -rf dist && uv build && uv publish          # needs UV_PUBLISH_TOKEN / ~/.pypirc; name `localdesign` was free
gh release create v0.3.0 dist/* --title "localdesign 0.3.0" --notes-file docs/RELEASE-0.3.0.md
```
The README already says `uv tool install localdesign`; it is wrong until `uv publish` has run, so do this soon.

## Session 2, part 2 (after the merge)
- README repositioned: lead with regulated/offline, comparison table vs Open Design (nexu-io, Apache-2.0, 60–85k stars, drives Claude Code/Codex), Dyad (local Lovable), Claude Design/Stitch; "Air-gapped install" section (pip download → --no-index, Ollama model copy, LD_CHROME).
- DESIGN.md (Google Labs / Stitch spec, alpha: YAML front matter `colors/typography/rounded/spacing/components`, `{token}` refs, fixed `##` sections Overview, Colors, Typography, Layout, Elevation & Depth, Shapes, Components, Do's and Don'ts). `designsystem.yaml_subset` is a 60-line stdlib YAML-subset parser (maps, scalars, inline/block lists) — enough for front matter, not general YAML. Import via the DS dialog (auto-detected) or `/api/ds/parse kind=designmd`; export via Export ▾ → DESIGN.md (`/api/export/designmd`) and inside every pack.
- Pack ships `verify.sh`: parses VERIFY.md's "- [ ] `cmd` — desc" lines, substitutes the src dir, prints PASS/FAIL/TODO, exits with the fail count. Tested end-to-end with a fake src tree.
- Not done from the "do all of this" list: the small-model proof recording (needs Ollama + a Mac; recipe in the GIF notes above — swap `demo_llm.py` for the real `lde --provider ollama -m gemma3:4b`), and the release steps above.

## Ideas queue (user-approved direction: ship for regulated/offline teams)
1. Real-mouse QA pass (editor, library drag, the three new dialogs), then the release checklist above.
2. Pack v3: a `verify.sh` that runs VERIFY.md's commands and prints the report; per-screen *diff* images (reference PNG vs. the agent's build) via the same headless browser; export the pack as a single `DESIGN.md` for tiny context windows.
3. Artifacts v2: multi-file artifacts, "chat with the artifact" log per frame, embed data sources into artifact JS.
4. Design-system v2: Storybook stories, Figma tokens plugin JSON; component *categories* in the library; DS-from-URL could also pull `<link rel=icon>`/logo into assets.
5. Editor v2: resize handles, redo, multi-select, align/distribute, copy element as spec node (keep spec linkage after manual edits).
6. Onboarding: sample project on first run, keyboard-shortcut sheet (Test button + first-run hint are done).
7. Local-model quality: fine-tune/evaluate spec-engine prompts per model family; cache component thumbnails.

## Memory
Claude's project memory for this repo lives in `~/.claude/projects/-Users-janelle-Documents-me-design/memory/project-localdesign.md`
(and `project-localcode.md`). The idea inbox is `~/.claude/projects/-Users-janelle-Documents/memory/ideas_inbox.md`.

## docs/app.png (session 3)
Still screenshot of the app itself, populated. Made without a model: a script writes `$LD_HOME/projects/helios.json` with three
screens rendered by `components.render(spec, width)` (fleet overview from `EXAMPLE_SPEC` + alerts table + 390-px field app),
a 20-line stub OpenAI-compatible server answers `/v1/models` so the status dot is green and the first-run dialog stays shut,
`lde --no-open --provider openai --base-url <stub> -m qwen2.5-coder:14b`, then Playwright at 1600×860, deviceScaleFactor 2,
`?project=helios&fit=1`, `localStorage['ld.hint.editor']='1'` (suppresses the hint toast), click the first frame's `.title`
to select it (clicking elsewhere on the title bar starts a drag and does **not** select), fill `#prompt`.
