"""Sign-in policy over browser/auth primitives, independent of command parsing."""
import time
from dataclasses import replace
from datetime import datetime, timedelta

from ..auth import credentials, login_flow, session
from ..browser import screenshots
from ..contracts import LoginAttempt, LoginOutcome
from ..nexacro import popups
from ..screens.filters import normalise_date
from .connect_uc import connect_gmes


def date_from_args(date=None, days_back=None):
    """Resolve explicit dates or caller-requested arithmetic; no implicit default."""
    if days_back is not None:
        return (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")
    return normalise_date(date)


def sign_in(attempts=2, log=print, **kwargs):
    """Retry only FAILED. Each attempt observes readiness before interacting.

    There is no blind delay between attempts: the auth/session readiness polls
    establish when a new attempt can proceed. REJECTED is always terminal.
    """
    if attempts < 1:
        raise ValueError("attempts must be at least one")
    for number in range(1, attempts + 1):
        result = sign_in_once(log=log, **kwargs)
        if not isinstance(result, LoginAttempt) or not isinstance(result.outcome, LoginOutcome):
            raise TypeError("sign_in_once must return LoginAttempt with a LoginOutcome")
        result = replace(result, attempts_used=number)
        if result.outcome is not LoginOutcome.FAILED:
            return result
        if number < attempts:
            log(f"Sign-in attempt {number} did not complete; retrying after checking readiness...")
    return result


def _wait_signed_in(ws, timeout, message=""):
    """A stale login message never outranks a session that is still arriving."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if session.is_logged_in(ws)[0]:
            return True, message
        message = login_flow.login_error(ws) or message
        time.sleep(1.5)
    return False, message


def _authenticate(ws, log):
    user, password = credentials.load()
    if not user or not password:
        return LoginAttempt(LoginOutcome.REJECTED, "no saved credentials")
    if not login_flow.click_by_id(ws, login_flow.BTN_SSO):
        screenshots.screenshot_on_failure("gmes_no_sso_button")
        return LoginAttempt(LoginOutcome.FAILED, "the AD SSO Login button was not on screen")

    tab = login_flow.wait_for_sso_window(ws)
    message, promising = "", False
    if isinstance(tab, tuple) and tab[0] == "rejected":
        message = tab[1]
        log("AD SSO did not complete; checking the session before using the login form.")
    elif tab == "already-signed-in":
        promising = True
    elif tab is not None:
        promising, detail = login_flow.complete_sso(tab, user, password)
        if not promising:
            log(f"The SSO page could not be completed: {detail}")

    signed_in, message = _wait_signed_in(ws, 120 if promising else 5, message)
    if not signed_in:
        log("AD SSO did not complete. Trying G-MES's own login form.")
        submitted, detail = login_flow.direct_login(ws, user, password)
        if submitted:
            signed_in, message = _wait_signed_in(ws, 60, message)
        else:
            log(f"The login form could not be used: {detail}")
    if signed_in:
        return LoginAttempt(LoginOutcome.OK)
    screenshots.screenshot_on_failure("gmes_login_rejected" if message else "gmes_login_timeout")
    return LoginAttempt(LoginOutcome.REJECTED if message else LoginOutcome.FAILED,
                        message or "still not signed in after the sign-in waits")


def sign_in_once(show_browser=False, refresh_profile=False, assist=False, log=print):
    """One legacy sign-in attempt, with no CLI parsing or credential prompting."""
    try:
        log(f"Browser: {session.ensure_browser(show_browser, refresh_profile)}")
        session.open_gmes()
        ws = connect_gmes()
    except RuntimeError as error:
        return LoginAttempt(LoginOutcome.FAILED, str(error))
    try:
        state, ws = session.wait_for_login_or_session(ws)
        if state == "timeout":
            screenshots.screenshot_on_failure("gmes_never_loaded")
            return LoginAttempt(LoginOutcome.FAILED, "G-MES showed neither login nor session")
        if state not in ("login", "session"):
            raise RuntimeError(f"unknown G-MES readiness state: {state!r}")
        signed_in, _who = session.is_logged_in(ws)
        was_signed_in = signed_in
        if not signed_in:
            if assist:
                if not session.wait_for_manual_sign_in(ws):
                    screenshots.screenshot_on_failure("gmes_assist_timeout")
                    return LoginAttempt(LoginOutcome.FAILED, "manual sign-in timed out")
            else:
                result = _authenticate(ws, log)
                if result.outcome is not LoginOutcome.OK:
                    return result
        if was_signed_in:
            closed = popups.close_child_popups(ws)
        else:
            closed = popups.close_popups_when_they_appear(ws)
        log(f"Popups closed: {closed or 'none'}")
        left = popups.find_child_popups(ws)
        if left.get("count"):
            log(f"WARNING: {left['count']} popup(s) still on screen")
        screenshots.capture_screenshot("gmes_ready.png")
        return LoginAttempt(LoginOutcome.OK)
    finally:
        ws.close()
