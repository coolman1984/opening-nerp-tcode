"""Low-level Chrome DevTools Protocol (CDP) transport for standalone G-MES.

Forked from the shared `cdp_common.py` used by both N-ERP and G-MES in the
original repo layout (HISTORY.md, Phase 3 of the standalone-gmes.exe
migration) - this package deliberately does not import cdp_common, so
N-ERP's own automation stays completely untouched and the two never share
a module again. Only the transport primitives G-MES's own code actually
calls (confirmed by grepping every gmes_*.py file's cdp_common usage
before forking) are copied here.

Two facts this project has already paid to learn, preserved verbatim:

  * The corporate proxy intercepts even http://localhost traffic unless
    NO_PROXY/no_proxy explicitly exempt it.
  * On Windows, "localhost" resolves to ::1 first and Chrome's DevTools
    endpoint listens on IPv4 only, so every call through the name pays a
    150x penalty (2.05s vs 0.013s, measured) waiting for the IPv6 attempt
    to fail first. Always address 127.0.0.1 directly, and rewrite the
    websocket URLs Chrome hands back the same way.
"""
import itertools
import json
import os
import sys
import time
import urllib.request

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

# A dedicated env var, not NERP_CDP_PORT: the original cdp_common.py's
# CDP_PORT was shared by both automations, so setting NERP_CDP_PORT to run
# two N-ERP sessions side by side silently changed which port G-MES also
# tried to use. GMES_CDP_PORT decouples that; the default (9444) is
# unchanged so nobody who never touched the env var sees any difference.
CDP_PORT = int(os.environ.get("GMES_CDP_PORT", "9444"))

CDP_HOST = "127.0.0.1"

_PROXY_BYPASS = "localhost,127.0.0.1,::1"


def apply_proxy_bypass():
    """HTTP_PROXY/HTTPS_PROXY point at a corporate gateway with no localhost
    exception, so even http://localhost:9444 is routed through it and
    blocked. urllib reads these env vars at call time, so setting them in
    this process is enough - but it must happen before the first request.
    Idempotent; called at import time below."""
    for name in ("NO_PROXY", "no_proxy"):
        current = os.environ.get(name, "")
        if all(host in current for host in ("localhost", "127.0.0.1")):
            continue
        os.environ[name] = _PROXY_BYPASS if not current else f"{current},{_PROXY_BYPASS}"


apply_proxy_bypass()


try:
    import websocket  # websocket-client
except ImportError:  # pragma: no cover - environment guard
    sys.stderr.write(
        "ERROR: the 'websocket-client' package is required.\n"
        f"Install it with:  {sys.executable} -m pip install websocket-client\n"
    )
    raise


_msg_ids = itertools.count(1)


def next_id():
    """Monotonic CDP message ids, shared across every helper on a socket so
    two overlapping calls can never read each other's reply."""
    return next(_msg_ids)


def ipv4(url):
    """Rewrite a DevTools URL to the IPv4 literal (see module docstring)."""
    if not url:
        return url
    return url.replace("://localhost:", f"://{CDP_HOST}:")


def get_tabs(port=None, timeout=5):
    port = port or CDP_PORT
    req = urllib.request.Request(f"http://{CDP_HOST}:{port}/json/list")
    # Explicit empty ProxyHandler: NO_PROXY covers urlopen's default opener,
    # but this also survives a caller that installed its own opener earlier.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as response:
        return json.loads(response.read().decode())


def cdp_is_up(port=None, timeout=2):
    try:
        get_tabs(port=port, timeout=timeout)
        return True
    except Exception:
        return False


def send(ws, method, params=None, msg_id=None, timeout=20):
    """Send one CDP command and return its matching reply, discarding the
    event traffic (Runtime.consoleAPICalled etc.) that arrives in between."""
    msg_id = next_id() if msg_id is None else msg_id
    ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = json.loads(ws.recv())
        except websocket.WebSocketTimeoutException:
            continue
        if resp.get("id") == msg_id:
            return resp
    raise TimeoutError(f"No response for {method}")


def evaluate(ws, js, timeout=20):
    """Run JS that returns a JSON string, and give back the parsed object.

    Always passes returnByValue (several original call sites omitted it and
    only worked by accident, since primitives are inlined in the reply) and
    raises a named RuntimeError on a JS exception instead of a bare
    KeyError deep in the caller."""
    resp = send(ws, "Runtime.evaluate",
                {"expression": js, "returnByValue": True}, timeout=timeout)
    result = resp.get("result", {})
    if "exceptionDetails" in result:
        detail = result["exceptionDetails"]
        text = (detail.get("exception", {}).get("description")
                or detail.get("text") or "unknown JS error")
        raise RuntimeError(f"JS evaluation failed: {text}")
    value = result.get("result", {}).get("value")
    if value is None:
        raise RuntimeError("JS evaluation returned no value (expected a JSON string)")
    return json.loads(value)


def connect(ws_url, timeout=20, enable_runtime=True):
    ws = websocket.create_connection(ipv4(ws_url), timeout=timeout)
    if enable_runtime:
        send(ws, "Runtime.enable", timeout=timeout)
    return ws


def get_page_tab(prefer_url_substring=None, port=None):
    """Pick the top-level page target to drive.

    The original cdp_common.get_page_tab() defaulted prefer_url_substring
    to "nerps" for N-ERP's own use; every G-MES call site (gmes_common.py's
    gmes_tab(), gmes_connect.py) always passes None explicitly, so that is
    the default here instead - no behavior change for G-MES, just dropping
    a leftover N-ERP-specific default value.

    Falls back to any page target when no preference matches. A long-lived
    session can accumulate duplicate tabs, so this is not simply "the first
    page target" - callers needing a specific G-MES tab use gmes_tab()
    (nexacro/), which layers Nexacro-specific matching on top of this."""
    tabs = get_tabs(port=port)
    pages = [t for t in tabs if t.get("type") == "page"]
    if not pages:
        return tabs[0] if tabs else None
    if prefer_url_substring:
        preferred = [t for t in pages if prefer_url_substring in t.get("url", "")]
        if preferred:
            return preferred[0]
    return pages[0]


def navigate_page(url, port=None, timeout=15):
    """Point the top-level page target at `url` on a short-lived connection.

    The socket is opened and closed around the navigation on purpose:
    holding one open and idle across a page load makes the next recv()
    time out. The Page.navigate acknowledgement is treated as optional -
    navigating away from a chrome:// page is a cross-process navigation
    that can tear the DevTools session down before the reply is written,
    surfacing as a bare ConnectionResetError. By then the navigation has
    already been issued, and the caller polls for the loaded page
    regardless, so a lost ack is not a failure."""
    tab = get_page_tab(prefer_url_substring=None, port=port)
    if tab is None:
        raise RuntimeError("No page target available. Is Chrome running with CDP enabled?")

    ws = None
    try:
        ws = websocket.create_connection(ipv4(tab["webSocketDebuggerUrl"]),
                                         timeout=timeout)
        send(ws, "Page.enable", timeout=timeout)
        send(ws, "Page.navigate", {"url": url}, timeout=timeout)
    except (OSError, TimeoutError, websocket.WebSocketException) as e:
        print(f"(no navigate acknowledgement: {e!r} - the navigation was still "
              "issued; the poll that follows confirms the load)")
    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass
    return tab
