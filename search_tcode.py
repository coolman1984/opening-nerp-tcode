import json
import sys
import time

from cdp_common import get_tabs, send, click_element_by_rect
import websocket

NERP_URL = "https://nerps.sec.samsung.net"


def js_locate_go_button(tcode):
    return """
    (function() {
        let inputs = Array.from(document.querySelectorAll('input'));
        let searchInput = inputs.find(inp => inp.placeholder === 'Search Program') ||
                           inputs.find(inp => inp.placeholder && inp.placeholder.toLowerCase().includes('search'));

        let buttons = Array.from(document.querySelectorAll('button, input[type="submit"], a'));
        let goButton = buttons.find(btn => (btn.textContent || btn.value || '').trim() === 'Go');

        if (searchInput) {
            searchInput.focus();
            searchInput.value = '%s';
            searchInput.dispatchEvent(new Event('input', { bubbles: true }));
            searchInput.dispatchEvent(new Event('change', { bubbles: true }));
        }

        if (goButton) {
            const r = goButton.getBoundingClientRect();
            if (r.width === 0 || r.height === 0) return JSON.stringify({ inputFound: !!searchInput, found: false });
            return JSON.stringify({
                inputFound: !!searchInput,
                found: true,
                x: r.left + r.width/2,
                y: r.top + r.height/2
            });
        }
        return JSON.stringify({ inputFound: !!searchInput, found: false });
    })()
    """ % tcode


def main(tcode):
    # Step 1: navigate (short-lived connection; closed before the wait below
    # so the socket doesn't go stale while idle)
    tabs = get_tabs()
    page_tab = next((t for t in tabs if t.get("type") == "page"), tabs[0])
    ws_url = page_tab["webSocketDebuggerUrl"]
    print(f"Connecting to: {page_tab.get('title')}")

    ws = websocket.create_connection(ws_url, timeout=15)
    send(ws, "Page.enable", msg_id=1)
    print(f"Navigating to {NERP_URL} ...")
    send(ws, "Page.navigate", {"url": NERP_URL}, msg_id=2)
    ws.close()

    # Step 2: poll until the "Go" button actually appears, rather than
    # guessing a fixed wait duration. Page-load time varies a lot (chatbot
    # widget init, network conditions - sometimes noticeably slow), and any
    # fixed sleep is either wastefully long or, worse, sometimes too short
    # and fails outright. The loop below exits the instant the button is
    # detected, so a generous safety cap costs nothing on the fast path and
    # is what actually matters when the network/page is slow. It also
    # tolerates the page still being mid-navigation early on (Runtime.enable
    # timing out / connection refused) by simply retrying the connection.
    print("Waiting for the N-ERP portal's 'Go' button to appear (no fixed timeout - polling until it renders)...")
    info = {"found": False}
    max_attempts = 120  # ~4 minutes wall-clock ceiling at 2s/attempt, only reached if something is genuinely broken
    for attempt in range(max_attempts):
        time.sleep(2)

        tabs = get_tabs()
        page_tab = next(
            (t for t in tabs if t.get("type") == "page" and "nerps" in t.get("url", "")),
            None,
        ) or next((t for t in tabs if t.get("type") == "page"), tabs[0])
        ws_url = page_tab["webSocketDebuggerUrl"]

        ws2 = None
        try:
            ws2 = websocket.create_connection(ws_url, timeout=10)
            send(ws2, "Runtime.enable", msg_id=1, timeout=10)
            resp = send(ws2, "Runtime.evaluate", {
                "expression": js_locate_go_button(tcode), "returnByValue": True
            }, msg_id=2, timeout=10)
            info = json.loads(resp["result"]["result"]["value"])
        except TimeoutError:
            info = {"found": False}
        finally:
            if ws2:
                ws2.close()

        if info.get("found"):
            print(f"'Go' button appeared after ~{(attempt + 1) * 2}s.")
            break

        if attempt % 5 == 0:
            print(f"Still waiting... ({(attempt + 1) * 2}s elapsed, title: {page_tab.get('title')})")
    else:
        print(f"ERROR: 'Go' button never appeared after ~{max_attempts * 2}s. "
              "Portal may be down or navigation failed.")
        sys.exit(1)

    print(f"Dispatching real mouse click at ({info['x']}, {info['y']})...")

    # IMPORTANT: element.click() does NOT reliably work on this SAP UI5
    # (Fiori) page - the framework ignores synthetic .click() calls on this
    # button. A real mouse event sequence via the CDP Input domain is
    # required instead.
    ws2 = websocket.create_connection(page_tab["webSocketDebuggerUrl"], timeout=15)
    send(ws2, "Runtime.enable", msg_id=1)
    click_element_by_rect(ws2, info["x"], info["y"], msg_id_start=4)

    print(f"Go button clicked. '{tcode}' search should now be executed.")
    print("The T-code's selection screen loads in a separate SAP WebGUI CDP")
    print("target (not this page's DOM) - use execute_filters.py to fill")
    print("filter fields and click Execute on it.")
    ws2.close()


if __name__ == "__main__":
    tcode = sys.argv[1] if len(sys.argv) > 1 else "MB52"
    main(tcode)
