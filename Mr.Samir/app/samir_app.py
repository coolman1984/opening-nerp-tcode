"""Samir Export - the window.

Two tabs:
  Export             filters -> Connect & load rows -> choose rows and files -> Start.
                     Stop (or Esc) is always one click away.
  Account & Browser  the person's own G-MES login (encrypted for their Windows
                     account) and which browser's profile the automation copies.

Also:  SamirExport.exe --cli <options>   the same engine without a window
       SamirExport.exe --selftest        checks that everything needed is present
"""
import os
import queue
import re
import sys
import threading
import traceback
from dataclasses import asdict
from datetime import datetime

import samir_env

if samir_env.FROZEN and sys.stdout is None:          # a windowed .exe has no console
    os.makedirs(os.path.join(samir_env.data_dir(), "logs"), exist_ok=True)
    _console = open(os.path.join(samir_env.data_dir(), "logs", "console.txt"), "a", buffering=1,
                    encoding="utf-8")
    sys.stdout = sys.stderr = _console

samir_env.setup()

import json                                   # noqa: E402
import tkinter as tk                          # noqa: E402
from tkinter import filedialog, ttk           # noqa: E402

import cdp_common                             # noqa: E402
import samir_runner as sr                     # noqa: E402
import samir_setup as setup                   # noqa: E402
import samir_ui as ui                         # noqa: E402
from samir_ui import C, F, S                  # noqa: E402

VERSION = "2.0"
APP_NAME = "Samir Export"
SETTINGS_FILE = os.path.join(samir_env.data_dir(), "settings.json")
LOG_FILE = os.path.join(samir_env.data_dir(), "logs", f"samir_{datetime.now():%Y%m%d}.log")
SECONDS_PER_ROW = 6.5            # measured live, 2026-09-30 (5.8 - 6.6 s; some rows 14 s)
DIVISIONS = ("MAIN Part", "LCM Part", "SMD Part", "PBA Part", "OCM", "MKD Part", "KD Part",
             "BND", "Production 1", "Production 2", "VD")
KNOWN_GRIDS = (("grdPackInspArtList", "Grid 1 - grdPackInspArtList"),
               ("grdDtlInspArtList", "Grid 2 - grdDtlInspArtList"))
NAME_PRESETS = (("{plan}_{model}_{lot}", "Plan date _ Model _ Lot no.   (recommended)"),
                ("{model}_{lot}", "Model _ Lot no."),
                ("{lot}", "Lot no. only"),
                ("{plan}_{lot}", "Plan date _ Lot no."))
SIGNED_IN = re.compile(r"[Ss]igned in as '([^']+)'")


# --------------------------------------------------------------------------
# Engine output -> the activity log
# --------------------------------------------------------------------------
class OutputSink:
    """Everything the engine prints (sign-in progress, first-run copy) reaches the
    window's log as whole lines, from any thread, and still goes to the console
    file. The engine never prints a password (CLAUDE.md 2.2)."""

    def __init__(self, fallback):
        self.fallback = fallback
        self.target = None
        self._buffers = {}
        self._lock = threading.Lock()

    def write(self, text):
        if self.fallback is not None:
            try:
                self.fallback.write(text)
            except Exception:                                # noqa: BLE001
                pass
        tid = threading.get_ident()
        with self._lock:
            parts = (self._buffers.get(tid, "") + text).split("\n")
            self._buffers[tid] = parts.pop()
        for line in parts:
            if self.target is not None:
                self.target(line.rstrip("\r"))
        return len(text)

    def flush(self):
        if self.fallback is not None:
            try:
                self.fallback.flush()
            except Exception:                                # noqa: BLE001
                pass

    def isatty(self):
        return False


def classify(text):
    t = text.lower()
    if re.search(r"fail|stopped|problem|error|refus|could not|cannot|not found|gone", t):
        return "err"
    if re.search(r"\bok\b|exported|signed in as|loaded \d|ready|copied", t):
        return "ok"
    if re.search(r"note|warning|skipped|already exists|paused|stop pressed|first use", t):
        return "warn"
    if text.startswith(("  |", "    ", "  (")):
        return "muted"
    return "info"


def fmt_eta(seconds):
    if not seconds or seconds <= 0:
        return "-"
    h, rest = divmod(int(seconds), 3600)
    m, s = divmod(rest, 60)
    return f"{h}h {m:02d}m" if h else (f"{m}m {s:02d}s" if m else f"{s}s")


def pretty_period(mode, value):
    if mode == "Monthly" and len(value) == 6:
        return f"{value[:4]}-{value[4:]}"
    if len(value) == 8:
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


def load_saved():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("settings_version", 1) < 2 and data.get("link_value") == "PASS":
            data["link_value"] = ""        # v1 exported PASS only; the owner wants every status
        return sr.Settings.from_dict(data), data.get("browser", "auto")
    except (OSError, ValueError, TypeError):
        return sr.Settings(), "auto"


# --------------------------------------------------------------------------
# The window
# --------------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self):
        ui.make_dpi_aware()
        super().__init__()
        ui.setup_theme(self)
        self.title(f"{APP_NAME} - G-MES Detail Inspection")
        self.configure(bg=C["bg"])
        self._set_icon()
        w = min(S(1340), self.winfo_screenwidth() - S(40))
        h = min(S(880), self.winfo_screenheight() - S(90))
        self.geometry(f"{w}x{h}+{max(0, (self.winfo_screenwidth() - w) // 2)}+"
                      f"{max(0, (self.winfo_screenheight() - h) // 3)}")
        self.minsize(min(S(1120), w), min(S(700), h))

        self.saved, self.browser_choice = load_saved()
        self.runner = None
        self.state = "idle"          # idle | connecting | connected | loading | loaded | running
        self.loaded_signature = None
        self.q = queue.Queue()
        self.worker = None
        self.run_started = None
        self.last_summary = None
        self.signed_in_as = ""
        self.login_user = None

        self.sink = OutputSink(sys.stdout)
        self.sink.target = lambda line: self._post("engine_line", text=line)
        sys.stdout = self.sink
        sys.stderr = self.sink

        try:
            setup.apply_browser_choice(self.browser_choice)
        except Exception as e:                                # noqa: BLE001
            self.browser_choice = "auto"
            setup.apply_browser_choice("auto")
            self._early_note = f"Browser choice reset to Automatic ({e})."
        else:
            self._early_note = ""

        self._build()
        self.bind("<Escape>", lambda _e: self._on_stop() if self.state in ("running", "connecting",
                                                                            "loading") else None)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._pump)
        self.after(250, self._tick)
        self._set_state("idle")
        self._log("Welcome. Check the filters on the left, then press 'Connect & load rows'.", "info")
        if self._early_note:
            self._log(self._early_note, "warn")
        self.after(300, self.refresh_account)

    def _set_icon(self):
        base = getattr(sys, "_MEIPASS", samir_env.HERE)
        for path in (os.path.join(base, "assets", "samir.ico"),
                     os.path.join(samir_env.HERE, "assets", "samir.ico")):
            if os.path.isfile(path):
                try:
                    self.iconbitmap(default=path)
                except tk.TclError:
                    pass
                return

    # ---- layout -----------------------------------------------------------
    def _build(self):
        self._build_header()
        self._build_tabs()
        self._build_statusbar()
        self.content = tk.Frame(self, bg=C["bg"])
        self.content.pack(fill="both", expand=True)
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)
        self.page_export = tk.Frame(self.content, bg=C["bg"])
        self.page_account = tk.Frame(self.content, bg=C["bg"])
        for page in (self.page_export, self.page_account):
            page.grid(row=0, column=0, sticky="nsew")
        self._build_export(self.page_export)
        self._build_account(self.page_account)
        self.show_tab("export")

    def _build_header(self):
        bar = tk.Frame(self, bg=C["header"], height=S(64))
        bar.pack(fill="x")
        bar.pack_propagate(False)
        logo = tk.Canvas(bar, width=S(38), height=S(38), bg=C["header"], highlightthickness=0)
        logo.create_rectangle(0, 0, S(38), S(38), fill=C["accent"], outline="")
        logo.create_polygon(S(38), 0, S(38), S(38), S(14), S(38), fill="#3B82F6", outline="")
        logo.create_text(S(19), S(19), text="S", fill="white", font=("Segoe UI Semibold", 16))
        logo.pack(side="left", padx=(S(22), S(14)))
        titles = tk.Frame(bar, bg=C["header"])
        titles.pack(side="left")
        tk.Label(titles, text=APP_NAME, font=F["title"], bg=C["header"], fg="white",
                 anchor="w").pack(anchor="w")
        tk.Label(titles, text="G-MES  ·  Detail Inspection  ·  Q321KUM00  ·  one Excel file per row",
                 font=F["subtitle"], bg=C["header"], fg=C["header_muted"], anchor="w").pack(anchor="w")
        right = tk.Frame(bar, bg=C["header"])
        right.pack(side="right", padx=S(22))
        self.pill = ui.Pill(right)
        self.pill.pack(side="right")
        self.lbl_user = tk.Label(right, text="", font=F["small"], bg=C["header"], fg=C["header_text"])
        self.lbl_user.pack(side="right", padx=(0, S(14)))

    def _build_tabs(self):
        bar = tk.Frame(self, bg=C["card"])
        bar.pack(fill="x")
        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")
        self.tabs = {}
        for key, text in (("export", "Export"), ("account", "Account & Browser")):
            holder = tk.Frame(bar, bg=C["card"])
            holder.pack(side="left", padx=(S(14) if key == "export" else 0, 0))
            b = ui.FlatButton(holder, text, command=lambda k=key: self.show_tab(k), kind="tab_off",
                              font=F["tab"], padx=18, pady=10)
            b.configure(highlightthickness=0)
            b.pack()
            line = tk.Frame(holder, bg=C["card"], height=S(3))
            line.pack(fill="x")
            self.tabs[key] = (b, line)
        self.tab_dot = tk.Label(bar, text="", font=F["small"], bg=C["card"], fg=C["err"])
        self.tab_dot.pack(side="left", padx=(S(2), 0))

    def show_tab(self, key):
        self.current_tab = key
        for k, (b, line) in self.tabs.items():
            b.set_kind("tab_on" if k == key else "tab_off")
            line.configure(bg=C["accent"] if k == key else C["card"])
        (self.page_export if key == "export" else self.page_account).tkraise()
        if key == "account":
            self.refresh_account()

    def _build_statusbar(self):
        bar = tk.Frame(self, bg=C["card"])
        bar.pack(side="bottom", fill="x")
        tk.Frame(bar, bg=C["border"], height=1).pack(fill="x", side="top")
        self.lbl_status = tk.Label(bar, text="", font=F["small"], bg=C["card"], fg=C["muted"], anchor="w")
        self.lbl_status.pack(side="left", padx=S(16), pady=S(5))
        tk.Label(bar, text=f"{APP_NAME} {VERSION}   ·   read-only in G-MES   ·   Esc = Stop",
                 font=F["small"], bg=C["card"], fg=C["faint"]).pack(side="right", padx=S(16))
        self._status(f"Files and logs: {samir_env.data_dir()}")

    def _status(self, text):
        self.lbl_status.configure(text=text)

    # ---- Export tab -------------------------------------------------------
    def _build_export(self, page):
        page.grid_columnconfigure(0, minsize=S(470))
        page.grid_columnconfigure(1, weight=1)
        page.grid_rowconfigure(0, weight=1)
        left = ui.ScrollFrame(page, C["bg"])
        left.grid(row=0, column=0, sticky="nsew", padx=(S(18), S(8)), pady=S(16))
        col = left.inner
        right = tk.Frame(page, bg=C["bg"])
        right.grid(row=0, column=1, sticky="nsew", padx=(S(8), S(18)), pady=S(16))
        self._build_filters(col)
        self._build_rows(col)
        self._build_files(col)
        self._build_advanced(col)
        self._build_run(right)

    def _grid_field(self, parent, row, label, widget, hint=None, col=0, span=1, pady=(0, 10)):
        ui.field_label(parent, label, hint).grid(row=row, column=col, columnspan=span, sticky="w")
        widget.grid(row=row + 1, column=col, columnspan=span, sticky="we", pady=(S(4), S(pady[1])))

    def _build_filters(self, col):
        s = self.saved
        card = ui.Card(col, "Filters", step=1, subtitle="What G-MES should list - like the left panel")
        card.pack(fill="x", pady=(0, S(12)))
        b = card.body
        b.grid_columnconfigure(0, weight=1)
        b.grid_columnconfigure(1, weight=1)
        self.v_div = tk.StringVar(value=s.division)
        self._grid_field(b, 0, "Organization", ttk.Combobox(b, textvariable=self.v_div, values=DIVISIONS),
                         hint="tree entry, e.g. MAIN Part", span=2)
        self.v_mode = tk.StringVar(value=s.period_mode)
        ui.field_label(b, "Period").grid(row=2, column=0, columnspan=2, sticky="w")
        self.seg_mode = ui.Segmented(b, (("Monthly", "Monthly"), ("Daily", "Daily")), self.v_mode,
                                     command=self._period_changed)
        self.seg_mode.grid(row=3, column=0, sticky="w", pady=(S(4), S(8)))
        which = {"": "current", "current": "current", "previous": "previous"}.get(s.period.lower(), "custom")
        self.v_which = tk.StringVar(value=which)
        self.seg_which = ui.Segmented(b, (("current", "This month"), ("previous", "Last month"),
                                          ("custom", "Choose...")), self.v_which,
                                      command=self._period_changed, padx=11)
        self.seg_which.grid(row=4, column=0, columnspan=2, sticky="w")
        self.v_custom = tk.StringVar(value=s.period if which == "custom" else "")
        self.custom_row = tk.Frame(b, bg=C["card"])
        self.custom_row.grid(row=5, column=0, columnspan=2, sticky="we", pady=(S(8), 0))
        self.ent_custom = ttk.Entry(self.custom_row, textvariable=self.v_custom, width=14)
        self.ent_custom.pack(side="left")
        self.lbl_custom_hint = tk.Label(self.custom_row, font=F["small"], bg=C["card"], fg=C["faint"])
        self.lbl_custom_hint.pack(side="left", padx=S(10))
        self.lbl_period = tk.Label(b, font=F["label"], bg=C["card"], fg=C["accent"], anchor="w")
        self.lbl_period.grid(row=6, column=0, columnspan=2, sticky="w", pady=(S(8), S(10)))
        filters = dict(f.split("=", 1) for f in s.extra_filters if "=" in f)
        self.v_model = tk.StringVar(value=filters.pop("Model", ""))
        self.v_sn = tk.StringVar(value=filters.pop("SN No.", ""))
        self._more_filters_initial = "; ".join(f"{k}={v}" for k, v in filters.items())
        self._grid_field(b, 7, "Model", ttk.Entry(b, textvariable=self.v_model), hint="optional", col=0)
        self._grid_field(b, 7, "SN No.", ttk.Entry(b, textvariable=self.v_sn), hint="optional", col=1)
        for var in (self.v_div, self.v_model, self.v_sn, self.v_custom):
            var.trace_add("write", lambda *_a: self._filters_changed())
        self._period_changed(initial=True)

    def _build_rows(self, col):
        s = self.saved
        card = ui.Card(col, "Rows", step=2, subtitle="Which rows of the list get their Excel file")
        card.pack(fill="x", pady=(0, S(12)))
        b = card.body
        b.grid_columnconfigure(0, weight=1)
        b.grid_columnconfigure(1, weight=1)
        self.v_start = tk.StringVar(value=str(s.start_row))
        self.v_count = tk.StringVar(value=str(s.count or 20))
        self.v_all = tk.BooleanVar(value=s.count == 0)
        self._grid_field(b, 0, "Start at row No.", ttk.Spinbox(b, from_=1, to=999999, increment=1,
                                                             textvariable=self.v_start), col=0)
        self.spin_count = ttk.Spinbox(b, from_=1, to=999999, increment=1, textvariable=self.v_count)
        self._grid_field(b, 0, "How many rows", self.spin_count, col=1)
        chips = tk.Frame(b, bg=C["card"])
        chips.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, S(6)))
        tk.Label(chips, text="Quick:", font=F["small"], bg=C["card"], fg=C["muted"]).pack(side="left")
        for n in (5, 20, 100, 500):
            ui.FlatButton(chips, str(n), command=lambda n=n: self._quick_count(n), kind="chip",
                          font=F["label"], padx=10, pady=3).pack(side="left", padx=(S(6), 0))
        ttk.Checkbutton(b, text="All remaining rows", variable=self.v_all,
                        command=self._rows_changed).grid(row=3, column=0, columnspan=2, sticky="w")
        self.lbl_rows = ui.note(b, "Load the rows to see what will be exported.", wrap=400)
        self.lbl_rows.grid(row=4, column=0, columnspan=2, sticky="we", pady=(S(8), 0))
        for var in (self.v_start, self.v_count):
            var.trace_add("write", lambda *_a: self._rows_changed())
        self._rows_changed()

    def _build_files(self, col):
        s = self.saved
        card = ui.Card(col, "Excel files", step=3, subtitle="What the 'Save to Excel' box saves, and where")
        card.pack(fill="x", pady=(0, S(12)))
        b = card.body
        b.grid_columnconfigure(0, weight=1)
        ui.field_label(b, "Grids to tick in 'Save to Excel'").grid(row=0, column=0, sticky="w")
        self.grid_vars = {}
        wanted = {g.lower() for g in s.dialog_grids}
        for i, (name, label) in enumerate(KNOWN_GRIDS):
            var = tk.BooleanVar(value=name.lower() in wanted)
            self.grid_vars[name] = var
            ttk.Checkbutton(b, text=label, variable=var).grid(row=1 + i, column=0, sticky="w",
                                                              pady=(S(2), 0))
        self.v_single = tk.BooleanVar(value=s.single_file is not False)
        ttk.Checkbutton(b, text="Save as a single file", variable=self.v_single).grid(
            row=3, column=0, sticky="w", pady=(S(2), S(10)))
        labels = [label for _p, label in NAME_PRESETS]
        current = next((label for p, label in NAME_PRESETS if p == s.name_pattern), s.name_pattern)
        self.v_pattern = tk.StringVar(value=current)
        self._grid_field(b, 4, "File name", ttk.Combobox(b, textvariable=self.v_pattern, values=labels),
                         hint="a file is never overwritten")
        self.v_skip = tk.BooleanVar(value=s.skip_existing)
        ttk.Checkbutton(b, text="Skip rows whose file already exists  (resume a stopped run)",
                        variable=self.v_skip).grid(row=6, column=0, sticky="w", pady=(0, S(10)))
        ui.field_label(b, "Save the files in").grid(row=7, column=0, sticky="w")
        row = tk.Frame(b, bg=C["card"])
        row.grid(row=8, column=0, sticky="we", pady=(S(4), 0))
        self.v_out = tk.StringVar(value=s.out_dir)
        ttk.Entry(row, textvariable=self.v_out).pack(side="left", fill="x", expand=True)
        ui.FlatButton(row, "Browse", command=self._browse, kind="secondary", font=F["label"],
                      padx=12, pady=5).pack(side="left", padx=(S(8), 0))
        ui.note(b, "Empty = Mr.Samir\\data\\output\\<screen>_<period>", fg=C["faint"]).grid(
            row=9, column=0, sticky="w", pady=(S(4), 0))

    def _build_advanced(self, col):
        s = self.saved
        card = ui.Card(col, "Advanced", subtitle="Only if the screen or the task changes")
        card.pack(fill="x", pady=(0, S(4)))
        self.adv_open = tk.BooleanVar(value=False)
        self.adv_toggle = ui.FlatButton(card.head_right, "Show", command=self._toggle_adv, kind="ghost",
                                        font=F["label"], padx=10, pady=3)
        self.adv_toggle.pack()
        b = card.body
        self.adv_body = tk.Frame(b, bg=C["card"])
        a = self.adv_body
        a.grid_columnconfigure(0, weight=1)
        a.grid_columnconfigure(1, weight=1)
        self.v_grid = tk.StringVar(value=s.result_grid)
        self.v_linkcol = tk.StringVar(value=s.link_column)
        self.v_linkval = tk.StringVar(value=s.link_value)
        self.v_more_grids = tk.StringVar(value=", ".join(g for g in s.dialog_grids
                                                         if g.lower() not in {k.lower() for k, _ in KNOWN_GRIDS}))
        self.v_more_filters = tk.StringVar(value=self._more_filters_initial)
        self.v_onerr = tk.StringVar(value=s.on_error)
        self.v_retries = tk.StringVar(value=str(s.retries))
        self.v_pause = tk.StringVar(value=str(s.pause_between))
        self._grid_field(a, 0, "Result grid", ttk.Entry(a, textvariable=self.v_grid), col=0)
        self._grid_field(a, 0, "Column to double-click", ttk.Entry(a, textvariable=self.v_linkcol), col=1)
        self._grid_field(a, 2, "Only rows showing", ttk.Entry(a, textvariable=self.v_linkval),
                         hint="empty = every status", col=0)
        self._grid_field(a, 2, "More Excel grids", ttk.Entry(a, textvariable=self.v_more_grids),
                         hint="names, comma", col=1)
        self._grid_field(a, 4, "More filters", ttk.Entry(a, textvariable=self.v_more_filters),
                         hint="Name=Value; Name=Value", span=2)
        ui.field_label(a, "When a row fails").grid(row=6, column=0, columnspan=2, sticky="w")
        ui.Segmented(a, (("stop", "Stop the run"), ("skip", "Skip it and go on")), self.v_onerr,
                     padx=12).grid(row=7, column=0, columnspan=2, sticky="w", pady=(S(4), S(10)))
        self._grid_field(a, 8, "Retries per row", ttk.Spinbox(a, from_=0, to=5, textvariable=self.v_retries),
                         col=0)
        self._grid_field(a, 8, "Pause between rows (s)",
                         ttk.Spinbox(a, from_=0, to=60, increment=0.5, textvariable=self.v_pause), col=1)
        for var in (self.v_grid, self.v_linkval, self.v_more_filters):
            var.trace_add("write", lambda *_a: self._filters_changed())

    def _toggle_adv(self):
        if self.adv_open.get():
            self.adv_body.pack_forget()
            self.adv_open.set(False)
            self.adv_toggle.set_text("Show")
        else:
            self.adv_body.pack(fill="x")
            self.adv_open.set(True)
            self.adv_toggle.set_text("Hide")

    def _build_run(self, parent):
        self.banner_login = ui.Banner(parent, "", "warn", wrap=620,
                                      action=lambda: self.show_tab("account"), action_text="Open Account")
        run = ui.Card(parent, "Run", subtitle="Connect, check the numbers, then start")
        run.pack(fill="x", pady=(0, S(12)))
        self.run_card = run
        b = run.body
        top = tk.Frame(b, bg=C["card"])
        top.pack(fill="x")
        self.lbl_state = tk.Label(top, text="", font=F["status"], bg=C["card"], fg=C["text"], anchor="w")
        self.lbl_state.pack(fill="x")
        self.lbl_state_sub = tk.Label(top, text="", font=F["small"], bg=C["card"], fg=C["muted"],
                                      anchor="w", justify="left", wraplength=S(700))
        self.lbl_state_sub.pack(fill="x", pady=(S(2), 0))

        btns = tk.Frame(b, bg=C["card"])
        btns.pack(fill="x", pady=(S(14), S(4)))
        self.btn_load = ui.FlatButton(btns, "Connect & load rows", command=self._on_load, kind="primary",
                                      font=F["button_lg"], padx=18, pady=9)
        self.btn_load.pack(side="left")
        self.btn_start = ui.FlatButton(btns, "▶  Start export", command=self._on_start, kind="success",
                                       font=F["button_lg"], padx=22, pady=9)
        self.btn_start.pack(side="left", padx=(S(10), 0))
        self.btn_pause = ui.FlatButton(btns, "❚❚  Pause", command=self._on_pause, kind="secondary",
                                       font=F["button_lg"], padx=16, pady=9)
        self.btn_pause.pack(side="left", padx=(S(10), 0))
        self.btn_stop = ui.FlatButton(btns, "■  Stop", command=self._on_stop, kind="danger",
                                      font=F["button_lg"], padx=20, pady=9)
        self.btn_stop.pack(side="left", padx=(S(10), 0))
        self.btn_now = ui.FlatButton(btns, "Force stop + close browser", command=self._on_stop_now,
                                     kind="dark", font=F["label"], padx=12, pady=6)
        self.btn_now.pack(side="right")

        tiles = tk.Frame(b, bg=C["card"])
        tiles.pack(fill="x", pady=(S(14), 0))
        self.tiles = {}
        for i, (key, caption, color) in enumerate((
                ("found", "In G-MES", C["faint"]), ("todo", "To export", C["accent"]),
                ("ok", "Exported", C["ok"]), ("skipped", "Skipped", C["warn"]),
                ("failed", "Failed", C["err"]), ("eta", "Time left", C["header2"]))):
            tile = ui.StatTile(tiles, caption, "-", color)
            tile.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else S(8), 0))
            tiles.grid_columnconfigure(i, weight=1, uniform="tile")
            self.tiles[key] = tile

        prog = tk.Frame(b, bg=C["card"])
        prog.pack(fill="x", pady=(S(14), 0))
        self.bar = ttk.Progressbar(prog, mode="determinate", style="Run.Horizontal.TProgressbar")
        self.bar.pack(fill="x")
        line = tk.Frame(prog, bg=C["card"])
        line.pack(fill="x", pady=(S(6), 0))
        self.lbl_prog = tk.Label(line, text="", font=F["small"], bg=C["card"], fg=C["muted"], anchor="w")
        self.lbl_prog.pack(side="left")
        self.lbl_pct = tk.Label(line, text="", font=F["label"], bg=C["card"], fg=C["text"], anchor="e")
        self.lbl_pct.pack(side="right")

        act = ui.Card(parent, "Activity")
        act.pack(fill="both", expand=True)
        for text, cmd in (("Clear", self._clear_log), ("Log file", self._open_log),
                          ("Result list", self._open_results), ("Output folder", self._open_out)):
            ui.FlatButton(act.head_right, text, command=cmd, kind="ghost", font=F["label"],
                          padx=10, pady=3).pack(side="right", padx=(S(4), 0))
        box = tk.Frame(act.body, bg=C["console"])
        box.pack(fill="both", expand=True)
        self.log_text = tk.Text(box, wrap="word", state="disabled", font=F["mono"], bg=C["console"],
                                fg=C["console_text"], insertbackground="white", relief="flat", bd=0,
                                padx=S(14), pady=S(10), height=10, selectbackground="#27406E")
        sb = ttk.Scrollbar(box, command=self.log_text.yview, style="Console.Vertical.TScrollbar")
        self.log_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)
        for tag, color in (("time", "#56657E"), ("info", "#DCE4F0"), ("muted", "#7D8BA3"),
                           ("ok", "#4ADE80"), ("warn", "#FBBF24"), ("err", "#F87171")):
            self.log_text.tag_configure(tag, foreground=color)

    # ---- Account tab ------------------------------------------------------
    def _build_account(self, page):
        scroller = ui.ScrollFrame(page, C["bg"])          # small laptop screens: nothing is cut off
        scroller.pack(fill="both", expand=True, padx=(S(18), S(8)), pady=S(16))
        wrap = tk.Frame(scroller.inner, bg=C["bg"])
        wrap.pack(fill="both", expand=True, padx=(0, S(10)))
        ready = ui.Card(wrap, "This PC", subtitle="Everything the export needs, checked without "
                                                  "signing in")
        ready.pack(fill="x", pady=(0, S(12)))
        self.ready_items = {}
        row = tk.Frame(ready.body, bg=C["card"])
        row.pack(fill="x")
        for i, (key, text) in enumerate((("login", "G-MES login"), ("browser", "Chrome / Edge"),
                                         ("copy", "Browser copy"), ("folder", "Output folder"))):
            cell = tk.Frame(row, bg=C["tile"], highlightthickness=1, highlightbackground=C["line"])
            cell.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else S(10), 0))
            row.grid_columnconfigure(i, weight=1, uniform="ready")
            dot = tk.Canvas(cell, width=S(22), height=S(22), bg=C["tile"], highlightthickness=0)
            dot.pack(side="left", padx=(S(12), S(8)), pady=S(12))
            texts = tk.Frame(cell, bg=C["tile"])
            texts.pack(side="left", fill="x", expand=True, pady=S(8))
            tk.Label(texts, text=text, font=F["label"], bg=C["tile"], fg=C["text"], anchor="w").pack(fill="x")
            detail = tk.Label(texts, text="checking...", font=F["small"], bg=C["tile"], fg=C["muted"],
                              anchor="w", justify="left", wraplength=S(230))
            detail.pack(fill="x")
            self.ready_items[key] = (dot, detail)

        cols = tk.Frame(wrap, bg=C["bg"])
        cols.pack(fill="both", expand=True)
        cols.grid_columnconfigure(0, weight=1, uniform="acc")
        cols.grid_columnconfigure(1, weight=1, uniform="acc")
        cols.grid_rowconfigure(0, weight=1)
        self._build_login_card(cols)
        self._build_browser_card(cols)

    def _build_login_card(self, cols):
        card = ui.Card(cols, "G-MES login", step="A", subtitle="The Knox / G-MES account this PC signs in with")
        card.grid(row=0, column=0, sticky="nsew", padx=(0, S(6)))
        b = card.body
        b.grid_columnconfigure(0, weight=1)
        self.login_banner = ui.Banner(b, "", "info", wrap=440)
        self.login_banner.grid(row=0, column=0, sticky="we", pady=(0, S(14)))
        self.v_user = tk.StringVar()
        self.v_pw1 = tk.StringVar()
        self.v_pw2 = tk.StringVar()
        self._grid_field(b, 1, "Knox / G-MES user ID", ttk.Entry(b, textvariable=self.v_user))
        pw_row = tk.Frame(b, bg=C["card"])
        self.ent_pw1 = ttk.Entry(pw_row, textvariable=self.v_pw1, show="•")
        self.ent_pw1.pack(side="left", fill="x", expand=True)
        self.btn_show = ui.FlatButton(pw_row, "Show", command=self._toggle_pw, kind="secondary",
                                      font=F["label"], padx=12, pady=5)
        self.btn_show.pack(side="left", padx=(S(8), 0))
        self._grid_field(b, 3, "Password", pw_row)
        self.ent_pw2 = ttk.Entry(b, textvariable=self.v_pw2, show="•")
        self._grid_field(b, 5, "Password again", self.ent_pw2)
        btns = tk.Frame(b, bg=C["card"])
        btns.grid(row=7, column=0, sticky="w", pady=(S(4), S(12)))
        self.btn_save_login = ui.FlatButton(btns, "Save login", command=self._on_save_login, kind="primary")
        self.btn_save_login.pack(side="left")
        self.btn_test = ui.FlatButton(btns, "Test sign-in", command=self._on_test_signin, kind="secondary")
        self.btn_test.pack(side="left", padx=(S(10), 0))
        ui.note(b, "Encrypted with Windows (DPAPI) for this Windows account only - nobody else, and no "
                   "other PC, can read it. It is never shown, logged or written anywhere else, and is "
                   "only typed into the Samsung sign-in page. Each person saves their OWN login on "
                   "their own laptop.", wrap=460).grid(row=8, column=0, sticky="we")
        self.lbl_store = ui.note(b, "", fg=C["faint"], wrap=460)
        self.lbl_store.grid(row=9, column=0, sticky="we", pady=(S(6), 0))

    def _build_browser_card(self, cols):
        card = ui.Card(cols, "Browser", step="B", subtitle="Whose browser profile the automation starts from")
        card.grid(row=0, column=1, sticky="nsew", padx=(S(6), 0))
        b = card.body
        b.grid_columnconfigure(0, weight=1)
        self.v_browser = tk.StringVar(value=self.browser_choice)
        ui.field_label(b, "Use").grid(row=0, column=0, sticky="w")
        self.seg_browser = ui.Segmented(b, (("auto", "Automatic (Windows default)"), ("chrome", "Chrome"),
                                            ("edge", "Edge")), self.v_browser, padx=12)
        self.seg_browser.grid(row=1, column=0, sticky="w", pady=(S(4), S(12)))
        self.browser_rows = tk.Frame(b, bg=C["card"])
        self.browser_rows.grid(row=2, column=0, sticky="we")
        self.browser_banner = ui.Banner(b, "Checking the browsers on this PC...", "info", wrap=440)
        self.browser_banner.grid(row=3, column=0, sticky="we", pady=(S(12), S(8)))
        self.lbl_profile = ui.note(b, "", fg=C["faint"], wrap=460)
        self.lbl_profile.grid(row=4, column=0, sticky="we")
        btns = tk.Frame(b, bg=C["card"])
        btns.grid(row=5, column=0, sticky="w", pady=(S(12), S(10)))
        self.btn_apply_browser = ui.FlatButton(btns, "Use this browser", command=self._on_apply_browser,
                                               kind="primary")
        self.btn_apply_browser.pack(side="left")
        ui.FlatButton(btns, "Check again", command=self.refresh_account, kind="secondary").pack(
            side="left", padx=(S(10), 0))
        ui.note(b, "On the first Connect, the tool makes its OWN copy of this person's Chrome or Edge "
                   "profile, once - so a G-MES session they already have comes along. Their own "
                   "browser is only read: never changed, never controlled, never deleted. If that "
                   "browser is open during the first copy, the tool asks to close it once.",
                wrap=460).grid(row=6, column=0, sticky="we")

    # ---- account logic -----------------------------------------------------
    def refresh_account(self):
        user, problem = setup.saved_login()
        self.login_user = user
        store = setup.store_location()
        self.lbl_store.configure(text=f"Stored in: {store}")
        if user:
            self.login_banner.set(f"Saved for Windows user '{setup.windows_user()}':  Knox ID  {user}.\n"
                                  "Type a new user ID and password below only to replace it.", "ok")
            self._ready("login", "ok", f"saved ({user})")
            self.tab_dot.configure(text="")
            self.banner_login.pack_forget()
        else:
            text = (f"{problem}. Enter the login again to replace it." if problem else
                    "No login saved on this PC yet. Enter the Knox / G-MES user ID and password, "
                    "then press Save login.")
            self.login_banner.set(text, "warn")
            self._ready("login", "err", "not saved yet" if not problem else problem)
            self.tab_dot.configure(text="●")
            self.banner_login.set("No G-MES login is saved on this PC yet - add it on the Account & "
                                  "Browser tab first.", "warn")
            if not self.banner_login.winfo_ismapped():
                self.banner_login.pack(fill="x", pady=(0, S(12)), before=self.run_card)
        try:
            out = os.path.join(samir_env.data_dir(), "output")
            os.makedirs(out, exist_ok=True)
            probe = os.path.join(out, ".write-test")
            with open(probe, "w") as fh:
                fh.write("x")
            os.remove(probe)
            self._ready("folder", "ok", "writable")
        except OSError as e:
            self._ready("folder", "err", f"cannot write: {e.strerror or e}")
        threading.Thread(target=lambda: self._post("browsers", info=setup.describe_browsers()),
                         daemon=True).start()

    def _ready(self, key, tone, text):
        dot, detail = self.ready_items[key]
        color = {"ok": C["ok"], "warn": C["warn"], "err": C["err"], "info": C["accent"]}[tone]
        dot.delete("all")
        dot.create_oval(S(2), S(2), S(20), S(20), fill=color, outline="")
        dot.create_text(S(11), S(11), text={"ok": "✓", "err": "!", "warn": "!", "info": "i"}[tone],
                        fill="white", font=F["badge"])
        detail.configure(text=text)

    def _on_browsers_msg(self, info):
        for w in self.browser_rows.winfo_children():
            w.destroy()
        installed = [x for x in info["browsers"] if x["installed"]]
        for i, br in enumerate(info["browsers"]):
            cell = tk.Frame(self.browser_rows, bg=C["tile"], highlightthickness=1,
                            highlightbackground=C["line"])
            cell.pack(fill="x", pady=(0 if i == 0 else S(8), 0))
            top = tk.Frame(cell, bg=C["tile"])
            top.pack(fill="x", padx=S(12), pady=(S(8), 0))
            tk.Label(top, text=br["label"], font=F["label"], bg=C["tile"], fg=C["text"]).pack(side="left")
            if info["default"] == br["key"]:
                tk.Label(top, text="WINDOWS DEFAULT", font=F["tiny"], bg=C["accent_soft"], fg=C["accent"],
                         padx=S(6), pady=S(1)).pack(side="left", padx=(S(8), 0))
            tk.Label(top, text="installed" if br["installed"] else "not installed", font=F["small"],
                     bg=C["tile"], fg=C["ok_text"] if br["installed"] else C["faint"]).pack(side="right")
            if br["installed"]:
                if br["profiles"]:
                    p = br["profiles"][0]
                    used = {True: "has used G-MES", False: "no G-MES use seen",
                            None: "G-MES use unknown"}[p["gmes"]]
                    more = f"  (+{len(br['profiles']) - 1} more)" if len(br["profiles"]) > 1 else ""
                    text = f"Profile to copy: '{p['name']}'  ·  {used}{more}"
                else:
                    text = "No signed-in profile found - an empty one would be used"
            else:
                text = "-"
            tk.Label(cell, text=text, font=F["small"], bg=C["tile"], fg=C["muted"], anchor="w",
                     justify="left").pack(fill="x", padx=S(12), pady=(S(2), S(8)))
        state = info.get("state") or {}
        done = bool(state.get("completed") and info.get("same_machine"))
        if info.get("error"):
            self.browser_banner.set(f"Could not read the browsers: {info['error']}", "err")
        else:
            self.browser_banner.set(setup.setup_sentence(info), "ok" if done else "info")
        self.lbl_profile.configure(text=f"Automation profile folder: {info.get('profile_dir') or '-'}")
        self._ready("browser", "ok" if installed else "err",
                    ", ".join(x["label"].split()[-1] for x in installed) + " found" if installed
                    else "no Chrome or Edge found")
        if done:
            used = state.get("browser")
            label = {"chrome": "Chrome", "edge": "Edge"}.get(used, used)
            self._ready("copy", "ok", f"ready ({label}, {state.get('strategy')})")
        else:
            nxt = info.get("next_copy")
            self._ready("copy", "info", f"made on first Connect from {nxt['label'].split()[-1]} "
                                        f"'{nxt['profile']}'" if nxt else "empty profile on first Connect")

    def _toggle_pw(self):
        showing = self.ent_pw1.cget("show") == ""
        for e in (self.ent_pw1, self.ent_pw2):
            e.configure(show="•" if showing else "")
        self.btn_show.set_text("Show" if showing else "Hide")

    def _on_save_login(self):
        user, pw1, pw2 = self.v_user.get(), self.v_pw1.get(), self.v_pw2.get()
        problems = setup.check_new_login(user, pw1, pw2)
        if problems:
            ui.tell(self, "Check the login", "\n".join(problems), icon="warn")
            return
        if self.login_user and not ui.ask(
                self, "Replace the saved login?",
                f"A login is already saved on this PC for Knox ID '{self.login_user}'. "
                f"Replace it with '{user.strip()}'?", yes="Replace", icon="warn"):
            return
        try:
            saved = setup.save_login(user, pw1, pw2)
        except (ValueError, OSError) as e:
            ui.tell(self, "The login was not saved", str(e), icon="err")
            return
        self.v_pw1.set("")
        self.v_pw2.set("")
        self._log(f"Login saved for Knox ID {saved} (encrypted for this Windows account).", "ok")
        self.refresh_account()
        ui.tell(self, "Login saved", f"The login for '{saved}' is saved on this PC.\n"
                                     "Press 'Test sign-in' to check it once.", icon="ok")

    def _on_test_signin(self):
        if not self._need_login():
            return
        if self.state not in ("idle", "connected", "loaded"):
            return
        self._start_connect(load_after=False)

    def _on_apply_browser(self):
        choice = self.v_browser.get()
        if self.state in ("connecting", "loading", "running"):
            ui.tell(self, "Busy", "Change the browser when nothing is running.", icon="warn")
            return
        if self.runner is not None:
            self.runner.close()
            self.runner = None
            try:
                cdp_common.stop_if_started_here(False)
            except Exception:                                # noqa: BLE001
                pass
            self.loaded_signature = None
            self._set_state("idle")
        try:
            plan = setup.apply_browser_choice(choice)
        except Exception as e:                               # noqa: BLE001
            ui.tell(self, "Browser not changed", str(e), icon="err")
            return
        self.browser_choice = choice
        self._save_settings()
        separate = plan.get("GMES_PROFILE_DIR")
        self._log(f"Browser: {setup.CHOICE_LABELS[choice]}"
                  + (" - a separate automation profile is used for it (the existing one is kept)."
                     if separate else "."), "ok")
        self.refresh_account()

    def _need_login(self):
        if setup.saved_login()[0]:
            return True
        self.show_tab("account")
        ui.tell(self, "Add the G-MES login first",
                "No login is saved on this PC. Enter the Knox / G-MES user ID and password here, "
                "press Save login, then connect.", icon="warn")
        return False

    # ---- form helpers ------------------------------------------------------
    def _period_changed(self, initial=False):
        monthly = self.v_mode.get() == "Monthly"
        self.seg_which.set_labels({"current": "This month" if monthly else "Today",
                                   "previous": "Last month" if monthly else "Yesterday"})
        custom = self.v_which.get() == "custom"
        self.ent_custom.configure(state="normal" if custom else "disabled")
        self.lbl_custom_hint.configure(text=("month, e.g. 2026-09" if monthly else "day, e.g. 2026-09-29")
                                       if custom else "type a period after 'Choose...'")
        if custom and not initial and not self.v_custom.get():
            self.ent_custom.focus_set()
        self._show_resolved()
        if not initial:
            self._filters_changed()

    def _period_value(self):
        which = self.v_which.get()
        if which == "current":
            return ""
        if which == "previous":
            return "previous"
        return re.sub(r"\D", "", self.v_custom.get())

    def _show_resolved(self):
        mode = self.v_mode.get()
        value = sr.resolve_period(mode, self._period_value())
        problems = sr.validate_settings(sr.Settings(period_mode=mode, period=self._period_value()))
        bad = [p for p in problems if p.startswith("Period")]
        if bad:
            self.lbl_period.configure(text="⚠  " + bad[0], fg=C["err"])
        else:
            follows = self.v_which.get() != "custom"
            self.lbl_period.configure(
                text=f"G-MES gets  {pretty_period(mode, value)}"
                     + ("   ·   follows the calendar" if follows else ""), fg=C["accent"])

    def _quick_count(self, n):
        self.v_all.set(False)
        self.v_count.set(str(n))
        self._rows_changed()

    def _rows_changed(self):
        self.spin_count.configure(state="disabled" if self.v_all.get() else "normal")
        if not hasattr(self, "lbl_rows"):
            return
        r = self.runner
        if not (r and r.rows and self.state in ("loaded", "running")):
            self.lbl_rows.configure(text="Load the rows to see exactly which ones will be exported.",
                                    fg=C["muted"])
            return
        try:
            start = int(self.v_start.get() or 1)
            count = 0 if self.v_all.get() else int(self.v_count.get() or 0)
        except ValueError:
            self.lbl_rows.configure(text="Start row and number of rows must be whole numbers.", fg=C["err"])
            return
        if start > len(r.rows):
            self.lbl_rows.configure(text=f"Row {start} does not exist - the list has {len(r.rows)} rows.",
                                    fg=C["err"])
            self.tiles["todo"].set("0")
            return
        picked, other = sr.select_rows(r.rows, r.s.status_column, r.s.link_value, start, count)
        if picked:
            text = (f"Will export {len(picked):,} file(s): rows {picked[0] + 1:,} - {picked[-1] + 1:,}"
                    + (f"  ·  {other} row(s) in between are not '{r.s.link_value}' and are left alone"
                       if other else "") + f".  About {fmt_eta(len(picked) * SECONDS_PER_ROW)}.")
            self.lbl_rows.configure(text=text, fg=C["text"])
        else:
            self.lbl_rows.configure(text="No row from there on can be exported.", fg=C["err"])
        self.tiles["todo"].set(f"{len(picked):,}")

    def _browse(self):
        folder = filedialog.askdirectory(title="Save the Excel files in", parent=self)
        if folder:
            self.v_out.set(os.path.normpath(folder))

    def _pattern(self):
        text = self.v_pattern.get().strip()
        return next((p for p, label in NAME_PRESETS if label == text), text)

    def _collect(self):
        """Settings from the form, or raise ValueError with what to fix."""
        def num(var, name, kind=int, empty=0):
            text = str(var.get()).strip()
            if not text:
                return empty
            try:
                return kind(text)
            except ValueError:
                raise ValueError(f"{name} must be a number.") from None
        filters = []
        if self.v_model.get().strip():
            filters.append(f"Model={self.v_model.get().strip()}")
        if self.v_sn.get().strip():
            filters.append(f"SN No.={self.v_sn.get().strip()}")
        filters += [f.strip() for f in self.v_more_filters.get().split(";") if f.strip()]
        grids = [name for name, var in self.grid_vars.items() if var.get()]
        grids += [g.strip() for g in self.v_more_grids.get().split(",") if g.strip()]
        s = sr.Settings(
            division=self.v_div.get().strip(), period_mode=self.v_mode.get(),
            period=self._period_value(), extra_filters=filters,
            result_grid=self.v_grid.get().strip() or "grdMain",
            link_column=self.v_linkcol.get().strip() or "Insp. Result",
            link_value=self.v_linkval.get().strip(),
            dialog_grids=grids, single_file=bool(self.v_single.get()),
            name_pattern=self._pattern(), skip_existing=bool(self.v_skip.get()),
            start_row=num(self.v_start, "Start row", empty=1),
            count=0 if self.v_all.get() else num(self.v_count, "Number of rows"),
            out_dir=self.v_out.get().strip(), on_error=self.v_onerr.get(),
            retries=num(self.v_retries, "Retries", empty=1),
            pause_between=num(self.v_pause, "Pause", float))
        if self.v_which.get() == "custom" and not s.period:
            raise ValueError("Type the period after 'Choose...', or pick This month / Last month.")
        if not self.v_all.get() and s.count == 0:
            raise ValueError("How many rows: type a number, or tick 'All remaining rows'.")
        if s.retries < 0 or s.pause_between < 0:
            raise ValueError("Retries and pause cannot be negative.")
        problems = sr.validate_settings(s)
        if problems:
            raise ValueError("\n".join(problems))
        return s

    @staticmethod
    def _signature(s):
        return (s.division, s.period_mode, sr.resolve_period(s.period_mode, s.period),
                tuple(s.extra_filters), s.result_grid, s.link_value)

    def _save_settings(self, s=None):
        try:
            s = s or self._collect()
        except ValueError:
            return
        data = asdict(s)
        data["browser"] = self.browser_choice
        data["settings_version"] = 2
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except OSError:
            pass

    def _filters_changed(self):
        if hasattr(self, "lbl_period"):
            self._show_resolved()
        if self.state == "loaded" and self.loaded_signature is not None:
            try:
                same = self._signature(self._collect()) == self.loaded_signature
            except ValueError:
                same = False
            if not same:
                self.loaded_signature = None
                self._set_state("connected")
                self._headline("Filters changed", "Press 'Connect & load rows' again to load "
                                                  "the list for the new filters.")

    # ---- log -------------------------------------------------------------
    def _log(self, text, tag=None):
        text = str(text).rstrip()
        if not text:
            return
        tag = tag or classify(text)
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", stamp + "  ", "time")
        self.log_text.insert("end", text + "\n", tag)
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > 4000:
            self.log_text.delete("1.0", f"{lines - 3000}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        try:
            os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {text}\n")
        except OSError:
            pass

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _open(self, path):
        try:
            os.startfile(path)                               # noqa: S606 - the person's own files
        except OSError as e:
            ui.tell(self, "Cannot open", f"{path}\n\n{e}", icon="warn")

    def _open_out(self):
        path = ((self.runner.out_dir if self.runner and self.runner.out_dir else "")
                or self.v_out.get().strip() or os.path.join(samir_env.data_dir(), "output"))
        os.makedirs(path, exist_ok=True)
        self._open(path)

    def _open_results(self):
        csv_path = (self.last_summary or {}).get("csv")
        if csv_path and os.path.isfile(csv_path):
            self._open(csv_path)
        else:
            ui.tell(self, "No result list yet", "The result list (results_<time>.csv) is written by a run. "
                                                "Start one first.", icon="info")

    def _open_log(self):
        if os.path.isfile(LOG_FILE):
            self._open(LOG_FILE)

    def destroy(self):
        """Cancel pending timers first, or Tk prints 'invalid command name' noise."""
        try:
            for after_id in self.tk.splitlist(self.tk.call("after", "info")):
                try:
                    self.after_cancel(after_id)
                except tk.TclError:
                    pass
        except tk.TclError:
            pass
        super().destroy()

    # ---- messages from the worker threads ------------------------------------
    def _post(self, kind, **kw):
        self.q.put((kind, kw))

    def _pump(self):
        """Hand the worker threads' messages to the window. One bad message must
        never stop the pump: a dead pump freezes the whole window while the work
        itself goes on unseen (it happened once, live, on the first sign-in line)."""
        try:
            for _ in range(400):
                try:
                    kind, kw = self.q.get_nowait()
                except queue.Empty:
                    break
                try:
                    getattr(self, "_on_" + kind + "_msg")(**kw)
                except Exception as e:                       # noqa: BLE001
                    self._log(f"(display problem with a '{kind}' message: {type(e).__name__}: {e})",
                              "muted")
        finally:
            self.after(80, self._pump)

    def _on_log_msg(self, text, tag=None):
        self._log(text, tag)

    def _on_engine_line_msg(self, text):
        clean = text.strip()
        if not clean or set(clean) <= set("=-"):
            return
        m = SIGNED_IN.search(clean)
        if m:
            self.signed_in_as = m.group(1)
            self.lbl_user.configure(text=f"Signed in as {self.signed_in_as}")
        if clean in ("GMES login",) or clean.startswith("Traceback"):
            return
        tag = classify(clean)
        self._log(clean, tag if tag in ("err", "ok", "warn") else "muted")

    # ---- state ------------------------------------------------------------
    def _headline(self, title, sub=""):
        self.lbl_state.configure(text=title)
        self.lbl_state_sub.configure(text=sub)

    def _set_state(self, state):
        self.state = state
        busy = state in ("connecting", "loading", "running")
        self.btn_load.set_enabled(not busy)
        self.btn_load.set_text("Reload rows" if state == "loaded" else "Connect & load rows")
        self.btn_start.set_enabled(state == "loaded")
        self.btn_pause.set_enabled(state == "running")
        if state != "running":
            self.btn_pause.set_text("❚❚  Pause")
        self.btn_stop.set_enabled(busy)
        self.btn_now.set_enabled(busy)
        self.btn_save_login.set_enabled(not busy)
        self.btn_test.set_enabled(state in ("idle", "connected", "loaded"))
        self.btn_apply_browser.set_enabled(not busy)
        self.seg_browser.set_enabled(not busy)
        pill = {"idle": ("idle", "Not connected"), "connecting": ("busy", "Connecting"),
                "connected": ("ready", "Connected"), "loading": ("busy", "Loading rows"),
                "loaded": ("ready", "Rows loaded"), "running": ("run", "Exporting")}[state]
        self.pill.set(*pill)
        if state == "idle":
            self._headline("Ready to connect", "Check the filters on the left, then press "
                                               "'Connect & load rows'. Nothing in G-MES is changed - "
                                               "the tool only reads and downloads.")
        self._rows_changed()

    def _tick(self):
        if self.state == "running" and self.run_started:
            elapsed = int((datetime.now() - self.run_started).total_seconds())
            self._status(f"Running for {fmt_eta(elapsed) if elapsed else '0s'}   ·   files go to "
                         f"{self.runner.out_dir if self.runner else ''}")
        self.after(1000, self._tick)

    # ---- connect & load -----------------------------------------------------
    def _on_load(self):
        if not self._need_login():
            return
        try:
            s = self._collect()
        except ValueError as e:
            ui.tell(self, "Check the form", str(e), icon="warn")
            return
        self._save_settings(s)
        self._start_connect(load_after=True, settings=s)

    def _start_connect(self, load_after, settings=None):
        s = settings or (self.runner.s if self.runner else None)
        if s is None:
            try:
                s = self._collect()
            except ValueError:
                s = sr.Settings()
        reuse = self.runner is not None and self.runner.ws is not None
        if load_after:
            self.loaded_signature = None          # Start stays off until THIS load has finished
        if not reuse:
            if self.runner is not None:
                self.runner.close()
            self.runner = sr.Runner(s, log=lambda m: self._post("log", text=m))
        else:
            self.runner.s = s
            self.runner._stop.clear()
        self._set_state("loading" if (load_after and reuse) else "connecting")
        self._headline("Connecting to G-MES..." if not reuse else "Loading the list...",
                       "The first time on a PC this takes a minute or two (browser copy and sign-in). "
                       "The automation browser opens in its own window - leave it alone while it works.")
        self.worker = threading.Thread(target=self._connect_worker, args=(load_after, reuse), daemon=True)
        self.worker.start()

    def _connect_worker(self, load_after, reuse):
        r = self.runner
        try:
            if not reuse or not r._alive():
                if reuse:
                    r.close()
                r.connect()
                self._post("connected")
            elif not load_after:
                self._post("connected")                       # already connected: say so
            if load_after:
                self._post("loading")
                total, counts = r.load()
                self._post("loaded", total=total, counts=counts)
        except sr.StopRequested:
            self._post_failed(r, "Stopped before the list was loaded.", title="Stopped", icon="warn")
        except (sr.FatalError, ValueError) as e:
            self._post_failed(r, str(e))
        except Exception as e:                               # noqa: BLE001
            self._post("log", text=traceback.format_exc(), tag="muted")
            self._post_failed(r, f"{type(e).__name__}: {e}")

    def _post_failed(self, runner, text, title="Stopped", icon="err"):
        """From a worker thread: the browser check can take seconds when the
        browser hangs, so it is made here and never on the window's thread."""
        alive = runner is not None and runner.ws is not None and runner._alive()
        self._post("failed", text=text, title=title, icon=icon, alive=alive)

    def _on_connected_msg(self):
        still_loaded = bool(self.loaded_signature and self.runner and self.runner.rows)
        self._set_state("loaded" if still_loaded else "connected")
        who = f" as {self.signed_in_as}" if self.signed_in_as else ""
        self._headline(f"Connected{who}", "Signed in to G-MES. Press 'Connect & load rows' to "
                                           "load the list for the filters on the left.")
        self._log(f"Connected to G-MES{who}.", "ok")
        self.refresh_account()

    def _on_loading_msg(self):
        self._set_state("loading")
        self._headline("Loading the list...", "Opening Detail Inspection, applying the filters and "
                                              "pressing Inquiry.")

    def _on_loaded_msg(self, total, counts):
        r = self.runner
        self.loaded_signature = self._signature(r.s)
        can = sr.count_link_rows(r.rows, r.s.status_column, r.s.link_value)
        self.tiles["found"].set(f"{total:,}")
        for key in ("ok", "skipped", "failed"):
            self.tiles[key].set("0")
        self.tiles["eta"].set("-")
        self.bar.configure(value=0, style="Run.Horizontal.TProgressbar")
        self.lbl_prog.configure(text="")
        self.lbl_pct.configure(text="")
        self._set_state("loaded")
        detail = "   ·   ".join(f"{k or '(blank)'} {v:,}" for k, v in counts.items()) if counts else ""
        self._headline(f"{total:,} rows loaded  -  {can:,} can be exported",
                       f"{r.s.division}  ·  {r.s.period_mode} {pretty_period(r.s.period_mode, r.period)}"
                       + (f"  ·  {detail}" if detail else "")
                       + ". Choose the rows on the left, then press Start export.")
        self._status(f"Loaded {total:,} rows at {datetime.now():%H:%M}   ·   files and logs: "
                     f"{samir_env.data_dir()}")
        if total == 0 or can == 0:
            self._log("Nothing in this list can be exported.", "warn")

    def _on_failed_msg(self, text, title="Stopped", icon="err", alive=False):
        self._log(f"PROBLEM: {text}", "err")
        if not alive and self.runner is not None:
            self.runner.close()
            self.runner = None
        self.loaded_signature = None
        self._set_state("connected" if alive else "idle")
        self._headline("Something needs your attention", text.split("\n")[0])
        ui.tell(self, title, text, icon=icon)

    # ---- run --------------------------------------------------------------
    def _on_start(self):
        try:
            s = self._collect()
        except ValueError as e:
            ui.tell(self, "Check the form", str(e), icon="warn")
            return
        if self._signature(s) != self.loaded_signature:
            self._set_state("connected")
            ui.tell(self, "Load the list again", "The filters changed after the list was loaded. "
                                                 "Press 'Connect & load rows' first.", icon="warn")
            return
        r = self.runner
        picked, other = sr.select_rows(r.rows, s.status_column, s.link_value, s.start_row, s.count)
        if not picked:
            ui.tell(self, "Nothing to export", "No row from the chosen start row can be exported.",
                    icon="warn")
            return
        folder = s.out_dir or os.path.join(samir_env.data_dir(), "output",
                                           f"{s.screen_code}_{r.period}")
        grids = ", ".join(s.dialog_grids)
        details = [("Rows", f"{picked[0] + 1:,} - {picked[-1] + 1:,}   ({len(picked):,} files)"),
                   ("Left alone", f"{other} row(s) that are not '{s.link_value}'") if other else None,
                   ("Excel grids", grids + ("   (single file)" if s.single_file else "")),
                   ("Folder", folder),
                   ("Existing files", "skipped (resume)" if s.skip_existing else "kept - new ones get -2, -3"),
                   ("If a row fails", "stop the run" if s.on_error == "stop" else "skip it and go on"),
                   ("Estimated time", fmt_eta(len(picked) * SECONDS_PER_ROW))]
        if not ui.ask(self, f"Export {len(picked):,} file(s)?",
                      "The tool double-clicks each row's Insp. Result (PASS, In progress, Outgoing Revoke...), saves its Excel file and moves on. "
                      "Press Stop (or Esc) at any moment.",
                      yes="▶  Start", kind="success", icon="ask", details=[d for d in details if d]):
            return
        r.s = s
        r._stop.clear()
        r.resume()
        self._save_settings(s)
        self.bar.configure(value=0, maximum=len(picked), style="Run.Horizontal.TProgressbar")
        for key in ("ok", "skipped", "failed"):
            self.tiles[key].set("0")
        self.tiles["todo"].set(f"{len(picked):,}")
        self.tiles["eta"].set(fmt_eta(len(picked) * SECONDS_PER_ROW))
        self.lbl_prog.configure(text="Starting...")
        self.lbl_pct.configure(text="0 %")
        self.run_started = datetime.now()
        self._set_state("running")
        self._headline(f"Exporting {len(picked):,} file(s)...",
                       "You can keep working in other windows. Do not click inside the automation "
                       "browser while it runs.")
        r.progress = lambda **kw: self._post("progress", **kw)
        self.worker = threading.Thread(target=self._run_worker, daemon=True)
        self.worker.start()

    def _run_worker(self):
        try:
            summary = self.runner.run()
            summary["alive"] = self.runner._alive()
            self._post("done", summary=summary)
        except Exception as e:                               # noqa: BLE001
            self._post("log", text=traceback.format_exc(), tag="muted")
            self._post_failed(self.runner, f"{type(e).__name__}: {e}")

    def _on_progress_msg(self, done, total, ok, skipped, failed, row, eta):
        self.bar.configure(maximum=max(1, total), value=done)
        self.tiles["ok"].set(f"{ok:,}", fg=C["ok"] if ok else None)
        self.tiles["skipped"].set(f"{skipped:,}", fg=C["warn"] if skipped else None)
        self.tiles["failed"].set(f"{failed:,}", fg=C["err"] if failed else None)
        self.tiles["eta"].set(fmt_eta(eta) if done < total else "-")
        self.lbl_prog.configure(text=f"{done:,} of {total:,}   ·   last: row {row:,}")
        self.lbl_pct.configure(text=f"{int(done * 100 / max(1, total))} %")

    def _on_done_msg(self, summary):
        self.last_summary = summary
        text = (f"{summary['ok']:,} exported, {summary['skipped']:,} skipped, {summary['failed']:,} "
                f"failed of {summary['planned']:,}")
        if summary["fatal"]:
            title, tone = "Stopped - " + summary["fatal"].split("\n")[0], "err"
        elif summary["stopped"]:
            title, tone = "Stopped by you", "warn"
        elif summary["failed"]:
            title, tone = "Finished with failures", "warn"
        else:
            title, tone = "Finished", "ok"
        self._log(f"{title}: {text}.", tone)
        if summary.get("csv"):
            self._log(f"Result list: {summary['csv']}", "muted")
        if not summary["fatal"] and not summary["stopped"]:
            self.bar.configure(style="Done.Horizontal.TProgressbar")
        self.tiles["eta"].set("-")
        alive = summary.get("alive")
        if not alive and self.runner is not None:
            self.runner.close()
            self.runner = None
            self.loaded_signature = None
        self._set_state("loaded" if alive else "idle")
        self._headline(title if len(title) < 90 else title[:87] + "...",
                       f"{text}.   Files: {summary.get('out_dir') or '-'}")
        elapsed = (datetime.now() - self.run_started).total_seconds() if self.run_started else 0
        self._status(f"Last run: {text} in {fmt_eta(elapsed)}   ·   {summary.get('out_dir') or ''}")
        if summary["fatal"]:
            ui.tell(self, "The run stopped", summary["fatal"], icon="err")

    def _on_pause(self):
        if not self.runner or self.state != "running":
            return
        if self.runner._pause.is_set():
            self.runner.resume()
            self.btn_pause.set_text("❚❚  Pause")
            self.pill.set("run", "Exporting")
            self._log("Resumed.", "info")
        else:
            self.runner.pause()
            self.btn_pause.set_text("▶  Resume")
            self.pill.set("busy", "Paused")
            self._log("Paused - the file in progress finishes first.", "warn")

    def _on_stop(self):
        if self.runner and self.state in ("running", "connecting", "loading"):
            self.runner.request_stop()
            self.runner.resume()
            self.btn_stop.set_enabled(False)
            self.pill.set("stop", "Stopping")
            self._log("STOP pressed - stopping after the click in progress (a second or two)...", "warn")

    def _on_stop_now(self):
        if not ui.ask(self, "Force stop?", "This stops the run AND closes the automation browser at "
                                           "once. The next Connect opens it again.",
                      yes="Force stop", kind="dark", icon="warn"):
            return
        self._log("FORCE STOP - closing the automation browser.", "err")
        if self.runner:
            self.runner.request_stop()
            self.runner.resume()
        threading.Thread(target=self._hard_close, daemon=True).start()

    @staticmethod
    def _hard_close():
        try:
            cdp_common.close_browser()
        except Exception:                                    # noqa: BLE001
            pass

    def _on_close(self):
        if self.state in ("connecting", "loading", "running"):
            if not ui.ask(self, "Quit while it works?", "A run is active. Stop it and quit?",
                          yes="Stop and quit", kind="danger", icon="warn"):
                return
            if self.runner:
                self.runner.request_stop()
                self.runner.resume()
            if self.worker:
                self.worker.join(timeout=10)
        self._save_settings()
        if self.runner:
            self.runner.close()
        try:
            cdp_common.stop_if_started_here(False)          # only a browser THIS program opened
        except Exception:                                    # noqa: BLE001
            pass
        sys.stdout, sys.stderr = self.sink.fallback, self.sink.fallback
        self.destroy()


# --------------------------------------------------------------------------
def selftest():
    import sync_engine
    print(f"{APP_NAME} {VERSION} self-test")
    print("  data folder :", samir_env.data_dir())
    print("  engine ok   :", sr.core.__name__, "/", cdp_common.__name__)
    user, problem = setup.saved_login()
    print("  login       :", f"saved ({user})" if user else (problem or "not saved yet (Account tab)"))
    info = setup.describe_browsers()
    found = [b["label"] for b in info["browsers"] if b["installed"]]
    print("  browsers    :", ", ".join(found) or "none found", "| default:", info["default"])
    print("  browser copy:", setup.setup_sentence(info))
    if not samir_env.FROZEN:
        problems = sync_engine.check()
        print("  engine copy :", "identical to the root modules" if not problems else problems)
    try:
        import websocket                                     # noqa: F401
        print("  websocket   : ok")
    except ImportError:
        print("  websocket   : MISSING")
        return 1
    return 0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    if argv and argv[0] == "--cli":
        import samir_cli
        return samir_cli.main(argv[1:])
    App().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
