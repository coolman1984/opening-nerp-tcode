"""The live browser session, and the three repairs the recovery ladder uses.

`application/recovery.py` decides WHEN to climb; this performs the rungs. The
split matters because the ladder's decisions are worth testing without a
browser, and everything that actually touches Chrome lives here.

The repairs get more drastic in order, and each one is a different action
rather than a longer wait:

    settle()      reattach a socket that has died, clear notice popups
    reset_page()  prune the engine cache, clear the browser cache, reload,
                  and sign in again if the reload landed on the login page
    cold_start()  close the automation browser, start it, sign in, reattach

None of them deletes anything of the operator's. `cold_start()` closes the
automation browser through its own DevTools endpoint and starts it again on
the SAME profile; it never refreshes or replaces that profile, because doing
so destroys the signed-in session inside it and is a last-resort action a
person asks for explicitly (CLAUDE.md 2.1a).
"""
import time

from ..browser.cdp import clear_browser_cache, evaluate, send
from ..browser.chrome import close_browser
from ..contracts import LoginOutcome
from ..nexacro import popups
from ..nexacro.app_state import app_is_built, prune_nexacro_cache, storage_state
from .connect_uc import connect_gmes
from .sign_in_uc import sign_in

JS_ALIVE = "(function(){ return JSON.stringify({alive: true}); })()"


class LiveSession:
    """One authenticated browser session that can repair itself.

    `ws` is deliberately a property rather than a stored handle the caller
    keeps: every repair may replace the socket, and a caller holding the old
    one would go on talking to a connection that is gone.
    """

    def __init__(self, ws, sign_in_kwargs=None, log=print):
        self._ws = ws
        self._sign_in_kwargs = dict(sign_in_kwargs or {})
        self.log = log

    @property
    def ws(self):
        return self._ws

    def close(self):
        try:
            self._ws.close()
        except Exception:
            pass

    # -- repairs ------------------------------------------------------------

    def settle(self):
        """Cheapest rung: a live socket and nothing covering the screen."""
        self._reattach_if_dead()
        closed, left = popups.close_notices(self._ws)
        if closed:
            self.log(f"  repaired : closed {', '.join(closed)}")
        if left:
            self.log(f"  repaired : left alone {', '.join(left)}")

    def reset_page(self):
        """Second rung: clear both caches and rebuild the page.

        The two caches fail differently and both have been seen. G-MES
        stores a copy of its whole Nexacro engine in localStorage on every
        load and never removes the old ones, until the quota fills and the
        application cannot bootstrap at all (HISTORY.md Phase 22). Chrome's
        own HTTP cache fails the other way, serving a stale script to a page
        that then half-builds. Pruning one and not the other leaves the
        reload as unlikely to work as the attempt that just failed."""
        self._reattach_if_dead()
        state = storage_state(self._ws)
        pruned = prune_nexacro_cache(self._ws)
        self.log(f"  repaired : storage {state.get('bytes', 0) / 1048576:.2f} MB, "
                 f"removed {pruned.get('removed', 0)} stale engine copies; "
                 f"browser cache cleared: {clear_browser_cache(self._ws)}")
        try:
            send(self._ws, "Page.reload", {"ignoreCache": True})
        except Exception:
            # A reload that cannot even be requested means the socket went
            # between the check above and here; the wait below reattaches.
            pass
        self._wait_for_a_usable_page()

    def cold_start(self):
        """Third rung: a browser that has been started fresh, and signed in.

        Everything held in the page - a half-built Nexacro application, a
        screen in an unknown state, a dialog nobody can name - goes with the
        process. The profile is not touched, so the session inside it and
        the operator's saved logins survive the restart."""
        self.log("  repaired : closing the automation browser")
        close_browser()
        attempt = sign_in(log=self.log, **self._sign_in_kwargs)
        if attempt.outcome is not LoginOutcome.OK:
            raise RuntimeError(
                f"the browser restarted but signing in did not complete: "
                f"{attempt.detail or 'no detail'}")
        self._ws = connect_gmes()
        self.log("  repaired : browser restarted and signed in")

    # -- the observations the repairs rely on --------------------------------

    def _reattach_if_dead(self):
        """Replace the socket when it has gone, and only then.

        Asked rather than assumed: a page busy building is not a dead
        connection, and reattaching to a healthy session costs a round trip
        and loses nothing but is pure noise in the log."""
        try:
            evaluate(self._ws, JS_ALIVE)
            return False
        except Exception:
            pass
        self.close()
        self._ws = connect_gmes()
        self.log("  repaired : reattached to the G-MES tab")
        return True

    def _wait_for_a_usable_page(self, timeout=180, poll=1.5):
        """Wait for the application to rebuild, and for a session to be on it.

        A reload drops whatever the page held, so waiting for the document
        is not enough - Nexacro builds its UI in JavaScript long afterwards
        (CLAUDE.md 3.2), and the reload can land on the login page when the
        session did not survive it. Both are polled for, and a sign-in is
        only attempted once the page is actually there to sign in to."""
        from ..auth.session import is_logged_in

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if app_is_built(self._ws) and is_logged_in(self._ws)[0]:
                    return True
            except Exception:
                self._reattach_if_dead()
            time.sleep(poll)

        self.log("  repaired : the reloaded page is not signed in; signing in again")
        attempt = sign_in(log=self.log, **self._sign_in_kwargs)
        if attempt.outcome is not LoginOutcome.OK:
            raise RuntimeError(f"the page was reloaded but signing in did not "
                               f"complete: {attempt.detail or 'no detail'}")
        self._ws = connect_gmes()
        return True
