"""Unattended sign-in: is a session already up, or does the login page
need working, and clearing the Notice popups once it's signed in.

Forked from gmes_login.py (ensure_browser, open_gmes,
wait_for_login_or_session, wait_for_manual_sign_in) and gmes_common.py
(is_logged_in). `is_logged_in` lives here rather than nexacro/ per the
migration plan, even though it's a plain DOM read, because the plan
treats "are we signed in" as a session-state question, not a generic
element lookup - see login_flow.py's docstring for how the resulting
mutual dependency between this module and login_flow.py is broken.
"""
import time

from ..application.connect_uc import connect_gmes, gmes_tab
from ..browser.cdp import cdp_is_up, evaluate, navigate_page, send
from ..browser.chrome import (
    chrome_is_running, close_browser, launch_chrome_with_user_profile,
)
from ..config import GMES_URL
from ..nexacro.app_state import app_is_built, prune_nexacro_cache, storage_state
from ..nexacro.dom import js_find_by_id
from .login_flow import BTN_SSO, login_error

# The signed-in user's name sits in the top bar. Testing for THIS is
# right; testing for the absence of the Login button is not - Nexacro
# keeps the login frame in the DOM after signing in, merely hidden, so
# "no login button" never becomes true and the check would report a
# failed login forever.
USER_INFO_BTN = "mainframe.vFrameSet1.vFrameSet2.topFrame.form.btnUserInfo"


def is_logged_in(ws):
    info = evaluate(ws, js_find_by_id(USER_INFO_BTN))
    return bool(info.get("found")), info.get("text", "")


def wait_for_manual_sign_in(ws, max_wait=420, poll_interval=2.0):
    """Hold while a person signs in themselves, in the automation
    browser.

    This is the supported answer to an AD SSO that will not complete on
    its own. Observed on this account: clicking AD SSO sometimes opens
    the Samsung ADFS page and sometimes makes G-MES answer 'Auth bad
    credentials' outright, with no window and nothing to wait for.

    A person signing in once solves it completely, because the session
    then lives in the profile copy and every later run reuses it.

    Nothing is typed for them. Whatever Chrome has saved is Chrome's
    business; this only watches for the signed-in state to appear."""
    print()
    print("=" * 70)
    print("  PLEASE SIGN IN, IN THE BROWSER WINDOW THAT IS NOW OPEN")
    print("=" * 70)
    print("  Use whichever way works for you - 'AD SSO Login', or the ID and")
    print("  password boxes with the password Chrome has saved.")
    print()
    print("  Nothing is typed for you and no password is read.")
    print(f"  Waiting up to {max_wait // 60} minutes, checking every {poll_interval:.0f}s...")
    print()

    started = time.time()
    announced = 0
    while time.time() - started < max_wait:
        try:
            signed_in, who = is_logged_in(ws)
            if signed_in:
                print(f"  Signed in as {who!r}. Thank you - carrying on.")
                return True
        except Exception:
            # Mid-navigation through ADFS is normal and passes. A browser
            # that has GONE is not: without this check the wait sat
            # happily for its full seven minutes polling a browser that
            # had been closed, and then blamed the person for not
            # signing in.
            if not cdp_is_up():
                print("\n  The browser window was closed, so there is nothing "
                      "to sign in to.")
                print("  Start it again with:  gmes login --assist")
                return False

        waited = int(time.time() - started)
        if waited // 30 > announced:
            announced = waited // 30
            print(f"  ...still waiting ({waited}s). The window is open behind this one.")
        time.sleep(poll_interval)

    print("  Nobody signed in within the time allowed.")
    return False


def ensure_browser(show_browser=False, refresh_profile=False):
    """Make sure the automation browser is up.

    `refresh_profile` re-copies the user's real Chrome profile over the
    debuggable copy. That is what brings a CURRENT signed-in session and
    the passwords Chrome has saved into the automated browser - and it
    DESTROYS whatever session the copy already had, so it is a
    last-resort operation, not a routine one (HISTORY.md Phase 20)."""
    if refresh_profile:
        print("NOTE: this replaces the automated browser's profile, INCLUDING "
              "the G-MES session\n      that lets it sign in instantly. Only "
              "do this if sign-in is already failing.")
        # Both browsers have to be closed: ours because it holds the copy
        # open, and the user's because Chrome keeps its cookie and
        # password databases locked while it runs - copying them then
        # yields a profile missing the very session the refresh is for.
        if cdp_is_up():
            print("Closing the automation browser so its profile can be replaced...")
            close_browser()
        if chrome_is_running():
            raise RuntimeError(
                "Close every Chrome window first (check the system tray), then "
                "run this again. Chrome keeps its saved logins and cookies "
                "locked while it is running, so they cannot be copied - and "
                "those are exactly what this needs.")
        launch_chrome_with_user_profile(url=GMES_URL, refresh_profile=True)
        return "profile refreshed from your own Chrome, browser started"

    if cdp_is_up():
        return "already running"

    # Your own Chrome being open is NOT a conflict. The automation runs
    # on a separate copy of the profile, and Chrome happily runs a
    # second instance on a different --user-data-dir (measured with 30
    # of the user's own chrome.exe processes running).
    if chrome_is_running():
        print("(your own Chrome is open - that is fine, the automation uses "
              "its own separate profile)")
    launch_chrome_with_user_profile(url=GMES_URL)
    return "started"


def open_gmes():
    tab = gmes_tab()
    if tab is None:
        navigate_page(GMES_URL)
        tab = gmes_tab()
    if tab is None:
        raise RuntimeError("Could not open the GMES page.")
    return tab


def wait_for_login_or_session(ws, max_wait=240, poll_interval=1.5, verbose=True):
    """Wait until GMES has actually built one of the two screens we can
    act on.

    Waiting for "readyState complete" or for a raw element count is not
    enough: Nexacro downloads and constructs its whole UI in JavaScript
    well after the document calls itself complete, so the only reliable
    signal is a NAMED control being on screen.

    Returns (state, ws) where state is 'session' (already signed in),
    'login' (login form ready) or 'timeout'. The websocket comes back
    because this may have had to replace it.

    A few failures in a row mean the connection is gone, not that the
    page is busy, and it reattaches - swallowing every exception here is
    what made an earlier version of this look frozen (HISTORY.md Phase
    21.6)."""
    started = time.time()
    announced, errors, swept = 0, 0, False
    while time.time() - started < max_wait:
        try:
            signed_in, _who = is_logged_in(ws)
            if signed_in:
                return "session", ws
            if evaluate(ws, js_find_by_id(BTN_SSO)).get("found"):
                return "login", ws
            errors = 0

            # Neither control is there. Is the application even building,
            # or has it failed to start? Those look identical from
            # outside - both are a blank page - and the usual cause of
            # the second is G-MES's engine cache filling localStorage
            # until its own bootstrap throws QuotaExceededError. Swept
            # once, then the page is reloaded.
            if not swept and time.time() - started > 20 \
                    and not app_is_built(ws):
                state = storage_state(ws)
                if verbose:
                    print(f"  the G-MES application has not started. "
                          f"Storage: {state.get('bytes', 0) / 1048576:.2f} MB, "
                          f"{state.get('engineCopies', 0)} cached engine copies.")
                pruned = prune_nexacro_cache(ws)
                swept = True
                if pruned.get("removed"):
                    if verbose:
                        print(f"  cleared {pruned['removed']} stale engine "
                              f"cache entries ({pruned['freed'] / 1048576:.2f} MB) "
                              f"and reloading the page...")
                    try:
                        send(ws, "Page.reload", {"ignoreCache": True})
                    except Exception:
                        pass
                elif verbose:
                    print("  nothing stale in the engine cache - the page is "
                          "just slow, still waiting.")
        except Exception:
            errors += 1
            if errors >= 3:
                if verbose:
                    print("  (lost the connection to the page - reattaching)")
                try:
                    ws.close()
                except Exception:
                    pass
                try:
                    ws = connect_gmes()
                    errors = 0
                except Exception:
                    pass       # browser may still be starting; try again shortly

        waited = int(time.time() - started)
        if verbose and waited // 15 > announced:
            announced = waited // 15
            print(f"  still waiting for G-MES to finish loading ({waited}s)...")
        time.sleep(poll_interval)
    return "timeout", ws
