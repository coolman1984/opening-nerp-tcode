"""AD SSO race, direct-login fallback, and reading G-MES's own login-page
error message.

Forked from gmes_login.py. `is_logged_in` deliberately lives in
`auth/session.py`, not here, per the migration plan - which makes this
module and session.py mutually dependent (this module's
`wait_for_sso_window` needs to check "are we already signed in", and
session.py's `wait_for_login_or_session` needs this module's
`login_error`/`BTN_SSO`). Broken the same way `browser/chrome.py` breaks
its own cdp.py/chrome.py cycle (see `close_browser()` there): a local
import inside the one function that needs it, not a module-level one.
"""
import json
import time

from ..browser.cdp import connect, evaluate, list_windows
from ..browser.interaction import click_element_by_rect
from ..nexacro.dom import click_by_id, js_find_by_id, set_value_by_id
from ..nexacro.js_snippets import JS_IS_VISIBLE

LOGIN_FORM = "mainframe.vFrameSet1.loginFrame.form.divLogin.form"
BTN_SSO = f"{LOGIN_FORM}.btnAdSSO"
BTN_LOGIN = f"{LOGIN_FORM}.btnLogin"
ERR_MSG = f"{LOGIN_FORM}.staErrMsg"

SSO_URL_MARK = "secsso.net"
SSO_USER_FIELD = "userNameInput"
SSO_PW_FIELD = "passwordInput"

# G-MES's own login form, beside the AD SSO button. These ids are safe to
# hardcode: loginFrame is a shell frame, and there is only ever one of it.
USER_FIELD = f"{LOGIN_FORM}.edUserID"
PW_FIELD = f"{LOGIN_FORM}.edPassword"


def login_error(ws):
    """Whatever G-MES is displaying on its own login form, e.g.
    'Auth bad credentials'.

    This is read while WAITING, not only after a timeout. A run once sat
    for 45 seconds, retried, and sat for 45 more - 90 seconds of silence -
    while the answer was printed on the login page the whole time."""
    try:
        info = evaluate(ws, js_find_by_id(ERR_MSG))
        return (info.get("text") or "").strip() if info.get("found") else ""
    except Exception:
        return ""


JS_SSO_SUBMIT = """
(function() {
    const isVisible = %s;
    // ADFS normally exposes #submitButton; fall back to the smallest visible
    // thing that says Login, so a template change does not break sign-in.
    let btn = document.getElementById('submitButton');
    if (!btn || !isVisible(btn)) {
        const candidates = Array.from(document.querySelectorAll(
                'span, input[type="submit"], button, div, a'))
            .filter(el => {
                const t = (el.textContent || el.value || '').trim();
                return /^(log ?in|sign ?in)$/i.test(t) && isVisible(el);
            });
        candidates.sort((a, b) => {
            const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
            return (ra.width * ra.height) - (rb.width * rb.height);
        });
        btn = candidates[0];
    }
    if (!btn) return JSON.stringify({found: false});
    const r = btn.getBoundingClientRect();
    return JSON.stringify({found: true, id: btn.id,
                           x: r.left + r.width/2, y: r.top + r.height/2});
})()
""" % JS_IS_VISIBLE

JS_SSO_ERROR = """
(function() {
    const el = document.getElementById('errorText') ||
               document.querySelector('.error, #error, .fieldMargin.error');
    return JSON.stringify({text: el ? (el.textContent || '').trim().slice(0, 200) : ''});
})()
"""

JS_DIRECT_LOGIN = """
(function() {
    const user = %s, password = %s;
    let f = null;
    try {
        f = nexacro.getApplication().mainframe.vFrameSet1.loginFrame.form
                   .divLogin.form;
    } catch (e) { return JSON.stringify({ok: false, reason: 'login form not reachable'}); }
    if (!f || !f.edUserID || !f.edPassword)
        return JSON.stringify({ok: false, reason: 'no ID/password boxes on this page'});
    try {
        // Through Nexacro's own components, not the DOM input. Nexacro reads
        // the component when the Login button is pressed, so a raw .value on
        // the inner <input> would look right on screen and submit nothing.
        f.edUserID.set_value(user);
        f.edPassword.set_value(password);
    } catch (e) { return JSON.stringify({ok: false, reason: 'could not set: ' + e.message}); }
    // Read back the ID only. The password is never returned, printed or logged.
    let back = '';
    try { back = String(f.edUserID.value || ''); } catch (e) {}
    let filled = false;
    try { filled = String(f.edPassword.value || '').length > 0; } catch (e) {}
    return JSON.stringify({ok: back === user && filled, user: back, pw_set: filled});
})()
"""

JS_SSO_FORM_READY = """
    (function(){ return JSON.stringify({
        user: !!document.getElementById('userNameInput'),
        pw: !!document.getElementById('passwordInput')}); })()"""


def direct_login(ws, user, password):
    """Sign in with G-MES's own ID and password form.

    The fallback for an AD SSO that will not complete. G-MES puts a plain
    login form right beside the SSO button, and the stored credentials
    are for the same account, so there is no reason to be stuck on a page
    that is asking for exactly what we already hold.

    The password goes from the encrypted store straight into the
    browser. It is never printed, never returned by the JavaScript above,
    and never reaches a log line."""
    filled = evaluate(ws, JS_DIRECT_LOGIN % (json.dumps(user), json.dumps(password)))
    if not filled.get("ok"):
        return False, filled.get("reason", "the ID and password did not take")

    if not click_by_id(ws, BTN_LOGIN, attempts=10):
        return False, "the Login button was not on screen"
    return True, "submitted"


def find_sso_window(port=None):
    for tab in list_windows(port=port):
        if SSO_URL_MARK in (tab.get("url") or ""):
            return tab
    return None


def wait_for_sso_window(ws=None, max_wait=45, poll_interval=1.0):
    """Wait for the Samsung SSO window - or for the sign-in to complete
    without one - or for G-MES to say it refused.

    Clicking AD SSO does not always open a window. When a session cookie
    has survived in the profile, G-MES signs straight back in and no SSO
    page is ever shown. Waiting only for the window then fails the whole
    run with "the Samsung SSO window never opened" while the user is, in
    fact, already signed in.

    And it does not always succeed. When G-MES refuses, it writes the
    reason onto its own login form ("Auth bad credentials") and then
    nothing further happens - no window, no session, no error thrown.
    Waiting the full 45s for a window that is never coming, while the
    reason sits on screen, is the difference between a run that explains
    itself and one that hangs.

    A message on the page NEVER decides anything, and an earlier version
    of this let it. It returned "rejected" as soon as 'Auth bad
    credentials' had been showing for a few seconds - while the Samsung
    ADFS window was still on its way, and while the message itself was
    often left over from a previous attempt. That false alarm cost three
    wrong diagnoses and a needless manual sign-in.

    The logic is now the simple one it should always have been:

        signed in            -> done, whatever the page says
        an SSO window        -> go and fill it in
        neither, for the full wait -> a real failure, and THEN the page's
                                      message is worth quoting

    Returns the SSO tab, "already-signed-in", or ("rejected", message)."""
    # Local import: session.py imports login_error/BTN_SSO from this module
    # at its own top level, so importing session at THIS module's top level
    # would be circular. By the time this function actually runs, both
    # modules are fully loaded and the import resolves fine.
    from .session import is_logged_in

    started = time.time()
    seen_message = ""
    while time.time() - started < max_wait:
        tab = find_sso_window()
        if tab:
            return tab
        if ws is not None:
            try:
                # Checked first, every pass. Being signed in beats anything
                # written on the login form.
                if is_logged_in(ws)[0]:
                    return "already-signed-in"
                seen_message = login_error(ws) or seen_message
            except Exception:
                pass       # still navigating; the socket or document is in flux
        time.sleep(poll_interval)

    # Nothing arrived in the whole window. Now the message explains why.
    return ("rejected", seen_message) if seen_message else None


def complete_sso(tab, user, password):
    """Fill the Samsung SSO page and submit it.

    The password goes straight from the encrypted store into the browser
    - it is never printed, and never lands in a variable that gets
    logged.

    The connection is re-established rather than assumed. ADFS redirects
    several times while it settles, and each redirect can tear the
    DevTools session down: attaching once and evaluating in a loop
    crashed the whole sign-in with `ConnectionAbortedError [WinError
    10053]` just as the window appeared. A dropped socket here means the
    page moved, which is normal - only the window actually going away is
    a failure."""
    def attach():
        fresh = find_sso_window() or tab
        return connect(fresh["webSocketDebuggerUrl"], timeout=20)

    try:
        ws = attach()
    except Exception as e:
        return False, f"could not attach to the SSO page ({e})"

    try:
        # The sign-in form is server-rendered, but wait for it anyway
        # rather than assuming: the window can be registered before it
        # has painted.
        ready = False
        for _ in range(40):
            try:
                state = evaluate(ws, JS_SSO_FORM_READY)
                if state.get("user") and state.get("pw"):
                    ready = True
                    break
            except Exception:
                if find_sso_window() is None:
                    # It closed by itself, which is what a successful
                    # silent sign-in looks like. The caller checks for a
                    # session.
                    return True, "the SSO window closed on its own"
                try:
                    ws.close()
                except Exception:
                    pass
                try:
                    ws = attach()
                except Exception:
                    pass
            time.sleep(1)
        if not ready:
            return False, "the SSO page never showed its ID and password boxes"

        try:
            set_value_by_id(ws, SSO_USER_FIELD, user)
            set_value_by_id(ws, SSO_PW_FIELD, password)
            btn = evaluate(ws, JS_SSO_SUBMIT)
            if not btn.get("found"):
                return False, "could not find the Login button on the SSO page"
            click_element_by_rect(ws, btn["x"], btn["y"])
        except Exception as e:
            if find_sso_window() is None:
                return True, "the SSO window closed while being filled in"
            return False, f"the SSO page could not be filled in ({e})"

        # Give the SSO page a moment to report a bad password rather than
        # silently redirecting.
        time.sleep(3)
        try:
            err = evaluate(ws, JS_SSO_ERROR).get("text", "")
        except Exception:
            err = ""     # the window is already navigating away - that is good
        if err:
            return False, f"SSO rejected the sign-in: {err!r}"
        return True, "submitted"
    finally:
        try:
            ws.close()
        except Exception:
            pass
