"""Where GMES Automation keeps its data, and how the engine is pointed at it.

The engine (identical copies of the project's flat modules, see sync_engine.py)
writes recordings, logs, run reports, saved batches, schedule launchers, exports
and screenshots next to its own files. Inside a one-file .exe those files live in
a temporary folder that disappears when the program closes. `setup()` points every
one of those paths at a `data/` folder beside the app - without editing a line of
the engine.

    data/screens          recordings made on this PC (what a run proved)
    data/screens/batches  saved batches
    data/logs             the engine's run log and the app's activity log
    data/logs/batches     every run report (JSON, text, HTML summary)
    data/output           exported files (unless a screen or run names another folder)
    data/schedules        the launchers Task Scheduler runs
    data/diagnostics      screenshots taken when something failed
    data/certificates     the record check of every recording (what was proven)
"""
import os
import sys
import time

FROZEN = bool(getattr(sys, "frozen", False))
HERE = os.path.dirname(os.path.abspath(__file__))
ORIGINAL_CWD = os.getcwd()          # setup() moves the working directory; paths typed
                                    # on a command line are relative to THIS one
APP_NAME = "GMES Automation"
SCHEDULE_PREFIX = "GMES_App_"       # never the CLI tool's own GMES_Batch_ tasks


def base_dir():
    """The GMES folder: beside the .exe when frozen, else the parent of app/."""
    return os.path.dirname(sys.executable) if FROZEN else os.path.dirname(HERE)


def data_dir():
    override = os.environ.get("GMES_APP_DATA")
    return override or os.path.join(base_dir(), "data")


def resource(*parts):
    """A file shipped with the app (assets, shipped screen structures)."""
    root = getattr(sys, "_MEIPASS", HERE)
    return os.path.join(root, *parts)


def sub(*parts):
    path = os.path.join(data_dir(), *parts)
    os.makedirs(path, exist_ok=True)
    return path


_done = False


def hide_console_windows():
    """Every console program the engine starts (tasklist, robocopy, PowerShell for Task
    Scheduler) used to flash a black CMD window over the app: a windowed program has no
    console, so Windows gives each child one of its own. CREATE_NO_WINDOW for every
    child that does not choose its own flags; their output is captured anyway, and a
    window program (the browser) is not affected by the flag."""
    import subprocess
    if os.name != "nt" or getattr(subprocess.Popen, "_gmes_no_console", False):
        return

    class NoConsolePopen(subprocess.Popen):
        _gmes_no_console = True

        def __init__(self, *args, **kwargs):
            if not kwargs.get("creationflags"):
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            super().__init__(*args, **kwargs)

    subprocess.Popen = NoConsolePopen


def setup():
    """Import the engine and redirect its runtime paths. Safe to call twice."""
    global _done
    if _done:
        return
    hide_console_windows()
    engine = os.path.join(HERE, "engine")
    if not FROZEN and engine not in sys.path:
        sys.path.insert(0, engine)
    data = data_dir()
    for name in ("screens", "logs", "output", "diagnostics", "schedules", "certificates",
                 os.path.join("screens", "batches"), os.path.join("logs", "batches")):
        os.makedirs(os.path.join(data, name), exist_ok=True)

    import cdp_common
    import gmes_batch
    import gmes_common
    import gmes_core
    import gmes_log
    import gmes_profile
    import gmes_schedule

    gmes_core.SCRIPT_DIR = data
    gmes_core.OUTPUT_DIR = os.path.join(data, "output")
    gmes_profile.SCRIPT_DIR = data
    gmes_profile.SCREENS_DIR = os.path.join(data, "screens")
    gmes_profile.SHIPPED_DIR = resource("shipped")
    gmes_log.SCRIPT_DIR = data
    gmes_log.LOG_DIR = os.path.join(data, "logs")
    gmes_batch.BATCH_DIR = os.path.join(data, "screens", "batches")
    gmes_batch.REPORT_DIR = os.path.join(data, "logs", "batches")
    gmes_schedule.SCHEDULE_DIR = os.path.join(data, "schedules")
    gmes_schedule.PREFIX = SCHEDULE_PREFIX

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
    # "gmes_ready.png" - a picture of G-MES with production data on it). Working in
    # data\diagnostics keeps them with the other diagnostics and out of anything that
    # gets zipped and handed on.
    try:
        os.chdir(diagnostics)
    except OSError:
        pass
    _done = True
