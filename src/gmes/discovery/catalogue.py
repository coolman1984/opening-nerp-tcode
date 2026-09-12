"""Open any G-MES screen by its code or name - the equivalent of typing a
T-code in N-ERP.

Forked from gmes_open_screen.py (library functions only; the CLI/argparse
front end is not ported here - that becomes a `cli/commands/find.py` and
`describe.py` in a later phase).

Why a search box and not the menus: the menu tree is four levels deep and
its labels are translated, while a screen code is short, stable and printed
on every screen's own breadcrumb. One entry point reaches all 809 screens.

Two things had to be learned to make this reliable, both recorded in
HISTORY.md and GMES_SKILL.md gotcha #22:

  * Setting the search box value through the Nexacro API fills the box but
    searches nothing. The suggestion list is driven by the control's keyup
    handler, so the text must be typed with real key events.
  * The Notice popup is MODAL. While it is open the whole application is
    greyed out and every click is swallowed silently - the search button
    appeared to do nothing at all until the popup was closed first.
"""
import json
import re
import time

from ..browser.cdp import evaluate, send
from ..browser.interaction import click_element_by_rect
from ..nexacro.dom import js_find_by_id
from ..nexacro.js_snippets import JS_IS_VISIBLE
from ..nexacro.popups import close_child_popups
from ..query.form_locator import list_forms

SEARCH_EDIT = "mainframe.vFrameSet1.vFrameSet2.topFrame.form.divSearch.form.edtSearch"

# The screen catalogue is `gdsMenuList` - 1177 rows, held client-side.
#
# A representative screen row carries a menu id, screen code, translated
# title, breadcrumb, folder prefix, and menu type. These fields are generic
# catalogue facts; no report-specific mapping belongs here.
#
# menuId is the identifier that matters: it is what gdsOpenMenu records when
# a screen opens, and what the window is named after (winPPM0219_0_603).
#
# Do NOT use `gdsMenuList_` for this (GMES_SKILL #21). It looks like the same
# catalogue but its menuTitle is Korean only and its menuIds are a different
# series (PM0001 vs PPM0219), so joining or searching it in English finds
# nothing.
JS_CATALOGUE = r"""
(function() {
    const ds = nexacro.getApplication().gdsMenuList;
    if (!ds) return JSON.stringify({found: false});

    const val = (r, c) => { try { return String(ds.getColumn(r, c) || ''); } catch (e) { return ''; } };

    // Pass one: every menuId's display name, so ancestors can be resolved
    // into a readable breadcrumb.
    const name = {};
    for (let r = 0; r < ds.getRowCount(); r++) {
        const id = val(r, 'menuId');
        if (id) name[id] = val(r, 'enMsgCont') || val(r, 'msgCont') || val(r, 'koMsgCont');
    }
    function breadcrumb(sn) {
        // screenSn is "UI0000>PPM0001>PPM0087>..." - the ancestor chain.
        return sn.split('>')
                 .filter(id => id && id !== 'UI0000')
                 .map(id => name[id] || id)
                 .join(' > ');
    }

    const q = %s.toLowerCase();
    const rows = [];
    let screens = 0;
    for (let r = 0; r < ds.getRowCount(); r++) {
        const screenId = val(r, 'sysScreenId');
        // Folders have no screen, and external links carry a URL instead.
        if (!screenId || screenId.indexOf('http') === 0) continue;
        screens++;
        const menuId = val(r, 'menuId');
        const en = val(r, 'enMsgCont') || val(r, 'msgCont');
        const ko = val(r, 'koMsgCont');
        const hay = (menuId + ' ' + screenId + ' ' + en + ' ' + ko).toLowerCase();
        if (q && hay.indexOf(q) === -1) continue;
        if (rows.length < 60) {
            rows.push({screenId: screenId, menuTitle: en || ko, korean: ko,
                       path: breadcrumb(val(r, 'screenSn')), menuId: menuId,
                       sysCode: val(r, 'sysCode'),
                       pageUrl: val(r, 'fldrNm') + screenId});
        }
    }
    return JSON.stringify({found: true, total: screens, matched: rows.length, rows: rows});
})()
"""

# gdsOpenMenu lists the screens currently open as tabs.
JS_OPEN_MENU = r"""
(function() {
    const ds = nexacro.getApplication().gdsOpenMenu;
    if (!ds) return JSON.stringify({found: false});
    const cols = [];
    for (let i = 0; i < ds.getColCount(); i++) cols.push(ds.getColID(i));
    const rows = [];
    for (let r = 0; r < ds.getRowCount(); r++) {
        const o = {};
        for (const c of cols) { try { o[c] = String(ds.getColumn(r, c) || ''); } catch (e) {} }
        rows.push(o);
    }
    return JSON.stringify({found: true, rows: rows});
})()
"""


def search_catalogue(ws, query=""):
    """Search the client-side screen catalogue by code, name, path or menu id.

    Named distinctly from this module (`catalogue.py`) on purpose: a same-
    named function re-exported from `discovery/__init__.py` previously
    shadowed the `gmes.discovery.catalogue` submodule attribute itself,
    so any `from . import catalogue` or `import gmes.discovery.catalogue`
    elsewhere silently got the function instead of the module - the direct
    cause of a live "'function' object has no attribute 'open_screens'"
    failure. See HISTORY.md."""
    return evaluate(ws, JS_CATALOGUE % json.dumps(query))


def open_screens(ws):
    return evaluate(ws, JS_OPEN_MENU)


# A work-form (…WM00, …UF00, …WF00) has its own catalogue entry but is never
# itself a top-level tab: it loads nested inside its …UM00 shell's tab, and
# gdsOpenMenu only ever records the shell. Its form path carries the
# containing tab's window id as a plain segment (e.g.
# "...workFrameSet.winPPM0221_2_373.divWorkMain..."), which is how a code
# whose shell is already open is still recognised without a catalogue
# search - one that would click the already-open shell, create no new tab,
# and time out waiting for a menu id gdsOpenMenu will never record.
_WIN_ID_RE = re.compile(r"win[A-Za-z0-9]+_\d+_\d+")


def tab_for_embedded_form(ws, code, rows):
    """The already-open tab containing `code`, if it is loaded as a nested
    work-form rather than a top-level tab of its own; else None."""
    for form in list_forms(ws).get("forms", []):
        if form.get("file", "").upper().startswith(code.upper()):
            match = _WIN_ID_RE.search(form.get("path", ""))
            if match:
                return next((r for r in rows if r.get("winId") == match.group(0)), None)
    return None


def type_into_search(ws, text):
    """Clear the search box and type into it with real key events.

    `set_value()` alone is not enough: the suggestion list is produced by
    the control's own keyup handler, so a programmatic assignment fills the
    box and searches nothing."""
    evaluate(ws, """
    (function() {
        const f = nexacro.getApplication().mainframe.vFrameSet1.vFrameSet2.topFrame.form;
        f.divSearch.form.edtSearch.set_value("");
        return JSON.stringify({ok: true});
    })()""")

    box = evaluate(ws, js_find_by_id(SEARCH_EDIT))
    if not box.get("found"):
        raise RuntimeError(f"The search box is not reachable ({box.get('reason')}). "
                           "A modal popup may be covering the application.")
    click_element_by_rect(ws, box["x"], box["y"])
    time.sleep(0.4)

    for ch in text:
        for kind in ("keyDown", "char", "keyUp"):
            params = {"type": kind, "key": ch, "code": f"Key{ch.upper()}"}
            if kind == "char":
                params["text"] = ch
            else:
                params["windowsVirtualKeyCode"] = ord(ch.upper())
            send(ws, "Input.dispatchKeyEvent", params)
        time.sleep(0.08)
    return box


# The suggestion list is a Nexacro grid, `integratedSearch.form.grdResult`,
# bound to `dsSearchResult`. Reading that dataset says exactly which row is
# which, so the right row can be chosen by data instead of by guessing which
# visible element is a result.
JS_SEARCH_RESULTS = r"""
(function() {
    const app = nexacro.getApplication();
    let f = null;
    try { f = app.mainframe.vFrameSet1.vFrameSet2.topFrame.form.integratedSearch.form; }
    catch (e) { return JSON.stringify({found: false, reason: 'popup not created'}); }
    if (!f) return JSON.stringify({found: false, reason: 'popup not created'});
    const ds = f.dsSearchResult;
    if (!ds) return JSON.stringify({found: false, reason: 'no result dataset'});
    const rows = [];
    for (let r = 0; r < ds.getRowCount(); r++) {
        const g = c => { try { return String(ds.getColumn(r, c) || ''); } catch (e) { return ''; } };
        rows.push({index: r, menuId: g('menuId'), screenId: g('sysScreenId'),
                   name: g('enMsgCont') || g('msgCont') || g('koMsgCont')});
    }
    return JSON.stringify({found: true, count: rows.length, rows: rows});
})()
"""


def wait_for_results(ws, max_wait=20, poll_interval=0.5):
    """Wait for the search to return rows in dsSearchResult."""
    deadline = time.time() + max_wait
    last = {}
    while time.time() < deadline:
        last = evaluate(ws, JS_SEARCH_RESULTS)
        if last.get("found") and last.get("count"):
            return last["rows"]
        time.sleep(poll_interval)
    return []


def js_result_row_rect(index):
    """Where to click for result row `index`.

    It must be the GRID row. The first attempt clicked the popup's detail
    panel (`divDetail.form.staTitle`), which shows the same text and is the
    obvious visual match - and clicking it opens nothing at all."""
    return """
    (function() {
        const isVisible = %s;
        const prefix = 'mainframe.vFrameSet1.vFrameSet2.topFrame.form.integratedSearch.form.grdResult.body.gridrow_%d';
        let el = document.getElementById(prefix + '.cell_%d_0') ||
                 document.getElementById(prefix);
        if (!el) return JSON.stringify({found: false, reason: 'grid row not rendered'});
        if (!isVisible(el)) return JSON.stringify({found: false, reason: 'grid row not visible'});
        const r = el.getBoundingClientRect();
        return JSON.stringify({found: true, id: el.id,
                               text: (el.textContent || '').trim().slice(0, 50),
                               x: r.left + r.width/2, y: r.top + r.height/2});
    })()
    """ % (JS_IS_VISIBLE, index, index)


def js_window_visible(win_id):
    return """
    (function() {
        const isVisible = %s;
        const el = document.getElementById(
            'mainframe.vFrameSet1.vFrameSet2.hFrameSet1.workFrameSet.%s');
        if (!el) return JSON.stringify({found: false});
        return JSON.stringify({found: true, visible: isVisible(el)});
    })()
    """ % (JS_IS_VISIBLE, win_id)


def activate_screen(ws, win_id, max_wait=20):
    """Bring an already-open screen to the front by clicking its tab.

    G-MES keeps every opened screen alive behind tabs, so a screen can be
    "open" while a completely different one is in front. Their datasets stay
    reachable either way, which makes this dangerous: filters written to a
    background screen apply fine, and then the Inquiry click lands on
    whatever IS in front. That produced a run that set the date and division
    correctly, queried the wrong screen, and reported zero rows.

    Tabs are named after the window: TAB_<winId>."""
    tab_id = (f"mainframe.vFrameSet1.vFrameSet2.mdiFrame.form.divTab.form."
              f"TAB_{win_id}")
    info = evaluate(ws, js_find_by_id(tab_id))
    if not info.get("found"):
        return False
    click_element_by_rect(ws, info["x"], info["y"])

    deadline = time.time() + max_wait
    while time.time() < deadline:
        state = evaluate(ws, js_window_visible(win_id))
        if state.get("found") and state.get("visible"):
            return True
        time.sleep(0.5)
    return False


def open_screen(ws, query, timeout=90, log=print):
    """Close blockers, search, click the first suggestion, confirm it opened.

    `log` is how the caller receives the running commentary, in the same
    `key : detail` shape used everywhere else in this project, so a front
    end can lay it out with everything around it."""
    closed = close_child_popups(ws)
    if closed:
        log(f"  popups   : closed {closed}")

    before = {r.get("winId") for r in open_screens(ws).get("rows", [])}

    type_into_search(ws, query)
    results = wait_for_results(ws)
    if not results:
        raise RuntimeError(
            f"The search returned nothing for {query!r}. Check the code with "
            f"the 'find' command.")

    # Prefer an exact screen-code or menu-id match over the first row.
    wanted = query.strip().upper()
    chosen = next((r for r in results
                   if wanted in (r["screenId"].upper(), r["menuId"].upper())),
                  results[0])
    if len(results) > 1:
        log(f"  found    : {chosen['screenId']} - {chosen['name']} "
            f"({len(results)} matches; took the exact one)")
    else:
        log(f"  found    : {chosen['screenId']} - {chosen['name']}")

    target = evaluate(ws, js_result_row_rect(chosen["index"]))
    if not target.get("found"):
        raise RuntimeError(f"The result row could not be clicked "
                           f"({target.get('reason')}).")
    click_element_by_rect(ws, target["x"], target["y"])

    # Wait for the tab to appear in gdsOpenMenu rather than guessing.
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = open_screens(ws).get("rows", [])
        for r in rows:
            if r.get("menuId", "").upper() == chosen["menuId"].upper():
                # Covers both a new tab and re-activating one already open.
                return r
        new = [r for r in rows if r.get("winId") not in before]
        if new:
            return new[0]
        time.sleep(1.0)

    raise RuntimeError(
        f"{chosen['screenId']} ({chosen['menuId']}) did not open within "
        f"{timeout}s. It may not be permitted for this account.")
