"""Where this app keeps its data, and how the engine is pointed at it.

The engine writes `screens/`, `logs/`, the export folder and failure screenshots
next to its own files. Inside a one-file .exe those files live in a temporary
folder that disappears when the program closes, so every run would lose its
learned screen, its log and its diagnostics. `setup()` points those paths at a
`data/` folder beside the app instead, without editing a line of the engine.
"""
import os
import sys
import time

FROZEN = bool(getattr(sys, "frozen", False))
HERE = os.path.dirname(os.path.abspath(__file__))
ORIGINAL_CWD = os.getcwd()          # setup() moves the working directory; paths typed
                                    # on a command line are relative to THIS one


def base_dir():
    """The Mr.Samir folder: beside the .exe when frozen, else the parent of app/."""
    return os.path.dirname(sys.executable) if FROZEN else os.path.dirname(HERE)


def data_dir():
    return os.path.join(base_dir(), "data")


_done = False


def setup():
    """Import the engine and redirect its runtime paths. Safe to call twice."""
    global _done
    if _done:
        return
    engine = os.path.join(HERE, "engine")
    if not FROZEN and engine not in sys.path:
        sys.path.insert(0, engine)
    data = data_dir()
    for sub in ("screens", "screens_known", "logs", "output", "diagnostics"):
        os.makedirs(os.path.join(data, sub), exist_ok=True)

    import gmes_common
    import gmes_core
    import gmes_log
    import gmes_profile
    import cdp_common

    gmes_core.SCRIPT_DIR = data
    gmes_core.OUTPUT_DIR = os.path.join(data, "output")
    gmes_profile.SCRIPT_DIR = data
    gmes_profile.SCREENS_DIR = os.path.join(data, "screens")
    gmes_profile.SHIPPED_DIR = os.path.join(data, "screens_known")
    gmes_log.SCRIPT_DIR = data
    gmes_log.LOG_DIR = os.path.join(data, "logs")

    diagnostics = os.path.join(data, "diagnostics")

    def shot(prefix="gmes_failure"):
        path = os.path.join(diagnostics, f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.png")
        try:
            saved = gmes_common.capture_screenshot(path)
        except Exception:                                  # noqa: BLE001 - diagnostics only
            saved = None
        if saved:
            print(f"Diagnostic screenshot saved: {saved}")
        return saved

    gmes_common.screenshot_on_failure = shot
    cdp_common.screenshot_on_failure = lambda prefix="failure", tab=None: shot(prefix)
    # The engine also saves a few screenshots by bare file name (the sign-in
    # "gmes_ready.png" - a picture of G-MES with production data on it). A bare
    # name lands in the working directory, which for the .exe is the folder the
    # person double-clicked in. Working in data\diagnostics keeps them with the
    # other diagnostics and out of anything that gets zipped and handed on.
    try:
        os.chdir(diagnostics)
    except OSError:
        pass
    _done = True
