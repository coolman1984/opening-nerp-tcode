"""G-MES Excel download and delivered-file verification.

G-MES produces NASCA DRM-wrapped workbooks.  We can prove that a file arrived
and has bytes, but cannot inspect its encrypted contents; callers must retain
the data-layer CSV when machine-readable content verification is required.
"""
import os
import shutil
import tempfile
import time

from ..browser.cdp import evaluate, send
from ..browser.interaction import click_element_by_rect
from ..nexacro.dom import click_control, js_find_by_id


# A shell-frame control: unlike work-screen instance ids, this one is stable.
EXCEL_BTN = "mainframe.vFrameSet1.vFrameSet2.mdiFrame.form.btnExcel"

# The confirm button on the 'Save to Excel' dialog. "OK" is what a live run
# has actually seen, and it stays first; the rest are here because a locale
# or a template change must not stop an unattended job on a button that is
# on screen under a different word.
CONFIRM_LABELS = ("OK", "확인", "Ok", "Yes", "예", "Save", "저장")


def confirm_export_dialog(ws, timeout=20, poll=0.5):
    """Press the export dialog's confirm button, whatever it is labelled.

    Polls rather than waiting a set time: the dialog is built after the icon
    is clicked, so the button can be a second away from existing. Each label
    is tried once per pass so a dialog that appears late is still caught by
    the first label that matches, not by whichever one happened to be tried
    when it arrived."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for label in CONFIRM_LABELS:
            clicked = click_control(ws, text=label, attempts=1, delay=0)
            if clicked:
                return clicked
        time.sleep(poll)
    return None


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
    closed.  A dedicated staging directory is the only directory observed,
    so a stale workbook can never be mistaken for this export.
    """
    os.makedirs(target_dir, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".gmes-download-", dir=target_dir)

    try:
        send(ws, "Browser.setDownloadBehavior", {
            "behavior": "allow", "downloadPath": staging, "eventsEnabled": True,
        })
    except Exception:
        send(ws, "Page.setDownloadBehavior", {
            "behavior": "allow", "downloadPath": staging,
        })

    def snapshot(folder):
        try:
            return {name for name in os.listdir(folder)
                    if name.lower().endswith((".xlsx", ".crdownload"))}
        except OSError:
            return set()

    try:
        icon = evaluate(ws, js_find_by_id(EXCEL_BTN))
        if not icon.get("found"):
            raise RuntimeError(
                f"the Excel Download icon was not visible ({icon.get('reason')})")
        click_element_by_rect(ws, icon["x"], icon["y"])
        if not confirm_export_dialog(ws):
            raise RuntimeError(
                "the 'Save to Excel' dialog offered no confirm button - looked for "
                + ", ".join(CONFIRM_LABELS))

        deadline = time.time() + timeout
        candidate, last_size, stable = None, -1, 0
        while time.time() < deadline:
            names = snapshot(staging)
            finished = [name for name in names if name.lower().endswith(".xlsx")]
            downloading = [name for name in names if name.lower().endswith(".crdownload")]
            if len(finished) > 1:
                raise RuntimeError("more than one workbook arrived for one export request")
            if finished and not downloading:
                candidate = os.path.join(staging, finished[0])
                current_size = os.path.getsize(candidate)
                stable = stable + 1 if current_size == last_size else 0
                last_size = current_size
                if stable >= 2:
                    final = os.path.join(target_dir, finished[0])
                    os.replace(candidate, final)
                    return final
            time.sleep(0.5)
        raise RuntimeError(f"no complete .xlsx file appeared within {timeout}s")
    finally:
        shutil.rmtree(staging, ignore_errors=True)


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
    with open(path, "rb") as handle:
        prefix = handle.read(64)
    if not (prefix.startswith(b"PK\x03\x04") or b"NASCA DRM" in prefix):
        raise RuntimeError(f"{os.path.basename(path)} is not an XLSX or a NASCA DRM workbook")
    return size
