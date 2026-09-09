"""
Step 1: open the N-ERP portal and search for a T-code.

Navigates the Fiori shell to the portal, waits (by polling, never a fixed
sleep) for the "Search Program" field and "Go" button to render, types the
T-code and clicks Go with a real mouse event.

Usage:
    python search_tcode.py MB52
    python search_tcode.py MB51 --no-verify
"""
import json
import sys
import time

import cdp_common
from cdp_common import (
    NERP_URL, connect, evaluate, get_page_tab, click_element_by_rect,
    get_webgui_tab, read_selection_screen_state,
)


# Locating "Go" is the same problem as locating any SAP button (gotcha #9):
# textContent is inherited, so the shell container that WRAPS the button
# also has the text "Go" and, being first in document order, wins a naive
# `find`. Clicking its centre lands on empty space and nothing happens - a
# silent failure with no error anywhere. So candidates are filtered to
# visible, in-viewport, short-text elements and the smallest one wins,
# exactly as find_visible_leaf_by_text does for the WebGUI toolbar.
JS_FIND_SEARCH_UI = """
(function() {
    const isVisible = %s;
    let inputs = Array.from(document.querySelectorAll('input'));
    let searchInput = inputs.find(inp => inp.placeholder === 'Search Program') ||
                      inputs.find(inp => inp.placeholder &&
                                         inp.placeholder.toLowerCase().includes('search'));

    let candidates = Array.from(document.querySelectorAll('button, input[type="submit"], a, div, span'))
        .filter(el => {
            const t = (el.textContent || el.value || '').trim();
            if (t !== 'Go') return false;
            return isVisible(el);
        });
    candidates.sort((a, b) => {
        const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
        return (ra.width * ra.height) - (rb.width * rb.height);
    });

    if (!candidates.length)
        return JSON.stringify({ inputFound: !!searchInput, found: false });

    const r = candidates[0].getBoundingClientRect();
    return JSON.stringify({
        inputFound: !!searchInput,
        found: true,
        tag: candidates[0].tagName,
        id: candidates[0].id,
        x: r.left + r.width / 2,
        y: r.top + r.height / 2
    });
})()
""" % cdp_common.JS_IS_VISIBLE


def js_type_tcode(tcode):
    return """
    (function() {
        const value = %s;
        let inputs = Array.from(document.querySelectorAll('input'));
        let el = inputs.find(inp => inp.placeholder === 'Search Program') ||
                 inputs.find(inp => inp.placeholder &&
                                    inp.placeholder.toLowerCase().includes('search'));
        if (!el) return JSON.stringify({found: false});
        %s
        return JSON.stringify({found: true, value: el.value});
    })()
    """ % (json.dumps(tcode), cdp_common.JS_SET_VALUE)


def wait_for_search_ui(max_wait=240, poll_interval=2):
    """Poll until the portal's Go button has actually rendered.

    Gotcha #4/#24: the original code slept a flat 30s here. That is
    guessably wrong in both directions - the page has loaded in as little as
    4s, and has also needed well over 30s on a slow connection, where the
    fixed sleep turned into a hard failure. Polling exits the instant the
    button appears, so the generous cap costs nothing on the fast path.

    Each attempt reconnects with a FRESH websocket: holding one open and
    idle across a page load makes the next recv() time out (gotcha #4)."""
    deadline = time.time() + max_wait
    attempt = 0
    info = {"found": False}
    page_tab = None

    while time.time() < deadline:
        time.sleep(poll_interval)
        attempt += 1

        page_tab = get_page_tab()
        if page_tab is None:
            continue

        ws = None
        try:
            ws = connect(page_tab["webSocketDebuggerUrl"], timeout=10)
            info = evaluate(ws, JS_FIND_SEARCH_UI, timeout=10)
        except Exception:
            # Page still mid-navigation: connection refused, handshake
            # failure, or Runtime.enable timing out. Just retry.
            info = {"found": False}
        finally:
            if ws:
                ws.close()

        if info.get("found"):
            print(f"'Go' button appeared after ~{attempt * poll_interval}s.")
            return page_tab, info

        if attempt % 5 == 1:
            print(f"Still waiting... ({attempt * poll_interval}s elapsed, "
                  f"title: {page_tab.get('title')!r})")

    raise RuntimeError(
        f"'Go' button never appeared after ~{max_wait}s "
        f"(last page title: {(page_tab or {}).get('title')!r}, "
        f"url: {(page_tab or {}).get('url')!r}). "
        "The portal may be down, or navigation/SSO may have failed.")


def verify_screen_matches(tcode, max_wait=60, poll_interval=2):
    """Gotcha #22, which the original code documented but never enforced:
    after a forced Chrome restart, session-restore has silently reopened an
    unrelated screen from a previous run, and every later step then operated
    on a perfectly valid but completely wrong page with no error at all.

    Confirms the WebGUI target that came up actually belongs to the T-code
    just requested, by looking for the code in its title/body text. Returns
    (ok, detail). A False result is a warning, not a hard stop - some
    t-codes render a title that never repeats the code - but it gets
    surfaced instead of silently ignored."""
    deadline = time.time() + max_wait
    detail = "no WebGUI target appeared"
    needle = tcode.strip().upper()

    while time.time() < deadline:
        tab = get_webgui_tab()
        if tab:
            try:
                state = read_selection_screen_state(tab)
            except Exception as e:
                detail = f"could not read the WebGUI target ({e!r})"
                time.sleep(poll_interval)
                continue

            haystack = f"{tab.get('title', '')} {state.get('title', '')} {state.get('bodyText', '')}".upper()
            detail = (f"title={state.get('title')!r}, "
                      f"first text={state.get('bodyText', '')[:120]!r}")
            if needle in haystack:
                return True, detail
            if state.get("readyState") == "complete" and state.get("visibleInputCount", 0) > 1:
                # Fully rendered and still no mention of the t-code: report
                # what did come up rather than waiting out the whole cap.
                return False, detail
        time.sleep(poll_interval)

    return False, detail


def main(tcode, verify=True):
    print(f"Navigating to {NERP_URL} ...")
    try:
        page_tab = cdp_common.navigate_page(NERP_URL)
        print(f"Navigated the tab that was showing {page_tab.get('title')!r}.")
    except RuntimeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print("Waiting for the N-ERP portal's 'Go' button to appear "
          "(polling until it renders - no fixed timeout)...")
    try:
        page_tab, info = wait_for_search_ui()
    except RuntimeError as e:
        print(f"ERROR: {e}")
        cdp_common.screenshot_on_failure("nerp_portal_load")
        sys.exit(1)

    if not info.get("inputFound"):
        print("ERROR: the 'Search Program' field was not found even though "
              "'Go' rendered - the portal layout may have changed.")
        cdp_common.screenshot_on_failure("nerp_search_field")
        sys.exit(1)

    # Type the T-code once, immediately before clicking - the original code
    # retyped it on every poll iteration as a side effect of the same JS
    # that located the button, which made the wait loop mutate page state
    # dozens of times for no reason.
    ws = connect(page_tab["webSocketDebuggerUrl"], timeout=15)
    typed = evaluate(ws, js_type_tcode(tcode))
    print(f"Typed T-code: {typed}")

    print(f"Dispatching real mouse click at ({info['x']}, {info['y']})...")
    # element.click() does NOT work on this SAP UI5 (Fiori) page - the
    # framework ignores synthetic clicks on this button (gotcha #5).
    click_element_by_rect(ws, info["x"], info["y"])
    ws.close()

    print(f"Go clicked. '{tcode}' should now be opening.")

    if verify:
        ok, detail = verify_screen_matches(tcode)
        if ok:
            print(f"Verified: the open screen refers to {tcode} ({detail}).")
        else:
            print(f"WARNING: could not confirm the open screen belongs to {tcode} - {detail}. "
                  "If the next step behaves oddly, this is the reason: check the Chrome "
                  "window, and see SKILL.md gotcha #22.")

    print("The T-code's selection screen lives in a separate SAP WebGUI CDP "
          "target (not this page's DOM) - use execute_filters.py to fill "
          "filter fields and click Execute on it.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0] if args else "MB52", verify="--no-verify" not in sys.argv)
