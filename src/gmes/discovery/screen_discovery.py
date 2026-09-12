"""Read what a screen actually offers: its filters, its result grids, and
the left-panel decisions (`form.binds` cannot see any of the second kind).

Forked from gmes_core.py. This is the one place a raw JS_DISCOVER/
JS_LEFT_OPTIONS/JS_ORG_TREES response is turned into `gmes.contracts`
dataclasses - everything downstream (screens/, discovery/screen.py) works
with FilterRef/GridRef/TreeRef/OptionRef/QuickViewRef, never with the
loose dict shape the browser actually returns.
"""
import json

from ..browser.cdp import evaluate
from ..contracts import (
    FilterRef,
    GridRef,
    OptionRef,
    QuickViewRef,
    ScreenInfo,
    TreeRef,
)
from ..nexacro.js_snippets import JS_IS_VISIBLE
from ..query.form_locator import JS_HELPERS

# The only ids safe to hardcode: the shell has exactly one of each.
EXCEL_BTN = "mainframe.vFrameSet1.vFrameSet2.mdiFrame.form.btnExcel"

# Nexacro names a control by its type, and that prefix is the only reliable
# way to tell an input from a read-only display.
INPUT_PREFIXES = ("edt", "msk", "cbo", "chk", "rdo", "cal", "spn", "txt", "lst")


def _js(template, *args):
    return template % args


JS_DISCOVER = r"""
(function() {
    %s
    const isVisible = %s;
    const screenCode = %s;

    const forms = _findForms(screenCode);
    if (!forms.length) return JSON.stringify({found: false, reason: 'no forms for this screen code'});

    // The work window is the ancestor whose name starts with "win". Keep the
    // full path INCLUDING the "application." prefix: _findForms returns paths
    // with it, so a stripped prefix silently matches nothing and the screen
    // looks as though it has no filters at all.
    const anchor = forms[0].path;
    const parts = anchor.split('.');
    const winIdx = parts.findIndex(p => /^win/.test(p));
    if (winIdx < 0) return JSON.stringify({found: false, reason: 'no work window'});
    const winPath = parts.slice(0, winIdx + 1).join('.');

    // A component path inside a form maps to a DOM id by inserting ".form"
    // after the window and after every nested Div.
    function domId(formPath, comp) {
        const p = formPath.replace(/^application\./, '').split('.');
        const i = p.findIndex(x => /^win/.test(x));
        if (i < 0) return null;
        let id = p.slice(0, i + 1).join('.') + '.form';
        for (const seg of p.slice(i + 1)) id += '.' + seg + '.form';
        return id + '.' + comp;
    }

    // What a control currently shows. A focused Nexacro edit renders a real
    // <input>; an unfocused one is a div carrying the text.
    function shownValue(el) {
        if (!el) return '';
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') return el.value || '';
        const inner = el.querySelector('input, textarea');
        if (inner) return inner.value || '';
        return (el.textContent || '').trim();
    }

    // The label for a control: the nearest visible Static to its left on the
    // same line, else the nearest one directly above it.
    const statics = [];
    for (const el of document.querySelectorAll('div')) {
        const cls = (typeof el.className === 'string') ? el.className : '';
        if (!/\bStatic\b/.test(cls)) continue;
        if (!isVisible(el)) continue;
        const t = (el.textContent || '').trim();
        if (!t || t.length > 40) continue;
        // Calendar day cells are Statics too and sit right beside the date
        // boxes, which made the date filters come back labelled "6" and "8".
        if (/^[\d.,:\/-]+$/.test(t)) continue;
        if (t.length < 3) continue;
        if (/^(mon|tue|wed|thu|fri|sat|sun)\.?$/i.test(t)) continue;
        const r = el.getBoundingClientRect();
        statics.push({t: t, l: r.left, r: r.right, cy: r.top + r.height / 2, top: r.top});
    }
    function labelFor(rect) {
        let best = null, bestD = 1e9;
        for (const s of statics) {
            const sameLine = Math.abs(s.cy - (rect.top + rect.height / 2)) < 12;
            if (sameLine && s.r <= rect.left + 8) {
                const d = rect.left - s.r;
                if (d >= 0 && d < 260 && d < bestD) { best = s.t; bestD = d; }
            }
        }
        if (best) return best;
        for (const s of statics) {
            const above = rect.top - s.top;
            if (above > 0 && above < 46 && Math.abs(s.l - rect.left) < 130) {
                if (above < bestD) { best = s.t; bestD = above; }
            }
        }
        return best || '';
    }

    const INPUTS = %s;
    function kindOf(name) {
        const n = (name || '').toLowerCase();
        for (const p of INPUTS) if (n.indexOf(p) === 0) return 'input';
        if (/^(sta|img|btn|grd|div)/.test(n)) return 'display';
        return 'unknown';
    }
    // The shell's own forms carry binds, grids and trees that belong to the
    // FRAME, not to the report - the My Menu panel, the widget list, the
    // module bar. Observed leaking into a live describe of P1112UM00: 21 of
    // the 22 "category trees" and 4 of the 8 "result grids" were shell.
    const SHELL = /WorkMainTitle|WorkMain\.xfdl|WorkTemplate|MyMenu|TopMenu|LeftMenu|LeftMain|PortalMain/i;

    const filters = [], unbound = [], grids = [], datasets = {};
    const quickViews = [], seenQV = {};

    // Dataset ids that are UI CHROME, not a result set - an org tree
    // (commonName + _checked, gotcha #40) or the Quick View widget
    // (sysScreenId + menuId + quickViewId, gotcha #46) - collected by name
    // in one pass over every form in this window. A grid's OWN form does not
    // always carry the dataset it renders as an own property: Nexacro
    // resolves `binddataset` through the form's ancestor scope at render
    // time, so `grdWidgetList`'s form does not have `dsWidget` on it even
    // though it displays it - looking the id up only on the grid's own form
    // silently found nothing and let it straight through.
    const chromeDatasets = {};
    for (const h of _findForms(null)) {
        if (h.path.indexOf(winPath) !== 0) continue;
        let keys = [];
        try { keys = Object.keys(h.form); } catch (e) { continue; }
        for (const k of keys) {
            let d = null;
            try { d = h.form[k]; } catch (e) { continue; }
            if (!d || _typeName(d) !== 'Dataset') continue;
            const cols = [];
            try { const n = d.getColCount();
                  for (let i = 0; i < n; i++) cols.push(d.getColID(i)); } catch (e) { continue; }
            const isTree = cols.indexOf('commonName') >= 0 && cols.indexOf('_checked') >= 0;
            const isQV = cols.indexOf('sysScreenId') >= 0 && cols.indexOf('menuId') >= 0
                        && cols.indexOf('quickViewId') >= 0;
            if (isTree || isQV) chromeDatasets[k] = true;
        }
    }

    for (const h of _findForms(null)) {
        if (h.path.indexOf(winPath) !== 0) continue;   // only this work window

        try {
            for (const k of Object.keys(h.form)) {
                let d = h.form[k];
                if (!d || _typeName(d) !== 'Dataset') continue;
                const cols = [];
                try { const n = d.getColCount();
                      for (let i = 0; i < n; i++) cols.push(d.getColID(i)); } catch (e) {}
                datasets[k] = {rows: (function(){ try { return d.getRowCount(); } catch(e){ return -1; } })(),
                               cols: cols.length, form: h.file || ''};
            }
        } catch (e) {}

        // Bound controls -> settable through the dataset.
        try {
            const b = SHELL.test(h.file || '') ? null : h.form.binds;
            if (b && b.length !== undefined) {
                for (let i = 0; i < b.length; i++) {
                    const x = b[i];
                    const ds = String(x.datasetid || ''), col = String(x.columnid || '');
                    if (!ds || !col) continue;
                    const comp = String(x.compid || '');
                    const leaf = comp.split('.').pop();
                    if (kindOf(leaf) !== 'input') continue;   // a display, not a filter
                    const id = domId(h.path, comp);
                    let label = '', value = '', visible = false, kind = '';
                    const el = id ? document.getElementById(id) : null;
                    if (el) {
                        visible = isVisible(el);
                        if (visible) label = labelFor(el.getBoundingClientRect());
                        const cls = (typeof el.className === 'string') ? el.className : '';
                        kind = (cls.split(/\s+/)[0] || '');
                    }
                    try {
                        const d = h.form[ds];
                        if (d && d.getRowCount() > 0) value = String(d.getColumn(0, col) || '');
                    } catch (e) {}
                    filters.push({dataset: ds, column: col, control: leaf,
                                  label: label, value: value, visible: visible,
                                  kind: kind, id: id || '', form: h.file || '',
                                  bound: true});
                }
            }
        } catch (e) {}

        // Visible inputs with NO binding. Not every screen binds its filters
        // - Q2241UM00 sets them in code - so those screens would otherwise
        // report "no filters" and look broken. They cannot be written through
        // a dataset, but they CAN be typed into.
        try {
            const bound = {};
            const b2 = h.form.binds;
            if (b2 && b2.length !== undefined)
                for (let i = 0; i < b2.length; i++)
                    bound[String(b2[i].compid || '')] = true;
            const comps = h.form.components;
            if (comps && comps.length !== undefined && !SHELL.test(h.file || '')) {
                for (let i = 0; i < comps.length; i++) {
                    const c = comps[i];
                    if (!c || bound[c.name]) continue;
                    if (kindOf(c.name) !== 'input') continue;
                    const id = domId(h.path, c.name);
                    const el = id ? document.getElementById(id) : null;
                    if (!el || !isVisible(el)) continue;
                    const cls = (typeof el.className === 'string') ? el.className : '';
                    unbound.push({control: c.name, form: h.file || '', id: id,
                                  label: labelFor(el.getBoundingClientRect()),
                                  value: shownValue(el), visible: true,
                                  kind: (cls.split(/\s+/)[0] || ''), bound: false,
                                  dataset: '', column: ''});
                }
            }
        } catch (e) {}

        // Grids -> candidate result sets. The shell's grids (My Menu, the
        // widget list) are inside the work window's form tree too, so they
        // have to be excluded here as well as from the binds - otherwise they
        // are offered as places the report's rows might be.
        try {
            const comps = SHELL.test(h.file || '') ? null : h.form.components;
            if (comps && comps.length !== undefined) {
                for (let i = 0; i < comps.length; i++) {
                    const c = comps[i];
                    if (!c) continue;
                    if (!/Grid/i.test(_typeName(c))) continue;
                    // The Excel export builds a throwaway clone of the grid
                    // it is exporting (grdPrnMpp__EXCEL__) and leaves it on
                    // the form. It is the same dataset, so it changes no
                    // answer - but it appears and disappears with the last
                    // export, which is exactly the kind of thing that must
                    // not look like the screen having changed.
                    if (/__EXCEL__/.test(c.name || '')) continue;
                    const bd = String(c.binddataset || '');
                    if (!bd) continue;
                    // An org tree or the Quick View widget, rendered as a
                    // Grid: chrome, not this screen's own result set. The
                    // SHELL filename test above does not reach them because
                    // they sit on forms of their own (OrgCategory_GDS.xfdl.js,
                    // WidgetFilter.xfdl.js), not a shell one, so this is by
                    // dataset shape instead - see chromeDatasets above.
                    if (chromeDatasets[bd]) continue;

                    const id = domId(h.path, c.name);
                    const el = id ? document.getElementById(id) : null;
                    const r = el ? el.getBoundingClientRect() : null;
                    grids.push({name: c.name, dataset: bd, form: h.file || '',
                                area: r ? Math.round(r.width * r.height) : 0,
                                visible: !!(el && isVisible(el))});
                }
            }
        } catch (e) {}

        // Quick View - a screen-embedded SHORTCUT TO A DIFFERENT SCREEN,
        // never a filter. Found by shape: a dataset carrying menuId +
        // sysScreenId + quickViewId is a slice of the same catalogue behind
        // the top search box (gotcha #21), scoped to this screen's siblings.
        // It renders as a Grid, not a Button/CheckBox, so JS_LEFT_OPTIONS
        // never sees it - it must not be offered as a left-panel option,
        // because clicking a row changes which SCREEN is open, not what the
        // query means (see HISTORY.md Phase 27).
        try {
            for (const k of Object.keys(h.form)) {
                let d = null;
                try { d = h.form[k]; } catch (e) { continue; }
                if (!d || _typeName(d) !== 'Dataset') continue;
                const cols = [];
                try { const n = d.getColCount();
                      for (let i = 0; i < n; i++) cols.push(d.getColID(i)); } catch (e) { continue; }
                if (cols.indexOf('sysScreenId') < 0 || cols.indexOf('menuId') < 0
                    || cols.indexOf('quickViewId') < 0) continue;
                let rows = 0;
                try { rows = d.getRowCount(); } catch (e) { continue; }
                for (let r = 0; r < rows; r++) {
                    let sid = '', nm = '';
                    try { sid = String(d.getColumn(r, 'sysScreenId') || '').trim(); } catch (e) {}
                    try { nm = String(d.getColumn(r, 'enMsgCont')
                                    || d.getColumn(r, 'msgCont') || '').trim(); } catch (e) {}
                    if (!sid || seenQV[sid]) continue;
                    seenQV[sid] = true;
                    quickViews.push({screen: sid, name: nm, active: sid === screenCode});
                }
            }
        } catch (e) {}
    }

    // One dataset column can be bound to several controls (a value shown in
    // two places). Keep one entry per dataset.column, preferring the visible
    // control - that is the one a person means when they name a label.
    const seen = {};
    const unique = [];
    for (const f of filters) {
        const key = f.dataset + '.' + f.column;
        const prev = seen[key];
        if (prev === undefined) { seen[key] = unique.length; unique.push(f); }
        else if (f.visible && !unique[prev].visible) { unique[prev] = f; }
    }
    filters.length = 0;
    Array.prototype.push.apply(filters, unique);

    // A bind records the control by its FULL path from the owning form
    // (divBasic.form.divCal.form.mskDateFrom) while a component knows only
    // its own name, and the two are usually recorded on different forms.
    // Comparing them directly listed bound controls as unbound.
    const boundLeaves = {};
    for (const f of filters) boundLeaves[f.control] = true;
    const seenUnbound = {};
    const trulyUnbound = [];
    for (const u of unbound) {
        if (boundLeaves[u.control] || seenUnbound[u.control]) continue;
        seenUnbound[u.control] = true;
        trulyUnbound.push(u);
    }

    grids.sort((a, b) => b.area - a.area);

    const inquiry = Array.from(document.querySelectorAll('div')).find(el => {
        const cls = (typeof el.className === 'string') ? el.className : '';
        return /btn_LF_Search_New/.test(cls) && isVisible(el);
    });
    const excel = document.getElementById(%s);

    return JSON.stringify({found: true, screen: screenCode,
                           window: winPath.split('.').pop(),
                           filters: filters, unbound: trulyUnbound.slice(0, 40),
                           grids: grids.slice(0, 8), datasets: datasets,
                           quickViews: quickViews,
                           hasInquiry: !!inquiry,
                           hasExcel: !!(excel && isVisible(excel))});
})()
"""


def _filter_ref(d):
    return FilterRef(dataset=d.get("dataset", ""), column=d.get("column", ""),
                     control=d.get("control", ""), label=d.get("label", ""),
                     form=d.get("form", ""), value=d.get("value", ""),
                     visible=bool(d.get("visible", False)), kind=d.get("kind", ""),
                     id=d.get("id", ""), bound=bool(d.get("bound", True)))


def _grid_ref(d):
    return GridRef(name=d.get("name", ""), dataset=d.get("dataset", ""),
                   form=d.get("form", ""), area=int(d.get("area", 0) or 0),
                   visible=bool(d.get("visible", False)))


def _quick_view_ref(d):
    return QuickViewRef(screen=d.get("screen", ""), name=d.get("name", ""),
                        active=bool(d.get("active", False)))


def discover(ws, screen_code):
    """Read a screen's filters, grids and Quick View entries.

    Raises RuntimeError with the browser's own reason when the screen has
    no forms yet - a screen still building its UI in JavaScript looks
    exactly like this, so callers that poll (discovery/screen.py's
    `open_screen()`) catch this and keep waiting rather than treating it
    as a hard failure."""
    raw = evaluate(ws, _js(JS_DISCOVER, JS_HELPERS, JS_IS_VISIBLE,
                          json.dumps(screen_code), json.dumps(list(INPUT_PREFIXES)),
                          json.dumps(EXCEL_BTN)))
    if not raw.get("found"):
        raise RuntimeError(raw.get("reason", "the screen was not found"))
    return ScreenInfo(
        code=raw.get("screen", screen_code),
        window=raw.get("window", ""),
        filters=tuple(_filter_ref(f) for f in raw.get("filters", [])),
        unbound=tuple(_filter_ref(f) for f in raw.get("unbound", [])),
        grids=tuple(_grid_ref(g) for g in raw.get("grids", [])),
        quick_views=tuple(_quick_view_ref(q) for q in raw.get("quickViews", [])),
        datasets=raw.get("datasets", {}),
        has_inquiry=bool(raw.get("hasInquiry", False)),
        has_excel=bool(raw.get("hasExcel", False)),
    )


# ---------------------------------------------------------------------------
# Left-panel options
# ---------------------------------------------------------------------------

# The left panel carries dimensions that `form.binds` cannot see, and every
# one of them changes what the query returns:
#
#   Org / Prod / Fac / Proc     which category tree the selection comes from
#   STD / PLANT                 the organisation attribute
#   Including Past Org.         whether closed organisations are included
#   Plan Date / Create Date     WHICH date the period applies to
#   General / Compare / OI      the search mode
#   Quick View entries          Master vs Detail Prod. Plan - a different result
#
# Running "yesterday" against Create Date instead of Plan Date returns a
# plausible, completely different answer, and nothing looks wrong. Nexacro
# encodes the chosen state in the CSS class, so they can be listed with their
# state and set by label.
JS_LEFT_OPTIONS = r"""
(function() {
    const isVisible = %s;
    const out = [];
    const seen = {};
    for (const el of document.querySelectorAll('div')) {
        const id = el.id || '';
        if (!/\.divLeft\.form\./.test(id) && !/divTabBtnArea/.test(id)) continue;
        if (/:icontext$|:text$/.test(id)) continue;
        const cls = (typeof el.className === 'string') ? el.className : '';
        const isBtn = /\bButton\b/.test(cls), isChk = /\bCheckBox\b/.test(cls);
        if (!isBtn && !isChk) continue;
        if (!isVisible(el)) continue;
        const text = (el.textContent || '').trim();
        if (!text || text.length > 32) continue;
        if (seen[text]) continue;
        seen[text] = true;
        const r = el.getBoundingClientRect();
        let state = 'unknown';
        if (/_Sel\b|_Sel$|ToggleSearchV2|Category_Sel/.test(cls)) state = 'selected';
        else if (/_Dis\b|_Dis$|_Default/.test(cls)) state = 'not selected';
        else if (isChk) state = el.querySelector('.checked') ? 'checked' : 'unchecked';
        out.push({label: text, id: id, cls: cls.slice(0, 46), state: state,
                  kind: isChk ? 'checkbox' : 'button',
                  x: r.left + r.width / 2, y: r.top + r.height / 2});
    }
    return JSON.stringify({count: out.length, options: out});
})()
""" % JS_IS_VISIBLE


def left_options(ws):
    """Every left-panel option and its current state, as OptionRef tuples."""
    raw = evaluate(ws, JS_LEFT_OPTIONS)
    return tuple(
        OptionRef(label=o["label"], id=o.get("id", ""), cls=o.get("cls", ""),
                 state=o.get("state", "unknown"), kind=o.get("kind", ""),
                 x=float(o.get("x", 0.0)), y=float(o.get("y", 0.0)))
        for o in raw.get("options", [])
    )


# ---------------------------------------------------------------------------
# Category trees (Org / Prod / Fac / Proc)
# ---------------------------------------------------------------------------

# Organisation trees: the left panel offers Org / Prod / Fac / Proc,
# and each tab has a tree of its own. They are found by SHAPE instead: a
# dataset carrying a `commonName` column and a `_checked` flag is a category
# tree, whatever it is called and wherever it lives.
JS_ORG_TREES = r"""
(function() {
    %s
    // The shell's My Menu panels keep datasets with a commonName column too,
    // so a pure shape test found 22 "category trees" on a screen that has
    // one. They are not organisation trees and must not be offered as them.
    const SHELL = /WorkMainTitle|WorkMain\.xfdl|WorkTemplate|MyMenu|TopMenu|LeftMenu|LeftMain|PortalMain/i;
    const out = [];
    for (const h of _findForms(null)) {
        if (SHELL.test(h.file || '')) continue;
        let keys = [];
        try { keys = Object.keys(h.form); } catch (e) { continue; }
        for (const k of keys) {
            let ds = null;
            try { ds = h.form[k]; } catch (e) { continue; }
            if (!ds || _typeName(ds) !== 'Dataset') continue;
            let cols = [], rows = 0;
            try {
                rows = ds.getRowCount();
                const n = ds.getColCount();
                for (let i = 0; i < n; i++) cols.push(ds.getColID(i));
            } catch (e) { continue; }
            if (cols.indexOf('commonName') < 0) continue;
            if (rows === 0) continue;      // an empty tree cannot hold a division
            const names = [], checked = [];
            for (let r = 0; r < rows; r++) {
                let nm = '', ck = '';
                try { nm = String(ds.getColumn(r, 'commonName') || ''); } catch (e) {}
                try { ck = String(ds.getColumn(r, '_checked') || ''); } catch (e) {}
                if (nm) names.push(nm);
                if (ck === '1') checked.push(nm);
            }
            out.push({form: h.file || '', dataset: k, rows: rows,
                      settable: cols.indexOf('_checked') >= 0,
                      names: names.slice(0, 60), checked: checked});
        }
    }
    return JSON.stringify({count: out.length, trees: out});
})()
"""


def org_trees(ws):
    """Every category tree on the screen (Org/Prod/Fac/Proc, whichever tab),
    as TreeRef tuples. `entry` is left blank - it is only populated on a
    persisted profile reference, never on live discovery."""
    raw = evaluate(ws, _js(JS_ORG_TREES, JS_HELPERS))
    return tuple(
        TreeRef(form=t.get("form", ""), dataset=t.get("dataset", ""),
               rows=int(t.get("rows", 0) or 0), settable=bool(t.get("settable", True)),
               names=tuple(t.get("names", [])), checked=tuple(t.get("checked", [])))
        for t in raw.get("trees", [])
    )
