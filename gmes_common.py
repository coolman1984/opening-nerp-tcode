"""
Shared helpers for driving GMES (Nexacro).

Why GMES is easier than NERP's SAP screens: Nexacro renders real DOM
elements and gives them stable, meaningful ids that mirror the form tree -
`mainframe.vFrameSet1.loginFrame.form.divLogin.form.btnLogin` is the Login
button and will still be called that tomorrow. So we target ids, not screen
positions, and nothing depends on window size.

What carries over unchanged from the NERP work:
  * Nexacro buttons are <div>s, so element.click() is not reliable - use a
    real dispatched mouse event.
  * Never sleep a fixed duration; poll until the thing is actually there.
"""
import time

import cdp_common
from cdp_common import (
    click_element_by_rect, connect, evaluate, get_page_tab, get_tabs,
)

GMES_URL = "http://seegmes4.sec.samsung.net/mes4/sm/nexacro/index_ext_2318.html"


def gmes_tab(port=None, wait=20):
    """The browser tab showing GMES.

    Matched on the host, and the Samsung SSO window is excluded outright.
    Matching the whole URL for "gmes" picked the ADFS sign-in tab instead:
    its address carries a long base64 `SAMLRequest`, and that happened to
    contain those four letters. Everything downstream then read the wrong
    document and reported the G-MES login form as missing.

    A closed browser is the most common reason any of these tools fail, so it
    is reported as one sentence rather than as a urllib stack trace about a
    refused connection to a port number."""
    def host_of(tab):
        url = tab.get("url") or ""
        return url.split("//", 1)[-1].split("/", 1)[0].lower()

    # Waited for, not taken on the first look. Straight after Chrome starts,
    # the G-MES tab is still on about:blank or mid-navigation; returning
    # whatever page happened to be listed handed back a tab that was about to
    # be replaced, and attaching to it died with "Connection to remote host
    # was lost".
    deadline = time.time() + wait
    pages = []
    while True:
        try:
            pages = [t for t in get_tabs(port=port) if t.get("type") == "page"]
        except Exception:
            raise RuntimeError(
                "Cannot reach the automation browser. It is not running, or was "
                "closed by a previous job. Start it with:  python gmes_login.py")
        for tab in pages:
            if "secsso.net" not in host_of(tab) and "gmes" in host_of(tab):
                return tab
        if time.time() >= deadline:
            break
        time.sleep(0.5)

    real = [t for t in pages if "secsso.net" not in host_of(t)]
    return real[0] if real else (pages[0] if pages else None)


def connect_gmes(timeout=20, port=None, attempts=4):
    """Attach to the G-MES tab, re-resolving it on each attempt.

    A tab that is loading can accept the socket and then drop it mid-handshake
    while Chrome swaps renderers, which surfaced as a bare
    WebSocketConnectionClosedException out of `Runtime.enable`. The tab is
    looked up again each time rather than retried against the same one,
    because by then it is usually a different tab."""
    last = None
    for attempt in range(attempts):
        tab = gmes_tab(port=port)
        if tab is None:
            raise RuntimeError("No G-MES tab is open. Run:  python gmes_login.py")
        try:
            return connect(tab["webSocketDebuggerUrl"], timeout=timeout)
        except Exception as e:
            last = e
            time.sleep(1.5)
    raise RuntimeError(f"Could not attach to the G-MES tab after {attempts} "
                       f"attempts ({last}).")


def js_find_by_id(element_id):
    """Locate one Nexacro element by its exact id and report where it is."""
    return """
    (function() {
        const isVisible = %s;
        const el = document.getElementById(%s);
        if (!el) return JSON.stringify({found: false, reason: 'no such id'});
        if (!isVisible(el)) return JSON.stringify({found: false, reason: 'not visible'});
        const r = el.getBoundingClientRect();
        return JSON.stringify({found: true, text: (el.textContent || '').trim().slice(0, 40),
                               x: r.left + r.width/2, y: r.top + r.height/2});
    })()
    """ % (cdp_common.JS_IS_VISIBLE, cdp_common.json.dumps(element_id))


def click_by_id(ws, element_id, attempts=20, delay=0.5):
    """Click a Nexacro control by id, waiting for it to appear first.

    Polls rather than assuming the control is ready: a Nexacro screen builds
    itself in JavaScript after the page reports 'complete', so a control can
    be seconds away from existing when we first look."""
    for _ in range(attempts):
        info = evaluate(ws, js_find_by_id(element_id))
        if info.get("found"):
            click_element_by_rect(ws, info["x"], info["y"])
            return info
        time.sleep(delay)
    return None


def set_value_by_id(ws, element_id, value):
    """Type into a Nexacro input. Nexacro listens for the events, so a bare
    value assignment is not enough."""
    js = """
    (function() {
        const value = %s;
        const el = document.getElementById(%s);
        if (!el) return JSON.stringify({found: false});
        %s
        el.dispatchEvent(new Event('blur', { bubbles: true }));
        return JSON.stringify({found: true, value: el.value});
    })()
    """ % (cdp_common.json.dumps(value), cdp_common.json.dumps(element_id),
           cdp_common.JS_SET_VALUE)
    return evaluate(ws, js)


JS_SCREEN_REPORT = """
(function() {
    const isVisible = %s;
    const seen = new Set();
    const items = [];
    Array.from(document.querySelectorAll('div, span, button, a, td, li')).forEach(el => {
        const t = (el.textContent || '').trim();
        if (!t || t.length > 40) return;
        if (!isVisible(el) || seen.has(t)) return;
        seen.add(t);
        const r = el.getBoundingClientRect();
        items.push({text: t, id: el.id,
                    x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2)});
    });
    const fields = Array.from(document.querySelectorAll('input, textarea, select'))
        .filter(isVisible)
        .map(el => ({id: el.id, type: el.type || '', value: (el.value || '').slice(0, 40)}));
    return JSON.stringify({
        title: document.title,
        url: location.href,
        loggedIn: !document.getElementById(
            'mainframe.vFrameSet1.loginFrame.form.divLogin.form.btnLogin'),
        textPreview: (document.body ? (document.body.innerText || '') : '')
                        .replace(/\\s+/g, ' ').trim().slice(0, 500),
        fields: fields.slice(0, 40),
        items: items.slice(0, 80)
    });
})()
""" % cdp_common.JS_IS_VISIBLE


def screen_report(ws):
    return evaluate(ws, JS_SCREEN_REPORT)


def print_report(report, item_limit=60):
    print(f"Title      : {report.get('title')!r}")
    print(f"URL        : {report.get('url')}")
    print(f"Logged in  : {report.get('loggedIn')}")
    print(f"\nOn screen  : {report.get('textPreview')!r}\n")
    if report.get("fields"):
        print("Fields:")
        for f in report["fields"]:
            print(f"  id={f['id']!r} type={f['type']!r} value={f['value']!r}")
    if report.get("items"):
        print("\nClickable items:")
        for it in report["items"][:item_limit]:
            print(f"  {it['text']!r:36} id={it['id']!r} at ({it['x']}, {it['y']})")


def wait_until(ws, predicate, max_wait=60, poll_interval=1.0):
    """Poll a screen report until predicate(report) is true. Returns the last
    report either way, so a timeout still shows what was actually on screen."""
    deadline = time.time() + max_wait
    report = {}
    while time.time() < deadline:
        try:
            report = screen_report(ws)
            if predicate(report):
                return True, report
        except Exception:
            pass
        time.sleep(poll_interval)
    return False, report


def list_windows(port=None):
    """Every browser window/tab currently open - SSO often opens a popup."""
    return [t for t in get_tabs(port=port) if t.get("type") == "page"]


# --------------------------------------------------------------------------
# Finding controls
# --------------------------------------------------------------------------
#
# Full ids must NEVER be hardcoded for anything inside a work screen. GMES
# numbers each opened screen instance, so the same Inquiry button was
#   ...workFrameSet.winPPM0219_0_516.form.divLeft.form.btnSearch
# on one visit and
#   ...workFrameSet.winPPM0219_0_315.form.divLeft.form.btnSearch
# on the next. An exact-id rule works once and then silently finds nothing.
#
# The stable parts are the screen code (winPPM0219), the trailing control
# path (form.divLeft.form.btnSearch), the CSS class Nexacro assigns by
# control type (btn_LF_Search_New), and the visible label. Match on those.
#
# Only the shell frames (topFrame, loginFrame, mdiFrame) have genuinely
# fixed ids, because there is only ever one of each.

def js_find_elements(id_regex=None, cls=None, text=None, exact_text=True,
                     visible_only=True, limit=40):
    return """
    (function() {
        const isVisible = %s;
        const idRe   = %s;
        const cls    = %s;
        const text   = %s;
        const exact  = %s;
        const visOnly = %s;

        const rx = idRe ? new RegExp(idRe) : null;
        const out = [];
        for (const el of document.querySelectorAll('*')) {
            const id = el.id || '';
            const klass = (typeof el.className === 'string') ? el.className : '';
            const t = (el.textContent || '').trim();

            if (rx && !rx.test(id)) continue;
            if (cls && !klass.split(/\\s+/).includes(cls)) continue;
            if (text !== null) {
                if (exact ? t !== text : !t.toLowerCase().includes(text.toLowerCase()))
                    continue;
            }
            if (visOnly && !isVisible(el)) continue;

            const r = el.getBoundingClientRect();
            out.push({id: id, cls: klass.slice(0, 60), text: t.slice(0, 40),
                      tag: el.tagName, w: Math.round(r.width), h: Math.round(r.height),
                      x: r.left + r.width/2, y: r.top + r.height/2,
                      area: r.width * r.height});
            if (out.length >= %d) break;
        }
        // Smallest first: the real control, not a container wrapping it.
        out.sort((a, b) => a.area - b.area);
        return JSON.stringify({count: out.length, hits: out});
    })()
    """ % (cdp_common.JS_IS_VISIBLE,
           cdp_common.json.dumps(id_regex) if id_regex else "null",
           cdp_common.json.dumps(cls) if cls else "null",
           cdp_common.json.dumps(text) if text is not None else "null",
           "true" if exact_text else "false",
           "true" if visible_only else "false",
           limit)


def find_elements(ws, **criteria):
    return evaluate(ws, js_find_elements(**criteria))


def click_control(ws, attempts=20, delay=0.5, **criteria):
    """Click the smallest visible control matching the criteria, waiting for
    it to appear first. Returns the clicked element, or None."""
    for _ in range(attempts):
        found = find_elements(ws, **criteria)
        if found.get("count"):
            target = found["hits"][0]
            click_element_by_rect(ws, target["x"], target["y"])
            return target
        time.sleep(delay)
    return None


# --------------------------------------------------------------------------
# Signed-in state
# --------------------------------------------------------------------------

# The signed-in user's name sits in the top bar. Testing for THIS is right;
# testing for the absence of the Login button is not - Nexacro keeps the
# login frame in the DOM after signing in, merely hidden, so "no login
# button" never becomes true and the check would report a failed login
# forever.
USER_INFO_BTN = "mainframe.vFrameSet1.vFrameSet2.topFrame.form.btnUserInfo"


def is_logged_in(ws):
    info = evaluate(ws, js_find_by_id(USER_INFO_BTN))
    return bool(info.get("found")), info.get("text", "")


# --------------------------------------------------------------------------
# Popups
# --------------------------------------------------------------------------

# Nexacro gives every floating popup a title bar with the same three
# controls. Matching on the CSS class rather than the popup's own name
# matters: the Notice window's id contains Korean text (`공지사항`), and the
# next popup will have a different name again, so a name-based rule would
# only ever close this one popup on this one screen.
#
# The scope is deliberately narrow - only title bars marked
# `titlebarChildFrame`, i.e. floating child windows. The user's actual work
# screen also has a close button, and closing that would throw away the
# thing the automation just opened.
JS_CLOSE_CHILD_POPUPS = """
(function() {
    const isVisible = %s;
    const closed = [];
    const bars = Array.from(document.querySelectorAll('.TitleBarControl.titlebarChildFrame'));
    for (const bar of bars) {
        if (!isVisible(bar)) continue;
        const btn = bar.querySelector('.closebutton');
        if (!btn || !isVisible(btn)) continue;
        const r = btn.getBoundingClientRect();
        closed.push({
            name: (bar.textContent || '').trim().slice(0, 40),
            id: btn.id,
            x: r.left + r.width / 2,
            y: r.top + r.height / 2
        });
    }
    return JSON.stringify({count: closed.length, popups: closed});
})()
""" % cdp_common.JS_IS_VISIBLE


def find_child_popups(ws):
    return evaluate(ws, JS_CLOSE_CHILD_POPUPS)


def close_popups_when_they_appear(ws, appear_wait=45, poll_interval=1.0,
                                  quiet_rounds=3, verbose=True):
    """Wait for popups to show up, then close them - and keep watching.

    Checking once straight after signing in finds nothing: the Notice window
    is opened by the app a few seconds AFTER the user name appears in the top
    bar, so a single check races it and reports "none were open" while the
    popup is on its way. It then sits there blocking every later click.

    So this waits for the first popup to appear, closes it, and keeps
    looking until several consecutive checks come back empty - which also
    catches notices that queue up one behind another."""
    closed = []
    started = time.time()
    deadline = started + appear_wait
    quiet, stuck = 0, 0

    # `or closed` used to keep this loop alive indefinitely once anything had
    # been closed, and the deadline was pushed out another 8s on every pass
    # that clicked something - so a popup that would not close kept the loop
    # running and the list growing. It is bounded now, in both directions.
    while time.time() < deadline and time.time() - started < appear_wait * 2:
        found = find_child_popups(ws)
        before = found.get("count", 0)
        if before:
            quiet = 0
            for popup in found["popups"]:
                click_element_by_rect(ws, popup["x"], popup["y"])
                name = popup["name"] or popup["id"]
                closed.append(name)
                if verbose:
                    print(f"  closed popup: {name}")
                time.sleep(0.4)
            time.sleep(poll_interval)
            if find_child_popups(ws).get("count", 0) >= before:
                stuck += 1
                if stuck >= 2:
                    if verbose:
                        print("  a popup is not responding to its close button - "
                              "leaving it and carrying on")
                    break
            else:
                stuck = 0
                deadline = max(deadline, time.time() + 8)   # let a queued one arrive
            continue

        quiet += 1
        if closed and quiet >= quiet_rounds:
            break
        time.sleep(poll_interval)

    return closed


def close_child_popups(ws, rounds=8, delay=0.5):
    """Click the X on every floating popup, until they are actually gone.

    Repeats because popups queue up: the Notice window can be followed by
    another one that only appears once the first is gone, so a single pass
    leaves the screen blocked.

    But it stops when clicking stops WORKING. A real sign-in reported closing
    the same popup - `S9502UP01` - twenty-three times, because each pass
    re-found the one before it and clicked it again. The count is checked
    after every pass: if it has not dropped twice running, the clicks are not
    closing anything and going round again only burns time. That run spent
    most of its 52 seconds here."""
    closed, stuck = [], 0
    for _ in range(rounds):
        found = find_child_popups(ws)
        before = found.get("count", 0)
        if not before:
            break
        for popup in found["popups"]:
            click_element_by_rect(ws, popup["x"], popup["y"])
            closed.append(popup["name"] or popup["id"])
            time.sleep(0.3)
        time.sleep(delay)

        if find_child_popups(ws).get("count", 0) >= before:
            stuck += 1
            if stuck >= 2:
                break
        else:
            stuck = 0
    return closed
