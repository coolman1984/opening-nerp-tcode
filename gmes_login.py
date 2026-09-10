"""
GMES login - unattended.

    python gmes_login.py                 # open GMES, sign in, clear popups
    python gmes_login.py --show-browser  # same, but watch it happen
    python gmes_login.py --status        # just report where we are

Designed to run at night with nobody watching, so it never asks a question:
the credentials come from the encrypted store (gmes_credentials.py), and
every wait polls for the thing it needs instead of sleeping a guessed
number of seconds.

The flow it handles, in order:
  1. Chrome not running under our control  -> start it on the profile copy.
  2. Not on GMES                           -> navigate there.
  3. Already signed in                     -> skip straight to step 6.
  4. GMES login screen                     -> click "AD SSO Login".
  5. Samsung SSO sign-in page              -> fill ID + password, submit.
  6. Notice popups covering the screen     -> close each one by its X.
"""
import sys
import time

import cdp_common
import gmes_common
import gmes_credentials
from gmes_common import (
    GMES_URL, click_by_id, close_child_popups, connect_gmes, is_logged_in,
    list_windows, print_report, screen_report, set_value_by_id, wait_until,
)
from cdp_common import connect, evaluate

LOGIN_FORM = "mainframe.vFrameSet1.loginFrame.form.divLogin.form"
BTN_SSO = f"{LOGIN_FORM}.btnAdSSO"
BTN_LOGIN = f"{LOGIN_FORM}.btnLogin"
ERR_MSG = f"{LOGIN_FORM}.staErrMsg"

SSO_URL_MARK = "secsso.net"
SSO_USER_FIELD = "userNameInput"
SSO_PW_FIELD = "passwordInput"

# What main() returns. The distinction matters because one of these is worth
# retrying and the other never is.
OK = 0
FAILED = 1          # transient: no SSO window, a timeout, a closed browser
REJECTED = 2        # G-MES said the credentials are wrong. Retrying repeats it.


def login_error(ws):
    """Whatever G-MES is displaying on its own login form, e.g.
    'Auth bad credentials'.

    This is read while WAITING, not only after a timeout. A run once sat for
    45 seconds, retried, and sat for 45 more - 90 seconds of silence - while
    the answer was printed on the login page the whole time."""
    try:
        info = evaluate(ws, gmes_common.js_find_by_id(ERR_MSG))
        return (info.get("text") or "").strip() if info.get("found") else ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Samsung SSO page
# ---------------------------------------------------------------------------

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
""" % cdp_common.JS_IS_VISIBLE

JS_SSO_ERROR = """
(function() {
    const el = document.getElementById('errorText') ||
               document.querySelector('.error, #error, .fieldMargin.error');
    return JSON.stringify({text: el ? (el.textContent || '').trim().slice(0, 200) : ''});
})()
"""


def find_sso_window(port=None):
    for tab in list_windows(port=port):
        if SSO_URL_MARK in (tab.get("url") or ""):
            return tab
    return None


def wait_for_sso_window(ws=None, max_wait=45, poll_interval=1.0, error_grace=6):
    """Wait for the Samsung SSO window - or for the sign-in to complete
    without one - or for G-MES to say it refused.

    Clicking AD SSO does not always open a window. When a session cookie has
    survived in the profile, G-MES signs straight back in and no SSO page is
    ever shown. Waiting only for the window then fails the whole run with
    "the Samsung SSO window never opened" while the user is, in fact, already
    signed in.

    And it does not always succeed. When G-MES refuses, it writes the reason
    onto its own login form ("Auth bad credentials") and then nothing further
    happens - no window, no session, no error thrown. Waiting the full 45s
    for a window that is never coming, while the reason sits on screen, is
    the difference between a run that explains itself and one that hangs.

    `error_grace` exists because that message can be left over from an
    EARLIER attempt, including one the user made by hand. A real SSO window
    appears within a second or two, so a message still showing after a few
    seconds, with no window and no session, is this attempt's answer whether
    the text is new or not.

    Returns the SSO tab, "already-signed-in", or ("rejected", message)."""
    started = time.time()
    while time.time() - started < max_wait:
        tab = find_sso_window()
        if tab:
            return tab
        if ws is not None:
            try:
                if is_logged_in(ws)[0]:
                    return "already-signed-in"
                message = login_error(ws)
                if message and time.time() - started > error_grace:
                    return ("rejected", message)
            except Exception:
                pass       # still navigating; the socket or document is in flux
        time.sleep(poll_interval)
    return None


def complete_sso(tab, user, password):
    """Fill the Samsung SSO page and submit it.

    The password goes straight from the encrypted store into the browser -
    it is never printed, and never lands in a variable that gets logged."""
    ws = connect(tab["webSocketDebuggerUrl"], timeout=20)
    try:
        # The sign-in form is server-rendered, but wait for it anyway rather
        # than assuming: the window can be registered before it has painted.
        for _ in range(30):
            state = evaluate(ws, """
                (function(){ return JSON.stringify({
                    user: !!document.getElementById('userNameInput'),
                    pw: !!document.getElementById('passwordInput')}); })()""")
            if state.get("user") and state.get("pw"):
                break
            time.sleep(1)
        else:
            return False, "the SSO page never showed its ID and password boxes"

        set_value_by_id(ws, SSO_USER_FIELD, user)
        set_value_by_id(ws, SSO_PW_FIELD, password)

        btn = evaluate(ws, JS_SSO_SUBMIT)
        if not btn.get("found"):
            return False, "could not find the Login button on the SSO page"
        cdp_common.click_element_by_rect(ws, btn["x"], btn["y"])

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
        ws.close()


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

def ensure_browser(show_browser=False):
    if cdp_common.cdp_is_up():
        return "already running"
    if cdp_common.chrome_is_running():
        raise RuntimeError(
            "Chrome is open but not under automation control. Close every "
            "Chrome window (check the system tray) and run this again.")
    cdp_common.launch_chrome_with_user_profile(url=GMES_URL)
    return "started"


def open_gmes():
    tab = gmes_common.gmes_tab()
    if tab is None:
        cdp_common.navigate_page(GMES_URL)
        time.sleep(2)
        tab = gmes_common.gmes_tab()
    if tab is None:
        raise RuntimeError("Could not open the GMES page.")
    return tab


def wait_for_login_or_session(ws, max_wait=240, poll_interval=1.5, verbose=True):
    """Wait until GMES has actually built one of the two screens we can act on.

    Waiting for "readyState complete" or for a raw element count is not
    enough and produced a real failure: the count crossed the threshold while
    the page was still blank white, so the next step went looking for the
    AD SSO button before the login form existed and gave up. Nexacro
    downloads and constructs its whole UI in JavaScript well after the
    document calls itself complete, so the only reliable signal is a
    NAMED control being on screen.

    Returns 'session' (already signed in), 'login' (login form ready), or
    'timeout'."""
    deadline = time.time() + max_wait
    announced = False
    while time.time() < deadline:
        try:
            signed_in, _who = is_logged_in(ws)
            if signed_in:
                return "session"
            if evaluate(ws, gmes_common.js_find_by_id(BTN_SSO)).get("found"):
                return "login"
        except Exception:
            pass       # still navigating; the socket or document is in flux
        if verbose and not announced:
            print("Waiting for the GMES app to build itself...")
            announced = True
        time.sleep(poll_interval)
    return "timeout"


def main(show_browser=False, status_only=False):
    print("=" * 70)
    print("GMES login")
    print("=" * 70)

    if not status_only:
        try:
            print(f"Browser: {ensure_browser(show_browser)}")
        except RuntimeError as e:
            print(f"ERROR: {e}")
            return FAILED
        open_gmes()

    ws = connect_gmes()
    try:
        state = wait_for_login_or_session(ws, verbose=not status_only)
        if state == "timeout" and not status_only:
            print("ERROR: GMES showed neither the login form nor a signed-in "
                  "session within 4 minutes.")
            cdp_common.screenshot_on_failure("gmes_never_loaded")
            return FAILED

        signed_in, who = is_logged_in(ws)
        if status_only:
            print(f"Signed in : {signed_in}" + (f" as {who!r}" if who else ""))
            message = login_error(ws)
            if message:
                print(f"Login page says: {message!r}")
            popups = gmes_common.find_child_popups(ws)
            print(f"Popups open: {popups.get('count')} {[p['name'] for p in popups.get('popups', [])]}")
            return OK

        was_already_signed_in = signed_in
        if signed_in:
            print(f"Already signed in as {who!r}.")
        else:
            user, password = gmes_credentials.load()
            if not user or not password:
                print("\nERROR: no saved credentials. Run this once:")
                print("    python gmes_credentials.py set")
                return REJECTED     # retrying cannot conjure a password

            print(f"Signing in as {user!r} via AD SSO...")
            windows_before = {t["id"] for t in list_windows()}
            if not click_by_id(ws, BTN_SSO):
                print("ERROR: the 'AD SSO Login' button was not on screen.")
                cdp_common.screenshot_on_failure("gmes_no_sso_button")
                return FAILED

            sso_tab = wait_for_sso_window(ws)

            if isinstance(sso_tab, tuple) and sso_tab[0] == "rejected":
                print(f"\nERROR: G-MES refused the sign-in and says: "
                      f"{sso_tab[1]!r}")
                print("\n  Nothing is wrong with the automation - the account or "
                      "the saved password\n  was not accepted. Check which user "
                      "is stored, and re-save it:")
                print("      python gmes_credentials.py show")
                print("      python gmes_credentials.py set")
                print("  If signing in by hand on the same page fails too, the "
                      "account itself\n  needs attention (expired or locked "
                      "password) - not this tool.")
                cdp_common.screenshot_on_failure("gmes_login_rejected")
                return REJECTED

            if sso_tab is None:
                message = login_error(ws)
                print("ERROR: the Samsung SSO window never opened, and the "
                      "session did not sign in on its own."
                      + (f" The login page says: {message!r}" if message else ""))
                cdp_common.screenshot_on_failure("gmes_no_sso_window")
                return FAILED

            if sso_tab == "already-signed-in":
                print("No SSO window was needed - the saved session signed in.")
            else:
                print("SSO window opened; filling in the saved credentials...")
                ok, detail = complete_sso(sso_tab, user, password)
                if not ok:
                    print(f"ERROR: {detail}")
                    cdp_common.screenshot_on_failure("gmes_sso_failed")
                    # Samsung ADFS saying no is a rejection, not a hiccup:
                    # sending the same password again gets the same answer and
                    # walks the account closer to being locked.
                    return REJECTED if "rejected" in detail else FAILED
                print("Credentials submitted; waiting for GMES to come up...")

            # Watch for the refusal as well as the success. Polling only for
            # "signed in" spends the full two minutes on a sign-in that was
            # already rejected in the first second.
            deadline = time.time() + 120
            signed_in = False
            while time.time() < deadline:
                if is_logged_in(ws)[0]:
                    signed_in = True
                    break
                message = login_error(ws)
                if message:
                    print(f"\nERROR: G-MES refused the sign-in and says: {message!r}")
                    print("  Check the stored login:  python gmes_credentials.py show")
                    cdp_common.screenshot_on_failure("gmes_login_rejected")
                    return REJECTED
                time.sleep(1.5)

            if not signed_in:
                print("ERROR: still not signed in after 2 minutes.")
                cdp_common.screenshot_on_failure("gmes_login_timeout")
                return FAILED

            signed_in, who = is_logged_in(ws)
            print(f"Signed in as {who!r}.")

        # The Notice window blocks everything behind it, so clearing it is
        # part of signing in rather than a separate step.
        #
        # But WAIT for it only after an actual sign-in. It arrives a few
        # seconds after the user name appears, so a fresh sign-in has to
        # watch for it. On a session that was already signed in, that
        # popup was dealt with when the session started - any popup now
        # would already be on screen, so waiting 45s for one to turn up
        # achieved nothing and cost ~59 seconds on EVERY command, since
        # every tool calls this first.
        if was_already_signed_in:
            closed = gmes_common.close_child_popups(ws)
            print(f"Popups: {closed if closed else 'none open'}")
        else:
            print("Watching for notice popups (they arrive a few seconds "
                  "after sign-in)...")
            closed = gmes_common.close_popups_when_they_appear(ws)
            print(f"Popups closed: {closed if closed else 'none appeared'}")

        left = gmes_common.find_child_popups(ws)
        if left.get("count"):
            print(f"WARNING: {left['count']} popup(s) still on screen: "
                  f"{[p['name'] for p in left['popups']]}")

        shot = cdp_common.capture_screenshot("gmes_ready.png")
        print(f"\nReady. Screenshot: {shot}")
        return OK
    finally:
        ws.close()


if __name__ == "__main__":
    sys.exit(main(show_browser="--show-browser" in sys.argv,
                  status_only="--status" in sys.argv))
