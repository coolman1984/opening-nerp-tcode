"""Diagnostic screenshots.

Forked from cdp_common.py. An unattended job that fails at 2am leaves
nothing else to diagnose from, so every failure path saves one.

Gotcha carried over unchanged: Page.captureScreenshot fails with "Command
can only be executed on top-level targets" if called on anything but the
page-type CDP target, so this always connects through get_page_tab()
rather than whatever target the caller happened to be using.
"""
import base64
import os
import time

from .cdp import connect, get_page_tab, send


def capture_screenshot(path, port=None, timeout=20):
    """Save a PNG of the browser window."""
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


def screenshot_on_failure(prefix="gmes_failure", directory=None):
    """Best-effort diagnostic snapshot, named by time.

    `directory` defaults to the current working directory rather than this
    module's own install location (unlike the original cdp_common.py,
    which saved beside the calling script - fine at the repo root, but
    wrong once this code lives inside an installed/packaged gmes package).
    Phase 7 of the migration wires this to paths.screenshots_dir()
    (%LOCALAPPDATA%\\GMES\\screenshots\\); until then this keeps failure
    screenshots landing somewhere sensible and discoverable rather than
    inside site-packages."""
    name = f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.png"
    path = os.path.join(directory or os.getcwd(), name)
    saved = capture_screenshot(path)
    if saved:
        print(f"Diagnostic screenshot saved: {saved}")
    return saved
