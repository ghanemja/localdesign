/* localdesign — canvas app. Vanilla JS, no build step. */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const uid = () => Math.random().toString(36).slice(2, 10);
  const HEIGHTS = { 1280: 800, 768: 1024, 390: 844 };
  const frameH = (s) => s.kind === "artifact" ? (s.width >= 1280 ? 880 : HEIGHTS[s.width]) : HEIGHTS[s.width];

  // ------------------------------------------------------------ state
  const blankProject = () => ({ id: null, name: "Untitled", device: 1280, screens: [], camera: { x: 80, y: 60, z: 1 }, designSystem: null, data: {}, assets: [], code: null });
  let project = blankProject();
  let selected = null;           // screen id
  let cfg = {};
  let aborter = null;
  const frames = new Map();     // id -> element
  const busyIds = new Set();    // screens with a model call in flight: drives .loading, and renderFrame never marks them as failed
  const startedAt = {};         // screen id -> ms when its model call started (per-frame elapsed time)
  let saveTimer = null;
  const kb = n => n >= 1e6 ? (n / 1e6).toFixed(1) + " MB" : Math.max(1, Math.round((n || 0) / 1000)) + " KB";

  const viewport = $("#viewport"), canvas = $("#canvas"), emptyEl = $("#empty");
  const promptEl = $("#prompt"), goBtn = $("#goBtn"), stopBtn = $("#stopBtn");

  // ------------------------------------------------------------ toast
  let toastTimer;
  function toast(msg, ms = 3000) {
    const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.add("hidden"), ms);
  }

  // ------------------------------------------------------------ camera
  function applyCamera() {
    const c = project.camera;
    canvas.style.transform = `translate(${c.x}px, ${c.y}px) scale(${c.z})`; canvas.style.setProperty("--z", c.z);
    viewport.style.backgroundPosition = `${c.x}px ${c.y}px`;
    viewport.style.backgroundSize = c.z < 0.25 ? `${96 * c.z}px ${96 * c.z}px` : `${24 * c.z}px ${24 * c.z}px`;   // coarser grid when zoomed far out
    $("#zoomLabel").textContent = Math.round(c.z * 100) + "%";
    scheduleSave();
  }
  function zoomAt(factor, cx, cy) {
    const c = project.camera, nz = Math.min(3, Math.max(0.08, c.z * factor));
    c.x = cx - (cx - c.x) * (nz / c.z); c.y = cy - (cy - c.y) * (nz / c.z); c.z = nz;
    applyCamera();
  }
  function fitAll() {
    if (!project.screens.length) return;
    const xs = project.screens.map(s => s.x), ys = project.screens.map(s => s.y);
    const xe = project.screens.map(s => s.x + s.width), ye = project.screens.map(s => s.y + frameH(s) + 36);
    const bx = Math.min(...xs), by = Math.min(...ys), bw = Math.max(...xe) - bx, bh = Math.max(...ye) - by;
    const vw = viewport.clientWidth, vh = viewport.clientHeight - 140;
    const z = Math.min(3, Math.max(0.08, Math.min((vw - 80) / bw, (vh - 60) / bh)));
    project.camera = { z, x: (vw - bw * z) / 2 - bx * z, y: (vh - bh * z) / 2 - by * z + 20 };
    applyCamera();
  }
  viewport.addEventListener("wheel", e => {
    e.preventDefault();
    const r = viewport.getBoundingClientRect();
    if (e.ctrlKey || e.metaKey) zoomAt(Math.exp(-e.deltaY * 0.01), e.clientX - r.left, e.clientY - r.top);
    else { project.camera.x -= e.deltaX; project.camera.y -= e.deltaY; applyCamera(); }
  }, { passive: false });

  // pan: drag on empty viewport, middle button, or space+drag anywhere
  let space = false, pan = null;
  window.addEventListener("keydown", e => { if (e.code === "Space" && !isTyping(e)) { space = true; viewport.classList.add("panning"); e.preventDefault(); } });
  window.addEventListener("keyup", e => { if (e.code === "Space") { space = false; if (!pan) viewport.classList.remove("panning"); } });
  viewport.addEventListener("pointerdown", e => {
    const onFrame = e.target.closest(".frame");
    if (e.button === 1 || space || (!onFrame && e.button === 0)) {
      pan = { x: e.clientX, y: e.clientY, cx: project.camera.x, cy: project.camera.y };
      viewport.classList.add("panning"); viewport.setPointerCapture(e.pointerId); e.preventDefault();
      if (!onFrame && !space) select(null);
    }
  });
  viewport.addEventListener("pointermove", e => {
    if (!pan) return;
    project.camera.x = pan.cx + e.clientX - pan.x; project.camera.y = pan.cy + e.clientY - pan.y; applyCamera();
  });
  viewport.addEventListener("pointerup", () => { pan = null; if (!space) viewport.classList.remove("panning"); });

  function isTyping(e) { const t = e.target; return t && (t.tagName === "TEXTAREA" || t.tagName === "INPUT" || t.isContentEditable); }

  // ------------------------------------------------------------ frames
  function screenById(id) { return project.screens.find(s => s.id === id); }

  function renderFrame(s) {
    let el = frames.get(s.id);
    if (!el) {
      el = $("#frameTpl").content.firstElementChild.cloneNode(true);
      el.dataset.id = s.id; canvas.appendChild(el); frames.set(s.id, el);
      wireFrame(el, s);
    }
    el.style.left = s.x + "px"; el.style.top = s.y + "px"; el.style.width = s.width + "px";
    $(".body", el).style.height = frameH(s) + "px";
    $(".eng", el).textContent = s.kind === "artifact" ? "artifact" : (s.spec ? "spec" : "");
    $(".title", el).textContent = s.title;
    const v = $(".ver", el); v.textContent = "v" + (s.versions.length); v.title = s.versions.length > 1 ? "Click to switch version" : "";
    v.style.display = s.versions.length > 1 ? "" : "none";
    el.classList.toggle("selected", s.id === selected);
    const busy = busyIds.has(s.id); el.classList.toggle("loading", busy);
    if (!s.html && !busy) { el.classList.add("noresult"); const er = $(".err", el); if (!er.textContent) { er.textContent = "No result saved (page was closed mid-generation?). Click ↻ to regenerate."; er.classList.remove("hidden"); } }
    else if (s.html && !el.classList.contains("failed")) { el.classList.remove("noresult"); const er = $(".err", el); er.textContent = ""; er.classList.add("hidden"); }
    if ($("iframe", el).dataset.html !== s.html) setFrameHTML(el, s.html);
    return el;
  }
  let EDITOR_SRC = "";
  fetch("/static/editor.js").then(r => r.text()).then(t => { EDITOR_SRC = t; }).catch(() => {});
  function withEditor(html) {
    if (!EDITOR_SRC || !html) return html;
    const tag = `<script data-ld-ui="1">${EDITOR_SRC}</script>`;
    return /<\/body>/i.test(html) ? html.replace(/<\/body>/i, tag + "</body>") : html + tag;
  }
  function setFrameHTML(el, html) {
    const f = $("iframe", el);
    f.dataset.html = html; f.srcdoc = withEditor(html) || "<!doctype html><body style='font:14px system-ui;color:#999;padding:24px'>…</body>";
    elClear(el.dataset.id);
  }
  function wireFrame(el, s) {
    el.addEventListener("pointerdown", e => { if (e.button === 0 && !space) { select(s.id); } });
    // drag by bar
    $(".bar", el).addEventListener("pointerdown", e => {
      if (e.button !== 0 || space || e.target.closest("button, .title, .ver")) return;
      e.stopPropagation(); select(s.id);   // stopPropagation also skips the frame's own select handler
      const st = { x: e.clientX, y: e.clientY, sx: s.x, sy: s.y };
      const mv = ev => { s.x = st.sx + (ev.clientX - st.x) / project.camera.z; s.y = st.sy + (ev.clientY - st.y) / project.camera.z; el.style.left = s.x + "px"; el.style.top = s.y + "px"; };
      const up = () => { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); scheduleSave(); drawArrows(); };
      window.addEventListener("pointermove", mv); window.addEventListener("pointerup", up);
    });
    $(".title", el).addEventListener("blur", e => { const old = s.title; s.title = e.target.textContent.trim() || s.title; e.target.textContent = s.title; if (old !== s.title) renameLinks(old, s.title); scheduleSave(); drawArrows(); });
    $(".title", el).addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); e.target.blur(); } });
    $(".ver", el).addEventListener("click", e => { e.stopPropagation(); cycleVersion(s); });
    $(".dup", el).addEventListener("click", e => { e.stopPropagation(); duplicate(s); });
    $(".dl", el).addEventListener("click", async e => { e.stopPropagation(); download(`${slug(s.title)}.html`, await inlined(s.html), "text/html"); });
    $(".open", el).addEventListener("click", async e => { e.stopPropagation(); const b = new Blob([await inlined(s.html)], { type: "text/html" }); window.open(URL.createObjectURL(b), "_blank"); });
    $(".del", el).addEventListener("click", e => { e.stopPropagation(); removeScreen(s.id); });
    $(".regen", el).addEventListener("click", e => { e.stopPropagation(); regenerate(s); });
  }
  function linkContext(s) {   // navigation instructions for a screen that links to others (flow plan + data-link already in it)
    const links = [...new Set([...((s.flow && s.flow.links) || []), ...linksOf(s)])].filter(t => screenByTitle(t));
    if (!s.flow && !links.length) return "";
    const sibs = s.flow ? project.screens.filter(x => x.flow && x.flow.group === s.flow.group).map(x => x.title) : [s.title, ...links];
    return `This screen is part of a flow with these screens: ${sibs.join(", ")}.\nNavigation elements that lead to another screen must carry data-link="<exact screen title>" (in spec mode: set "link" on buttons/nav items/list rows). This screen links to: ${links.join(", ") || "none"}.`;
  }
  function renameLinks(old, now) {   // links are by title: keep every data-link / spec link / planned link pointing at a renamed screen
    const a = `data-link="${esc(old)}"`, b = `data-link="${esc(now)}"`;
    const walk = n => { if (Array.isArray(n)) n.forEach(walk); else if (n && typeof n === "object") for (const k in n) { if (k === "link" && n[k] === old) n[k] = now; else walk(n[k]); } };
    for (const x of project.screens) {
      if (x.flow && x.flow.links) x.flow.links = x.flow.links.map(t => t === old ? now : t);
      if (x.spec) walk(x.spec);
      if (x.html && x.html.includes(a)) {
        x.html = x.html.split(a).join(b); if (x.versions.length) x.versions[x.versions.length - 1] = x.html;
        const fe = frames.get(x.id); if (fe) setFrameHTML(fe, x.html);
      }
    }
  }
  function cycleVersion(s) {
    const i = s.versions.indexOf(s.html);
    const next = s.versions[(i + 1) % s.versions.length];
    s.html = next; if (s.specVersions) s.spec = s.specVersions[s.versions.indexOf(next)] || null; const el = frames.get(s.id); setFrameHTML(el, next); $(".eng", el).textContent = s.spec ? "spec" : "";
    $(".ver", el).textContent = "v" + (s.versions.indexOf(next) + 1); toast(`Showing v${s.versions.indexOf(next) + 1} of ${s.versions.length}`, 1200); scheduleSave();
  }
  function renderAll() {
    for (const [id, el] of frames) if (!screenById(id)) { el.remove(); frames.delete(id); }
    project.screens.forEach(renderFrame);
    emptyEl.classList.toggle("hidden", project.screens.length > 0);
    $("#projectName").value = project.name;
    $$("#deviceSeg button").forEach(b => b.classList.toggle("on", +b.dataset.w === project.device));
    dsIndicator(); drawArrows();
    applyCamera();
  }
  function select(id) {
    if (selected && selected !== id) { const prev = frames.get(selected); if (prev) postFrame(selected, { type: "mode", edit: false }); elClear(selected); }
    selected = id;
    frames.forEach((el, fid) => el.classList.toggle("selected", fid === id));
    const s = id && screenById(id);
    if (s) { postFrame(id, { type: "mode", edit: true }); if (!localStorage.getItem("ld.hint.editor")) { toast("Click any element inside the screen to edit it · double-click text · drag to reorder or onto another screen · ⌘Z undo", 7000); localStorage.setItem("ld.hint.editor", "1"); } }
    updateChip();
  }
  function updateChip() {
    const s = selected && screenById(selected);
    const el = elSel && frames.get(elSel.frame) ? elSel : null;
    $("#targetChip").classList.toggle("hidden", !s);
    if (el) { $("#targetKind").textContent = "Element"; $("#targetName").textContent = `${el.info.desc} in ${screenById(el.frame)?.title || ""}`; promptEl.placeholder = "Describe how to change this element…"; goBtn.firstChild.textContent = "Change "; }
    else if (s) { $("#targetKind").textContent = "Editing"; $("#targetName").textContent = s.title; promptEl.placeholder = "Describe a change to this screen…"; goBtn.firstChild.textContent = "Apply "; }
    else { promptEl.placeholder = "Describe a screen to design…"; goBtn.firstChild.textContent = "Generate "; }
  }
  function postFrame(id, msg) { const el = frames.get(id); const w = el && $("iframe", el).contentWindow; if (w) w.postMessage({ ld: true, ...msg }, "*"); }
  function removeScreen(id) {
    project.screens = project.screens.filter(s => s.id !== id);
    if (selected === id) select(null);
    renderAll(); scheduleSave();
  }
  function duplicate(s) {
    const d = { ...s, id: uid(), title: s.title + " copy", x: s.x + s.width + 60, versions: [...s.versions] };
    project.screens.push(d); renderAll(); select(d.id); scheduleSave();
  }
  function nextRowY() {
    if (!project.screens.length) return 0;
    return Math.max(...project.screens.map(s => s.y + frameH(s) + 36)) + 120;
  }
  async function inlined(html) { if (!/\/assets\//.test(html)) return html; try { const r = await fetch("/api/inline", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ html }) }); return (await r.json()).html || html; } catch { return html; } }
  const slug = t => (t || "screen").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "").slice(0, 60);

  // ------------------------------------------------------------ SSE helper
  async function streamPost(url, body, onEvent, signal) {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal });
    if (!r.ok) { let m = r.statusText; try { m = (await r.json()).error || m; } catch {} throw new Error(m); }
    const rd = r.body.getReader(), dec = new TextDecoder(); let buf = "";
    for (;;) {
      const { value, done } = await rd.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      let i; while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        for (const line of chunk.split("\n")) if (line.startsWith("data:")) { try { onEvent(JSON.parse(line.slice(5))); } catch {} }
      }
    }
  }

  // ------------------------------------------------------------ generate / iterate
  let genKind = "screen";
  $$("#kindSeg button").forEach(b => b.addEventListener("click", () => { genKind = b.dataset.kind; $$("#kindSeg button").forEach(x => x.classList.toggle("on", x === b)); if (genKind === "artifact") { $("#variants").value = "1"; } promptEl.placeholder = genKind === "artifact" ? "Describe an app, tool, chart, game or document to build…" : "Describe a screen to design…"; }));
  const genExtras = () => ({ mode: $("#engine").value, kind: genKind, design_system: project.designSystem || undefined, data: Object.keys(project.data || {}).length ? project.data : undefined, assets: (project.assets || []).length ? project.assets : undefined, code: codeRef() });
  let progTimer = null, progStart = 0, progBytes = {}, ctxNote = "";
  const LOCAL = ["ollama", "lmstudio", "llamacpp", "vllm", "custom"];
  function setLoading(s, on) {
    if (on) { busyIds.add(s.id); startedAt[s.id] = Date.now(); } else busyIds.delete(s.id);
    const el = frames.get(s.id); if (!el) return;
    el.classList.toggle("loading", on);
    if (on) {
      el.classList.remove("failed", "noresult", "streaming"); const er = $(".err", el); er.textContent = ""; er.classList.add("hidden");
      delete $(".prog", el).dataset.phase; progBytes[s.id] = 0; $(".wait .wlbl", el).textContent = waitLabel(s.id, 0);
    } else { el.classList.remove("streaming", "queued"); $(".prog", el).textContent = ""; }
  }
  function waitLabel(id, secs) {
    const el = frames.get(id); if (!el) return "";
    if (el.classList.contains("queued")) return "Queued";
    const t = secs ? ` ${secs}s` : "", k = (progBytes[id] || 0) / 1024;
    if (k) return `Writing… ${k.toFixed(0)} KB ·${t}`;
    if ($(".prog", el).dataset.phase === "thinking") return `Model is thinking…${t}`;
    return `Waiting for ${cfg.model || "the model"}…${t}` + (secs >= 20 && LOCAL.includes(cfg.provider) ? " (a local model can take a minute to load)" : "");
  }
  function setBusy(b, label) {
    goBtn.disabled = b; stopBtn.classList.toggle("hidden", !b);
    clearInterval(progTimer);
    if (b) {
      progStart = Date.now(); progBytes = {}; ctxNote = "";
      progTimer = setInterval(() => {
        const secs = Math.round((Date.now() - progStart) / 1000);
        const total = Object.values(progBytes).reduce((a, n) => a + n, 0) / 1024;
        $("#status").textContent = `${label} · ${secs}s · ${total.toFixed(0)} KB received` + (ctxNote ? ` · ${ctxNote}` : "");
        let thinking = 0;
        for (const [id, el] of frames) if (el.classList.contains("loading")) {
          const p = $(".prog", el), k = (progBytes[id] || 0) / 1024, fs = Math.round((Date.now() - (startedAt[id] || progStart)) / 1000);
          if (el.classList.contains("queued")) p.textContent = "queued";
          else if (p.dataset.phase === "thinking" && !k) { thinking++; p.textContent = `thinking… ${fs}s`; }
          else p.textContent = `${fs}s · ${k.toFixed(0)} KB`;
          $(".wait .wlbl", el).textContent = waitLabel(id, fs);
        }
        if (thinking) $("#status").textContent += ` · model is thinking (${thinking})`;
        $("#status").title = $("#status").textContent;
      }, 1000);
      $("#status").textContent = label + " · 0s";
    } else { $("#status").textContent = ""; $("#status").title = ""; }
  }

  async function generate(brief) {
    const n = +$("#variants").value, width = project.device, y = nextRowY();
    const batch = [];
    for (let i = 0; i < n; i++) {
      const s = { id: uid(), title: shortTitle(brief) + (n > 1 ? ` ${String.fromCharCode(65 + i)}` : ""), brief, x: i * (width + 80), y, width, html: "", versions: [], kind: genKind };
      project.screens.push(s); batch.push(s);
    }
    batch.forEach(s => busyIds.add(s.id));   // before renderAll, so the new empty frames render as loading, not as "no result"
    renderAll(); batch.forEach(s => setLoading(s, true));
    if (project.screens.length === n) fitAll(); else panTo(batch[0]);
    const context = projectContext(batch);
    aborter = new AbortController(); setBusy(true, `Generating ${n} variant${n > 1 ? "s" : ""}`);
    try {
      await streamPost("/api/generate", { brief, variants: n, width, context, ...genExtras() }, ev => handleEvent(ev, batch), aborter.signal);
    } catch (e) { if (e.name !== "AbortError") toast("Error: " + e.message, 6000); }
    finally { finish(batch); }
  }

  async function iterate(s, instruction) {
    setLoading(s, true);
    const prev = s.html; aborter = new AbortController(); setBusy(true, "Applying change");
    try {
      await streamPost("/api/iterate", { html: prev, instruction, width: s.width, spec: s.spec || undefined, ...genExtras(), kind: s.kind || "screen" }, ev => handleEvent(ev, [s]), aborter.signal);
    } catch (e) { if (e.name !== "AbortError") toast("Error: " + e.message, 6000); }
    finally { finish([s]); }
  }

  async function regenerate(s) {
    if (goBtn.disabled) { toast("Wait for the current generation to finish."); return; }
    setLoading(s, true);
    const brief = s.brief || s.title;
    aborter = new AbortController(); setBusy(true, "Regenerating");
    try {
      const links = linkContext(s), context = [projectContext([s]), links].filter(Boolean).join("\n") || null;   // keep its navigation
      await streamPost("/api/generate", { brief, variants: 1, width: s.width, context, ...genExtras(), kind: s.kind || "screen" }, ev => handleEvent(ev, [s]), aborter.signal);
    } catch (e) { if (e.name !== "AbortError") toast("Error: " + e.message, 6000); }
    finally { finish([s]); }
  }

  function handleEvent(ev, batch) {
    if (ev.type === "context") { noteContext(ev); return; }
    const s = batch[ev.i]; if (!s) return;
    const el = frames.get(s.id); if (!el) return;
    if (ev.type === "status") { $(".prog", el).dataset.phase = ev.status; }
    else if (ev.type === "partial") { delete $(".prog", el).dataset.phase; progBytes[s.id] = ev.chars || (ev.html || "").length; if (ev.html) { setFrameHTML(el, ev.html); el.classList.add("streaming"); } }
    if (ev.type === "status" || ev.type === "partial") $(".wait .wlbl", el).textContent = waitLabel(s.id, Math.round((Date.now() - (startedAt[s.id] || progStart)) / 1000));   // don't wait for the 1 s tick
    else if (ev.type === "done") {
      s.html = ev.html; s.versions.push(ev.html); s.spec = ev.spec || null; s.specVersions = s.specVersions || []; s.specVersions.push(ev.spec || null);
      setLoading(s, false); setFrameHTML(el, ev.html); el.classList.remove("failed", "noresult"); const er0 = $(".err", el); er0.textContent = ""; er0.classList.add("hidden");
      renderFrame(s); scheduleSave(); drawArrows();
      if (ev.warning) { toast("⚠ " + s.title + ": " + ev.warning, 7000); $(".title", el).title = ev.warning; }
    } else if (ev.type === "error") {
      setLoading(s, false); el.classList.add("failed"); const er = $(".err", el); er.textContent = ev.message; er.classList.remove("hidden");
      if (s.html) setFrameHTML(el, s.html);
    }
  }
  function finish(batch) {
    setBusy(false); aborter = null;
    for (const s of batch) {
      setLoading(s, false);
      const el = frames.get(s.id); if (!el) continue;
      if (!s.versions.length && !$(".err", el).textContent) { $(".err", el).textContent = "Stopped before any result. Click ↻ to regenerate."; $(".err", el).classList.remove("hidden"); el.classList.add("noresult"); }
    }
    scheduleSave();
  }
  function noteContext(ev) {   // the server says which attached code files went into the prompt
    const n = ev.files.length;
    ctxNote = n ? `📎 ${n} file${n > 1 ? "s" : ""} from ${ev.name}` : `📎 ${ev.name} (file list only)`;
    const w = [];
    if (ev.unresolved && ev.unresolved.length) w.push(`not found in ${ev.name}: ${ev.unresolved.map(t => "@" + t).join(", ")}`);
    if (ev.omitted && ev.omitted.length) w.push(`${ev.omitted.length} file${ev.omitted.length > 1 ? "s" : ""} did not fit the ${kb(ev.budget)} code budget (Settings): ${ev.omitted.slice(0, 4).join(", ")}${ev.omitted.length > 4 ? "…" : ""}`);
    const cut = ev.files.filter(f => f.truncated); if (cut.length) w.push(`cut short to fit the ${kb(ev.budget)} budget: ${cut.map(f => f.path).join(", ")}`);
    if (w.length) toast("⚠ " + w.join("\n"), 9000);
  }
  function panTo(s) {
    const c = project.camera, vw = viewport.clientWidth;
    c.x = (vw - s.width * c.z) / 2 - s.x * c.z; c.y = 40 - s.y * c.z; applyCamera();
  }
  function shortTitle(b) {
    const t = b.replace(/(^|\s)@(\S+)/g, (m, sp, p) => sp + (p.replace(/\/$/, "").split("/").pop() || p)).replace(/\s+/g, " ").trim();   // "@src/pages/Settings.tsx" → "Settings.tsx"
    return t.length > 42 ? t.slice(0, 40).replace(/\s\S*$/, "") + "…" : t;
  }
  function projectContext(exclude) {
    const others = project.screens.filter(s => !exclude.includes(s) && s.html);
    if (!others.length) return null;
    return others.slice(-4).map(s => `- Existing screen "${s.title}": ${s.brief || ""}`).join("\n") + "\nReuse the same palette/typography as existing screens where sensible.";
  }

  $("#promptBar").addEventListener("submit", e => {
    e.preventDefault(); const text = promptEl.value.trim(); if (!text || goBtn.disabled) return;
    promptEl.value = ""; autosize(); hideMention();
    const s = selected && screenById(selected);
    if (elSel && s && elSel.frame === s.id) iterateElement(s, text);
    else if (s && s.html) iterate(s, text); else generate(text);
  });
  promptEl.addEventListener("keydown", e => {
    if (e.isComposing) return;
    if (mentionOpen()) {   // @file completion owns the arrows, Enter/Tab and Esc while it is open
      const n = mention.items.length;
      if ((e.key === "ArrowDown" || e.key === "ArrowUp") && n) { e.preventDefault(); mention.idx = (mention.idx + (e.key === "ArrowDown" ? 1 : n - 1)) % n; renderMention(); return; }
      if ((e.key === "Enter" || e.key === "Tab") && n && !e.shiftKey) { e.preventDefault(); pickMention(mention.idx); return; }
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); hideMention(); return; }
    }
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#promptBar").requestSubmit(); }
  });
  promptEl.addEventListener("beforeinput", e => { if ((e.inputType === "insertLineBreak" || e.inputType === "insertParagraph") && !mentionOpen()) { e.preventDefault(); $("#promptBar").requestSubmit(); } });
  function autosize() { if (!promptEl.value) { promptEl.style.height = ""; return; } promptEl.style.height = "auto"; promptEl.style.height = Math.min(200, promptEl.scrollHeight) + "px"; }
  promptEl.addEventListener("input", autosize);
  stopBtn.addEventListener("click", () => aborter && aborter.abort());
  $("#clearTarget").addEventListener("click", () => select(null));
  $("#engine").addEventListener("change", e => postConfig({ mode: e.target.value }));

  // ------------------------------------------------------------ toolbar
  $("#zoomIn").addEventListener("click", () => zoomAt(1.25, viewport.clientWidth / 2, viewport.clientHeight / 2));
  $("#zoomOut").addEventListener("click", () => zoomAt(0.8, viewport.clientWidth / 2, viewport.clientHeight / 2));
  $("#zoomLabel").addEventListener("click", () => { project.camera.z = 1; applyCamera(); });
  $("#fitBtn").addEventListener("click", fitAll);
  $$("#deviceSeg button").forEach(b => b.addEventListener("click", async () => {
    const w = +b.dataset.w; project.device = w;
    const s = selected && screenById(selected);
    if (s && s.width !== w) {
      s.width = w; renderFrame(s);
      if (s.spec) {
        try { const r = await fetch("/api/render", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ spec: s.spec, width: w, design_system: project.designSystem || undefined, data: project.data }) });
          const d = await r.json(); if (d.html) { s.html = d.html; s.versions[s.versions.length - 1] = d.html; setFrameHTML(frames.get(s.id), d.html); } } catch {}
        toast(`${s.title} re-rendered at ${w}px`, 2000);
      } else toast(`${s.title} resized to ${w}px — it reflows; press ↻ to regenerate it for this size`, 3500);
      drawArrows();
    } else if (!s) toast(`New screens will be ${w === 1280 ? "desktop" : w === 768 ? "tablet" : "phone"} width. Select a screen to resize it.`, 2500);
    renderAll(); scheduleSave();
  }));
  $("#projectName").addEventListener("change", e => { project.name = e.target.value.trim() || "Untitled"; scheduleSave(); });
  const exportMenu = $("#exportMenu");
  $("#exportBtn").addEventListener("click", e => { e.stopPropagation(); exportMenu.classList.toggle("hidden"); });
  document.addEventListener("click", e => { if (!e.target.closest(".menuwrap")) exportMenu.classList.add("hidden"); });
  exportMenu.addEventListener("click", async e => {
    const b = e.target.closest("button"); if (!b) return; exportMenu.classList.add("hidden");
    const kind = b.dataset.x, s = selected && screenById(selected);
    const needSel = ["html", "react", "react-ai"].includes(kind);
    if (needSel && !(s && s.html)) { toast("Select a screen first"); return; }
    const post = async (url, body) => { const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); const d = await r.json(); if (d.error) throw new Error(d.error); return d; };
    try {
      if (kind === "json") download(`${slug(project.name)}.localdesign.json`, JSON.stringify(project, null, 2), "application/json");
      else if (kind === "pack") {
        if (!project.screens.some(x => x.html)) { toast("Nothing to export yet"); return; }
        $("#packShots").disabled = !cfg.chrome; if (!cfg.chrome) $("#packShots").checked = false;
        $("#packShotsNote").textContent = cfg.chrome ? "" : "— no headless Chrome/Chromium/Edge found on this machine (install one, or set LD_CHROME)";
        $("#packNarrative").disabled = !cfg.model; $("#packMsg").textContent = ""; $("#packDest").value = localStorage.getItem("ld.packDest") || ""; $("#packDlg").showModal();
      }
      else if (kind === "spec") { const d = await post("/api/export/spec", { project }); download(`${slug(project.name)}-design-spec.md`, d.markdown, "text/markdown"); }
      else if (kind === "designmd") { const d = await post("/api/export/designmd", { project }); download("DESIGN.md", d.markdown, "text/markdown"); toast("DESIGN.md exported — drop it in a repo for Claude Code, Stitch, Open Design or any agent that reads DESIGN.md", 5000); }
      else if (kind === "html") download(`${slug(s.title)}.html`, await inlined(s.html), "text/html");
      else if (kind === "html-all") { for (const sc of project.screens.filter(x => x.html)) { download(`${slug(sc.title)}.html`, await inlined(sc.html), "text/html"); await new Promise(r => setTimeout(r, 300)); } }
      else if (kind === "react" || kind === "react-all") {
        const list = kind === "react" ? [s] : project.screens.filter(x => x.html);
        for (const sc of list) { const d = await post("/api/export/react", { html: sc.html, title: sc.title }); download(`${d.name}.jsx`, d.jsx, "text/javascript"); await new Promise(r => setTimeout(r, 250)); download(`${d.name}.css`, d.css, "text/css"); await new Promise(r => setTimeout(r, 300)); }
        toast(`Exported ${list.length} component${list.length > 1 ? "s" : ""} (.jsx + .css)`);
      }
      else if (kind === "react-ai") {
        if (goBtn.disabled) { toast("Wait for the current generation to finish."); return; }
        aborter = new AbortController(); setBusy(true, "Converting to React + Tailwind");
        try {
          await streamPost("/api/export/react-ai", { html: s.html, title: s.title }, ev => {
            if (ev.type === "done") { const name = (ev.text.match(/function\s+([A-Z][A-Za-z0-9]*)/) || [, slug(s.title)])[1]; download(`${name}.jsx`, ev.text, "text/javascript"); toast("Exported " + name + ".jsx"); }
            else if (ev.type === "error") toast("Error: " + ev.message, 6000);
          }, aborter.signal);
        } finally { setBusy(false); aborter = null; }
      }
    } catch (err) { toast("Export failed: " + err.message, 5000); }
  });
  $("#packCancel").addEventListener("click", () => $("#packDlg").close());
  $("#packGo").addEventListener("click", async () => {
    const opts = { screenshots: $("#packShots").checked, narrative: $("#packNarrative").checked, dest: $("#packDest").value.trim() || undefined, replace: $("#packReplace").checked || undefined };
    if (opts.narrative && goBtn.disabled) { toast("Wait for the current generation to finish."); return; }
    const btn = $("#packGo"); btn.disabled = true;
    $("#packMsg").textContent = opts.narrative ? "Writing the overview with the model, then packing…" : opts.screenshots ? "Rendering screenshots…" : "Packing…";
    if (opts.narrative) setBusy(true, "Writing ARCHITECTURE.md overview");
    try {
      await save();
      const r = await fetch("/api/export/pack", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project, ...opts }) });
      if (!r.ok) throw new Error((await r.json()).error || r.statusText);
      if (opts.dest) {
        const d = await r.json(); $("#packDlg").close(); try { localStorage.setItem("ld.packDest", opts.dest); } catch {}
        toast((d.warning ? "Pack written, but: " + d.warning + " — " : "") + `${d.files} files written to ${d.dest}. Tell your agent: "Read ${d.dest.replace(/\/$/, "")}/AGENTS.md and follow it."`, d.warning ? 9000 : 7000);
        return;
      }
      const warn = r.headers.get("X-LD-Warning");
      const blob = await r.blob(); const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `${slug(project.name)}-pack.zip`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
      $("#packDlg").close();
      toast(warn ? "Pack exported, but: " + warn : "Implementation pack exported — drop the folder into your repo and tell your agent to read AGENTS.md", warn ? 8000 : 5000);
    } catch (err) { $("#packMsg").textContent = "Export failed: " + err.message; }
    finally { btn.disabled = false; if (opts.narrative) setBusy(false); }
  });
  window.addEventListener("keydown", e => {
    if (isTyping(e)) { if (e.key === "Escape") e.target.blur(); return; }
    const mod = e.metaKey || e.ctrlKey;
    if (e.key === "Escape") select(null);
    else if ((e.key === "Delete" || e.key === "Backspace") && selected) { if (elSel && elSel.frame === selected) postFrame(selected, { type: "delete" }); else if (confirm("Delete this screen?")) removeScreen(selected); }
    else if (mod && e.key === "z" && selected) { e.preventDefault(); undoScreen(screenById(selected)); }
    else if (mod && e.key === "d" && selected) { e.preventDefault(); duplicate(screenById(selected)); }
    else if (mod && (e.key === "=" || e.key === "+")) { e.preventDefault(); zoomAt(1.25, viewport.clientWidth / 2, viewport.clientHeight / 2); }
    else if (mod && e.key === "-") { e.preventDefault(); zoomAt(0.8, viewport.clientWidth / 2, viewport.clientHeight / 2); }
    else if (e.shiftKey && e.key === "!") fitAll();
    else if (e.key === "/" ) { e.preventDefault(); promptEl.focus(); }
  });
  function download(name, text, type) {
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([text], { type })); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }

  // ------------------------------------------------------------ persistence
  function scheduleSave() {
    clearTimeout(saveTimer); $("#saveState").textContent = "·";
    saveTimer = setTimeout(save, 800);
  }
  let saveChain = Promise.resolve();
  function save(force = false) {   // serialised: two saves racing on a new project would otherwise create two project ids
    saveChain = saveChain.then(() => doSave(force));
    return saveChain;
  }
  async function doSave(force) {
    if (!force && !project.screens.length && !project.id) { $("#saveState").textContent = ""; return; }
    try {
      const r = await fetch("/api/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(project) });
      const d = await r.json(); project.id = d.id; localStorage.setItem("ld.last", d.id); $("#saveState").textContent = "saved";
      setTimeout(() => { if ($("#saveState").textContent === "saved") $("#saveState").textContent = ""; }, 1500);
    } catch { $("#saveState").textContent = "save failed"; }
  }
  async function ensureProject() { if (!project.id) await save(true); return !!project.id; }   // uploads (assets, code) need a project id
  async function loadProject(id) {
    const r = await fetch("/api/projects/" + id); if (!r.ok) return false;
    project = await r.json(); project.camera ||= { x: 80, y: 60, z: 1 }; project.data ||= {}; project.designSystem ||= null; project.assets ||= []; project.code ||= null; project.screens.forEach(s => { s.versions ||= s.html ? [s.html] : []; });
    frames.forEach(el => el.remove()); frames.clear(); select(null); renderAll(); codeChanged(); localStorage.setItem("ld.last", id); return true;
  }
  function newProject() {
    project = blankProject();
    frames.forEach(el => el.remove()); frames.clear(); select(null); renderAll(); codeChanged(); localStorage.removeItem("ld.last");
  }
  async function showProjects() {
    const r = await fetch("/api/projects"); const { projects } = await r.json();
    const ul = $("#projectList"); ul.innerHTML = "";
    if (!projects.length) ul.innerHTML = "<li class='muted'>No saved projects yet.</li>";
    for (const p of projects) {
      const li = document.createElement("li"); li.className = p.id === project.id ? "current" : "";
      li.innerHTML = `<span>${esc(p.name)}</span><span class="meta">${p.screens} screen${p.screens === 1 ? "" : "s"} · ${new Date(p.updated * 1000).toLocaleString()}</span><button class="ic del" title="Delete">×</button>`;
      li.addEventListener("click", async e => {
        if (e.target.classList.contains("del")) { if (confirm(`Delete "${p.name}"?`)) { await fetch("/api/projects/" + p.id, { method: "DELETE" }); if (p.id === project.id) newProject(); showProjects(); } return; }
        await loadProject(p.id); $("#projects").close();
      });
      ul.appendChild(li);
    }
    $("#projects").showModal();
  }
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  $("#projectsBtn").addEventListener("click", showProjects);
  $("#projectsClose").addEventListener("click", () => $("#projects").close());
  $("#newProject").addEventListener("click", () => { newProject(); $("#projects").close(); });
  $("#importBtn").addEventListener("click", () => $("#importFile").click());
  $("#importFile").addEventListener("change", async e => {
    const f = e.target.files[0]; if (!f) return;
    try { const p = JSON.parse(await f.text()); p.id = null; p.code = null; project = p; project.screens.forEach(s => { s.versions ||= [s.html]; }); frames.forEach(el => el.remove()); frames.clear(); renderAll(); codeChanged(); scheduleSave(); $("#projects").close(); fitAll(); }   // attached code lives on the server, not in the JSON
    catch { toast("Not a valid project file"); }
    e.target.value = "";
  });

  // ------------------------------------------------------------ in-screen editor
  let elSel = null;        // { frame: screenId, info }
  let xdrag = null;        // cross-frame drag: { from, html, desc }
  let pendingDrag = null;  // frame id that started an in-frame drag
  function frameOfWindow(w) { for (const [id, el] of frames) if ($("iframe", el).contentWindow === w) return id; return null; }
  window.addEventListener("message", e => {
    const m = e.data; if (!m || !m.ld) return;
    const id = frameOfWindow(e.source); if (!id) return;
    const s = screenById(id), el = frames.get(id); if (!s || !el) return;
    switch (m.type) {
      case "ready": if (id === selected) postFrame(id, { type: "mode", edit: true }); if (playing && playing.id === id) postFrame(id, { type: "play" }); break;
      case "select": elSel = { frame: id, info: m.info }; showElTools(el, m.info); updateChip(); if (!$("#stylePop").classList.contains("hidden")) fillStylePop(m.info); break;
      case "deselect": if (elSel && elSel.frame === id) { elSel = null; } hideElTools(el); updateChip(); break;
      case "html": commitEdit(s, el, m.html, m.kind); break;
      case "undo": undoScreen(s); break;
      case "dragstart": pendingDrag = id; break;
      case "dragout": startXDrag(id, m.html, m.desc); break;
      case "dragback": cancelXDrag(false); break;
      case "dragmove": { const pt = framePoint(el, m.x, m.y); xdragMove(pt.x, pt.y); break; }
      case "dragend": pendingDrag = null; if (xdrag && m.x != null) { const pt = framePoint(el, m.x, m.y); xdragDrop(pt.x, pt.y); } break;
      case "navigate": playNavigate(m.target); break;
      case "saved": saveToMine(m.html, m.desc); break;
    }
  });
  function elClear(id) { if (elSel && elSel.frame === id) { elSel = null; updateChip(); } const el = frames.get(id); if (el) hideElTools(el); }
  function showElTools(el, info) { const t = $(".eltools", el); t.classList.remove("hidden"); $(".crumb", t).textContent = info.crumbs || info.desc; $("[data-act=edit]", t).style.display = info.isLeaf ? "" : "none"; }
  function hideElTools(el) { $(".eltools", el).classList.add("hidden"); hidePops(); }
  function hidePops() { $("#stylePop").classList.add("hidden"); $("#linkPop").classList.add("hidden"); }
  function commitEdit(s, el, html, kind) {
    s.html = html; s.versions.push(html); $("iframe", el).dataset.html = html;   // don't reload the iframe; it already shows the change
    if (s.spec) { s.spec = null; (s.specVersions ||= []).push(null); $(".eng", el).textContent = ""; if (!s._specWarned) { s._specWarned = true; toast("Manual edit: this screen is now plain HTML (AI edits will work on the HTML).", 4000); } }
    else if (s.specVersions) s.specVersions.push(null);
    const v = $(".ver", el); v.textContent = "v" + s.versions.length; v.style.display = s.versions.length > 1 ? "" : "none";
    scheduleSave(); drawArrows();
  }
  function undoScreen(s) {
    if (!s || s.versions.length < 2) { toast("Nothing to undo", 1200); return; }
    s.versions.pop(); if (s.specVersions) s.specVersions.pop();
    s.html = s.versions[s.versions.length - 1]; s.spec = s.specVersions ? (s.specVersions[s.specVersions.length - 1] || null) : null;
    renderFrame(s); scheduleSave(); toast("Undo", 900);
  }
  // toolbar actions (delegated; the template is cloned per frame)
  canvas.addEventListener("click", e => {
    const b = e.target.closest(".eltools button"); if (!b) return;
    const fr = e.target.closest(".frame"); const id = fr.dataset.id; e.stopPropagation();
    const act = b.dataset.act;
    if (act === "style") { toggleStylePop(fr); return; }
    if (act === "link") { toggleLinkPop(fr); return; }
    if (act === "ai") { promptEl.focus(); toast("Describe the change in the prompt bar", 1800); return; }
    if (act === "save") { postFrame(id, { type: "save-request" }); return; }
    const msg = { edit: { type: "edit" }, up: { type: "move", dir: -1 }, down: { type: "move", dir: 1 }, dup: { type: "dup" }, delete: { type: "delete" } }[act];
    if (msg) postFrame(id, msg);
  });
  // style popover
  function popAt(pop, fr) { const r = fr.getBoundingClientRect(), vr = viewport.getBoundingClientRect(); pop.style.left = Math.max(8, Math.min(vr.width - 316, r.left - vr.left)) + "px"; pop.style.top = Math.max(8, r.top - vr.top + 64 * project.camera.z) + "px"; }
  function toggleStylePop(fr) { const pop = $("#stylePop"); if (!pop.classList.contains("hidden")) { pop.classList.add("hidden"); return; } $("#linkPop").classList.add("hidden"); if (elSel) fillStylePop(elSel.info); popAt(pop, fr); pop.classList.remove("hidden"); }
  function fillStylePop(info) { const st = info.styles || {}; $$("#stylePop [data-s]").forEach(i => { const k = i.dataset.s; i.value = k === "background" ? (st.background === "rgba(0, 0, 0, 0)" ? "" : st.background || "") : (st[k] || ""); }); }
  $$("#stylePop [data-s]").forEach(i => i.addEventListener("input", () => { if (!elSel) return; postFrame(elSel.frame, { type: "style", styles: { [i.dataset.s]: i.value } }); }));
  $("#styleReset").addEventListener("click", () => { if (!elSel) return; postFrame(elSel.frame, { type: "style", styles: Object.fromEntries($$("#stylePop [data-s]").map(i => [i.dataset.s, ""])) }); });
  $("#styleDone").addEventListener("click", () => $("#stylePop").classList.add("hidden"));
  // link popover
  function toggleLinkPop(fr) {
    const pop = $("#linkPop"); if (!pop.classList.contains("hidden")) { pop.classList.add("hidden"); return; } $("#stylePop").classList.add("hidden");
    const sel = $("#linkTarget"); sel.innerHTML = '<option value="">— no link —</option>' + project.screens.filter(s => s.id !== fr.dataset.id).map(s => `<option value="${esc(s.title)}" ${elSel && elSel.info.link === s.title ? "selected" : ""}>${esc(s.title)}</option>`).join("");
    popAt(pop, fr); pop.classList.remove("hidden");
  }
  $("#linkTarget").addEventListener("change", e => { if (elSel) postFrame(elSel.frame, { type: "link", target: e.target.value }); drawArrows(); });
  $("#linkDone").addEventListener("click", () => $("#linkPop").classList.add("hidden"));
  // element-scoped AI edit
  async function iterateElement(s, instruction) {
    const el = frames.get(s.id), info = elSel.info; setLoading(s, true);
    const css = (s.html.match(/<style[^>]*>([\s\S]*?)<\/style>/i) || [, ""])[1];
    const root = (css.match(/:root\s*\{[^}]*\}/g) || []).join("\n");
    aborter = new AbortController(); setBusy(true, "Changing element");
    try {
      await streamPost("/api/iterate-element", { html: info.html, css: root || css.slice(0, 3000), instruction, width: s.width, design_system: project.designSystem || undefined, code: codeRef() }, ev => {
        if (ev.type === "context") noteContext(ev);
        else if (ev.type === "status") { $(".prog", el).dataset.phase = ev.status; }
        else if (ev.type === "partial") progBytes[s.id] = ev.chars || 0;
        else if (ev.type === "done") { postFrame(s.id, { type: "replace", html: ev.html }); if (ev.warning) toast("⚠ " + ev.warning, 6000); }
        else if (ev.type === "error") toast("Error: " + ev.message, 6000);
      }, aborter.signal);
    } catch (e) { if (e.name !== "AbortError") toast("Error: " + e.message, 6000); }
    finally { setLoading(s, false); setBusy(false); aborter = null; }
  }
  // cross-frame drag (element from screen A dropped into screen B)
  function startXDrag(from, html, desc) {
    xdrag = { from, html, desc }; document.body.classList.add("xdrag");
    const g = $("#dragGhost"); g.textContent = "⇢ " + desc; g.classList.remove("hidden");
  }
  function cancelXDrag(notify = true) { if (!xdrag) return; if (notify && xdrag.from !== "library") postFrame(xdrag.from, { type: "dragcancel" }); xdrag = null; document.body.classList.remove("xdrag"); $("#dragGhost").classList.add("hidden"); $$(".frame.droptarget").forEach(f => f.classList.remove("droptarget")); }
  // A drag that starts inside a screen keeps the mouse captured by that iframe, so the parent never sees the pointer:
  // the shim forwards it (dragmove/dragend in frame coordinates) and framePoint() maps it back to the page.
  function framePoint(el, x, y) { const f = $("iframe", el), r = f.getBoundingClientRect(), z = r.width / (f.offsetWidth || 1); return { x: r.left + x * z, y: r.top + y * z }; }
  function frameAt(x, y) { return document.elementsFromPoint(x, y).find(n => n.classList && n.classList.contains("frame")); }
  function xdragMove(x, y) {
    const g = $("#dragGhost"); g.style.left = x + "px"; g.style.top = y + "px";
    const fr = frameAt(x, y);
    $$(".frame.droptarget").forEach(f => { if (f !== fr) f.classList.remove("droptarget"); }); if (fr && fr.dataset.id !== xdrag.from) fr.classList.add("droptarget");
  }
  function xdragDrop(x, y) {
    const fr = frameAt(x, y);
    if (fr && fr.dataset.id !== xdrag.from) {
      const r = $("iframe", fr).getBoundingClientRect(), z = project.camera.z;
      postFrame(fr.dataset.id, { type: "drop", html: xdrag.html, x: (x - r.left) / z, y: (y - r.top) / z });
      if (xdrag.from !== "library") postFrame(xdrag.from, { type: "dragcancel" }); select(fr.dataset.id);
      xdrag = null; document.body.classList.remove("xdrag"); $("#dragGhost").classList.add("hidden"); fr.classList.remove("droptarget");
    } else cancelXDrag(true);
  }
  window.addEventListener("pointermove", e => {
    if (pendingDrag && !xdrag) { postFrame(pendingDrag, { type: "dragout-request" }); pendingDrag = null; }
    if (xdrag) xdragMove(e.clientX, e.clientY);
  });
  window.addEventListener("pointerup", e => { if (xdrag) xdragDrop(e.clientX, e.clientY); });
  window.addEventListener("keydown", e => { if (e.key === "Escape" && xdrag) cancelXDrag(true); });

  // ------------------------------------------------------------ flows: links, arrows, prototype player
  let playing = null;   // { id, history: [] }
  const LINK_RE = /data-link="([^"]*)"/g;
  function linksOf(s) { const out = new Set(); let m; LINK_RE.lastIndex = 0; while ((m = LINK_RE.exec(s.html || ""))) { const t = m[1].trim(); if (t && t !== s.title) out.add(t); } return [...out]; }
  function screenByTitle(t) { const n = (t || "").trim().toLowerCase(); return project.screens.find(s => s.title.trim().toLowerCase() === n); }
  function drawArrows() {
    const svg = $("#arrows"); if (!svg) return; let out = "", labels = "";
    for (const s of project.screens) {
      for (const t of linksOf(s)) {
        const d = screenByTitle(t); if (!d || d === s) continue;
        const sh = HEIGHTS[s.width] + 36, dh = HEIGHTS[d.width] + 36;
        const x1 = s.x + s.width, y1 = s.y + sh / 2, x2 = d.x, y2 = d.y + dh / 2;
        const dx = Math.max(60, Math.abs(x2 - x1) / 2);
        const back = x2 < x1 + 40;   // target is left of / overlapping source → loop over the top
        const path = back ? `M${x1},${s.y + 20} C${x1 + 80},${s.y - 120} ${x2 - 80},${d.y - 120} ${x2},${d.y + 20}` : `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
        out += `<path d="${path}" marker-end="url(#ah)"/>`;
      }
    }
    svg.innerHTML = `<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path class="hd" d="M0,0 L10,5 L0,10 z"/></marker></defs>` + out + labels;
    $("#playBtn").disabled = !project.screens.length;
  }
  function startPlay(s) {
    if (!s) return; playing = { id: s.id, history: [] };
    $("#player").classList.remove("hidden"); showPlayScreen(s);
  }
  function showPlayScreen(s) {
    playing.id = s.id; $("#playTitle").textContent = s.title;
    const f = $("#playFrame"), stage = $("#player .pstage"); const h = HEIGHTS[s.width];
    f.style.width = s.width + "px"; f.style.height = h + "px";
    const z = Math.min(1, (stage.clientWidth - 32) / s.width, (stage.clientHeight - 32) / h);
    f.style.transform = `scale(${z})`; f.style.transformOrigin = "center center";
    f.srcdoc = withEditor(s.html);
    $("#playBack").disabled = !playing.history.length;
  }
  function playNavigate(target) {
    if (!playing) return; const d = screenByTitle(target);
    if (!d) { toast(`No screen called “${target}” — link it or rename a screen`, 2500); return; }
    playing.history.push(playing.id); showPlayScreen(d);
  }
  window.addEventListener("message", e => {   // the player iframe isn't in `frames`; handle it here
    const m = e.data; if (!m || !m.ld || !playing) return;
    if (e.source !== $("#playFrame").contentWindow) return;
    if (m.type === "ready") $("#playFrame").contentWindow.postMessage({ ld: true, type: "play" }, "*");
    else if (m.type === "navigate") playNavigate(m.target);
  });
  $("#playBtn").addEventListener("click", () => { const s = (selected && screenById(selected)) || project.screens[0]; if (!s || !s.html) { toast("Nothing to play yet"); return; } startPlay(s); });
  $("#playBack").addEventListener("click", () => { if (!playing || !playing.history.length) return; const id = playing.history.pop(); const s = screenById(id); if (s) showPlayScreen(s); });
  $("#playClose").addEventListener("click", () => { playing = null; $("#player").classList.add("hidden"); $("#playFrame").srcdoc = ""; });
  window.addEventListener("keydown", e => { if (playing && e.key === "Escape") $("#playClose").click(); });

  // flow planner: journey / PRD → screens → generate each with link context
  const flowDlg = $("#flowDlg"); let plan = [];
  $("#flowBtn").addEventListener("click", () => { $("#flowMsg").textContent = ""; flowDlg.showModal(); });
  $("#flowCancel").addEventListener("click", () => flowDlg.close());
  $("#flowPlan").addEventListener("click", async () => {
    const text = $("#flowText").value.trim(); if (!text) { $("#flowMsg").textContent = "Describe the flow first."; return; }
    $("#flowMsg").textContent = "planning…"; $("#flowPlan").disabled = true;
    try {
      const r = await fetch("/api/plan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, max: +$("#flowMax").value || 6, code: codeRef() }) });
      const d = await r.json(); if (d.error) throw new Error(d.error);
      plan = d.screens; renderPlan(); $("#flowGo").disabled = !plan.length;
      $("#flowMsg").textContent = `${plan.length} screens planned` + (d.context ? ` · using ${d.context.files.length} file${d.context.files.length === 1 ? "" : "s"} from ${d.context.name}` : "");
      if (d.context) noteContext(d.context);
    } catch (e) { $("#flowMsg").textContent = "Planning failed: " + e.message; }
    finally { $("#flowPlan").disabled = false; }
  });
  function renderPlan() {
    const ul = $("#flowList"); ul.innerHTML = ""; $("#flowPlanOut").classList.remove("hidden");
    plan.forEach((p, i) => {
      const li = document.createElement("li");
      li.innerHTML = `<input value="${esc(p.title)}"><textarea rows="2">${esc(p.brief || "")}</textarea><span class="meta">→ ${esc((p.links || []).join(", ") || "no links")} · <a href="#" class="rm">remove</a></span>`;
      li.querySelector("input").addEventListener("input", e => { p.title = e.target.value; }); li.querySelector("textarea").addEventListener("input", e => { p.brief = e.target.value; });
      li.querySelector(".rm").addEventListener("click", e => { e.preventDefault(); plan.splice(i, 1); renderPlan(); });
      ul.appendChild(li);
    });
  }
  $("#flowGo").addEventListener("click", async () => {
    if (!plan.length || goBtn.disabled) return; flowDlg.close();
    const width = project.device, y = nextRowY(), group = uid();
    const batch = plan.map((p, i) => ({ id: uid(), title: p.title, brief: p.brief, x: i * (width + 120), y, width, html: "", versions: [], flow: { links: p.links || [], group } }));
    project.screens.push(...batch); batch.forEach(s => busyIds.add(s.id)); renderAll();
    batch.forEach((s, i) => { if (i) frames.get(s.id).classList.add("queued"); setLoading(s, true); }); fitAll();
    const flowText = $("#flowText").value;   // @mentions in the flow description apply to every screen of the flow
    aborter = new AbortController(); setBusy(true, `Generating flow (${batch.length} screens)`);
    try {
      for (let i = 0; i < batch.length; i++) {
        const s = batch[i], p = plan[i];
        frames.get(s.id)?.classList.remove("queued"); startedAt[s.id] = Date.now();
        const context = (projectContext([s]) || "") + "\n" + linkContext(s);
        $("#status").textContent = `Flow: ${i + 1}/${batch.length} · ${s.title}`;
        const ex = genExtras(); if (ex.code) ex.code.text = flowText;
        await streamPost("/api/generate", { brief: `${s.title}: ${s.brief}`, variants: 1, width, context, ...ex }, ev => handleEvent(ev, [s]), aborter.signal);
        if (aborter.signal.aborted) break;
      }
    } catch (e) { if (e.name !== "AbortError") toast("Error: " + e.message, 6000); }
    finally { finish(batch); drawArrows(); }
  });

  // ------------------------------------------------------------ library panel (components + assets)
  const lib = $("#library"); let libLoaded = false, libStyleTag = "";
  function showLib(on) { lib.classList.toggle("hidden", !on); viewport.classList.toggle("withlib", on); if (on && !libLoaded) loadLibrary(); if (on) renderAssets(); if (!on) document.body.classList.remove("libwide"); else if (!$("#libKits").classList.contains("hidden")) document.body.classList.add("libwide"); }
  $("#libBtn").addEventListener("click", () => showLib(lib.classList.contains("hidden")));
  $("#libClose").addEventListener("click", () => showLib(false));
  $$("#library [data-tab]").forEach(b => b.addEventListener("click", () => {
    const tab = b.dataset.tab; $$("#library [data-tab]").forEach(x => x.classList.toggle("on", x === b));
    $("#libComponents").classList.toggle("hidden", tab !== "components"); $("#libAssets").classList.toggle("hidden", tab !== "assets"); $("#libKits").classList.toggle("hidden", tab !== "kits");
    $("#library > .libhint").classList.toggle("hidden", tab === "kits"); document.body.classList.toggle("libwide", tab === "kits");
    if (tab === "kits" && !kitsLoaded) loadKits();
  }));
  async function loadLibrary() {
    const r = await fetch("/api/library", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ design_system: project.designSystem || undefined }) });
    const d = await r.json(); libStyleTag = d.style_tag; libLoaded = true;
    const grid = $("#libComponents"); grid.innerHTML = "";
    for (const it of d.items) {
      const card = document.createElement("div"); card.className = "libitem"; card.title = "Drag onto a screen";
      card.innerHTML = `<div class="thumb"><iframe sandbox="" loading="lazy"></iframe></div><div class="lbl">${esc(it.name)}</div>`;
      card.querySelector("iframe").srcdoc = `<!doctype html><html><head><style>${d.css}body{padding:12px;background:#fff}</style></head><body>${it.html}</body></html>`;
      wireLibDrag(card, () => libStyleTag + it.html, it.name);
      grid.appendChild(card);
    }
    renderSnippets();
  }
  function renderSnippets() {
    const grid = $("#snippetGrid"); grid.innerHTML = "";
    const comps = (project.designSystem && project.designSystem.components) || [];
    if (!comps.length) { grid.innerHTML = "<div class='muted small'>None yet.</div>"; return; }
    for (const c of comps) {
      const card = document.createElement("div"); card.className = "libitem";
      card.innerHTML = `<div class="thumb"><iframe sandbox="" loading="lazy"></iframe></div><div class="lbl">${esc(c.name || "snippet")}</div>`;
      card.querySelector("iframe").srcdoc = `<!doctype html><html><head><style>${(project.designSystem.css || "")}body{padding:12px;font-family:system-ui}</style></head><body>${c.html}</body></html>`;
      wireLibDrag(card, () => (project.designSystem.css ? `<style data-ld-lib="ds">${project.designSystem.css}</style>` : "") + c.html, c.name);
      grid.appendChild(card);
    }
  }
  function renderAssets() {
    const grid = $("#assetGrid"); grid.innerHTML = "";
    const assets = project.assets || [];
    if (!assets.length) grid.innerHTML = "<div class='muted small'>No assets yet. Upload your logo, icons, product shots.</div>";
    for (const a of assets) {
      const card = document.createElement("div"); card.className = "libitem";
      card.innerHTML = `<div class="thumb"><img src="${esc(a.url)}" alt=""></div><div class="lbl">${esc(a.name)}<button class="ic del" title="Remove">×</button></div>`;
      card.querySelector(".del").addEventListener("pointerdown", e => e.stopPropagation());
      card.querySelector(".del").addEventListener("click", async e => { e.stopPropagation(); await fetch(a.url, { method: "DELETE" }); project.assets = project.assets.filter(x => x !== a); renderAssets(); scheduleSave(); });
      const img = card.querySelector("img"); img.addEventListener("load", () => { a.w = img.naturalWidth; a.h = img.naturalHeight; });
      wireLibDrag(card, () => `<img src="${a.url}" alt="${esc(a.name)}" style="max-width:100%;height:auto;display:block">`, a.name);
      grid.appendChild(card);
    }
  }
  function wireLibDrag(card, htmlFn, desc) {
    card.setAttribute("draggable", "false"); card.querySelectorAll("img").forEach(i => i.setAttribute("draggable", "false"));
    card.addEventListener("dragstart", e => e.preventDefault());
    card.addEventListener("mousedown", e => { if (e.button === 0) e.preventDefault(); });   // no text selection / native drag
    card.addEventListener("pointerdown", e => {
      if (e.button !== 0 || e.target.closest("button")) return; e.preventDefault();
      const st = { x: e.clientX, y: e.clientY }; let moved = false;
      const mv = ev => { if (Math.hypot(ev.clientX - st.x, ev.clientY - st.y) > 6) { moved = true; window.removeEventListener("pointermove", mv); startXDrag("library", htmlFn(), desc); } };
      const up = () => {
        window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up);
        if (!moved) insertIntoSelected(htmlFn(), desc);      // plain click = insert at the end of the selected screen
      };
      window.addEventListener("pointermove", mv); window.addEventListener("pointerup", up);
    });
  }
  function insertIntoSelected(html, desc) {
    const s = selected && screenById(selected);
    if (!s || !s.html) { toast("Click a screen first, then click a component to add it (or drag it onto a screen).", 3500); return; }
    const el = frames.get(s.id), r = $("iframe", el).getBoundingClientRect(), z = project.camera.z;
    postFrame(s.id, { type: "drop", html, x: 20, y: Math.max(10, (r.height / z) - 40) });   // near the bottom of the visible area
    toast(`Added ${desc} to ${s.title}`, 1800);
  }

  // ------------------------------------------------------------ UI kits: browse open-source and your own element collections
  const kitState = { kit: "", cat: "", q: "", offset: 0, total: 0, dark: false, kits: [], catalog: [], seq: 0, busy: false, catalogOpen: false };
  let kitsLoaded = false;
  const kitPreviews = new Map();   // preview window → { it, frame }: drags can start inside a live preview
  const KIT_PREVIEW_JS = `<script>(()=>{const P=m=>parent.postMessage(Object.assign({ldkit:1},m),"*");let d=null;
addEventListener("dragstart",e=>e.preventDefault(),true);
addEventListener("mousedown",e=>{if(e.button===0)d={x:e.clientX,y:e.clientY,on:false}},true);
addEventListener("mousemove",e=>{if(!d)return;if(!d.on&&Math.hypot(e.clientX-d.x,e.clientY-d.y)>6){d.on=true;P({t:"start"})}if(d.on)P({t:"move",x:e.clientX,y:e.clientY})},true);
addEventListener("mouseup",e=>{if(d&&d.on)P({t:"end",x:e.clientX,y:e.clientY});d=null},true);
const fit=()=>{const w=document.getElementById("w");if(!w||w.dataset.fill)return;const s=Math.min(1,(innerWidth-14)/Math.max(1,w.scrollWidth),(innerHeight-14)/Math.max(1,w.scrollHeight));w.style.transform="scale("+s+")"};
addEventListener("load",fit);setTimeout(fit,300)})()<\/script>`;
  function kitPreviewDoc(it) {
    const dark = kitState.dark, fill = it.category === "Patterns";
    return `<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;height:100%}body{display:grid;place-items:center;overflow:hidden;background:${dark ? "#18181b" : "#f4f4f5"};color:${dark ? "#eee" : "#111"};font-family:system-ui,sans-serif}#w{display:inline-block;transform-origin:center}#w[data-fill]{position:fixed;inset:0}</style>`
      + `<style>${it.shared_css || ""}\n${it.css || ""}</style></head><body><div id="w"${fill ? " data-fill=1" : ""}>${it.html}</div>${KIT_PREVIEW_JS}</body></html>`;
  }
  function kitInsertHTML(it) {   // what lands in a screen: scoped CSS (deduplicated per element/kit by the editor) + the markup
    const credit = `/* ${it.name}${it.author ? " by " + it.author : ""} — ${it.kit_name}${it.license ? " (" + it.license + ")" : ""}${it.repo ? ", github.com/" + it.repo : ""} */`.replace(/\*\//g, "* /").replace(/^\/\* /, "/* ").replace(/\* \/$/, "*/");
    return (it.shared_css ? `<style data-ld-lib="kit-${it.kit_scope}">${credit}\n${it.shared_css}</style>` : "")
      + (it.css ? `<style data-ld-lib="${it.scope}">${credit}\n${it.css}</style>` : "") + it.html;
  }
  async function loadKits() {
    let d; try { d = await (await fetch("/api/kits")).json(); } catch { $("#kitMore").textContent = "Could not load kits."; return; }
    kitState.kits = d.installed; kitState.catalog = d.catalog; kitsLoaded = true;
    const total = d.installed.reduce((a, k) => a + k.count, 0);
    $("#kitSel").innerHTML = `<option value="">All kits (${total})</option>` + d.installed.map(k => `<option value="${esc(k.id)}">${esc(k.name)} (${k.count})</option>`).join("");
    if (!d.installed.some(k => k.id === kitState.kit)) kitState.kit = "";
    $("#kitSel").value = kitState.kit; $("#kitQ").placeholder = total ? `Search ${total.toLocaleString()} elements — e.g. glow button, toggle, loader` : "Add a kit to start browsing";
    kitCats(); renderKitCatalog();
    $("#kitCatalog").classList.toggle("hidden", !!d.installed.length && !kitState.catalogOpen);
    await kitSearch(true);
  }
  function kitCats() {
    const cats = {};
    for (const k of kitState.kits) if (!kitState.kit || k.id === kitState.kit) for (const [c, n] of Object.entries(k.categories || {})) cats[c] = (cats[c] || 0) + n;
    if (!cats[kitState.cat]) kitState.cat = "";
    $("#kitCat").innerHTML = `<option value="">All categories</option>` + Object.keys(cats).sort().map(c => `<option value="${esc(c)}">${esc(c)} (${cats[c]})</option>`).join("");
    $("#kitCat").value = kitState.cat;
  }
  async function kitSearch(reset) {
    if (reset) { kitState.offset = 0; kitState.seq++; kitState.busy = false; $("#kitGrid").innerHTML = ""; kitPreviews.clear(); }
    if (kitState.busy || !kitState.kits.length) { if (!kitState.kits.length) $("#kitMore").textContent = ""; return; }
    kitState.busy = true; const seq = kitState.seq;
    const qs = new URLSearchParams({ kit: kitState.kit, cat: kitState.cat, q: kitState.q, offset: kitState.offset, limit: 30 });
    try {
      const d = await (await fetch("/api/kits/items?" + qs)).json(); if (seq !== kitState.seq) return;
      kitState.total = d.total; for (const it of d.items) $("#kitGrid").appendChild(kitCard(it)); kitState.offset += d.items.length;
      $("#kitMore").textContent = !d.total ? "Nothing matches — try another word or category." : kitState.offset < d.total ? `${kitState.offset} of ${d.total.toLocaleString()} — scroll for more` : `${d.total.toLocaleString()} element${d.total === 1 ? "" : "s"}`;
    } catch { $("#kitMore").textContent = "Could not load elements."; }
    finally { if (seq === kitState.seq) kitState.busy = false; }
  }
  function kitCard(it) {
    const card = document.createElement("div"); card.className = "libitem kit"; card.title = `${it.name}${it.author ? " by " + it.author : ""} · ${it.category} · ${it.kit_name}`;
    card.innerHTML = `<div class="thumb"><iframe sandbox="allow-scripts" loading="lazy" title="${esc(it.name)}"></iframe></div><div class="lbl"><span class="nm">${esc(it.name)}</span><span class="by">${it.author ? "· " + esc(it.author) : ""}</span>`
      + `<button class="ic ins" title="Insert into the selected screen">＋</button><button class="ic star" title="Add to the design system: generated screens (HTML engine) reuse this exact markup">★</button>`
      + (it.kit === "mine" ? `<button class="ic del" title="Remove from My components">×</button>` : it.repo ? `<button class="ic src" title="Source: github.com/${esc(it.repo)} · ${esc(it.license)}">ⓘ</button>` : "") + `</div>`;
    const f = card.querySelector("iframe"); f.srcdoc = kitPreviewDoc(it);
    f.addEventListener("load", () => { if (f.contentWindow) kitPreviews.set(f.contentWindow, { it, frame: f }); });
    card.querySelector(".ins").addEventListener("click", e => { e.stopPropagation(); insertIntoSelected(kitInsertHTML(it), it.name); });
    card.querySelector(".star").addEventListener("click", e => { e.stopPropagation(); kitToDS(it); });
    const src = card.querySelector(".src"); if (src) src.addEventListener("click", e => { e.stopPropagation(); window.open(`https://github.com/${it.repo}`, "_blank", "noopener"); });
    const del = card.querySelector(".del"); if (del) del.addEventListener("click", async e => { e.stopPropagation(); await fetch(`/api/kits/mine/items/${it.id}`, { method: "DELETE" }); card.remove(); loadKits(); });
    wireLibDrag(card.querySelector(".lbl"), () => kitInsertHTML(it), it.name);   // the label strip drags/inserts; the preview drags via its own script
    return card;
  }
  window.addEventListener("message", e => {   // drags that start inside a live preview (the preview keeps the mouse; it forwards the pointer)
    const m = e.data; if (!m || !m.ldkit) return;
    const pv = kitPreviews.get(e.source); if (!pv) return;
    if (m.t === "start") { if (!xdrag) startXDrag("library", kitInsertHTML(pv.it), pv.it.name); return; }
    if (!xdrag) return;
    const r = pv.frame.getBoundingClientRect();
    if (m.t === "move") xdragMove(r.left + m.x, r.top + m.y); else if (m.t === "end") xdragDrop(r.left + m.x, r.top + m.y);
  });
  function kitToDS(it) {
    const ds = project.designSystem || (project.designSystem = { name: "", tokens: {}, components: [], css: "", notes: "", palette: [] });
    ds.components ||= [];
    if (ds.components.some(c => c.html === it.html)) { toast(`${it.name} is already in the design system`); return; }
    ds.components.push({ name: it.name, description: `${it.category} — ${it.kit_name}${it.author ? ", by " + it.author : ""}`, html: it.html });
    const add = [it.shared_css && !(ds.css || "").includes(it.kit_scope) ? it.shared_css : "", it.css || ""].filter(Boolean).join("\n");
    ds.css = [ds.css || "", add].filter(Boolean).join("\n");
    dsIndicator(); scheduleSave(); libLoaded = false;
    toast(`★ ${it.name} added to the design system (${ds.components.length} component${ds.components.length === 1 ? "" : "s"}). HTML-engine screens will reuse its markup; it is also under My assets → Brand snippets.`, 6000);
  }
  async function saveToMine(html, desc) {
    const name = prompt("Save to your library as:", desc || "component"); if (name === null) return;
    const r = await fetch("/api/kits/mine", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, html }) });
    const d = await r.json(); if (d.error) { toast(d.error, 5000); return; }
    toast(`⊕ Saved “${d.name}” to My components (Library → UI kits)`, 4000);
    if (kitsLoaded) loadKits();
  }
  function renderKitCatalog() {
    const own = kitState.kits.filter(k => !kitState.catalog.some(c => c.id === k.id));
    $("#kitCatList").innerHTML = kitState.catalog.map(c => `<div class="kitsrc"><span class="t">${esc(c.name)}</span><span>${c.installed ? `<button type="button" class="ghost" data-rm="${esc(c.id)}">Remove</button>` : `<button type="button" data-get="${esc(c.id)}">Download</button>`}</span><span class="d">${esc(c.desc)}</span><span class="m">${esc(c.license)} · <a href="${esc(c.url)}" target="_blank" rel="noopener">github.com/${esc(c.repo)}</a> · ${esc(c.size)}</span></div>`).join("")
      + own.map(k => `<div class="kitsrc"><span class="t">${esc(k.name)}</span><span><button type="button" class="ghost" data-rm="${esc(k.id)}">Remove</button></span><span class="m">${k.count} elements${k.source && k.source.repo ? " · github.com/" + esc(k.source.repo) : ""}</span></div>`).join("");
  }
  async function installKit(body, label) {
    const msg = $("#kitMsg"); msg.textContent = `${label}…`; msg.className = "small";
    try {
      const r = await fetch("/api/kits/install", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const d = await r.json(); if (d.error) throw new Error(d.error);
      const sk = Object.entries(d.skipped || {}).filter(([, n]) => n).map(([k, n]) => `${n} ${k === "tailwind" ? "Tailwind-only (need a build step)" : k}`).join(", ");
      msg.textContent = `✓ ${d.name}: ${d.count.toLocaleString()} elements imported${sk ? ` · skipped ${sk}` : ""}.`;
      kitState.kit = d.id; kitState.cat = ""; kitState.q = ""; $("#kitQ").value = ""; kitState.catalogOpen = false; await loadKits();   // show the new kit, unfiltered $("#kitCatalog").classList.add("hidden");
      toast(`✓ ${d.name}: ${d.count.toLocaleString()} elements — hover to preview, drag onto a screen`, 5000);
    } catch (e) { msg.textContent = "✗ " + e.message; msg.className = "small err-text"; }
  }
  $("#kitCatList").addEventListener("click", async e => {
    const g = e.target.closest("[data-get]"), rm = e.target.closest("[data-rm]");
    if (g) { const c = kitState.catalog.find(x => x.id === g.dataset.get); g.disabled = true; await installKit({ source: g.dataset.get }, `Downloading ${c.name} from GitHub and importing (${c.size})`); g.disabled = false; }
    if (rm && confirm("Remove this kit? Elements already on screens stay.")) { await fetch("/api/kits/" + rm.dataset.rm, { method: "DELETE" }); await loadKits(); kitState.catalogOpen = true; $("#kitCatalog").classList.remove("hidden"); }
  });
  $("#kitAddBtn").addEventListener("click", () => { kitState.catalogOpen = $("#kitCatalog").classList.contains("hidden"); $("#kitCatalog").classList.toggle("hidden", !kitState.catalogOpen); renderKitCatalog(); if (kitState.catalogOpen) $("#kitCatalog").scrollIntoView({ block: "start" }); });
  $("#kitImportRepo").addEventListener("click", () => { const repo = $("#kitRepo").value.trim(); if (repo) installKit({ repo }, `Downloading ${repo} and importing`); });
  $("#kitImportFolder").addEventListener("click", () => $("#kitFolder").click());
  $("#kitFolder").addEventListener("change", async e => {
    const fs = [...e.target.files]; e.target.value = ""; if (!fs.length) return;
    const root = (fs[0].webkitRelativePath || "").split("/")[0] || "My kit", files = [];
    for (const f of fs) {
      const p = f.webkitRelativePath || f.name;
      if (/(^|\/)(node_modules|\.git)\//.test(p) || f.size > 200000 || !/\.(html?|css)$|(^|\/)(licen[cs]e|copying)[^/]*$/i.test(p)) continue;
      files.push({ path: p, content: await f.text() });
    }
    if (!files.length) { $("#kitMsg").textContent = "No .html or .css files in that folder."; return; }
    installKit({ files, name: root }, `Importing ${files.length} files from ${root}`);
  });
  let kitTimer;
  $("#kitQ").addEventListener("input", e => { clearTimeout(kitTimer); kitTimer = setTimeout(() => { kitState.q = e.target.value.trim(); kitSearch(true); }, 200); });
  $("#kitSel").addEventListener("change", e => { kitState.kit = e.target.value; kitCats(); kitSearch(true); });
  $("#kitCat").addEventListener("change", e => { kitState.cat = e.target.value; kitSearch(true); });
  $("#kitBg").addEventListener("click", () => { kitState.dark = !kitState.dark; $("#kitBg").classList.toggle("on", kitState.dark); kitSearch(true); });
  new IntersectionObserver(es => { if (es.some(x => x.isIntersecting) && kitState.offset < kitState.total) kitSearch(false); }, { root: lib }).observe($("#kitMore"));
  $("#assetUpload").addEventListener("click", () => $("#assetFile").click());
  $("#assetFile").addEventListener("change", async e => {
    if (!(await ensureProject())) { toast("Could not create the project on the server — is lde still running?"); return; }
    for (const f of e.target.files) {
      const b64 = await new Promise(res => { const rd = new FileReader(); rd.onload = () => res(rd.result.split(",")[1]); rd.readAsDataURL(f); });
      const r = await fetch("/api/assets", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project: project.id, name: f.name, type: f.type || "image/png", data: b64 }) });
      const d = await r.json(); if (d.error) { toast(d.error, 4000); continue; }
      (project.assets ||= []).push({ name: d.name, url: d.url, type: d.type });
    }
    e.target.value = ""; renderAssets(); scheduleSave(); toast(`${project.assets.length} asset${project.assets.length === 1 ? "" : "s"} — generated screens will use them`);
  });

  // ------------------------------------------------------------ code context: attach a folder, reference its files with @path
  // Same filter as codebase.py (the server re-checks): text sources only; no vendored/build dirs, lockfiles, minified bundles or secrets.
  const CODE = {
    skipDirs: new Set("node_modules .git .hg .svn dist build out .next .nuxt .svelte-kit .output .vercel coverage __pycache__ .venv venv site-packages .tox .mypy_cache .pytest_cache .ruff_cache vendor target .idea .vscode .turbo .cache .parcel-cache Pods DerivedData .gradle obj .expo .angular storybook-static bower_components .yarn .pnpm-store .terraform".split(" ")),
    ext: new Set("js jsx ts tsx mjs cjs mts cts vue svelte astro html htm css scss sass less styl pcss json json5 jsonc md mdx txt yml yaml toml ini xml svg graphql gql prisma sql py rb go rs java kt kts swift dart php cs cshtml razor fs scala ex exs erb hbs handlebars ejs pug liquid njk twig jinja j2 lua r sh bash zsh ps1 bat tf proto csv".split(" ")),
    names: new Set(["dockerfile", "makefile", "procfile", "gemfile", "rakefile", "justfile", ".env.example", ".env.sample", ".env.template"]),
    skipNames: new Set(["package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "cargo.lock", "uv.lock", "composer.lock", "gemfile.lock", "bun.lockb", "pipfile.lock", "go.sum", ".ds_store", "secrets.yml", "secrets.yaml", "secrets.json", "credentials.json", "credentials.yml", "service-account.json", "id_rsa", "id_ed25519"]),
    maxFile: 256000, maxTotal: 8e6, maxFiles: 5000,
  };
  function codeKeep(path) {
    const parts = path.split("/"); if (parts.slice(0, -1).some(d => CODE.skipDirs.has(d))) return false;
    const name = parts[parts.length - 1].toLowerCase();
    if (CODE.skipNames.has(name) || /\.(min\.js|min\.css|map|pem|key|p12|pfx)$/.test(name)) return false;
    if (name === ".env" || (name.startsWith(".env.") && !CODE.names.has(name))) return false;
    const dot = name.lastIndexOf(".");
    return CODE.names.has(name) || (dot > 0 && CODE.ext.has(name.slice(dot + 1)));
  }
  function codeRef() { return project.code && project.id ? { project: project.id, pins: project.code.pinned || [] } : undefined; }
  let codeDirs = [], codeSizes = new Map();
  function codeChanged() {   // project.code changed: chip, 📎 button, completion index
    const c = project.code;
    codeDirs = []; codeSizes = new Map();
    if (c) {
      const dirs = new Set();
      for (const f of c.files) { codeSizes.set(f.path, f.size); const p = f.path.split("/"); for (let i = 1; i < p.length; i++) dirs.add(p.slice(0, i).join("/") + "/"); }
      codeDirs = [...dirs];
      c.pinned = (c.pinned || []).filter(p => codeSizes.has(p));
    }
    $("#codeChip").classList.toggle("hidden", !c); $("#attachBtn").classList.toggle("on", !!c);
    $("#attachBtn").title = c ? `Code: ${c.name} — click to see files and pins; type @ in the prompt to reference one` : "Attach a code folder so prompts can reference your existing files with @ (or drop a folder anywhere)";
    if (c) { $("#codeName").textContent = c.name; $("#codeMeta").textContent = `${c.files.length} files${c.pinned.length ? ` · ${c.pinned.length} pinned` : ""} · type @`; }
  }
  async function readCodeFiles(items) {   // [{file, path}] → text contents that pass the filter, within the caps
    const files = []; let total = 0, skipped = 0, tooMuch = 0;
    for (const { file, path } of items) {
      if (!codeKeep(path) || file.size > CODE.maxFile) { skipped++; continue; }
      if (files.length >= CODE.maxFiles || total + file.size > CODE.maxTotal) { tooMuch++; continue; }
      let text; try { text = await file.text(); } catch { skipped++; continue; }
      if (text.includes("\u0000")) { skipped++; continue; }
      files.push({ path, content: text }); total += text.length;
    }
    return { files, skipped, tooMuch };
  }
  async function attachCode(items, add = false) {
    if (!items.length) return;
    const first = items[0].path.split("/")[0];
    const root = items.every(it => it.path.startsWith(first + "/")) ? first : null;   // a picked/dropped folder: strip its own name
    const rel = root ? items.map(it => ({ file: it.file, path: it.path.slice(root.length + 1) })) : items;
    toast(`Reading ${rel.length} file${rel.length === 1 ? "" : "s"}…`, 60000);
    const { files, skipped, tooMuch } = await readCodeFiles(rel);
    if (!files.length) { toast("No source files there — only text files are read (node_modules, build output, binaries, lockfiles and .env are skipped).", 7000); return; }
    if (!(await ensureProject())) { toast("Could not create the project on the server — is lde still running?"); return; }
    let d;
    try {
      const r = await fetch("/api/code", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project: project.id, name: root || (add && project.code && project.code.name) || "code", files, add: add && !!project.code }) });
      d = await r.json();
    } catch (e) { toast("Upload failed: " + e.message, 6000); return; }
    if (d.error) { toast(d.error, 7000); return; }
    const keepPins = add && project.code ? project.code.pinned || [] : [];
    project.code = { name: d.name, files: d.files, bytes: d.bytes, pinned: [...new Set([...keepPins, ...(add && project.code ? [] : d.style || [])])] };
    codeChanged(); scheduleSave(); if ($("#codeDlg").open) renderCodeList();
    const skip = skipped + (d.skipped || 0);
    toast(`📁 ${d.name}: ${d.files.length} files attached${skip ? ` (${skip} non-source skipped)` : ""}.` +
      (tooMuch ? ` ⚠ ${tooMuch} more did not fit the ${kb(CODE.maxTotal)} limit — attach a subfolder like src/ instead.` : "") +
      (project.code.pinned.length ? `\nPinned as style context: ${project.code.pinned.join(", ")}.` : "") +
      `\nType @ in the prompt to reference a file, e.g. @${(d.files.find(f => /\.(tsx|jsx|vue|svelte|html)$/.test(f.path)) || d.files[0]).path}`, tooMuch ? 12000 : 9000);
  }
  async function detachCode() {
    if (!project.code || !confirm(`Detach “${project.code.name}”? Prompts will stop seeing its files.`)) return;
    if (project.id) await fetch("/api/code/" + project.id, { method: "DELETE" }).catch(() => {});
    project.code = null; codeChanged(); scheduleSave(); $("#codeDlg").close();
  }
  $("#attachBtn").addEventListener("click", () => project.code ? openCodeDlg() : $("#codeFolder").click());
  $("#codeChip").addEventListener("click", e => { if (!e.target.closest("#codeDetach")) openCodeDlg(); });
  $("#codeDetach").addEventListener("click", e => { e.stopPropagation(); detachCode(); });
  $("#codeFolder").addEventListener("change", e => { const fs = [...e.target.files]; e.target.value = ""; attachCode(fs.map(f => ({ file: f, path: f.webkitRelativePath || f.name }))); });
  $("#codeFiles").addEventListener("change", e => { const fs = [...e.target.files]; e.target.value = ""; attachCode(fs.map(f => ({ file: f, path: f.name })), true); });
  // dialog: file list, pins
  function openCodeDlg() { $("#codeFilter").value = ""; renderCodeList(); $("#codeDlg").showModal(); }
  function renderCodeList() {
    const c = project.code, ul = $("#codeList"); if (!c) { ul.innerHTML = ""; return; }
    const pins = new Set(c.pinned);
    $("#codeSummary").innerHTML = `<b>${esc(c.name)}</b> · ${c.files.length} files · ${kb(c.bytes)} · ${pins.size} pinned`;
    $("#codeBudget").textContent = kb(cfg.code_budget_resolved || 0);
    const q = $("#codeFilter").value.trim().toLowerCase();
    const list = c.files.filter(f => !q || f.path.toLowerCase().includes(q)).sort((a, b) => (pins.has(b.path) - pins.has(a.path)) || a.path.localeCompare(b.path));
    ul.innerHTML = list.slice(0, 400).map(f => `<li class="${pins.has(f.path) ? "pinned" : ""}"><label title="Pin: include in every prompt"><input type="checkbox" data-p="${esc(f.path)}" ${pins.has(f.path) ? "checked" : ""}><span class="p">${esc(f.path)}</span></label><span class="meta">${kb(f.size)}</span></li>`).join("")
      + (list.length > 400 ? `<li class="muted">… ${list.length - 400} more — type to filter</li>` : "") + (!list.length ? `<li class="muted">No file matches.</li>` : "");
  }
  $("#codeFilter").addEventListener("input", renderCodeList);
  $("#codeList").addEventListener("change", e => {
    const p = e.target.dataset.p; if (!p || !project.code) return;
    const pins = new Set(project.code.pinned); e.target.checked ? pins.add(p) : pins.delete(p); project.code.pinned = [...pins];
    e.target.closest("li").classList.toggle("pinned", e.target.checked);
    $("#codeSummary").innerHTML = `<b>${esc(project.code.name)}</b> · ${project.code.files.length} files · ${kb(project.code.bytes)} · ${pins.size} pinned`;
    codeChanged(); scheduleSave();
  });
  $("#codeRemove").addEventListener("click", detachCode);
  $("#codeReplace").addEventListener("click", () => $("#codeFolder").click());
  $("#codeAddFiles").addEventListener("click", () => $("#codeFiles").click());
  $("#codeDone").addEventListener("click", () => $("#codeDlg").close());
  // drop a folder (or files) anywhere on the window
  let fileDrag = 0;
  const hasFiles = e => [...((e.dataTransfer && e.dataTransfer.types) || [])].includes("Files");
  const endFileDrag = () => { fileDrag = 0; document.body.classList.remove("filedrag"); $("#dropHint").classList.add("hidden"); };
  window.addEventListener("dragenter", e => { if (!hasFiles(e)) return; fileDrag++; document.body.classList.add("filedrag"); $("#dropHint").classList.remove("hidden"); });
  window.addEventListener("dragover", e => { if (hasFiles(e)) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; } });
  window.addEventListener("dragleave", e => { if (hasFiles(e) && --fileDrag <= 0) endFileDrag(); });
  window.addEventListener("drop", async e => {
    if (!hasFiles(e)) return;
    e.preventDefault(); endFileDrag();   // never let the browser navigate to the dropped file
    const pending = droppedEntries(e.dataTransfer);   // must read the DataTransfer synchronously, inside the event
    const other = document.querySelector("dialog[open]:not(#codeDlg)");
    if (other) { toast("Close the dialog first, then drop the folder to attach it as code context."); return; }
    const { items, dirs } = await pending;
    attachCode(items, !(dirs === 1));   // one folder replaces the attached code; loose files are added to it
  });
  async function droppedEntries(dt) {
    const entries = [...dt.items].filter(i => i.kind === "file").map(i => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null));
    const plain = [...dt.files];
    if (!entries.some(Boolean)) return { items: plain.map(f => ({ file: f, path: f.name })), dirs: 0 };
    const items = []; let dirs = 0, seen = 0;
    const walk = async (entry, prefix) => {
      if (++seen > 60000) return;
      if (entry.isFile) { const f = await new Promise((res, rej) => entry.file(res, rej)).catch(() => null); if (f) items.push({ file: f, path: prefix + entry.name }); return; }
      if (CODE.skipDirs.has(entry.name)) return;   // don't even walk node_modules & co
      const rd = entry.createReader();
      for (;;) { const batch = await new Promise((res, rej) => rd.readEntries(res, rej)).catch(() => []); if (!batch.length) break; for (const c of batch) await walk(c, prefix + entry.name + "/"); }
    };
    for (const en of entries) if (en) { if (en.isDirectory) dirs++; await walk(en, ""); }
    return { items, dirs };
  }
  // @ completion in the prompt
  const mentionPop = $("#mentionPop"); let mention = null;   // { start, query, items, idx }
  const mentionOpen = () => !!mention && !mentionPop.classList.contains("hidden");
  function hideMention() { mention = null; mentionPop.classList.add("hidden"); }
  function mentionAt() {
    if (!project.code || promptEl.selectionStart !== promptEl.selectionEnd) return null;
    const pos = promptEl.selectionStart, m = promptEl.value.slice(0, pos).match(/(^|[\s(\[{"'`])@([^\s@]*)$/);
    return m ? { start: pos - m[2].length - 1, query: m[2] } : null;
  }
  function mentionItems(q) {
    const ql = q.toLowerCase(), out = [];
    const score = (path, dir) => {
      const pl = path.toLowerCase(); if (pl === ql) return -1;
      const base = (dir ? pl.slice(0, -1) : pl).split("/").pop();
      if (!ql) return path.replace(/\/$/, "").includes("/") ? -1 : dir ? 0 : 1;   // empty query: top-level folders, then root files
      return pl.startsWith(ql) ? 0 : base.startsWith(ql) ? 1 : base.includes(ql) ? 2 : pl.includes(ql) ? 3 : -1;
    };
    for (const d of codeDirs) { const s = score(d, true); if (s >= 0) out.push({ path: d, dir: true, s }); }
    for (const f of project.code.files) { const s = score(f.path, false); if (s >= 0) out.push({ path: f.path, dir: false, s }); }
    const depth = p => p.replace(/\/$/, "").split("/").length;
    return out.sort((a, b) => a.s - b.s || depth(a.path) - depth(b.path) || a.path.length - b.path.length || a.path.localeCompare(b.path)).slice(0, 10);
  }
  function showMention() {
    const at = mentionAt(); if (!at) { hideMention(); return; }
    const same = mention && mention.query === at.query;
    mention = { ...at, items: mentionItems(at.query), idx: same ? mention.idx : 0 };
    renderMention();
  }
  function renderMention() {
    const pins = new Set(project.code.pinned || []);
    mentionPop.innerHTML = mention.items.length ? mention.items.map((it, i) => {
      const p = it.dir ? it.path.slice(0, -1) : it.path, k = p.lastIndexOf("/");
      const tag = it.dir ? `folder · ${project.code.files.filter(f => f.path.startsWith(it.path)).length} files` : pins.has(it.path) ? "pinned" : kb(codeSizes.get(it.path));
      return `<button type="button" role="option" data-i="${i}" class="${i === mention.idx ? "on" : ""}"><span class="base">${esc(p.slice(k + 1))}${it.dir ? "/" : ""}</span><span class="dir">${esc(k >= 0 ? p.slice(0, k + 1) : "")}</span><span class="tag">${tag}</span></button>`;
    }).join("") : `<div class="empty">No file matching “${esc(mention.query)}” in ${esc(project.code.name)}</div>`;
    mentionPop.classList.remove("hidden");
    const on = mentionPop.querySelector(".on"); if (on) on.scrollIntoView({ block: "nearest" });
  }
  function pickMention(i) {
    const it = mention && mention.items[i]; if (!it) return;
    const v = promptEl.value, end = mention.start + 1 + mention.query.length, ins = "@" + it.path + (it.dir ? "" : " ");
    promptEl.value = v.slice(0, mention.start) + ins + v.slice(end);
    const caret = mention.start + ins.length; promptEl.focus(); promptEl.setSelectionRange(caret, caret); autosize();
    mention = null; if (it.dir) showMention(); else hideMention();   // a folder drills down; type a space to reference the whole folder
  }
  promptEl.addEventListener("input", showMention);
  promptEl.addEventListener("click", showMention);
  promptEl.addEventListener("keyup", e => { if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) showMention(); });
  promptEl.addEventListener("blur", () => setTimeout(() => { if (document.activeElement !== promptEl) hideMention(); }, 120));
  mentionPop.addEventListener("pointerdown", e => e.preventDefault());   // keep focus (and the caret) in the prompt
  mentionPop.addEventListener("click", e => { const b = e.target.closest("button[data-i]"); if (b) pickMention(+b.dataset.i); });

  // ------------------------------------------------------------ design system
  const dsDlg = $("#dsDlg");
  let dsDraft = null;   // working copy while the dialog is open
  function dsIndicator() {
    const ds = project.designSystem, d = Object.keys(project.data || {}).length;
    $("#dsLabel").textContent = ds ? (ds.name || "Design system") : "Design system"; $("#dsBtn").classList.toggle("on", !!ds);
    $("#dataLabel").textContent = d ? `Data (${d})` : "Data"; $("#dataBtn").classList.toggle("on", d > 0);
  }
  function openDS() {
    dsDraft = JSON.parse(JSON.stringify(project.designSystem || { name: "", tokens: {}, components: [], css: "", notes: "", palette: [] }));
    $("#dsName").value = dsDraft.name || ""; $("#dsSource").value = ""; $("#dsMsg").textContent = ""; $("#dsNotes").value = dsDraft.notes || ""; $("#dsCss").value = dsDraft.css || "";
    dsFillTokens(dsDraft.tokens || {}); dsRenderPalette(dsDraft.palette || []); dsRenderComps();
    dsDlg.showModal();
  }
  function dsFillTokens(t) { $$("#dsTokens [data-t]").forEach(i => { i.value = t[i.dataset.t] ?? ""; }); }
  function dsReadTokens() { const t = {}; $$("#dsTokens [data-t]").forEach(i => { if (i.value !== "") t[i.dataset.t] = i.type === "number" ? +i.value : i.value; }); return t; }
  function dsRenderPalette(pal) {
    const el = $("#dsPalette"); el.innerHTML = "";
    for (const c of pal.slice(0, 40)) {
      const sp = document.createElement("span"); sp.innerHTML = `<i style="background:${esc(c.value)}"></i>${esc(c.name)}`; sp.title = `${c.value} — click to set as primary, ⇧click for bg, ⌥click for text`;
      sp.addEventListener("click", e => { const t = dsReadTokens(); t[e.shiftKey ? "bg" : e.altKey ? "text" : "primary"] = c.value; dsFillTokens(t); });
      el.appendChild(sp);
    }
  }
  function dsRenderComps() {
    const box = $("#dsComps"); box.innerHTML = "";
    (dsDraft.components || []).forEach((c, i) => {
      const d = document.createElement("div"); d.className = "comp";
      d.innerHTML = `<input placeholder="name (Button, Card…)" value="${esc(c.name || "")}"><input placeholder="when to use it" value="${esc(c.description || "")}"><button type="button" class="ic del" title="Remove">×</button><textarea rows="3" placeholder="<button class=&quot;btn btn-primary&quot;>Label</button>">${esc(c.html || "")}</textarea>`;
      const [name, desc] = d.querySelectorAll("input"), ta = d.querySelector("textarea");
      name.addEventListener("input", () => c.name = name.value); desc.addEventListener("input", () => c.description = desc.value); ta.addEventListener("input", () => c.html = ta.value);
      d.querySelector(".del").addEventListener("click", () => { dsDraft.components.splice(i, 1); dsRenderComps(); });
      box.appendChild(d);
    });
  }
  $("#dsAddComp").addEventListener("click", () => { (dsDraft.components ||= []).push({ name: "", description: "", html: "" }); dsRenderComps(); });
  $("#dsFetch").addEventListener("click", async () => {
    const url = $("#dsUrl").value.trim(); if (!url) { $("#dsMsg").textContent = "Enter a URL first."; return; }
    $("#dsMsg").textContent = "fetching…";
    const r = await fetch("/api/ds/fetch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }) });
    const d = await r.json(); if (d.error) { $("#dsMsg").textContent = d.error; return; }
    if (!$("#dsName").value && d.title) $("#dsName").value = d.title;
    $("#dsSource").value = d.source_css || ""; $("#dsKind").value = "css";
    const cur = dsReadTokens(); dsFillTokens({ ...cur, ...d.tokens }); dsDraft.palette = d.palette || []; dsRenderPalette(dsDraft.palette);
    if (d.css && !$("#dsCss").value) $("#dsCss").value = d.css;
    $("#dsMsg").textContent = `${d.sheets.length} stylesheet${d.sheets.length === 1 ? "" : "s"} · ${Object.keys(d.tokens).length} tokens, ${(d.palette || []).length} colors found — adjust below`;
  });
  $("#dsParse").addEventListener("click", async () => {
    const text = $("#dsSource").value; if (!text.trim()) { $("#dsMsg").textContent = "Paste something first."; return; }
    $("#dsMsg").textContent = "parsing…";
    const r = await fetch("/api/ds/parse", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, kind: $("#dsKind").value }) });
    const d = await r.json(); if (d.error) { $("#dsMsg").textContent = d.error; return; }
    const cur = dsReadTokens(); dsFillTokens({ ...cur, ...d.tokens }); dsDraft.palette = d.palette || []; dsRenderPalette(dsDraft.palette);
    if (d.css && !$("#dsCss").value) $("#dsCss").value = d.css;
    if (d.kind === "designmd") { if (d.name && !$("#dsName").value) $("#dsName").value = d.name; if (d.notes && !$("#dsNotes").value) $("#dsNotes").value = d.notes; }
    if (d.kind === "html") { const m = text.match(/<body[^>]*>([\s\S]*)<\/body>/i); if (m && !(dsDraft.components || []).length) { (dsDraft.components ||= []).push({ name: "Reference page", description: "match this markup style", html: m[1].trim().slice(0, 4000) }); dsRenderComps(); } }
    $("#dsMsg").textContent = `${d.kind}: ${Object.keys(d.tokens).length} tokens, ${(d.palette || []).length} colors found — adjust below`;
  });
  $("#dsSave").addEventListener("click", async () => {
    dsDraft.name = $("#dsName").value.trim(); dsDraft.tokens = dsReadTokens(); dsDraft.notes = $("#dsNotes").value.trim(); dsDraft.css = $("#dsCss").value.trim();
    dsDraft.components = (dsDraft.components || []).filter(c => c.html && c.html.trim());
    project.designSystem = dsDraft; dsDlg.close(); dsIndicator(); scheduleSave(); libLoaded = false; if (!lib.classList.contains("hidden")) loadLibrary();
    await rerenderSpecScreens(); toast("Design system saved" + (project.designSystem.name ? ": " + project.designSystem.name : ""));
  });
  $("#dsClear").addEventListener("click", async () => { project.designSystem = null; dsDlg.close(); dsIndicator(); scheduleSave(); await rerenderSpecScreens(); });
  $("#dsCancel").addEventListener("click", () => dsDlg.close());
  $("#dsBtn").addEventListener("click", openDS);
  async function rerenderSpecScreens() {
    const specScreens = project.screens.filter(s => s.spec);
    for (const s of specScreens) {
      try {
        const r = await fetch("/api/render", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ spec: s.spec, width: s.width, design_system: project.designSystem || undefined, data: project.data }) });
        const d = await r.json(); if (d.html) { s.html = d.html; s.versions[s.versions.length - 1] = d.html; setFrameHTML(frames.get(s.id), d.html); }
      } catch {}
    }
    if (specScreens.length) scheduleSave();
  }

  // ------------------------------------------------------------ data sources
  const dataDlg = $("#dataDlg");
  function parseCSV(text) {
    const delim = text.indexOf("\t") >= 0 && text.indexOf(",") < 0 ? "\t" : ",";
    const rows = []; let row = [], cell = "", q = false;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (q) { if (ch === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else q = false; } else cell += ch; }
      else if (ch === '"') q = true;
      else if (ch === delim) { row.push(cell); cell = ""; }
      else if (ch === "\n" || ch === "\r") { if (ch === "\r" && text[i + 1] === "\n") i++; row.push(cell); rows.push(row); row = []; cell = ""; }
      else cell += ch;
    }
    if (cell !== "" || row.length) { row.push(cell); rows.push(row); }
    const [head, ...body] = rows.filter(r => r.some(c => c.trim() !== ""));
    if (!head) return [];
    return body.map(r => Object.fromEntries(head.map((h, i) => [h.trim(), (r[i] ?? "").trim()])));
  }
  function dataRenderList() {
    const ul = $("#dataList"); ul.innerHTML = "";
    const names = Object.keys(project.data || {});
    if (!names.length) ul.innerHTML = "<li class='muted'>No sources yet.</li>";
    for (const n of names) {
      const rows = project.data[n]; const cols = Array.isArray(rows) && rows[0] && typeof rows[0] === "object" ? Object.keys(rows[0]) : [];
      const li = document.createElement("li"); li.innerHTML = `<b>${esc(n)}</b><span class="meta">${Array.isArray(rows) ? rows.length : 1} rows · ${esc(cols.slice(0, 6).join(", "))}${cols.length > 6 ? "…" : ""}</span><button class="ic del" title="Remove">×</button>`;
      li.querySelector(".del").addEventListener("click", () => { delete project.data[n]; dataRenderList(); dsIndicator(); scheduleSave(); });
      ul.appendChild(li);
    }
  }
  $("#dataAdd").addEventListener("click", () => {
    const name = $("#dataName").value.trim().replace(/\s+/g, "_"), text = $("#dataSource").value.trim(); let kind = $("#dataKind").value;
    if (!name || !text) { $("#dataMsg").textContent = "Need a name and some rows."; return; }
    if (kind === "auto") kind = /^[\[{]/.test(text) ? "json" : "csv";
    let rows;
    try { rows = kind === "json" ? JSON.parse(text) : parseCSV(text); } catch (e) { $("#dataMsg").textContent = "Could not parse: " + e.message; return; }
    if (rows && !Array.isArray(rows) && typeof rows === "object") rows = rows.rows || rows.data || rows.items || [rows];
    if (!Array.isArray(rows) || !rows.length) { $("#dataMsg").textContent = "No rows found."; return; }
    if (rows.length > 500) rows = rows.slice(0, 500);
    (project.data ||= {})[name] = rows; $("#dataName").value = ""; $("#dataSource").value = ""; $("#dataMsg").textContent = `added ${name} (${rows.length} rows)`;
    dataRenderList(); dsIndicator(); scheduleSave(); rerenderSpecScreens();
  });
  $("#dataBtn").addEventListener("click", () => { dataRenderList(); $("#dataMsg").textContent = ""; dataDlg.showModal(); });
  $("#dataClose").addEventListener("click", () => dataDlg.close());

  // ------------------------------------------------------------ settings
  const dlg = $("#settings"), form = $("#settingsForm");
  async function loadConfig() {
    cfg = await (await fetch("/api/config")).json();
    $("#modelLabel").textContent = cfg.model || "no model"; $("#modelDot").className = "dot " + (cfg.model ? "ok" : "bad");
    $("#variants").value = String(cfg.variants || 3);
    $("#engine").value = cfg.mode || "auto";
    $("#engine").title = `auto currently resolves to: ${cfg.resolved_mode || "html"}`;
  }
  function openSettings() {
    const sel = $("#providerSel"); sel.innerHTML = Object.keys(cfg.presets).map(k => `<option ${k === cfg.provider ? "selected" : ""}>${k}</option>`).join("");
    form.base_url.value = cfg.base_url || ""; form.model.value = cfg.model || ""; form.api_key.value = "";
    form.temperature.value = cfg.temperature ?? 0.8; form.max_tokens.value = cfg.max_tokens ?? 8192; form.allow_cdn.checked = !!cfg.allow_cdn; form.effort.value = cfg.effort || "medium";
    form.code_budget.value = Math.round((+cfg.code_budget || 0) / 1000); $("#codeBudgetAuto").textContent = kb(cfg.code_budget_auto || 0);
    $("#keyState").textContent = cfg.api_key_set ? `current: ${cfg.api_key}` : "none set"; $("#modelsMsg").textContent = ""; $("#modelList").innerHTML = "";
    dlg.showModal();
  }
  $("#providerSel").addEventListener("change", e => { const p = cfg.presets[e.target.value]; if (p) { if (p.base_url) form.base_url.value = p.base_url; form.model.value = p.model || ""; } });
  $("#fetchModels").addEventListener("click", async () => {
    $("#modelsMsg").textContent = "fetching…";
    // save endpoint first so the server queries the right place
    await postConfig({ provider: form.provider.value, base_url: form.base_url.value, api_key: form.api_key.value || undefined });
    const r = await fetch("/api/models"); const d = await r.json();
    if (d.error) { $("#modelsMsg").textContent = d.error; return; }
    $("#modelList").innerHTML = d.models.map(m => `<option value="${esc(m)}">`).join("");
    $("#modelsMsg").textContent = `${d.models.length} models — start typing in the Model field`;
    if (!form.model.value && d.models.length) form.model.value = d.models[0];
  });
  $("#testModel").addEventListener("click", async () => {
    $("#modelsMsg").textContent = "testing…";
    await postConfig({ provider: form.provider.value, base_url: form.base_url.value, model: form.model.value, api_key: form.api_key.value || undefined });
    const t0 = Date.now();
    try {
      const r = await fetch("/api/test", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); const d = await r.json();
      $("#modelDot").className = "dot " + (d.ok ? "ok" : "bad");
      $("#modelsMsg").textContent = d.ok ? `✓ ${cfg.model} answered “${d.reply}” in ${d.secs}s · engine auto → ${d.mode}. Save to start.` : "✗ " + d.error;
    } catch (e) { $("#modelsMsg").textContent = "✗ " + e.message + ` (${((Date.now() - t0) / 1000).toFixed(1)}s)`; }
  });
  async function postConfig(body) {
    const r = await fetch("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    cfg = await r.json(); $("#modelLabel").textContent = cfg.model || "no model"; $("#modelDot").className = "dot " + (cfg.model ? "ok" : "bad");
  }
  form.addEventListener("submit", async e => {
    e.preventDefault();
    await postConfig({ provider: form.provider.value, base_url: form.base_url.value, model: form.model.value, api_key: form.api_key.value || undefined,
      temperature: +form.temperature.value, max_tokens: +form.max_tokens.value, allow_cdn: form.allow_cdn.checked, effort: form.effort.value, variants: +$("#variants").value,
      code_budget: Math.max(0, Math.round(+form.code_budget.value || 0)) * 1000 });
    dlg.close(); toast(`Using ${cfg.model} @ ${cfg.base_url}`);
  });
  $("#settingsBtn").addEventListener("click", openSettings);
  $("#settingsCancel").addEventListener("click", () => dlg.close());

  // ------------------------------------------------------------ boot
  (async () => {
    await loadConfig();
    const qp = new URLSearchParams(location.search);
    const last = qp.get("project") || localStorage.getItem("ld.last");
    if (!(last && await loadProject(last))) renderAll();
    if (qp.get("fit")) setTimeout(fitAll, 400);
    const firstRun = () => { $("#firstRun").classList.remove("hidden"); if (!dlg.open) openSettings(); };
    if (!cfg.model) firstRun();
    else if (!cfg.saved) {   // defaults only (Ollama): check it answers before the user types a prompt into a dead endpoint
      fetch("/api/models").then(r => r.json()).then(d => { if (d.error) { firstRun(); $("#modelsMsg").textContent = d.error; $("#modelDot").className = "dot bad"; $("#settingsBtn").title = d.error; } }).catch(() => {});
    }
    promptEl.focus();
  })();
})();
