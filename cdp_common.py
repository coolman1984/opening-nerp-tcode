"""
The Chrome DevTools Protocol (CDP) transport layer, shared by every G-MES
tool in this project.

Everything here exists because of a concrete failure observed against a real
corporate system. The short version:

  * The corporate proxy swallows localhost traffic unless NO_PROXY is set,
    so every local CDP call comes back "403 URLBlocked" without it.
  * Chrome 136+ silently IGNORES --remote-debugging-port when --user-data-dir
    is the real profile directory, and rejects the DevTools websocket
    entirely without --remote-allow-origins=*. Hence the profile copy
    (GMES_SKILL.md gotcha #1) and the flag.
  * element.click() is ignored by Nexacro's controls - they are <div>s wired
    to mousedown/mouseup with no click handler to invoke - so clicks must be
    real Input.dispatchMouseEvent sequences.
  * A websocket held open and idle across a page load goes stale; the next
    recv() times out. Close it, wait with no socket open, reconnect fresh.
  * Nothing about render timing is predictable, so every wait polls until the
    thing is actually there, with a generous safety cap - never a tuned fixed
    sleep (CLAUDE.md 3.1).

This file was shared with N-ERP until HISTORY.md Phase 72. Its N-ERP-only
half - the SAP WebGUI iframe resolver, the selection-screen readiness poll,
the busy-indicator wait, the text/title element finders and the throwaway-
profile launcher - was removed there, verified unused by any G-MES file
first. `tests/test_cdp_common.py` guards what remains.
"""
import base64
import itertools
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request


# --------------------------------------------------------------------------
# Configuration (single source of truth - do not re-declare these elsewhere)
# --------------------------------------------------------------------------

# The env var keeps its historical name. It is the live knob for this
# engine - renaming it would break any machine or scheduled task that
# already sets it, for a cosmetic gain - so it is recorded here rather than
# changed (HISTORY.md Phase 72.4). Accepting a GMES_-prefixed alias
# alongside it would be additive and safe, if that is ever wanted.
CDP_PORT = int(os.environ.get("NERP_CDP_PORT", "9444"))

# Always address the DevTools endpoint by its IPv4 literal, never by name.
# On Windows "localhost" resolves to ::1 first; Chrome listens on IPv4 only,
# so every call waits for the IPv6 attempt to fail before falling back.
# Measured: 2.05s per /json/list via "localhost" against 0.013s via
# 127.0.0.1 - a 150x difference paid by every target lookup and every
# websocket connect, which is most of what these tools do.
CDP_HOST = "127.0.0.1"

_PROXY_BYPASS = "localhost,127.0.0.1,::1"


def apply_proxy_bypass():
    """HTTP_PROXY/HTTPS_PROXY point at a corporate gateway with no localhost
    exception, so even http://localhost:9444 is routed through it and blocked
    ("403 URLBlocked", Skyhigh Secure Web Gateway). urllib reads these env
    vars at call time, so setting them in this process is enough - but it
    must happen before the first request.

    Note this covers OUR calls to the CDP endpoint only. Chrome's own page
    requests still go through the corporate proxy, which is what the real
    G-MES portal needs.

    Idempotent; every entry point calls it at import time."""
    for name in ("NO_PROXY", "no_proxy"):
        current = os.environ.get(name, "")
        if all(host in current for host in ("localhost", "127.0.0.1")):
            continue
        os.environ[name] = _PROXY_BYPASS if not current else f"{current},{_PROXY_BYPASS}"


apply_proxy_bypass()


try:
    import websocket  # websocket-client
except ImportError:  # offline diagnostics and unit tests do not need CDP
    websocket = None


def _require_websocket():
    if websocket is None:
        raise RuntimeError(
            "websocket-client is not installed. Install it with: "
            f"{sys.executable} -m pip install websocket-client")
    return websocket


# --------------------------------------------------------------------------
# Chrome discovery / launch
# --------------------------------------------------------------------------

def find_chrome():
    """Locate chrome.exe without hardcoding one install path.

    The original code assumed "C:\\Program Files\\Google\\Chrome\\
    Application\\chrome.exe", which is only correct for a machine-wide
    install; a per-user install lands in %LOCALAPPDATA% instead and the
    script would die with a bare WinError 2."""
    override = os.environ.get("CHROME_PATH")
    if override and os.path.isfile(override):
        return override

    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     r"Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path

    found = shutil.which("chrome") or shutil.which("chrome.exe")
    if found:
        return found

    try:  # registry is authoritative when Chrome is installed oddly
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                key = winreg.OpenKey(
                    root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe")
                path, _ = winreg.QueryValueEx(key, "")
                if path and os.path.isfile(path):
                    return path
            except OSError:
                continue
    except ImportError:
        pass

    raise RuntimeError(
        "Could not find chrome.exe. Set the CHROME_PATH environment variable "
        "to its full path and retry.")


# The Popen handle for the Chrome this process started, so a caller (the
# test suite) can shut down exactly that instance instead of taskkilling
# every chrome.exe on the machine.
LAST_CHROME_PROCESS = None


def default_user_profile_dir():
    """The real Chrome profile - the one with the user's logins, extensions
    and certificates. Needed for sites that only work inside the normal
    browser session (GMES), as opposed to the throwaway profile used for
    NERP."""
    override = os.environ.get("CHROME_USER_DATA_DIR")
    if override:
        return override
    return os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\User Data")


def chrome_is_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
                             capture_output=True, text=True, timeout=15)
        return "chrome.exe" in (out.stdout or "")
    except Exception:
        return False


def working_profile_dir():
    """Where the debuggable copy of the user's profile lives."""
    override = os.environ.get("CHROME_CDP_PROFILE_DIR")
    if override:
        return override
    return os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\CDP Profile")


# Caches are large, regenerate themselves, and carry nothing we need.
_PROFILE_SKIP_DIRS = [
    "Cache", "Code Cache", "GPUCache", "DawnCache", "DawnGraphiteCache",
    "DawnWebGPUCache", "GrShaderCache", "ShaderCache", "Media Cache",
    "component_crx_cache", "extensions_crx_cache", "Crashpad",
    "Safe Browsing", "optimization_guide_model_store",
]


def clone_user_profile(dest=None, refresh=False, verbose=True):
    """Copy the real Chrome profile to a directory we are allowed to debug.

    Chrome 136 and later REFUSE --remote-debugging-port whenever
    --user-data-dir points at the default profile directory. The flag is not
    rejected loudly; it is silently ignored and the port simply never opens,
    which looks exactly like a launch failure. This is a deliberate security
    fix (it stopped malware from reading cookies out of a live browser via
    DevTools), so it is not something to work around in place - the
    supported approach is to debug a copy.

    The copy keeps extensions, cookies and saved logins, so the automated
    browser is signed in the same way the user's is. Session-only cookies do
    not survive, so a site may ask to log in once inside the copy.

    Copying is skipped when the destination already exists, unless refresh
    is set - re-copying on every run would be slow and would throw away the
    logged-in state built up inside the copy."""
    src = default_user_profile_dir()
    dest = dest or working_profile_dir()

    if not os.path.isdir(src):
        raise RuntimeError(f"Could not find the Chrome profile at {src!r}. "
                           "Set CHROME_USER_DATA_DIR to its location.")

    if os.path.isdir(dest) and not refresh:
        if verbose:
            print(f"Using the existing debuggable profile copy: {dest}")
        return dest

    if verbose:
        print(f"Copying your Chrome profile (this happens once, ~1 minute):")
        print(f"  from {src}")
        print(f"  to   {dest}")

    excludes = []
    for name in _PROFILE_SKIP_DIRS:
        excludes.append(name)
    cmd = ["robocopy", src, dest, "/E", "/R:0", "/W:0",
           "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/XJ",
           "/XD"] + excludes
    result = subprocess.run(cmd, capture_output=True, text=True)
    # robocopy uses exit codes as a bitmask; 0-7 are success, 8+ are errors.
    if result.returncode >= 8:
        raise RuntimeError(
            f"Copying the profile failed (robocopy exit {result.returncode}). "
            f"{(result.stdout or '').strip()[-400:]}")
    if verbose:
        print("Profile copy ready.")
    return dest


def launch_chrome_with_user_profile(port=None, url=None, wait_seconds=45,
                                    refresh_profile=False):
    """Start Chrome on a debuggable COPY of the user's own profile.

    Never deletes or modifies the real profile - see clone_user_profile for
    why a copy is required at all. Chrome will not open a second browser
    process on a profile already in use, so the caller must make sure Chrome
    is closed first."""
    port = port or CDP_PORT
    if cdp_is_up(port):
        return None  # already listening; reuse it

    profile = clone_user_profile(refresh=refresh_profile)
    chrome = find_chrome()
    args = [chrome, f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "--profile-directory=Default",
            "--remote-allow-origins=*",
            "--no-first-run", "--no-default-browser-check",
            "--restore-last-session=false",
            # G-MES's "AD SSO Login" opens ADFS via window.open(); this
            # machine's Chrome popup-allowlist GPO does not cover that
            # origin, so the popup is silently swallowed with nothing for
            # Runtime.evaluate to see (HISTORY.md Phase 56.1, live-proven
            # against the frozen engine's identical launch pattern). The
            # same flag Selenium and Puppeteer both set by default.
            "--disable-popup-blocking"]
    if url:
        args.append(url)

    global LAST_CHROME_PROCESS
    LAST_CHROME_PROCESS = subprocess.Popen(
        args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if cdp_is_up(port):
            return LAST_CHROME_PROCESS
        time.sleep(0.5)

    raise RuntimeError(
        f"Chrome started but never opened the debugging port {port}. Usual "
        "causes: another Chrome window is still open (check the system tray), "
        f"or the profile copy at {profile!r} is in use by another instance.")


def close_browser(port=None, timeout=15):
    """Close the automation browser, and only that one.

    Through its own DevTools endpoint rather than `taskkill /IM chrome.exe`,
    which would take every Chrome window the user has open (CLAUDE.md 2.6).
    Returns True once the port has actually gone."""
    port = port or CDP_PORT
    if not cdp_is_up(port):
        return True
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://{CDP_HOST}:{port}/json/version", timeout=5) as response:
            info = json.loads(response.read().decode())
        ws = connect(ipv4(info["webSocketDebuggerUrl"]), enable_runtime=False)
        try:
            send(ws, "Browser.close", timeout=5)
        finally:
            try:
                ws.close()
            except Exception:
                pass
    except Exception:
        pass        # it may have gone on its own between the check and the call

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not cdp_is_up(port):
            return True
        time.sleep(0.5)
    return False


def cdp_is_up(port=None, timeout=2):
    try:
        get_tabs(port=port, timeout=timeout)
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------
# Low-level CDP transport
# --------------------------------------------------------------------------

_msg_ids = itertools.count(1)


def next_id():
    """Monotonic CDP message ids.

    The original code hand-picked ids per call site (2, 10, 11, 30, 90, 95,
    ...) with ad-hoc "+10" offsets, which is a latent correlation bug: two
    overlapping helpers on the same socket can reuse an id and read each
    other's reply. A shared counter makes collisions impossible."""
    return next(_msg_ids)


def ipv4(url):
    """Rewrite a DevTools URL to the IPv4 literal.

    Chrome hands back webSocketDebuggerUrl values pointing at "localhost".
    Connecting to those pays the same IPv6-first penalty as the HTTP
    endpoint - about two seconds per websocket, on every connect."""
    if not url:
        return url
    return url.replace("://localhost:", f"://{CDP_HOST}:")


def get_tabs(port=None, timeout=5):
    port = port or CDP_PORT
    req = urllib.request.Request(f"http://{CDP_HOST}:{port}/json/list")
    # Explicitly bypass any configured proxy handler; setting NO_PROXY covers
    # urlopen's default opener, but being explicit also survives a caller
    # that installed its own opener earlier in the process.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as response:
        return json.loads(response.read().decode())


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

    Two real problems this removes:
      * Several call sites omitted returnByValue and only worked by accident
        (primitives are inlined in the reply; anything else would not be).
      * A JS exception surfaced as a bare KeyError deep in the caller. Now it
        raises a RuntimeError naming the failing expression."""
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
    ws = _require_websocket().create_connection(ipv4(ws_url), timeout=timeout)
    if enable_runtime:
        send(ws, "Runtime.enable", timeout=timeout)
    return ws


def navigate_page(url, port=None, timeout=15):
    """Point the top-level page target at `url` on a short-lived connection.

    The socket is opened and closed around the navigation on purpose: holding
    one open and idle across a page load makes the next recv() time out
    (gotcha #4).

    The Page.navigate acknowledgement is treated as optional. Navigating away
    from a chrome:// page (chrome://newtab is what a freshly launched Chrome
    shows) is a cross-process navigation that swaps renderers, and Chrome can
    tear the DevTools session down before the reply is written - observed as
    a bare ConnectionResetError WinError 10054, which used to abort the whole
    run. By then the navigation has already been issued, and the caller polls
    for the loaded page regardless, so a lost ack is not a failure."""
    tab = get_page_tab(prefer_url_substring=None, port=port)
    if tab is None:
        raise RuntimeError("No page target available. Is Chrome running with CDP enabled?")

    client = _require_websocket()
    ws = None
    try:
        ws = client.create_connection(ipv4(tab["webSocketDebuggerUrl"]), timeout=timeout)
        send(ws, "Page.enable", timeout=timeout)
        send(ws, "Page.navigate", {"url": url}, timeout=timeout)
    except (OSError, TimeoutError, client.WebSocketException) as e:
        print(f"(no navigate acknowledgement: {e!r} - the navigation was still "
              "issued; the poll that follows confirms the load)")
    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass
    return tab


# --------------------------------------------------------------------------
# Input simulation
# --------------------------------------------------------------------------

def click_element_by_rect(ws, x, y, msg_id_start=None):
    """Real mouse event simulation. Required because element.click() is
    ignored by Nexacro's controls - they are <div>s wired to mousedown/
    mouseup, with no click handler to invoke at all.

    msg_id_start is accepted for backwards compatibility and ignored; ids
    now come from the shared counter."""
    send(ws, "Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    send(ws, "Input.dispatchMouseEvent", {
        "type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
    time.sleep(0.1)
    send(ws, "Input.dispatchMouseEvent", {
        "type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})


def dispatch_key_combo(ws, key, code, vk, ctrl=False, shift=False, alt=False,
                       msg_id_start=None):
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
    send(ws, "Input.dispatchKeyEvent", {"type": "rawKeyDown", **params})
    send(ws, "Input.dispatchKeyEvent", {"type": "keyUp", **params})


# JS snippet shared by every "type into a field" call site. A bare
# `.value =` assignment is not observed - the framework listens for the
# events, not the property - so they must be fired too.
JS_SET_VALUE = """
    el.focus();
    el.value = value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
"""


# --------------------------------------------------------------------------
# Element lookup
# --------------------------------------------------------------------------

# Shared JS predicate: an element is only clickable if it has a non-zero box
# AND that box actually intersects the viewport (CLAUDE.md 3.3). Some menus
# and dropdown widgets pre-render off-screen to measure themselves before
# repositioning - observed at y = -99984 with a perfectly valid width and
# height - so a size-only check finds them, clicks empty space, and the whole
# flow fails silently with no error anywhere.
JS_IS_VISIBLE = """
    function(el) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return false;
        if (r.bottom <= 0 || r.right <= 0) return false;
        if (r.top >= window.innerHeight || r.left >= window.innerWidth) return false;
        return true;
    }
"""


# --------------------------------------------------------------------------
# Target selection
# --------------------------------------------------------------------------

def get_page_tab(prefer_url_substring="nerps", port=None):
    """Pick the top-level page target to drive.

    Prefers a tab whose URL contains `prefer_url_substring`; falls back to
    any page target. The preference exists because a long-lived CDP session
    accumulates duplicate and stale page targets, so
    `next(t for t in tabs if t['type'] == 'page')` picks whichever stale one
    happens to be listed first.

    **The `"nerps"` default is dead and deliberately left alone.** Every
    surviving caller passes the argument explicitly - `gmes_connect.py` sends
    `"gmes"`, while `navigate_page()` and `capture_screenshot()` both send
    `None` - so the default is unreachable in this codebase. It was N-ERP's,
    and N-ERP was removed in HISTORY.md Phase 72. Changing it would be a
    behaviour change on the shared screenshot path for no practical gain, so
    it was recorded rather than edited; `tests/test_cdp_common.py` covers the
    two forms that are actually used."""
    tabs = get_tabs(port=port)
    pages = [t for t in tabs if t.get("type") == "page"]
    if not pages:
        return tabs[0] if tabs else None
    if prefer_url_substring:
        preferred = [t for t in pages if prefer_url_substring in t.get("url", "")]
        if preferred:
            return preferred[0]
    return pages[0]


# --------------------------------------------------------------------------
# Diagnostics
# --------------------------------------------------------------------------

def capture_screenshot(path, port=None, timeout=20, tab=None):
    """Save a PNG of the browser window.

    Page.captureScreenshot fails with "Command can only be executed on
    top-level targets" if called on an iframe target's own connection, so
    this always connects to a page-type target. Iframe content is still
    visible in the result, since it renders inside that page.

    `tab`, optional: use this exact CDP target instead of resolving one via
    `get_page_tab(prefer_url_substring=None, ...)` (i.e. whichever page
    target happens to be listed first). That default is correct when only
    one page target normally exists, which is why every caller so far has
    been fine leaving `tab` unset. It stops being correct the moment a
    second page target exists at the same time - a leftover popup, an old
    tab - and the diagnostic silently photographs the wrong page while
    looking like evidence (HISTORY.md Phase 56.4). A caller that can name
    its own tab correctly (see `gmes_common.capture_screenshot`) should."""
    if tab is None:
        tab = get_page_tab(prefer_url_substring=None, port=port)
    if not tab:
        return None
    ws = None
    try:
        ws = connect(tab["webSocketDebuggerUrl"], timeout=timeout, enable_runtime=False)
        send(ws, "Page.enable", timeout=timeout)
        resp = send(ws, "Page.captureScreenshot", {"format": "png"}, timeout=timeout)
        data = resp["result"]["data"]
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(data))
        return path
    except Exception as e:
        print(f"(screenshot failed: {e!r})")
        return None
    finally:
        if ws:
            ws.close()


def screenshot_on_failure(prefix="gmes_failure", tab=None):
    """Best-effort diagnostic snapshot next to the scripts, named by time.

    `tab`: see `capture_screenshot()` - unset preserves the exact existing
    behaviour for every caller that does not need to name one. Prefer
    `gmes_common.screenshot_on_failure()`, which resolves the G-MES tab
    strictly rather than taking whichever page is listed first.

    The default prefix was `nerp_failure` until HISTORY.md Phase 72; no
    caller relies on it (every one passes its own), and `.gitignore` covers
    `gmes_*.png`."""
    name = f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.png"
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    saved = capture_screenshot(path, tab=tab)
    if saved:
        print(f"Diagnostic screenshot saved: {saved}")
    return saved
