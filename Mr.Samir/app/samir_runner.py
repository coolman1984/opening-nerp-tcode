"""Row-by-row export for G-MES screens whose result grid has a clickable link
(Q321KUM00 "Detail Inspection": double-click PASS -> popup Q321KUP00 -> Excel
icon -> "Save to Excel" dialog -> OK -> one .xlsx per row).

No window code here: the GUI and the command line both drive `Runner`.
Every step checks the stop flag, and every row is verified against the data
layer before anything is clicked and again after the popup opens - a wrong row
exported under a right-looking name is the failure this tool must never have.
"""
import csv
import json
import os
import re
import shutil
import threading
import time
from collections import Counter
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime

import samir_env

samir_env.setup()

import cdp_common                      # noqa: E402
import gmes_common                     # noqa: E402
import gmes_core as core               # noqa: E402
import gmes_data                       # noqa: E402

ROW_HEIGHT_FALLBACK = 24
BAD_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class StopRequested(Exception):
    """The person pressed Stop. Not an error: everything is left tidy."""


class FatalError(RuntimeError):
    """Something that makes continuing pointless (browser gone, screen lost)."""


class RowFailed(RuntimeError):
    """One row could not be exported after its retries."""


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
@dataclass
class Settings:
    screen_code: str = "Q321KUM00"
    division: str = "MAIN Part"
    period_mode: str = "Monthly"             # Monthly | Daily
    period: str = ""                         # YYYYMM or YYYYMMDD; "" = the current one
    period_from_key: str = "fromDt"
    period_to_key: str = "toDt"
    extra_filters: list = field(default_factory=list)      # ["Model=UA65", "SN No.=..."]
    result_grid: str = "grdMain"
    link_column: str = "Insp. Result"        # the grid column holding the clickable text
    link_value: str = "PASS"                 # only rows showing exactly this are exported
    status_column: str = "outInspLotStatusNm"   # the same value in the data layer
    model_column: str = "modelCode"
    plan_column: str = "planYmd"
    lot_column: str = "outInspLotNo"
    dialog_grids: list = field(default_factory=lambda: ["grdPackInspArtList"])
    single_file: object = True               # True / False / None = leave as it opens
    start_row: int = 1                       # grid row number to start at (1-based)
    count: int = 0                           # rows to export; 0 = all that remain
    out_dir: str = ""                        # "" = data/output/<screen>_<period>
    name_pattern: str = "{plan}_{model}_{lot}"
    skip_existing: bool = True
    on_error: str = "stop"                   # stop | skip
    max_errors: int = 3                      # with on_error=skip: stop after this many in a row
    retries: int = 1                         # extra attempts per row
    pause_between: float = 0.0
    popup_timeout: float = 30.0
    download_timeout: float = 90.0

    def to_json(self):
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_dict(cls, data):
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


def default_period(mode, now=None):
    now = now or datetime.now()
    return now.strftime("%Y%m") if mode == "Monthly" else now.strftime("%Y%m%d")


def validate_settings(s):
    """Problems a person can fix before anything is opened; [] when fine."""
    problems = []
    if s.period_mode not in ("Monthly", "Daily"):
        problems.append("Period mode must be Monthly or Daily.")
    period = s.period or default_period(s.period_mode)
    want = r"\d{6}" if s.period_mode == "Monthly" else r"\d{8}"
    if not re.fullmatch(want, period):
        problems.append(f"Period {period!r} must look like "
                        f"{'YYYYMM (202609)' if s.period_mode == 'Monthly' else 'YYYYMMDD (20260930)'}.")
    else:
        try:
            datetime.strptime(period + ("01" if len(period) == 6 else ""), "%Y%m%d")
        except ValueError:
            problems.append(f"Period {period!r} is not a real date.")
    if not str(s.division).strip():
        problems.append("Division is empty.")
    if not isinstance(s.start_row, int) or s.start_row < 1:
        problems.append("Start row must be 1 or more.")
    if not isinstance(s.count, int) or s.count < 0:
        problems.append("Number of rows must be 0 (all) or more.")
    if not s.dialog_grids:
        problems.append("Choose at least one grid to save in the Excel dialog.")
    elif len(s.dialog_grids) > 1 and s.single_file is not True:
        problems.append("This tool saves ONE file per row, so several grids need "
                        "'Save a single file' = Yes.")
    if s.on_error not in ("stop", "skip"):
        problems.append("On error must be stop or skip.")
    for item in s.extra_filters:
        if "=" not in item or not item.split("=", 1)[0].strip():
            problems.append(f"Extra filter {item!r} must be Name=Value.")
    try:
        s.name_pattern.format(plan="a", model="b", lot="c")
    except (KeyError, IndexError, ValueError):
        problems.append("File name pattern may only use {plan}, {model} and {lot}.")
    return problems


# --------------------------------------------------------------------------
# Pure helpers (tested offline)
# --------------------------------------------------------------------------
def safe_name(text):
    cleaned = BAD_NAME_CHARS.sub("_", str(text)).strip(" .")
    return re.sub(r"\s+", "_", cleaned) or "_"


def file_stem(pattern, plan, model, lot):
    return safe_name(pattern.format(plan=plan, model=model, lot=lot))


def unique_path(folder, stem, ext=".xlsx", taken=()):
    """A path in `folder` that neither exists nor is `taken`; never overwrites."""
    n, name = 1, stem + ext
    while os.path.exists(os.path.join(folder, name)) or name in taken:
        n += 1
        name = f"{stem}-{n}{ext}"
    return os.path.join(folder, name)


def select_rows(rows, status_column, link_value, start_row, count):
    """(indices to export, count of rows skipped because their status differs).

    `rows` are the data-layer rows in grid order, so grid row No. = index + 1.
    A screen without the status column exports every row and leaves the check
    to the grid text itself."""
    picked, other = [], 0
    for index, row in enumerate(rows):
        if index + 1 < start_row:
            continue
        if status_column and status_column in row and row.get(status_column) != link_value:
            other += 1
            continue
        picked.append(index)
    if count:
        picked = picked[:count]
    return picked, other


def plan_dialog_clicks(states, desired):
    """`states` = [{'name', 'on'}] as the dialog shows them; returns
    (names to click, names wanted but absent). Comparison ignores case."""
    want = {d.strip().lower() for d in desired}
    have = {s["name"].strip().lower() for s in states}
    missing = sorted(want - have)
    clicks = [s["name"] for s in states if s["on"] != (s["name"].strip().lower() in want)]
    return clicks, missing


def visible_in_grid(cell, grid):
    """True when a cell's centre lies inside the grid's body, not under its header,
    not below its bottom edge (rows past it are drawn but clipped - a click there
    lands on the panel underneath) and not behind its vertical scroll bar.

    The bottom margin is small on purpose: the LAST row of a list sits about 13 px
    above the edge once the grid is scrolled to the end (live, row 1074 of 1074);
    a larger margin refused a perfectly clickable row."""
    return (grid["head_bottom"] + 5 <= cell["y"] <= grid["bottom"] - 5
            and grid["left"] <= cell["x"] <= grid["right"] - 20)


def eta_seconds(done, total, elapsed):
    return int(elapsed / done * (total - done)) if done and total > done else 0


# --------------------------------------------------------------------------
# Browser-side snippets
# --------------------------------------------------------------------------
JS_GRID_GEOM = r"""
(function() {
    const grid = %s, win = %s;
    const dom = [...document.querySelectorAll('[id$=".' + grid + '"]')]
        .find(e => (!win || e.id.indexOf(win) >= 0) && e.getBoundingClientRect().width > 50);
    if (!dom) return JSON.stringify({found: false});
    const r = dom.getBoundingClientRect();
    const head = document.getElementById(dom.id + '.head');
    const hb = head ? head.getBoundingClientRect().bottom : r.top + 40;
    return JSON.stringify({found: true, left: r.left, right: r.right, top: r.top, bottom: r.bottom,
                           head_bottom: hb, path: dom.id});
})()
"""

JS_GRID_SCROLL = r"""
(function() {
    const path = %s, pos = %s;
    const app = nexacro.getApplication();
    let g; try { g = eval('app.' + path); } catch (e) { return JSON.stringify({ok: false, why: String(e)}); }
    const vs = g && g.vscrollbar;
    if (!vs) return JSON.stringify({ok: true, none: true});
    vs.set_pos(Math.max(0, Math.min(vs.max, pos)));
    return JSON.stringify({ok: true, pos: vs.pos, max: vs.max});
})()
"""

JS_MODAL_ICON = r"""
(function() {
    const win = %s;
    const el = [...document.querySelectorAll('[id$=".modal.form.btnExlDown"]')]
        .find(e => (!win || e.id.indexOf(win) >= 0) && e.getBoundingClientRect().width > 0);
    if (!el) return JSON.stringify({found: false});
    const r = el.getBoundingClientRect();
    return JSON.stringify({found: true, x: r.left + r.width / 2, y: r.top + r.height / 2});
})()
"""

JS_MODAL_VALUES = r"""
(function() {
    const vals = [];
    for (const el of document.querySelectorAll('input'))
        if (/\.modal\.form\./.test(el.id) && el.value) vals.push(el.value);
    return JSON.stringify(vals);
})()
"""

JS_DIALOG = r"""
(function() {
    const rows = [];
    for (let i = 0; i < 40; i++) {
        const name = document.querySelector('[id$="popupExcelExport.form.grdList.body.gridrow_' + i + '.cell_' + i + '_2:text"]');
        const box = document.querySelector('[id$="popupExcelExport.form.grdList.body.gridrow_' + i + '.cell_' + i + '_0.cellcheckbox"]');
        if (!name || !box) break;
        const r = box.getBoundingClientRect();
        if (r.width === 0) continue;
        rows.push({name: (name.textContent || '').trim(), on: box.getAttribute('userstatus') === 'selected',
                   x: r.left + r.width / 2, y: r.top + r.height / 2});
    }
    const single = document.querySelector('[id$="popupExcelExport.form.chkSingleFile"]');
    let s = null;
    if (single && single.getBoundingClientRect().width > 0) {
        const r = single.getBoundingClientRect();
        s = {on: single.getAttribute('userstatus') === 'selected', x: r.left + 8, y: r.top + r.height / 2};
    }
    return JSON.stringify({rows: rows, single: s});
})()
"""


# --------------------------------------------------------------------------
# The runner
# --------------------------------------------------------------------------
class Runner:
    def __init__(self, settings, log=print, progress=None, trace=None):
        self.s = settings
        self.log = log
        self.trace = trace or (lambda _label: None)
        self._t0 = time.time()
        self._current = None
        self.progress = progress or (lambda **_k: None)
        self._stop = threading.Event()
        self._pause = threading.Event()
        self.ws = None
        self.lock = None
        self.win_id = ""
        self.dataset = ""
        self.rows = []
        self.columns = []
        self.total = 0
        self.status_counts = {}
        self.results = []
        self.out_dir = ""

    # ---- control --------------------------------------------------------
    def request_stop(self):
        self._stop.set()

    def pause(self):
        self._pause.set()

    def resume(self):
        self._pause.clear()

    @property
    def stopped(self):
        return self._stop.is_set()

    def _check(self):
        if self._stop.is_set():
            raise StopRequested()
        while self._pause.is_set():
            time.sleep(0.2)
            if self._stop.is_set():
                raise StopRequested()

    def _sleep(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            self._check()
            time.sleep(min(0.2, max(0.0, end - time.time())))

    def _mark(self, label):
        """Timing trace of the current row (only shown when a trace is wanted)."""
        now = time.time()
        self.trace(f"      {label}: +{now - self._t0:.1f}s")
        self._t0 = now

    def _wait(self, fn, timeout, delay=0.3):
        """Poll `fn` until it returns something truthy; the stop flag is honoured
        between polls (CLAUDE.md 3.1 - never a fixed sleep)."""
        end = time.time() + timeout
        while True:
            self._check()
            value = fn()
            if value:
                return value
            if time.time() >= end:
                return None
            time.sleep(delay)

    # ---- connection -----------------------------------------------------
    def connect(self):
        self._check()
        try:
            self.lock = core.acquire_run_lock()
        except core.RunLocked as e:
            raise FatalError(str(e)) from e
        try:
            self.log("Signing in to G-MES (or reusing the open session)...")
            if not core.sign_in():
                raise FatalError("Sign-in failed. Look at the browser window; "
                                 "do not retry many times in a row.")
            self.ws = core.connect()
            self._keep_page_responsive()
        except BaseException:
            core.release_run_lock(self.lock)
            self.lock = None
            raise

    def _keep_page_responsive(self):
        """Make the page behave as focused even while the person works in another window.

        Measured live (2026-09-30): with the automation window in the background
        every Input.dispatchMouseEvent waited exactly 5.0 s for the browser's
        acknowledgement (a 5-click row took 32 s instead of 5 s, and a mouse
        wheel timed out). Focus emulation removes the wait (0.01 s) and, unlike
        Page.bringToFront, never pulls the window over what the person is doing.
        It lives on THIS connection, so it is set again after any reconnect."""
        try:
            cdp_common.send(self.ws, "Emulation.setFocusEmulationEnabled", {"enabled": True})
        except Exception as e:                              # noqa: BLE001 - slower, not wrong
            self.log(f"  note: could not enable focus emulation ({e}); rows may run slower "
                     "unless the automation window is in front")

    def close(self, close_browser=False):
        try:
            if self.ws is not None:
                self.ws.close()
        except Exception:                                   # noqa: BLE001
            pass
        self.ws = None
        if self.lock is not None:
            core.release_run_lock(self.lock)
            self.lock = None
        if close_browser:
            try:
                cdp_common.close_browser()
            except Exception:                               # noqa: BLE001
                pass

    def _alive(self):
        try:
            return cdp_common.evaluate(self.ws, "JSON.stringify(1+1)") == 2
        except Exception:                                   # noqa: BLE001
            return False

    # ---- load the rows --------------------------------------------------
    def load(self):
        """Open the screen, apply the filters, Inquiry, read the data layer."""
        s = self.s
        problems = validate_settings(s)
        if problems:
            raise ValueError("\n".join(problems))
        self._check()
        period = s.period or default_period(s.period_mode)
        sets = {s.period_from_key: period, s.period_to_key: period}
        for item in s.extra_filters:
            key, value = item.split("=", 1)
            sets[key.strip()] = value.strip()
        self.log(f"Opening {s.screen_code}: division {s.division}, {s.period_mode} {period} ...")
        try:
            result = core.run_screen(self.ws, s.screen_code, division=s.division.strip(), sets=sets,
                                     options=[s.period_mode], export="none",
                                     grid_name=s.result_grid or None, remember_destination=False,
                                     log=self._engine_log)
        except (StopRequested, FatalError):
            raise
        except Exception as e:                              # noqa: BLE001
            text = str(e)
            if "no rows" in text:
                raise FatalError("G-MES found no rows for these filters (division, period, "
                                 "extra filters). Change them and load again.") from e
            raise FatalError(text) from e
        if not result.get("ok"):
            raise FatalError(result.get("error") or "the screen could not be run")
        self.win_id = result.get("window") or ""
        grid = str(result.get("grid", ""))
        self.dataset = grid.split("->")[-1].strip()
        if not self.dataset:
            raise FatalError("the screen did not say which dataset holds its result")
        data = gmes_data.read_dataset(self.ws, s.screen_code, self.dataset, limit=-1)
        if not data.get("found", True):
            raise FatalError(f"dataset {self.dataset} not found")
        self.rows = data["rows"]
        self.columns = data["columns"]
        self.total = len(self.rows)
        missing = [c for c in (s.model_column, s.plan_column, s.lot_column)
                   if c not in self.columns]
        if missing:
            raise FatalError(f"the data has no column {missing}; it has {self.columns[:40]}")
        if s.status_column in self.columns:
            self.status_counts = dict(Counter(r.get(s.status_column) for r in self.rows))
        for w in result.get("warnings") or []:
            self.log(f"  note: {w}")
        self.log(f"Loaded {self.total} rows."
                 + (f" Status: {self.status_counts}" if self.status_counts else ""))
        return self.total, self.status_counts

    def _engine_log(self, message=""):
        text = str(message).rstrip()
        if text:
            self.log("  | " + text.strip())

    # ---- grid access ----------------------------------------------------
    def _grid(self):
        geom = cdp_common.evaluate(self.ws, core._js(JS_GRID_GEOM, json.dumps(self.s.result_grid),
                                                     json.dumps(self.win_id)))
        return geom if geom.get("found") else None

    def _cells(self):
        return cdp_common.evaluate(self.ws, core._js(core.JS_GRID_CELLS, json.dumps(self.s.result_grid),
                                                     json.dumps(self.win_id)))

    def _row_height(self, data):
        ncol = next((c for c, t in data["heads"].items() if t == "No."), None)
        ys = sorted(cells[ncol]["y"] for cells in data["rows"].values() if ncol in cells)
        gaps = [b - a for a, b in zip(ys, ys[1:]) if b - a > 5]
        return sorted(gaps)[len(gaps) // 2] if gaps else ROW_HEIGHT_FALLBACK

    def _row_cells(self, row_no, data=None):
        data = data or self._cells()
        try:
            res = core.find_grid_cell(data["heads"], data["rows"], {"No.": str(row_no)},
                                      self.s.link_column)
            model = core.find_grid_cell(data["heads"], data["rows"], {"No.": str(row_no)},
                                        "Model Code")["t"]
            plan = core.find_grid_cell(data["heads"], data["rows"], {"No.": str(row_no)},
                                       "Plan Date")["t"]
        except RuntimeError:
            return None
        return res, model, plan, data

    def bring_row_into_view(self, row_no):
        """Scroll the grid (its own scroll bar, not the mouse wheel - a wheel over
        this grid stalled the browser connection) until the row is inside the
        grid body, and return its link cell, model text and plan text."""
        geom = self._grid()
        if geom is None:
            raise FatalError("the result grid is not on screen any more")
        data = self._cells()
        row_h = self._row_height(data)
        for attempt in range(6):
            self._check()
            found = self._row_cells(row_no, data)
            if found and visible_in_grid(found[0], geom):
                return found[0], found[1], found[2]
            pos = max(0, (row_no - 1) * row_h - (attempt % 3) * row_h)
            cdp_common.evaluate(self.ws, core._js(JS_GRID_SCROLL, json.dumps(geom["path"]), str(pos)))
            end = time.time() + 4
            while time.time() < end:
                self._check()
                time.sleep(0.25)
                data = self._cells()
                found = self._row_cells(row_no, data)
                if found and visible_in_grid(found[0], geom):
                    return found[0], found[1], found[2]
        raise RuntimeError(f"row {row_no} could not be brought into view in {self.s.result_grid}")

    # ---- one row --------------------------------------------------------
    def _double_click(self, cell):
        x, y = cell["x"], cell["y"]
        cdp_common.send(self.ws, "Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        for n in (1, 2):
            cdp_common.send(self.ws, "Input.dispatchMouseEvent",
                            {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": n})
            cdp_common.send(self.ws, "Input.dispatchMouseEvent",
                            {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": n})
            time.sleep(0.08)

    def _dialog_trigger(self, model, plan_dash):
        """Runs between the double-click and the dialog's OK (inside download_excel)."""
        s = self.s

        def trigger(_ws):
            icon = self._wait(lambda: (lambda d: d if d.get("found") else None)(
                cdp_common.evaluate(self.ws, core._js(JS_MODAL_ICON, json.dumps(self.win_id)))),
                s.popup_timeout)
            if not icon:
                raise RuntimeError("the detail popup did not open")
            self._mark("popup icon visible")
            vals = []

            def loaded():
                nonlocal vals
                vals = cdp_common.evaluate(self.ws, JS_MODAL_VALUES)
                return model in vals and plan_dash in vals
            if not self._wait(loaded, s.popup_timeout):
                raise RuntimeError(f"the popup shows {vals[:6]}, not model {model} / plan {plan_dash} - "
                                   "the wrong row may have been opened")
            self._mark("popup data loaded")
            # A click that lands before the icon's handler is ready does nothing
            # (seen live on row 1070): press again, up to three times, until the
            # dialog is there. A modal dialog blocks a further click, so this
            # cannot open two.
            dlg = None
            for _attempt in range(3):
                icon = cdp_common.evaluate(self.ws, core._js(JS_MODAL_ICON, json.dumps(self.win_id)))
                if icon.get("found"):
                    core.click_element_by_rect(self.ws, icon["x"], icon["y"])
                self._mark("excel icon clicked")
                dlg = self._wait(lambda: (lambda d: d if d["rows"] else None)(
                    cdp_common.evaluate(self.ws, JS_DIALOG)), max(4.0, s.popup_timeout / 4))
                if dlg:
                    break
            if not dlg:
                raise RuntimeError("the 'Save to Excel' dialog did not show its grid list")
            self._mark("dialog visible")
            clicks, missing = plan_dialog_clicks(dlg["rows"], s.dialog_grids)
            if missing:      # a wrong setting, not a glitch: retrying cannot fix it
                raise FatalError(f"the 'Save to Excel' dialog has no grid {missing}; it offers "
                                 f"{[r['name'] for r in dlg['rows']]}. Change 'Grids to save in Excel'.")
            for row in dlg["rows"]:
                if row["name"] in clicks:
                    core.click_element_by_rect(self.ws, row["x"], row["y"])
                    time.sleep(0.4)
            if s.single_file is not None and dlg["single"] is not None \
                    and dlg["single"]["on"] != bool(s.single_file):
                core.click_element_by_rect(self.ws, dlg["single"]["x"], dlg["single"]["y"])
                time.sleep(0.4)
            after = cdp_common.evaluate(self.ws, JS_DIALOG)
            again, _ = plan_dialog_clicks(after["rows"], s.dialog_grids)
            if again:
                raise RuntimeError(f"the dialog's grid choice did not take: {again} still differ")
            if s.single_file is not None and after["single"] is not None \
                    and after["single"]["on"] != bool(s.single_file):
                raise RuntimeError("the 'save a single file' choice did not take")
            self._mark("dialog set, OK next")
            self._check()
        return trigger

    def export_row(self, index, stem_taken):
        """Export the grid row at data index `index`; returns (path, bytes)."""
        s = self.s
        row_no = index + 1
        d = self.rows[index]
        model, plan, lot = d[s.model_column], d[s.plan_column], d[s.lot_column]
        plan_dash = f"{plan[:4]}-{plan[4:6]}-{plan[6:8]}" if len(str(plan)) == 8 else str(plan)
        link, g_model, g_plan = self.bring_row_into_view(row_no)
        if g_model != model or g_plan != plan_dash:
            raise FatalError(f"grid row {row_no} shows {g_model}/{g_plan} but the data says "
                             f"{model}/{plan_dash}: the grid order changed (was it sorted?). Stopped.")
        if link["t"] != s.link_value:
            raise RuntimeError(f"row {row_no} shows {link['t']!r} under {s.link_column}, "
                               f"not {s.link_value!r}")
        self._mark("row in view")
        self._double_click(link)
        self._mark("double-clicked")
        path = core.download_excel(self.ws, self.out_dir, timeout=s.download_timeout,
                                   trigger=self._dialog_trigger(model, plan_dash), dialog=True)
        self._mark("file downloaded and popups closed")
        core.check_download(path)
        final = unique_path(self.out_dir, file_stem(s.name_pattern, plan, model, lot),
                            taken=stem_taken)
        os.replace(path, final)
        if not self._wait(lambda: self._grid() and self._cells()["rows"], 30):
            raise FatalError("the result grid did not come back after the export")
        return final, os.path.getsize(final)

    def _recover(self):
        """After a failed row: close popups, prove the grid is usable again."""
        try:
            gmes_common.close_child_popups(self.ws)
        except Exception:                                   # noqa: BLE001
            pass
        time.sleep(1.0)
        if not self._alive():
            raise FatalError("the browser connection is gone (was the window closed?). Stopped.")
        if not self._grid():
            raise FatalError("the G-MES screen is no longer in the expected state "
                             "(session expired or screen closed). Stopped.")

    # ---- the whole run --------------------------------------------------
    def prepare_output(self):
        s = self.s
        period = s.period or default_period(s.period_mode)
        out = s.out_dir.strip() or os.path.join(samir_env.data_dir(), "output",
                                                f"{s.screen_code}_{period}")
        os.makedirs(out, exist_ok=True)
        probe = os.path.join(out, ".write-test")
        with open(probe, "w") as fh:
            fh.write("x")
        os.remove(probe)
        self.out_dir = out
        return out

    def run(self):
        """Export the chosen rows. Returns a summary dict; never raises for Stop."""
        s = self.s
        started = time.time()
        summary = {"ok": 0, "skipped": 0, "failed": 0, "not_link": 0, "planned": 0,
                   "stopped": False, "fatal": "", "csv": "", "out_dir": ""}
        writer = fh = None
        try:
            out = self.prepare_output()
            summary["out_dir"] = out
            indices, other = select_rows(self.rows, s.status_column, s.link_value,
                                         s.start_row, s.count)
            summary["not_link"], summary["planned"] = other, len(indices)
            need = len(indices) * 60_000 + 50_000_000
            free = shutil.disk_usage(out).free
            if free < need:
                raise FatalError(f"only {free // 1_000_000} MB free in {out}; "
                                 f"about {need // 1_000_000} MB are needed")
            if s.count and len(indices) < s.count:
                self.log(f"You asked for {s.count} rows but only {len(indices)} match "
                         f"from row {s.start_row}; exporting those {len(indices)}.")
            if not indices:
                self.log("Nothing to export with these settings.")
                return summary
            csv_path = os.path.join(out, f"results_{datetime.now():%Y%m%d_%H%M%S}.csv")
            summary["csv"] = csv_path
            fh = open(csv_path, "w", newline="", encoding="utf-8")
            writer = csv.writer(fh)
            writer.writerow(["row_no", "plan", "model", "lot", "status", "file", "bytes", "seconds", "note"])
            self.log(f"Exporting {len(indices)} rows to {out}")
            if "{lot}" not in s.name_pattern:
                self.log("  note: the file name has no {lot}, so two rows can get the same name "
                         "(the second gets -2, -3 ...) and 'skip existing' cannot tell them apart "
                         "when you resume.")
            # 'Already exists' means: it was there BEFORE this run. A name this run produced
            # a moment ago belongs to another row and must not make this row look done.
            preexisting = set(os.listdir(out))
            taken, errors_in_row = set(), 0
            for n, index in enumerate(indices, 1):
                self._check()
                d = self.rows[index]
                plan, model, lot = d[s.plan_column], d[s.model_column], d[s.lot_column]
                row_no, t0 = index + 1, time.time()
                self._current = (row_no, plan, model, lot)
                stem = file_stem(s.name_pattern, plan, model, lot)
                existing = os.path.join(out, stem + ".xlsx")
                if (s.skip_existing and stem + ".xlsx" in preexisting
                        and os.path.isfile(existing) and os.path.getsize(existing) > 0):
                    summary["skipped"] += 1
                    writer.writerow([row_no, plan, model, lot, "skipped", os.path.basename(existing),
                                     os.path.getsize(existing), 0, "already exists"])
                    fh.flush()
                    self._current = None
                    self.log(f"[{n}/{len(indices)}] row {row_no}: already exists - skipped")
                    self.progress(done=n, total=len(indices), **self._counts(summary), row=row_no,
                                  eta=eta_seconds(n, len(indices), time.time() - started))
                    continue
                status, note, path, size = "ok", "", "", 0
                for attempt in range(s.retries + 1):
                    try:
                        path, size = self.export_row(index, taken)
                        break
                    except (StopRequested, FatalError):
                        raise
                    except Exception as e:                  # noqa: BLE001
                        note = f"{type(e).__name__}: {e}"
                        self.log(f"[{n}/{len(indices)}] row {row_no}: attempt {attempt + 1} failed - {note}")
                        try:
                            gmes_common.screenshot_on_failure(f"row{row_no}")
                        except Exception:                   # noqa: BLE001
                            pass
                        self._recover()
                        status = "failed"
                if status == "ok":
                    errors_in_row = 0
                    taken.add(os.path.basename(path))
                    summary["ok"] += 1
                    note = ""
                else:
                    summary["failed"] += 1
                    errors_in_row += 1
                writer.writerow([row_no, plan, model, lot, status,
                                 os.path.basename(path) if path else "", size,
                                 round(time.time() - t0, 1), note])
                fh.flush()
                self._current = None
                if status == "ok":
                    self.log(f"[{n}/{len(indices)}] row {row_no}: OK  {os.path.basename(path)}  "
                             f"{size} bytes  {time.time() - t0:.1f}s")
                self.progress(done=n, total=len(indices), **self._counts(summary), row=row_no,
                              eta=eta_seconds(n, len(indices), time.time() - started))
                if status == "failed":
                    if s.on_error == "stop":
                        raise FatalError(f"row {row_no} failed ({note}). Stopped, as 'On error = stop'.")
                    if errors_in_row >= s.max_errors:
                        raise FatalError(f"{errors_in_row} rows failed in a row. Stopped.")
                if s.pause_between:
                    self._sleep(s.pause_between)
        except StopRequested:
            summary["stopped"] = True
            self._note_unfinished(writer, "stopped", "stopped by you before this row finished - no file")
            self.log("STOP: the run was stopped by you. Closing any open popup...")
            try:
                gmes_common.close_child_popups(self.ws)
            except Exception:                               # noqa: BLE001
                pass
        except FatalError as e:
            summary["fatal"] = str(e)
            self._note_unfinished(writer, "aborted", str(e))
            self.log(f"STOPPED: {e}")
            try:
                gmes_common.close_child_popups(self.ws)
            except Exception:                               # noqa: BLE001
                pass
        except OSError as e:
            summary["fatal"] = f"file problem: {e}"
            self.log(f"STOPPED: {summary['fatal']}")
        finally:
            if fh:
                fh.close()
        summary["seconds"] = round(time.time() - started, 1)
        self.log(f"Done: {summary['ok']} exported, {summary['skipped']} skipped, "
                 f"{summary['failed']} failed of {summary['planned']} planned "
                 f"({summary['not_link']} rows not '{s.link_value}' were left alone) "
                 f"in {summary['seconds']}s.")
        return summary

    def _note_unfinished(self, writer, status, note):
        """One line in the result list for the row that was open when the run ended."""
        current = getattr(self, "_current", None)
        if writer is None or not current:
            return
        row_no, plan, model, lot = current
        writer.writerow([row_no, plan, model, lot, status, "", 0, 0, note])

    @staticmethod
    def _counts(summary):
        return {"ok": summary["ok"], "skipped": summary["skipped"], "failed": summary["failed"]}
