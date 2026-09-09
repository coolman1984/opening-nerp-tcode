"""
Step 2: fill selection-screen filter fields on the currently-open SAP WebGUI
screen and click Execute.

Usage:
    python execute_filters.py "Material Number=SM-A137FLBHMEB" "Plant=P703"
    python execute_filters.py            # no filters, just click Execute

Fields are matched by their DOM `title` attribute (case-insensitive
substring), which is the SAP field label ("Material Number", "Plant",
"Storage Location") and stays stable across t-codes and sessions - unlike
the dynpro-generated element `id` (e.g. "M0:46:::2:34"), which is
regenerated per screen layout and must never be hardcoded.
"""
import json
import sys

import cdp_common
from cdp_common import (
    connect, evaluate, click_element_by_rect, wait_for_busy_indicator_clear,
    wait_for_selection_screen_ready,
)


def js_fill_filters(filters):
    return """
    (function() {
        const filters = %s;
        let inputs = Array.from(document.querySelectorAll('input[type="text"], input:not([type])'));
        let results = [];
        for (const [label, value] of Object.entries(filters)) {
            const lower = label.toLowerCase();
            let el = inputs.find(inp => (inp.title || '').toLowerCase().includes(lower));
            if (!el) {
                results.push({label: label, found: false});
                continue;
            }
            %s
            el.dispatchEvent(new Event('blur', { bubbles: true }));
            results.push({label: label, found: true, elementId: el.id, value: el.value});
        }
        return JSON.stringify(results);
    })()
    """ % (json.dumps(filters), cdp_common.JS_SET_VALUE)


# Locate the primary "Execute Emphasized" (F8) toolbar button.
#
# This is gotcha #9 applied to Execute, and the original version had the bug
# it warns about: it matched on `/execute/i.test(el.textContent)` with no
# visibility or length filter, so any ANCESTOR containing the button also
# matched - and, being earlier in document order, won. Clicking the centre
# of a whole screen container lands on empty space, so Execute was never
# pressed and the run then waited for results that were never coming, with
# no error to explain it.
#
# So: prefer the precise `(F8)` title, fall back to SHORT visible text
# mentioning execute (a container's text is long, a button's is not), and
# among whatever survives take the smallest box.
JS_LOCATE_EXECUTE = """
(function() {
    const isVisible = %s;
    const area = el => { const r = el.getBoundingClientRect(); return r.width * r.height; };
    const all = Array.from(document.querySelectorAll(
        'div, button, a, span, input[type="button"], input[type="submit"]'));

    let pool = all.filter(el => /\\(F8\\)/.test(el.title || '') && isVisible(el));
    if (!pool.length) {
        pool = all.filter(el => {
            const t = (el.textContent || el.value || '').trim();
            return t.length > 0 && t.length <= 40 && /execute/i.test(t) && isVisible(el);
        });
    }
    if (!pool.length) return JSON.stringify({found: false});

    pool.sort((a, b) => area(a) - area(b));
    // "Execute Emphasized" is the primary action; "Execute and Print" and
    // friends are variants that must not be preferred over it.
    const emphasized = pool.filter(el =>
        /execute emphasized/i.test((el.textContent || '').trim()));
    const btn = (emphasized.length ? emphasized : pool)[0];

    const r = btn.getBoundingClientRect();
    return JSON.stringify({found: true, id: btn.id, title: btn.title,
                           text: (btn.textContent || '').trim().slice(0, 40),
                           x: r.left + r.width/2, y: r.top + r.height/2});
})()
""" % cdp_common.JS_IS_VISIBLE


def list_available_fields(ws):
    """Report every visible input's title, so a mistyped/guessed field label
    produces an actionable message instead of a bare 'not found'."""
    js = """
    (function() {
        const isVisible = %s;
        let inputs = Array.from(document.querySelectorAll('input[type="text"], input:not([type])'));
        return JSON.stringify(inputs.filter(isVisible)
            .map(i => i.title || i.placeholder || '(untitled)'));
    })()
    """ % cdp_common.JS_IS_VISIBLE
    try:
        return evaluate(ws, js)
    except Exception:
        return []


def main(filters, strict=False):
    # Wait for the selection screen to be rendered and interactive, not just
    # for its CDP target to exist (gotcha #16): the target registers a beat
    # before its DOM has real content, which used to let this step race onto
    # a blank document and find no fields at all. Kept here rather than only
    # in the orchestrator so direct invocation is protected too.
    print("Waiting for the selection/filter screen to be ready...")
    try:
        webgui_tab = wait_for_selection_screen_ready()
    except RuntimeError as e:
        print(f"ERROR: {e}")
        cdp_common.screenshot_on_failure("nerp_selection_screen")
        sys.exit(1)

    print(f"Connected to WebGUI: {webgui_tab.get('url')}")
    ws = connect(webgui_tab["webSocketDebuggerUrl"], timeout=20)

    try:
        if filters:
            fill_results = evaluate(ws, js_fill_filters(filters))
            print("Fill results:", fill_results)

            missing = [r["label"] for r in fill_results if not r["found"]]
            if missing:
                available = list_available_fields(ws)
                print(f"WARNING: could not find fields for: {missing}")
                print(f"         Field labels actually on this screen: {available}")
                if strict:
                    print("ERROR: --strict was requested and some filters did not match. "
                          "Nothing was executed.")
                    sys.exit(1)

        info = evaluate(ws, JS_LOCATE_EXECUTE)
        print("Execute button:", info)

        if not info.get("found"):
            print("ERROR: Execute button not found on this screen.")
            cdp_common.screenshot_on_failure("nerp_execute_button")
            sys.exit(1)

        click_element_by_rect(ws, info["x"], info["y"])
        print("Execute clicked. Waiting for the result page to finish loading "
              "(polling the busy indicator, not a fixed delay)...")

        # Do not hand control back to the caller (e.g. export_to_excel) until
        # the results have actually rendered. Guessing a sleep here is the
        # same duration-tuned mistake already solved for the export dialogs
        # (gotchas #23-25). If this raises, the WebGUI target itself was
        # replaced by a larger transition - the caller re-fetches it anyway,
        # so that is not fatal.
        try:
            if not wait_for_busy_indicator_clear(ws):
                print("WARNING: the busy indicator did not clear within the wait window - "
                      "the result page may still be loading. Proceeding anyway.")
        except Exception as e:
            print(f"Busy-indicator check ended early ({e!r}) - the screen likely changed "
                  "significantly; proceeding.")
    finally:
        ws.close()


def parse_filter_args(argv):
    filters = {}
    for arg in argv:
        if arg.startswith("--"):
            continue
        if "=" in arg:
            key, value = arg.split("=", 1)
            filters[key.strip()] = value.strip()
        else:
            print(f"WARNING: ignoring argument {arg!r} - expected 'Label=Value'.")
    return filters


if __name__ == "__main__":
    main(parse_filter_args(sys.argv[1:]), strict="--strict" in sys.argv)
