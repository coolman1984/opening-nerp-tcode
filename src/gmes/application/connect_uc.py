"""Resolve and attach to the G-MES browser tab.

Forked from gmes_common.py. Lives in application/ rather than browser/ or
nexacro/ because choosing WHICH tab is the real G-MES tab (excluding the
SSO popup, waiting out a mid-navigation replacement) is a decision, not a
DOM primitive - built here ahead of the migration's originally planned
Phase 6, because auth/session.py's open_gmes() and connect_gmes() are
both needed to even test the sign-in flow this phase ports.
"""
import time
from urllib.parse import urlparse

from ..browser.cdp import connect, get_tabs
from ..config import GMES_URL


def host_of(tab):
    """Return a page hostname only; never search query strings for identity."""
    return (urlparse(tab.get("url") or "").hostname or "").lower()


GMES_HOST = (urlparse(GMES_URL).hostname or "").lower()


def is_gmes_tab(tab):
    return host_of(tab) == GMES_HOST


def gmes_tab(port=None, wait=20):
    """The browser tab showing GMES.

    Matched on the host, and the Samsung SSO window is excluded outright.
    Matching the whole URL for "gmes" picked the ADFS sign-in tab instead:
    its address carries a long base64 `SAMLRequest`, and that happened to
    contain those four letters. Everything downstream then read the wrong
    document and reported the G-MES login form as missing.

    A closed browser is the most common reason any of these tools fail,
    so it is reported as one sentence rather than as a urllib stack trace
    about a refused connection to a port number."""
    # Waited for, not taken on the first look. Straight after Chrome
    # starts, the G-MES tab is still on about:blank or mid-navigation;
    # returning whatever page happened to be listed handed back a tab
    # that was about to be replaced, and attaching to it died with
    # "Connection to remote host was lost".
    deadline = time.time() + wait
    pages = []
    while True:
        try:
            pages = [t for t in get_tabs(port=port) if t.get("type") == "page"]
        except Exception:
            raise RuntimeError(
                "Cannot reach the automation browser. It is not running, or "
                "was closed by a previous job. Start it with:  gmes login")
        for tab in pages:
            if is_gmes_tab(tab):
                return tab
        if time.time() >= deadline:
            break
        time.sleep(0.5)

    return None


def connect_gmes(timeout=20, port=None, attempts=4):
    """Attach to the G-MES tab, re-resolving it on each attempt.

    A tab that is loading can accept the socket and then drop it
    mid-handshake while Chrome swaps renderers, which surfaced as a bare
    WebSocketConnectionClosedException out of `Runtime.enable`. The tab is
    looked up again each time rather than retried against the same one,
    because by then it is usually a different tab."""
    last = None
    for attempt in range(attempts):
        tab = gmes_tab(port=port)
        if tab is None:
            raise RuntimeError("No G-MES tab is open. Run:  gmes login")
        try:
            return connect(tab["webSocketDebuggerUrl"], timeout=timeout)
        except Exception as e:
            last = e
            time.sleep(1.5)
    raise RuntimeError(f"Could not attach to the G-MES tab after {attempts} "
                       f"attempts ({last}).")
