/* localdesign editor shim — injected into every screen iframe (never saved with the screen).
   Talks to the parent via postMessage. Handles hover/select, text edit, drag-reorder,
   cross-frame drops, style edits, and serializes the page back after each change. */
(() => {
  if (window.__ldEditor) return; window.__ldEditor = true;
  let active = false, sel = null, hover = null, drag = null, editing = null;
  const post = (m) => parent.postMessage({ ld: true, ...m }, "*");
  const SKIP = new Set(["HTML", "BODY", "SCRIPT", "STYLE", "HEAD", "META", "LINK", "TITLE"]);
  const INLINE_PROPS = ["display", "position", "flex", "flex-direction", "flex-wrap", "gap", "align-items", "justify-content", "grid-template-columns",
    "width", "max-width", "min-width", "height", "min-height", "margin", "padding", "box-sizing", "border", "border-radius", "box-shadow",
    "background", "color", "font-family", "font-size", "font-weight", "line-height", "letter-spacing", "text-align", "text-transform",
    "text-decoration", "opacity", "overflow", "white-space", "list-style"];

  // ---------- overlays
  const mk = (cls) => { const d = document.createElement("div"); d.setAttribute("data-ld-ui", "1"); d.className = cls; d.style.cssText = "position:fixed;pointer-events:none;z-index:2147483000;box-sizing:border-box;display:none;"; document.documentElement.appendChild(d); return d; };
  const hoverBox = mk("ld-hover"), selBox = mk("ld-sel"), dropLine = mk("ld-drop"), label = mk("ld-label");
  hoverBox.style.cssText += "outline:1.5px dashed #1f6feb;outline-offset:-1px;";
  selBox.style.cssText += "outline:2px solid #1f6feb;outline-offset:-2px;background:rgba(31,111,235,.04);";
  dropLine.style.cssText += "background:#1f6feb;height:3px;border-radius:2px;";
  label.style.cssText += "background:#1f6feb;color:#fff;font:11px/1 system-ui;padding:3px 6px;border-radius:4px;transform:translateY(-100%);";
  function box(el, b) { if (!el || !el.isConnected) { b.style.display = "none"; return; } const r = el.getBoundingClientRect(); Object.assign(b.style, { display: "block", left: r.left + "px", top: r.top + "px", width: r.width + "px", height: r.height + "px" }); }
  function refresh() { box(hover, hoverBox); box(sel, selBox); if (sel) { const r = sel.getBoundingClientRect(); label.textContent = describe(sel); Object.assign(label.style, { display: "block", left: r.left + "px", top: Math.max(14, r.top) + "px" }); } else label.style.display = "none"; }
  window.addEventListener("scroll", refresh, true); window.addEventListener("resize", refresh);

  // ---------- helpers
  const isUI = (el) => el && el.closest && el.closest("[data-ld-ui]");
  function pick(x, y) { const els = document.elementsFromPoint(x, y).filter(e => !isUI(e) && !SKIP.has(e.tagName)); return els[0] || null; }
  function describe(el) { const cls = [...el.classList].filter(c => !c.startsWith("ld-ui")).slice(0, 2).join("."); return el.tagName.toLowerCase() + (cls ? "." + cls : ""); }
  function pathOf(el) { const p = []; while (el && el !== document.body) { p.unshift([...el.parentElement.children].indexOf(el)); el = el.parentElement; } return p; }
  function byPath(p) { let el = document.body; for (const i of p) { el = el.children[i]; if (!el) return null; } return el; }
  function leafText(el) { return [...el.childNodes].every(n => n.nodeType === 3 || (n.nodeType === 1 && ["B", "I", "EM", "STRONG", "SPAN", "A", "SMALL", "BR"].includes(n.tagName))); }
  function info(el) {
    const cs = getComputedStyle(el), r = el.getBoundingClientRect();
    return { path: pathOf(el), tag: el.tagName.toLowerCase(), desc: describe(el), crumbs: crumbs(el), text: leafText(el) ? el.textContent.trim().slice(0, 120) : null, isLeaf: leafText(el),
      rect: { x: r.left, y: r.top + window.scrollY, w: r.width, h: r.height }, link: el.getAttribute("data-link") || "",
      styles: { color: cs.color, background: cs.backgroundColor, fontSize: cs.fontSize, fontWeight: cs.fontWeight, padding: cs.padding, borderRadius: cs.borderRadius, width: el.style.width || "", textAlign: cs.textAlign }, html: el.outerHTML.slice(0, 6000) };
  }
  function crumbs(el) { const c = []; let e = el; while (e && e !== document.body && c.length < 4) { c.unshift(describe(e)); e = e.parentElement; } return c.join(" › "); }
  function serialize() {
    const clone = document.documentElement.cloneNode(true);
    clone.querySelectorAll("[data-ld-ui]").forEach(n => n.remove());
    clone.querySelectorAll("[contenteditable]").forEach(n => n.removeAttribute("contenteditable"));
    clone.querySelectorAll("[data-ld-drag]").forEach(n => n.removeAttribute("data-ld-drag"));
    return "<!DOCTYPE html>\n" + clone.outerHTML;
  }
  let changeTimer; function changed(kind) { clearTimeout(changeTimer); changeTimer = setTimeout(() => post({ type: "html", html: serialize(), kind }), 150); if (sel) post({ type: "select", info: info(sel) }); refresh(); }
  function inlineStyles(root) {
    const clone = root.cloneNode(true);
    const walk = (src, dst) => { const cs = getComputedStyle(src); const decl = INLINE_PROPS.map(p => { const v = cs.getPropertyValue(p); return v ? `${p}:${v}` : ""; }).filter(Boolean).join(";"); dst.setAttribute("style", decl + (src.getAttribute("style") ? ";" + src.getAttribute("style") : "")); [...src.children].forEach((c, i) => dst.children[i] && walk(c, dst.children[i])); };
    walk(root, clone); return clone.outerHTML;
  }

  // ---------- selection
  function select(el, notify = true) { if (editing && editing !== el) endEdit(); sel = el; refresh(); if (notify) post({ type: el ? "select" : "deselect", info: el ? info(el) : null }); }
  document.addEventListener("mousemove", e => { if (!active || drag) return; const el = pick(e.clientX, e.clientY); if (el !== hover) { hover = el; box(hover, hoverBox); } }, true);
  document.addEventListener("mouseleave", () => { hover = null; hoverBox.style.display = "none"; });
  document.addEventListener("click", e => { if (!active) return; if (editing && editing.contains(e.target)) return; e.preventDefault(); e.stopPropagation(); const el = pick(e.clientX, e.clientY); if (el) select(el === sel ? el : el); }, true);
  document.addEventListener("dblclick", e => { if (!active) return; e.preventDefault(); e.stopPropagation(); const el = pick(e.clientX, e.clientY); if (el && leafText(el)) beginEdit(el); }, true);
  document.addEventListener("submit", e => e.preventDefault(), true);
  document.addEventListener("keydown", e => {
    if (!active) return;
    if (editing) { if (e.key === "Escape" || (e.key === "Enter" && !e.shiftKey && editing.tagName !== "P")) { e.preventDefault(); endEdit(); } return; }
    if (e.key === "Escape") select(null);
    else if ((e.key === "Delete" || e.key === "Backspace") && sel) { e.preventDefault(); del(); }
    else if ((e.metaKey || e.ctrlKey) && e.key === "z") { e.preventDefault(); post({ type: "undo" }); }
    else if ((e.metaKey || e.ctrlKey) && e.key === "d" && sel) { e.preventDefault(); dup(); }
    else if (e.key === "ArrowUp" && sel && (e.metaKey || e.altKey)) { e.preventDefault(); move(-1); }
    else if (e.key === "ArrowDown" && sel && (e.metaKey || e.altKey)) { e.preventDefault(); move(1); }
  }, true);

  // ---------- text editing
  function beginEdit(el) { select(el, true); editing = el; el.setAttribute("contenteditable", "true"); el.focus(); document.execCommand && document.execCommand("selectAll", false, null); el.addEventListener("blur", endEdit, { once: true }); }
  function endEdit() { if (!editing) return; const el = editing; editing = null; el.removeAttribute("contenteditable"); changed("text"); }

  // ---------- mutations
  function del() { if (!sel) return; const n = sel.nextElementSibling || sel.previousElementSibling || sel.parentElement; sel.remove(); select(null); changed("delete"); }
  function dup() { if (!sel) return; const c = sel.cloneNode(true); sel.after(c); select(c); changed("duplicate"); }
  function move(dir) { if (!sel) return; const sib = dir < 0 ? sel.previousElementSibling : sel.nextElementSibling; if (!sib || isUI(sib)) return; dir < 0 ? sib.before(sel) : sib.after(sel); changed("move"); }
  function setStyle(styles) { if (!sel) return; for (const [k, v] of Object.entries(styles)) sel.style[k] = v; changed("style"); }
  function setText(text) { if (!sel) return; sel.textContent = text; changed("text"); }
  function replaceHTML(html) { if (!sel) return; const t = document.createElement("template"); t.innerHTML = html.trim(); const nodes = [...t.content.childNodes]; const first = nodes.find(n => n.nodeType === 1); sel.replaceWith(...nodes); select(first || null); changed("replace"); }
  function setLink(target) { if (!sel) return; if (target) sel.setAttribute("data-link", target); else sel.removeAttribute("data-link"); changed("link"); }

  // ---------- drag to reorder (inside this frame) + drag out (to another frame)
  document.addEventListener("mousedown", e => { if (!active || e.button !== 0 || editing) return; const el = pick(e.clientX, e.clientY); if (!el || el !== sel) return; drag = { el, x: e.clientX, y: e.clientY, moving: false, out: false }; }, true);
  document.addEventListener("mousemove", e => {
    if (!drag) return;
    if (!drag.moving) { if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 6) return; drag.moving = true; drag.el.style.opacity = ".4"; post({ type: "dragstart" }); }
    const over = pick(e.clientX, e.clientY);
    const outside = e.clientX < 0 || e.clientY < 0 || e.clientX > innerWidth || e.clientY > innerHeight;
    if (outside && !drag.out) { drag.out = true; post({ type: "dragout", html: inlineStyles(drag.el), desc: describe(drag.el) }); dropLine.style.display = "none"; return; }
    if (!outside && drag.out) { drag.out = false; post({ type: "dragback" }); }
    if (!over || over === drag.el || drag.el.contains(over)) { dropLine.style.display = "none"; drag.target = null; return; }
    const r = over.getBoundingClientRect(); const after = e.clientY > r.top + r.height / 2;
    drag.target = over; drag.after = after;
    Object.assign(dropLine.style, { display: "block", left: r.left + "px", width: r.width + "px", top: (after ? r.bottom - 1 : r.top - 1) + "px", height: "3px" });
  }, true);
  document.addEventListener("mouseup", e => {
    if (!drag) return; const d = drag; drag = null; dropLine.style.display = "none"; d.el.style.opacity = "";
    if (d.el.getAttribute("style") === "") d.el.removeAttribute("style");
    if (d.out) { post({ type: "dragend", dropped: false }); return; }
    if (d.moving && d.target) { d.after ? d.target.after(d.el) : d.target.before(d.el); changed("move"); }
  }, true);
  function dropAt(html, x, y) {
    const over = pick(x, y) || document.body; const t = document.createElement("template"); t.innerHTML = html.trim(); const node = t.content.firstElementChild; if (!node) return;
    if (over === document.body) document.body.appendChild(node); else { const r = over.getBoundingClientRect(); (y > r.top + r.height / 2) ? over.after(node) : over.before(node); }
    select(node); changed("drop");
  }

  // ---------- parent → shim
  window.addEventListener("message", e => {
    const m = e.data; if (!m || !m.ld) return;
    switch (m.type) {
      case "mode": active = !!m.edit; if (!active) { select(null, false); hover = null; refresh(); } break;
      case "select": select(byPath(m.path)); break;
      case "deselect": select(null, false); break;
      case "delete": del(); break;
      case "dup": dup(); break;
      case "move": move(m.dir); break;
      case "style": setStyle(m.styles); break;
      case "text": setText(m.text); break;
      case "edit": if (sel && leafText(sel)) beginEdit(sel); break;
      case "replace": replaceHTML(m.html); break;
      case "link": setLink(m.target); break;
      case "drop": dropAt(m.html, m.x, m.y); break;
      case "ping": post({ type: "ready" }); break;
      case "dragout-request": if (drag && drag.moving && !drag.out) { drag.out = true; post({ type: "dragout", html: inlineStyles(drag.el), desc: describe(drag.el) }); dropLine.style.display = "none"; } break;
      case "dragcancel": if (drag) { drag.el.style.opacity = ""; if (drag.el.getAttribute("style") === "") drag.el.removeAttribute("style"); drag = null; dropLine.style.display = "none"; } break;
      case "play": document.body.addEventListener("click", ev => { const t = ev.target.closest("[data-link]"); if (t) { ev.preventDefault(); post({ type: "navigate", target: t.getAttribute("data-link") }); } }, true);
        document.querySelectorAll("[data-link]").forEach(n => { n.style.cursor = "pointer"; }); break;
    }
  });
  post({ type: "ready" });
})();
