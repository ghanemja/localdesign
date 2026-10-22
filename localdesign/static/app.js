/* localdesign — canvas app. Vanilla JS, no build step. */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const uid = () => Math.random().toString(36).slice(2, 10);
  const HEIGHTS = { 1280: 800, 768: 1024, 390: 844 };

  // ------------------------------------------------------------ state
  const blankProject = () => ({ id: null, name: "Untitled", device: 1280, screens: [], camera: { x: 80, y: 60, z: 1 }, designSystem: null, data: {} });
  let project = blankProject();
  let selected = null;           // screen id
  let cfg = {};
  let aborter = null;
  const frames = new Map();     // id -> element
  let saveTimer = null;

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
    canvas.style.transform = `translate(${c.x}px, ${c.y}px) scale(${c.z})`;
    viewport.style.backgroundPosition = `${c.x}px ${c.y}px`;
    viewport.style.backgroundSize = `${24 * c.z}px ${24 * c.z}px`;
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
    const xe = project.screens.map(s => s.x + s.width), ye = project.screens.map(s => s.y + HEIGHTS[s.width] + 36);
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
    $(".body", el).style.height = HEIGHTS[s.width] + "px";
    $(".title", el).textContent = s.title;
    const v = $(".ver", el); v.textContent = "v" + (s.versions.length); v.title = s.versions.length > 1 ? "Click to switch version" : "";
    v.style.display = s.versions.length > 1 ? "" : "none";
    el.classList.toggle("selected", s.id === selected);
    $(".eng", el).textContent = s.spec ? "spec" : "";
    if (!s.html && !el.classList.contains("loading")) { el.classList.add("noresult"); const er = $(".err", el); if (!er.textContent) { er.textContent = "No result saved (page was closed mid-generation?). Click ↻ to regenerate."; er.classList.remove("hidden"); } }
    if ($("iframe", el).dataset.html !== s.html) setFrameHTML(el, s.html);
    return el;
  }
  function setFrameHTML(el, html) {
    const f = $("iframe", el);
    f.dataset.html = html; f.srcdoc = html || "<!doctype html><body style='font:14px system-ui;color:#999;padding:24px'>…</body>";
  }
  function wireFrame(el, s) {
    el.addEventListener("pointerdown", e => { if (e.button === 0 && !space) { select(s.id); } });
    // drag by bar
    $(".bar", el).addEventListener("pointerdown", e => {
      if (e.button !== 0 || space || e.target.closest("button, .title, .ver")) return;
      e.stopPropagation();
      const st = { x: e.clientX, y: e.clientY, sx: s.x, sy: s.y };
      const mv = ev => { s.x = st.sx + (ev.clientX - st.x) / project.camera.z; s.y = st.sy + (ev.clientY - st.y) / project.camera.z; el.style.left = s.x + "px"; el.style.top = s.y + "px"; };
      const up = () => { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); scheduleSave(); };
      window.addEventListener("pointermove", mv); window.addEventListener("pointerup", up);
    });
    $(".title", el).addEventListener("blur", e => { s.title = e.target.textContent.trim() || s.title; e.target.textContent = s.title; scheduleSave(); });
    $(".title", el).addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); e.target.blur(); } });
    $(".ver", el).addEventListener("click", e => { e.stopPropagation(); cycleVersion(s); });
    $(".dup", el).addEventListener("click", e => { e.stopPropagation(); duplicate(s); });
    $(".dl", el).addEventListener("click", e => { e.stopPropagation(); download(`${slug(s.title)}.html`, s.html, "text/html"); });
    $(".open", el).addEventListener("click", e => { e.stopPropagation(); const b = new Blob([s.html], { type: "text/html" }); window.open(URL.createObjectURL(b), "_blank"); });
    $(".del", el).addEventListener("click", e => { e.stopPropagation(); removeScreen(s.id); });
    $(".regen", el).addEventListener("click", e => { e.stopPropagation(); regenerate(s); });
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
    dsIndicator();
    applyCamera();
  }
  function select(id) {
    selected = id;
    frames.forEach((el, fid) => el.classList.toggle("selected", fid === id));
    const s = id && screenById(id);
    $("#targetChip").classList.toggle("hidden", !s);
    if (s) { $("#targetName").textContent = s.title; promptEl.placeholder = "Describe a change to this screen…"; goBtn.firstChild.textContent = "Apply "; }
    else { promptEl.placeholder = "Describe a screen to design…"; goBtn.firstChild.textContent = "Generate "; }
  }
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
    return Math.max(...project.screens.map(s => s.y + HEIGHTS[s.width] + 36)) + 120;
  }
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
  const genExtras = () => ({ mode: $("#engine").value, design_system: project.designSystem || undefined, data: Object.keys(project.data || {}).length ? project.data : undefined });
  let progTimer = null, progStart = 0, progBytes = {};
  function setBusy(b, label) {
    goBtn.disabled = b; stopBtn.classList.toggle("hidden", !b);
    clearInterval(progTimer);
    if (b) {
      progStart = Date.now(); progBytes = {};
      progTimer = setInterval(() => {
        const secs = Math.round((Date.now() - progStart) / 1000);
        const kb = Object.values(progBytes).reduce((a, n) => a + n, 0) / 1024;
        $("#status").textContent = `${label} · ${secs}s · ${kb.toFixed(0)} KB received`;
        let thinking = 0;
        for (const [id, el] of frames) if (el.classList.contains("loading")) {
          const p = $(".prog", el), kb = (progBytes[id] || 0) / 1024;
          if (p.dataset.phase === "thinking" && !kb) { thinking++; p.textContent = `thinking… ${secs}s`; }
          else p.textContent = `${secs}s · ${kb.toFixed(0)} KB`;
        }
        if (thinking) $("#status").textContent += ` · model is thinking (${thinking})`;
      }, 1000);
      $("#status").textContent = label + " · 0s";
    } else $("#status").textContent = "";
  }

  async function generate(brief) {
    const n = +$("#variants").value, width = project.device, y = nextRowY();
    const batch = [];
    for (let i = 0; i < n; i++) {
      const s = { id: uid(), title: shortTitle(brief) + (n > 1 ? ` ${String.fromCharCode(65 + i)}` : ""), brief, x: i * (width + 80), y, width, html: "", versions: [] };
      project.screens.push(s); batch.push(s);
    }
    renderAll(); batch.forEach(s => frames.get(s.id).classList.add("loading"));
    if (project.screens.length === n) fitAll(); else panTo(batch[0]);
    const context = projectContext(batch);
    aborter = new AbortController(); setBusy(true, `Generating ${n} variant${n > 1 ? "s" : ""}`);
    try {
      await streamPost("/api/generate", { brief, variants: n, width, context, ...genExtras() }, ev => handleEvent(ev, batch), aborter.signal);
    } catch (e) { if (e.name !== "AbortError") toast("Error: " + e.message, 6000); }
    finally { finish(batch); }
  }

  async function iterate(s, instruction) {
    const el = frames.get(s.id); el.classList.add("loading");
    const prev = s.html; aborter = new AbortController(); setBusy(true, "Applying change");
    try {
      await streamPost("/api/iterate", { html: prev, instruction, width: s.width, spec: s.spec || undefined, ...genExtras() }, ev => handleEvent(ev, [s]), aborter.signal);
    } catch (e) { if (e.name !== "AbortError") toast("Error: " + e.message, 6000); }
    finally { finish([s]); }
  }

  async function regenerate(s) {
    if (goBtn.disabled) { toast("Wait for the current generation to finish."); return; }
    const el = frames.get(s.id); const er = $(".err", el); er.textContent = ""; er.classList.add("hidden");
    el.classList.remove("failed", "noresult"); el.classList.add("loading");
    const brief = s.brief || s.title;
    aborter = new AbortController(); setBusy(true, "Regenerating");
    try {
      await streamPost("/api/generate", { brief, variants: 1, width: s.width, context: projectContext([s]), ...genExtras() }, ev => handleEvent(ev, [s]), aborter.signal);
    } catch (e) { if (e.name !== "AbortError") toast("Error: " + e.message, 6000); }
    finally { finish([s]); }
  }

  function handleEvent(ev, batch) {
    const s = batch[ev.i]; if (!s) return;
    const el = frames.get(s.id); if (!el) return;
    if (ev.type === "status") { $(".prog", el).dataset.phase = ev.status; }
    else if (ev.type === "partial") { delete $(".prog", el).dataset.phase; progBytes[s.id] = ev.chars || (ev.html || "").length; if (ev.html) setFrameHTML(el, ev.html); }
    else if (ev.type === "done") {
      s.html = ev.html; s.versions.push(ev.html); s.spec = ev.spec || null; s.specVersions = s.specVersions || []; s.specVersions.push(ev.spec || null);
      setFrameHTML(el, ev.html); el.classList.remove("loading", "failed", "noresult"); $(".prog", el).textContent = "";
      renderFrame(s); scheduleSave();
      if (ev.warning) { toast("⚠ " + s.title + ": " + ev.warning, 7000); $(".title", el).title = ev.warning; }
    } else if (ev.type === "error") {
      el.classList.remove("loading"); el.classList.add("failed"); $(".prog", el).textContent = ""; const er = $(".err", el); er.textContent = ev.message; er.classList.remove("hidden");
      if (s.html) setFrameHTML(el, s.html);
    }
  }
  function finish(batch) {
    setBusy(false); aborter = null;
    for (const s of batch) {
      const el = frames.get(s.id); if (!el) continue;
      el.classList.remove("loading"); $(".prog", el).textContent = "";
      if (!s.versions.length && !$(".err", el).textContent) { $(".err", el).textContent = "Stopped before any result. Click ↻ to regenerate."; $(".err", el).classList.remove("hidden"); el.classList.add("noresult"); }
    }
    scheduleSave();
  }
  function panTo(s) {
    const c = project.camera, vw = viewport.clientWidth;
    c.x = (vw - s.width * c.z) / 2 - s.x * c.z; c.y = 40 - s.y * c.z; applyCamera();
  }
  function shortTitle(b) { const t = b.replace(/\s+/g, " ").trim(); return t.length > 42 ? t.slice(0, 40).replace(/\s\S*$/, "") + "…" : t; }
  function projectContext(exclude) {
    const others = project.screens.filter(s => !exclude.includes(s) && s.html);
    if (!others.length) return null;
    return others.slice(-4).map(s => `- Existing screen "${s.title}": ${s.brief || ""}`).join("\n") + "\nReuse the same palette/typography as existing screens where sensible.";
  }

  $("#promptBar").addEventListener("submit", e => {
    e.preventDefault(); const text = promptEl.value.trim(); if (!text || goBtn.disabled) return;
    promptEl.value = ""; autosize();
    const s = selected && screenById(selected);
    if (s && s.html) iterate(s, text); else generate(text);
  });
  promptEl.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#promptBar").requestSubmit(); } });
  promptEl.addEventListener("beforeinput", e => { if (e.inputType === "insertLineBreak" || (e.inputType === "insertParagraph")) { e.preventDefault(); $("#promptBar").requestSubmit(); } });
  function autosize() { promptEl.style.height = "auto"; promptEl.style.height = Math.min(200, promptEl.scrollHeight) + "px"; }
  promptEl.addEventListener("input", autosize);
  stopBtn.addEventListener("click", () => aborter && aborter.abort());
  $("#clearTarget").addEventListener("click", () => select(null));
  $("#engine").addEventListener("change", e => postConfig({ mode: e.target.value }));

  // ------------------------------------------------------------ toolbar
  $("#zoomIn").addEventListener("click", () => zoomAt(1.25, viewport.clientWidth / 2, viewport.clientHeight / 2));
  $("#zoomOut").addEventListener("click", () => zoomAt(0.8, viewport.clientWidth / 2, viewport.clientHeight / 2));
  $("#zoomLabel").addEventListener("click", () => { project.camera.z = 1; applyCamera(); });
  $("#fitBtn").addEventListener("click", fitAll);
  $$("#deviceSeg button").forEach(b => b.addEventListener("click", () => { project.device = +b.dataset.w; renderAll(); scheduleSave(); }));
  $("#projectName").addEventListener("change", e => { project.name = e.target.value.trim() || "Untitled"; scheduleSave(); });
  $("#exportBtn").addEventListener("click", () => download(`${slug(project.name)}.localdesign.json`, JSON.stringify(project, null, 2), "application/json"));
  window.addEventListener("keydown", e => {
    if (isTyping(e)) { if (e.key === "Escape") e.target.blur(); return; }
    const mod = e.metaKey || e.ctrlKey;
    if (e.key === "Escape") select(null);
    else if ((e.key === "Delete" || e.key === "Backspace") && selected) removeScreen(selected);
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
  async function save() {
    if (!project.screens.length && !project.id) { $("#saveState").textContent = ""; return; }
    try {
      const r = await fetch("/api/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(project) });
      const d = await r.json(); project.id = d.id; localStorage.setItem("ld.last", d.id); $("#saveState").textContent = "saved";
      setTimeout(() => { if ($("#saveState").textContent === "saved") $("#saveState").textContent = ""; }, 1500);
    } catch { $("#saveState").textContent = "save failed"; }
  }
  async function loadProject(id) {
    const r = await fetch("/api/projects/" + id); if (!r.ok) return false;
    project = await r.json(); project.camera ||= { x: 80, y: 60, z: 1 }; project.data ||= {}; project.designSystem ||= null; project.screens.forEach(s => { s.versions ||= s.html ? [s.html] : []; });
    frames.forEach(el => el.remove()); frames.clear(); select(null); renderAll(); localStorage.setItem("ld.last", id); return true;
  }
  function newProject() {
    project = blankProject();
    frames.forEach(el => el.remove()); frames.clear(); select(null); renderAll(); localStorage.removeItem("ld.last");
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
    try { const p = JSON.parse(await f.text()); p.id = null; project = p; project.screens.forEach(s => { s.versions ||= [s.html]; }); frames.forEach(el => el.remove()); frames.clear(); renderAll(); scheduleSave(); $("#projects").close(); fitAll(); }
    catch { toast("Not a valid project file"); }
    e.target.value = "";
  });

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
  $("#dsParse").addEventListener("click", async () => {
    const text = $("#dsSource").value; if (!text.trim()) { $("#dsMsg").textContent = "Paste something first."; return; }
    $("#dsMsg").textContent = "parsing…";
    const r = await fetch("/api/ds/parse", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, kind: $("#dsKind").value }) });
    const d = await r.json(); if (d.error) { $("#dsMsg").textContent = d.error; return; }
    const cur = dsReadTokens(); dsFillTokens({ ...cur, ...d.tokens }); dsDraft.palette = d.palette || []; dsRenderPalette(dsDraft.palette);
    if (d.css && !$("#dsCss").value) $("#dsCss").value = d.css;
    if (d.kind === "html") { const m = text.match(/<body[^>]*>([\s\S]*)<\/body>/i); if (m && !(dsDraft.components || []).length) { (dsDraft.components ||= []).push({ name: "Reference page", description: "match this markup style", html: m[1].trim().slice(0, 4000) }); dsRenderComps(); } }
    $("#dsMsg").textContent = `${d.kind}: ${Object.keys(d.tokens).length} tokens, ${(d.palette || []).length} colors found — adjust below`;
  });
  $("#dsSave").addEventListener("click", async () => {
    dsDraft.name = $("#dsName").value.trim(); dsDraft.tokens = dsReadTokens(); dsDraft.notes = $("#dsNotes").value.trim(); dsDraft.css = $("#dsCss").value.trim();
    dsDraft.components = (dsDraft.components || []).filter(c => c.html && c.html.trim());
    project.designSystem = dsDraft; dsDlg.close(); dsIndicator(); scheduleSave();
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
  async function postConfig(body) {
    const r = await fetch("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    cfg = await r.json(); $("#modelLabel").textContent = cfg.model || "no model"; $("#modelDot").className = "dot " + (cfg.model ? "ok" : "bad");
  }
  form.addEventListener("submit", async e => {
    e.preventDefault();
    await postConfig({ provider: form.provider.value, base_url: form.base_url.value, model: form.model.value, api_key: form.api_key.value || undefined,
      temperature: +form.temperature.value, max_tokens: +form.max_tokens.value, allow_cdn: form.allow_cdn.checked, effort: form.effort.value, variants: +$("#variants").value });
    dlg.close(); toast(`Using ${cfg.model} @ ${cfg.base_url}`);
  });
  $("#settingsBtn").addEventListener("click", openSettings);
  $("#settingsCancel").addEventListener("click", () => dlg.close());

  // ------------------------------------------------------------ boot
  (async () => {
    await loadConfig();
    const last = localStorage.getItem("ld.last");
    if (!(last && await loadProject(last))) renderAll();
    if (!cfg.model) { toast("Set a model in Settings (top right) to start.", 5000); }
    promptEl.focus();
  })();
})();
