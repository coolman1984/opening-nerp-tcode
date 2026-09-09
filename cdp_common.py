import json
import time
import urllib.request
import websocket

CDP_PORT = 9444


def get_tabs():
    req = urllib.request.Request(f"http://localhost:{CDP_PORT}/json/list")
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode())


def send(ws, method, params=None, msg_id=1, timeout=20):
    cmd = {"id": msg_id, "method": method, "params": params or {}}
    ws.send(json.dumps(cmd))
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = json.loads(ws.recv())
        except websocket.WebSocketTimeoutException:
            continue
        if resp.get("id") == msg_id:
            return resp
    raise TimeoutError(f"No response for {method}")


def connect_with_retry(ws_url_getter, attempts=3, backoff=5, timeout=20):
    """ws_url_getter is a zero-arg callable returning a fresh ws_url each
    attempt (tab lists can change between retries)."""
    last_err = None
    for attempt in range(attempts):
        ws_url, label = ws_url_getter()
        print(f"Connecting to: {label} (attempt {attempt + 1})")
        ws = None
        try:
            ws = websocket.create_connection(ws_url, timeout=timeout)
            send(ws, "Runtime.enable", msg_id=1, timeout=timeout)
            return ws
        except TimeoutError as e:
            last_err = e
            print(f"Attempt {attempt + 1} timed out ({e}); waiting {backoff}s and retrying...")
            if ws:
                ws.close()
            time.sleep(backoff)
    raise last_err


def click_element_by_rect(ws, x, y, msg_id_start=90):
    """Real mouse event simulation. Required because element.click() is
    ignored by both the SAP UI5/Fiori shell buttons and the classic WebGUI
    toolbar buttons (which are DIVs wired to mousedown/mouseup, not real
    <button> click handlers)."""
    send(ws, "Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y}, msg_id=msg_id_start)
    send(ws, "Input.dispatchMouseEvent", {
        "type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1
    }, msg_id=msg_id_start + 1)
    time.sleep(0.1)
    send(ws, "Input.dispatchMouseEvent", {
        "type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1
    }, msg_id=msg_id_start + 2)


def dispatch_key_combo(ws, key, code, vk, ctrl=False, shift=False, alt=False, msg_id_start=80):
    """Dispatch a keyboard shortcut (e.g. Ctrl+Shift+F7) to whichever target
    ws is connected to. modifiers bitmask: Alt=1, Ctrl=2, Meta=4, Shift=8."""
    mods = (1 if alt else 0) | (2 if ctrl else 0) | (8 if shift else 0)
    params = {
        "modifiers": mods,
        "key": key,
        "code": code,
        "windowsVirtualKeyCode": vk,
        "nativeVirtualKeyCode": vk,
    }
    send(ws, "Input.dispatchKeyEvent", {"type": "rawKeyDown", **params}, msg_id=msg_id_start)
    send(ws, "Input.dispatchKeyEvent", {"type": "keyUp", **params}, msg_id=msg_id_start + 1)


def find_visible_leaf_by_text(ws, *texts, max_len=30, msg_id=95):
    """Find a small, visible leaf-ish element whose trimmed text exactly
    matches one of `texts`. SAP WebGUI buttons are <div>s nested several
    layers deep inside toolbars; naive querySelector text matches often hit
    large ancestor containers (whole toolbars/pages) instead of the actual
    clickable element, so this filters by visible bounding box AND short
    text length to find the real button. Returns list of candidate dicts
    with tag/id/text/x/y, smallest (most specific) element first.

    Also requires the element's position to be within the viewport, not
    just non-zero size: some dropdown/menu widgets (e.g. the toolbar
    "Export" icon's dropdown) render off-screen first to measure their
    size (seen at y ~ -99984) before repositioning into view, so a
    width/height-only check can match and click a not-yet-visible
    placeholder that silently does nothing."""
    texts_json = json.dumps(list(texts))
    js = """
    (function() {
        const texts = %s;
        let all = Array.from(document.querySelectorAll('*'));
        let candidates = all.filter(el => {
            let t = (el.textContent || '').trim();
            if (t.length === 0 || t.length > %d) return false;
            const r = el.getBoundingClientRect();
            if (r.width === 0 || r.height === 0) return false;
            if (r.bottom <= 0 || r.right <= 0) return false;
            if (r.top >= window.innerHeight || r.left >= window.innerWidth) return false;
            return texts.some(needle => t === needle);
        });
        candidates.sort((a, b) => {
            const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
            return (ra.width * ra.height) - (rb.width * rb.height);
        });
        return JSON.stringify(candidates.map(el => {
            const r = el.getBoundingClientRect();
            return { tag: el.tagName, id: el.id, text: el.textContent.trim(),
                     x: r.left + r.width/2, y: r.top + r.height/2 };
        }));
    })()
    """ % (texts_json, max_len)
    resp = send(ws, "Runtime.evaluate", {"expression": js, "returnByValue": True}, msg_id=msg_id)
    return json.loads(resp["result"]["result"]["value"])


def wait_for_busy_indicator_clear(ws, max_wait=120, poll_interval=0.5, grace_checks=4):
    """Poll for the generic SAP WebGUI busy/loading indicator
    ('hiddenLoadingToolbarButton', title "Click to stop long-running
    application" - part of the generic shell chrome, present regardless of
    which t-code/report is open, not something specific to one screen) to
    appear and then disappear after clicking Execute/OK/etc.

    Same poll-until-detected-with-generous-cap principle as the export
    dialog waits: don't guess a fixed sleep duration for "processing
    finished", since a large dataset can take much longer than a small one
    and there's no way to know from the outside. The loop exits immediately
    once done, so a generous cap costs nothing when processing is fast.

    Handles two cases:
    - The indicator becomes visible (busy) then invisible again (done) -
      the common case for anything that takes long enough to notice.
    - The indicator never becomes visible at all (operation was faster than
      our poll interval) - after `grace_checks` polls with no busy state
      ever observed, this is treated as already done rather than waiting
      out the full cap for a busy state that was never going to appear.

    Returns True if a settled (not-busy) state was observed, False if
    max_wait elapsed while still busy (caller should decide whether that's
    fatal - it may just mean processing is still legitimately ongoing)."""
    js_busy = """
    (function() {
        let el = document.getElementById('hiddenLoadingToolbarButton');
        if (!el) return JSON.stringify({busy: false});
        const r = el.getBoundingClientRect();
        return JSON.stringify({busy: r.width > 0 && r.height > 0});
    })()
    """
    seen_busy = False
    attempts = max(1, int(max_wait / poll_interval))
    for i in range(attempts):
        resp = send(ws, "Runtime.evaluate", {"expression": js_busy, "returnByValue": True}, msg_id=97)
        state = json.loads(resp["result"]["result"]["value"])
        if state.get("busy"):
            seen_busy = True
        elif seen_busy or i >= grace_checks:
            return True
        time.sleep(poll_interval)
    return False


def wait_for_selection_screen_ready(max_wait=120, poll_interval=1.5):
    """Poll until the SAP WebGUI selection/filter screen is not just present
    as a CDP target but actually rendered and interactive.

    The bug this fixes: get_webgui_tab() finding the iframe TARGET only
    confirms CDP has registered it - the SAP content inside can still be
    mid-load for a bit afterward (blank/loading document), so a caller that
    proceeds the instant the target exists can connect successfully and
    still find zero (or the wrong) filter inputs, or an Execute button that
    isn't there/clickable yet. This confirms actual DOM readiness, not just
    target existence, by re-fetching the live target fresh each attempt
    (get_webgui_tab() already picks the candidate with the most inputs when
    there are several, but even the sole candidate can be blank right after
    Go is clicked) and checking, inside its DOM:
      - document.readyState === 'complete'
      - at least one visible, enabled filter input exists
      - a visible, non-disabled Execute button exists

    Same poll-until-detected-with-generous-cap principle as the other waits
    in this skill (search_tcode's Go-button wait, wait_for_busy_indicator_clear)
    - no fixed sleep; the loop exits the instant the screen is actually
    ready, and the cap is generous so slow loads are tolerated rather than
    guessed at.

    Returns the ready webgui tab dict on success. Raises RuntimeError with a
    single diagnostic message (elapsed time, target url/title, visible input
    count/titles, whether Execute was found) on timeout."""
    js_ready = """
    (function() {
        let inputs = Array.from(document.querySelectorAll('input[type="text"], input:not([type])'));
        let visibleInputs = inputs.filter(inp => {
            if (inp.disabled || inp.readOnly) return false;
            const r = inp.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 &&
                   r.top < window.innerHeight && r.left < window.innerWidth;
        });

        let execCandidates = Array.from(document.querySelectorAll('div, button, a'))
            .filter(el => /execute/i.test(el.textContent || '') || /\\(F8\\)/.test(el.title || ''));
        let execBtn = execCandidates.find(el => {
            if (el.disabled) return false;
            if ((el.getAttribute('aria-disabled') || '').toLowerCase() === 'true') return false;
            if (/disabled/i.test(el.className || '')) return false;
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 &&
                   r.top < window.innerHeight && r.left < window.innerWidth;
        });

        return JSON.stringify({
            readyState: document.readyState,
            visibleInputCount: visibleInputs.length,
            visibleInputTitles: visibleInputs.map(i => i.title || i.placeholder || '(untitled)').slice(0, 20),
            executeFound: !!execBtn
        });
    })()
    """

    start = time.time()
    last_tab = None
    last_state = {"readyState": "(no target found yet)", "visibleInputCount": 0,
                  "visibleInputTitles": [], "executeFound": False}

    attempts = max(1, int(max_wait / poll_interval))
    for _ in range(attempts):
        tab = get_webgui_tab()
        if tab:
            last_tab = tab
            ws = None
            try:
                ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=10)
                send(ws, "Runtime.enable", msg_id=1, timeout=10)
                resp = send(ws, "Runtime.evaluate",
                            {"expression": js_ready, "returnByValue": True},
                            msg_id=2, timeout=10)
                last_state = json.loads(resp["result"]["result"]["value"])
                if (last_state.get("readyState") == "complete"
                        and last_state.get("visibleInputCount", 0) > 0
                        and last_state.get("executeFound")):
                    return tab
            except Exception:
                pass
            finally:
                if ws:
                    ws.close()
        time.sleep(poll_interval)

    elapsed = time.time() - start
    raise RuntimeError(
        "Selection screen never became ready after "
        f"{elapsed:.1f}s. Target url={(last_tab or {}).get('url', '(none found)')!r} "
        f"title={(last_tab or {}).get('title', '(none)')!r}. "
        f"documentReadyState={last_state.get('readyState')}, "
        f"visible inputs={last_state.get('visibleInputCount', 0)} "
        f"titles={last_state.get('visibleInputTitles', [])}, "
        f"Execute button found={last_state.get('executeFound', False)}."
    )


def get_webgui_tab():
    """The classic SAP selection-screen / data-list content (field inputs,
    Execute button) renders in a separate cross-origin CDP target
    (/sap/bc/gui/sap/its/webgui), NOT in the main Fiori shell page's DOM.
    This finds that target.

    Two gotchas:
    - There's also an AppDynamics/adrum monitoring wrapper iframe whose URL
      is a URL-ENCODED string that happens to contain "webgui" as a
      substring too (e.g. ".../controller/adrum-xd...html#https%3A%2F%2F...
      %2Fwebgui%3B..."), so a naive "webgui" substring match picks the wrong
      iframe and every field/button lookup inside it then fails silently
      (0 inputs found). Exclude anything with "adrum" in the URL.
    - Opening multiple T-codes in the same browser session (even after
      re-navigating the Fiori shell) can leave STALE webgui iframe targets
      around from previous T-codes instead of replacing them - the backend
      SAP GUI session can spawn additional windows that don't get torn down
      by just reloading the Fiori page. Position in the tabs list is NOT a
      reliable indicator of which one is current - in practice the stale one
      has shown up both before and after the real one. Instead, connect to
      each real candidate and count its text inputs; the stale ones are
      near-blank placeholder documents (title "SAP", ~1 input for the
      transaction-code box only) while the live one has the actual
      selection-screen/list fields. Pick whichever has the most inputs."""
    tabs = get_tabs()
    candidates = [
        t for t in tabs
        if t.get("type") == "iframe"
        and "webgui" in t.get("url", "").lower()
        and "adrum" not in t.get("url", "").lower()
    ]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    best_tab, best_count = None, -1
    for tab in candidates:
        try:
            ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=10)
            send(ws, "Runtime.enable", msg_id=1, timeout=10)
            resp = send(ws, "Runtime.evaluate", {
                "expression": "document.querySelectorAll('input[type=\"text\"]').length",
                "returnByValue": True,
            }, msg_id=2, timeout=10)
            ws.close()
            count = resp["result"]["result"]["value"]
        except Exception:
            count = -1
        if count > best_count:
            best_tab, best_count = tab, count

    return best_tab if best_tab is not None else candidates[0]
