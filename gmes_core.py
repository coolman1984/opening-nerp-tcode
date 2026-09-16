"""
The core of G-MES control: one screen, driven completely, without the tool
having been taught that screen first.

This is a library, not a command. The commands are thin callers:

    gmes_report.py          non-interactive: describe / run any UI number
    run_gmes_workflow.py    the by-hand front end
    gmes_daily_prodplan.py  the one hardcoded nightly job

What "control" means here
-------------------------
READ-ONLY. This module opens a screen, sets everything the screen offers,
runs its Inquiry, verifies what came back and exports it. It never clicks
Save, Submit, Approve or Delete, and it has no code path that could
(CLAUDE.md 2.5). Every write it performs goes into a *filter*, which is
input to a query.

The five mechanisms that make any of the 809 screens reachable
--------------------------------------------------------------
1. `gdsMenuList` is a client-side catalogue: menuId <-> sysScreenId <->
   English name <-> breadcrumb. The top search box opens any of them by
   code, so no menu walking (gmes_open_screen.py).
2. `_findForms(screenCode)` walks Nexacro's `_frames` AND its nested
   `Div.form` trees, so a screen is addressable by its stable code while the
   window id (winPPM0219_0_516) is renumbered on every open.
3. `form.binds` maps each control to the dataset column behind it, so a
   screen describes its own filters instead of being taught them.
4. Controls the screen does NOT bind are still typed into, with real key
   events, because a programmatic value assignment fills the box and changes
   nothing Nexacro can see.
5. Results come from the Dataset, never the grid: a Nexacro grid only builds
   the rows you can see, so reading the page turns 5,000 rows into 20 and
   reports success.

The order of operations is not arbitrary
----------------------------------------
    options -> organisation -> dates -> clear stale -> filters -> Inquiry

Switching a category tab or a Quick View REBUILDS the left panel and
discards whatever was set before it, so the panel options go first. Stale
values are cleared after the dates because the dates are values this run
asked for. See GMES_SKILL.md #32 and #34.

Everything here verifies its own outcome. On these systems the normal
failure produces no error at all: a filter that did not take, a query
answered from the previous screen's dataset, an export of the wrong day.
"""
import os
import re
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timedelta

import cdp_common
from cdp_common import click_element_by_rect, dispatch_key_combo, evaluate, send
import gmes_common
import gmes_data
import gmes_login
import gmes_open_screen
import gmes_profile
from gmes_common import connect_gmes

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "Data Hub Folder", "GMES")

# Two gmes_report.py/run_gmes_workflow.py processes share ONE Chrome/CDP
# session (CLAUDE.md section 0) with nothing isolating them from each
# other. Live-proven: running two at once, the second process's screen-open
# landed on a row the first process's screen had made temporarily not
# visible, and failed with "The result row could not be clicked (grid row
# not visible)" - a real symptom that gives no hint a second run is the
# cause. This lock turns that into an immediate, explicit refusal instead.
RUN_LOCK_PATH = os.path.join(gmes_profile.SCREENS_DIR, ".run.lock")


class RunLocked(RuntimeError):
    """Another G-MES run already holds RUN_LOCK_PATH."""


def _pid_alive(pid):
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def acquire_run_lock():
    """Claim RUN_LOCK_PATH for this process, or raise RunLocked.

    os.O_EXCL makes the create-if-absent check and the create itself one
    atomic filesystem operation, so two processes racing to start at the
    same instant cannot both believe they got the lock.
    """
    os.makedirs(gmes_profile.SCREENS_DIR, exist_ok=True)
    try:
        fd = os.open(RUN_LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        holder, pid = "unknown", None
        try:
            with open(RUN_LOCK_PATH, encoding="utf-8") as fh:
                holder = fh.read().strip()
            pid = int(holder.split()[0])
        except (OSError, ValueError, IndexError):
            pass
        if pid is not None and not _pid_alive(pid):
            # The process that made this lock is gone - crashed or killed
            # before it could clean up. A stale lock must not block every
            # run after it forever.
            try:
                os.unlink(RUN_LOCK_PATH)
            except OSError:
                pass
            return acquire_run_lock()
        raise RunLocked(
            "Another G-MES run already has the browser "
            f"(lock held by pid {holder!s}). Two runs sharing one Chrome/CDP "
            "session interfere with each other - wait for it to finish, or "
            f"delete {RUN_LOCK_PATH} if you are sure it is not really running.")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(f"{os.getpid()} {datetime.now():%Y-%m-%d %H:%M:%S}\n")
    return True


def release_run_lock():
    try:
        os.unlink(RUN_LOCK_PATH)
    except OSError:
        pass

# The only ids that may be hardcoded: the shell has exactly one of each.
EXCEL_BTN = "mainframe.vFrameSet1.vFrameSet2.mdiFrame.form.btnExcel"
TAB_PREFIX = "mainframe.vFrameSet1.vFrameSet2.mdiFrame.form.divTab.form.TAB_"

# Nexacro names a control by its type, and that prefix is the only reliable
# way to tell an input from a read-only display.
INPUT_PREFIXES = ("edt", "msk", "cbo", "chk", "rdo", "cal", "spn", "txt", "lst")


# ===========================================================================
# Discovery
# ===========================================================================

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
# Checkbox state used to be read from a `.checked` CSS class
# (`el.querySelector('.checked')`) - confirmed live, HISTORY.md Phase 69,
# that this Nexacro CheckBox type never adds one at all: its checked/
# unchecked look is drawn by swapping the icon IMG, not by toggling a
# class anywhere in its subtree. `hasCheckedSelector` was `false` both
# before AND after a real, confirmed-working click that correctly flipped
# the component's own `value` between its `truevalue`/`falsevalue` - so
# this test reported "unchecked" 100% of the time regardless of the real
# state. That silently broke two things at once: `set_option()`'s
# already-on guard could never see a checkbox as already checked, and its
# post-click verification could never see one as checked either, so every
# checkbox click - even a fully successful one - ended in "could not prove
# option was selected". Read the component's own `value`/`truevalue`
# instead, resolved from the DOM id by walking it as a `nexacro.
# getApplication()` property path - confirmed live to resolve correctly,
# the same technique `gfnCloseWorkFarme` used for closing a tab (HISTORY.md
# Phase 60). Falls back to the DOM-class heuristic only if that resolution
# fails, rather than assuming every checkbox on every screen is built the
# same way.
JS_LEFT_OPTIONS = r"""
(function() {
    const isVisible = %s;
    function resolveNexacro(id) {
        try {
            let obj = nexacro.getApplication();
            for (const part of id.split('.')) {
                if (obj == null) break;
                obj = obj[part];
            }
            return obj;
        } catch (e) { return null; }
    }
    function checkboxState(obj, el) {
        if (obj != null && obj.value !== undefined && obj.truevalue !== undefined) {
            return String(obj.value) === String(obj.truevalue) ? 'checked' : 'unchecked';
        }
        return el.querySelector('.checked') ? 'checked' : 'unchecked';
    }
    // The component path with the work-window segment removed. Window ids
    // embed an instance number that changes on every open (winPPM0219_0_926
    // one visit, _0_315 the next - GMES_SKILL.md #7), so the window segment
    // can never be part of an identity. Everything after it is authored in
    // the screen's XFDL and is the same for every user in every language.
    function relativePath(id) {
        const parts = id.split('.');
        for (let i = 0; i < parts.length; i++) {
            if (/^win.*_\d+_\d+$/.test(parts[i])) return parts.slice(i + 1).join('.');
        }
        return id;
    }
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
        const obj = resolveNexacro(id);
        let state = 'unknown';
        if (/_Sel\b|_Sel$|ToggleSearchV2|Category_Sel/.test(cls)) state = 'selected';
        else if (/_Dis\b|_Dis$|_Default/.test(cls)) state = 'not selected';
        else if (isChk) state = checkboxState(obj, el);
        // The CSS suffix `_Dis`/`_Default` names the DESELECTED visual
        // style, not "disabled" despite the name - a button can be
        // deselected and perfectly clickable at the same time. Whether it
        // can actually be clicked right now is the live Nexacro object's
        // own `enable` flag, which is a completely separate axis: a click
        // on btnProduce ('실적일') sent to its exact on-screen coordinates
        // changed nothing at all, live-traced down to the class never
        // moving before or after - not a detection bug like Phase 69.1's
        // checkbox, but a genuinely disabled control the click can never
        // affect. Reported here so callers can refuse BEFORE clicking
        // rather than after failing to prove a click that could not have
        // worked, which otherwise looks identical to a real bug.
        const enabled = (obj != null && obj.enable === false) ? false : true;
        // `name` is the component's own Nexacro name - btnCreate, btnPlan,
        // chkDisuseYn, tabTitle_Org. It is authored in the XFDL, so it is
        // identical whatever language the UI renders in, which is the whole
        // basis of language-independent replay (HISTORY.md Phase 76). Live
        // evidence: the control rendering '생성일' is named btnCreate, and its
        // rendered text sits in a SEPARATE property, `_displaytext`.
        // Falls back to the last id segment, which is that same name.
        const name = (obj != null && obj.name) ? String(obj.name)
                                               : (id.split('.').pop() || '');
        out.push({label: text, id: id, name: name, path: relativePath(id),
                  cls: cls.slice(0, 46), state: state,
                  kind: isChk ? 'checkbox' : 'button', enabled: enabled,
                  x: r.left + r.width / 2, y: r.top + r.height / 2});
    }
    return JSON.stringify({count: out.length, options: out});
})()
""" % cdp_common.JS_IS_VISIBLE


# Organisation trees. The nightly Production Plan job addresses exactly one -
# OrgCategory_GDS.dsCatCommonTreeNodeDVO - which is correct for that screen
# and wrong as a general rule: the left panel offers Org / Prod / Fac / Proc,
# and each tab has a tree of its own. They are found by SHAPE instead: a
# dataset carrying a `commonName` column and a `_checked` flag is a category
# tree, whatever it is called and wherever it lives.
#
# Scoped to the CURRENT screen's own window (confirmed live, HISTORY.md
# Phase 65): with three unrelated screens open at once, this used to find
# THREE identical-looking "OrgCategory_GDS.dsCatCommonTreeNodeDVO" trees -
# one per open window, not one per tab on any single screen - because it
# walked `_findForms(null)` with no window filter at all, unlike
# `JS_DISCOVER`. Since every copy shares the exact same form and dataset
# name, no `--tree` value could ever tell them apart, so `select_org()`
# refused to run at all: "'VD' appears in multiple category trees" on a
# screen that, on its own, may not be ambiguous. Left unnoticed until now
# because a single-screen CLI run rarely has another screen already open;
# an interactive session or a batch - the two ways this tool is actually
# used - very often does, since screens are not closed between reports by
# default.
JS_ORG_TREES = r"""
(function() {
    %s
    const screenCode = %s;
    const forms = _findForms(screenCode);
    if (!forms.length) return JSON.stringify({count: 0, trees: [],
        reason: 'no forms for this screen code'});
    const anchor = forms[0].path;
    const parts = anchor.split('.');
    const winIdx = parts.findIndex(p => /^win/.test(p));
    const winPath = winIdx >= 0 ? parts.slice(0, winIdx + 1).join('.') : null;

    // The shell's My Menu panels keep datasets with a commonName column too,
    // so a pure shape test found 22 "category trees" on a screen that has
    // one. They are not organisation trees and must not be offered as them.
    const SHELL = /WorkMainTitle|WorkMain\.xfdl|WorkTemplate|MyMenu|TopMenu|LeftMenu|LeftMain|PortalMain/i;
    const out = [];
    for (const h of _findForms(null)) {
        if (winPath !== null && h.path.indexOf(winPath) !== 0) continue;
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


JS_TICK_ORG = r"""
(function() {
    %s
    const treeName = %s;
    const wanted = %s;
    const exclusive = %s;
    const screenCode = %s;

    // EVERY instance of the tree, not the first one found.
    //
    // A screen can hold the same category tree several times - Work Calendar
    // has THREE copies of OrgCategory_GDS.dsCatCommonTreeNodeDVO, one per
    // panel tab - and `_dataset()` returns whichever the form walk reaches
    // first. Writing to that one and reporting success is how a run announced
    // "Tick the division ... VD" while the screen still had MOBILE ticked by
    // hand, and then exported MOBILE's rows under a VD heading.
    //
    // They are the same logical tree, so writing all of them is both safe and
    // the only way to be sure the visible one was included.
    const targets = [];
    for (const h of _findForms(screenCode)) {
        let ds = null;
        try { ds = h.form[treeName]; } catch (e) { continue; }
        if (!ds || _typeName(ds) !== 'Dataset') continue;
        let cols = [];
        try { const n = ds.getColCount();
              for (let i = 0; i < n; i++) cols.push(ds.getColID(i)); } catch (e) { continue; }
        if (cols.indexOf('commonName') < 0) continue;
        if (cols.indexOf('_checked') < 0) continue;
        targets.push({ds: ds, file: h.file});
    }
    if (!targets.length)
        return JSON.stringify({found: false, reason:
            'no instance of this tree has a _checked column'});

    const want = wanted.map(w => String(w).trim().toLowerCase());
    const ticked = [], cleared = [], present = {};
    let available = [];

    for (const t of targets) {
        const ds = t.ds;
        for (let r = 0; r < ds.getRowCount(); r++) {
            let nm = '';
            try { nm = String(ds.getColumn(r, 'commonName') || '').trim(); }
            catch (e) { continue; }
            const low = nm.toLowerCase();
            // Case-insensitive: a user typing "vd" must find "VD". An exact
            // comparison once failed a run with the answer sitting in the
            // very error message it printed.
            const isWanted = want.indexOf(low) >= 0;
            let was = '';
            try { was = String(ds.getColumn(r, '_checked') || ''); } catch (e) {}

            if (isWanted) {
                present[low] = true;
                try {
                    ds.setColumn(r, '_checked', 1);
                    let pathKey = '';
                    try { pathKey = String(ds.getColumn(r, 'commonPathKey') || ''); }
                    catch (e) {}
                    ticked.push({name: nm, pathKey: pathKey,
                                 now: String(ds.getColumn(r, '_checked'))});
                } catch (e) {}
            } else if (exclusive && was === '1') {
                // A tick SURVIVES between runs, and can also have been made
                // by hand a moment ago. Leaving one behind means the next run
                // silently queries a different organisation and answers
                // confidently with the wrong scope.
                try { ds.setColumn(r, '_checked', 0); cleared.push(nm); } catch (e) {}
            }
        }
        if (!available.length) {
            for (let r = 0; r < ds.getRowCount(); r++) {
                try { const n = String(ds.getColumn(r, 'commonName') || '').trim();
                      if (n) available.push(n); } catch (e) {}
            }
        }
    }

    const missing = want.filter(w => !present[w]);
    return JSON.stringify({found: missing.length === 0, ticked: ticked,
                           cleared: cleared, missing: missing,
                           instances: targets.length,
                           file: targets[0].file, available: available});
})()
"""


# The screen's own summary of what organisation is selected - the ground
# truth, and the only thing that would have caught the MOBILE-under-a-VD-label
# run. Reads "Org VD l Prod All l Proc All".
JS_ORG_SELECTION = r"""
(function() {
    const isVisible = %s;
    let best = null;
    for (const el of document.querySelectorAll('div')) {
        const id = el.id || '';
        if (!/staCategory(Ori)?(:text)?$/.test(id)) continue;
        if (!isVisible(el)) continue;
        const text = (el.textContent || '').trim();
        if (!/^Org\s/.test(text) || text.length > 120) continue;
        if (!best || text.length < best.length) best = text;
    }
    if (best === null) return JSON.stringify({found: false});
    // "Org VD l Prod All l Proc All" - the separator renders as a lowercase
    // L in one place and a pipe in another, so both are accepted.
    const first = best.split(/\s+[l|]\s+/)[0];
    return JSON.stringify({found: true, text: best,
                           org: first.replace(/^Org\s+/, '').trim()});
})()
"""


# What a control shows right now - used to confirm that a typed value landed.
JS_CONTROL_VALUE = r"""
(function() {
    const el = document.getElementById(%s);
    if (!el) return JSON.stringify({found: false, reason: 'no such id'});
    let v = '';
    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') v = el.value || '';
    else {
        const inner = el.querySelector('input, textarea');
        v = inner ? (inner.value || '') : (el.textContent || '').trim();
    }
    return JSON.stringify({found: true, value: v});
})()
"""


# Closing a tab. The close control is looked for INSIDE the tab element and
# matched by class or id, never guessed at by position - and if there is no
# such control this reports that instead of clicking something unknown
# (CLAUDE.md 3.9).
JS_TAB_CLOSE_TARGET = r"""
(function() {
    const isVisible = %s;
    const tab = document.getElementById(%s);
    if (!tab) return JSON.stringify({found: false, reason: 'no tab with that id'});
    const cands = [];
    for (const el of tab.querySelectorAll('div, span, button')) {
        const cls = (typeof el.className === 'string') ? el.className : '';
        const id = el.id || '';
        if (!/close/i.test(cls) && !/close/i.test(id)) continue;
        if (!isVisible(el)) continue;
        const r = el.getBoundingClientRect();
        cands.push({id: id, cls: cls.slice(0, 50), area: r.width * r.height,
                    x: r.left + r.width / 2, y: r.top + r.height / 2});
    }
    if (!cands.length)
        return JSON.stringify({found: false, reason: 'the tab has no close control'});
    cands.sort((a, b) => a.area - b.area);
    return JSON.stringify({found: true, target: cands[0]});
})()
"""


def _js(template, *args):
    return template % args


# Fallback for closing a work-screen tab when it has no separate DOM close
# control to click (confirmed live 2026-09-13, HISTORY.md Phase 60.1: a real
# open "Production Plan by Order(Line)" tab's element had only a label child,
# no close button at all, so JS_TAB_CLOSE_TARGET correctly reported "the tab
# has no close control" on every single run - `close_after=True` therefore
# never actually closed a tab of this shape, and it kept accumulating behind
# every later command, which is the same tab-reuse state Phase 58.2 found
# inflating discovery). `gfnCloseWorkFarme` - the G-MES application's own
# close-tab handler (found live by dumping the tab bar's method list and
# reading its source) - reduces to exactly this one call; it needs only the
# win_id we already have, not any DOM element at all.
JS_CLOSE_WORK_FRAME = """
(function() {
    try {
        window.nexacro.getApplication().gvMdiFrame.form.fnRemoveForm(%s);
        return JSON.stringify({ok: true});
    } catch (e) {
        return JSON.stringify({ok: false, reason: 'threw: ' + e.message});
    }
})()
"""


def close_work_frame(ws, win_id):
    result = evaluate(ws, JS_CLOSE_WORK_FRAME % cdp_common.json.dumps(win_id))
    return bool(result.get("ok"))


def discover(ws, screen_code):
    return evaluate(ws, _js(JS_DISCOVER, gmes_data.JS_HELPERS,
                            cdp_common.JS_IS_VISIBLE,
                            cdp_common.json.dumps(screen_code),
                            cdp_common.json.dumps(list(INPUT_PREFIXES)),
                            cdp_common.json.dumps(EXCEL_BTN)))


def left_options(ws):
    return evaluate(ws, JS_LEFT_OPTIONS)


# ---------------------------------------------------------------------------
# Left-panel options, identified by something other than what they say
# ---------------------------------------------------------------------------
#
# A remembered option used to be a visible label - `"options": ["Create Date"]`.
# That works exactly as long as the screen keeps rendering the language it was
# rendering when the screen was taught, and G-MES does not: the same account on
# the same machine renders `생성일` instead, and replay stopped dead with "no
# left-panel option called 'Create Date'" (HISTORY.md Open Item 19, closed in
# Phase 76).
#
# The fix is not a translation table. Live probing of the real screen found
# that every one of these controls carries its own Nexacro `name`, authored in
# the screen's XFDL and identical in every language:
#
#     생성일           -> btnCreate            과거 조직도 포함 -> chkDisuseYn
#     계획일           -> btnPlan              DB 조회        -> chkPoSearch
#     실적일           -> btnProduce           일반 검색       -> btnSearchNormal
#     Org/Prod/...    -> tabTitle_Org/...     비교 검색       -> btnSearchCompare
#
# So the identity is the component name, the semantic key is that name
# normalised, and the visible text is demoted to display metadata.

#: Nexacro control-type prefixes. `tabtitle_` first: it starts with `tab`, and
#: stripping the shorter one would leave `title_org` instead of `org`.
_OPTION_PREFIXES = ("tabtitle_", "btn", "chk", "rdo", "cbo", "spn", "tab")


def option_key(name):
    """The normalised, language-independent semantic key for an option.

    `btnCreate` -> `create`, `chkDisuseYn` -> `disuseyn`, `tabTitle_Org` ->
    `org`, `btnstd` -> `std`. Case and the control-type prefix carry no
    meaning, so neither survives."""
    text = re.sub(r"[^a-z0-9_]+", "", (name or "").strip().lower())
    for prefix in _OPTION_PREFIXES:
        if text.startswith(prefix) and len(text) > len(prefix):
            text = text[len(prefix):]
            break
    return text.replace("_", "")


def option_words(text):
    """The ASCII words in a requested option name, lowercased.

    Korean and punctuation fall away deliberately: this is only ever used for
    the alias step, which exists to rescue an ENGLISH label saved by an older
    profile. A Korean request is matched by its label directly, exactly."""
    return [w for w in re.split(r"[^a-z0-9]+", (text or "").lower()) if w]


def option_identity(opt):
    """What gets written into a profile: the stable identity plus, separately,
    the text that happened to be on screen when it was learned.

    The label is kept because a person reading their own profile should be able
    to tell what `btnCreate` was, and because it still serves as the migration
    path for anything recorded before this existed. It is never matched on
    first."""
    return {"key": option_key(opt.get("name")),
            "name": opt.get("name") or "",
            "path": opt.get("path") or "",
            "label": opt.get("label") or ""}


def option_display(wanted):
    """One human-readable token for a log line, from either profile shape."""
    if isinstance(wanted, dict):
        label, key = wanted.get("label"), wanted.get("key") or wanted.get("name")
        if label and key:
            return f"{label} [{key}]"
        return label or key or "?"
    return str(wanted)


def _alias_candidates(found, wanted_text):
    """Options whose semantic key is derivable from an English request.

    This is the migration rescue, and it is deliberately narrow. Only two
    rules, both exact:

      * the whole request, punctuation removed, IS the key  - "PLANT" -> plant
      * the request's FIRST word is the key                 - "Create Date"
                                                              -> create

    Anything looser guesses. A "key appears anywhere in the request" rule was
    written first and rejected after testing it against this very screen:
    "Including Past Org." contains the word "org", so it matched the Org
    CATEGORY TAB (`tabTitle_Org`) instead of the `chkDisuseYn` checkbox it
    means - a confidently wrong match that would silently change what the
    query returns. Nothing is better than that, because nothing stops and
    says so (CLAUDE.md 3.9).

    Note "Plan Date" -> `plan` and "PLANT" -> `plant` stay distinct under
    these rules, which a prefix rule would not have managed."""
    words = option_words(wanted_text)
    if not words:
        return []
    joined = "".join(words)
    hits = []
    for opt in found:
        key = option_key(opt.get("name"))
        if not key:
            continue
        if key == joined or key == words[0]:
            hits.append(opt)
    return hits


def _option_diagnostics(found):
    """Every option with everything needed to name one unambiguously."""
    return ", ".join(
        f"{o.get('label')!r} [{option_key(o.get('name'))}]" for o in found[:20])


def resolve_option(found, wanted):
    """Find the one option `wanted` means, or raise saying why not.

    `wanted` is either a profile entry (a dict carrying the stable identity) or
    a plain string - what `--option` passes, and what every profile written
    before Phase 76 contains.

    The order is strongest-evidence-first, and each step must produce exactly
    one match or the next is tried:

      1. component name      language-independent, the identity we now store
      2. component path      distinguishes two controls sharing a name
      3. semantic key        the normalised form of 1
      4. exact label         what a person reading the screen types
      5. English alias       rescues a pre-Phase-76 profile (see above)
      6. label substring     the historical last resort, unchanged

    Returns (option, how). Raises on no match AND on ambiguity - never picks
    one of several (CLAUDE.md 3.9). The message lists every option with its
    key, so the answer to "then what should I have said" is in the failure
    itself rather than requiring another run to find out."""
    if isinstance(wanted, dict):
        attempts = [
            ("component name", lambda o: (o.get("name") or "").lower()
             == (wanted.get("name") or "\0").lower()),
            ("component path", lambda o: (o.get("path") or "").lower()
             == (wanted.get("path") or "\0").lower()),
            ("semantic key", lambda o: option_key(o.get("name"))
             == (wanted.get("key") or "\0")),
        ]
        text = wanted.get("label") or wanted.get("name") or ""
    else:
        text = str(wanted)
        attempts = [
            ("component name", lambda o: (o.get("name") or "").lower() == text.lower()),
            ("semantic key", lambda o: option_key(o.get("name")) == option_key(text)),
        ]

    attempts += [
        ("label", lambda o: (o.get("label") or "").strip().casefold()
         == text.strip().casefold()),
    ]

    for how, predicate in attempts:
        matches = [o for o in found if predicate(o)]
        if len(matches) == 1:
            return matches[0], how
        if len(matches) > 1:
            raise RuntimeError(
                f"{option_display(wanted)!r} matches {len(matches)} left-panel "
                f"options by {how}: {_option_diagnostics(matches)}. Refusing to "
                "guess - name one by its key.")

    for how, matches in (("english alias", _alias_candidates(found, text)),
                         ("label fragment",
                          [o for o in found
                           if text.strip() and text.strip().casefold()
                           in (o.get("label") or "").casefold()])):
        if len(matches) == 1:
            return matches[0], how
        if len(matches) > 1:
            raise RuntimeError(
                f"{option_display(wanted)!r} matches {len(matches)} left-panel "
                f"options by {how}: {_option_diagnostics(matches)}. Refusing to "
                "guess - name one by its key.")

    raise RuntimeError(
        f"no left-panel option matching {option_display(wanted)!r}. "
        f"This screen offers: {_option_diagnostics(found)}. "
        "The name in [brackets] is language-independent and is what a "
        "recorded profile stores; pass one of those with --option.")


def org_trees(ws, screen_code):
    return evaluate(ws, _js(JS_ORG_TREES, gmes_data.JS_HELPERS,
                            cdp_common.json.dumps(screen_code)))


# A work-screen validation alert (e.g. "Start Date is later than End Date")
# is not the title-bar popup `find_child_popups()` detects - that mechanism
# was built for sign-in Notice popups (HISTORY.md Phase 59.1) and reads the
# POPUP'S OWN title bar text, which came back empty for this alert when
# confirmed live: `poll_inquiry()` correctly detected that SOMETHING opened
# and safely stopped, but could only report `['']`, losing the real message
# G-MES had already put on screen. The real text lives in a `txt_WF_alert`
# Static nested under the work window itself (`<winId>.Info_N.form.divBody.
# form.staContents`), confirmed by live DOM dump - reached by CLASS, not the
# `Info_N` suffix, which is exactly the kind of generated, renumbered id
# CLAUDE.md 3.4 already rules out. Scoped to the current screen's window for
# the same reason `org_trees()` had to be (HISTORY.md Phase 65.1): an
# unrelated alert on a DIFFERENT open screen must not bleed into this one's
# error message.
JS_ALERT_TEXT = r"""
(function() {
    %s
    const screenCode = %s;
    const forms = _findForms(screenCode);
    if (!forms.length) return JSON.stringify({texts: []});
    const anchor = forms[0].path;
    const parts = anchor.split('.');
    const winIdx = parts.findIndex(p => /^win/.test(p));
    if (winIdx < 0) return JSON.stringify({texts: []});
    // _findForms() paths carry an "application." prefix that real DOM ids
    // never have (the same translation JS_DISCOVER's own domId() already
    // does) - comparing the raw object-path winPath against el.id matched
    // nothing at all, confirmed live: every real .txt_WF_alert id started
    // with "mainframe...", not "application.mainframe...".
    const winPath = parts.slice(0, winIdx + 1).join('.').replace(/^application\./, '');

    const texts = [];
    for (const el of document.querySelectorAll('.txt_WF_alert')) {
        if ((el.id || '').indexOf(winPath) !== 0) continue;
        const t = (el.textContent || '').trim();
        if (t) texts.push(t);
    }
    return JSON.stringify({texts: texts});
})()
"""


def alert_text(ws, screen_code):
    """The real message behind a work-screen validation alert, if any -
    see JS_ALERT_TEXT above. Best-effort: a read failure here must never
    hide the original "a dialog opened" error underneath it."""
    try:
        result = evaluate(ws, _js(JS_ALERT_TEXT, gmes_data.JS_HELPERS,
                                  cdp_common.json.dumps(screen_code)))
        return result.get("texts", [])
    except Exception:
        return []


# ===========================================================================
# Pure helpers - no browser, so they are unit-testable offline
# ===========================================================================

def normalise_date(value):
    """Accept the ways people actually type a date; return G-MES's YYYYMMDD.

    A date typed as 2026-09-07 used to be written into the filter verbatim.
    G-MES stores YYYYMMDD, so the query ran against a value it could not
    interpret - no error, just a different answer. Anything not resolvable to
    a real calendar date is rejected rather than passed through and hoped
    for."""
    raw = (value or "").strip()
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    if len(digits) != 8:
        raise ValueError(f"{value!r} is not a date. Use YYYYMMDD (20260907) or "
                         "YYYY-MM-DD (2026-09-07).")
    try:
        datetime.strptime(digits, "%Y%m%d")
    except ValueError:
        raise ValueError(f"{value!r} is not a real calendar date.")
    return digits


def fit_date_to_field(yyyymmdd, current_value):
    """Match the width the field is actually storing.

    Not every G-MES period field holds a full date. Month fields (`stdYm`,
    `paramYm`) hold YYYYMM, and writing eight digits into one of those is the
    same class of mistake as writing "2026-09-07" into a YYYYMMDD field: it is
    accepted, and the query then answers something else. The width already in
    the box is the screen telling us which it wants."""
    existing = re.sub(r"[^\d]", "", (current_value or "").strip())
    if len(existing) == 6:
        return yyyymmdd[:6]
    if len(existing) == 4:
        return yyyymmdd[:4]
    return yyyymmdd


_DATE_WORDS = {"date", "dates", "ymd", "ym", "dt", "day", "period", "yyyymmdd"}
_FROM_WORDS = {"from", "start", "fr", "st", "begin"}
_TO_WORDS = {"end", "to", "thru", "through", "until", "last"}


def words(name):
    """Split an identifier into lowercase words: paramFromDate -> from, date.

    Substring matching is not safe here and produced a concrete trap:
    `paramVendorCode` contains "end", so a plain search classified a vendor
    code as the period's end date. Only whole camel-case or underscore words
    count."""
    parts = re.split(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])", name or "")
    return {p.lower() for p in parts if p}


def is_date_field(flt):
    """Whether a discovered filter is a date or period field.

    Two signals, because neither holds alone. The column or label naming a
    date is the strong one. Failing that, Nexacro's own control type: a date
    is a masked edit or a calendar (`msk`, `cal`) holding four, six or eight
    digits. The shape of the value is deliberately NOT a signal on its own -
    plenty of eight-digit codes are not dates."""
    named = (words(flt.get("column")) | words(flt.get("label"))) & _DATE_WORDS
    if named:
        return True
    control = (flt.get("control") or "").lower()
    value = digits_only(flt.get("value"))
    return control.startswith(("msk", "cal")) and len(value) in (0, 4, 6, 8)


def date_named_columns(columns):
    """Which of a result's own column names merely LOOK like a date - naming
    only, no value shape checked. Used to suggest real `--verify` candidates
    before Inquiry has ever run, when there are no row values yet to confirm
    against. `Screen.date_like_columns()` re-checks the shape once rows
    exist; this is the weaker, earlier-available half of that same test."""
    return [c for c in columns if not c.startswith("_") and words(c) & _DATE_WORDS]


def date_targets(info):
    """Split the screen's date fields into (from, to, singles).

    The previous rule matched only `*fromdate*` / `*enddate*`, so a screen
    storing `paramYmd` or `stdYm` was reported as having no date filter at all
    and the run silently used whatever the screen had in it."""
    dates = [f for f in info.get("filters", []) if is_date_field(f)]

    def tagged(vocab):
        for f in dates:
            if words(f.get("column")) & vocab or words(f.get("control")) & vocab:
                return f
        return None

    frm = tagged(_FROM_WORDS)
    to = tagged(_TO_WORDS)
    singles = [f for f in dates if f is not frm and f is not to]
    return frm, to, singles


def match_filter(info, key, include_unbound=True):
    """Resolve a name to a discovered control.

    Accepts the column name, the visible label, or the control name - in that
    order of confidence - so a screen can be driven either the way it reads on
    screen or the way it is stored. Returns one control, a list when the name
    is ambiguous, or None."""
    pool = list(info.get("filters", []))
    if include_unbound:
        pool += list(info.get("unbound", []))
    k = key.strip().lower()

    for attr in ("column", "label", "control"):
        exact = [f for f in pool if (f.get(attr) or "").lower() == k]
        if len(exact) == 1:
            return exact[0]
        if exact:
            return exact
    partial = [f for f in pool
               if k in (f.get("label") or "").lower()
               or k in (f.get("column") or "").lower()
               or k in (f.get("control") or "").lower()]
    if len(partial) == 1:
        return partial[0]
    return partial or None


def choose_grid(info, prefer=None):
    """Pick the grid holding the report's rows, and say when the pick is a guess.

    The default is the biggest visible grid, which is right on a single-result
    screen and a coin toss on a master-detail one. A silent coin toss is
    exactly the failure this project keeps hitting, so when a second grid is
    comparable in size the choice is reported as ambiguous and the caller
    prints it. `prefer` (a grid or dataset name) settles it outright.

    Returns (grid, alternatives) - alternatives is empty when the pick is
    unambiguous."""
    grids = info.get("grids", [])
    if not grids:
        return None, []

    if prefer:
        p = prefer.strip().lower()
        for attr in ("dataset", "name"):
            exact = [g for g in grids if g[attr].lower() == p]
            if exact:
                return exact[0], []
        partial = [g for g in grids
                   if p in g["dataset"].lower() or p in g["name"].lower()]
        if len(partial) == 1:
            return partial[0], []
        if partial:
            return None, partial
        return None, grids

    visible = [g for g in grids if g["visible"]]
    # Sorted here as well as in the JS, so this function is correct on its own
    # terms rather than on an assumption about its caller.
    pool = sorted(visible or grids, key=lambda g: g["area"], reverse=True)
    best = pool[0]
    rivals = [g for g in pool[1:] if g["area"] > best["area"] * 0.4]
    return best, rivals


def digits_only(value):
    return re.sub(r"[^\d]", "", str(value or ""))


def is_pure_number(text):
    """Whether `text` is safe to compare by DIGITS ALONE - a bare number or
    a date written with only digit-grouping punctuation this codebase
    actually uses for dates (-, /, :, space), the shape `digits_only()`
    exists for (2026-09-08 == 20260908).

    Confirmed live, a second time: `.` is a DECIMAL POINT, not a date
    separator this project's own `normalise_date()` ever produces or
    accepts - `values_match("1.2", "12")` was `True`, both reducing to
    digits `"12"`, before `.` was excluded here. A leading `-` or `+` is a
    SIGN, not the mid-string date separator in `2026-09-08` -
    `values_match("-1", "1")` was also `True`, both reducing to `"1"`,
    before a leading sign was excluded. Neither collision is theoretical:
    a quantity field ("Remain Q'ty", a negative adjustment) sits right next
    to date columns on the very screens this tool drives. A mid-string `-`
    or `/` is still accepted (a real date), and a value that fails this
    check still compares correctly as exact text in `values_match()` - it
    only loses the date-reformatting equivalence, which a non-date value
    never needed anyway.

    A narrower residual case is NOT handled: a `/`-separated value shaped
    like a small fraction (`"1/2"`) still reduces to digits like a date
    would (`digits_only("1/2") == "12"`, colliding with a bare `"12"`) -
    `/` cannot simply be excluded the way `.` was, since real dates
    (`2026/09/08`) depend on it. Accepted as an open, narrower risk rather
    than guessed at with a date-shape validator this session could not
    verify against enough real screens to trust."""
    text = str(text or "").strip()
    if not text or text[0] in "+-":
        return False
    return bool(re.fullmatch(r"[\d\-/: ]+", text)) and bool(digits_only(text))


def values_match(wanted, got):
    """The one comparison `verify_rows()`, `apply()` and `type_text()` all
    need: equal as digits-only when BOTH sides are genuinely numbers, equal
    as casefolded text otherwise.

    Checking only ONE side's shape is not enough, and this project shipped
    that exact mistake twice. `is_pure_number(expected)` alone let a result
    of MODEL-B1 verify against an expected MODEL-A1 (both reduce to digit
    "1"); checking only the WANTED side the other way let a wanted "123"
    silently accept an actual value of "X123", confirmed live:
    `verify_rows(..., column, "123")` against a row holding "X123" returned
    `problem=None` - accepted - because "123" alone looked like a number
    worth reducing to digits, and nothing checked what the row actually
    held before doing the same reduction to it. Both sides have to look
    like the same kind of value before comparing them as one."""
    wanted_text = str(wanted or "").strip()
    got_text = str(got or "").strip()
    if is_pure_number(wanted_text) and is_pure_number(got_text):
        return digits_only(wanted_text) == digits_only(got_text)
    return wanted_text.casefold() == got_text.casefold()


# ===========================================================================
# Dataset-level operations
#
# These take a screen code and a dataset name rather than a Screen, so the
# one hardcoded job (gmes_daily_prodplan.py) drives exactly the same code as
# the generic runner. The alternative - a second implementation for the job -
# is how the lying row count in Phase 10.4 happened.
# ===========================================================================

def tick_org(ws, form_code, dataset, names, exclusive=True):
    """Tick entries in a category tree by their visible name."""
    if isinstance(names, str):
        names = [names]
    return evaluate(ws, _js(JS_TICK_ORG, gmes_data.JS_HELPERS,
                            cdp_common.json.dumps(dataset),
                            cdp_common.json.dumps(list(names)),
                            "true" if exclusive else "false",
                            cdp_common.json.dumps(form_code)))


def org_selection(ws):
    """What the SCREEN says is selected, e.g. {'org': 'VD'}.

    Read back after ticking, because the dataset write is not proof. The
    write went into one of three copies of the tree while the visible one
    still had MOBILE ticked by hand; the run reported VD and exported
    MOBILE's rows. This label is what the screen itself believes."""
    try:
        return evaluate(ws, _js(JS_ORG_SELECTION, cdp_common.JS_IS_VISIBLE))
    except Exception as e:
        return {"found": False, "reason": str(e)}


def read_rows(ws, form_code, dataset, limit=-1):
    return gmes_data.read_dataset(ws, form_code, dataset, limit=limit)


def verify_rows(ws, form_code, dataset, column, expected, sample=None):
    """Confirm the returned rows carry the value that was asked for.

    A stale result set looks exactly like a fresh one, and an export of the
    wrong day is worse than no export. Digits are compared rather than text,
    so 2026-09-08 and 20260908 are the same answer.

    Returns (values_seen, problem). `problem` is None when the result agrees;
    the caller decides whether a disagreement is fatal."""
    result = read_rows(ws, form_code, dataset, limit=-1)
    if not result.get("found"):
        return None, "the result dataset disappeared before verification"
    if not result["rows"]:
        return None, "the result dataset contains no rows to verify"
    if column not in result["columns"]:
        near = [c for c in result["columns"] if column.lower() in c.lower()]
        return None, (f"the result has no {column!r} column"
                      + (f" - did you mean {near[:4]}?" if near else ""))
    expected_text = str(expected or "").strip()
    if not expected_text:
        return None, "verification needs an expected value"
    # Compared per row, not by one global "is the EXPECTED value a number"
    # flag - a row's own value can be a different shape than what was
    # asked for, and only checking the expected side let a wanted "123"
    # silently accept an actual "X123" (see values_match()'s docstring).
    raw = [str(r.get(column) or "").strip() for r in result["rows"]]
    raw = [v for v in raw if v]
    if not raw:
        return [], f"the results contain no values in {column!r}"
    seen = sorted(set(raw))
    if any(not values_match(expected_text, v) for v in raw):
        return seen, (f"the results carry {column}={seen}, not exactly the "
                      f"requested {expected_text}")
    return seen, None


def verify_date_range(ws, form_code, dataset, column, date_from, date_to):
    """Confirm every row's date column falls WITHIN [date_from, date_to]
    inclusive - `verify_rows()`'s range equivalent.

    Confirmed live: a genuine multi-day query (`--from 20260901 --to
    20260910` on P1112UM00, 6529 rows) correctly returned rows spanning
    that whole window - and `verify_rows()`, which only ever compares
    every row to ONE expected value (`date_from`, since `--verify COLUMN`
    with no explicit `=VALUE` had no other value to use), rejected the
    entire, genuinely correct answer: "the results carry
    creYmd=['20260901', '20260902', ..., '20260909'], not exactly the
    requested 20260901". A multi-day report could never pass verification
    at all, which is worse than not verifying - it teaches a person to
    stop using `--verify` rather than trust it.

    Returns (values_seen, problem), matching `verify_rows()`'s shape."""
    result = read_rows(ws, form_code, dataset, limit=-1)
    if not result.get("found"):
        return None, "the result dataset disappeared before verification"
    if not result["rows"]:
        return None, "the result dataset contains no rows to verify"
    if column not in result["columns"]:
        near = [c for c in result["columns"] if column.lower() in c.lower()]
        return None, (f"the result has no {column!r} column"
                      + (f" - did you mean {near[:4]}?" if near else ""))
    lo, hi = digits_only(date_from), digits_only(date_to)
    if len(lo) != 8 or len(hi) != 8:
        return None, f"the range {date_from}-{date_to} is not two YYYYMMDD dates"
    raw = [str(r.get(column) or "").strip() for r in result["rows"]]
    raw = [v for v in raw if v]
    if not raw:
        return [], f"the results contain no values in {column!r}"
    seen = sorted(set(raw))
    # Same-width YYYYMMDD strings sort and compare lexicographically the
    # same as chronologically; a value that does not even reduce to 8
    # digits cannot be compared at all and counts as out of range rather
    # than being silently skipped.
    out_of_range = sorted({v for v in raw
                           if len(digits_only(v)) != 8 or not (lo <= digits_only(v) <= hi)})
    if out_of_range:
        return seen, (f"the results carry {column} values outside the "
                      f"requested {date_from}-{date_to}: {out_of_range}")
    return seen, None


class InquirySettle:
    """The settle-decision core of `poll_inquiry()`, isolated from the
    browser calls so it can be unit-tested against a synthetic sequence of
    row-count readings instead of only ever being verified live.

    Requiring `changed` (the count differing from either the pre-click
    snapshot OR the previous poll) was meant to stop a dataset left
    populated by an earlier run from being mistaken for a finished query.
    Live-traced instead of assumed (HISTORY.md Phase 65.2): replaying
    M4131UM00 with the SAME division right after recording it produced the
    SAME correct 10-row answer, and the count did not merely fail to differ
    from `before` - it stayed at exactly 10 on every single poll, never
    dipping through 0, for 17+ seconds of direct observation. Nexacro does
    not always visibly clear a dataset before refilling it; sometimes a
    re-query updates it in place with no observable transition at all. A
    live probe for any OTHER signal (an overlay/spinner class, the Inquiry
    button's own class toggling) found none either - row count genuinely is
    the only thing available to poll here.

    So `changed` can no longer be a hard requirement without reintroducing
    the 300s hang this was traced to fix, but dropping it outright would
    remove the one thing standing between "the query genuinely re-ran" and
    "the click landed but nothing happened, and stale data is just sitting
    there" - `click_control()` finding and clicking the right element is
    real but not total assurance the query actually ran. The compromise:
    settle quickly (`settle_checks`) when a change WAS observed - the
    common, unambiguous case, unchanged from before - and settle only after
    much longer, sustained stability (`unconfirmed_settle_checks`, default
    3x) when no change was ever observed. Real confidence is still rewarded
    with a fast return; its absence costs patience, not a five-minute
    failure on a result that was correct the entire time.

    A zero count used to be a hard exception to all of this: `step()` reset
    `stable` to 0 on every zero reading and never returned a settled 0, no
    matter how long the count held there. Live-traced (HISTORY.md Phase
    71): a query against a date range with genuinely no matching rows -
    completely ordinary in production, e.g. no orders yet for a future
    date - burned the full 300s `max_wait` and then failed with "the query
    had not settled", every time, for an answer that was correct within a
    second of being clicked. Zero is not special: the SAME asymmetric
    settle/unconfirmed-settle logic already trusted for a nonzero count
    applies to it unchanged - fast if a change was observed (e.g. a stale
    nonzero count from an earlier screen dropping to 0), the slower but
    still bounded `unconfirmed_settle_checks` window if it was 0 from the
    very first reading. A genuinely empty result now costs the same
    patience an unconfirmed nonzero one already did, not an unconditional
    300s failure."""

    def __init__(self, before, settle_checks=4, unconfirmed_settle_checks=None):
        self.before = before
        self.previous = before
        self.last = None
        self.stable = 0
        self.changed = False
        self.settle_checks = settle_checks
        self.unconfirmed_settle_checks = unconfirmed_settle_checks or settle_checks * 3

    def step(self, count):
        """Feed one new reading. Returns the settled count, or None to
        keep polling. Zero is not a special case: the same
        confirmed/unconfirmed threshold applies to it as to any other
        value, so a genuinely empty result settles too, just with the
        same patience an unconfirmed nonzero one already needs."""
        if count != self.before or count != self.previous:
            self.changed = True
        self.previous = count
        self.stable = self.stable + 1 if count == self.last else 0
        self.last = count
        threshold = self.settle_checks if self.changed else self.unconfirmed_settle_checks
        if self.stable >= threshold:
            return count
        return None


def poll_inquiry(ws, form_code, dataset, max_wait=300, settle_checks=4,
                 poll_interval=1.0):
    """Click Inquiry and wait for THIS screen's result set to settle.

    Polling a dataset by a hardcoded name reported 875 rows - the count still
    sitting in the PREVIOUS screen's dataset - for a screen that had returned
    17. The export was right because it used the discovered dataset; only the
    number and the wait were wrong, which is the more dangerous combination:
    the file is correct, the log lies, and nobody checks.

    An empty result set does not mean the query finished either. Nexacro
    clears the dataset the instant Inquiry is pressed and refills it when the
    server answers, so the count sits at 0 for the whole round trip. Treating
    ANY stable zero as settled immediately reported 0 rows and refused to
    export while 790 rows were on their way.

    So: prefer the count to have been seen CHANGING, so a dataset left
    populated by an earlier run - or, symmetrically, a zero-row round trip
    still in flight - is not mistaken for a finished query on its first
    stable reading. Zero itself is not otherwise a special case (Phase 71):
    a genuinely empty result settles the same way an unconfirmed nonzero one
    does, after sustained stability, not never. Neither cap is an estimate of
    how long the query takes - the loop exits the moment it has its answer,
    which is what makes a generous cap free.

    "Changed" cannot be a hard requirement, though - confirmed by two rounds
    of live investigation, not assumed (HISTORY.md Phase 65.2). Replaying
    M4131UM00 with the same division right after recording it produced the
    same correct 10-row answer, and directly tracing the poll loop showed
    the count sitting at exactly 10 on EVERY single reading, never dipping
    through 0, for 17+ seconds - not merely "equal to the pre-click value",
    genuinely never changing at all, poll to poll, the whole time. A
    fresh query with an unchanged, correct answer can look, from row count
    alone, IDENTICAL to a click that silently did nothing. A live search for
    any other observable signal (a busy overlay, the Inquiry button's own
    class toggling) found none either - row count is genuinely all there is
    to poll on this screen. See `InquirySettle`'s docstring for how the two
    cases are told apart anyway: fast settlement when a change WAS seen,
    slower (but bounded, not infinite) settlement when it was not."""
    def row_count():
        r = read_rows(ws, form_code, dataset, limit=0)
        return r.get("total", -1) if r.get("found") else -1

    before = row_count()
    button = gmes_common.click_control(ws, cls="btn_LF_Search_New", text="Inquiry")
    if not button:
        raise RuntimeError("the Inquiry button was not found on this screen")

    tracker = InquirySettle(before, settle_checks)
    started = time.time()

    while time.time() - started < max_wait:
        time.sleep(poll_interval)
        count = row_count()

        # An alert instead of results - usually "no data found", or a
        # validation rejection (e.g. "Start Date is later than End Date").
        # The popup's own title-bar text is unreliable here (confirmed
        # live: empty for a validation alert) - alert_text() reads the
        # real on-screen message instead, when there is one.
        popups = gmes_common.find_child_popups(ws)
        if popups.get("count"):
            texts = alert_text(ws, form_code)
            if texts:
                raise RuntimeError(f"a dialog opened instead of results: {'; '.join(texts)}")
            names = [p["name"] for p in popups["popups"]]
            raise RuntimeError(f"a dialog opened instead of results: {names}")

        settled = tracker.step(count)
        if settled is not None:
            return settled

    raise RuntimeError(f"the query had not settled after {max_wait}s "
                       f"(last count {tracker.last})")


# ===========================================================================
# Typing into a control that has no dataset behind it
# ===========================================================================

def _key_events(ch):
    """CDP key parameters for one character.

    `char` carries the actual text, which is what the input consumes; the
    keyDown/keyUp pair is what Nexacro's own onkeyup handlers watch for. The
    code/virtual-key values are only right for letters and digits, and that is
    enough - punctuation still arrives through the `char` event."""
    if ch.isalpha():
        return f"Key{ch.upper()}", ord(ch.upper())
    if ch.isdigit():
        return f"Digit{ch}", ord(ch)
    return "", 0


def type_text(ws, dom_id, text, clear=True, commit=True, verify=True):
    """Type into a control with real key events, then confirm what it shows.

    Nexacro's own `set_value()` fills a box and changes nothing the control
    reacts to - that is how the screen search box was filled while searching
    for nothing. The suggestion lists, validation and value commits all hang
    off the key handlers, so the keys have to be real."""
    box = evaluate(ws, gmes_common.js_find_by_id(dom_id))
    if not box.get("found"):
        raise RuntimeError(f"the control {dom_id.split('.')[-1]} is not on screen "
                           f"({box.get('reason')})")
    click_element_by_rect(ws, box["x"], box["y"])
    time.sleep(0.3)

    if clear:
        dispatch_key_combo(ws, "a", "KeyA", 65, ctrl=True)
        dispatch_key_combo(ws, "Delete", "Delete", 46)
        time.sleep(0.1)

    for ch in str(text):
        code, vk = _key_events(ch)
        for kind in ("keyDown", "char", "keyUp"):
            params = {"type": kind, "key": ch, "code": code}
            if kind == "char":
                params["text"] = ch
            elif vk:
                params["windowsVirtualKeyCode"] = vk
            send(ws, "Input.dispatchKeyEvent", params)
        time.sleep(0.05)

    if commit:
        # Nexacro commits an edit on blur. Without this the value sits in the
        # editor and the Inquiry runs on the previous one.
        dispatch_key_combo(ws, "Tab", "Tab", 9)
        time.sleep(0.3)

    if not verify:
        return str(text)
    shown = evaluate(ws, _js(JS_CONTROL_VALUE, cdp_common.json.dumps(dom_id)))
    got = (shown.get("value") or "").strip()
    # A third, separate call site with the exact class of one-sided/ungated
    # digits_only() comparison found in verify_rows() and apply() (HISTORY.md
    # Phase 66) - here not even gated on the WANTED side being a number, so
    # typing "MODEL-A1" and reading back "MODEL-B1" (both reduce to digit
    # "1") was accepted as having taken correctly. values_match() requires
    # BOTH sides to look like the same kind of value before comparing them
    # as digits at all.
    if not values_match(text, got):
        raise RuntimeError(f"typing into {dom_id.split('.')[-1]} did not take - "
                           f"it shows {got!r}, not {str(text)!r}")
    return got


# ===========================================================================
# One open screen
# ===========================================================================

class Screen:
    """A live handle on one open, active G-MES work screen."""

    def __init__(self, ws, code, opened, info):
        self.ws = ws
        self.code = code.strip().upper()
        self.menu_id = opened.get("menuId", "")
        self.win_id = opened.get("winId", "")
        self.title = opened.get("title", "") or self.code
        self.info = info
        self.warnings = []
        self.last_tree = None       # which category tree the division came from

    # -- introspection ------------------------------------------------------

    def refresh(self):
        """Re-read the screen. Required after anything that rebuilds the left
        panel - a category tab or a Quick View entry replaces the controls,
        so a handle taken before the click points at elements that no longer
        exist."""
        self.info = discover(self.ws, self.code)
        return self.info

    @property
    def filters(self):
        return self.info.get("filters", [])

    @property
    def unbound(self):
        return self.info.get("unbound", [])

    def options(self):
        return left_options(self.ws).get("options", [])

    def trees(self):
        return org_trees(self.ws, self.code).get("trees", [])

    def grid(self, prefer=None):
        grid, rivals = choose_grid(self.info, prefer)
        if grid is None:
            if rivals:
                names = ", ".join(f"{g['name']} -> {g['dataset']}" for g in rivals[:6])
                raise RuntimeError(f"which grid? this screen has: {names}. "
                                   "Name one with --grid.")
            raise RuntimeError("no result grid was found on this screen")
        if rivals:
            names = ", ".join(f"{g['name']}({g['dataset']})" for g in rivals[:6])
            raise RuntimeError(
                f"more than one plausible result grid: {grid['name']}({grid['dataset']}), {names}. "
                "Pass --grid to prove which dataset is the report.")
        return grid

    @staticmethod
    def form_code(entry):
        """The screen code a dataset lives on. `_findForms` matches on the
        file name, so the .xfdl.js suffix has to come off."""
        return (entry.get("form") or "").replace(".xfdl.js", "")

    # -- setting ------------------------------------------------------------

    def set_option(self, wanted, verify_wait=6):
        """Select a left-panel option, unless it already is, and confirm it.

        `wanted` is a profile entry carrying the component's stable Nexacro
        name, or a plain string (what `--option` passes, and what every profile
        written before HISTORY.md Phase 76 holds). `resolve_option()` decides
        which; this method is deliberately not where that logic lives, so the
        matching can be tested without a browser.

        Returns a dict: `outcome` for the log, plus the resolved stable
        identity, so the caller can write THAT into the profile rather than
        whatever text it was asked with. That is what makes an old
        English-labelled profile heal itself on its next successful run."""
        found = left_options(self.ws)["options"]
        opt, how = resolve_option(found, wanted)
        identity = option_identity(opt)

        def done(outcome):
            return {"outcome": outcome, "matched_by": how, **identity}

        # JS_LEFT_OPTIONS reports a BUTTON-style option as "selected"/"not
        # selected" but a CHECKBOX-style one as "checked"/"unchecked" - only
        # "selected" counted as already-on here, so asking to switch on an
        # option that was a checkbox and was ALREADY checked fell through
        # to the click below and toggled it OFF instead of leaving it
        # alone, silently changing what the query means in the opposite
        # direction from what was asked.
        if opt["state"] in ("selected", "checked"):
            return done(f"{opt['label']} [{identity['key']}] "
                        f"(already {opt['state']})")

        # Live-traced (HISTORY.md Phase 71.2): a click on a genuinely
        # disabled option (Nexacro's own `enable` flag false - a screen-state
        # precondition, e.g. a date-kind toggle only meaningful under a
        # different category tab) lands at the exact right coordinates and
        # changes nothing at all. Caught here, before clicking, so the
        # failure says WHY rather than looking identical to an unproven
        # click that might have actually worked.
        if not opt.get("enabled", True):
            raise RuntimeError(
                f"option {opt['label']!r} is disabled in the current screen "
                "state - nothing was clicked")

        click_element_by_rect(self.ws, opt["x"], opt["y"])

        deadline = time.time() + verify_wait
        outcome = None
        while time.time() < deadline:
            time.sleep(0.5)
            now = left_options(self.ws)["options"]
            # Re-found by component NAME, not by label. The click can rebuild
            # the panel, and a rebuilt panel is exactly where a label could
            # come back rendered differently - re-identifying the control by
            # the thing that does not change is the point of this whole phase.
            cur = next((o for o in now
                        if (o.get("name") or "").lower() == (opt.get("name") or "").lower()),
                       None)
            if cur and cur["state"] in ("selected", "checked"):
                outcome = f"{cur['label']} [{identity['key']}] -> {cur['state']}"
                break
        # The panel may have been rebuilt by that click, which invalidates
        # every control path discovered before it.
        self.refresh()
        if outcome is None:
            raise RuntimeError(
                f"could not prove option {opt['label']!r} "
                f"[{identity['key']}] was selected")
        return done(outcome)

    def select_org(self, names, tree=None, prefer=None, exclusive=True):
        """Tick one or more entries in a category tree.

        Without this the query returns nothing at all and the screen says
        "Select Search Criteria" - the single most likely cause of a silent
        empty export.

        The tree is found by shape rather than by its name, so the Prod / Fac
        / Proc tabs work as well as Org. `exclusive` clears ticks this run did
        not ask for: a tick survives between runs exactly as a typed filter
        does, and one left behind widens the query without saying so."""
        if isinstance(names, str):
            names = [names]
        names = [n for n in names if n and n.strip()]
        if not names:
            return None

        found = self.trees()
        settable = [t for t in found if t["settable"]]
        if not settable:
            raise RuntimeError("this screen has no category tree to tick")

        wanted_low = {n.strip().lower() for n in names}
        if tree:
            low = tree.lower()
            pool = [t for t in settable
                    if low in t["dataset"].lower() or low in t["form"].lower()]
            if not pool:
                have = ", ".join(f"{t['form']}.{t['dataset']}" for t in settable[:6])
                raise RuntimeError(f"no category tree matching {tree!r}. Present: {have}")
        else:
            # Choose by DATA: the tree that actually contains what was asked
            # for. Picking the first tree, or the biggest, is a guess that
            # fails silently on a screen with four of them.
            pool = [t for t in settable
                    if wanted_low <= {n.strip().lower() for n in t["names"]}]
            if not pool:
                have = sorted({n for t in settable for n in t["names"]})[:20]
                raise RuntimeError(
                    f"{', '.join(names)} is not in any category tree on this "
                    f"screen. Present: {have}")
            if len(pool) > 1:
                # A name can live in more than one tree - "VD" is in the Org
                # tree and the Prod one. `prefer` is the tree a previous run
                # actually proved, so a remembered screen stops re-deciding
                # this. It is only a preference: if the tree that worked
                # before does not hold what is being asked for now, the
                # data-driven choice still applies.
                chosen = [t for t in pool if prefer
                          and prefer.lower() in (t["dataset"].lower(),
                                                 t["form"].lower())]
                if chosen:
                    pool = chosen
                else:
                    choices = ", ".join(f"{t['form']}.{t['dataset']}" for t in pool[:6])
                    raise RuntimeError(
                        f"{names[0]!r} appears in multiple category trees: {choices}. "
                        "Pass --tree to select the intended one.")

        target = pool[0]
        # Remembered so a successful run can record WHICH tree the division
        # came from - a screen with four trees can have the same name in more
        # than one, and next time we want the one that worked.
        self.last_tree = {"form": self.form_code(target) or target["form"],
                          "dataset": target["dataset"], "entry": names[0]}
        result = tick_org(self.ws, self.last_tree["form"],
                          target["dataset"], names, exclusive=exclusive)
        if not result.get("found"):
            raise RuntimeError(
                f"could not tick {', '.join(names)}: "
                f"{result.get('reason') or 'missing ' + str(result.get('missing'))}. "
                f"Present: {result.get('available', '(tree not loaded)')}")

        # Now ask the SCREEN what it thinks is selected. Writing the dataset
        # is not proof: a run announced "VD" while the screen still had MOBILE
        # ticked by hand, queried MOBILE, and delivered 288 rows of MOBILE
        # data in a file labelled VD. Nothing in the log looked wrong.
        deadline = time.time() + 10
        shown = {}
        while time.time() < deadline:
            shown = org_selection(self.ws)
            if not shown.get("found"):
                break                          # no such label on this screen
            got = (shown.get("org") or "").strip().lower()
            if any(got == n.strip().lower() for n in names):
                result["confirmed"] = shown.get("org")
                return result
            time.sleep(0.5)

        if shown.get("found"):
            raise RuntimeError(
                f"the division did not take: asked for {', '.join(names)}, but "
                f"the screen still shows {shown.get('text')!r}. Refusing to "
                f"query the wrong organisation.")
        raise RuntimeError(
            f"could not confirm that {', '.join(names)} is active on the screen")

    def set_filter(self, key, value):
        """Set one filter by label, column or control name.

        Bound controls are written through their dataset - Nexacro binds the
        two, so the visible field follows and there is no date picker or combo
        widget to fight. Unbound controls are typed into instead; a screen
        that sets its filters in code (Q2241UM00 binds none) used to be
        undriveable for that reason."""
        flt = match_filter(self.info, key)
        if flt is None:
            hint = ""
            if any(w in key.lower() for w in ("division", "org", "category",
                                              "attribute", "plant", "std")):
                hint = (" That looks like an organisation choice: use the "
                        "Division prompt / --division, or --option for the "
                        "Org / Prod / Fac / Proc and STD / PLANT controls.")
            raise RuntimeError(f"no filter matches {key!r} on this screen "
                               f"(run 'describe {self.code}' to see them)." + hint)
        if isinstance(flt, list):
            names = ", ".join(f["label"] or f["column"] or f["control"] for f in flt[:6])
            raise RuntimeError(f"{key!r} is ambiguous - matches: {names}")
        return flt, self.apply(flt, value)

    def apply(self, flt, value):
        """Write one discovered control, whichever mechanism it needs.

        The read-back is checked, but a difference is only fatal when the
        field came back EMPTY - that is the failure mode that matters, a write
        that did not land. A field that came back changed is usually Nexacro
        normalising its own value (a mask reformatting a date, a combo storing
        a code for a label), so that is reported rather than treated as a
        failure and used to abort a good run."""
        if flt.get("bound"):
            result = gmes_data.set_filter(self.ws, self.form_code(flt),
                                          flt["dataset"], {flt["column"]: value})
            if not result.get("found"):
                raise RuntimeError(f"could not write {flt['dataset']}.{flt['column']}")
            applied = result["applied"].get(flt["column"])
            wanted, got = str(value or "").strip(), str(applied or "").strip()
            if not values_match(wanted, got):
                raise RuntimeError(f"{flt['column']} did not take: asked for {value!r}, "
                                   f"but reads back as {applied!r}")
            return applied
        if not flt.get("id"):
            raise RuntimeError(f"{flt.get('control')} has no dataset behind it and "
                               "no reachable element - it cannot be set")
        return type_text(self.ws, flt["id"], value)

    def find_ref(self, ref):
        """Locate the control a saved profile refers to, on the screen as it
        is right now. Matched by dataset+column, or by control name for the
        unbound ones - never by anything positional. Returns None if it has
        gone, which is the caller's signal to stop trusting the profile."""
        if not ref:
            return None
        for f in self.filters + self.unbound:
            if ref.get("column") and f.get("column") == ref["column"] \
                    and f.get("dataset") == ref["dataset"]:
                return f
            if not ref.get("column") and f.get("control") == ref.get("control"):
                return f
        return None

    def set_date_range(self, from_value, to_value, profile=None):
        """Put the caller's own two dates into this screen's period fields.

        No date is ever calculated here. The two values arrive already
        decided; this only finds where they go and confirms they landed.

        A profile, when one has been proven, says which fields those are. On
        an unlearned screen they are worked out from the screen itself, and
        anything genuinely ambiguous stops the run rather than picking."""
        frm = self.find_ref(profile.get("from")) if profile else None
        to = self.find_ref(profile.get("to")) if profile else None

        if frm is None and to is None:
            frm, to, singles = date_targets(self.info)
            if frm is None and to is None:
                if not singles:
                    raise RuntimeError("this screen has no date field for the requested period")
                if from_value != to_value:
                    names = ", ".join(s["column"] or s["control"] for s in singles)
                    raise RuntimeError(
                        f"this screen has no from/to pair - only {names}. "
                        "Give --from and --to the same value, or name the field "
                        "with --set.")
                frm, to = singles[0], None

        written = []
        targets = ((frm, from_value, "--from"),)
        if to is not None:
            targets += ((to, to_value, "--to"),)
        for flt, value, which in targets:
            if value is None:
                continue
            if flt is None:
                # Refusing here rather than setting one end of the range and
                # querying a period nobody asked for.
                have = ", ".join(f["column"] for f in self.filters
                                 if is_date_field(f)) or "none"
                raise RuntimeError(f"this screen has no field for {which} "
                                   f"(date fields found: {have})")
            fitted = fit_date_to_field(value, flt.get("value"))
            self.apply(flt, fitted)
            written.append((flt, fitted))
        return written

    def set_date(self, yyyymmdd):
        """Apply a date to whatever period fields the screen has.

        Returns a list of (column, written) so the caller can print exactly
        what happened - including nothing, on a screen with no date at all."""
        frm, to, singles = date_targets(self.info)
        pair = [f for f in (frm, to) if f]
        if pair:
            targets = pair
        elif singles:
            # One date field is unambiguous. Several, with no from/to naming
            # among them, are not - setting them all would be a guess about
            # what each one means, so only the first is set and the rest are
            # named so the caller can set them explicitly.
            targets = singles[:1]
            if len(singles) > 1:
                others = ", ".join(f["column"] or f["control"] for f in singles[1:])
                self.warnings.append(
                    f"this screen has more than one date field; only "
                    f"{targets[0]['column'] or targets[0]['control']} was set. "
                    f"Others left alone: {others}")
        else:
            targets = []

        written = []
        for flt in targets:
            value = fit_date_to_field(yyyymmdd, flt.get("value"))
            self.apply(flt, value)
            written.append((flt["column"] or flt["control"], value))
        return written

    def clear_stale(self, keep=()):
        """Blank the free-text filters left behind by an earlier run.

        G-MES keeps a screen alive behind its tab, and a value typed into a
        filter STAYS there. A run asking only for a date returned zero rows
        because a Production Order from the previous run was still in the box:
        the date was right, the division was right, and the answer was empty
        with nothing to indicate why.

        Only `edt` text boxes are cleared, and only ones this run did not set.
        Combos and checkboxes hold meaningful defaults (`paramTecoYn` = "All",
        a status list = "1^2^3^4") and emptying those breaks the query a
        different way. Unbound boxes are only REPORTED: they are filled by the
        screen's own code, so a blank one may be a state the screen never
        expects to see."""
        cleared, noted, failed = [], [], []
        for f in self.filters:
            if not (f.get("control") or "").lower().startswith("edt"):
                continue
            if f["column"] in keep or not (f.get("value") or "").strip():
                continue
            try:
                self.apply(f, "")
                cleared.append(f"{f['label'] or f['column']}={f['value']}")
            except RuntimeError:
                # This used to be silently swallowed - exactly the failure
                # mode this method exists to prevent (a leftover filter from
                # an earlier run quietly narrowing or emptying the answer),
                # just moved one level down: instead of an OLD value never
                # being asked to leave, it is a value that refused to leave
                # when asked. Refusing to proceed matches how every other
                # "the screen still shows a value we did not want" case in
                # this project is already handled (verify_column's strict
                # mode, select_org() refusing an unconfirmed division) -
                # the query must not run with a leftover value still in a
                # filter box this run tried and failed to clear.
                failed.append(f"{f['label'] or f['column']}={f['value']}")
        if failed:
            raise RuntimeError(
                f"could not clear the leftover value(s) {failed} from an earlier "
                f"run - refusing to query with them possibly still in effect.")
        for u in self.unbound:
            if not (u.get("control") or "").lower().startswith("edt"):
                continue
            if (u.get("value") or "").strip():
                noted.append(f"{u['label'] or u['control']}={u['value']}")
        if noted:
            self.warnings.append("left as-is (the screen fills these in code): "
                                 + ", ".join(noted))
        return cleared

    # -- running ------------------------------------------------------------

    def inquiry(self, grid, **kwargs):
        """Click Inquiry and wait for THIS screen's result set to settle."""
        return poll_inquiry(self.ws, self.form_code(grid), grid["dataset"], **kwargs)

    def rows(self, grid, limit=-1):
        return read_rows(self.ws, self.form_code(grid), grid["dataset"], limit=limit)

    def verify_column(self, grid, column, expected, sample=8, strict=True):
        """Confirm the returned rows really carry the value that was asked for."""
        seen, problem = verify_rows(self.ws, self.form_code(grid), grid["dataset"],
                                    column, expected, sample=sample)
        if problem:
            if strict:
                raise RuntimeError(problem + ". Refusing to export the wrong data.")
            self.warnings.append(problem)
        return seen

    def verify_date_range(self, grid, column, date_from, date_to, strict=True):
        """Confirm every row's date column falls within [date_from, date_to]."""
        seen, problem = verify_date_range(self.ws, self.form_code(grid), grid["dataset"],
                                          column, date_from, date_to)
        if problem:
            if strict:
                raise RuntimeError(problem + ". Refusing to export the wrong data.")
            self.warnings.append(problem)
        return seen

    def date_like_columns(self, grid, sample=3):
        """Result columns that really are dates - what `--verify` can be given.

        The first version asked only whether every sampled value was six or
        eight digits. On the Production Plan result that reported `prodTime`
        (000025 - a time), `planWeekno` (202636 - a week) and `modelDesc`
        (65856560 - a model) as "dates that came back", under a heading
        promising dates.

        It is the same mistake as offering every dataset with a `commonName`
        column as an organisation tree: **shape is not identity**. The column
        has to be NAMED like a date as well as look like one."""
        result = self.rows(grid, limit=sample)
        if not result.get("found") or not result["rows"]:
            return []
        out = []
        for c in date_named_columns(result["columns"]):
            values = [digits_only(r.get(c)) for r in result["rows"]]
            values = [v for v in values if v]
            if values and all(len(v) in (6, 8) for v in values):
                out.append(c)
        return out

    def candidate_verify_columns(self, grid):
        """Column names worth suggesting for `--verify`, before Inquiry has
        run and there are no rows to confirm a real date shape against.

        Reads only the dataset's own column list (`getColID`), which exists
        independently of row count, so this works on the 0-row screen a
        RECORD run always starts from. Naming-only - a person still decides;
        `verify_column()` is what actually enforces the answer once rows
        exist."""
        try:
            result = self.rows(grid, limit=0)
        except Exception:
            return []
        if not result.get("found"):
            return []
        return date_named_columns(result.get("columns", []))

    # -- output -------------------------------------------------------------

    def export_excel(self, target_dir, timeout=240):
        return download_excel(self.ws, target_dir, timeout=timeout)

    def to_csv(self, grid, path):
        """Write the result dataset as CSV.

        Only completely empty rows are dropped. That is deliberately weaker
        than the Production Plan job, which drops rows with no `poNo` because
        it knows those are LINE SUM / PROC SUM subtotals. On an unknown screen
        there is no equivalent key, and guessing one would silently discard
        real data - filtering a single PO returned four dataset rows for one
        visible line, three of them continuation rows the grid merges.

        Returns (path, written, total).

        Columns that look like a credential (CLAUDE.md 2.3: `dsAnyframeDVO`
        carries `tokenId`/`refreshTokenId` for the signed-in session) are
        withheld, the same redaction `gmes_log.py` already applies to
        console/log output - applied here too, since a CSV file is exactly
        the kind of place CLAUDE.md 2.3 already says never to paste one."""
        import csv as _csv
        result = self.rows(grid, limit=-1)
        if not result.get("found") or not result["rows"]:
            return None, 0, 0
        cols, dropped = gmes_data.redact_sensitive_columns(result["columns"])
        if dropped:
            self.warnings.append(
                f"withheld from CSV, column name looks like a credential: {dropped}")
        real = [r for r in result["rows"]
                if any((r.get(c) or "").strip() for c in cols)]
        directory = os.path.dirname(os.path.abspath(path)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".gmes-csv-", suffix=".partial", dir=directory)
        try:
            with os.fdopen(fd, "w", newline="", encoding="utf-8-sig") as fh:
                writer = _csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(real)
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        return path, len(real), len(result["rows"])

    # -- lifecycle ----------------------------------------------------------

    def activate(self, max_wait=20):
        return gmes_open_screen.activate_screen(self.ws, self.win_id, max_wait=max_wait)

    def _is_open(self):
        open_now = {r.get("winId") for r in
                    gmes_open_screen.open_screens(self.ws).get("rows", [])}
        return self.win_id in open_now

    def close(self, timeout=20):
        """Close this screen's tab, and confirm it actually went.

        Screens accumulate: every one stays alive behind its tab holding its
        filters, its result set and its memory, and a long batch ends with a
        dozen of them. Returns (True, detail) or (False, reason) - it never
        clicks something it cannot identify as a close control.

        Tries the visible X first, since that is what a person would do and
        it needs no knowledge of Nexacro internals - but not every tab shape
        has one (a real "Production Plan by Order(Line)" tab's element had
        only a label child, confirmed live, HISTORY.md Phase 60.1). Falls
        back to calling the application's own close-tab handler directly,
        which needs only the win_id already in hand."""
        target = evaluate(self.ws, _js(JS_TAB_CLOSE_TARGET, cdp_common.JS_IS_VISIBLE,
                                       cdp_common.json.dumps(TAB_PREFIX + self.win_id)))
        if target.get("found"):
            click_element_by_rect(self.ws, target["target"]["x"], target["target"]["y"])
            deadline = time.time() + timeout
            while time.time() < deadline:
                if not self._is_open():
                    return True, f"closed {self.win_id}"
                time.sleep(0.5)
            # Clicking a control we found is not the same as it working -
            # gotcha #48 found exactly this for popups. Fall through to the
            # direct call rather than reporting failure while another way
            # to close it has not been tried yet.

        if close_work_frame(self.ws, self.win_id):
            deadline = time.time() + timeout
            while time.time() < deadline:
                if not self._is_open():
                    return True, f"closed {self.win_id} (direct)"
                time.sleep(0.5)

        if target.get("found"):
            return False, f"{self.win_id} was still open {timeout}s after clicking its X and calling fnRemoveForm"
        return False, f"{target.get('reason', 'no close control')}, and fnRemoveForm did not close it either"


# ===========================================================================
# Opening
# ===========================================================================

def open_screen(ws, code, ready_wait=90, settle_checks=2, poll_interval=1.0, log=print):
    """Open a screen by code or name, bring it to the FRONT, and wait until
    it has actually built itself.

    Both halves matter. A background screen still accepts dataset writes, so
    filters apply cleanly and the Inquiry click then lands on whichever screen
    is really in front - that produced a run which set the date and division
    correctly, queried a completely different report, and reported zero rows.

    And a tab existing is not the same as a screen being built: Nexacro
    constructs the whole UI in JavaScript long after the tab appears, so this
    polls for the screen's own forms rather than reading them once and
    declaring the screen unreadable.

    "Has a grid or a filter" is not the same as "is finished". Confirmed live
    on P1114WM00 (HISTORY.md Phase 62): its category tree and result grid are
    ready almost immediately, so the old one-shot check returned right away -
    but the screen's own "Detail" filter panel (a reusable Widget Filter
    component, the same late-binding pattern already known from the Quick
    View widget) attaches `Module Name`, `MES P/O`, `Mail` and `PO` several
    seconds LATER. A run recorded at the first "ready" moment never saw those
    fields at all - not an error, just a screen offer and a set of settable
    filters that were quietly short. So readiness now requires the discovered
    shape (filter/unbound/grid counts) to read the SAME on two consecutive
    polls, the same settle discipline `poll_inquiry` already uses for the
    result count, before this screen is handed to the caller.

    Closing every OTHER open screen first was tried (HISTORY.md Phase 62.5)
    to stop a Quick View sibling's leftover filter form leaking into this
    screen's own discovery (P1114WM01 left `workYmd`/`poNo`/`modelCode` in
    P1114WM00 after a switch), and reverted the same session: it traded that
    problem for a worse one. Confirmed live over a 90s trace - a fully cold
    P1114WM00, opened with NOTHING else already open, never populated its
    own Detail filter widget at all (`Module Name`, `MES P/O`, `Mail`, `PO`
    stayed missing the entire time). P1114WM00 is a "Detail Schedule"
    child of P1114UM00 in the menu breadcrumb, and every prior successful
    discovery of it happened with P1114UM00 already open alongside it - the
    widget filter panel appears to depend on that parent screen's own
    state to populate, so force-closing "everything but the target" closed
    something this screen actually needed. The narrower Quick View
    contamination is not reachable through the normal front end any more
    (`run_gmes_workflow.py`'s Quick View question was reverted to
    informational-only in the same session), so there is nothing left in
    this codebase that opens a Quick View sibling programmatically - the
    blanket close bought no live safety it does not already have."""
    code = code.strip()

    # A screen already open is reached by clicking its tab. Driving the search
    # box again would work, but it types a code one character at a time and
    # waits on a suggestion list to reach a screen that is already there - and
    # a batch re-runs the same screen constantly.
    # Only a full screen code or menu id takes this path. A partial one
    # ("P111") would match several open screens and silently pick whichever
    # came first; a name goes through the catalogue, which validates it.
    opened = None
    if re.fullmatch(r"[A-Za-z]{1,4}\d{4,}[A-Za-z0-9]*", code):
        rows = gmes_open_screen.open_screens(ws).get("rows", [])
        for row in rows:
            haystack = f"{row.get('pageUrl', '')} {row.get('menuId', '')}".upper()
            if code.upper() in haystack:
                opened = row
                break
        if opened is None:
            opened = gmes_open_screen.tab_for_embedded_form(ws, code, rows)
    if opened is None:
        opened = gmes_open_screen.open_screen(ws, code, log=log)

    if not gmes_open_screen.activate_screen(ws, opened.get("winId", "")):
        raise RuntimeError(f"{code} is open as {opened.get('winId')} but its tab "
                           "could not be brought to the front")

    deadline = time.time() + ready_wait
    info, last = None, "the screen never reported any forms"
    shape, stable = None, 0
    while time.time() < deadline:
        info = discover(ws, code)
        if info.get("found") and (info.get("grids") or info.get("filters")):
            current = (len(info.get("filters", [])), len(info.get("unbound", [])),
                       len(info.get("grids", [])))
            if current == shape:
                stable += 1
                if stable >= settle_checks:
                    return Screen(ws, code, opened, info)
            else:
                shape, stable = current, 1
        else:
            shape, stable = None, 0
        last = info.get("reason", last)
        time.sleep(poll_interval)
    raise RuntimeError(f"{code} opened but never finished building ({last})")


def sign_in(attempts=2):
    """Sign in, retrying only what is worth retrying.

    Session expiry is real: after a long idle, clicking AD SSO produced no SSO
    window and the run failed; a second attempt signed in normally. So one
    expired session should not take a whole batch with it.

    But a retry is only ever right for a transient failure. When G-MES has
    said "Auth bad credentials", the second attempt sends the same password
    to the same server and gets the same answer - it just doubles the time
    the user waits for news they could have had immediately. Worse, repeated
    attempts with a bad password are how an account gets locked."""
    for attempt in range(1, attempts + 1):
        result = gmes_login.main()
        if result == gmes_login.OK:
            return True
        if result == gmes_login.REJECTED:
            return False        # the credentials are wrong; trying again cannot help
        if attempt < attempts:
            print(f"\nSign-in attempt {attempt} did not complete; retrying once "
                  "after rechecking the login state...")
    return False


def connect(timeout=20, port=None):
    return connect_gmes(timeout=timeout, port=port)


# ===========================================================================
# Export
# ===========================================================================

def is_drm_protected(path):
    """G-MES exports come back wrapped by Samsung's NASCA DRM.

    The file opens normally in Excel on a machine running the DRM client, but
    it is NOT a readable workbook: the bytes are encrypted, so openpyxl,
    pandas and every other library see a corrupt file. Worth knowing before
    anything downstream tries to parse it - which is why a CSV is written from
    the data layer alongside."""
    try:
        with open(path, "rb") as fh:
            return b"NASCA DRM" in fh.read(64)
    except OSError:
        return False


def download_excel(ws, target_dir, timeout=240):
    """Click the toolbar Excel icon, confirm its dialog, wait for the file.

    Two things that are not obvious. The icon opens a "Save to Excel" dialog
    (PopupExcelExport) with the grid already ticked - it does not download on
    its own. And Chrome's download redirect dies with the connection that set
    it, so `Browser.setDownloadBehavior` is issued on the SAME open connection
    that does the clicking; setting it from a connection that is then closed
    leaves the file in the user's Downloads folder, which is exactly what
    happened the first time. That folder is watched too, as a fallback.

    The popup closer must NOT be running around this: the export dialog is a
    child popup like any other, and closing it would cancel the export."""
    os.makedirs(target_dir, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".gmes-download-", dir=target_dir)

    try:
        send(ws, "Browser.setDownloadBehavior",
             {"behavior": "allow", "downloadPath": staging, "eventsEnabled": True})
    except Exception:
        send(ws, "Page.setDownloadBehavior",
             {"behavior": "allow", "downloadPath": staging})

    def snapshot(folder):
        try:
            return {f for f in os.listdir(folder)
                    if f.lower().endswith((".xlsx", ".crdownload"))}
        except OSError:
            return set()

    try:
        icon = evaluate(ws, gmes_common.js_find_by_id(EXCEL_BTN))
        if not icon.get("found"):
            raise RuntimeError(f"the Excel Download icon was not visible ({icon.get('reason')})")
        click_element_by_rect(ws, icon["x"], icon["y"])
        if not gmes_common.click_control(ws, text="OK", attempts=30, delay=0.5):
            raise RuntimeError("the 'Save to Excel' dialog did not offer an OK button")

        deadline = time.time() + timeout
        last_size, stable = -1, 0
        while time.time() < deadline:
            names = snapshot(staging)
            finished = [name for name in names if name.lower().endswith(".xlsx")]
            downloading = [name for name in names if name.lower().endswith(".crdownload")]
            if len(finished) > 1:
                raise RuntimeError("more than one workbook arrived for one export request")
            if finished and not downloading:
                candidate = os.path.join(staging, finished[0])
                size = os.path.getsize(candidate)
                stable = stable + 1 if size == last_size else 0
                last_size = size
                if stable >= 2:
                    final = os.path.join(
                        target_dir, f".gmes-download-{uuid.uuid4().hex}_{finished[0]}")
                    os.replace(candidate, final)
                    return final
            time.sleep(0.5)
        raise RuntimeError(f"no complete .xlsx file appeared within {timeout}s")
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def check_download(path, minimum=512):
    """Confirm a delivered file is actually there and is not an empty shell.

    "The download succeeded" has meant three different things here: the click
    worked, a file appeared, and the file has content. Only the third is worth
    reporting, and it is the one that was never checked - a zero-byte or
    stub file arrives looking exactly like a real export.

    This is as far as verification can go for the .xlsx: it is NASCA-DRM
    encrypted, so no library can read it and nothing can confirm what is
    inside. The CSV written from the data layer is the only real evidence of
    content, which is why both are produced."""
    if not os.path.isfile(path):
        raise RuntimeError(f"the export reported success but {path} is not there")
    size = os.path.getsize(path)
    if size < minimum:
        raise RuntimeError(f"{os.path.basename(path)} is only {size} bytes - "
                            "that is not a real export")
    with open(path, "rb") as fh:
        prefix = fh.read(64)
    if not (prefix.startswith(b"PK\x03\x04") or b"NASCA DRM" in prefix):
        raise RuntimeError(f"{os.path.basename(path)} is not an XLSX or a NASCA DRM workbook")
    return size


_WINDOWS_RESERVED_NAME = re.compile(
    r"(?i)^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$"
)


def safe_name(text):
    """A file name that survives Windows. Report titles carry '/' and ':'.

    Every export uses this only as a PREFIX to a timestamp+uuid suffix
    (`f"{name}_{stamp}.xlsx"`), so an exact reserved-name collision
    (Windows blocks CON, PRN, AUX, NUL, COM1-9, LPT1-9 exactly, regardless
    of extension - not names merely starting with one) is not reachable
    through that one call site today. Guarded anyway: this function has no
    control over every future caller, and a report legitimately titled
    "AUX" or "NUL" is not implausible in a system with 810 screens."""
    name = re.sub(r'[<>:"/\\|?*]', "-", (text or "").strip())
    name = name.rstrip(". ") or "report"   # Windows also drops a trailing dot/space
    if _WINDOWS_RESERVED_NAME.match(name):
        name = f"_{name}"
    return name


# ===========================================================================
# The whole pipeline for one screen
# ===========================================================================

def run_screen(ws, screen_code, division=None, date_from=None, date_to=None,
               sets=None, options=(), export="both", out_dir=OUTPUT_DIR,
               grid_name=None, tree=None, verify=None, dry_run=False,
               close_after=False, use_profile=True, trust_profile=True,
               log=print):
    """Open a screen, set everything asked for, run it, verify it, export it.

    The nine steps of the basic workflow, in the order the screen imposes:
    open, read, apply, verify each, Inquiry, wait, export, verify the file,
    and - only if all of that worked - remember what was proven.

    Dates are never calculated here. `date_from` and `date_to` arrive already
    decided by the caller.

    Options come first because switching a category tab or a Quick View
    rebuilds the left panel and discards whatever was set before it.

    `use_profile` and `trust_profile` are deliberately separate knobs
    (HISTORY.md Phase 66). `use_profile` alone used to gate BOTH reading the
    saved profile at step 2 and writing a new one at step 11 - so a caller
    re-teaching a screen had no way to skip trusting the OLD profile
    without also skipping saving the new one. The interactive front end
    worked around that by deleting `screens/<CODE>.json` on disk the moment
    RECORD was chosen for an already-learned screen - before the screen was
    even opened, before anything was confirmed. Cancelling, or any later
    step failing, then meant the old (working) profile was already gone
    with nothing to replace it. `trust_profile=False` (with `use_profile`
    left True) instead skips only the LOAD - step 11's save still runs
    normally on success and atomically replaces the old file via
    `gmes_profile.save()`'s own temp-file-plus-rename write, so an old
    profile is only ever lost by being properly superseded, never by being
    pre-emptively deleted on a guess that a replacement is coming."""
    sets = dict(sets or {})
    if export not in ("xlsx", "csv", "both", "none"):
        raise ValueError(f"unknown export format: {export}")
    started = time.time()
    code = screen_code.strip().upper()
    out = {"screen": code, "ok": False, "rows": 0, "files": [], "error": None,
           "warnings": [], "applied": {}, "options": [], "cleared": [],
           "dry_run": bool(dry_run)}

    log(f"\n{'=' * 70}\n{code}\n{'=' * 70}")

    # 1. Open, bring to the front, wait until it has built itself.
    screen = open_screen(ws, code, log=log)
    opening_info = screen.info
    out["title"] = screen.title
    out["menuId"] = screen.menu_id
    out["window"] = screen.win_id
    log(f"  screen   : {screen.title}  [{screen.menu_id}]")

    # 2. Read the screen as it is now, then decide whether anything remembered
    #    about it can still be trusted. A profile is never repaired silently:
    #    if the screen moved, it is dropped and the screen is read fresh.
    profile = gmes_profile.load(code) if (use_profile and trust_profile) else None
    if profile:
        opening_fingerprint = profile.get("opening_fingerprint")
        if opening_fingerprint and opening_fingerprint != gmes_profile.fingerprint(opening_info):
            log("  changed  : the screen opening shape changed since this was learned")
            raise RuntimeError(
                "the remembered screen shape changed; refusing to replay saved settings")
        if not opening_fingerprint:
            # Old profiles cannot prove an option-bearing opening shape. The
            # old no-option form remains compatible; option profiles require
            # an explicit relearn rather than a false comparison.
            if profile.get("options"):
                raise RuntimeError("the remembered profile predates opening-shape checks; refusing to replay saved settings")
            problems = gmes_profile.describe_change(profile, opening_info)
            if problems:
                for p in problems:
                    log(f"  changed  : {p}")
                raise RuntimeError("the remembered screen shape changed; refusing to replay saved settings")
        log(f"  learned  : {gmes_profile.summary(profile)}")
    out["used_profile"] = bool(profile)

    # `or {}` after the get, not a default INSIDE it: dict.get(k, {}) returns
    # None when the key exists holding None, which every profile saved without
    # a division does. That crashed a replay with
    # "'NoneType' object has no attribute 'get'".
    grid = screen.grid(grid_name or ((profile or {}).get("grid") or {}).get("dataset"))
    out["grid"] = f"{grid['name']} -> {grid['dataset']}"
    log(f"  filters  : {len(screen.filters)} bound, {len(screen.unbound)} unbound")
    log(f"  results  : {grid['dataset']} (grid {grid['name']})")

    # 3. Left-panel options first: switching a category tab or a Quick View
    #    rebuilds the panel and discards what was set before it.
    #
    #    A remembered screen re-applies the options chosen when it was taught,
    #    unless this run names its own. They are decisions nothing on the
    #    screen records - "Plan Date" and "Create Date" both look correct and
    #    return different answers - so forgetting them between runs would make
    #    a learned screen quietly stop meaning what it meant.
    if not options and profile:
        options = profile.get("options") or []
        if options:
            log("  learned  : options from last time: "
                + ", ".join(option_display(o) for o in options))
    # What gets REMEMBERED is what was resolved, never what was asked for. A
    # profile holding the English label "Create Date" therefore heals itself
    # into the stable `btnCreate` identity on its next successful run, with no
    # re-record and nothing for the user to do (HISTORY.md Phase 76).
    resolved_options = []
    for wanted in options:
        result = screen.set_option(wanted)
        out["options"].append(result["outcome"])
        resolved_options.append(
            {k: result[k] for k in ("key", "name", "path", "label")})
        if result["matched_by"] not in ("component name", "component path",
                                        "semantic key"):
            # Worth saying out loud: this run matched on something that can
            # change under it, and would have failed had the UI language
            # changed first. It is about to be replaced by one that cannot.
            log(f"  migrated : {option_display(wanted)} matched by "
                f"{result['matched_by']}; remembering [{result['key']}] instead")
        log(f"  option   : {result['outcome']}")
    if options:
        grid = screen.grid(grid_name)      # the panel was rebuilt; re-resolve
    if profile:
        # Saved refs were intentionally captured after options rebuilt the
        # panel. Validate them only now, on that same shape.
        problems = gmes_profile.describe_change(profile, screen.info)
        if problems:
            for p in problems:
                log(f"  changed  : {p}")
            raise RuntimeError("the remembered screen shape changed; refusing to replay saved settings")

    # 4. Organisation.
    if division:
        picked = screen.select_org(
            division, tree=tree,
            prefer=((profile or {}).get("division") or {}).get("dataset"))
        # De-duplicated: the same tree exists several times on some
        # screens, so a single division comes back once per copy.
        names = ", ".join(sorted({t["name"] for t in picked["ticked"]}))
        dropped = sorted(set(picked.get("cleared") or []))
        out["division"] = names
        confirmed = picked.get("confirmed")
        detail = names + (f"  (screen confirms {confirmed})" if confirmed else "")
        if dropped:
            detail += f"  (unticked {len(dropped)}: " \
                      + ", ".join(dropped[:4]) \
                      + ("..." if len(dropped) > 4 else "") + ")"
        log(f"  division : {detail}")

    # 5. The dates the caller gave. Nothing is worked out from today's date.
    date_fields = []
    if date_from or date_to:
        date_fields = screen.set_date_range(date_from, date_to, profile)
        out["dates"] = [(f["column"] or f["control"], v) for f, v in date_fields]
        if not date_fields:
            raise RuntimeError("the requested period was not applied to any field")
        log("  dates    : " + ", ".join(f"{c}={v}" for c, v in out["dates"]))

    # 6. Sweep values inherited from an earlier run, before applying this
    #    run's own, so nothing is carried over in silence.
    keep = {f["column"] for f, _ in date_fields}
    for key in sets:
        m = match_filter(screen.info, key)
        if m is not None and not isinstance(m, list):
            keep.add(m.get("column"))
    out["cleared"] = screen.clear_stale(keep)
    if out["cleared"]:
        log(f"  cleared  : leftover {', '.join(out['cleared'])}")

    # 7. Anything else the caller named.
    for key, value in sets.items():
        flt, applied = screen.set_filter(key, value)
        out["applied"][flt["label"] or flt["column"] or flt["control"]] = applied
        how = "typed" if not flt.get("bound") else "set"
        log(f"  filter   : {flt['label'] or flt['column']} {how} to {applied!r}")

    if dry_run:
        out["ok"] = True
        out["warnings"] = screen.warnings
        out["seconds"] = round(time.time() - started, 1)
        log("  dry run  : everything above was applied; Inquiry NOT clicked")
        for w in screen.warnings:
            log(f"  warning  : {w}")
        return out

    # What organisation is REALLY in effect as the query runs - read off the
    # screen's own label, not from what was typed.
    #
    # This is what the memory should have been recording all along. A run that
    # named no division still queries whichever one is ticked, and storing ""
    # for it left the screen looking un-taught: P1111UM00 was recorded with
    # VD, then run once with everything blank, and its memory came back empty
    # so the next replay asked cold. Recording what was USED also fixes the
    # spelling for free - a division typed "vd" is stored as the tree's own
    # "VD".
    effective_division = division or ""
    seen_org = org_selection(ws)
    if seen_org.get("found") and seen_org.get("org"):
        effective_division = seen_org["org"]
        if not division:
            log(f"  division : none asked for; the screen has "
                f"{effective_division} in effect")

    # 8. Inquiry, watching the dataset this screen actually uses.
    rows = screen.inquiry(grid)
    out["rows"] = rows
    log(f"  inquiry  : {rows} rows in {time.time() - started:.1f}s")
    if rows == 0:
        raise RuntimeError("the query returned no rows - nothing exported")

    # 9. Verification. Explicit COLUMN=VALUE is strict; otherwise the date
    #    columns are reported so the caller can see what came back without a
    #    guess being made about which column the filter applied to.
    if verify:
        column, _, expected = verify.partition("=")
        column = column.strip()
        if expected:
            seen = screen.verify_column(grid, column, expected, strict=True)
        elif date_to and date_to != date_from:
            # A genuine multi-day range with no explicit =VALUE - checking
            # every row against the single value date_from (the only prior
            # behaviour) rejected every legitimately correct multi-day
            # answer, since real rows span the whole requested window, not
            # one day. Confirmed live: 6529 correct rows over a real 10-day
            # range, all reported as "not exactly the requested" against
            # date_from alone.
            seen = screen.verify_date_range(grid, column, date_from, date_to, strict=True)
        else:
            seen = screen.verify_column(grid, column, date_from, strict=True)
        out["verified"] = {column: seen}
        log(f"  verified : {column} = {seen}")
    elif date_from:
        raise RuntimeError("a date-constrained run requires --verify COLUMN[=VALUE]")

    # 10. Export, and check the file is really there and really has content.
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid.uuid4().hex[:8]
    name = safe_name(screen.title or code)
    if export in ("xlsx", "csv", "both"):
        os.makedirs(out_dir, exist_ok=True)
    downloaded = None
    try:
        if export in ("xlsx", "both"):
            if not screen.activate():
                raise RuntimeError("could not prove the report screen was active for Excel export")
            downloaded = screen.export_excel(out_dir)
            # Validate BEFORE renaming to the final, believable name - not
            # after. A corrupt or truncated download used to be renamed to
            # its real "<title>_<stamp>.xlsx" name first and only checked
            # afterward; a failed check then raised past the point where
            # out["files"] recorded it, so the exception handler's cleanup
            # loop never found it to delete - a corrupt file was left
            # behind under the exact name a real export would have used.
            #
            # Checking it before that rename does NOT, on its own, clean it
            # up on failure: download_excel() already moves the file OUT of
            # its disposable staging directory - into `out_dir`, under a
            # hidden `.gmes-download-<uuid>_...` name - before returning, so
            # by the time `downloaded` reaches here it is no longer inside
            # the staging dir that `download_excel()`'s own
            # `finally: shutil.rmtree(staging, ...)` removes. A prior fix
            # claimed that cleanup happened automatically; it does not - the
            # `downloaded` variable is kept live across this whole block
            # specifically so the except clause below can unlink it.
            size = check_download(downloaded)
            final = os.path.join(out_dir, f"{name}_{stamp}.xlsx")
            if os.path.abspath(downloaded) != os.path.abspath(final):
                os.replace(downloaded, final)
            downloaded = None      # renamed away; nothing left to clean up under this name
            out["files"].append(final)
            out["excel_bytes"] = size
            log(f"  excel    : {os.path.basename(final)}  {size / 1024:,.1f} KB"
                + ("  [DRM - opens in Excel, unreadable by other programs]"
                   if is_drm_protected(final) else ""))
        if export in ("csv", "both"):
            path, written, total = screen.to_csv(
                grid, os.path.join(out_dir, f"{name}_{stamp}_data.csv"))
            if not path or not os.path.isfile(path) or written <= 0:
                raise RuntimeError("CSV export did not produce a checked file")
            out["files"].append(path)
            out["csv_rows"] = written
            note = "" if written == total else f"  ({total - written} empty rows dropped)"
            log(f"  csv      : {os.path.basename(path)}  {written} rows{note}")
    except Exception:
        for path in out["files"]:
            try:
                os.unlink(path)
            except OSError:
                pass
        if downloaded:
            try:
                os.unlink(downloaded)
            except OSError:
                pass
        raise

    if close_after:
        ok, detail = screen.close()
        log(f"  tab      : {detail}")
        out["closed"] = ok

    # 11. Only now - after the query, the verification and the file - is any
    #     of this worth remembering. A profile written from a run that failed
    #     would be a guess dressed up as knowledge.
    #
    #     This is outside the export try/except above on purpose - the files
    #     already delivered must not be lost because of it - but it is its
    #     OWN try/except for the same reason: unhandled, an exception here
    #     used to propagate straight out of run_screen(), past the `return
    #     out` that carries the real, already-verified file paths.
    #     run_many()'s caller then only ever sees the exception and builds a
    #     brand new result with files=[] - a genuinely delivered export
    #     reported as "DID NOT FINISH ... nothing was saved" with the real
    #     files sitting on disk, unmentioned. Remembering the screen for
    #     next time is a convenience; failing to remember it must not cost
    #     the report that already succeeded.
    if use_profile:
        try:
            saved = gmes_profile.save(
                code, screen.title, screen.menu_id, screen.info,
                from_ref=gmes_profile.field_ref(date_fields[0][0]) if date_fields else None,
                to_ref=gmes_profile.field_ref(date_fields[1][0]) if len(date_fields) > 1 else None,
                division=(gmes_profile.tree_ref(**screen.last_tree)
                          if screen.last_tree else None),
                grid=grid, rows=rows, options=resolved_options,
                values={"division": effective_division, "from": date_from or "",
                        "to": date_to or "", "verify": verify or "", "sets": dict(sets)},
                command=f"--division {division} --from {date_from} --to {date_to}",
                opening_info=opening_info)
            out["profile"] = saved
            log(f"  learned  : saved to {os.path.basename(saved)}")
        except Exception as e:
            msg = f"the export succeeded but this screen could not be remembered for next time: {e}"
            screen.warnings.append(msg)
            log(f"  warning  : {msg}")

    out["ok"] = True
    out["warnings"] = screen.warnings
    for w in screen.warnings:
        log(f"  warning  : {w}")
    out["seconds"] = round(time.time() - started, 1)
    return out


def run_many(ws, specs, log=print):
    """Run several screens SEQUENTIALLY, isolating each one.

    Sequential is a decision, not a limitation left for later:

      * Only one tab is in front, and a background screen still accepts filter
        writes - running two at once reintroduces that bug by design.
      * The Excel button and its "Save to Excel" dialog are global to the
        application; two exports would collide over both.
      * A modal popup blocks the whole application, not one screen.
      * Real parallelism needs a separate Chrome, a ~340 MB profile copy and
        an SSO sign-in each - more authentication load and more ways to fail
        unattended at 02:00.
      * The measured gain is small: 11.8s and 28.3s of server time for two
        reports. G-MES answering is the bottleneck, not this tool.

    A failure stops the batch because the foreground screen can no longer be
    proved safe for the next report."""
    specs = tuple(specs)
    results = []
    for index, spec in enumerate(specs):
        try:
            results.append(run_screen(ws, log=log, **spec))
        except Exception as e:
            code = spec.get("screen_code", "?")
            log(f"  FAILED   : {e}")
            try:
                gmes_common.screenshot_on_failure(f"gmes_{code}")
            except Exception as diagnostic_error:
                log(f"  diagnostic unavailable: {diagnostic_error}")
            results.append({"screen": code, "ok": False, "rows": 0, "files": [],
                            "error": str(e), "warnings": []})
            for skipped in specs[index + 1:]:
                results.append({"screen": skipped.get("screen_code", "?"), "ok": False,
                                "rows": 0, "files": [],
                                "error": "not run because the previous screen left an unknown state",
                                "warnings": []})
            break
    return results


def print_summary(results, log=print):
    log(f"\n{'=' * 70}\nSUMMARY\n{'=' * 70}")
    log(f"  {'SCREEN':<14} {'STATUS':<9} {'ROWS':>7}  FILES / ERROR")
    log("  " + "-" * 84)
    for r in results:
        if r["ok"]:
            files = ", ".join(os.path.basename(f) for f in r["files"]) or "-"
            log(f"  {r['screen']:<14} {'ok':<9} {r['rows']:>7}  {files}")
        else:
            log(f"  {r['screen']:<14} {'FAILED':<9} {'-':>7}  {r['error']}")
    ok = sum(1 for r in results if r["ok"])
    log(f"\n  {ok}/{len(results)} succeeded")
    return ok


def date_from_args(date=None, days_back=None):
    """One place for --date / --days-back, so every command agrees."""
    if days_back is not None:
        return (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")
    return normalise_date(date)
