"""
GMES login - unattended.

    python gmes_login.py                    # open GMES, sign in, clear popups
    python gmes_login.py --show-browser     # same, but watch it happen
    python gmes_login.py --status           # just report where we are
    python gmes_login.py --refresh-profile  # re-copy your Chrome profile first
    python gmes_login.py --assist           # you sign in by hand, once
    python gmes_login.py --allow-password-login   # see the warning below

**A failed corporate sign-in is not a failed password.** If AD SSO does not
complete, this stops. It does NOT fall through to typing the saved password
into G-MES's own login form, because that form counts every refusal against
a five-attempt lockout, and an SSO window that never opened says nothing
about whether the password is right. `--allow-password-login` permits one
such attempt, deliberately off by default (HISTORY.md Phase 74).

`--refresh-profile` re-copies your real Chrome profile over the automated
browser's copy. Every Chrome window must be closed first, because Chrome
keeps its cookie and login databases locked while it runs.

**Use it only as a last resort.** The G-MES session that makes sign-in
instant lives in the COPY, and refreshing OVERWRITES it - so a browser that
was signing in by itself stops doing so, and has to authenticate for real
again. That is exactly what happened once here: a refresh threw away a
working session, and the sign-in failures that followed were then blamed on
the password and the account. If sign-in is working, leave the profile
alone.

Designed to run at night with nobody watching, so it never asks a question:
the credentials come from the encrypted store (gmes_credentials.py), and
every wait polls for the thing it needs instead of sleeping a guessed
number of seconds.

The flow it handles, in order:
  1. No automation browser running         -> start it on the tool's own
                                              profile (built on the first run
                                              from the Chrome/Edge profile you
                                              already use - HISTORY.md Phase 75).
  2. Not on GMES                           -> navigate there.
  3. Already signed in                     -> skip straight to step 6.
  4. GMES login screen                     -> click "AD SSO Login".
  5. Samsung SSO sign-in page              -> fill ID + password, submit.
  6. Notice popups covering the screen     -> close each one by its X.
"""
import sys
import time

import cdp_common
import gmes_browsers
import gmes_common
import gmes_credentials
from gmes_common import (
    GMES_URL, click_by_id, close_child_popups, connect_gmes, is_logged_in,
    list_windows, print_report, screen_report, set_value_by_id, wait_until,
)
from cdp_common import connect, evaluate, send

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


# The pre-signin login form's own English/Korean toggle. Safe to hardcode:
# loginFrame is a fixed shell path (LOGIN_FORM, above), never renumbered.
STA_ENG = f"{LOGIN_FORM}.staEng"
STA_KOR = f"{LOGIN_FORM}.staKor"

JS_LOGIN_LANGUAGE_IS_ENGLISH = """
(function() {
    const isVisible = %s;
    const eng = document.getElementById(%s);
    const kor = document.getElementById(%s);
    if (!eng || !kor || !isVisible(eng) || !isVisible(kor)) {
        return JSON.stringify({found: false});
    }
    // Live-verified both directions (HISTORY.md Phase 77): whichever of the
    // two toggle statics is NOT currently selected carries a 'V2' suffix on
    // this component's own class (sta_Login_LanguageV2 vs sta_Login_Language).
    // Backwards from what the name suggests, but Nexacro swaps the class
    // between the two elements as the selection changes, not once per
    // element - confirmed live by toggling English -> Korean -> English and
    // watching the suffix move each time.
    const engCls = (typeof eng.className === 'string') ? eng.className : '';
    const korCls = (typeof kor.className === 'string') ? kor.className : '';
    const engSelected = !/V2/.test(engCls);
    const korSelected = !/V2/.test(korCls);
    // Exactly one of the two must be selected. A bare "not V2" check on ONE
    // element alone (the original version of this probe) cannot tell "English
    // is selected" apart from "neither toggle carries the suffix right now" -
    // an unrecognized state this project refuses to guess through
    // (CLAUDE.md 3.9), rather than risk clicking English and actually landing
    // on Korean with nothing to say so (Phase 77.3 review finding).
    if (engSelected === korSelected) {
        return JSON.stringify({found: true, ambiguous: true});
    }
    return JSON.stringify({found: true, ambiguous: false, english: engSelected});
})()
""" % (cdp_common.JS_IS_VISIBLE, cdp_common.json.dumps(STA_ENG), cdp_common.json.dumps(STA_KOR))


def ensure_login_language_english(ws, verify_wait=5):
    """Switch the pre-signin LOGIN FORM to English, if it is not already.

    This is the login page shown before any credential is submitted - not the
    signed-in application, whose language is a separate, account-side setting
    (`gvLanguage`) this project deliberately does not touch (HISTORY.md
    Phase 76.5; CLAUDE.md 2.5 forbids writing a value in the target system
    without explicit confirmation, and doing this every run IS that
    confirmation, given by the project owner - HISTORY.md Phase 77).

    **Verified live to be purely cosmetic.** `Network.enable` plus a 3-second
    capture around the click saw zero requests: the click swaps an
    already-downloaded message bundle client-side and writes nothing to the
    server. That is what makes it safe to do unconditionally on every run,
    unlike `gvLanguage`, which the login page never touches at all.

    It does **not** persist across a reload or a fresh navigation (no cookie,
    no localStorage key holds it - Phase 74.3 already established that), so
    this runs every time a fresh login form is reached, not once. A failure
    here is never fatal to signing in: the label language has no bearing on
    which control gets clicked, since every one of them is already addressed
    by a fixed id or class, never by text (CLAUDE.md 3.3).

    The probe requires both toggle statics to be visible and in the viewport
    (the same test `click_by_id()` itself applies before clicking) rather than
    a bare `getElementById` - without that, a control merely present but not
    yet positioned (some Nexacro menus pre-render off-screen at
    y = -99984 before their real layout runs - CLAUDE.md 3.3) would report
    `found: true` here while `click_by_id()` correctly refuses to click it,
    silently burning most of its own poll budget for nothing.

    Returns a short string for the log, or None when there is nothing to do -
    no toggle visible yet (an already-signed-in session shows no login form at
    all), the state is ambiguous (see the JS above), or the probe itself
    failed. Like `login_error()`/`lockout_warning()` above, anything
    unexpected here is swallowed rather than allowed to abort a sign-in over a
    cosmetic feature."""
    try:
        check = evaluate(ws, JS_LOGIN_LANGUAGE_IS_ENGLISH)
    except Exception:
        return None
    if not check.get("found") or check.get("ambiguous"):
        return None
    if check.get("english"):
        return "already English"

    # A short budget, not the default 10s (20 attempts x 0.5s): by the time
    # `state == "login"` was confirmed, `wait_for_login_or_session()` has
    # already waited for the SSO button on this same, already-rendered form to
    # become visible, so the language toggle rendered in the same pass is
    # very unlikely to still be settling.
    try:
        info = click_by_id(ws, STA_ENG, attempts=6, delay=0.5)
    except Exception:
        info = None
    if not info:
        return "the language toggle was not found to click"

    deadline = time.time() + verify_wait
    while time.time() < deadline:
        time.sleep(0.3)
        try:
            check = evaluate(ws, JS_LOGIN_LANGUAGE_IS_ENGLISH)
        except Exception:
            continue
        if check.get("found") and not check.get("ambiguous") and check.get("english"):
            return "switched to English"
    return "clicked English but could not confirm the switch"


def login_error(ws):
    """Whatever G-MES is displaying on its own login form, e.g.
    'Auth bad credentials'.

    **This is a diagnostic string and nothing more.** It must never be used
    to conclude that the credentials are wrong. The element it reads has been
    observed live carrying "아이디 또는 패스워드를 확인하세요." ("check your ID
    or password") on a page where NOTHING had been submitted - it appeared
    after a click on the language toggle alone (HISTORY.md Phase 74). A
    string that can be present without any sign-in attempt cannot be evidence
    about a sign-in attempt. `lockout_warning()` below is the signal that
    actually means something."""
    try:
        info = evaluate(ws, gmes_common.js_find_by_id(ERR_MSG))
        return (info.get("text") or "").strip() if info.get("found") else ""
    except Exception:
        return ""


# The one unambiguous "the server refused these credentials" signal.
#
# G-MES answers a failed form login with a modal that COUNTS, observed live
# on 2026-09-15:
#
#     아이디 또는 비밀번호가 일치하지 않습니다.
#     5회 불일치할 경우 로그인이 제한됩니다.(시도횟수1/5)
#
#     "ID or password does not match. If it does not match 5 times, login
#      will be restricted. (attempt count 1/5)"
#
# This is a real, server-generated modal that appears ONLY after a real
# submission, and it is the difference between "something went wrong" and
# "this account is now one step closer to being locked out". Anything that
# sees this must stop immediately and must not try again - the next four
# attempts are all that stand between the account and a lockout.
# The three English-language MARKERS below (attempt\s*count etc.) are
# translated GUESSES, never observed live - correctly so, because observing
# the real wording would mean deliberately failing a login in English to see
# it, which spends the exact lockout attempt this function exists to protect
# (HISTORY.md Phase 74). Since HISTORY.md Phase 77 switches the login page to
# English by default, an actual refusal is now more likely to be RENDERED in
# English than in Korean, and untranslated guesses are the same category of
# risk this project exists to refuse: a silent miss that looks like "nothing
# happened" rather than an error (Phase 77.3 review finding).
#
# So the primary signal is now STRUCTURAL, not lexical: the counter itself,
# "(N/M)" - observed live as "(시도횟수1/5)" - in parentheses immediately after
# digits and a slash. That shape does not depend on which language surrounds
# it, and nothing else on a bare login form is expected to render one. The
# language-specific MARKERS remain as a second, independent path - keeping both
# means either alone missing the real wording still leaves the other.
JS_LOCKOUT_WARNING = """
(function() {
    const isVisible = %s;
    const MARKERS = [/시도횟수/, /로그인이\\s*제한/, /일치하지\\s*않습니다/,
                     /attempt\\s*count/i, /will\\s*be\\s*restricted/i,
                     /account\\s*(is\\s*)?locked/i, /login\\s*is\\s*restricted/i,
                     /\\(\\s*\\d+\\s*\\/\\s*\\d+\\s*\\)/];
    for (const el of document.querySelectorAll('div, span, td')) {
        if (!isVisible(el)) continue;
        const t = (el.textContent || '').trim();
        if (!t || t.length > 300) continue;
        if (!MARKERS.some(rx => rx.test(t))) continue;
        const counter = t.match(/(\\d+)\\s*\\/\\s*(\\d+)/);
        return JSON.stringify({found: true,
                               text: t.replace(/\\s+/g, ' ').slice(0, 200),
                               used: counter ? Number(counter[1]) : null,
                               limit: counter ? Number(counter[2]) : null});
    }
    return JSON.stringify({found: false});
})()
""" % cdp_common.JS_IS_VISIBLE


def lockout_warning(ws):
    """Is G-MES counting a failed credential attempt right now?

    Returns {found, text, used, limit}. `found` true means a real submission
    was refused and the account's lockout counter has moved - the run must
    stop, and must NOT retry (HISTORY.md Phase 56.1: repeated attempts with a
    password the server is refusing is how an account gets locked)."""
    try:
        return evaluate(ws, JS_LOCKOUT_WARNING)
    except Exception:
        return {"found": False}


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


# G-MES's own login form, beside the AD SSO button. These ids are safe to
# hardcode: loginFrame is a shell frame, and there is only ever one of it
# (GMES_SKILL #7 - only work-screen ids are renumbered).
USER_FIELD = f"{LOGIN_FORM}.edUserID"
PW_FIELD = f"{LOGIN_FORM}.edPassword"

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


def direct_login(ws, user, password):
    """Sign in with G-MES's own ID and password form.

    The fallback for an AD SSO that will not complete. G-MES puts a plain
    login form right beside the SSO button, and the stored credentials are
    for the same account, so there is no reason to be stuck on a page that is
    asking for exactly what we already hold.

    The password goes from the encrypted store straight into the browser. It
    is never printed, never returned by the JavaScript above, and never
    reaches a log line."""
    filled = evaluate(ws, JS_DIRECT_LOGIN % (cdp_common.json.dumps(user),
                                             cdp_common.json.dumps(password)))
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

    A message on the page NEVER decides anything, and an earlier version of
    this let it. It returned "rejected" as soon as 'Auth bad credentials' had
    been showing for a few seconds - while the Samsung ADFS window was still
    on its way, and while the message itself was often left over from a
    previous attempt. That false alarm cost three wrong diagnoses and a
    needless manual sign-in.

    **The outcome is deliberately named "no-window", not "rejected"**
    (HISTORY.md Phase 74). The SSO window failing to appear says nothing
    whatsoever about whether the credentials are good: the window can be
    swallowed by a Chrome popup policy (GMES_SKILL #51), lost to a network
    problem, or - live-observed - simply not appear when the same account is
    being signed in from a second browser profile. Calling that "rejected"
    is what led the caller to "fix" it by submitting a password, which
    burned a real attempt against the account's lockout counter for a
    password that was almost certainly correct.

    The logic:

        signed in            -> done, whatever the page says
        an SSO window        -> go and fill it in
        neither, for the full wait -> ("no-window", whatever the page said)
                                      where the message is a DIAGNOSTIC only

    Returns the SSO tab, "already-signed-in", or ("no-window", message)."""
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

    # Nothing arrived in the whole window. The message, if any, is context
    # for a human reading the log - not a verdict on the credentials.
    return ("no-window", seen_message)


JS_SSO_FORM_READY = """
    (function(){ return JSON.stringify({
        user: !!document.getElementById('userNameInput'),
        pw: !!document.getElementById('passwordInput')}); })()"""


def complete_sso(tab, user, password):
    """Fill the Samsung SSO page and submit it.

    The password goes straight from the encrypted store into the browser - it
    is never printed, and never lands in a variable that gets logged.

    The connection is re-established rather than assumed. ADFS redirects
    several times while it settles, and each redirect can tear the DevTools
    session down: attaching once and evaluating in a loop crashed the whole
    sign-in with `ConnectionAbortedError [WinError 10053]` just as the window
    appeared. A dropped socket here means the page moved, which is normal -
    only the window actually going away is a failure."""
    def attach():
        fresh = find_sso_window() or tab
        return connect(fresh["webSocketDebuggerUrl"], timeout=20)

    try:
        ws = attach()
    except Exception as e:
        return False, f"could not attach to the SSO page ({e})"

    try:
        # The sign-in form is server-rendered, but wait for it anyway rather
        # than assuming: the window can be registered before it has painted.
        ready = False
        for _ in range(40):
            try:
                state = evaluate(ws, JS_SSO_FORM_READY)
                if state.get("user") and state.get("pw"):
                    ready = True
                    break
            except Exception:
                if find_sso_window() is None:
                    # It closed by itself, which is what a successful silent
                    # sign-in looks like. The caller checks for a session.
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
            cdp_common.click_element_by_rect(ws, btn["x"], btn["y"])
        except Exception as e:
            if find_sso_window() is None:
                return True, "the SSO window closed while being filled in"
            return False, f"the SSO page could not be filled in ({e})"

        # Poll for either an error message to render or the window to leave -
        # not a fixed sleep, then one look (HISTORY.md Phase 79.5). A
        # successful sign-in redirects the window away almost immediately, so
        # a real poll exits on the FAST path most of the time; a bad
        # password's error message is server-rendered and can legitimately
        # take a moment, which is what the cap is for.
        deadline = time.time() + 5
        err = ""
        while time.time() < deadline:
            try:
                err = evaluate(ws, JS_SSO_ERROR).get("text", "")
            except Exception:
                err = ""     # the window is already navigating away - that is good
                break
            if err:
                break
            if find_sso_window() is None:
                break        # gone - the redirect completed
            time.sleep(0.3)
        if err:
            return False, f"SSO rejected the sign-in: {err!r}"
        return True, "submitted"
    finally:
        try:
            ws.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

def wait_for_manual_sign_in(ws, max_wait=420, poll_interval=2.0):
    """Hold while a person signs in themselves, in the automation browser.

    This is the supported answer to an AD SSO that will not complete on its
    own. Observed on this account: clicking AD SSO sometimes opens the Samsung
    ADFS page and sometimes makes G-MES answer 'Auth bad credentials' outright,
    with no window and nothing to wait for. Measured after one such refusal:
    75 seconds of polling, no SSO window ever appeared.

    A person signing in once solves it completely, because the session then
    lives in the profile copy and every later run reuses it - which is exactly
    what every successful run on this project has actually been doing
    ("No SSO window was needed - the saved session signed in").

    Nothing is typed for them and nothing saved is read; this only watches for
    the signed-in state to appear.

    Note the automation profile deliberately does NOT carry the browser's saved
    passwords - the first-run copy excludes them (HISTORY.md Phase 75.8), so
    there is no autofill to offer here and the text below must not promise
    any."""
    print()
    print("=" * 70)
    print("  PLEASE SIGN IN, IN THE BROWSER WINDOW THAT IS NOW OPEN")
    print("=" * 70)
    print("  Use whichever way works for you - 'AD SSO Login', or type your ID")
    print("  and password into the form.")
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
            # that has GONE is not: without this check the wait sat happily
            # for its full seven minutes polling a browser that had been
            # closed, and then blamed the person for not signing in.
            if not cdp_common.cdp_is_up():
                print("\n  The browser window was closed, so there is nothing "
                      "to sign in to.")
                print("  Start it again with:  python gmes_login.py --assist")
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

    By default this launches the profile THIS TOOL owns
    (`cdp_common.automation_profile_dir()`). On the very first run that
    profile is built by copying the Chrome or Edge profile the employee
    already uses - on this machine only, reading their real profile and never
    touching it - so a G-MES session they are already signed in with comes
    across and the run goes straight through (HISTORY.md Phase 75). If there
    is nothing usable to copy from, it is created empty exactly as it was in
    Phase 73 and the first sign-in is a real one.

    Either way the copy happens ONCE. Every run after it reuses the session
    living in that profile, and nothing looks at the user's real profile
    again.

    A copied profile still cannot be moved to another PC - Chrome 140+ binds
    cookie encryption to the machine (HISTORY.md Phase 73) - which is why the
    bootstrap records which machine it ran on and sets a different PC up
    separately rather than reusing a copy that would silently decrypt nothing.

    `refresh_profile` is the escape hatch to the OLD strategy - re-copying the
    user's real Chrome profile over the debuggable copy, bringing its current
    session and saved passwords with it. It stays available because it is
    sometimes the answer (CLAUDE.md 2.1a), and it runs only when a person
    explicitly asks for it in that run."""
    if refresh_profile:
        print("NOTE: this replaces the automated browser's profile, INCLUDING "
              "the G-MES session\n      that lets it sign in instantly. Only "
              "do this if sign-in is already failing.")
        # Both browsers have to be closed: ours because it holds the copy
        # open, and the user's because Chrome keeps its cookie and password
        # databases locked while it runs - copying them then yields a profile
        # missing the very session the refresh is for.
        if cdp_common.cdp_is_up():
            print("Closing the automation browser so its profile can be replaced...")
            cdp_common.close_browser()
        if cdp_common.chrome_is_running():
            raise RuntimeError(
                "Close every Chrome window first (check the system tray), then "
                "run this again. Chrome keeps its saved logins and cookies "
                "locked while it is running, so they cannot be copied - and "
                "those are exactly what this needs.")
        cdp_common.launch_chrome_with_user_profile(url=GMES_URL, refresh_profile=True)
        return "profile refreshed from your own Chrome, browser started"

    # Deliberately NOT a bare `cdp_is_up()` pre-check here. That asks "is
    # ANY browser answering on the port we would resolve to", which with an
    # OS-assigned port falls back to the historical 9444 when this tool's
    # profile has never been launched - so a leftover browser on the OLD
    # copied profile would answer, be reported as "already running", and the
    # whole run would proceed against a profile this code no longer intends
    # to drive. `launch_automation_chrome()` asks the narrower and correct
    # question - is a browser serving THIS profile - and returns None when
    # there is, so the decision belongs there and only there.
    #
    # Your own browser being open is not a conflict once the tool has its own
    # profile: the automation runs on its own --user-data-dir, and Chromium
    # happily runs a second instance on one. Measured with 30 of the user's
    # own chrome.exe processes running (GMES_SKILL.md #44). Telling someone to
    # close every window they have open, to run a report, was a real cost for
    # no reason.
    #
    # The ONE exception is the very first run, which copies the profile they
    # already use - and a browser holds the files carrying that session open
    # while it runs. So the reassurance is printed only when there is already
    # a profile, and the first run is left to say its own, opposite thing
    # (HISTORY.md Phase 75). Printing both would tell someone their open
    # browser was fine and then immediately fail because it was not.
    onboarded = gmes_browsers.recorded_profile_dir()
    if onboarded:
        open_now = [gmes_browsers.spec(k)["short"]
                    for k in gmes_browsers.SUPPORTED if gmes_browsers.is_running(k)]
        if open_now:
            print(f"(your own {' and '.join(open_now)} is open - that is fine, "
                  "the automation uses its own separate profile)")
    started = cdp_common.launch_automation_chrome(url=GMES_URL)
    return "already running" if started is None else "started"


def open_gmes():
    """Make sure GMES_URL is open, navigating there if it is not already.

    No fixed sleep between the navigation and re-checking for the tab
    (HISTORY.md Phase 79.5): `gmes_tab()` already polls for the tab to
    appear, on its own generous cap, so a sleep first only delayed the start
    of a wait that already existed. The one real risk a sleep happened to
    paper over is narrower and handled directly: `navigate_page()` can tear
    the CDP target down mid-navigation (documented elsewhere in this
    project - a cross-origin navigation away from about:blank can reset the
    connection), and `gmes_tab()` raises immediately on the FIRST
    `get_tabs()` failure rather than retrying one itself. So a single
    transient failure right after navigating is retried once here, not
    guessed around with a delay."""
    tab = gmes_common.gmes_tab()
    if tab is None:
        cdp_common.navigate_page(GMES_URL)
        try:
            tab = gmes_common.gmes_tab()
        except RuntimeError:
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

    Returns (state, ws) where state is 'session' (already signed in), 'login'
    (login form ready) or 'timeout'. The websocket comes back because this
    may have had to replace it.

    Swallowing every exception here is what made the tool look frozen. A tab
    that is replaced while the page loads leaves the socket dead, so EVERY
    check afterwards raised, every raise was ignored, and the loop sat for its
    full four minutes printing one line - while the browser beside it was
    showing the login page perfectly. A few failures in a row now mean the
    connection is gone, not that the page is busy, and it reattaches."""
    started = time.time()
    announced, errors, swept = 0, 0, False
    while time.time() - started < max_wait:
        try:
            signed_in, _who = is_logged_in(ws)
            if signed_in:
                return "session", ws
            if evaluate(ws, gmes_common.js_find_by_id(BTN_SSO)).get("found"):
                return "login", ws
            errors = 0

            # Neither control is there. Is the application even building, or
            # has it failed to start? Those look identical from outside - both
            # are a blank page - and the usual cause of the second is G-MES's
            # engine cache filling localStorage until its own bootstrap throws
            # QuotaExceededError. Swept once, then the page is reloaded.
            if not swept and time.time() - started > 20 \
                    and not gmes_common.app_is_built(ws):
                state = gmes_common.storage_state(ws)
                if verbose:
                    print(f"  the G-MES application has not started. "
                          f"Storage: {state.get('bytes', 0) / 1048576:.2f} MB, "
                          f"{state.get('engineCopies', 0)} cached engine copies.")
                pruned = gmes_common.prune_nexacro_cache(ws)
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


def main(show_browser=False, status_only=False, refresh_profile=False, assist=False,
         allow_password_login=False):
    """Sign in, unattended.

    `allow_password_login` is OFF by default and should stay that way for
    anything automated. It permits ONE attempt at G-MES's own ID/password
    form when AD SSO does not complete. That path burned a real attempt
    against the account's lockout counter on 2026-09-15 for a password that
    was correct - the SSO window had simply never opened (HISTORY.md Phase
    74). A failed corporate sign-in and a wrong password are different
    events and are treated as such here."""
    print("=" * 70)
    print("GMES login")
    print("=" * 70)

    tab = None
    if not status_only:
        try:
            print(f"Browser: {ensure_browser(show_browser, refresh_profile)}")
        except RuntimeError as e:
            print(f"ERROR: {e}")
            return FAILED
        tab = open_gmes()

    # gmes_tab() raises a RuntimeError written for a person to read. Letting
    # it escape buried that sentence under forty lines of urllib traceback,
    # which is how `--status` - a command whose whole job is to REPORT the
    # situation - came to crash when the situation was simply "no browser".
    try:
        ws = connect_gmes()
    except RuntimeError as e:
        print(f"\n{e}")
        if status_only:
            print("\n(--status only looks; it never starts the browser itself.)")
        return FAILED

    try:
        state, ws = wait_for_login_or_session(ws, verbose=not status_only)
        if state == "timeout" and not status_only:
            print("ERROR: GMES showed neither the login form nor a signed-in "
                  "session within 4 minutes.")
            gmes_common.screenshot_on_failure("gmes_never_loaded")
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

        # Every time a fresh login form is reached, not once: it does not
        # persist across a reload (HISTORY.md Phase 77). Skipped when already
        # signed in - there is no login form to switch.
        if state == "login" and not signed_in:
            outcome = ensure_login_language_english(ws)
            if outcome:
                print(f"Login page language: {outcome}")

        # Leftovers from EARLIER runs, before this one adds any state of its
        # own. A successful AD SSO leaves its popup behind as a second G-MES
        # application (see prune_duplicate_gmes_tabs), and they accumulate -
        # four were found open live, three of them empty. Swept here rather
        # than at the end so a run never attaches to an empty duplicate while
        # the screens it opened sit in another tab (HISTORY.md Phase 76.4).
        gmes_common.prune_duplicate_gmes_tabs(keep=tab.get("id") if tab else None)

        was_already_signed_in = signed_in
        if signed_in:
            print(f"Already signed in as {who!r}.")
        elif assist:
            # Asked for explicitly: skip the automated attempt entirely and
            # let a person do it. Clicking AD SSO first would only risk
            # another refusal against a corporate directory.
            if not wait_for_manual_sign_in(ws):
                gmes_common.screenshot_on_failure("gmes_assist_timeout")
                return FAILED
            signed_in, who = is_logged_in(ws)
            was_already_signed_in = False
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
                gmes_common.screenshot_on_failure("gmes_no_sso_button")
                return FAILED

            # A failed AD SSO is NOT a failed credential. The branches below
            # therefore report what happened and stop; none of them falls
            # through to typing the password (HISTORY.md Phase 74).
            sso_tab = wait_for_sso_window(ws)
            message, promising = "", False

            if isinstance(sso_tab, tuple) and sso_tab[0] == "no-window":
                message = sso_tab[1]
                print("  The Samsung SSO window never opened.")
                if message:
                    print(f"  (the login form shows {message!r} - that text has "
                          "been seen with nothing submitted, so it is not "
                          "evidence about the password)")
            elif sso_tab is None:
                print("  The Samsung SSO window never opened.")
            elif sso_tab == "already-signed-in":
                print("No SSO window was needed - the saved session signed in.")
                promising = True
            else:
                print("SSO window opened; filling in the saved credentials...")
                ok, detail = complete_sso(sso_tab, user, password)
                if ok:
                    print("Credentials submitted; waiting for GMES to come up...")
                    promising = True
                else:
                    print(f"  The SSO page could not be completed: {detail}")

            # Being signed in wins, always. The message is remembered so it can
            # explain a failure, but it never ends the wait - a stale
            # 'Auth bad credentials' left on the form from an earlier attempt
            # would otherwise abort a sign-in that was about to succeed.
            signed_in = False
            deadline = time.time() + (120 if promising else 5)
            while time.time() < deadline:
                if is_logged_in(ws)[0]:
                    signed_in = True
                    break
                message = login_error(ws) or message
                time.sleep(1.5)

            # Did the corporate sign-in itself get refused? That is the only
            # thing that proves anything about the credentials, and it stops
            # everything dead.
            if not signed_in:
                warned = lockout_warning(ws)
                if warned.get("found"):
                    counted = ""
                    if warned.get("used") and warned.get("limit"):
                        counted = (f"  Attempt {warned['used']} of "
                                   f"{warned['limit']} before this account is "
                                   "locked.\n")
                    print(f"\nERROR: G-MES refused the credentials.")
                    print(f"  It said: {warned.get('text', '')!r}")
                    print(counted + "  STOPPING. Nothing will be retried - "
                          "another attempt moves the account closer to a\n"
                          "  lockout. Check the account by signing in by hand "
                          "before running this again.")
                    gmes_common.screenshot_on_failure("gmes_login_rejected")
                    return REJECTED

            # AD SSO did not complete, and nothing says the credentials are
            # at fault. This used to fall through to typing the password into
            # G-MES's own form - and that is exactly what burned a real
            # attempt against the lockout counter on 2026-09-15, for a
            # password that was almost certainly correct (HISTORY.md Phase
            # 74). The window had simply not opened.
            #
            # The password path is now opt-in and off by default. A corporate
            # sign-in that does not complete is a TRANSIENT failure worth
            # retrying as itself; it is not a licence to spend an attempt.
            if not signed_in and not allow_password_login:
                print("\nERROR: the corporate (AD SSO) sign-in did not complete.")
                print("  The saved password was NOT submitted, deliberately: a")
                print("  failed SSO says nothing about whether the password is")
                print("  right, and a wrong guess costs one of five attempts")
                print("  before the account locks.")
                print("\n  Usual causes, in order: the SSO popup was blocked or")
                print("  slow, the network hiccupped, or this account already")
                print("  has a session open in another browser profile.")
                print("\n  To use G-MES's own ID/password form instead - only if")
                print("  you are sure the password is current:")
                print("      python gmes_login.py --allow-password-login")
                gmes_common.screenshot_on_failure("gmes_sso_incomplete")
                return FAILED

            if not signed_in and allow_password_login:
                print("\nAD SSO did not complete. --allow-password-login was "
                      "given, so trying G-MES's own form once...")
                ok, detail = direct_login(ws, user, password)
                if ok:
                    deadline = time.time() + 60
                    while time.time() < deadline:
                        if is_logged_in(ws)[0]:
                            signed_in = True
                            break
                        if lockout_warning(ws).get("found"):
                            break        # refused - stop polling immediately
                        time.sleep(1.5)
                else:
                    print(f"  (that form could not be used: {detail})")

                if not signed_in:
                    warned = lockout_warning(ws)
                    if warned.get("found"):
                        counted = ""
                        if warned.get("used") and warned.get("limit"):
                            counted = (f"  Attempt {warned['used']} of "
                                       f"{warned['limit']} before this account "
                                       "is locked.\n")
                        print(f"\nERROR: G-MES refused the credentials.")
                        print(f"  It said: {warned.get('text', '')!r}")
                        print(counted + "  STOPPING. Nothing will be retried.")
                        gmes_common.screenshot_on_failure("gmes_login_rejected")
                        return REJECTED

            if not signed_in:
                if message:
                    print(f"\nERROR: not signed in. The page shows {message!r},")
                    print("  which is a diagnostic only - it is NOT proof the")
                    print("  password is wrong.")
                    gmes_common.screenshot_on_failure("gmes_login_failed")
                    return FAILED
                print("ERROR: still not signed in after 2 minutes.")
                gmes_common.screenshot_on_failure("gmes_login_timeout")
                return FAILED

            signed_in, who = is_logged_in(ws)
            print(f"Signed in as {who!r}.")

        # Again, now that THIS run's sign-in is done. If it went through AD
        # SSO, the popup that carried it has by now followed its own
        # RelayState back to the G-MES host and turned into a second, empty
        # G-MES application - the one nothing used to close. Pruned before the
        # popup sweep, so the sweep runs against the tab that will actually be
        # driven (HISTORY.md Phase 76.4).
        if not was_already_signed_in:
            gmes_common.prune_duplicate_gmes_tabs(keep=tab.get("id") if tab else None)

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
            names = [p["name"] for p in left["popups"]]
            print(f"WARNING: {left['count']} popup(s) still on screen: {names}")
            print("Both the click and the direct-close fallback failed to "
                  "clear it - stopping here instead of continuing onto a "
                  "screen a notice window is still covering (see CLAUDE.md "
                  "3.9, HISTORY.md Phase 59.1).")
            gmes_common.screenshot_on_failure("gmes_login_stuck_popup")
            return FAILED

        shot = gmes_common.capture_screenshot("gmes_ready.png")
        print(f"\nReady. Screenshot: {shot}")
        return OK
    finally:
        ws.close()


if __name__ == "__main__":
    sys.exit(main(allow_password_login="--allow-password-login" in sys.argv,
                  show_browser="--show-browser" in sys.argv,
                  status_only="--status" in sys.argv,
                  refresh_profile="--refresh-profile" in sys.argv,
                  assist="--assist" in sys.argv))
