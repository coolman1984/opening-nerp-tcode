"""
Shared Chrome DevTools Protocol (CDP) plumbing for the NERP T-code skill.

Everything here exists because of a concrete failure observed against the
real N-ERP portal - see the numbered gotchas in SKILL.md. The short version:

  * The corporate proxy swallows localhost traffic unless NO_PROXY is set.
  * Chrome ignores --remote-debugging-port unless it gets its own profile,
    and rejects the DevTools websocket without --remote-allow-origins=*.
  * The actual SAP screen lives in a separate cross-origin CDP target, not
    in the Fiori page's DOM.
  * element.click() is ignored by both Fiori and classic WebGUI controls, so
    clicks must be real Input.dispatchMouseEvent sequences.
  * Nothing about SAP's render timing is predictable, so every wait polls
    until the thing is actually there, with a generous safety cap - never a
    tuned fixed sleep.
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

CDP_PORT = int(os.environ.get("NERP_CDP_PORT", "9444"))

# Always address the DevTools endpoint by its IPv4 literal, never by name.
# On Windows "localhost" resolves to ::1 first; Chrome listens on IPv4 only,
# so every call waits for the IPv6 attempt to fail before falling back.
# Measured: 2.05s per /json/list via "localhost" against 0.013s via
# 127.0.0.1 - a 150x difference paid by every target lookup and every
# websocket connect, which is most of what these tools do.
CDP_HOST = "127.0.0.1"
NERP_URL = os.environ.get("NERP_URL", "https://nerps.sec.samsung.net")
PROFILE_NAME = os.environ.get("NERP_CHROME_PROFILE", "chrome_cdp_profile")

CHROME_FLAGS = [
    # Gotcha #3: without this Chrome answers the DevTools websocket
    # handshake with 403 Forbidden.
    "--remote-allow-origins=*",
    "--no-first-run",
    "--no-default-browser-check",
]

_PROXY_BYPASS = "localhost,127.0.0.1,::1"


def apply_proxy_bypass():
    """SKILL.md gotcha #1: HTTP_PROXY/HTTPS_PROXY point at a corporate
    gateway with no localhost exception, so even http://localhost:9444 is
    routed through it and blocked ("403 URLBlocked", Skyhigh Secure Web
    Gateway). urllib reads these env vars at call time, so setting them in
    this process is enough - but it must happen before the first request.

    Idempotent; every entry point calls it at import time."""
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
            "--restore-last-session=false"]
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


def profile_dir(name=None):
    import tempfile
    return os.path.join(tempfile.gettempdir(), name or PROFILE_NAME)


def cdp_is_up(port=None, timeout=2):
    try:
        get_tabs(port=port, timeout=timeout)
        return True
    except Exception:
        return False


def launch_chrome(port=None, profile=None, kill_existing=True, extra_flags=(),
                  wait_seconds=20):
    """Start Chrome with CDP enabled and wait until the endpoint answers.

    kill_existing (gotchas #2/#15/#22): taskkill every chrome.exe AND delete
    the profile directory before relaunching. Killing alone is not enough -
    /F looks like a crash to Chrome, so session-restore silently reopens
    tabs from a previous run on the same --user-data-dir, and every later
    step then operates on a stale but perfectly valid screen with no error.

    Pass kill_existing=False to leave the user's own browser alone; that is
    safe as long as `profile` is a directory no other Chrome instance is
    using, because a distinct --user-data-dir forces a genuinely new browser
    process rather than forwarding to the running one."""
    port = port or CDP_PORT
    profile = profile or profile_dir()
    chrome = find_chrome()

    if kill_existing:
        subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)

    shutil.rmtree(profile, ignore_errors=True)

    global LAST_CHROME_PROCESS
    LAST_CHROME_PROCESS = subprocess.Popen(
        [chrome, f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
         *CHROME_FLAGS, *extra_flags,
         # Start on about:blank rather than letting Chrome open its new-tab
         # page. chrome://newtab is a privileged WebUI target: Page.enable on
         # it has been seen to hang, and navigating away from it forces a
         # cross-process swap that drops the DevTools session. about:blank is
         # an ordinary, immediately controllable target.
         "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if cdp_is_up(port):
            return chrome
        time.sleep(0.5)

    raise RuntimeError(
        f"Chrome did not expose a CDP endpoint on port {port} within "
        f"{wait_seconds}s (launched from {chrome!r}, profile {profile!r}).")


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
    ws = websocket.create_connection(ipv4(ws_url), timeout=timeout)
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


def connect_with_retry(ws_url_getter, attempts=3, backoff=5, timeout=20):
    """ws_url_getter is a zero-arg callable returning a fresh (url, label)
    each attempt - tab lists change between retries, so re-resolving matters.

    Retries on any connection-level failure, not just TimeoutError: a page
    still mid-navigation refuses the socket or fails the handshake outright,
    which the original TimeoutError-only handler let escape as a hard crash."""
    last_err = None
    for attempt in range(attempts):
        ws_url, label = ws_url_getter()
        print(f"Connecting to: {label} (attempt {attempt + 1})")
        ws = None
        try:
            return connect(ws_url, timeout=timeout)
        except Exception as e:
            last_err = e
            print(f"Attempt {attempt + 1} failed ({e!r}); waiting {backoff}s and retrying...")
            if ws:
                ws.close()
            time.sleep(backoff)
    raise last_err


# --------------------------------------------------------------------------
# Input simulation
# --------------------------------------------------------------------------

def click_element_by_rect(ws, x, y, msg_id_start=None):
    """Real mouse event simulation (gotcha #5). Required because
    element.click() is ignored by both the SAP UI5/Fiori shell buttons and
    the classic WebGUI toolbar buttons - the latter are DIVs wired to
    mousedown/mouseup, with no click handler to invoke at all.

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


# JS snippet shared by every "type into a dynpro field" call site. SAP does
# not observe a bare `.value =` assignment, so the events must be fired too.
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
# AND that box actually intersects the viewport. Gotcha #20: some dropdown
# widgets pre-render off-screen (observed at y = -99984) with a perfectly
# valid width/height, so a size-only check finds them, clicks empty space,
# and the whole flow fails silently with no error anywhere.
JS_IS_VISIBLE = """
    function(el) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return false;
        if (r.bottom <= 0 || r.right <= 0) return false;
        if (r.top >= window.innerHeight || r.left >= window.innerWidth) return false;
        return true;
    }
"""


def find_visible_leaf_by_text(ws, *texts, max_len=30, msg_id=None):
    """Find a small, visible leaf-ish element whose trimmed text exactly
    matches one of `texts`, smallest (most specific) first.

    Gotcha #9: SAP WebGUI buttons are <div>s nested several layers deep, and
    textContent is inherited up the tree, so a naive text match happily
    returns the whole toolbar - or a hidden context-menu item carrying the
    same words. Filtering to visible, in-viewport, short-text elements and
    sorting by area picks the real button."""
    js = """
    (function() {
        const texts = %s;
        const isVisible = %s;
        let candidates = Array.from(document.querySelectorAll('*')).filter(el => {
            const t = (el.textContent || '').trim();
            if (t.length === 0 || t.length > %d) return false;
            if (!texts.some(needle => t === needle)) return false;
            return isVisible(el);
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
    """ % (json.dumps(list(texts)), JS_IS_VISIBLE, max_len)
    return evaluate(ws, js)


def find_visible_by_title(ws, title, max_size=None, exact=False):
    """Find visible elements by their `title` attribute, smallest first.

    Some SAP controls are icon-only and carry no usable visible text at all
    (the format dialog's Continue checkmark, the toolbar Export icon), so
    text matching cannot reach them. `exact=True` matches the whole title
    (the Export icon's title is exactly "Export"); otherwise it is a
    case-insensitive substring match. `max_size` restricts to small icon
    boxes, which keeps a large titled container from matching."""
    js = """
    (function() {
        const isVisible = %s;
        const needle = %s;
        const exact = %s;
        const maxSize = %s;
        let els = Array.from(document.querySelectorAll('*')).filter(el => {
            const raw = (el.title || '').trim();
            if (!raw) return false;
            if (exact ? raw !== needle : !raw.toLowerCase().includes(needle.toLowerCase()))
                return false;
            if (!isVisible(el)) return false;
            if (maxSize !== null) {
                const r = el.getBoundingClientRect();
                if (r.width > maxSize || r.height > maxSize) return false;
            }
            return true;
        });
        els.sort((a, b) => {
            const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
            return (ra.width * ra.height) - (rb.width * rb.height);
        });
        return JSON.stringify(els.map(el => {
            const r = el.getBoundingClientRect();
            return { tag: el.tagName, id: el.id, title: el.title,
                     x: r.left + r.width/2, y: r.top + r.height/2 };
        }));
    })()
    """ % (JS_IS_VISIBLE, json.dumps(title), "true" if exact else "false",
           "null" if max_size is None else str(max_size))
    return evaluate(ws, js)


def describe_visible_dialog(ws, limit=400):
    """Dump the text of whatever modal/popup is currently on screen.

    Used for diagnostics when an export shortcut opens something we don't
    recognise: the original code just kept firing the next shortcut into the
    open dialog, so the eventual error message described the last shortcut
    rather than the thing actually blocking progress."""
    js = """
    (function() {
        const isVisible = %s;
        const sel = '[role="dialog"], .urPopupWindow, .lsPopup, .urPWContainer, dialog';
        let popups = Array.from(document.querySelectorAll(sel)).filter(isVisible);
        return JSON.stringify({
            count: popups.length,
            texts: popups.map(p => (p.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, %d))
        });
    })()
    """ % (JS_IS_VISIBLE, limit)
    try:
        return evaluate(ws, js)
    except Exception:
        return {"count": 0, "texts": []}


# --------------------------------------------------------------------------
# Waiting (poll until observed; never a tuned fixed sleep - gotchas #23-25)
# --------------------------------------------------------------------------

def wait_for_busy_indicator_clear(ws, max_wait=120, poll_interval=0.5, grace_checks=4):
    """Poll the generic SAP WebGUI busy indicator
    ('hiddenLoadingToolbarButton', part of the shell chrome and therefore
    present regardless of which t-code is open) until it has appeared and
    gone again.

    Handles both shapes: the indicator becomes visible then invisible (the
    normal case), or it never appears at all because the operation finished
    faster than the poll interval - after `grace_checks` quiet polls that is
    treated as done rather than waiting out the full cap for a busy state
    that was never coming.

    Returns True once a settled state is observed, False if max_wait elapsed
    while still busy (the caller decides whether that is fatal; it may just
    mean a genuinely long-running query)."""
    js_busy = """
    (function() {
        const el = document.getElementById('hiddenLoadingToolbarButton');
        if (!el) return JSON.stringify({busy: false});
        const r = el.getBoundingClientRect();
        return JSON.stringify({busy: r.width > 0 && r.height > 0});
    })()
    """
    seen_busy = False
    attempts = max(1, int(max_wait / poll_interval))
    for i in range(attempts):
        state = evaluate(ws, js_busy)
        if state.get("busy"):
            seen_busy = True
        elif seen_busy or i >= grace_checks:
            return True
        time.sleep(poll_interval)
    return False


JS_SELECTION_SCREEN_STATE = """
(function() {
    const isVisible = %s;
    let inputs = Array.from(document.querySelectorAll('input[type="text"], input:not([type])'));
    let visibleInputs = inputs.filter(inp => !inp.disabled && !inp.readOnly && isVisible(inp));

    // Same discipline as execute_filters' own lookup: a container that
    // merely CONTAINS the Execute button matches a bare /execute/ text test
    // too, so readiness would be reported before the button exists.
    let execBtn = Array.from(document.querySelectorAll(
            'div, button, a, span, input[type="button"], input[type="submit"]'))
        .find(el => {
            if (el.disabled) return false;
            if ((el.getAttribute('aria-disabled') || '').toLowerCase() === 'true') return false;
            if (/disabled/i.test(el.className || '')) return false;
            if (!isVisible(el)) return false;
            if (/\\(F8\\)/.test(el.title || '')) return true;
            const t = (el.textContent || el.value || '').trim();
            return t.length > 0 && t.length <= 40 && /execute/i.test(t);
        });

    return JSON.stringify({
        readyState: document.readyState,
        title: document.title,
        // innerText, not textContent: textContent includes the source of
        // every <script> on the page, which would let the t-code sanity
        // check match a string that is never actually displayed.
        bodyText: (document.body ? (document.body.innerText || '') : '')
                      .replace(/\\s+/g, ' ').trim().slice(0, 300),
        visibleInputCount: visibleInputs.length,
        visibleInputTitles: visibleInputs.map(i => i.title || i.placeholder || '(untitled)').slice(0, 20),
        executeFound: !!execBtn
    });
})()
""" % JS_IS_VISIBLE


def read_selection_screen_state(tab, timeout=10):
    """Connect to a webgui tab and report what is actually rendered inside
    it. Separated from the wait loop so callers can use it for the post-open
    sanity check (gotcha #22) as well."""
    ws = None
    try:
        ws = connect(tab["webSocketDebuggerUrl"], timeout=timeout)
        return evaluate(ws, JS_SELECTION_SCREEN_STATE, timeout=timeout)
    finally:
        if ws:
            ws.close()


def wait_for_selection_screen_ready(max_wait=120, poll_interval=1.5, port=None):
    """Poll until the SAP WebGUI selection screen is not merely present as a
    CDP target but actually rendered and interactive.

    get_webgui_tab() finding the target only proves CDP registered it - the
    SAP content inside can still be mid-load, so a caller that proceeds the
    instant the target exists connects fine and then finds zero (or the
    wrong) fields, or an Execute button that is not clickable yet. This
    re-fetches the live target each attempt and checks, inside its DOM:
    readyState complete, at least one visible enabled input, and a visible
    enabled Execute button.

    Returns the ready tab dict. Raises RuntimeError with a single diagnostic
    line (elapsed, target url/title, input count and titles, whether Execute
    was found) on timeout."""
    start = time.time()
    last_tab = None
    last_state = {"readyState": "(no target found yet)", "visibleInputCount": 0,
                  "visibleInputTitles": [], "executeFound": False}

    attempts = max(1, int(max_wait / poll_interval))
    for _ in range(attempts):
        tab = get_webgui_tab(port=port)
        if tab:
            last_tab = tab
            try:
                last_state = read_selection_screen_state(tab)
                if (last_state.get("readyState") == "complete"
                        and last_state.get("visibleInputCount", 0) > 0
                        and last_state.get("executeFound")):
                    return tab
            except Exception:
                pass
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


# --------------------------------------------------------------------------
# Target selection
# --------------------------------------------------------------------------

def get_page_tab(prefer_url_substring="nerps", port=None):
    """Pick the top-level page target to drive.

    Prefers a tab already on the portal; falls back to any page target.
    Gotcha #18: a long-lived session accumulates duplicate 'N-ERP Home'
    tabs, and `next(t for t in tabs if t['type'] == 'page')` then picks
    whichever stale one happens to be first."""
    tabs = get_tabs(port=port)
    pages = [t for t in tabs if t.get("type") == "page"]
    if not pages:
        return tabs[0] if tabs else None
    if prefer_url_substring:
        preferred = [t for t in pages if prefer_url_substring in t.get("url", "")]
        if preferred:
            return preferred[0]
    return pages[0]


def is_webgui_candidate(tab):
    """Gotcha #6/#12: match the SAP GUI-for-HTML iframe target, and exclude
    the AppDynamics monitoring iframe whose URL-ENCODED address happens to
    contain 'webgui' as a substring too (.../adrum-xd...#https%3A%2F%2F...
    %2Fwebgui%3B...). Matching that decoy makes every later field lookup
    silently find nothing."""
    url = (tab.get("url") or "").lower()
    return (tab.get("type") == "iframe"
            and "webgui" in url
            and "adrum" not in url)


JS_TARGET_CONTENT = """
(function() {
    return JSON.stringify({
        elements: document.querySelectorAll('*').length,
        textLen: (document.body ? (document.body.innerText || '') : '').trim().length,
        inputs: document.querySelectorAll('input[type="text"]').length,
        title: document.title
    });
})()
"""


def score_webgui_tab(tab, timeout=10):
    """How much real content a candidate WebGUI target is rendering.

    The original discriminator was "most text inputs wins", which is right
    for a selection screen and BACKWARDS after Execute: a result list has no
    input fields at all, so a stale placeholder holding one transaction-code
    box outscores the live list and every export step then drives the wrong
    target. Observed exactly that way in the test suite - export connected
    to `?stale=1` while the real list sat in the other frame.

    Scoring on rendered content instead holds in both states: a stale
    placeholder is a near-empty document either way, while a live screen has
    substantial DOM and visible text whether it is showing fields or rows.

    Returns (score, detail); score is -1 if the target could not be read."""
    ws = None
    try:
        ws = connect(tab["webSocketDebuggerUrl"], timeout=timeout)
        detail = evaluate(ws, JS_TARGET_CONTENT, timeout=timeout)
        score = detail["elements"] + detail["textLen"] + detail["inputs"]
        return score, detail
    except Exception as e:
        return -1, {"error": repr(e)}
    finally:
        if ws:
            ws.close()


def get_webgui_tab(port=None, tabs=None):
    """Find the CDP target holding the classic SAP screen (fields, Execute
    button, result list). It is a separate cross-origin target
    (/sap/bc/gui/sap/its/webgui), NOT part of the Fiori shell page's DOM, so
    it cannot be reached through contentDocument.

    Opening several T-codes in one browser session leaves STALE webgui
    targets behind - the backend SAP session spawns windows that reloading
    the Fiori page does not tear down. Position in the tab list is not a
    reliable discriminator (the stale one has appeared both before and after
    the live one across runs), so candidates are probed and the one
    rendering the most content wins - see score_webgui_tab for why that is
    scored on content rather than on field count."""
    tabs = get_tabs(port=port) if tabs is None else tabs
    candidates = [t for t in tabs if is_webgui_candidate(t)]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    best_tab, best_score = None, -1
    for tab in candidates:
        score, _detail = score_webgui_tab(tab)
        if score > best_score:
            best_tab, best_score = tab, score
    return best_tab if best_tab is not None else candidates[0]


# --------------------------------------------------------------------------
# Diagnostics
# --------------------------------------------------------------------------

def capture_screenshot(path, port=None, timeout=20):
    """Save a PNG of the browser window.

    Gotcha #8: Page.captureScreenshot fails with "Command can only be
    executed on top-level targets" if called on the WebGUI iframe's own
    connection, so this always connects to the page-type target. The iframe
    content is still visible in the result, since it renders inside that
    page."""
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


def screenshot_on_failure(prefix="nerp_failure"):
    """Best-effort diagnostic snapshot next to the scripts, named by time."""
    name = f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.png"
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    saved = capture_screenshot(path)
    if saved:
        print(f"Diagnostic screenshot saved: {saved}")
    return saved
