/* GMES Automation - the window (talks only to its own local server, web_server.py). */
"use strict";

const TOKEN = new URLSearchParams(location.search).get("t") || "";
const S = {
  busy: false, task: null, lastEvent: 0, boot: null, page: "reports",
  callbacks: {}, finished: {}, settings: null, appearance: null, connected: false,
  library: [], lastCheck: null, desc: null,
};
const pages = {};

// --------------------------------------------------------------------------
// Small helpers
// --------------------------------------------------------------------------
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k === "style") el.setAttribute("style", v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "busy") el.dataset.busy = "1";
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const $ = (sel, root = document) => root.querySelector(sel);
const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };
const fmtInt = (n) => (n === null || n === undefined || n === "") ? "-" : Number(n).toLocaleString("en-US");
const dirname = (p) => String(p || "").replace(/[\\/][^\\/]*$/, "");
const digits = (s) => String(s || "").replace(/\D/g, "");
function ymd(daysAgo) {
  const d = new Date(Date.now() - daysAgo * 86400000);
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
}
function fmtSecs(s) {
  s = Math.floor(s || 0); if (s <= 0) return "0s";
  const hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
  return hh ? `${hh}h ${String(mm).padStart(2, "0")}m` : (mm ? `${mm}m ${String(ss).padStart(2, "0")}s` : `${ss}s`);
}

async function api(path, body) {
  const opts = { headers: { "X-Token": TOKEN } };
  if (body !== undefined) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(path, opts);
  let data = {};
  try { data = await resp.json(); } catch (e) { /* empty */ }
  if (!resp.ok) {
    const err = new Error(data.error || `HTTP ${resp.status}`);
    err.status = resp.status;
    throw err;
  }
  return data;
}
async function call(path, body, title) {
  try { return await api(path, body); }
  catch (e) { await tell(title || "Something needs your attention", e.message, "err"); return null; }
}

// --------------------------------------------------------------------------
// Dialogs (in the page - never alert())
// --------------------------------------------------------------------------
function modal(title, message, { buttons = [["OK", "primary", true]], icon = "info", details = null, body = null } = {}) {
  return new Promise((resolve) => {
    const root = $("#modal-root");
    const glyph = { info: "i", ok: "✓", warn: "!", err: "✕", ask: "?" }[icon] || "i";
    const done = (v) => { back.remove(); document.removeEventListener("keydown", onKey, true); resolve(v); };
    const foot = h("div", { class: "modal-foot" });
    let last = null;
    buttons.forEach(([text, kind, value]) => {
      last = h("button", { class: `btn ${kind}`, text, onclick: () => done(value) });
      foot.append(last);
    });
    const det = details && details.length ? h("div", { class: "details" },
      details.map(([k, v]) => h("div", { class: "detail-row" }, h("span", { text: k }), h("span", { text: v })))) : null;
    const back = h("div", { class: "modal-back" },
      h("div", { class: "modal", role: "dialog" },
        h("div", { class: "modal-body" },
          h("div", { class: `modal-icon ${icon}`, text: glyph }),
          h("div", {}, h("h3", { text: title }), h("div", { class: "msg", text: message }), body, det)),
        foot));
    // Enter on a focused button presses THAT button (the browser's own click) - taking
    // it as the last button turned Enter on a focused Cancel into "Delete" / "Forget it".
    // Enter in the dialog's own text box is OK; elsewhere it is the main button.
    const onKey = (e) => {
      if (e.key === "Escape") { e.stopPropagation(); done(buttons[0][2]); }
      else if (e.key === "Enter" && !(e.target instanceof HTMLButtonElement)) {
        e.preventDefault(); done(buttons[buttons.length - 1][2]);
      }
    };
    document.addEventListener("keydown", onKey, true);
    root.append(back);
    (body && body.querySelector("input")) ? body.querySelector("input").focus() : last.focus();
  });
}
const tell = (title, message, icon = "info") => modal(title, message, { icon });
const ask = (title, message, { yes = "Continue", no = "Cancel", kind = "primary", icon = "ask", details = null } = {}) =>
  modal(title, message, { buttons: [[no, "", false], [yes, kind, true]], icon, details });
async function promptText(title, message, value = "") {
  const input = h("input", { type: "text", value, style: "margin-top:.8rem" });
  const ok = await modal(title, message, { body: h("div", {}, input), buttons: [["Cancel", "", false], ["OK", "primary", true]], icon: "ask" });
  return ok ? input.value.trim() || null : null;
}

// --------------------------------------------------------------------------
// Widgets
// --------------------------------------------------------------------------
function seg(options, value, onChange) {
  const el = h("div", { class: "seg" });
  const state = { value };
  const btns = options.map(([v, label]) => {
    const b = h("button", { text: label, onclick: () => { set(v); if (onChange) onChange(v); } });
    b.dataset.value = v;
    el.append(b);
    return b;
  });
  function set(v) { state.value = v; btns.forEach((b) => b.classList.toggle("on", b.dataset.value === String(v))); }
  set(value);
  el.get = () => state.value;
  el.set = set;
  el.setEnabled = (on) => btns.forEach((b) => { b.disabled = !on; });
  return el;
}

function banner(text = "", tone = "info", action = null) {
  const msg = h("div", { class: "grow" });
  const el = h("div", { class: "banner" }, msg, action);
  el.set = (t, k = "info") => { msg.textContent = t; el.className = `banner ${k === "info" ? "" : k}`; };
  el.set(text, tone);
  return el;
}

function card(title, { step = null, sub = null, fill = false, right = null } = {}) {
  const body = h("div", { class: "card-body", style: fill ? "flex:1;min-height:0;display:flex;flex-direction:column;gap:.6rem" : "" });
  const el = h("div", { class: `card${fill ? " fill" : ""}` },
    title ? h("div", { class: "card-head" },
      step !== null ? h("div", { class: "step", text: step }) : null,
      h("div", { class: "grow" }, h("h3", { text: title }), sub ? h("div", { class: "sub", text: sub }) : null),
      right) : null,
    body);
  el.body = body;
  return el;
}

function field(label, control, hint = null) {
  return h("div", { class: "field" }, h("label", {}, label, hint ? h("span", { class: "hint", text: hint }) : null), control);
}
function input(value = "", attrs = {}) { return h("input", Object.assign({ type: "text", value }, attrs)); }
function datalistInput(id, values, value = "", attrs = {}) {
  const list = h("datalist", { id }, values.map((v) => h("option", { value: v })));
  const el = input(value, Object.assign({ list: id }, attrs));
  el.setOptions = (vals) => { clear(list); vals.forEach((v) => list.append(h("option", { value: v }))); };
  return [el, list];
}
function select(options, value = "") {
  const el = h("select", {});
  el.setOptions = (opts, keep) => {
    const cur = keep === undefined ? el.value : keep;
    clear(el);
    opts.forEach((o) => { const [v, t] = Array.isArray(o) ? o : [o, o]; el.append(h("option", { value: v, text: t })); });
    if (opts.some((o) => (Array.isArray(o) ? o[0] : o) === cur)) el.value = cur;
  };
  el.setOptions(options, value);
  return el;
}

/* A table: rows = [{key, cells:{col: text}, tag}], multi-select with Ctrl / Shift. */
function table(columns, { multi = false, onSelect = null, onOpen = null, empty = "Nothing here yet." } = {}) {
  const thead = h("thead", {}, h("tr", {}, columns.map((c) => h("th", { text: c.title, style: c.width ? `width:${c.width}` : "" }))));
  const tbody = h("tbody");
  const wrap = h("div", { class: "table-wrap" }, h("table", { class: "t" }, thead, tbody));
  let rows = [], sel = new Set(), anchor = null;
  function paint() { for (const tr of tbody.children) tr.classList.toggle("sel", sel.has(tr.dataset.key)); }
  function fill(newRows) {
    rows = newRows;
    const keys = new Set(rows.map((r) => String(r.key)));
    sel = new Set([...sel].filter((k) => keys.has(k)));
    clear(tbody);
    if (!rows.length) {
      tbody.append(h("tr", { class: "empty" }, h("td", { colspan: columns.length, text: empty })));
    }
    const frag = document.createDocumentFragment();
    rows.forEach((r, i) => {
      const tr = h("tr", { class: r.tag ? `tag-${r.tag}` : "" });
      tr.dataset.key = String(r.key);
      tr.dataset.i = i;
      columns.forEach((c) => {
        const v = String(r.cells[c.key] ?? "");
        tr.append(h("td", { class: c.num ? "num" : (c.cls || ""), text: v, title: v.length > 24 ? v : null }));
      });
      frag.append(tr);
    });
    tbody.append(frag);
    paint();
  }
  tbody.addEventListener("click", (e) => {
    const tr = e.target.closest("tr"); if (!tr || !tr.dataset.key) return;
    const k = tr.dataset.key;
    if (multi && e.shiftKey && anchor !== null) {
      const a = rows.findIndex((r) => String(r.key) === anchor), b = Number(tr.dataset.i);
      const [lo, hi] = a < b ? [a, b] : [b, a];
      if (!e.ctrlKey) sel.clear();
      for (let i = lo; i <= hi; i++) sel.add(String(rows[i].key));
    } else if (multi && (e.ctrlKey || e.metaKey)) {
      sel.has(k) ? sel.delete(k) : sel.add(k); anchor = k;
    } else { sel = new Set([k]); anchor = k; }
    paint();
    if (onSelect) onSelect([...sel]);
  });
  tbody.addEventListener("dblclick", (e) => {
    const tr = e.target.closest("tr"); if (!tr || !tr.dataset.key) return;
    sel = new Set([tr.dataset.key]); paint();
    if (onOpen) onOpen(tr.dataset.key);
  });
  return {
    el: wrap, fill,
    selected: () => rows.map((r) => String(r.key)).filter((k) => sel.has(k)),
    select(keys) { sel = new Set(keys.map(String)); paint(); if (onSelect) onSelect([...sel]); },
    setCell(key, col, value, tag) {
      const tr = [...tbody.children].find((t) => t.dataset.key === String(key)); if (!tr) return;
      const i = columns.findIndex((c) => c.key === col); if (i >= 0) tr.children[i].textContent = value;
      if (tag) tr.className = `tag-${tag}` + (sel.has(String(key)) ? " sel" : "");
    },
    rows: () => rows,
  };
}

/* Two columns with a gap the person drags; the share is remembered per page. */
function columns(name, first, left, right) {
  const gutter = h("div", { class: "gutter-col", title: "Drag to resize - double-click to put it back" });
  const el = h("div", { class: "cols" }, left, gutter, right);
  const set = (f) => el.style.setProperty("--left", `${(f * 100).toFixed(2)}%`);
  const saved = (S.settings.panes || {})[name];
  set(typeof saved === "number" && saved > 0.1 && saved < 0.9 ? saved : first);
  gutter.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    gutter.setPointerCapture(e.pointerId);
    gutter.classList.add("dragging");
    const rect = el.getBoundingClientRect();
    let f = null;
    const move = (ev) => { f = Math.min(0.85, Math.max(0.15, (ev.clientX - rect.left) / rect.width)); set(f); };
    const up = () => {
      gutter.removeEventListener("pointermove", move);
      gutter.classList.remove("dragging");
      if (f !== null) { S.settings.panes[name] = Math.round(f * 1e4) / 1e4; savePanes(); }
    };
    gutter.addEventListener("pointermove", move);
    gutter.addEventListener("pointerup", up, { once: true });
  });
  gutter.addEventListener("dblclick", () => { set(first); delete S.settings.panes[name]; savePanes(); });
  return el;
}
function savePanes() { api("/api/settings", { panes: S.settings.panes }).catch(() => {}); }

function page(key, title, subtitle) {
  const el = h("section", { class: "page", id: `page-${key}` },
    h("div", { class: "page-title" }, h("h2", { text: title }), h("p", { text: subtitle })));
  $("#pages").append(el);
  return el;
}

// --------------------------------------------------------------------------
// Appearance
// --------------------------------------------------------------------------
function applyAppearance(a) {
  S.appearance = a;
  const root = document.documentElement.style;
  const palette = S.settings.themes[a.theme] || S.settings.themes.Light;
  for (const [k, v] of Object.entries(palette)) root.setProperty(`--${k.replace(/_/g, "-")}`, v);
  root.setProperty("--font", `"${a.font}", "Segoe UI", system-ui, sans-serif`);
  root.setProperty("--mono", `"${a.mono}", Consolas, monospace`);
  root.setProperty("--scale", String(a.size / 100));
  document.documentElement.style.colorScheme = ["Dark", "Midnight"].includes(a.theme) ? "dark" : "light";
}
async function setAppearance(change) {
  const a = Object.assign({}, S.appearance, change);
  applyAppearance(a);
  if (pages.appearance) pages.appearance.paint();
  try { await api("/api/settings", { appearance: a }); } catch (e) { /* kept for this session */ }
}

// --------------------------------------------------------------------------
// Activity console
// --------------------------------------------------------------------------
const consoleEl = () => $("#console");
function logLine(time, text, tag) {
  const c = consoleEl();
  const stick = c.scrollTop + c.clientHeight >= c.scrollHeight - 30;
  c.append(h("div", { class: tag || "info" }, h("span", { class: "t", text: time }), text));
  while (c.childElementCount > 4000) c.firstElementChild.remove();
  if (stick) c.scrollTop = c.scrollHeight;
}
function localLog(text, tag = "info") {
  const d = new Date();
  logLine(d.toTimeString().slice(0, 8), text, tag);
}
function setupActivity() {
  const work = $("#work"), gutter = $("#act-gutter");
  const act = S.settings.activity || {};
  const setH = (px) => work.style.setProperty("--act-h", `${px}px`);
  const setW = (px) => work.style.setProperty("--act-w", `${px}px`);
  if (act.height) setH(act.height);
  if (act.width) setW(act.width);
  // at the side (Phase 127) unless the window is narrow - the stylesheet's own breakpoint
  const atSide = () => !window.matchMedia("(max-width: 1100px)").matches;
  const save = (patch) => {
    S.settings.activity = Object.assign({}, S.settings.activity, patch);
    api("/api/settings", { activity: S.settings.activity }).catch(() => {});
  };
  const fold = (on, save = true) => {
    work.classList.toggle("folded", on);
    $("#act-fold").textContent = on ? "Show" : "Hide";
    if (save) { S.settings.activity = Object.assign({}, S.settings.activity, { folded: on }); api("/api/settings", { activity: S.settings.activity }).catch(() => {}); }
  };
  fold(!!act.folded, false);
  $("#act-fold").onclick = () => fold(!work.classList.contains("folded"));
  $("#act-clear").onclick = () => clear(consoleEl());
  $("#act-log").onclick = () => call("/api/open", { what: "log" });
  $("#act-data").onclick = () => call("/api/open", { what: "data" });
  gutter.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    gutter.setPointerCapture(e.pointerId);
    gutter.classList.add("dragging");
    const rect = work.getBoundingClientRect();
    const side = atSide();
    const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 14;
    let px = null;
    // The same limits the stylesheet applies to a saved size, so the pages always keep
    // the larger part of the window: at the side 18rem to 45% of the width, under the
    // pages 90 px to 38% of the height.
    const move = side
      ? (ev) => { px = Math.round(Math.max(18 * rem, Math.min(rect.width * 0.45, rect.right - ev.clientX))); setW(px); }
      : (ev) => { px = Math.round(Math.max(90, Math.min(rect.height * 0.38, rect.bottom - ev.clientY))); setH(px); };
    gutter.addEventListener("pointermove", move);
    gutter.addEventListener("pointerup", () => {
      gutter.removeEventListener("pointermove", move);
      gutter.classList.remove("dragging");
      if (px) save(side ? { width: px } : { height: px });
    }, { once: true });
  });
  gutter.addEventListener("dblclick", () => {
    if (atSide()) { work.style.removeProperty("--act-w"); save({ width: null }); }
    else { work.style.removeProperty("--act-h"); save({ height: null }); }
  });
}

// --------------------------------------------------------------------------
// Tasks and events
// --------------------------------------------------------------------------
async function runTask(kind, body, cbs = {}) {
  let r;
  try { r = await api(`/api/task/${kind}`, body || {}); }
  catch (e) {
    await tell(e.status === 409 ? "Busy" : "Check this first", e.message, e.status === 409 ? "warn" : "err");
    return false;
  }
  S.callbacks[r.task_id] = cbs;
  if (S.finished[r.task_id]) finishTask(S.finished[r.task_id]);   // it ended before we heard back
  return true;
}
function finishTask(e) {
  const cbs = S.callbacks[e.task_id];
  if (!cbs) { S.finished[e.task_id] = e; return; }
  delete S.callbacks[e.task_id]; delete S.finished[e.task_id];
  try {
    if (e.state === "done" && cbs.done) cbs.done(e.result);
    else if (e.state === "stopped") { if (cbs.stopped) cbs.stopped(); }
    else if (e.state === "failed") {
      if (cbs.failed) cbs.failed(e.error);
      else tell("Something needs your attention", e.error, "err");
    }
  } catch (err) { localLog(`(display problem: ${err.message})`, "muted"); }
}
// Which G-MES (HISTORY.md Phase 130): SEEG's own, or HQ (several factories). Each keeps its
// own recordings, batches and schedules, so the pages are read again after a switch.
function setupSite(info) {
  const box = $("#site");
  if (!box || !info || !info.sites) return;
  box.textContent = "";
  const names = { seeg: "SEEG G-MES", hq: "HQ G-MES" };
  const control = seg(info.sites.map((s) => [s.key, names[s.key] || s.label]), info.site, (v) => {
    if (v === info.site) return;
    api("/api/site", { site: v }).then(() => location.reload())
      .catch((e) => { control.set(info.site); tell("G-MES was not switched", e.message, "err"); });
  });
  control.dataset.busy = "";               // disabled while a task runs, like every action
  control.querySelectorAll("button").forEach((b) => { b.dataset.busy = ""; });
  box.append(control);
}
function setBusy(busy, task) {
  S.busy = busy; S.task = busy ? task : null;
  document.querySelectorAll("[data-busy]").forEach((b) => { b.disabled = busy || b.dataset.off === "1"; });
  $("#btn-stop").disabled = !busy;
  const pill = $("#pill");
  if (busy) { pill.className = "pill busy"; pill.textContent = `● ${task.name}`; }
  else { pill.className = `pill ${S.connected ? "ready" : "idle"}`; pill.textContent = S.connected ? "● Connected" : "● Not connected"; }
  Object.values(pages).forEach((p) => p.onBusy && p.onBusy(busy));
}
function handle(e) {
  if (e.type === "log") logLine(e.time, e.text, e.tag);
  else if (e.type === "who") { if (e.who) $("#who").textContent = `Signed in as ${e.who}`; }
  else if (e.type === "task") {
    if (e.state === "start") {
      setBusy(true, { id: e.task_id, name: e.name, started: Date.now() / 1000 });
    } else {
      if (e.connected !== undefined) S.connected = e.connected;
      setBusy(false);
      $("#task-label").textContent = `Last: ${e.name} (${fmtSecs(e.took)})`;
      finishTask(e);
    }
  }
  else if (e.type === "progress" && pages.rowexport) pages.rowexport.progress(e);
  else if (e.type === "batch_row" && pages.batch) pages.batch.row(e);
  else if (e.type === "batch_plan" && pages.batch) pages.batch.showPlan(e.plan);
}
async function poll() {
  for (;;) {
    try {
      const r = await api(`/api/events?after=${S.lastEvent}`);
      if (S.boot && r.boot !== S.boot) { location.reload(); return; }   // a new server: start clean
      S.boot = r.boot;
      if (r.reset) { S.lastEvent = 0; continue; }
      for (const e of r.events) { S.lastEvent = Math.max(S.lastEvent, e.id); handle(e); }
    } catch (err) {
      $("#pill").className = "pill stop";
      $("#pill").textContent = "● The app is not answering";
      await new Promise((res) => setTimeout(res, 2000));
    }
  }
}

// ==========================================================================
// Reports
// ==========================================================================
const STATUS_TAG = { "Ready": "ok", "Ready with warning": "warn", "Last run failed": "err", "Not yet run here": "muted" };
pages.reports = () => {
  const el = page("reports", "Reports", "Every screen this app can run. 'Record check' is the proof a recording works: a bare replay plus every item of the playbook, kept as a certificate.");
  const search = input("", { placeholder: "search code, title, division", style: "max-width:22rem" });
  const view = seg([["all", "All"], ["recorded", "Recorded here"], ["attention", "Needs attention"]], "all", () => paintTable());
  search.addEventListener("input", () => paintTable());
  el.append(h("div", { class: "row", style: "margin-bottom:.7rem" }, search, view, h("div", { class: "spacer" }),
    h("button", { class: "btn ghost", text: "Refresh", onclick: () => refresh() }),
    h("button", { class: "btn", text: "Import recordings...", onclick: () => importRecordings() })));
  const startHere = banner("Start here: nothing is recorded on this PC yet. Record a screen (any UI number), or bring recordings from another PC or from the project's screens folder with 'Import recordings'.",
    "info", h("button", { class: "btn ghost", text: "Record a screen", onclick: () => show("record") }));
  startHere.style.marginBottom = ".7rem";
  el.append(startHere);

  const t = table([{ key: "code", title: "Screen", width: "8rem" }, { key: "title", title: "Title" },
    { key: "status", title: "Status", width: "10rem" }, { key: "check", title: "Record check", width: "11rem" },
    { key: "settings", title: "Replays with" }, { key: "last", title: "Last run" }],
    { multi: true, onSelect: () => detail(), onOpen: () => runSelected(), empty: "No screen matches." });
  const count = h("div", { class: "note" });
  const left = card(null, { fill: true }); left.body.append(t.el, count);
  const detailBox = h("div", { style: "flex:1;min-height:0;overflow:auto" });
  const policy = seg([["keep", "As recorded"], ["yesterday", "Yesterday"], ["today", "Today"], ["lastweek", "Last week"]], "keep");
  const right = card("Selected screen", { fill: true });
  right.body.append(detailBox,
    h("div", { class: "field" }, h("label", { text: "Run for" }), policy),
    h("div", { class: "row" },
      h("button", { class: "btn success", text: "▶ Run selected", busy: true, onclick: () => runSelected() }),
      h("button", { class: "btn primary", text: "Record check", busy: true, onclick: () => checkSelected() }),
      h("button", { class: "btn", text: "Re-record", busy: true, onclick: () => rerecord() })),
    h("div", { class: "row" },
      h("button", { class: "btn ghost", text: "Open output folder", onclick: () => openOutput() }),
      h("button", { class: "btn ghost", text: "Open in the library", onclick: () => { const p = picked(); if (p.length === 1) pages.library.openCode(p[0].code); } }),
      h("button", { class: "btn ghost", text: "Forget this recording", onclick: () => forget() })));
  el.append(columns("reports", 0.62, h("div", { class: "col" }, left), h("div", { class: "col" }, right)));

  let cards = [], unreadable = [];
  async function refresh() {
    try { const r = await api("/api/library"); cards = r.cards; unreadable = r.unreadable; }
    catch (e) { localLog(`PROBLEM: the recordings could not be read (${e.message})`, "err"); cards = []; }
    S.library = cards;
    paintTable();
  }
  function paintTable() {
    const words = search.value.toLowerCase().split(/\s+/).filter(Boolean);
    const v = view.get();
    const rows = [];
    for (const c of cards) {
      const hay = `${c.code} ${c.title} ${c.settings}`.toLowerCase();
      if (words.length && !words.every((w) => hay.includes(w))) continue;
      if (v === "recorded" && !c.recorded) continue;
      if (v === "attention" && c.status === "Ready" && ["PASSED", ""].includes(c.check)) continue;
      const check = c.check ? `${c.check[0]}${c.check.slice(1).toLowerCase()}  ${c.check_at.slice(0, 10)}` : (c.recorded ? "not checked yet" : "-");
      rows.push({ key: c.code, tag: c.check === "FAILED" ? "err" : (STATUS_TAG[c.status] || ""),
        cells: { code: c.code, title: c.title, status: c.status, check, settings: c.replays, last: c.last_run || "-" } });
    }
    t.fill(rows);
    const recorded = cards.filter((c) => c.recorded).length;
    startHere.classList.toggle("hidden", recorded > 0);
    count.textContent = `${rows.length} shown  ·  ${recorded} recorded on this PC  ·  ${cards.length} known` +
      (unreadable.length ? `  ·  ⚠ ${unreadable.length} recording file(s) could not be read: ${unreadable.slice(0, 4).join(", ")}` : "");
    detail();
  }
  const picked = () => { const keys = new Set(t.selected()); return cards.filter((c) => keys.has(c.code)); };
  function detail() {
    clear(detailBox);
    const p = picked();
    if (!p.length) { detailBox.append(h("div", { class: "note", text: "Choose a screen on the left. Double-click runs it." })); return; }
    if (p.length > 1) { detailBox.append(h("div", { class: "note", text: `${p.length} screens selected - 'Run selected' runs them one after another in the same browser, like a batch.` })); return; }
    const c = p[0];
    const tone = { "Ready": "ok", "Ready with warning": "warn", "Last run failed": "err" }[c.status] || "info";
    detailBox.append(h("h3", { text: c.code }), h("div", { class: "note", style: "margin-bottom:.6rem", text: c.title }),
      banner(`${c.status}: ${c.why}`, tone),
      h("div", { style: "margin-top:.6rem" }, [
        ["Replays with", c.replays], ["Recorded", c.learned || "only the shipped structure - record it here"],
        ["Last run", c.last_run || "-"], ["Record check", c.check ? `${c.check}  (${c.check_at})` : "not yet"],
        ["Files go to", c.output_dir || "the app's output folder"]].map(([k, v]) =>
        h("div", { class: "detail-row" }, h("span", { text: k }), h("span", { text: v })))));
  }
  async function runSelected() {
    const p = picked(); if (!p.length) return;
    const notReady = p.filter((c) => !c.recorded).map((c) => c.code);
    if (notReady.length) { await tell("Record it first", `These have only the shipped structure on this PC: ${notReady.join(", ")}. Record them here once (Re-record).`, "warn"); return; }
    pages.batch.runCodes(p.map((c) => c.code), policy.get());
  }
  async function checkSelected() {
    const p = picked();
    if (p.length !== 1) { await tell("Choose one screen", "The record check runs one screen at a time."); return; }
    const code = p[0].code;
    if (!await ask(`Record check ${code}?`, "The screen is replayed bare - its code and nothing else - and every item of the check is proven again. It reads G-MES and exports one file.", { yes: "Run the check" })) return;
    runTask("recheck", { code }, { done: (view) => { refresh(); show("record"); pages.record.showCheck(view, code); } });
  }
  function rerecord() { const p = picked(); if (p.length === 1) { show("record"); pages.record.describeCode(p[0].code); } }
  function openOutput() {
    const p = picked();
    if (p.length && p[0].output_dir) call("/api/open", { path: p[0].output_dir });
    else call("/api/open", { what: "output" });
  }
  async function forget() {
    const p = picked(); if (p.length !== 1 || !p[0].recorded) return;
    const code = p[0].code;
    if (!await ask(`Forget ${code}?`, "This app's recording of the screen is removed (scope, dates, filters). The exported files are kept. You can record it again at any time.", { yes: "Forget it", kind: "danger", icon: "warn" })) return;
    if (await call("/api/forget", { code })) refresh();
  }
  async function importRecordings() {
    const r = await call("/api/import", {});
    if (!r || r.cancelled) return;
    await tell("Import finished", `${r.done.length} imported, ${r.skipped.length} left as they were (see Activity).`, r.done.length ? "ok" : "info");
    refresh();
  }
  return { el, show: refresh, refresh };
};

// ==========================================================================
// Screen library - one folder per recorded screen (HISTORY.md Phase 131)
// ==========================================================================
/* Every popup a run met, what was done, and the person's lasting rule for it; the sign-in budget
   (HISTORY.md Phase 132 - same as gmes_report.py popups / popup-rule). */
async function popupsMet() {
  let r;
  try { r = await api("/api/popups"); } catch (e) { tell("The popups could not be read", e.message, "err"); return; }
  const rules = [["auto", "auto (message: close; decision: stop)"], ["close", "close it"], ["stop", "stop the run"]];
  const body = h("div", { class: "col" }, h("div", { class: "note", text: `Sign-in: ${r.signin}` }));
  if (!r.popups.length) body.append(h("div", { class: "note", text: "No popup has been met yet." }));
  r.popups.forEach((p) => {
    const opts = rules.slice();
    (p.buttons || []).forEach((b) => opts.push([`press:${b}`, `press "${b}"`]));
    if (!opts.some((o) => o[0] === p.rule)) opts.push([p.rule, p.rule]);
    const pick = select(opts, p.rule);
    pick.addEventListener("change", async () => {
      const done = await call("/api/popup_rule", { key: p.key, rule: pick.value }, "The rule was not saved");
      if (done) localLog(`Popup ${p.key}: from now on '${pick.value}'.`, "ok");
    });
    body.append(h("div", { class: "card", style: "padding:.5rem .7rem;margin-top:.4rem" },
      h("div", { class: "row" }, h("b", { text: p.key }), h("span", { class: "note", text: ` ${p.kind || ""} · met ${p.count || 0}x · last ${p.last_seen || "-"}` }),
        h("div", { class: "spacer" }), pick),
      h("div", { class: "note", text: `${p.title || ""} ${p.text ? "- " + p.text : ""}`.slice(0, 300) }),
      h("div", { class: "note", text: `Buttons: ${(p.buttons || []).join(", ") || "-"} · last: ${p.last_action || "-"}${p.effective !== p.rule ? ` · built-in rule: ${p.effective}` : ""}` })));
  });
  modal("Popups met", "Every floating window a run met. A message (only OK / Close) is closed by itself; anything with a field or a choice stops the run until you set a rule here.",
    { body, icon: "info" });
}

const KIND_WORDS = { run: "Run", check: "Record check", edit: "Edited", restore: "Restored", describe: "Described",
  note: "Note", notes: "Notes edited" };
pages.library = () => {
  const el = page("library", "Screen library",
    "Everything about each recorded screen in one place: how it runs, what it looked like, what changed and what was learned. Edit a recording here without opening G-MES - the recording as it was is always kept.");
  const search = input("", { placeholder: "search code, title, filter, folder, notes...", style: "max-width:24rem" });
  const view = seg([["all", "All"], ["attention", "Needs attention"], ["notes", "Has notes"]], "all", () => paintList());
  search.addEventListener("input", () => paintList());
  const rootNote = h("div", { class: "note" });
  el.append(h("div", { class: "row", style: "margin-bottom:.7rem" }, search, view, h("div", { class: "spacer" }),
    h("button", { class: "btn ghost", text: "Refresh", onclick: () => refresh() }),
    h("button", { class: "btn ghost", text: "Popups met", onclick: () => popupsMet() }),
    h("button", { class: "btn ghost", text: "Open the library folder", onclick: () => S.libRoot && call("/api/open", { path: S.libRoot }) })));

  const list = table([{ key: "code", title: "Screen", width: "8rem" }, { key: "title", title: "Title" },
    { key: "last", title: "Last run", width: "10rem" }, { key: "check", title: "Record check", width: "8rem" }],
    { onSelect: (k) => open(k[0]), empty: "No screen matches." });
  const count = h("div", { class: "note" });
  const left = card(null, { fill: true }); left.body.append(list.el, count, rootNote);

  const head = h("div", { class: "lib-head" });
  const tabs = seg([["overview", "Overview"], ["shots", "Screenshots"], ["edit", "Edit"], ["history", "History & versions"],
    ["notes", "Notes"], ["code", "Code"]], "overview", () => paintTab());
  const body = h("div", { class: "lib-body" });
  const right = card(null, { fill: true });
  right.body.append(head, tabs, body);
  el.append(columns("library", 0.36, h("div", { class: "col" }, left), h("div", { class: "col" }, right)));
  body.append(h("div", { class: "note", text: "Choose a screen on the left." }));

  let rows = [], current = null;
  async function refresh(keep = true) {
    if (!rows.length) count.textContent = "Reading the library... the first time builds a folder for every recorded screen (about 10 seconds).";
    try { const r = await api("/api/dossiers"); rows = r.screens; S.libRoot = r.root; rootNote.textContent = `Folder: ${r.root}`; }
    catch (e) { localLog(`PROBLEM: the screen library could not be read (${e.message})`, "err"); rows = []; }
    paintList();
    if (keep && current) open(current.code, true);
  }
  function attention(r) { return r.last_ok === false || r.edited || r.check === "FAILED"; }
  function paintList() {
    const words = search.value.toLowerCase().split(/\s+/).filter(Boolean);
    const v = view.get();
    const shown = rows.filter((r) => (!words.length || words.every((w) => r.text.includes(w)))
      && (v !== "attention" || attention(r)) && (v !== "notes" || r.has_notes));
    list.fill(shown.map((r) => ({ key: r.code, tag: r.last_ok === false || r.check === "FAILED" ? "err" : (r.edited ? "warn" : ""),
      cells: { code: r.code, title: r.title, last: r.last_run ? r.last_run.slice(0, 16) + (r.last_ok === false ? " ✕" : "") : "-",
        check: r.edited ? "edited" : (r.check ? r.check[0] + r.check.slice(1).toLowerCase() : "-") } })));
    count.textContent = `${shown.length} shown · ${rows.length} recorded screens · ${rows.filter(attention).length} need attention`;
    if (current) list.select([current.code]);
  }
  async function open(code, quiet = false) {
    if (!code) return;
    try { const r = await api(`/api/dossier?code=${encodeURIComponent(code)}`); current = r.dossier; }
    catch (e) { if (!quiet) tell("The screen could not be opened", e.message, "err"); return; }
    paintHead(); paintTab();
  }
  function openCode(code) { show("library"); refresh(false).then(() => { list.select([code]); open(code); }); }

  function paintHead() {
    clear(head);
    const d = current;
    head.append(h("div", { class: "grow" }, h("h3", { text: `${d.code}  ·  ${d.title}` }),
      h("div", { class: "note", text: d.recorded ? `recorded ${d.learned}` : "only the shipped structure on this PC" })),
      h("div", { class: "row" },
        h("button", { class: "btn success sm", text: "▶ Run", busy: true, onclick: () => pages.batch.runCodes([d.code], "keep") }),
        h("button", { class: "btn primary sm", text: "Record check", busy: true, onclick: () => recheck() }),
        h("button", { class: "btn sm", text: "Describe again", busy: true, onclick: () => describeAgain() }),
        h("button", { class: "btn ghost sm", text: "Open folder", onclick: () => d.folder && call("/api/open", { path: d.folder }) })));
  }
  function rowsOf(items) { return h("div", {}, items.map((i) => h("div", { class: "detail-row" }, h("span", { text: i.name }), h("span", { text: i.value })))); }
  function paintTab() {
    clear(body);
    if (!current) { body.append(h("div", { class: "note", text: "Choose a screen on the left." })); return; }
    ({ overview, shots, edit, history, notes, code })[tabs.get()]();
  }

  function overview() {
    const d = current;
    const changed = d.status.find((s) => s.name === "Changed since");
    if (changed) body.append(banner(`Edited after its last record check (${changed.value.split(" (")[0]}) - prove it with a Record check before relying on it.`, "warn",
      h("button", { class: "btn sm", text: "Record check", busy: true, onclick: () => recheck() })));
    d.drift.forEach((w) => body.append(banner(`The newest describe: ${w}`, "warn")));
    body.append(h("h4", { text: "How it runs" }), rowsOf(d.recipe));
    if (d.status.length) body.append(h("h4", { text: "Proof" }), rowsOf(d.status));
    const latest = {};
    d.screenshots.forEach((s) => { if (!latest[s.stage]) latest[s.stage] = s; });
    const top = ["record-result", "check-result", "result", "record-scope", "scope", "describe", "failure"].map((k) => latest[k]).filter(Boolean).slice(0, 3);
    if (top.length) body.append(h("h4", { text: "What it looked like" }), thumbs(top));
    else body.append(h("div", { class: "note", style: "margin-top:.8rem", text: "No screenshots yet - the next run, record check or 'Describe again' takes them." }));
    const n = d.notes.replace(/^# Notes[\s\S]*?\n\n[\s\S]*?\n(?=\n|$)/, "").trim();
    body.append(h("h4", { text: "Notes" }), h("div", { class: "note pre", text: n || "None yet - the Notes tab keeps what was learned about this screen." }));
  }

  function shotUrl(name) { return `/shot?t=${encodeURIComponent(TOKEN)}&code=${encodeURIComponent(current.code)}&name=${encodeURIComponent(name)}`; }
  function thumbs(items) {
    return h("div", { class: "thumbs" }, items.map((s) => h("figure", { class: "thumb", onclick: () => bigShot(s) },
      h("img", { src: shotUrl(s.name), alt: s.stage, loading: "lazy" }),
      h("figcaption", {}, h("b", { text: s.stage }), ` ${s.at}`))));
  }
  function bigShot(s) {
    modal(`${current.code} · ${s.stage}`, s.at, { body: h("img", { class: "shot-big", src: shotUrl(s.name), alt: s.stage }), buttons: [["Close", "primary", true]] });
  }
  function shots() {
    const d = current;
    if (!d.screenshots.length) { body.append(h("div", { class: "note", text: "No screenshots yet. A run takes two (the scope just before Inquiry, the result after it), a record check and 'Describe again' take theirs, a failure is pictured as it happened." })); return; }
    body.append(h("div", { class: "note", style: "margin-bottom:.6rem", text: `${d.screenshots.length} screenshots, newest first - click one to see it large. Kept: the newest of each daily stage, and far more of recordings, record checks and describes.` }), thumbs(d.screenshots));
  }

  // ---- the editor -----------------------------------------------------------
  function edit() {
    const d = current;
    if (!d.recorded) { body.append(banner("Record this screen on this PC first - only a recording can be edited.", "warn")); return; }
    const v = d.values || {};
    const desc = d.describe || {};
    const filterNames = [...new Set([...(desc.filters || []), ...(desc.unbound || [])].flatMap((f) => [f.label, f.control]).filter(Boolean))];
    const division = input(v.division || "", { placeholder: "VD   ·   A | B = one query each   ·   A; B = ticked together" });
    const from = input(v.from || "", { placeholder: "YYYYMMDD or YYYYMM", style: "max-width:14rem" });
    const to = input(v.to || "", { placeholder: "YYYYMMDD or YYYYMM", style: "max-width:14rem" });
    const [verify, verifyList] = datalistInput("lib-verify", desc.verify_candidates || [], v.verify || "", { placeholder: "result column, e.g. planYmd" });
    // filters
    const fBox = h("div", { class: "kv" });
    const fRows = [];
    function addFilter(key, value, isNew) {
      const k = input(key, { placeholder: "filter (label or control)", list: "lib-filters", readonly: isNew ? null : true });
      const val = input(value, { placeholder: "value" });
      const rowEl = h("div", { class: "kv-row" }, k, val, h("button", { class: "btn ghost sm", text: "✕", title: "Remove this filter", onclick: () => { r.removed = true; rowEl.remove(); } }));
      const r = { k, val, orig: isNew ? null : key, removed: false };
      fRows.push(r); fBox.append(rowEl);
    }
    Object.entries(v.sets || {}).forEach(([k, val]) => addFilter(k, val, false));
    const fList = h("datalist", { id: "lib-filters" }, filterNames.map((n) => h("option", { value: n })));
    // options / picks / deliveries as chip lists
    function chips(initial, placeholder, listId, values) {
      const box = h("div", { class: "chips" });
      const state = { items: [...initial] };
      const add = input("", { placeholder, list: listId || null, style: "max-width:16rem" });
      function paint() {
        clear(box);
        state.items.forEach((it, i) => box.append(h("span", { class: "chip" }, it,
          h("button", { title: "Remove", text: "✕", onclick: () => { state.items.splice(i, 1); paint(); } }))));
      }
      paint();
      const addBtn = h("button", { class: "btn sm", text: "Add", onclick: () => { const t = add.value.trim(); if (t && !state.items.includes(t)) { state.items.push(t); add.value = ""; paint(); } } });
      add.addEventListener("keydown", (e) => { if (e.key === "Enter") addBtn.click(); });
      const wrap = h("div", {}, box, h("div", { class: "row" }, add, addBtn, listId && values ? h("datalist", { id: listId }, values.map((x) => h("option", { value: x }))) : null));
      wrap.get = () => state.items.slice();
      wrap.addPath = (p) => { if (p && !state.items.includes(p)) { state.items.push(p); paint(); } };
      return wrap;
    }
    const options = chips(d.options || [], "Weekly, Shift, PLANT...", "lib-options", (desc.options || []).map((o) => o.label));
    const picks = chips((d.picks || []).map((p) => `${p.label}=${p.value}`), "Label=Value  (PO Type=Normal P/O)");
    const dist = chips(d.distribute_to || [], "\\\\server\\share\\folder");
    const exportSeg = seg([["default", "Default (Excel)"], ["xlsx", "Excel"], ["csv", "CSV"], ["none", "No file"]], d.export || "default");
    const outDir = input(d.output_dir || "", { placeholder: "empty = the tool's output folder (a run can choose another)" });
    const periodCol = h("input", { type: "checkbox" }); periodCol.checked = !!d.period_column;
    const periodScreen = h("input", { type: "checkbox" }); periodScreen.checked = (v.period_check || "") === "screen";
    const result = h("div", {});
    body.append(
      h("div", { class: "note", style: "margin-bottom:.6rem", text: "Change what the recording does. Preview shows exactly what changes; Save keeps the recording as it was in its versions, so any edit can be put back." }),
      field("Division", division, "the organisation tree entry"),
      h("div", { class: "row" }, field("Period from (as recorded)", from), field("to", to)),
      field("Date proven in", h("div", {}, verify, verifyList), "the result column that must carry the period"),
      field("Filters", h("div", {}, fBox, fList, h("button", { class: "btn sm", text: "+ Add a filter", onclick: () => addFilter("", "", true) }))),
      field("Left-panel options", options),
      field("Picks from a popup list", picks),
      field("Files", exportSeg),
      field("Save folder", h("div", { class: "row" }, outDir, h("button", { class: "btn sm", text: "Browse", onclick: async () => { const r = await call("/api/pick_folder", { title: "Where this screen's files are saved" }); if (r && r.path) outDir.value = r.path; } }))),
      field("Also copy the files to", h("div", {}, dist, h("button", { class: "btn sm", text: "Browse for a folder", onclick: async () => { const r = await call("/api/pick_folder", { title: "Another folder the files are copied to" }); if (r && r.path) dist.addPath(r.path); } }))),
      h("label", { class: "check" }, periodCol, " CSV starts with Period From / Period To / Division"),
      h("label", { class: "check" }, periodScreen, " The screen defines its own period (rows may fall outside it - decided once)"),
      h("div", { class: "row", style: "margin-top:.8rem" },
        h("button", { class: "btn", text: "Preview changes", onclick: () => send(true) }),
        h("button", { class: "btn primary", text: "Save changes", onclick: () => send(false) }),
        h("button", { class: "btn ghost", text: "Undo my typing", onclick: () => paintTab() })),
      result);

    function change() {
      const c = {};
      if (division.value.trim() !== (v.division || "")) c.division = division.value.trim();
      if (digits(from.value) !== (v.from || "")) c.from = from.value.trim();
      if (digits(to.value) !== (v.to || "")) c.to = to.value.trim();
      if (verify.value.trim() !== (v.verify || "")) c.verify = verify.value.trim();
      const sets = {}, unset = [];
      fRows.forEach((r) => {
        if (r.removed) { if (r.orig) unset.push(r.orig); return; }
        const k = r.k.value.trim(), val = r.val.value.trim();
        if (!k) return;
        if (!r.orig || (v.sets || {})[r.orig] !== val) sets[k] = val;
      });
      if (Object.keys(sets).length) c.sets = sets;
      if (unset.length) c.unset = unset;
      const o0 = d.options || [], o1 = options.get();
      if (o1.some((x) => !o0.includes(x))) c.options_add = o1.filter((x) => !o0.includes(x));
      if (o0.some((x) => !o1.includes(x))) c.options_remove = o0.filter((x) => !o1.includes(x));
      const p0 = (d.picks || []).map((p) => `${p.label}=${p.value}`), p1 = picks.get();
      const label = (s) => s.split("=")[0].trim().toLowerCase();
      const added = p1.filter((x) => !p0.includes(x));
      if (added.length) c.picks_add = added;
      const gone = p0.filter((x) => !p1.includes(x) && !added.some((a) => label(a) === label(x)));
      if (gone.length) c.picks_remove = gone.map((x) => x.split("=")[0].trim());
      if (exportSeg.get() !== (d.export || "default")) c.export = exportSeg.get();
      if (outDir.value.trim() !== (d.output_dir || "")) c.output_dir = outDir.value.trim();
      const d1 = dist.get();
      if (JSON.stringify(d1) !== JSON.stringify(d.distribute_to || [])) c.distribute_to = d1;
      if (periodCol.checked !== !!d.period_column) c.period_column = periodCol.checked;
      if (periodScreen.checked !== ((v.period_check || "") === "screen")) c.period_check = periodScreen.checked ? "screen" : "";
      return c;
    }
    async function send(dry) {
      const c = change();
      clear(result);
      if (!Object.keys(c).length) { result.append(banner("Nothing changed yet.", "info")); return; }
      let r;
      try { r = await api("/api/edit", { code: d.code, change: c, dry_run: true }); }
      catch (e) { result.append(banner(e.message, "err")); return; }
      const lines = h("ul", { class: "diff" }, r.changes.map((l) => h("li", { text: l })));
      if (dry) {
        result.append(h("h4", { text: "This would change" }), lines);
        r.warnings.forEach((w) => result.append(banner(w, "warn")));
        return;
      }
      const ok = await modal(`Save the change to ${d.code}?`,
        "Every replay, batch and schedule of this screen will do this from now on. The recording as it is now is kept in its versions.",
        { body: h("div", {}, lines, ...r.warnings.map((w) => banner(w, "warn"))), buttons: [["Cancel", "", false], ["Save", "primary", true]], icon: "ask" });
      if (!ok) return;
      try { r = await api("/api/edit", { code: d.code, change: c, dry_run: false }); }
      catch (e) { result.append(banner(e.message, "err")); return; }
      current = r.dossier;
      paintHead(); tabs.set("overview"); paintTab(); refresh(false);
      body.prepend(banner(`Saved - the old recording is version ${r.version}. Prove the change with a Record check.`, "ok",
        h("button", { class: "btn sm", text: "Record check now", busy: true, onclick: () => recheck() })));
    }
  }

  // ---- history, versions, notes, code --------------------------------------------
  function history() {
    const d = current;
    body.append(h("h4", { text: `Versions of the recording (${d.versions.length})` }));
    if (!d.versions.length) body.append(h("div", { class: "note", text: "None yet - every edit, restore and new recording keeps the one before it here." }));
    d.versions.forEach((x) => body.append(h("div", { class: "detail-row" }, h("span", { text: x.at }),
      h("span", {}, `${x.reason}  ·  recorded ${x.learned || "?"}  `,
        h("button", { class: "btn ghost sm", text: "View", onclick: () => viewVersion(x) }),
        h("button", { class: "btn ghost sm", text: "Put this back", onclick: () => restoreVersion(x) })))));
    body.append(h("h4", { text: `History (${d.history.length})` }));
    if (!d.history.length) { body.append(h("div", { class: "note", text: "Nothing logged yet." })); return; }
    const t = table([{ key: "at", title: "When", width: "10.5rem" }, { key: "kind", title: "What", width: "8rem" }, { key: "detail", title: "Detail" }]);
    t.fill(d.history.map((e, i) => ({ key: i, tag: e.kind === "run" ? (e.ok ? "" : "err") : (e.kind === "check" ? (e.verdict === "FAILED" ? "err" : "ok") : (["edit", "restore"].includes(e.kind) ? "warn" : "")),
      cells: { at: e.at, kind: (KIND_WORDS[e.kind] || e.kind) + (e.context ? ` (${e.context})` : ""), detail: eventWords(e) } })));
    body.append(t.el);
  }
  function eventWords(e) {
    if (e.kind === "run") return e.ok ? `ok - ${fmtInt(e.rows)} rows${e.files ? " · " + e.files.join(", ") : ""}` : `FAILED - ${e.error || ""}`;
    if (e.kind === "check") return `${e.verdict || ""}${e.failed ? " - " + e.failed.join("; ") : ""}`;
    if (e.kind === "edit" || e.kind === "restore") return (e.changes || []).join("; ") + (e.by ? ` - by ${e.by}` : "");
    return String(e.detail || "");
  }
  async function viewVersion(x) {
    const r = await call(`/api/version?code=${encodeURIComponent(current.code)}&name=${encodeURIComponent(x.name)}`);
    if (!r) return;
    modal(`${current.code} · ${x.name}`, r.changes.length ? "Putting it back would change:" : "The same as the recording now.",
      { body: h("div", {}, h("ul", { class: "diff" }, r.changes.map((l) => h("li", { text: l }))), h("pre", { class: "code", text: r.text })), buttons: [["Close", "primary", true]] });
  }
  async function restoreVersion(x) {
    const r = await call(`/api/version?code=${encodeURIComponent(current.code)}&name=${encodeURIComponent(x.name)}`);
    if (!r) return;
    if (!r.changes.length) { tell("Nothing to put back", "This version does the same as the recording now."); return; }
    const ok = await modal(`Put ${x.name} back?`, "The recording as it is now is kept as a version first.",
      { body: h("ul", { class: "diff" }, r.changes.map((l) => h("li", { text: l }))), buttons: [["Cancel", "", false], ["Put it back", "primary", true]], icon: "ask" });
    if (!ok) return;
    const done = await call("/api/restore", { code: current.code, name: x.name });
    if (done) { current = done.dossier; paintHead(); paintTab(); refresh(false); }
  }
  function notes() {
    const d = current;
    const area = h("textarea", { class: "notes", spellcheck: "true" }); area.value = d.notes || "";
    const quick = input("", { placeholder: "Add a dated note: a problem and its fix, who uses the file, a G-MES quirk..." });
    const status = h("div", { class: "note" });
    const addBtn = h("button", { class: "btn primary", text: "Add note", onclick: async () => {
      if (!quick.value.trim()) return;
      const r = await call("/api/note", { code: d.code, text: quick.value.trim() });
      if (r) { d.notes = r.notes; area.value = r.notes; quick.value = ""; status.textContent = "Added."; refresh(false); }
    } });
    quick.addEventListener("keydown", (e) => { if (e.key === "Enter") addBtn.click(); });
    body.append(h("div", { class: "note", style: "margin-bottom:.5rem", text: "What people and agents learned about this screen. Kept in notes.md in its folder; the tool never overwrites it." }),
      h("div", { class: "row" }, quick, addBtn), area,
      h("div", { class: "row" }, h("button", { class: "btn", text: "Save the whole page", onclick: async () => {
        const r = await call("/api/notes", { code: d.code, text: area.value });
        if (r) { d.notes = r.notes; status.textContent = "Saved."; refresh(false); }
      } }), status));
  }
  function code() {
    const d = current;
    const desc = d.describe;
    if (desc) {
      body.append(h("h4", { text: `The screen as described ${desc.described_at || ""}` }));
      const t = table([{ key: "label", title: "Label" }, { key: "column", title: "Column" }, { key: "control", title: "Control" }, { key: "value", title: "Value then" }, { key: "kind", title: "", width: "6rem" }]);
      t.fill([...(desc.filters || []).map((f, i) => ({ key: "f" + i, cells: { label: f.label, column: f.column, control: f.control, value: f.value, kind: f.date ? "date" : "bound" } })),
        ...(desc.unbound || []).map((f, i) => ({ key: "u" + i, cells: { label: f.label, column: "-", control: f.control, value: f.value, kind: "typed" } }))]);
      body.append(t.el, h("div", { class: "note", style: "margin:.4rem 0 .8rem",
        text: `Grids: ${(desc.grids || []).map((g) => `${g.name}${g.suggested ? "*" : ""} (${g.dataset})`).join(", ") || "-"}  ·  Options: ${(desc.options || []).map((o) => o.label).join(", ") || "-"}  ·  Trees: ${(desc.trees || []).map((t) => t.dataset).join(", ") || "-"}  ·  Date fields: ${(desc.date_fields || []).join(", ") || "-"}` }));
    } else body.append(banner("No describe kept yet - 'Describe again' reads the screen (G-MES, read-only) and keeps what it offers here.", "info"));
    body.append(h("h4", { text: "The recording (as saved)" }), h("pre", { class: "code", text: d.recording_text }));
  }

  // ---- live actions ---------------------------------------------------------------
  async function recheck() {
    const d = current;
    if (!await ask(`Record check ${d.code}?`, "The screen is replayed bare - its code and nothing else - and every item of the check is proven again. It reads G-MES and exports one file.", { yes: "Run the check" })) return;
    runTask("recheck", { code: d.code }, { done: () => open(d.code, true).then(() => refresh(false)) });
  }
  async function describeAgain() {
    const d = current;
    runTask("describe", { code: d.code }, { done: () => { tabs.set("code"); open(d.code, true).then(() => refresh(false)); } });
  }
  return { el, show: () => refresh(), refresh, openCode };
};

// ==========================================================================
// Record a screen
// ==========================================================================
const CHECK_ICON = { ok: "✓", warn: "!", fail: "✕", info: "·" };
const CHECK_TAG = { ok: "ok", warn: "warn", fail: "err", info: "muted" };
pages.record = () => {
  const el = page("record", "Record a screen", "Any UI number: find it, see what it offers, choose the scope, record. The record check then replays it bare and proves every item before it counts as recorded.");
  // step 1
  const code = input("", { class: "big", placeholder: "P1112UM00  or words from its name", style: "max-width:18rem" });
  code.addEventListener("keydown", (e) => { if (e.key === "Enter") describe(); });
  const findT = table([{ key: "code", title: "Screen", width: "8rem" }, { key: "title", title: "Name" }, { key: "path", title: "Menu" }],
    { onSelect: (k) => { if (k.length) code.value = k[0]; }, onOpen: (k) => { code.value = k; describe(); } });
  findT.el.style.maxHeight = "14rem";
  const findBox = h("div", { class: "hidden", style: "display:flex;flex-direction:column;gap:.4rem;margin-top:.6rem" });
  const findNote = h("div", { class: "note" });
  findBox.append(findT.el, findNote);
  const c1 = card("Screen", { step: 1, sub: "A UI number, or words from its name" });
  c1.body.append(h("div", { class: "row" }, code,
    h("button", { class: "btn", text: "Find", busy: true, onclick: () => find() }),
    h("button", { class: "btn primary", text: "Describe", busy: true, onclick: () => describe() })),
    h("div", { class: "note", style: "margin-top:.5rem", text: "Describe opens the screen and reads it - grids, filters, divisions, options, date columns. It changes nothing in G-MES." }),
    findBox);
  // step 2
  const offer = h("div", {}, h("div", { class: "note", text: "Describe a screen first." }));
  const c2 = card("What the screen offers", { step: 2, sub: "Read from the live screen - the five questions of the playbook" });
  c2.body.append(offer);
  // step 3
  const grid = select([]);
  const [division, divList] = datalistInput("dl-division", [], "VD");
  const from = input(ymd(1)), to = input(ymd(1));
  const period = seg([["none", "No date"], ["day", "Day(s)"], ["month", "Month"]], "day", () => periodMode());
  const [verify, verifyList] = datalistInput("dl-verify", []);
  const optBox = h("div", { class: "row" }, h("span", { class: "note", text: "describe the screen to see its options" }));
  const fltBox = h("div", {}, h("span", { class: "note", text: "describe the screen to see its filters" }));
  const more = input("", { placeholder: "Name=Value; Name=Value" });
  let optionInputs = {}, filterInputs = {};
  const fromField = field("From", from, "YYYYMMDD");
  const verifyField = field("Verify: the result column that holds the date", h("div", {}, verify, verifyList), "required for a dated run");
  const c3 = card("Scope", { step: 3, sub: "What the recording will use every time it runs" });
  c3.body.append(field("Result grid", grid, "the table that IS the report"),
    field("Division / organisation", h("div", {}, division, divList), "empty = the screen's own"),
    field("Period", period),
    h("div", { class: "grid2" }, fromField, field("To", to)),
    h("div", { class: "row", style: "margin:-.3rem 0 .7rem" },
      h("button", { class: "chip", text: "Yesterday", onclick: () => quick(1) }),
      h("button", { class: "chip", text: "Today", onclick: () => quick(0) })),
    verifyField,
    field("Options", optBox, "left-panel choices to switch on"),
    field("Filters", fltBox, "leave empty to keep the screen's value"),
    field("More filters", more));
  // step 4
  const exportSeg = seg([["xlsx", "Excel"], ["csv", "CSV only"]], "xlsx");
  const out = input("", { placeholder: "empty = the app's output folder" });
  const c4 = card("Export and record", { step: 4, sub: "Excel is the default. The rows are checked against the data itself before any file is written." });
  c4.body.append(field("Files", exportSeg),
    field("Save the files in", h("div", { class: "row" }, h("div", { class: "grow" }, out),
      h("button", { class: "btn", text: "Browse", onclick: () => browse(out) }))),
    h("div", { class: "row" },
      h("button", { class: "btn", text: "Dry run", busy: true, onclick: () => record(true) }),
      h("button", { class: "btn success lg", text: "● Record + check", busy: true, onclick: () => record(false) })),
    h("div", { class: "note", style: "margin-top:.6rem", text: "Dry run applies everything and stops before Inquiry - to check the setup. Record + check runs it, replays it bare, and proves every item." }));
  // results
  const resBanner = banner("Record a screen to see its check here.");
  const checksT = table([{ key: "s", title: "", width: "2rem", cls: "ico" }, { key: "name", title: "Check" }, { key: "detail", title: "Evidence" }],
    { empty: "No check yet." });
  const confirmNote = h("div", { class: "note", text: "Only after looking at the same period on the G-MES screen." });
  const confirmBox = h("div", { class: "hidden" },
    h("button", { class: "btn success", text: "✓ I checked it on the G-MES screen", busy: true, onclick: () => confirmPeriod() }), confirmNote);
  const resCard = card("Record check", { fill: true, sub: "Every item of the playbook, from evidence" });
  resCard.body.append(resBanner, checksT.el, confirmBox, h("div", { class: "row" },
    h("button", { class: "btn ghost", text: "Open the files", onclick: () => { const f = (S.lastCheck || {}).files || []; if (f.length) call("/api/open", { path: dirname(f[0]) }); } }),
    h("button", { class: "btn ghost", text: "Open the certificate", onclick: () => { if (S.lastCheck) call("/api/open", { path: S.lastCheck.certificate }); } }),
    h("button", { class: "btn ghost", text: "Go to Reports", onclick: () => show("reports") })));
  el.append(columns("record", 0.55, h("div", { class: "col scroll" }, c1, c2, c3, c4), h("div", { class: "col" }, resCard)));

  function periodMode() {
    const m = period.get();
    from.disabled = to.disabled = m === "none";
    fromField.querySelector(".hint").textContent = m === "month" ? "YYYYMM - the whole month is checked" : "YYYYMMDD";
    if (m === "month") {
      // a recording keeps a month as its first and last day; show it as the month again
      const f = digits(from.value).slice(0, 6), t = digits(to.value).slice(0, 6) || f;
      if (f.length === 6) { from.value = f; to.value = t.length === 6 ? t : f; }
      else { const d = ymd(0).slice(0, 6); from.value = d; to.value = d; }
    } else if (m === "day" && digits(from.value).length !== 8) { from.value = ymd(1); to.value = ymd(1); }
  }
  function quick(days) { period.set("day"); from.value = ymd(days); to.value = ymd(days); periodMode(); }

  function find() {
    const q = code.value.trim(); if (!q) return;
    runTask("find", { query: q }, { done: (r) => {
      findT.fill(r.rows.map((x) => ({ key: x.code, cells: { code: x.code, title: x.title, path: x.path } })));
      findBox.classList.remove("hidden");
      findNote.textContent = `${r.matched} match(es) among ${r.total} screens` +
        (r.truncated ? ` - showing the first ${r.rows.length} of ${r.matched}; type more words` : "") + ". Double-click one to describe it.";
    } });
  }
  function describe() {
    const c = code.value.replace(/\s+/g, "").toUpperCase();
    if (!/^[A-Z][A-Z0-9]{3,5}[A-Z]{2}\d{2}$/.test(c)) { if (code.value.trim()) find(); return; }
    code.value = c;
    runTask("describe", { code: c }, { done: (d) => described(d) });
  }
  function describeCode(c) { code.value = c; describe(); }
  function described(d) {
    S.desc = d;
    clear(offer);
    offer.append(h("h3", { text: d.title }),
      h("div", { class: "note", style: "margin-bottom:.5rem", text: `${d.code}  ·  menu ${d.menu_id}  ·  Inquiry ${d.has_inquiry ? "yes" : "no"}  ·  Excel ${d.has_excel ? "yes" : "no"}` }),
      // spread: append() given an ARRAY wrote "[object HTMLDivElement],..." as text
      ...d.questions.map((q) => h("div", { class: "question" },
        h("span", { class: `ico tag-${{ ok: "ok", warn: "warn", decide: "info" }[q.tone]}`, text: { ok: "✓", warn: "!", decide: "?" }[q.tone] }),
        h("div", {}, h("b", { text: q.q }), h("span", { class: "note", text: q.a })))));
    if (d.profile && d.profile.learned) {
      const b = banner(`Already recorded here on ${d.profile.learned}. Recording again replaces it only if the new recording succeeds.`);
      b.style.marginTop = ".6rem"; offer.append(b);
    }
    // scope from what the screen offers, and from the last recording
    const last = d.last || {};
    grid.setOptions(d.grids.map((g) => [g.name, `${g.name}  (${g.dataset}, ${g.cols} cols)${g.suggested ? "  - suggested" : ""}`]),
      (d.grids.find((g) => g.suggested) || d.grids[0] || {}).name);
    const divisions = [...new Set(d.trees.flatMap((t) => t.names))].sort();
    division.setOptions(divisions);
    division.value = last.division || (divisions.length ? (divisions.includes("VD") ? "VD" : "") : "");
    // Period boxes the screen does not bind (R3220UM00) are filled by the same Period
    // picker - nobody has to know their control names (Phase 122)
    const typed = d.typed_dates || {};
    period.set(d.date_fields.length ? (d.looks_monthly ? "month" : "day")
      : (typed.from ? (typed.width === 6 ? "month" : "day") : "none"));
    if (last.from) { from.value = last.from; to.value = last.to || last.from; }
    else if (typed.from && (last.sets || {})[typed.from]) {
      from.value = digits(last.sets[typed.from]); to.value = digits((last.sets || {})[typed.to] || last.sets[typed.from]);
    }
    periodMode();
    verify.setOptions(d.verify_candidates);
    // A typed period is proven by the screen's read-back when the result has no date
    // column, so Verify is not guessed for it - only offered (a summary's blank
    // date-named column would fail the recording)
    verify.value = last.verify || (d.date_fields.length ? d.verify_candidates[0] || "" : "");
    verifyField.querySelector(".hint").textContent = d.date_fields.length ? "required for a dated run"
      : "optional - a result column that holds the date, if there is one";
    clear(optBox); optionInputs = {};
    const opts = d.options.filter((o) => ["button", "checkbox"].includes(o.kind) && !["inquiry", "search"].includes(o.label.toLowerCase()));
    if (!opts.length) optBox.append(h("span", { class: "note", text: "none on this screen" }));
    // a re-record starts from the options the last recording switched on, so it does not drop them
    const kept = new Set(((d.profile || {}).options || []).flatMap((o) => typeof o === "string" ? [o] : [o.key, o.label]).filter(Boolean));
    for (const o of opts) {
      const cb = h("input", { type: "checkbox", disabled: !o.enabled, checked: o.enabled && (kept.has(o.key) || kept.has(o.label)) });
      optionInputs[o.key || o.label] = cb;
      optBox.append(h("label", { class: "check" }, cb, `${o.label}  (${o.state}${o.enabled ? "" : ", disabled"})`));
    }
    clear(fltBox); filterInputs = {};
    const shown = d.filters.filter((f) => !f.date && f.visible);
    if (!shown.length) fltBox.append(h("span", { class: "note", text: "no other visible filters" }));
    for (const f of shown) {
      const key = f.label || f.column;
      const inp = input((last.sets || {})[key] || "");
      filterInputs[key] = inp;
      fltBox.append(h("div", { style: "display:grid;grid-template-columns:minmax(6rem,12rem) 1fr auto;gap:.6rem;align-items:center;margin-bottom:.3rem" },
        h("span", { class: "small muted", text: key }), inp, h("span", { class: "tiny faint", text: `now: ${(f.value || "-").slice(0, 18)}` })));
    }
    // What the last recording typed into fields that have no box above (R3220UM00's
    // mskFromDate / rdoSearchType) comes back in More filters - a re-record used to drop
    // them silently and then ran a different query.
    const rest = Object.entries(last.sets || {}).filter(([k]) => !(k in filterInputs) && k !== typed.from && k !== typed.to);
    more.value = rest.map(([k, v]) => `${k}=${v}`).join("; ");
  }
  function specBody(dry) {
    const c = code.value.replace(/\s+/g, "").toUpperCase();
    let g = grid.value;
    if (S.desc && S.desc.code === c) { const sug = (S.desc.grids.find((x) => x.suggested) || {}).name; if (g === sug) g = ""; }
    const sets = {}; for (const [k, i] of Object.entries(filterInputs)) if (i.value.trim()) sets[k] = i.value.trim();
    return { code: c, division: division.value.trim(), period: period.get(), from: from.value, to: to.value,
      verify: verify.value.trim(), sets, more: more.value, options: Object.entries(optionInputs).filter(([, i]) => i.checked).map(([k]) => k),
      grid: g, export: exportSeg.get(), out_dir: out.value.trim(), dry,
      typed_dates: (S.desc && S.desc.code === c) ? (S.desc.typed_dates || null) : null };
  }
  async function record(dry) {
    const body = specBody(dry);
    const r = await call("/api/spec", body); if (!r) return;
    if (r.problems.length) { await tell("Check the scope", r.problems.join("\n"), "warn"); return; }
    const spec = r.spec;
    if (!S.desc || S.desc.code !== spec.screen_code) {
      if (!await ask("Not described yet", `${spec.screen_code} has not been described in this session. The playbook describes first, so the scope is chosen from evidence. Record anyway?`, { yes: "Record anyway", icon: "warn" })) return;
    }
    if (dry) {
      runTask("record", body, { done: (o) => resBanner.set(o.ok ? "Dry run: everything was applied and Inquiry was NOT clicked. Read the Activity lines - every value is read back." : `Dry run did not finish: ${o.error}`, o.ok ? "ok" : "err") });
      return;
    }
    const details = [["Screen", spec.screen_code], ["Division", spec.division || "(screen's own)"],
      ["Period", spec.date_from ? `${spec.date_from} - ${spec.date_to}` : "(no date)"], ["Verify", spec.verify || "-"],
      ["Filters", Object.entries(spec.sets).map(([k, v]) => `${k}=${v}`).join(", ") || "-"],
      ["Options", spec.options.join(", ") || "-"], ["Files", spec.export]];
    if (!await ask(`Record ${spec.screen_code}?`, "It runs the screen with this scope (read-only), then replays it bare and checks every item. Stop is always one click away.", { yes: "● Record + check", kind: "success", details })) return;
    runTask("record", body, { done: (v) => { showCheck(v); pages.reports.refresh(); } });
  }
  function showCheck(v, c) {
    S.lastCheck = v;
    if (c) code.value = c;
    checksT.fill(v.checks.map((x, i) => ({ key: i, tag: CHECK_TAG[x.status], cells: { s: CHECK_ICON[x.status], name: x.name, detail: x.detail } })));
    const text = { "PASSED": "Record check PASSED - every item proven. The screen is ready for batches and schedules.",
      "PASSED WITH WARNINGS": "Record check PASSED WITH WARNINGS - read every '!' line below; they are not hidden failures but things to know.",
      "FAILED": "Record check FAILED - the '✕' lines say what was not proven. The screen is NOT ready; fix the scope and record again." }[v.verdict];
    resBanner.set(text, { "PASSED": "ok", "PASSED WITH WARNINGS": "warn" }[v.verdict] || "err");
    confirmBox.classList.toggle("hidden", !v.confirmable);
  }
  async function confirmPeriod() {
    const v = S.lastCheck; if (!v) return;
    const sp = v.spread || {};
    const outside = Object.entries(sp.outside || {}).map(([d, n]) => `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)} (${n})`).join(", ");
    if (!await ask("Confirm the period on the G-MES screen", "Open the screen in G-MES with the same period and look at the rows. If G-MES itself lists these rows for this period, confirm. It is kept with this exact pattern: a later run whose rows fall outside the period differently warns again.",
      { yes: "Confirm", kind: "success", details: [["Screen", v.code], ["Period", v.period || "-"], ["Date column", sp.column || "-"],
        ["In the period", `${fmtInt(sp.inside)} rows`], ["Outside", outside || "-"]] })) return;
    const r = await call("/api/confirm", {}, "Nothing to confirm");
    if (r) { showCheck(r.check); pages.reports.refresh(); }
  }
  return { el, showCheck, describeCode, show: () => {} };
};

async function browse(inputEl, title = "Save the files in") {
  const r = await call("/api/pick-folder", { title });
  if (r && r.path) inputEl.value = r.path;
}

// ==========================================================================
// Run & Batch
// ==========================================================================
pages.batch = () => {
  const el = page("batch", "Run & Batch", "Several recorded screens, one after another, in ONE browser session. Save the choice as a batch to run it again or to schedule it.");
  const batchSel = select([["", "(no saved batch)"]]);
  batchSel.addEventListener("change", () => loadBatch());
  const t = table([{ key: "code", title: "Screen", width: "8rem" }, { key: "title", title: "Title" }, { key: "replays", title: "Replays with" }],
    { multi: true, onSelect: () => countSel(), empty: "Nothing is recorded on this PC yet." });
  const sel = h("div", { class: "note" });
  const left = card("Screens", { fill: true, sub: "Ctrl / Shift to choose several" });
  left.body.append(h("div", { class: "row" }, h("div", { class: "grow" }, batchSel),
    h("button", { class: "btn", text: "Save as batch...", onclick: () => saveBatch() }),
    h("button", { class: "btn", text: "Schedule it...", onclick: () => scheduleIt() }),
    h("button", { class: "btn ghost", text: "Delete", onclick: () => deleteBatch() })), t.el, sel);

  const policy = seg([["yesterday", "Yesterday"], ["today", "Today"], ["lastweek", "Last week"], ["thisweek", "This week"], ["keep", "As recorded"], ["date", "Choose..."]], "yesterday");
  const date = input(ymd(1), { style: "max-width:14rem" });
  const exportSeg = seg([["xlsx", "Excel"], ["csv", "CSV only"]], "xlsx");
  const out = input("", { placeholder: "empty = a new batch_<time> folder" });
  const how = card("How to run them");
  how.body.append(field("Dates", h("div", { class: "row" }, policy, date, h("span", { class: "tiny faint", text: "YYYYMMDD or FROM:TO" }))),
    field("Files", exportSeg),
    field("Save the files in", h("div", { class: "row" }, h("div", { class: "grow" }, out), h("button", { class: "btn", text: "Browse", onclick: () => browse(out) }))),
    h("div", { class: "row" },
      h("button", { class: "btn", text: "Plan (no browser)", busy: true, onclick: () => makePlan() }),
      h("button", { class: "btn success lg", text: "▶ Run", busy: true, onclick: () => run(true) })));
  const resBanner = banner("Choose screens on the left, then Plan or Run.");
  const res = table([{ key: "code", title: "Screen", width: "8rem" }, { key: "dates", title: "Dates", width: "10rem" },
    { key: "status", title: "Status", width: "8rem" }, { key: "rows", title: "Rows", num: true, width: "5rem" }, { key: "detail", title: "Detail" }],
    { empty: "No plan yet." });
  const resCard = card("Plan and results", { fill: true });
  resCard.body.append(resBanner, res.el, h("div", { class: "row" },
    h("button", { class: "btn ghost", text: "Open the summary", onclick: () => { if (last && (last.summary || last.report)) call("/api/open", { path: last.summary || last.report }); } }),
    h("button", { class: "btn ghost", text: "Open the files", onclick: () => { if (outDir) call("/api/open", { path: outDir }); } })));
  el.append(columns("batch", 0.38, h("div", { class: "col" }, left), h("div", { class: "col" }, how, resCard)));

  let batches = {}, recordedCount = 0, last = null, outDir = "";
  async function refresh() {
    try {
      const [lib, b] = await Promise.all([api("/api/library"), api("/api/batches")]);
      const cards = lib.cards.filter((c) => c.recorded);
      recordedCount = cards.length;
      t.fill(cards.map((c) => ({ key: c.code, cells: { code: c.code, title: c.title, replays: c.replays } })));
      batches = b.batches;
      batchSel.setOptions([["", "(no saved batch)"], ...Object.keys(batches).sort()]);
    } catch (e) { localLog(`PROBLEM: ${e.message}`, "err"); }
    countSel();
  }
  function countSel() {
    const n = t.selected().length;
    sel.textContent = !recordedCount ? "Nothing is recorded on this PC yet - record a screen first, or import recordings on the Reports page."
      : (n ? `${n} chosen` : "Nothing chosen yet.");
  }
  const getPolicy = () => policy.get() === "date" ? date.value.trim() : policy.get();
  function loadBatch() {
    const b = batches[batchSel.value]; if (!b) return;
    const have = new Set(t.rows().map((r) => r.key));
    t.select(b.screens.filter((c) => have.has(c)));
    const missing = b.screens.filter((c) => !have.has(c));
    const pol = b.date || "yesterday";
    if (["yesterday", "today", "lastweek", "thisweek", "keep"].includes(pol)) policy.set(pol); else { policy.set("date"); date.value = pol; }
    exportSeg.set(b.export === "csv" ? "csv" : "xlsx");                 // "both" = Excel (98.1)
    out.value = b.output_dir || "";
    if (missing.length) localLog(`Batch ${batchSel.value}: not recorded here - ${missing.join(", ")}`, "warn");
  }
  async function saveBatch() {
    const codes = t.selected();
    if (!codes.length) { await tell("Choose screens", "Choose the screens of the batch first."); return; }
    const name = await promptText("Save as batch", "A name - letters, digits, - or _", batchSel.value);
    if (!name) return;
    const r = await call("/api/batch/save", { name, codes, policy: getPolicy(), export: exportSeg.get(), out_dir: out.value }, "Not saved");
    if (r) { batches = r.batches; batchSel.setOptions([["", "(no saved batch)"], ...Object.keys(batches).sort()], name); }
    return r ? name : null;
  }
  // From a list of screens to a schedule in one step: save the batch if it is new or
  // changed, then open Schedules with it chosen (the old way was three pages apart)
  async function scheduleIt() {
    let name = batchSel.value;
    const saved = batches[name];
    const codes = t.selected();
    const same = saved && codes.length && codes.length === saved.screens.length && codes.every((c) => saved.screens.includes(c));
    if (!saved || (codes.length && !same)) { name = await saveBatch(); if (!name) return; }
    show("schedules");
    await pages.schedules.show();
    pages.schedules.prefill(name);
  }
  async function deleteBatch() {
    const name = batchSel.value; if (!name) return;
    if (!await ask(`Delete batch '${name}'?`, "Only the saved list is removed; recordings and files stay. A schedule that runs it will fail until the batch exists again.", { yes: "Delete", kind: "danger", icon: "warn" })) return;
    const r = await call("/api/batch/delete", { name });
    if (r) { batches = r.batches; batchSel.setOptions([["", "(no saved batch)"], ...Object.keys(batches).sort()], ""); }
  }
  function showPlan(plan) {
    res.fill(plan.map((i) => ({ key: i.code, tag: i.ready ? "" : "warn",
      cells: { code: i.code, dates: i.dates || "-", status: i.ready ? "ready" : "skipped", rows: "", detail: i.blocked || i.notes.join("; ") || "ready" } })));
  }
  async function makePlan() {
    const codes = t.selected(); if (!codes.length) return null;
    let r;
    try { r = await api("/api/plan", { codes, policy: getPolicy(), export: exportSeg.get(), out_dir: out.value }); }
    catch (e) { await tell("Check the dates", e.message, "warn"); return null; }
    showPlan(r.plan);
    const ready = r.plan.filter((i) => i.ready).length;
    resBanner.set(`Plan: ${ready} ready, ${r.plan.length - ready} skipped (the reason is on its line). Nothing was run.`, ready ? "info" : "warn");
    return r.plan;
  }
  async function run(confirm) {
    const plan = await makePlan(); if (!plan) return;
    const ready = plan.filter((i) => i.ready).length; if (!ready) return;
    if (confirm && !await ask(`Run ${ready} screen(s)?`, "One after another in one browser session; each is checked on its own, and a report is written at the end. Stop is always one click away.",
      { yes: "▶ Run", kind: "success", details: [["Dates", getPolicy()], ["Files", exportSeg.get()], ["Folder", out.value || "a new batch_<time> folder"]] })) return;
    resBanner.set(`Running ${ready} screen(s)...`);
    runTask("batch", { codes: t.selected(), policy: getPolicy(), export: exportSeg.get(), out_dir: out.value, batch_name: batchSel.value || null }, {
      done: (o) => {
        last = o; outDir = o.out_dir;
        for (const r of o.results) if (r.status !== "ok") res.setCell(r.screen, "status", r.status.replace(/_/g, " "), r.status === "failed" ? "err" : "warn");
        const c = o.counts, total = o.results.length;
        resBanner.set(`${c.ok || 0} of ${total} delivered` + (c.failed ? `, ${c.failed} failed` : "") + (c.not_run ? `, ${c.not_run} not run` : "") +
          (c.blocked ? `, ${c.blocked} skipped` : "") + (o.stopped ? "  -  stopped by you" : "") + ".  The report is in History.",
          c.ok === total ? "ok" : (c.ok ? "warn" : "err"));
        pages.reports.refresh();
      },
      failed: (err) => { resBanner.set(`The run ended early: ${err}`, "err"); tell("The run ended early", err, "err"); },
      stopped: () => resBanner.set("Stopped by you before the batch report was written.", "warn"),
    });
  }
  function row(e) {
    res.setCell(e.code, "status", e.status, e.tag);
    if (e.rows !== undefined) res.setCell(e.code, "rows", fmtInt(e.rows));
    if (e.detail !== undefined) res.setCell(e.code, "detail", e.detail);
  }
  async function runCodes(codes, pol) {
    show("batch");
    await refresh();
    t.select(codes);
    if (["yesterday", "today", "lastweek", "thisweek", "keep"].includes(pol)) policy.set(pol);
    run(false);
  }
  return { el, show: refresh, row, showPlan, runCodes };
};

// ==========================================================================
// Schedules
// ==========================================================================
const DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const fmtWhen = (iso) => iso ? iso.replace("T", " ").slice(0, 16) : "-";
pages.schedules = () => {
  const el = page("schedules", "Schedules", "A saved batch, run by Windows Task Scheduler at a set time - while this Windows user is signed in (the login is encrypted for this account). A PC that was asleep runs it when it wakes. The app window may stay open: it lends the browser to a schedule between its own tasks.");
  // ---- left: what is scheduled ------------------------------------------------
  const t = table([{ key: "batch", title: "Batch", width: "9rem" }, { key: "when", title: "Runs" },
    { key: "dates", title: "Exports" }, { key: "screens", title: "Screens", width: "5rem", num: true },
    { key: "next", title: "Next run", width: "9rem" }, { key: "result", title: "Last result" }],
    { onSelect: () => picked(), empty: "No schedule yet." });
  const notes = banner("Reading Task Scheduler...");
  const btnRun = h("button", { class: "btn primary", text: "▶ Run now", busy: true, onclick: () => runNow() });
  const btnPause = h("button", { class: "btn", text: "Pause", busy: true, onclick: () => pauseResume() });
  const left = card("This app's schedules", { fill: true, sub: "Click one to see it, change it, run it now, pause or delete it" });
  left.body.append(t.el, notes, h("div", { class: "row" },
    h("button", { class: "btn ghost", text: "Refresh", onclick: () => refresh() }), btnRun, btnPause,
    h("button", { class: "btn danger", text: "Delete", busy: true, onclick: () => remove() })));
  // ---- right: one form for a new schedule AND for changing one ----------------
  const formTitle = h("h3", { text: "New schedule" });
  const batchSel = select([]);
  batchSel.addEventListener("change", () => batchChosen());
  const batchInfo = h("div", { class: "note" });
  const policy = seg([["yesterday", "Yesterday"], ["today", "Today"], ["lastweek", "Last week"], ["keep", "As recorded"]], "yesterday", () => policyNote());
  const policyHint = h("div", { class: "note" });
  const time = input("06:30", { style: "max-width:8rem", placeholder: "HH:MM" });
  const kind = seg([["daily", "Every day"], ["weekdays", "Mon - Fri"], ["days", "Chosen days"]], "weekdays", () => daysShown());
  const dayBoxes = {};
  const days = h("div", { class: "row" }, DAY_NAMES.map((d) => {
    const cb = h("input", { type: "checkbox", checked: !["sat", "sun"].includes(d) }); dayBoxes[d] = cb;
    return h("label", { class: "check" }, cb, d[0].toUpperCase() + d.slice(1));
  }));
  const saveBtn = h("button", { class: "btn success lg", text: "Save schedule", busy: true, onclick: () => save() });
  const right = card(null);
  right.body.append(h("div", { class: "row", style: "margin-bottom:.4rem" }, h("div", { class: "grow" }, formTitle),
      h("button", { class: "btn ghost", text: "+ New", onclick: () => newForm() })),
    field("Batch", h("div", {}, batchSel, batchInfo), "the screens to run - make one on Run & Batch"),
    field("Which day's data", h("div", {}, policy, policyHint)),
    field("Time", time, "24 hour, e.g. 06:30"),
    field("Days", h("div", { style: "display:flex;flex-direction:column;gap:.5rem" }, kind, days)),
    saveBtn,
    h("div", { class: "note", style: "margin-top:.8rem", text: "Saving a batch's schedule again replaces it - one schedule per batch. Prove a new one once with Run now; its report appears in History." }));
  el.append(columns("schedules", 0.62, h("div", { class: "col" }, left), h("div", { class: "col scroll" }, right)));

  let tasks = [], batches = {};
  const current = () => tasks.find((x) => x.batch === t.selected()[0]);
  function daysShown() { days.classList.toggle("hidden", kind.get() !== "days"); }
  function policyNote() {
    policyHint.textContent = { yesterday: "Every run exports the day before it runs - the usual morning report.",
      today: "Every run exports the day it runs, up to that moment.",
      lastweek: "Every run exports the whole week before it (Monday to Sunday) - for weekly reports; schedule it on Monday.",
      keep: "Every run exports the SAME dates each screen was recorded with - rarely what a schedule is for." }[policy.get()];
  }
  function batchChosen() {
    const b = batches[batchSel.value];
    if (!b) { batchInfo.textContent = "Save a batch on Run & Batch first - it is the list of screens a schedule runs."; return; }
    batchInfo.textContent = `${b.screens.length} screen(s): ${b.screens.slice(0, 8).join(", ")}${b.screens.length > 8 ? ", ..." : ""}`;
    const p = b.date || "yesterday";
    policy.set(["yesterday", "today", "lastweek", "thisweek", "keep"].includes(p) ? p : "yesterday");   // a fixed date is not a schedule
    policyNote();
  }
  function newForm() {
    t.select([]); formTitle.textContent = "New schedule"; saveBtn.textContent = "Save schedule";
    time.value = "06:30"; kind.set("weekdays"); daysShown(); batchChosen();
  }
  function fillFrom(x) {
    formTitle.textContent = `Change '${x.batch}'`; saveBtn.textContent = "Save changes";
    batchSel.value = x.batch; batchChosen();
    if (x.at) time.value = x.at;
    const wd = ["mon", "tue", "wed", "thu", "fri"];
    if (x.kind === "daily") kind.set("daily");
    else if (x.kind === "weekly" && x.days.length === 5 && wd.every((d) => x.days.includes(d))) kind.set("weekdays");
    else if (x.kind === "weekly") { kind.set("days"); DAY_NAMES.forEach((d) => { dayBoxes[d].checked = x.days.includes(d); }); }
    daysShown();
  }
  function picked() {
    const x = current();
    if (!x) { paintNotes(); return; }
    fillFrom(x); paintNotes();
    btnPause.textContent = String(x.state).toLowerCase() === "disabled" ? "Resume" : "Pause";
  }
  function paintNotes() {
    const x = current();
    if (!tasks.length) { notes.set("No schedule yet. Save a batch on Run & Batch (or press 'Schedule it' there), then save its schedule on the right.", "info"); return; }
    if (!x) {
      const bad = tasks.filter((y) => y.notes.length).length;
      notes.set(bad ? `${bad} schedule(s) need attention - click one to see why.` : `${tasks.length} schedule(s), no problem seen.`, bad ? "warn" : "ok");
      return;
    }
    const last = x.last_run ? `Last run ${fmtWhen(x.last_run)}: ${x.last_text || "-"}.` : "Has not run yet - prove it once with Run now.";
    notes.set(`${x.batch}: ${x.when || x.trigger} - ${x.dates || "?"}. ${last}` + (x.notes.length ? `  ⚠ ${x.notes.join("  ·  ")}` : ""),
      x.notes.length ? "warn" : (x.last_ok ? "ok" : "info"));
  }
  async function refresh() {
    try {
      batches = (await api("/api/batches")).batches;
      const keep = batchSel.value;
      batchSel.setOptions(Object.keys(batches).sort(), keep);
      tasks = (await api("/api/schedules")).tasks;
    } catch (e) { notes.set(`Task Scheduler could not be read: ${e.message}`, "err"); return; }
    const sel = t.selected();
    t.fill(tasks.map((x) => ({ key: x.batch, tag: x.notes.length ? "warn" : (x.last_ok ? "ok" : ""),
      cells: { batch: x.batch, when: (String(x.state).toLowerCase() === "disabled" ? "PAUSED - " : "") + (x.when || x.trigger || "-"),
        dates: x.dates || "-", screens: (x.screens || []).length, next: fmtWhen(x.next_run), result: x.last_text || "-" } })));
    if (sel.length && tasks.some((x) => x.batch === sel[0])) t.select(sel); else batchChosen();
    paintNotes();
  }
  async function runNow() {
    const x = current(); if (!x) { await tell("Choose a schedule", "Click the schedule to run in the list."); return; }
    if (!await ask(`Run '${x.batch}' now?`, `Windows starts it now in the background, exactly as at its time: ${x.screens.length} screen(s), ${x.dates}. Its report appears in History when it is done.`, { yes: "▶ Run now" })) return;
    runTask("schedule_run", { batch: x.batch }, { done: () => { localLog(`Started '${x.batch}' - it runs in the background; History shows the report.`, "ok"); refresh(); } });
  }
  function pauseResume() {
    const x = current(); if (!x) return;
    const off = String(x.state).toLowerCase() === "disabled";
    runTask(off ? "schedule_resume" : "schedule_pause", { batch: x.batch }, { done: () => { localLog(`${off ? "Resumed" : "Paused"} '${x.batch}'.`, "ok"); refresh(); } });
  }
  async function remove() {
    const x = current(); if (!x) return;
    if (!await ask(`Delete the schedule '${x.batch}'?`, "Windows will not run it any more. The batch itself, its recordings and its reports are kept.", { yes: "Delete", kind: "danger", icon: "warn" })) return;
    runTask("schedule_delete", { batch: x.batch }, { done: () => { localLog(`Deleted the schedule '${x.batch}'.`, "ok"); newForm(); refresh(); } });
  }
  async function save() {
    const batch = batchSel.value;
    if (!batch || !batches[batch]) { await tell("Choose a batch", "Save a batch on Run & Batch first - it is the list of screens a schedule runs."); return; }
    const body = { batch, time: time.value, kind: kind.get(), policy: policy.get(),
      days: Object.entries(dayBoxes).filter(([, c]) => c.checked).map(([d]) => d) };
    let w;
    try { w = await api("/api/when", body); } catch (e) { await tell("Check the time", e.message, "warn"); return; }
    const replacing = tasks.some((x) => x.batch === batch);
    const b = batches[batch];
    if (!await ask(replacing ? `Change the schedule of '${batch}'?` : `Schedule '${batch}'?`,
      `Windows Task Scheduler will run it ${w.text}.` + (replacing ? " This replaces its current schedule." : ""),
      { yes: replacing ? "Save changes" : "Save schedule", kind: "success",
        details: [["Screens", `${b.screens.length}: ${b.screens.slice(0, 6).join(", ")}${b.screens.length > 6 ? ", ..." : ""}`],
          ["Exports", { yesterday: "yesterday's data", today: "today's data", lastweek: "last week's data (Monday to Sunday)", thisweek: "this week so far", keep: "the recorded dates" }[body.policy]], ["When", w.text]] })) return;
    runTask("schedule_create", body, { done: () => { localLog(`Schedule saved: '${batch}' ${w.text}.`, "ok"); refresh().then(() => t.select([batch])); } });
  }
  function prefill(name) { t.select([]); newForm(); batchSel.value = name; batchChosen(); }
  daysShown(); policyNote();
  return { el, show: refresh, prefill };
};

// ==========================================================================
// Row export
// ==========================================================================
pages.rowexport = () => {
  const el = page("rowexport", "Row export", "One Excel file per row of a list: double-click the row's link (e.g. Insp. Result on Q321KUM00 Detail Inspection) -> detail popup -> Excel -> only the chosen grids.");
  const f = {};
  f.screen = input();
  const [div, divList] = datalistInput("dl-org", ["MAIN Part", "LCM Part", "SMD Part", "PBA Part", "OCM", "MKD Part", "KD Part", "VD"]);
  f.division = div;
  f.mode = seg([["Monthly", "Monthly"], ["Daily", "Daily"]], "Monthly");
  const [which, whichList] = datalistInput("dl-which", ["previous"], "", { placeholder: "empty = now; previous; or 202609" });
  f.period = which;
  f.model = input("", { placeholder: "optional" });
  f.status = input("", { placeholder: "empty = every status" });
  f.start = input("1", { type: "number", min: "1" });
  f.count = input("0", { type: "number", min: "0" });
  f.grids = input();
  f.out = input("", { placeholder: "empty = data\\output" });
  f.skip = h("input", { type: "checkbox" });
  f.onerr = seg([["stop", "Stop at a failed row"], ["skip", "Skip it and go on"]], "stop");
  const c1 = card("List", { step: 1 });
  c1.body.append(h("div", { class: "grid2" }, field("Screen", f.screen), field("Organization", h("div", {}, div, divList))),
    h("div", { class: "grid2" }, field("Period", f.mode), field("Which", h("div", {}, which, whichList))),
    h("div", { class: "grid2" }, field("Model", f.model, "optional"), field("Only rows showing", f.status, "empty = every status")));
  const c2 = card("Rows and files", { step: 2 });
  c2.body.append(h("div", { class: "grid2" }, field("Start at row No.", f.start), field("How many", f.count, "0 = all")),
    field("Grids to tick in 'Save to Excel'", f.grids),
    field("Save the files in", h("div", { class: "row" }, h("div", { class: "grow" }, f.out), h("button", { class: "btn", text: "Browse", onclick: () => browse(f.out) }))),
    h("label", { class: "check", style: "margin-bottom:.6rem" }, f.skip, "Skip rows whose file already exists (resume)"), f.onerr);

  const head = h("div", { style: "font-size:1.3rem;font-weight:600", text: "Load the list first" });
  const sub = h("div", { class: "note" });
  const btnLoad = h("button", { class: "btn primary lg", text: "Load the list", onclick: () => load() });
  const btnStart = h("button", { class: "btn success lg", text: "▶ Start export", onclick: () => start() });
  const btnPause = h("button", { class: "btn lg", text: "❚❚ Pause", onclick: () => pause() });
  const tiles = {};
  const tileBox = h("div", { class: "tiles" }, [["found", "In the list", "var(--faint)"], ["todo", "To export", "var(--accent)"], ["ok", "Exported", "var(--ok)"],
    ["skipped", "Skipped", "var(--warn)"], ["failed", "Failed", "var(--err)"], ["eta", "Time left", "var(--header2)"]].map(([k, cap, col]) => {
    const v = h("div", { class: "val", text: "-" }); tiles[k] = v;
    return h("div", { class: "tile", style: `border-left-color:${col}` }, h("div", { class: "cap", text: cap }), v);
  }));
  const bar = h("progress", { max: "100", value: "0" });
  const prog = h("div", { class: "note" });
  const runCard = card("Run");
  runCard.body.append(head, sub, h("div", { class: "row", style: "margin:.8rem 0" }, btnLoad, btnStart, btnPause), tileBox,
    h("div", { style: "margin-top:.8rem" }, bar), prog);
  el.append(columns("rowexport", 0.42, h("div", { class: "col scroll" }, c1, c2), h("div", { class: "col" }, runCard)));

  let loaded = false, paused = false, running = false;
  function form() {
    return { screen_code: f.screen.value, division: f.division.value, period_mode: f.mode.get(), period: f.period.value,
      model: f.model.value, link_value: f.status.value, start_row: f.start.value, count: f.count.value,
      grids: f.grids.value, out_dir: f.out.value, skip_existing: f.skip.checked, on_error: f.onerr.get() };
  }
  function state() {
    btnLoad.disabled = S.busy;
    btnStart.disabled = S.busy || !loaded;
    btnPause.disabled = !running;
  }
  function fill(s) {
    f.screen.value = s.screen_code || "Q321KUM00"; f.division.value = s.division || ""; f.mode.set(s.period_mode || "Monthly");
    f.period.value = s.period || "";
    const model = (s.extra_filters || []).find((x) => x.startsWith("Model="));
    f.model.value = model ? model.slice(6) : "";
    f.status.value = s.link_value || ""; f.start.value = s.start_row || 1; f.count.value = s.count || 0;
    f.grids.value = (s.dialog_grids || []).join(", "); f.out.value = s.out_dir || "";
    f.skip.checked = s.skip_existing !== false; f.onerr.set(s.on_error || "stop");
  }
  let filled = false;
  async function showPage() {
    try {
      const r = await api("/api/rowexport");
      if (!filled) { fill(r.settings); filled = true; }
      if (r.loaded && !loaded) { loaded = true; tiles.found.textContent = fmtInt(r.loaded.total); head.textContent = `${fmtInt(r.loaded.total)} rows loaded`; }
    } catch (e) { /* the form keeps its defaults */ }
    state();
  }
  function loadedText(r) {
    tiles.found.textContent = fmtInt(r.total); tiles.todo.textContent = fmtInt(r.todo);
    head.textContent = `${fmtInt(r.total)} rows loaded - ${fmtInt(r.can)} to export`;
    const detail = Object.entries(r.counts || {}).map(([k, v]) => `${k || "(blank)"} ${fmtInt(v)}`).join("  ·  ");
    const sort = Object.keys(r.sorted_by || {}).length ? `   ⚠ the G-MES list is SORTED by ${Object.entries(r.sorted_by).map(([k, v]) => `${k} ${v}`).join(", ")}` : "";
    sub.textContent = `${r.division} · ${r.mode} ${r.period} · ${detail}${sort}`;
  }
  function load() {
    // the old list is gone the moment a new one is asked for: Start must never export
    // rows that were loaded for other settings (the server forgets it too)
    loaded = false; head.textContent = "Loading the list..."; sub.textContent = "";
    ["found", "todo"].forEach((k) => { tiles[k].textContent = "-"; });
    state();
    runTask("rowexport_load", form(), {
      done: (r) => { loaded = true; loadedText(r); state(); },
      failed: (err) => { head.textContent = "The list did not load"; sub.textContent = err; tell("The list did not load", err, "err"); },
    });
  }
  async function start() {
    const fm = form();
    if (!await ask("Start the export?", `From row ${fm.start_row}${Number(fm.count) ? `, ${fm.count} row(s)` : ", every row that remains"}. Stop (or Esc) at any moment.`, { yes: "▶ Start", kind: "success" })) return;
    ["ok", "skipped", "failed"].forEach((k) => { tiles[k].textContent = "0"; });
    bar.value = 0; paused = false; btnPause.textContent = "❚❚ Pause";
    await runTask("rowexport_start", fm, {
      done: (s) => {
        const text = `${fmtInt(s.ok)} exported, ${fmtInt(s.skipped)} skipped, ${fmtInt(s.failed)} failed`;
        head.textContent = (s.stopped || s.fatal ? "Stopped - " : "Finished - ") + text;
        if (s.next_row && (s.stopped || s.fatal)) { f.start.value = s.next_row; localLog(`'Start at row No.' is now ${fmtInt(s.next_row)} - Start export carries on.`, "info"); }
        if (s.fatal) tell("The run stopped", s.fatal, "err");
      } });
  }
  async function pause() {
    const want = !paused;
    if (!await call("/api/rowexport/pause", { pause: want })) return;   // unchanged if it did not reach the app
    paused = want;
    btnPause.textContent = paused ? "▶ Resume" : "❚❚ Pause";
  }
  function progress(e) {
    bar.max = Math.max(1, e.total); bar.value = e.done;
    tiles.ok.textContent = fmtInt(e.ok); tiles.skipped.textContent = fmtInt(e.skipped); tiles.failed.textContent = fmtInt(e.failed);
    tiles.eta.textContent = e.eta ? fmtSecs(e.eta) : "-";
    prog.textContent = `${fmtInt(e.done)} of ${fmtInt(e.total)} · last row ${fmtInt(e.row)}`;
  }
  // "running" follows the app's own task, not the click: a run that ended before the
  // click's reply arrived used to leave Pause enabled with nothing to pause
  function onBusy(b) {
    running = b && !!S.task && S.task.name === "Row export";
    if (!running && paused) { paused = false; btnPause.textContent = "❚❚ Pause"; }
    state();
  }
  return { el, show: showPage, progress, onBusy };
};

// ==========================================================================
// History
// ==========================================================================
pages.history = () => {
  const el = page("history", "History", "Every run's report - batches, scheduled nights and runs from the Reports page.");
  const runsT = table([{ key: "started", title: "Started" }, { key: "name", title: "Batch" }, { key: "result", title: "Result" }],
    { onSelect: () => showRun(), empty: "No run yet." });
  const left = card("Runs", { fill: true });
  left.body.append(runsT.el, h("div", { class: "row" },
    h("button", { class: "btn", text: "Refresh", onclick: () => refresh() }),
    h("button", { class: "btn", text: "Self-test", busy: true, onclick: () => runTask("selftest", {}, { done: () => {} }) }),
    h("button", { class: "btn ghost", text: "Support package", busy: true, onclick: () => runTask("support", {}, { done: (p) => {
      localLog(`Support package: ${p} - logs and settings, never passwords.`, "ok"); if (p) call("/api/open", { path: dirname(p) }); } }) })));
  const detT = table([{ key: "screen", title: "Screen", width: "8rem" }, { key: "status", title: "Status", width: "7rem" },
    { key: "rows", title: "Rows", num: true, width: "5rem" }, { key: "dates", title: "Dates", width: "9rem" }, { key: "detail", title: "Detail" }],
    { empty: "Choose a run on the left." });
  const right = card("Screens in the selected run", { fill: true });
  right.body.append(detT.el, h("div", { class: "row" },
    h("button", { class: "btn ghost", text: "Open the summary", onclick: () => { const r = cur(); if (r) call("/api/open", { path: r.summary || r.path }); } }),
    h("button", { class: "btn ghost", text: "Open the files", onclick: () => { const r = cur(); if (r && r.output_dir) call("/api/open", { path: r.output_dir }); } })));
  el.append(columns("history", 0.4, h("div", { class: "col" }, left), h("div", { class: "col" }, right)));
  let runs = [];
  const cur = () => runs.find((r) => r.path === runsT.selected()[0]);
  async function refresh() {
    try { runs = (await api("/api/history")).runs; } catch (e) { localLog(`PROBLEM: ${e.message}`, "err"); return; }
    // keyed by the report file: a new run must not move the selection to another one
    runsT.fill(runs.map((r) => { const ok = r.counts.ok || 0;
      return { key: r.path, tag: ok === r.total ? "ok" : (ok ? "warn" : "err"), cells: { started: r.started, name: r.name || "-", result: `${ok} of ${r.total} delivered` } }; }));
    showRun();
  }
  function showRun() {
    const r = cur();
    detT.fill(!r ? [] : r.results.map((x, i) => ({ key: i, tag: { ok: "ok", failed: "err" }[x.status] || "warn",
      cells: { screen: x.screen, status: String(x.status || "").replace(/_/g, " "), rows: fmtInt(x.rows || 0), dates: x.dates || "-",
        detail: x.status === "ok" ? ((x.files || []).map((p) => p.split(/[\\/]/).pop()).join(", ") || (x.notes || []).join("; ")) : (x.error || "") } })));
  }
  return { el, show: refresh };
};

// ==========================================================================
// Account & Browser
// ==========================================================================
pages.account = () => {
  const el = page("account", "Account & Browser", "Each person saves their OWN Knox / G-MES login on their own PC, and chooses whose browser profile the automation starts from.");
  const ready = {};
  const readyBox = h("div", { class: "ready-grid" }, [["login", "G-MES login"], ["browser", "Chrome / Edge"], ["copy", "Browser copy"], ["folder", "Data folder"]].map(([k, label]) => {
    const dot = h("div", { class: "dot info", text: "…" }), det = h("div", { class: "small muted", text: "checking..." });
    ready[k] = [dot, det];
    return h("div", { class: "ready" }, dot, h("div", {}, h("b", { text: label }), det));
  }));
  const pc = card("This PC", { sub: "Everything a run needs, checked without signing in" });
  pc.body.append(readyBox);
  const loginBanner = banner("");
  const user = input("", { autocomplete: "off" });
  const pw1 = input("", { type: "password", autocomplete: "new-password" });
  const pw2 = input("", { type: "password", autocomplete: "new-password" });
  const showBtn = h("button", { class: "btn", text: "Show", onclick: () => { const on = pw1.type === "password"; pw1.type = pw2.type = on ? "text" : "password"; showBtn.textContent = on ? "Hide" : "Show"; } });
  const login = card("G-MES login", { step: "A", sub: "The Knox / G-MES account this PC signs in with" });
  login.body.append(loginBanner, h("div", { style: "height:.7rem" }), field("Knox / G-MES user ID", user),
    field("Password", h("div", { class: "row" }, h("div", { class: "grow" }, pw1), showBtn)), field("Password again", pw2),
    h("div", { class: "row" }, h("button", { class: "btn primary", text: "Save login", onclick: () => save() }),
      h("button", { class: "btn", text: "Test sign-in", busy: true, onclick: () => runTask("test_signin", {}, { done: (w) => localLog(`Sign-in works (${w}).`, "ok") }) })),
    h("div", { class: "note", style: "margin-top:.7rem", text: "Encrypted with Windows (DPAPI) for this Windows account only. It is never shown, logged or written anywhere else, and only typed into the Samsung sign-in page." }));
  const choice = seg([["auto", "Automatic (Windows default)"], ["chrome", "Chrome"], ["edge", "Edge"]], "auto");
  const rows = h("div", {});
  const brBanner = banner("Checking the browsers...");
  const browser = card("Browser", { step: "B", sub: "Whose browser profile the automation starts from" });
  browser.body.append(choice, h("div", { style: "height:.7rem" }), rows, brBanner,
    h("button", { class: "btn primary", style: "margin-top:.7rem", text: "Use this browser", busy: true, onclick: () => apply() }),
    h("div", { class: "note", style: "margin-top:.7rem", text: "On the first run the tool makes its OWN copy of that browser's profile, once, so an existing G-MES session comes along. The person's own browser is only read. Their extensions are switched off in the automation browser." }));
  el.append(h("div", { class: "col scroll", style: "flex:1" }, pc, h("div", { class: "grid2", style: "gap:.85rem;align-items:start" }, login, browser)));

  let saved = null;
  const setReady = (k, tone, text) => { ready[k][0].className = `dot ${tone}`; ready[k][0].textContent = tone === "ok" ? "✓" : "!"; ready[k][1].textContent = text; };
  async function refresh() {
    let a;
    try { a = await api("/api/account"); } catch (e) { loginBanner.set(e.message, "err"); return; }
    saved = a.user;
    if (a.user) { loginBanner.set(`Saved for Windows user '${a.windows_user}': Knox ID ${a.user}. Type a new one below only to replace it.`, "ok"); setReady("login", "ok", `saved (${a.user})`); }
    else { loginBanner.set(a.problem ? `${a.problem}.` : "No login saved on this PC yet.", "warn"); setReady("login", "err", "not saved yet"); }
    $("#nav-account-badge").textContent = a.user ? "" : "●";
    setReady("folder", "ok", "data\\ beside the app");
    choice.set(a.choice);
    clear(rows);
    const info = a.browsers;
    for (const br of info.browsers) {
      const p = br.profiles[0];
      rows.append(h("div", { class: "browser-cell" },
        h("div", { class: "row" }, h("b", { text: br.label }), info.default === br.key ? h("span", { class: "tag", text: "WINDOWS DEFAULT" }) : null,
          h("div", { class: "spacer" }), h("span", { class: `small ${br.installed ? "tag-ok" : "faint"}`, text: br.installed ? "installed" : "not installed" })),
        h("div", { class: "small muted", text: p ? `Profile to copy: '${p.name}' · ${{ true: "has used G-MES", false: "no G-MES use seen" }[p.gmes] || "G-MES use unknown"}` : "-" })));
    }
    brBanner.set(a.sentence, a.ready ? "ok" : "info");
    const installed = info.browsers.filter((b) => b.installed);
    setReady("browser", installed.length ? "ok" : "err", installed.length ? installed.map((b) => b.label.split(" ").pop()).join(", ") + " found" : "none found");
    setReady("copy", a.ready ? "ok" : "info", a.ready ? "ready" : "made on the first run");
  }
  async function save() {
    const body = { user: user.value, password: pw1.value, confirm: pw2.value };
    const chk = await call("/api/login/check", body); if (!chk) return;
    if (chk.problems.length) { await tell("Check the login", chk.problems.join("\n"), "warn"); return; }
    if (saved && !await ask("Replace the saved login?", `Knox ID '${saved}' is saved on this PC. Replace it with '${user.value.trim()}'?`, { yes: "Replace", icon: "warn" })) return;
    const r = await call("/api/login", body, "Not saved");
    pw1.value = pw2.value = "";
    if (r) refresh();
  }
  async function apply() { if (await call("/api/browser", { choice: choice.get() })) refresh(); }
  return { el, show: refresh, refresh };
};

// ==========================================================================
// Appearance
// ==========================================================================
pages.appearance = () => {
  const el = page("appearance", "Appearance", "Theme, fonts and text size for this window - applied at once and remembered. Drag the gap between any two panels to resize them; double-click a gap to put it back.");
  const swatches = h("div", { class: "swatches" });
  const theme = card("Theme", { sub: "Colours of the whole window" }); theme.body.append(swatches);
  const sizes = seg(S.settings.sizes.map((s) => [String(s), `${s} %`]), String(S.appearance.size), (v) => setAppearance({ size: Number(v) }));
  const size = card("Text size", { sub: "Every text in the window, tables and the console too" });
  size.body.append(sizes, h("div", { class: "note", style: "margin-top:.6rem", text: "100 % is the normal size. Larger sizes suit a big screen across a room or tired eyes." }));
  const layout = card("Layout", { sub: "Panels you resized are remembered per page" });
  layout.body.append(h("div", { class: "row" },
    h("button", { class: "btn", text: "Reset every divider", onclick: () => resetLayout() }),
    h("button", { class: "btn ghost", text: "Back to the original look", onclick: () => { resetLayout(); setAppearance(S.settings.defaults); } })),
    h("div", { class: "note", style: "margin-top:.6rem", text: "The Activity console at the bottom can also be dragged taller or shorter, or hidden with its Hide button." }));
  const fonts = h("div", {}), monos = h("div", {});
  const fcard = card("Text font", { sub: "Fonts found on this PC" }); fcard.body.append(fonts);
  const mcard = card("Console font", { sub: "The Activity console" }); mcard.body.append(monos);
  el.append(columns("appearance", 0.5, h("div", { class: "col scroll" }, theme, size, layout), h("div", { class: "col scroll" }, fcard, mcard)));

  function swatch(name, p) {
    const on = S.appearance.theme === name;
    return h("button", { class: `swatch${on ? " on" : ""}`, onclick: () => setAppearance({ theme: name }) },
      h("div", { class: "pic", style: `background:${p.bg}` },
        h("div", { class: "side", style: `background:${p.header};border-left:3px solid ${p.nav_bar}` }),
        h("div", { class: "body" }, h("div", { class: "cardm", style: `background:${p.card};border-color:${p.border}` },
          h("div", { class: "bar", style: `background:${p.text};width:60%` }), h("div", { class: "bar", style: `background:${p.muted};width:80%` }),
          h("div", { class: "btnm", style: `background:${p.accent}` })))),
      h("div", { class: "name", style: on ? "color:var(--accent)" : "", text: (on ? "✓ " : "") + name }));
  }
  function fontRow(name, which, sample) {
    const on = S.appearance[which] === name;
    return h("div", { class: `font-row${on ? " on" : ""}`, onclick: () => setAppearance({ [which]: name }) },
      h("div", { class: "fname" }, name, h("div", { class: "spacer" }), on ? "✓ in use" : ""),
      h("div", { class: "sample", style: `font-family:"${name}"`, text: sample }));
  }
  function paint() {
    clear(swatches).append(...Object.entries(S.settings.themes).map(([n, p]) => swatch(n, p)));
    sizes.set(String(S.appearance.size));
    clear(fonts).append(...S.settings.fonts.map((f) => fontRow(f, "font", "Detail Inspection  ·  Q321KUM00  ·  2026-09-30  ·  1,234 rows")));
    clear(monos).append(...S.settings.monos.map((f) => fontRow(f, "mono", "10:15:37  Record check PASSED - 10 of 10")));
  }
  function resetLayout() {
    S.settings.panes = {}; savePanes();
    document.querySelectorAll(".cols").forEach((c) => c.style.removeProperty("--left"));
    $("#work").style.removeProperty("--act-h");
    $("#work").style.removeProperty("--act-w");
    S.settings.activity = {}; api("/api/settings", { activity: {} }).catch(() => {});
    localLog("Every divider is back where it started (the pages take their own share again after a restart).", "ok");
  }
  paint();
  return { el, show: paint, paint };
};

// --------------------------------------------------------------------------
// Navigation and start
// --------------------------------------------------------------------------
/* The side panel: full, or collapsed to its icons (the toggle, or Ctrl+B). The person's
   choice is kept in settings.json; a window narrower than NAV_AUTO px shows the icons
   anyway without overwriting that choice, and widening it brings the choice back. */
const NAV_AUTO = 900;
function setupNav() {
  const nav = $("#nav"), toggle = $("#nav-toggle"), tip = $("#nav-tip");
  let chosen = !!((S.settings.nav || {}).collapsed);
  const apply = () => {
    const on = chosen || window.innerWidth < NAV_AUTO;
    nav.classList.toggle("collapsed", on);
    toggle.setAttribute("aria-expanded", String(!on));
    const words = on ? "Expand the side panel (Ctrl+B)" : "Collapse the side panel (Ctrl+B)";
    toggle.setAttribute("aria-label", words);
    toggle.title = words;
    toggle.querySelector(".label").textContent = on ? "Expand" : "Collapse";
    if (!on) hideTip();
  };
  const set = (on) => {
    chosen = on;
    S.settings.nav = Object.assign({}, S.settings.nav, { collapsed: on });
    api("/api/settings", { nav: S.settings.nav }).catch(() => {});
    apply();
  };
  // a collapsed item names itself - on hover and on keyboard focus alike
  const showTip = (el) => {
    if (!nav.classList.contains("collapsed")) return;
    const r = el.getBoundingClientRect();
    tip.textContent = el.getAttribute("aria-label") || "";
    tip.style.left = `${r.right + 8}px`;
    tip.style.top = `${r.top + r.height / 2}px`;
    tip.hidden = false;
  };
  function hideTip() { tip.hidden = true; }
  nav.querySelectorAll(".nav-item, .nav-toggle").forEach((el) => {
    el.addEventListener("mouseenter", () => showTip(el));
    el.addEventListener("focus", () => showTip(el));
    el.addEventListener("mouseleave", hideTip);
    el.addEventListener("blur", hideTip);
    el.addEventListener("click", hideTip);
  });
  nav.addEventListener("scroll", hideTip);
  toggle.onclick = () => set(!nav.classList.contains("collapsed") ? true : (window.innerWidth < NAV_AUTO ? chosen : false));
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "b"
        && !$("#modal-root").children.length) {
      e.preventDefault();
      toggle.click();
    }
  });
  window.addEventListener("resize", apply);
  apply();
}

function show(key) {
  S.page = key;
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("active", p.id === `page-${key}`));
  document.querySelectorAll(".nav-item").forEach((n) => n.classList.toggle("active", n.dataset.page === key));
  const p = pages[key];
  if (p && p.show) Promise.resolve(p.show()).catch((e) => localLog(`(page problem: ${e.message})`, "muted"));
}

async function start() {
  if (!TOKEN) { document.body.textContent = "Open GMES Automation from its own program (Start_GMES.bat)."; return; }
  try { S.settings = await api("/api/settings"); }
  catch (e) { document.body.textContent = `GMES Automation is not answering: ${e.message}`; return; }
  S.settings.panes = S.settings.panes || {};
  applyAppearance(S.settings.appearance);
  const builders = Object.entries(pages);
  for (const [k, make] of builders) { if (typeof make === "function") pages[k] = make(); }
  setupActivity();
  setupNav();
  // only page buttons switch pages: the guide link (an <a>, no data-page) opens /guide in its own window
  document.querySelectorAll(".nav-item[data-page]").forEach((n) => n.addEventListener("click", () => show(n.dataset.page)));
  $("#btn-stop").onclick = () => api("/api/stop", {}).then(() => { $("#pill").className = "pill stop"; $("#pill").textContent = "● Stopping"; $("#btn-stop").disabled = true; })
    .catch((e) => localLog(`Stop could not reach the app: ${e.message}`, "err"));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && S.busy && !$("#modal-root").children.length) $("#btn-stop").click(); });
  const st = await api("/api/state");
  S.connected = st.connected;
  $("#nav-foot").textContent = `v${st.version}  ·  read-only in G-MES`;
  if (st.who) $("#who").textContent = `Signed in as ${st.who}`;
  setupSite(st.site);
  setBusy(st.busy, st.task);
  setInterval(() => {
    if (S.busy && S.task) $("#task-label").textContent = `${S.task.name}...   ${fmtSecs(Date.now() / 1000 - S.task.started)}`;
  }, 1000);
  show("reports");
  pages.account.refresh();
  poll();
}
start();
