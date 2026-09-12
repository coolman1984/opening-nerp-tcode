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
from pathlib import Path

from .cdp import connect, get_page_tab, send
from ..paths import screenshots_dir


def _runtime_screenshot_path(path):
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return screenshots_dir() / candidate.name


def capture_screenshot(path, port=None, timeout=20):
    """Save a PNG of the browser window."""
    path = _runtime_screenshot_path(path)
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
        return str(path)
    except Exception as e:
        print(f"(screenshot failed: {e!r})")
        return None
    finally:
        if ws:
            ws.close()


def screenshot_on_failure(prefix="gmes_failure", directory=None):
    """Best-effort diagnostic snapshot, named by time.

    Relative paths always resolve under `%LOCALAPPDATA%\\GMES\\screenshots`.
    An explicit absolute directory remains available to an operator who
    deliberately chooses a separate evidence location."""
    name = f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.png"
    path = os.path.join(directory, name) if directory else str(screenshots_dir() / name)
    saved = capture_screenshot(path)
    if saved:
        print(f"Diagnostic screenshot saved: {saved}")
    return saved
