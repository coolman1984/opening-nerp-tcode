"""
Fill selection-screen filter fields on the currently-open SAP WebGUI screen
(e.g. after opening a T-code with search_tcode.py) and click Execute.

Usage:
    python execute_filters.py "Material Number=SM-A137FLBHMEB" "Plant=P703"
    python execute_filters.py            # no filters, just click Execute

Fields are matched by their DOM `title` attribute (case-insensitive
substring), which corresponds to the SAP field label (e.g. "Material
Number", "Plant", "Storage Location") and is stable across t-codes/sessions,
unlike the dynpro-generated element `id` (e.g. "M0:46:::2:34") which can
shift between screens.
"""
import json
import sys
import time

from cdp_common import (
    send, click_element_by_rect, wait_for_busy_indicator_clear,
    wait_for_selection_screen_ready,
)
import websocket


def main(filters):
    # Wait for the selection screen to actually be rendered and interactive
    # (not just for its CDP target to exist) before touching it - the target
    # can register a beat before its DOM has any real content, which used to
    # let this step race ahead onto a blank/loading document and fail to
    # find fields or the Execute button. Also covers manual/direct
    # invocation of this script, not just the orchestrator.
    print("Waiting for the selection/filter screen to be ready...")
    try:
        webgui_tab = wait_for_selection_screen_ready()
    except RuntimeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print(f"Connected to WebGUI: {webgui_tab.get('url')}")
    ws = websocket.create_connection(webgui_tab["webSocketDebuggerUrl"], timeout=20)
    send(ws, "Runtime.enable", msg_id=1)

    if filters:
        js_fill = """
        (function() {
            const filters = %s;
            let inputs = Array.from(document.querySelectorAll('input[type="text"], input:not([type])'));
            let results = [];
            for (const [label, value] of Object.entries(filters)) {
                const lower = label.toLowerCase();
                let el = inputs.find(inp => (inp.title || '').toLowerCase().includes(lower));
                if (!el) {
                    results.push({label, found: false});
                    continue;
                }
                el.focus();
                el.value = value;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('blur', { bubbles: true }));
                results.push({label, found: true, elementId: el.id, value: el.value});
            }
            return JSON.stringify(results);
        })()
        """ % json.dumps(filters)

        resp = send(ws, "Runtime.evaluate", {"expression": js_fill, "returnByValue": True}, msg_id=2)
        fill_results = json.loads(resp["result"]["result"]["value"])
        print("Fill results:", fill_results)

        missing = [r["label"] for r in fill_results if not r["found"]]
        if missing:
            print(f"WARNING: could not find fields for: {missing}")

    # Find the Execute button. Prefer the primary "Execute Emphasized" (F8)
    # toolbar button over variants like "Execute and Print".
    js_locate = """
    (function() {
        let candidates = Array.from(document.querySelectorAll('div, button, a'))
            .filter(el => /execute/i.test(el.textContent || '') || /\\(F8\\)/.test(el.title || ''));

        let btn = candidates.find(el => /execute emphasized/i.test(el.textContent || '')) ||
                  candidates.find(el => /\\(F8\\)/.test(el.title || '')) ||
                  candidates[0];

        if (!btn) return JSON.stringify({found: false});
        const r = btn.getBoundingClientRect();
        return JSON.stringify({found: true, id: btn.id, x: r.left + r.width/2, y: r.top + r.height/2});
    })()
    """
    resp2 = send(ws, "Runtime.evaluate", {"expression": js_locate, "returnByValue": True}, msg_id=3)
    info = json.loads(resp2["result"]["result"]["value"])
    print("Execute button:", info)

    if not info.get("found"):
        print("ERROR: Execute button not found.")
        ws.close()
        sys.exit(1)

    click_element_by_rect(ws, info["x"], info["y"], msg_id_start=10)
    print("Execute clicked! Waiting for the result data page to finish loading "
          "(polling the busy indicator, not a fixed delay)...")

    # Don't return control to the caller (e.g. export_to_excel.py) until the
    # results have actually rendered - a large query can take a while, and
    # guessing a fixed sleep here is exactly the "duration-tuned timeout"
    # problem already solved for the export dialogs (see SKILL.md gotchas
    # #23-24). If this raises (e.g. the connection drops because the WebGUI
    # target itself got replaced by a bigger transition), that's fine - it
    # just means something changed enough that the caller should re-fetch
    # get_webgui_tab() anyway, so don't treat it as fatal here.
    try:
        settled = wait_for_busy_indicator_clear(ws)
        if not settled:
            print("WARNING: busy indicator did not clear within the wait window - "
                  "the result page may still be loading. Proceeding anyway.")
    except Exception as e:
        print(f"Busy-indicator check ended early ({e}) - likely means the screen "
              "changed significantly; proceeding.")

    ws.close()


if __name__ == "__main__":
    filters = {}
    for arg in sys.argv[1:]:
        if "=" in arg:
            k, v = arg.split("=", 1)
            filters[k] = v
    main(filters)
