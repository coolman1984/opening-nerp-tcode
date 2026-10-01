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
    const onKey = (e) => {
      if (e.key === "Escape") { e.stopPropagation(); done(buttons[0][2]); }
      else if (e.key === "Enter" && !(e.target instanceof HTMLInputElement)) { e.preventDefault(); done(buttons[buttons.length - 1][2]); }
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
  input.addEventListener("keydown", () => {});
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
  if (act.height) setH(act.height);
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
    let px = null;
    const move = (ev) => { px = Math.round(Math.min(rect.height - 200, Math.max(90, rect.bottom - ev.clientY))); setH(px); };
    gutter.addEventListener("pointermove", move);
    gutter.addEventListener("pointerup", () => {
      gutter.removeEventListener("pointermove", move);
      gutter.classList.remove("dragging");
      if (px) { S.settings.activity = Object.assign({}, S.settings.activity, { height: px }); api("/api/settings", { activity: S.settings.activity }).catch(() => {}); }
    }, { once: true });
  });
  gutter.addEventListener("dblclick", () => {
    work.style.removeProperty("--act-h");
    S.settings.activity = Object.assign({}, S.settings.activity, { height: null });
    api("/api/settings", { activity: S.settings.activity }).catch(() => {});
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
  const policy = seg([["keep", "As recorded"], ["yesterday", "Yesterday"], ["today", "Today"]], "keep");
  const right = card("Selected screen", { fill: true });
  right.body.append(detailBox,
    h("div", { class: "field" }, h("label", { text: "Run for" }), policy),
    h("div", { class: "row" },
      h("button", { class: "btn success", text: "▶ Run selected", busy: true, onclick: () => runSelected() }),
      h("button", { class: "btn primary", text: "Record check", busy: true, onclick: () => checkSelected() }),
      h("button", { class: "btn", text: "Re-record", busy: true, onclick: () => rerecord() })),
    h("div", { class: "row" },
      h("button", { class: "btn ghost", text: "Open output folder", onclick: () => openOutput() }),
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
  const c3 = card("Scope", { step: 3, sub: "What the recording will use every time it runs" });
  c3.body.append(field("Result grid", grid, "the table that IS the report"),
    field("Division / organisation", h("div", {}, division, divList), "empty = the screen's own"),
    field("Period", period),
    h("div", { class: "grid2" }, field("From", from, "YYYYMMDD"), field("To", to)),
    h("div", { class: "row", style: "margin:-.3rem 0 .7rem" },
      h("button", { class: "chip", text: "Yesterday", onclick: () => quick(1) }),
      h("button", { class: "chip", text: "Today", onclick: () => quick(0) })),
    field("Verify: the result column that holds the date", h("div", {}, verify, verifyList), "required for a dated run"),
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
    if (m === "month" && digits(from.value).length !== 6) { const d = ymd(0).slice(0, 6); from.value = d; to.value = d; }
    else if (m === "day" && digits(from.value).length !== 8) { from.value = ymd(1); to.value = ymd(1); }
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
      d.questions.map((q) => h("div", { class: "question" },
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
    period.set(!d.date_fields.length ? "none" : (d.looks_monthly ? "month" : "day"));
    if (last.from) { from.value = last.from; to.value = last.to || last.from; }
    periodMode();
    verify.setOptions(d.verify_candidates);
    verify.value = last.verify || d.verify_candidates[0] || "";
    clear(optBox); optionInputs = {};
    const opts = d.options.filter((o) => ["button", "checkbox"].includes(o.kind) && !["inquiry", "search"].includes(o.label.toLowerCase()));
    if (!opts.length) optBox.append(h("span", { class: "note", text: "none on this screen" }));
    for (const o of opts) {
      const cb = h("input", { type: "checkbox", disabled: !o.enabled });
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
  }
  function specBody(dry) {
    const c = code.value.replace(/\s+/g, "").toUpperCase();
    let g = grid.value;
    if (S.desc && S.desc.code === c) { const sug = (S.desc.grids.find((x) => x.suggested) || {}).name; if (g === sug) g = ""; }
    const sets = {}; for (const [k, i] of Object.entries(filterInputs)) if (i.value.trim()) sets[k] = i.value.trim();
    return { code: c, division: division.value.trim(), period: period.get(), from: from.value, to: to.value,
      verify: verify.value.trim(), sets, more: more.value, options: Object.entries(optionInputs).filter(([, i]) => i.checked).map(([k]) => k),
      grid: g, export: exportSeg.get(), out_dir: out.value.trim(), dry };
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
    h("button", { class: "btn ghost", text: "Delete", onclick: () => deleteBatch() })), t.el, sel);

  const policy = seg([["yesterday", "Yesterday"], ["today", "Today"], ["keep", "As recorded"], ["date", "Choose..."]], "yesterday");
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
    if (["yesterday", "today", "keep"].includes(pol)) policy.set(pol); else { policy.set("date"); date.value = pol; }
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
    if (["yesterday", "today", "keep"].includes(pol)) policy.set(pol);
    run(false);
  }
  return { el, show: refresh, row, showPlan, runCodes };
};

// ==========================================================================
// Schedules
// ==========================================================================
pages.schedules = () => {
  const el = page("schedules", "Schedules", "A saved batch, run by Windows Task Scheduler at a set time. It runs only while this Windows user is signed in (the login is encrypted for this account), and a PC that was asleep runs it when it wakes.");
  const t = table([{ key: "batch", title: "Batch" }, { key: "state", title: "State" }, { key: "next", title: "Next run" },
    { key: "last", title: "Last run" }, { key: "result", title: "Last result" }], { onSelect: () => notesFor(), empty: "No schedule yet." });
  const notes = h("div", { class: "note" });
  const act = (kind) => { const b = t.selected()[0]; if (b) runTask(kind, { batch: b }, { done: () => { if (kind === "schedule_run") localLog(`Started ${b} - it runs in the background; History shows the report.`, "ok"); refresh(); } }); };
  const left = card("This app's schedules", { fill: true });
  left.body.append(t.el, notes, h("div", { class: "row" },
    h("button", { class: "btn", text: "Refresh", onclick: () => refresh() }),
    h("button", { class: "btn primary", text: "Run now", busy: true, onclick: () => act("schedule_run") }),
    h("button", { class: "btn", text: "Pause", busy: true, onclick: () => act("schedule_pause") }),
    h("button", { class: "btn", text: "Resume", busy: true, onclick: () => act("schedule_resume") }),
    h("button", { class: "btn danger", text: "Delete", busy: true, onclick: async () => {
      const b = t.selected()[0];
      if (b && await ask(`Delete the schedule '${b}'?`, "The batch itself is kept.", { yes: "Delete", kind: "danger", icon: "warn" })) act("schedule_delete");
    } })));
  const batchSel = select([]);
  const time = input("06:30", { style: "max-width:8rem" });
  const kind = seg([["daily", "Every day"], ["weekdays", "Mon - Fri"], ["days", "Chosen days"]], "daily");
  const dayBoxes = {};
  const days = h("div", { class: "row" }, ["mon", "tue", "wed", "thu", "fri", "sat", "sun"].map((d) => {
    const cb = h("input", { type: "checkbox", checked: !["sat", "sun"].includes(d) }); dayBoxes[d] = cb;
    return h("label", { class: "check" }, cb, d[0].toUpperCase() + d.slice(1));
  }));
  const right = card("New schedule");
  right.body.append(field("Saved batch", batchSel, "make one on Run & Batch"), field("Time", time, "HH:MM, 24 hour"),
    field("Days", h("div", { style: "display:flex;flex-direction:column;gap:.5rem" }, kind, days)),
    h("button", { class: "btn success", text: "Create schedule", busy: true, onclick: () => create() }),
    h("div", { class: "note", style: "margin-top:.8rem", text: "The task runs this app without a window: it signs in with the saved login, runs the batch with the batch's own date rule, and writes the report to History. Prove a new schedule once with 'Run now'." }));
  el.append(columns("schedules", 0.6, h("div", { class: "col" }, left), h("div", { class: "col scroll" }, right)));

  let tasks = [];
  async function refresh() {
    notes.textContent = "Reading Task Scheduler...";
    try {
      const b = await api("/api/batches");
      batchSel.setOptions(Object.keys(b.batches).sort());
      tasks = (await api("/api/schedules")).tasks;
    } catch (e) { notes.textContent = `Task Scheduler could not be read: ${e.message}`; return; }
    t.fill(tasks.map((x) => ({ key: x.batch, tag: (x.last_ok === false || x.notes.length) ? "err" : (x.last_ok ? "ok" : ""),
      cells: { batch: x.batch, state: x.state, next: x.next_run || "-", last: x.last_run || "-", result: x.last_text || "-" } })));
    notes.textContent = tasks.length ? "Choose a schedule to see what was found about it." : "No schedule yet. Save a batch on Run & Batch, then create its schedule on the right.";
    notesFor();
  }
  function notesFor() {
    const b = t.selected()[0]; const x = tasks.find((y) => y.batch === b);
    if (x) notes.textContent = (x.notes.join("  ·  ") || "No problems seen.") + `   Log: data\\logs\\scheduled_${x.batch}.log`;
  }
  async function create() {
    const batch = batchSel.value;
    if (!batch) { await tell("Choose a batch", "Save a batch on Run & Batch first."); return; }
    const body = { batch, time: time.value, kind: kind.get(), days: Object.entries(dayBoxes).filter(([, c]) => c.checked).map(([d]) => d) };
    let w;
    try { w = await api("/api/when", body); } catch (e) { await tell("Check the time", e.message, "warn"); return; }
    if (!await ask(`Schedule '${batch}'?`, `Windows Task Scheduler will run it ${w.text}.`, { yes: "Create", kind: "success" })) return;
    runTask("schedule_create", body, { done: (name) => { localLog(`Schedule created: ${name}.`, "ok"); refresh(); } });
  }
  return { el, show: refresh };
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
  function load() { runTask("rowexport_load", form(), { done: (r) => { loaded = true; loadedText(r); state(); } }); }
  async function start() {
    const fm = form();
    if (!await ask("Start the export?", `From row ${fm.start_row}${Number(fm.count) ? `, ${fm.count} row(s)` : ", every row that remains"}. Stop (or Esc) at any moment.`, { yes: "▶ Start", kind: "success" })) return;
    ["ok", "skipped", "failed"].forEach((k) => { tiles[k].textContent = "0"; });
    bar.value = 0; paused = false; btnPause.textContent = "❚❚ Pause";
    const ok = await runTask("rowexport_start", fm, {
      done: (s) => {
        const text = `${fmtInt(s.ok)} exported, ${fmtInt(s.skipped)} skipped, ${fmtInt(s.failed)} failed`;
        head.textContent = (s.stopped || s.fatal ? "Stopped - " : "Finished - ") + text;
        if (s.next_row && (s.stopped || s.fatal)) { f.start.value = s.next_row; localLog(`'Start at row No.' is now ${fmtInt(s.next_row)} - Start export carries on.`, "info"); }
        if (s.fatal) tell("The run stopped", s.fatal, "err");
      } });
    if (ok) { running = true; state(); }
  }
  async function pause() {
    paused = !paused;
    await call("/api/rowexport/pause", { pause: paused });
    btnPause.textContent = paused ? "▶ Resume" : "❚❚ Pause";
  }
  function progress(e) {
    bar.max = Math.max(1, e.total); bar.value = e.done;
    tiles.ok.textContent = fmtInt(e.ok); tiles.skipped.textContent = fmtInt(e.skipped); tiles.failed.textContent = fmtInt(e.failed);
    tiles.eta.textContent = e.eta ? fmtSecs(e.eta) : "-";
    prog.textContent = `${fmtInt(e.done)} of ${fmtInt(e.total)} · last row ${fmtInt(e.row)}`;
  }
  function onBusy(b) { if (!b) running = false; state(); }
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
        detail: x.status === "ok" ? (x.files || []).map((p) => p.split(/[\\/]/).pop()).join(", ") : (x.error || "") } })));
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
    S.settings.activity = {}; api("/api/settings", { activity: {} }).catch(() => {});
    localLog("Every divider is back where it started (the pages take their own share again after a restart).", "ok");
  }
  paint();
  return { el, show: paint, paint };
};

// --------------------------------------------------------------------------
// Navigation and start
// --------------------------------------------------------------------------
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
  document.querySelectorAll(".nav-item").forEach((n) => n.addEventListener("click", () => show(n.dataset.page)));
  $("#btn-stop").onclick = () => api("/api/stop", {}).then(() => { $("#pill").className = "pill stop"; $("#pill").textContent = "● Stopping"; $("#btn-stop").disabled = true; });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && S.busy && !$("#modal-root").children.length) $("#btn-stop").click(); });
  const st = await api("/api/state");
  S.connected = st.connected;
  $("#nav-foot").textContent = `v${st.version}  ·  read-only in G-MES`;
  if (st.who) $("#who").textContent = `Signed in as ${st.who}`;
  setBusy(st.busy, st.task);
  setInterval(() => {
    if (S.busy && S.task) $("#task-label").textContent = `${S.task.name}...   ${fmtSecs(Date.now() / 1000 - S.task.started)}`;
  }, 1000);
  show("reports");
  pages.account.refresh();
  poll();
}
start();
