# localdesign

A local, provider-agnostic take on **Claude Design**: describe a screen, get several UI mockup variants
rendered live on an infinite canvas, click one and chat to iterate, export HTML.
Single Python package, **zero dependencies**, no build step, works fully offline with a local model.

Works with anything that speaks the OpenAI chat-completions API — Ollama, LM Studio, llama.cpp server,
vLLM, an internal company endpoint, OpenRouter, OpenAI, Groq — plus the Anthropic Messages API.

## Install & run

```bash
uv tool install --editable /path/to/localdesign     # or pipx / pip install -e .
ld                                                  # opens http://127.0.0.1:7878
```

Point it at a model:

```bash
ld --provider ollama -m qwen2.5-coder:14b
ld --base-url https://llm.internal.corp/v1 -m our-model --api-key $TOKEN     # any OpenAI-compatible endpoint
LD_BASE_URL=http://10.0.0.5:8000/v1 LD_MODEL=Qwen/Qwen3-Coder-30B ld           # env vars work too
ld --provider anthropic -m claude-opus-5
```

Or open **Settings** (top right) in the app: pick a preset, paste a base URL, hit **Fetch** to list the
endpoint's models, save. Config persists in `~/.localdesign/config.json`.

## Using it

- Type a brief in the bar at the bottom → N variants (1–6, each with a different design direction) stream
  onto the canvas as they generate.
- Click a screen → the bar switches to **Apply**: describe a change, a new version replaces it in place.
  Click the `v3` badge to cycle through versions.
- Desktop / Tablet / Phone toggles set the viewport width for new screens.
- Drag to pan, ⌘/Ctrl + scroll to zoom, Space + drag to pan, `Fit` or ⇧1 to frame everything, `/` to focus the prompt.
- Per screen: duplicate, download `.html`, open in a new tab, delete. Project → **Export** JSON (re-importable).
- Projects autosave to `~/.localdesign/projects/`. The `▾` next to the name switches projects.

Generated screens are self-contained HTML with inline CSS and no external resources, so they render offline
and are safe to drop anywhere. Turn on *Allow CDN* in Settings to let the model use Tailwind + Google Fonts.

## Model notes

UI generation needs a decent coder/instruct model. Rough guide:

| Model | Result |
|---|---|
| 4B general (gemma3:4b) | works, simple layouts, sometimes forgets the "HTML only" rule |
| 7–14B coder (qwen2.5-coder, devstral, qwen3-coder) | good — recommended local floor |
| 30B+ / hosted frontier | Claude-Design-like quality |

## Layout

```
localdesign/
  server.py     stdlib HTTP server: static app, /api/generate + /api/iterate (SSE), projects, config
  llm.py        streaming over urllib: OpenAI-compatible + Anthropic
  prompts.py    designer system prompt, variant directions, HTML extraction
  config.py     presets, ~/.localdesign/config.json, LD_* env overrides
  static/       index.html · app.css · app.js  (vanilla, no build)
```
