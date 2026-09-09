"""
Run ANY G-MES report by its UI number, without teaching the tool the screen
first. It discovers the screen's own filters, applies the ones you name,
runs the Inquiry and downloads the result.

    # See what a screen offers - filters, result grid, export
    python gmes_report.py describe P1112UM00

    # Run it
    python gmes_report.py run P1112UM00 --division VD --date 20260908

    # Several screens in one go
    python gmes_report.py run P1112UM00 P1111UM00 --division VD --date 20260908

    # Set any discovered filter by label, column or control name
    python gmes_report.py run P1112UM00 --division VD \
        --set "Production Order=011074232146" --set paramTecoYn=All

How the discovery works
-----------------------
Nexacro keeps a binding table on every form (`form.binds`) that maps each
control to the dataset column behind it:

    divBasic.form.divCal.form.mskDateFrom -> dsFilterDVO.paramFromDate
    divDetail.form.edtProductionOrder     -> dsFilterDVO.paramPo

So the filters do not have to be learned per screen - they are read off the
screen itself, together with the label rendered next to each control. The
result grid is found the same way, through its `binddataset`.

SEQUENCING - why screens run one at a time
------------------------------------------
Several UI numbers in one command are executed **sequentially, in one
browser**. That is a deliberate choice, not a limitation left for later:

1. Only one tab can be in front, and a BACKGROUND screen still accepts
   filter writes. That is how a run once set the date and division on the
   right screen and then ran Inquiry on a different one, reporting 0 rows.
   Running two screens at once in one browser reintroduces that bug by
   design.
2. The export is global. There is one toolbar Excel button
   (`mdiFrame.form.btnExcel`) and one modal "Save to Excel" dialog for the
   whole application. Two exports at once would collide over both.
3. Modal popups are application-wide. A Notice appearing during one report
   blocks every other one.
4. Real parallelism would need separate Chrome instances, a separate ~340 MB
   profile copy each, and a separate SSO sign-in each - more load on
   corporate authentication, and more ways to fail unattended at 02:00.
5. The gain would be small. Measured: 11.8s and 28.3s of server time for two
   reports. The bottleneck is G-MES answering, not this tool. Ten reports
   run in a few minutes, which is nothing for an overnight job.

Each screen is isolated: one failing does not stop the rest, and the summary
at the end says which succeeded. If throughput ever genuinely matters, the
safe axis is more machines or accounts - never more tabs in one session.
"""
import argparse
import os
import sys
import time
from datetime import datetime, timedelta

import cdp_common
from cdp_common import evaluate
import gmes_common
import gmes_data
import gmes_daily_prodplan as job
import gmes_login
import gmes_open_screen
from gmes_common import connect_gmes, connect_gmes as _c

OUTPUT_DIR = job.OUTPUT_DIR


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

JS_DISCOVER = r"""
(function() {
    %s
    const isVisible = %s;
    const screenCode = %s;

    // Everything inside the work window for this screen. The window name
    // changes on every open, so it is found by screen code, never by id.
    const forms = _findForms(screenCode);
    if (!forms.length) return JSON.stringify({found: false});

    // The work window is the ancestor whose name starts with "win".
    // Keep the full path INCLUDING the "application." prefix: _findForms
    // returns paths with it, so a stripped prefix here silently matches
    // nothing and the screen looks as though it has no filters at all.
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

    // The label for a control: the nearest visible Static to its left on the
    // same line, else the nearest one directly above it.
    const statics = [];
    for (const el of document.querySelectorAll('div')) {
        const cls = (typeof el.className === 'string') ? el.className : '';
        if (!/\bStatic\b/.test(cls)) continue;
        if (!isVisible(el)) continue;
        const t = (el.textContent || '').trim();
        if (!t || t.length > 40) continue;
        // Calendar day cells are Statics too, and they sit right beside the
        // date boxes - which made the date filters come back labelled "6"
        // and "8". Anything purely numeric or a bare weekday is not a label.
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

    // Nexacro names controls by type, and that prefix is the only reliable
    // way to tell an input from a read-only display. Bound Statics
    // (staPlanQty, staProgRate) are computed OUTPUTS - offering them as
    // filters would be actively misleading.
    function kindOf(name) {
        const n = (name || '').toLowerCase();
        if (/^(edt|msk|cbo|chk|rdo|cal|spn|txt|lst)/.test(n)) return 'input';
        if (/^(sta|img|btn|grd|div)/.test(n)) return 'display';
        return 'unknown';
    }
    // Shell forms carry binds of their own (the My Menu panel's Personal /
    // Local / search box). They belong to the frame, not to the report.
    const SHELL = /WorkMainTitle|MyMenu|LeftMain|WorkMain\.xfdl|WorkTemplate/i;

    const filters = [], unbound = [], grids = [], datasets = {};

    for (const h of _findForms(null)) {
        if (h.path.indexOf(winPath) !== 0) continue;   // only this work window

        // Datasets on this form, for row counts later.
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

        // Bound controls -> filters.
        try {
            const b = SHELL.test(h.file || '') ? null : h.form.binds;
            if (b && b.length !== undefined) {
                for (let i = 0; i < b.length; i++) {
                    const x = b[i];
                    const ds = String(x.datasetid || ''), col = String(x.columnid || '');
                    if (!ds || !col) continue;
                    const comp = String(x.compid || '');
                    const leaf = comp.split('.').pop();
                    if (kindOf(leaf) !== 'input') continue;   // display, not a filter
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
                    filters.push({dataset: ds, column: col, control: comp.split('.').pop(),
                                  label: label, value: value, visible: visible,
                                  kind: kind, form: h.file || ''});
                }
            }
        } catch (e) {}

        // Visible inputs with NO binding. Not every screen binds its filters
        // - Q2241UM00 sets them in code - so those screens would otherwise
        // report "no filters" and look broken. They cannot be set through a
        // dataset, but the user still needs to know they exist.
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
                    unbound.push({control: c.name, form: h.file || '',
                                  label: labelFor(el.getBoundingClientRect())});
                }
            }
        } catch (e) {}

        // Grids -> candidate result sets.
        try {
            const comps = h.form.components;
            if (comps && comps.length !== undefined) {
                for (let i = 0; i < comps.length; i++) {
                    const c = comps[i];
                    if (!c) continue;
                    const t = _typeName(c);
                    if (!/Grid/i.test(t)) continue;
                    const bd = String(c.binddataset || '');
                    if (!bd) continue;
                    const id = domId(h.path, c.name);
                    const el = id ? document.getElementById(id) : null;
                    const r = el ? el.getBoundingClientRect() : null;
                    grids.push({name: c.name, dataset: bd, form: h.file || '',
                                area: r ? Math.round(r.width * r.height) : 0,
                                visible: !!(el && isVisible(el))});
                }
            }
        } catch (e) {}
    }

    // One dataset column can be bound to several controls (a value shown in
    // two places), and the shell's own forms contribute binds of their own.
    // Keep one entry per dataset.column, preferring the visible control.
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
    // its own name (mskDateFrom), and the two are usually recorded on
    // different forms. Comparing them directly listed bound controls as
    // unbound. Match on the leaf name across the whole window instead.
    const boundLeaves = {};
    for (const f of filters) boundLeaves[f.control] = true;
    const seenUnbound = {};
    const trulyUnbound = [];
    for (const u of unbound) {
        if (boundLeaves[u.control] || seenUnbound[u.control]) continue;
        seenUnbound[u.control] = true;
        trulyUnbound.push(u);
    }
    unbound.length = 0;
    Array.prototype.push.apply(unbound, trulyUnbound);

    grids.sort((a, b) => b.area - a.area);

    // The shared shell controls, which are the same on every screen.
    const inquiry = Array.from(document.querySelectorAll('div')).find(el => {
        const cls = (typeof el.className === 'string') ? el.className : '';
        return /btn_LF_Search_New/.test(cls) && isVisible(el);
    });
    const orgTree = _findForms('OrgCategory_GDS').length > 0;

    return JSON.stringify({found: true, window: winPath.split('.').pop(),
                           filters: filters, unbound: unbound.slice(0, 25),
                           grids: grids.slice(0, 6),
                           datasets: datasets, hasInquiry: !!inquiry,
                           hasOrgTree: orgTree});
})()
""" % (gmes_data.JS_HELPERS, cdp_common.JS_IS_VISIBLE, "%s")


def discover(ws, screen_code):
    return evaluate(ws, JS_DISCOVER % cdp_common.json.dumps(screen_code))


def result_dataset(info):
    """The grid most likely to hold the report's rows: the biggest visible
    one. Falls back to the biggest of any."""
    visible = [g for g in info["grids"] if g["visible"]]
    pool = visible or info["grids"]
    return pool[0] if pool else None


def match_filter(info, key):
    """Resolve a user's filter name to a discovered control.

    Accepts the column name, the control name, or the visible label - in
    that order of confidence - so a screen can be driven either the way it
    reads on screen or the way it is stored."""
    k = key.strip().lower()
    exact_col = [f for f in info["filters"] if f["column"].lower() == k]
    if exact_col:
        return exact_col[0]
    exact_label = [f for f in info["filters"] if f["label"].lower() == k]
    if exact_label:
        return exact_label[0]
    exact_ctrl = [f for f in info["filters"] if f["control"].lower() == k]
    if exact_ctrl:
        return exact_ctrl[0]
    partial = [f for f in info["filters"]
               if k in f["label"].lower() or k in f["column"].lower()
               or k in f["control"].lower()]
    return partial[0] if len(partial) == 1 else (partial if partial else None)


def normalise_date(value):
    """Accept the ways people actually type a date, return G-MES's YYYYMMDD.

    A date typed as 2026-09-07 used to be written into the filter verbatim.
    G-MES stores YYYYMMDD, so the query then ran against a value it could not
    interpret - no error, just a different (or empty) answer. Anything not
    resolvable to a real calendar date is rejected outright rather than
    passed through and hoped for."""
    import re
    from datetime import datetime as _dt

    raw = (value or "").strip()
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    if len(digits) != 8:
        raise ValueError(
            f"{value!r} is not a date. Use YYYYMMDD (20260907) or "
            "YYYY-MM-DD (2026-09-07).")
    try:
        _dt.strptime(digits, "%Y%m%d")
    except ValueError:
        raise ValueError(f"{value!r} is not a real calendar date.")
    return digits


def date_columns(info):
    """The from/to date pair, if the screen has one."""
    frm = next((f for f in info["filters"]
                if "fromdate" in f["column"].lower() or "startdate" in f["column"].lower()), None)
    to = next((f for f in info["filters"]
               if "enddate" in f["column"].lower() or "todate" in f["column"].lower()), None)
    return frm, to


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

# The left panel carries several dimensions besides the named filters, and
# each one changes what the query returns:
#
#   Org / Prod / Fac / Proc     which category tree the selection comes from
#   STD / PLANT                 the organisation attribute
#   Including Past Org.         whether closed organisations are included
#   Plan Date / Create Date     WHICH date the period applies to
#   General / Compare / OI      the search mode
#   Quick View entries          e.g. Master Prod. Plan vs Detail Prod. Plan
#
# They are all buttons or checkboxes carrying their own label, and Nexacro
# encodes the selected state in the CSS class - "_Sel" or "V2" for chosen,
# "_Dis" or "_Default" for not. So they can be listed and set generically by
# label, rather than being wired in one at a time.
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
""" % cdp_common.JS_IS_VISIBLE


def left_options(ws):
    return evaluate(ws, JS_LEFT_OPTIONS)


def set_option(ws, label, verify_wait=6):
    """Click a left-panel option by its visible label, unless it is already
    selected. Returns a short description of what happened."""
    found = left_options(ws)
    matches = [o for o in found["options"] if o["label"].lower() == label.lower()]
    if not matches:
        matches = [o for o in found["options"] if label.lower() in o["label"].lower()]
    if not matches:
        names = ", ".join(o["label"] for o in found["options"][:14])
        raise RuntimeError(f"no left-panel option called {label!r}. Available: {names}")
    opt = matches[0]

    if opt["state"] == "selected":
        return f"{opt['label']} (already selected)"

    cdp_common.click_element_by_rect(ws, opt["x"], opt["y"])

    # Confirm it took, rather than assuming the click landed.
    deadline = time.time() + verify_wait
    while time.time() < deadline:
        time.sleep(0.5)
        now = left_options(ws)
        cur = next((o for o in now["options"]
                    if o["label"].lower() == opt["label"].lower()), None)
        if cur and cur["state"] in ("selected", "checked"):
            return f"{opt['label']} -> {cur['state']}"
        if cur and cur["state"] == "unknown":
            return f"{opt['label']} (clicked; state not reported)"
    return f"{opt['label']} (clicked; could not confirm)"


def run_inquiry_on(ws, form_code, dataset, max_wait=300, settle_checks=4,
                   poll_interval=1.0, stale_grace=25, empty_grace=60):
    """Click Inquiry and wait for THIS screen's result set to settle.

    The nightly job's version polls the Production Plan dataset by name.
    Reusing it here produced a silently wrong answer: running Production
    Plan by Model reported 875 rows - the count still sitting in the
    PREVIOUS screen's dataset - when the screen had returned 17. The export
    was correct because it used the discovered dataset; only the number and
    the wait were wrong, which is the more dangerous combination.

    So the dataset to watch is the one discovered on the screen being run.
    It must also be seen to CHANGE: a dataset left populated by an earlier
    run looks identical to a finished query. Nexacro clears the result set
    on Inquiry, so the change is observable - but if a query returns faster
    than the first poll, `stale_grace` allows a stable non-zero count
    through rather than failing a good run."""
    def row_count():
        r = gmes_data.read_dataset(ws, form_code, dataset, limit=0)
        return r.get("total", -1) if r.get("found") else -1

    before = row_count()
    button = gmes_common.click_control(ws, cls="btn_LF_Search_New", text="Inquiry")
    if not button:
        raise RuntimeError("the Inquiry button was not found on this screen")

    started = time.time()
    last, stable, changed = None, 0, False

    while time.time() - started < max_wait:
        time.sleep(poll_interval)
        count = row_count()

        popups = gmes_common.find_child_popups(ws)
        if popups.get("count"):
            names = [p["name"] for p in popups["popups"]]
            raise RuntimeError(f"a dialog opened instead of results: {names}")

        if count != before:
            changed = True

        if count > 0:
            stable = stable + 1 if count == last else 0
            last = count
            if stable >= settle_checks and (changed or time.time() - started > stale_grace):
                return count
        else:
            last, stable = count, 0
            if changed and time.time() - started > empty_grace:
                return 0            # cleared and stayed empty: genuinely no data

    raise RuntimeError(f"the query had not settled after {max_wait}s "
                       f"(last count {last})")


def clear_stale_filters(ws, info, keep):
    """Blank the free-text filters left over from an earlier run.

    G-MES keeps a screen alive behind its tab, and a filter typed into it
    STAYS there. A later run that does not mention that field inherits it
    silently: asking for 2026-09-07 returned zero rows because a Production
    Order from the previous run was still in the box. Nothing looked wrong -
    the date was right, the division was right, the answer was empty.

    Only `edt` text boxes are cleared, and only ones the caller did not set.
    Combos and checkboxes are left alone because their values are meaningful
    defaults (paramTecoYn is "All", a status list is "1^2^3^4"), and blanking
    those would break the query in a different way."""
    cleared = []
    for f in info["filters"]:
        if not f["control"].lower().startswith("edt"):
            continue
        if f["column"] in keep:
            continue
        if not (f["value"] or "").strip():
            continue
        try:
            apply_filter(ws, f, "")
            cleared.append(f"{f['label'] or f['column']}={f['value']}")
        except RuntimeError:
            pass
    return cleared


def apply_filter(ws, flt, value):
    result = gmes_data.set_filter(ws, flt["form"].replace(".xfdl.js", ""),
                                  flt["dataset"], {flt["column"]: value})
    if not result.get("found"):
        raise RuntimeError(f"could not write {flt['dataset']}.{flt['column']}")
    return result["applied"].get(flt["column"])


def run_one(ws, screen_code, division, date, sets, export, out_dir, options=()):
    """Open a screen, apply filters, Inquiry, export. Returns a result dict."""
    # Screen codes are case-insensitive to G-MES, but a run reported as
    # "p1112um00" reads like a different thing from "P1112UM00".
    screen_code = screen_code.strip().upper()
    started = time.time()
    out = {"screen": screen_code, "ok": False, "rows": 0, "files": [], "error": None}

    print(f"\n{'=' * 70}\n{screen_code}\n{'=' * 70}")

    # 1. Open and bring to the front. Both matter - a background screen
    #    accepts filter writes and then the Inquiry lands elsewhere.
    opened = gmes_open_screen.open_screen(ws, screen_code)
    out["title"] = opened.get("title", "")
    gmes_open_screen.activate_screen(ws, opened.get("winId", ""))
    print(f"  screen   : {out['title']}  [{opened.get('menuId')}]")

    # 2. Discover what this screen actually offers.
    info = discover(ws, screen_code)
    if not info.get("found"):
        raise RuntimeError("the screen's forms did not appear after opening")
    grid = result_dataset(info)
    if not grid:
        raise RuntimeError("no result grid found on this screen")
    print(f"  filters  : {len(info['filters'])} discovered")
    print(f"  results  : {grid['dataset']} (grid {grid['name']})")

    # 3. Left-panel options first. Switching a category tab or a Quick View
    #    rebuilds the panel, so anything set before it would be discarded.
    for label in options:
        print(f"  option   : {set_option(ws, label)}")

    # 4. Division, if the screen has an org tree.
    if division and info["hasOrgTree"]:
        picked = job.select_division(ws, division)
        print(f"  division : {division} at {picked['pathKey']}")
    elif division:
        print(f"  division : this screen has no org tree - skipped")

    # 5. Dates.
    if date:
        frm, to = date_columns(info)
        if frm:
            apply_filter(ws, frm, date)
        if to:
            apply_filter(ws, to, date)
        if frm or to:
            print(f"  date     : {date} -> "
                  f"{', '.join(f['column'] for f in (frm, to) if f)}")
        else:
            print("  date     : this screen has no from/to date filter - skipped")

    # 6. Clear text filters left behind by an earlier run before applying
    #    this run's own, so nothing is inherited silently.
    wanted_columns = set()
    for key in sets:
        m = match_filter(info, key)
        if m is not None and not isinstance(m, list):
            wanted_columns.add(m["column"])
    stale = clear_stale_filters(ws, info, wanted_columns)
    if stale:
        print(f"  cleared  : leftover {', '.join(stale)}")

    # 7. Anything else the caller named.
    for key, value in sets.items():
        flt = match_filter(info, key)
        if flt is None:
            hint = ""
            if any(w in key.lower() for w in ("division", "org", "category",
                                              "attribute", "plant", "std")):
                hint = (" That looks like an organisation choice: use the "
                        "Division prompt / --division, or --option for the "
                        "Org / Prod / Fac / Proc and STD / PLANT controls.")
            raise RuntimeError(f"no filter matches {key!r} on this screen "
                               f"(run 'describe {screen_code}' to see them)."
                               + hint)
        if isinstance(flt, list):
            names = ", ".join(f"{f['label'] or f['column']}" for f in flt[:6])
            raise RuntimeError(f"{key!r} is ambiguous - matches: {names}")
        applied = apply_filter(ws, flt, value)
        print(f"  filter   : {flt['label'] or flt['column']} = {applied!r}")

    # 8. Inquiry, waiting for THIS screen's result set to settle.
    rows = run_inquiry_on(ws, grid["form"].replace(".xfdl.js", ""), grid["dataset"])
    out["rows"] = rows
    print(f"  inquiry  : {rows} rows in {time.time() - started:.1f}s")
    if rows == 0:
        raise RuntimeError("the query returned no rows - nothing exported")

    # 9. Export.
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = (out["title"] or screen_code).replace("/", "-")
    if export in ("xlsx", "both"):
        downloaded = job.download_excel(ws, out_dir)
        final = os.path.join(out_dir, f"{name}_{stamp}.xlsx")
        os.replace(downloaded, final)
        out["files"].append(final)
        print(f"  excel    : {os.path.basename(final)}"
              + ("  [DRM]" if job.is_drm_protected(final) else ""))
    if export in ("csv", "both"):
        path, written, total = write_csv(ws, info, grid, out_dir, name, stamp)
        if path:
            out["files"].append(path)
            note = "" if written == total else f"  ({total - written} empty rows dropped)"
            print(f"  csv      : {os.path.basename(path)}  {written} rows{note}")

    out["ok"] = True
    out["seconds"] = round(time.time() - started, 1)
    return out


def write_csv(ws, info, grid, out_dir, name, stamp):
    """Write the result dataset as CSV.

    Only completely empty rows are dropped. That is deliberately weaker than
    the Production Plan job, which drops rows with no `poNo` - because on an
    unknown screen there is no way to know which column is the key, and
    guessing would silently discard real data.

    So some datasets yield more CSV rows than the grid appears to show:
    filtering one PO returned four dataset rows for a single visible line,
    the other three being continuation rows the grid merges. Both counts are
    reported rather than one being quietly chosen.

    Returns (path, written, total)."""
    import csv as _csv
    form_code = grid["form"].replace(".xfdl.js", "")
    result = gmes_data.read_dataset(ws, form_code, grid["dataset"], limit=-1)
    if not result.get("found") or not result["rows"]:
        return None, 0, 0

    cols = [c for c in result["columns"] if not c.startswith("_")]
    real = [r for r in result["rows"] if any((r.get(c) or "").strip() for c in cols)]
    path = os.path.join(out_dir, f"{name}_{stamp}_data.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = _csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(real)
    return path, len(real), len(result["rows"])


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_describe(ws, screen_code):
    opened = gmes_open_screen.open_screen(ws, screen_code)
    gmes_open_screen.activate_screen(ws, opened.get("winId", ""))
    info = discover(ws, screen_code)
    if not info.get("found"):
        print("Could not read this screen.")
        return 1

    print(f"\n{opened.get('title')}   [{screen_code} / {opened.get('menuId')}]")
    print(f"Org tree (Division) : {'yes' if info['hasOrgTree'] else 'no'}")
    print(f"Inquiry button      : {'yes' if info['hasInquiry'] else 'no'}")

    grid = result_dataset(info)
    if grid:
        ds = info["datasets"].get(grid["dataset"], {})
        print(f"Result grid         : {grid['name']} -> {grid['dataset']} "
              f"({ds.get('cols', '?')} columns, {ds.get('rows', '?')} rows now)")

    print(f"\nFilters discovered ({len(info['filters'])}):\n")
    print(f"  {'LABEL':<26} {'COLUMN':<22} {'NOW':<14} CONTROL")
    print("  " + "-" * 84)
    for f in sorted(info["filters"], key=lambda x: (not x["visible"], x["label"])):
        mark = " " if f["visible"] else "."
        print(f" {mark}{(f['label'] or '-'):<26} {f['column']:<22} "
              f"{(f['value'] or '')[:13]:<14} {f['control']}")
    print("\n  ('.' = bound but not currently visible on screen)")

    unbound = info.get("unbound", [])
    if unbound:
        print(f"\nVisible inputs this screen does NOT bind to a dataset "
              f"({len(unbound)}):\n")
        for u in unbound:
            print(f"  {(u['label'] or '-'):<26} {u['control']:<22} {u['form']}")
        print("\n  These cannot be set with --set; the screen fills them in code.")
        print("  Ask for them to be added if you need them.")

    if not info["filters"]:
        print("\n  NOTE: this screen binds no filters at all. It can still be")
        print("  opened, run and exported - just not filtered by this tool.")

    print(f"\nSet any of them with:  --set \"<label or column>=<value>\"")
    return 0


def cmd_run(ws, screens, division, date, sets, export, out_dir, options=()):
    os.makedirs(out_dir, exist_ok=True)
    results = []
    for code in screens:
        try:
            results.append(run_one(ws, code, division, date, sets, export, out_dir, options))
        except Exception as e:
            print(f"  FAILED   : {e}")
            cdp_common.screenshot_on_failure(f"gmes_report_{code}")
            results.append({"screen": code, "ok": False, "rows": 0,
                            "files": [], "error": str(e)})

    print(f"\n{'=' * 70}\nSUMMARY\n{'=' * 70}")
    print(f"  {'SCREEN':<14} {'STATUS':<9} {'ROWS':>7}  FILES / ERROR")
    print("  " + "-" * 84)
    for r in results:
        if r["ok"]:
            files = ", ".join(os.path.basename(f) for f in r["files"]) or "-"
            print(f"  {r['screen']:<14} {'ok':<9} {r['rows']:>7}  {files}")
        else:
            print(f"  {r['screen']:<14} {'FAILED':<9} {'-':>7}  {r['error']}")
    ok = sum(1 for r in results if r["ok"])
    print(f"\n  {ok}/{len(results)} succeeded")
    return 0 if ok == len(results) else 1


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["describe", "run"])
    parser.add_argument("screens", nargs="+", metavar="UI",
                        help="one or more screen codes, e.g. P1112UM00")
    parser.add_argument("--division", help="e.g. VD - applied where the screen has an org tree")
    parser.add_argument("--date", help="YYYYMMDD, applied to the screen's from/to date pair")
    parser.add_argument("--days-back", type=int,
                        help="use the date N days ago instead of --date")
    parser.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                        help="any discovered filter, by label or column")
    parser.add_argument("--option", action="append", default=[], metavar="LABEL",
                        help='a left-panel option by its label, e.g. PLANT, '
                             '"Create Date", Prod, "Including Past Org."')
    parser.add_argument("--export", choices=["xlsx", "csv", "both", "none"],
                        default="both")
    parser.add_argument("--output-dir", default=OUTPUT_DIR)
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()

    date = args.date
    if args.days_back is not None:
        date = (datetime.now() - timedelta(days=args.days_back)).strftime("%Y%m%d")
    try:
        date = normalise_date(date)
    except ValueError as e:
        print(f"ERROR: {e}")
        return 2

    sets = {}
    for item in args.set:
        if "=" not in item:
            print(f"ERROR: --set needs NAME=VALUE, got {item!r}")
            return 2
        k, v = item.split("=", 1)
        sets[k.strip()] = v.strip()

    if gmes_login.main() != 0:
        return 1

    ws = connect_gmes()
    try:
        if args.command == "describe":
            for code in args.screens:
                cmd_describe(ws, code)
            return 0
        return cmd_run(ws, args.screens, args.division, date, sets,
                       args.export, args.output_dir, args.option)
    finally:
        ws.close()
        if not args.keep_open and cdp_common.LAST_CHROME_PROCESS:
            try:
                cdp_common.LAST_CHROME_PROCESS.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
