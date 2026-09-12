"""G-MES Excel download and delivered-file verification.

G-MES produces NASCA DRM-wrapped workbooks.  We can prove that a file arrived
and has bytes, but cannot inspect its encrypted contents; callers must retain
the data-layer CSV when machine-readable content verification is required.
"""
import os
import time

from ..browser.cdp import evaluate, send
from ..browser.interaction import click_element_by_rect
from ..nexacro.dom import click_control, js_find_by_id


# A shell-frame control: unlike work-screen instance ids, this one is stable.
EXCEL_BTN = "mainframe.vFrameSet1.vFrameSet2.mdiFrame.form.btnExcel"


def is_drm_protected(path):
    """Whether the first bytes carry Samsung NASCA DRM's signature."""
    try:
        with open(path, "rb") as handle:
            return b"NASCA DRM" in handle.read(64)
    except OSError:
        return False


def download_excel(ws, target_dir, timeout=240):
    """Drive G-MES's Excel dialog and poll for a stable downloaded workbook.

    Download behaviour is deliberately configured on ``ws`` itself: Chrome
    drops a redirect configured through a connection that is subsequently
    closed.  The normal target and the user's Downloads directory are both
    observed because older Chrome/G-MES combinations can use either.
    """
    os.makedirs(target_dir, exist_ok=True)
    downloads = os.path.join(os.environ.get("USERPROFILE", ""), "Downloads")

    try:
        send(ws, "Browser.setDownloadBehavior", {
            "behavior": "allow", "downloadPath": target_dir, "eventsEnabled": True,
        })
    except Exception:
        send(ws, "Page.setDownloadBehavior", {
            "behavior": "allow", "downloadPath": target_dir,
        })

    def snapshot(folder):
        try:
            return {name for name in os.listdir(folder)
                    if name.lower().endswith((".xlsx", ".crdownload"))}
        except OSError:
            return set()

    before = {target_dir: snapshot(target_dir), downloads: snapshot(downloads)}

    icon = evaluate(ws, js_find_by_id(EXCEL_BTN))
    if not icon.get("found"):
        raise RuntimeError(
            f"the Excel Download icon was not visible ({icon.get('reason')})")
    click_element_by_rect(ws, icon["x"], icon["y"])

    if not click_control(ws, text="OK", attempts=30, delay=0.5):
        raise RuntimeError("the 'Save to Excel' dialog did not offer an OK button")

    deadline = time.time() + timeout
    while time.time() < deadline:
        for folder in (target_dir, downloads):
            new = snapshot(folder) - before[folder]
            finished = [name for name in new if name.lower().endswith(".xlsx")]
            if finished and not any(name.endswith(".crdownload") for name in new):
                path = os.path.join(folder, sorted(finished)[-1])
                size = -1
                while True:
                    try:
                        current_size = os.path.getsize(path)
                    except OSError:
                        break
                    if current_size == size:
                        return path
                    size = current_size
                    time.sleep(0.5)
        time.sleep(1.0)

    raise RuntimeError(f"no .xlsx file appeared within {timeout}s")


def check_download(path, minimum=512):
    """Verify a delivered file exists and is larger than an empty shell.

    NASCA DRM prevents content-level workbook inspection.  This function is
    intentionally honest about that limitation; it validates delivery only.
    """
    if not os.path.isfile(path):
        raise RuntimeError(f"the export reported success but {path} is not there")
    size = os.path.getsize(path)
    if size < minimum:
        raise RuntimeError(f"{os.path.basename(path)} is only {size} bytes - "
                           "that is not a real export")
    return size
