"""Schedules, Row export, History and Account & Browser."""
import json
import os
import re
import threading
import tkinter as tk
from dataclasses import asdict
from datetime import datetime
from tkinter import filedialog, ttk

import account
import app_env
import app_settings
import rowexport as rx
import service
import ui_kit as ui
from page_base import Page
from pages_main import grid_field
from ui_kit import C, F, S

load_settings = app_settings.load
save_settings = app_settings.save


def fmt_eta(seconds):
    if not seconds or seconds <= 0:
        return "-"
    h, rest = divmod(int(seconds), 3600)
    m, s = divmod(rest, 60)
    return f"{h}h {m:02d}m" if h else (f"{m}m {s:02d}s" if m else f"{s}s")


# ==========================================================================
# Schedules
# ==========================================================================
class SchedulesPage(Page):
    key = "schedules"
    title = "Schedules"
    subtitle = ("A saved batch, run by Windows Task Scheduler at a set time. It runs only while "
                "this Windows user is signed in (the login is encrypted for this account), and a PC "
                "that was asleep runs it when it wakes.")

    def build(self, body):
        split = ui.Split(body, "schedules", first=0.6)
        split.pack(fill="both", expand=True)
        left = ui.Card(split, "This app's schedules", pad=14)
        split.add(left, minsize=420)
        b = left.body
        self.table = ui.Table(b, (("batch", "Batch", 140, "w"), ("state", "State", 90, "w"),
                                  ("next", "Next run", 150, "w"), ("last", "Last run", 150, "w"),
                                  ("result", "Last result", 240, "w")), height=5, stretch="result")
        self.table.pack(fill="both", expand=True)
        self.table.tree.bind("<<TreeviewSelect>>", lambda _e: self._notes())
        # Below the table, but given their room first: a short window or a large text size
        # shrinks the table, never cuts off the buttons.
        row = tk.Frame(b, bg=C["card"])
        row.pack(fill="x", side="bottom", pady=(S(10), 0), before=self.table)
        self.lbl_notes = ui.note(b, "", wrap=640, fit=True)
        self.lbl_notes.pack(fill="x", side="bottom", pady=(S(8), 0), before=self.table)
        for text, cmd, kind in (("Refresh", self.refresh, "secondary"), ("Run now", self.run_now, "primary"),
                                ("Pause", lambda: self.enable(False), "secondary"),
                                ("Resume", lambda: self.enable(True), "secondary"),
                                ("Delete", self.delete, "danger")):
            ui.FlatButton(row, text, command=cmd, kind=kind, font=F["label"], padx=12, pady=6).pack(
                side="left", padx=(0, S(8)))

        holder = ui.ScrollFrame(split, C["bg"])             # a short window scrolls the form
        split.add(holder, minsize=340)
        right = ui.Card(holder.inner, "New schedule", pad=16)
        right.pack(fill="x")
        r = right.body
        r.grid_columnconfigure(0, weight=1)
        self.v_batch = tk.StringVar()
        self.cmb = ttk.Combobox(r, textvariable=self.v_batch, state="readonly")
        grid_field(r, 0, "Saved batch", self.cmb, hint="make one on Run & Batch")
        self.v_time = tk.StringVar(value="06:30")
        grid_field(r, 2, "Time", ttk.Entry(r, textvariable=self.v_time, width=10), hint="HH:MM, 24 hour")
        self.v_kind = tk.StringVar(value="daily")
        ui.field_label(r, "Days").grid(row=4, column=0, sticky="w")
        ui.Segmented(r, (("daily", "Every day"), ("weekdays", "Mon - Fri"), ("days", "Chosen days")),
                     self.v_kind, padx=11).grid(row=5, column=0, sticky="w", pady=(S(4), S(6)))
        days = tk.Frame(r, bg=C["card"])
        days.grid(row=6, column=0, sticky="w", pady=(0, S(10)))
        self.day_vars = {}
        for i, d in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun")):
            v = tk.BooleanVar(value=d in ("mon", "tue", "wed", "thu", "fri"))
            ttk.Checkbutton(days, text=d.title(), variable=v).grid(row=i // 4, column=i % 4, sticky="w",
                                                                    padx=(0, S(10)))
            self.day_vars[d] = v
        ui.FlatButton(r, "Create schedule", command=self.create, kind="success", padx=16,
                      pady=8).grid(row=7, column=0, sticky="w")
        ui.note(r, "The task runs this app without a window: it signs in with the saved login, "
                   "runs the batch with the batch's own date rule, and writes the report to "
                   "History. Prove a new schedule once with 'Run now'.", wrap=320, fit=True).grid(
            row=8, column=0, sticky="we", pady=(S(12), 0))
        self.tasks = []

    def on_show(self, **_kw):
        self.cmb.configure(values=sorted(service.batches()))
        self.refresh()

    def refresh(self):
        def work(stop, log):
            return service.schedule_list()

        def done(tasks):
            self.tasks = tasks
            rows = []
            for t in tasks:
                tag = "err" if t.get("last_ok") is False or t["notes"] else (
                    "ok" if t.get("last_ok") else "")
                rows.append(({"batch": t["batch"], "state": t["state"], "next": t["next_run"] or "-",
                              "last": t["last_run"] or "-",
                              "result": t["last_text"] or "-"}, tag))
            self.table.fill(rows, iid_key="batch")
            # The note used to keep saying "No schedule yet" after the first one was made.
            self.lbl_notes.configure(text="No schedule yet. Save a batch on Run & Batch, then create "
                                          "its schedule on the right." if not tasks else
                                     "Choose a schedule to see what was found about it.")
            self._notes()
        self.app.background(lambda: work(None, None), done)

    def _notes(self):
        sel = self.table.selected()
        t = next((t for t in self.tasks if t["batch"] in sel), None)
        if t:
            self.lbl_notes.configure(text=("  ·  ".join(t["notes"]) or "No problems seen.")
                                     + f"   Log: data\\logs\\scheduled_{t['batch']}.log")

    def _selected(self):
        sel = self.table.selected()
        return sel[0] if sel else None

    def create(self):
        batch = self.v_batch.get()
        if not batch:
            ui.tell(self.app, "Choose a batch", "Save a batch on Run & Batch first.", icon="info")
            return
        kind = self.v_kind.get()
        try:
            when = service.gmes_schedule.parse_when(
                self.v_time.get().strip(), daily=kind == "daily", weekdays=kind == "weekdays",
                days=[d for d, v in self.day_vars.items() if v.get()] if kind == "days" else None)
        except (ValueError, service.gmes_schedule.ScheduleError) as e:
            ui.tell(self.app, "Check the time", str(e), icon="warn")
            return
        if not ui.ask(self.app, f"Schedule '{batch}'?",
                      f"Windows Task Scheduler will run it {service.gmes_schedule.describe_when(when)}.",
                      yes="Create", kind="success"):
            return

        def work(stop, log):
            return service.schedule_create(batch, when)

        def done(name):
            self.app.log(f"Schedule created: {name}.", "ok")
            self.refresh()
        self.app.run_task("Create schedule", work, done, needs_session=False)

    def run_now(self):
        b = self._selected()
        if b:
            self.app.run_task("Start schedule", lambda s, l: service.gmes_schedule.run_now(b),
                              lambda _r: (self.app.log(f"Started {b} - it runs in the background; "
                                                       "History shows the report.", "ok"), self.refresh()),
                              needs_session=False)

    def enable(self, flag):
        b = self._selected()
        if b:
            self.app.run_task("Change schedule", lambda s, l: service.gmes_schedule.set_enabled(b, flag),
                              lambda _r: self.refresh(), needs_session=False)

    def delete(self):
        b = self._selected()
        if b and ui.ask(self.app, f"Delete the schedule '{b}'?", "The batch itself is kept.",
                        yes="Delete", kind="danger", icon="warn"):
            self.app.run_task("Delete schedule", lambda s, l: service.gmes_schedule.delete(b),
                              lambda _r: self.refresh(), needs_session=False)


# ==========================================================================
# Row export
# ==========================================================================
class RowExportPage(Page):
    key = "rowexport"
    title = "Row export"
    subtitle = ("One Excel file per row of a list: double-click the row's link (e.g. Insp. Result on "
                "Q321KUM00 Detail Inspection) -> detail popup -> Excel -> only the chosen grids.")

    def build(self, body):
        saved = rx.Settings.from_dict(load_settings().get("rowexport", {}))
        self.s0 = saved
        split = ui.Split(body, "rowexport", first=0.42)
        split.pack(fill="both", expand=True)
        left = ui.ScrollFrame(split, C["bg"])
        split.add(left, minsize=400)
        col = left.inner
        right = tk.Frame(split, bg=C["bg"])
        split.add(right, minsize=420)

        f = ui.Card(col, "List", step=1)
        f.pack(fill="x", pady=(0, S(12)))
        b = f.body
        b.grid_columnconfigure(0, weight=1)
        b.grid_columnconfigure(1, weight=1)
        self.v_screen = tk.StringVar(value=saved.screen_code)
        grid_field(b, 0, "Screen", ttk.Entry(b, textvariable=self.v_screen), col=0)
        self.v_div = tk.StringVar(value=saved.division)
        grid_field(b, 0, "Organization", ttk.Combobox(b, textvariable=self.v_div, values=(
            "MAIN Part", "LCM Part", "SMD Part", "PBA Part", "OCM", "MKD Part", "KD Part", "VD")), col=1)
        self.v_mode = tk.StringVar(value=saved.period_mode)
        ui.field_label(b, "Period").grid(row=2, column=0, sticky="w")
        ui.Segmented(b, (("Monthly", "Monthly"), ("Daily", "Daily")), self.v_mode, padx=12).grid(
            row=3, column=0, sticky="w", pady=(S(4), S(6)))
        self.v_period = tk.StringVar(value=saved.period)
        grid_field(b, 2, "Which", ttk.Combobox(b, textvariable=self.v_period,
                                               values=("", "previous")), col=1,
                   hint="empty = now; previous; or 202609")
        filters = dict(x.split("=", 1) for x in saved.extra_filters if "=" in x)
        self.v_model = tk.StringVar(value=filters.get("Model", ""))
        grid_field(b, 4, "Model", ttk.Entry(b, textvariable=self.v_model), hint="optional", col=0, pad=2)
        self.v_status = tk.StringVar(value=saved.link_value)
        grid_field(b, 4, "Only rows showing", ttk.Entry(b, textvariable=self.v_status),
                   hint="empty = every status", col=1, pad=2)

        r = ui.Card(col, "Rows and files", step=2)
        r.pack(fill="x", pady=(0, S(4)))
        b = r.body
        b.grid_columnconfigure(0, weight=1)
        b.grid_columnconfigure(1, weight=1)
        self.v_start = tk.StringVar(value=str(saved.start_row))
        grid_field(b, 0, "Start at row No.", ttk.Spinbox(b, from_=1, to=999999, textvariable=self.v_start), col=0)
        self.v_count = tk.StringVar(value=str(saved.count))
        grid_field(b, 0, "How many", ttk.Spinbox(b, from_=0, to=999999, textvariable=self.v_count),
                   hint="0 = all", col=1)
        self.v_grids = tk.StringVar(value=", ".join(saved.dialog_grids))
        grid_field(b, 2, "Grids to tick in 'Save to Excel'", ttk.Entry(b, textvariable=self.v_grids), span=2)
        self.v_out = tk.StringVar(value=saved.out_dir)
        grid_field(b, 4, "Save the files in", ttk.Entry(b, textvariable=self.v_out),
                   hint="empty = data\\output", span=2)
        self.v_skip = tk.BooleanVar(value=saved.skip_existing)
        ttk.Checkbutton(b, text="Skip rows whose file already exists (resume)",
                        variable=self.v_skip).grid(row=6, column=0, columnspan=2, sticky="w")
        self.v_onerr = tk.StringVar(value=saved.on_error)
        ui.Segmented(b, (("stop", "Stop at a failed row"), ("skip", "Skip it and go on")), self.v_onerr,
                     padx=10).grid(row=7, column=0, columnspan=2, sticky="w", pady=(S(8), 0))

        run = ui.Card(right, "Run", pad=16)
        run.pack(fill="x", pady=(0, S(12)))
        b = run.body
        self.lbl_head = tk.Label(b, text="Load the list first", font=F["status"], bg=C["card"],
                                 fg=C["text"], anchor="w")
        self.lbl_head.pack(fill="x")
        self.lbl_sub = ui.fit_wrap(tk.Label(b, text="", font=F["small"], bg=C["card"], fg=C["muted"],
                                            anchor="w", justify="left", wraplength=S(620)), b)
        self.lbl_sub.pack(fill="x")
        btns = tk.Frame(b, bg=C["card"])
        btns.pack(fill="x", pady=(S(12), S(4)))
        self.btn_load = ui.FlatButton(btns, "Load the list", command=self.load, kind="primary",
                                      font=F["button_lg"], padx=18, pady=9)
        self.btn_load.pack(side="left")
        self.btn_start = ui.FlatButton(btns, "▶  Start export", command=self.start, kind="success",
                                       font=F["button_lg"], padx=20, pady=9)
        self.btn_start.pack(side="left", padx=(S(10), 0))
        self.btn_pause = ui.FlatButton(btns, "❚❚  Pause", command=self.pause, kind="secondary",
                                       font=F["button_lg"], padx=16, pady=9)
        self.btn_pause.pack(side="left", padx=(S(10), 0))
        tiles = tk.Frame(b, bg=C["card"])
        tiles.pack(fill="x", pady=(S(12), 0))
        self.tiles = {}
        for i, (key, cap, color) in enumerate((("found", "In the list", C["faint"]),
                                               ("todo", "To export", C["accent"]),
                                               ("ok", "Exported", C["ok"]), ("skipped", "Skipped", C["warn"]),
                                               ("failed", "Failed", C["err"]), ("eta", "Time left", C["header2"]))):
            t = ui.StatTile(tiles, cap, "-", color)
            t.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else S(8), 0))
            tiles.grid_columnconfigure(i, weight=1, uniform="t")
            self.tiles[key] = t
        self.bar = ttk.Progressbar(b, mode="determinate", style="Run.Horizontal.TProgressbar")
        self.bar.pack(fill="x", pady=(S(12), 0))
        self.lbl_prog = tk.Label(b, text="", font=F["small"], bg=C["card"], fg=C["muted"], anchor="w")
        self.lbl_prog.pack(fill="x", pady=(S(4), 0))
        self.runner = None
        self.loaded = False
        self._state()

    def _settings(self):
        filters = [f"Model={self.v_model.get().strip()}"] if self.v_model.get().strip() else []
        s = rx.Settings.from_dict(asdict(self.s0))
        s.screen_code = service.normalise_code(self.v_screen.get()) or "Q321KUM00"
        s.division = self.v_div.get().strip()
        s.period_mode = self.v_mode.get()
        s.period = self.v_period.get().strip()
        s.extra_filters = filters
        s.link_value = self.v_status.get().strip()
        s.dialog_grids = [g.strip() for g in self.v_grids.get().split(",") if g.strip()]
        try:
            s.start_row = int(self.v_start.get() or 1)
            s.count = int(self.v_count.get() or 0)
        except ValueError:
            raise ValueError("Start row and How many must be whole numbers.") from None
        s.out_dir = self.v_out.get().strip()
        s.skip_existing = bool(self.v_skip.get())
        s.on_error = self.v_onerr.get()
        problems = rx.validate_settings(s)
        if problems:
            raise ValueError("\n".join(problems))
        save_settings(rowexport=asdict(s))
        return s

    # A theme / text-size change rebuilds the window; a loaded list must survive it.
    def keep(self):
        return {"runner": self.runner, "loaded": self.loaded, "head": self.lbl_head.cget("text"),
                "sub": self.lbl_sub.cget("text"), "prog": self.lbl_prog.cget("text"),
                "tiles": {k: t.value.cget("text") for k, t in self.tiles.items()},
                "bar": (self.bar.cget("value"), self.bar.cget("maximum"))}

    def restore(self, state):
        self.runner, self.loaded = state.get("runner"), bool(state.get("loaded"))
        self.lbl_head.configure(text=state.get("head") or "Load the list first")
        self.lbl_sub.configure(text=state.get("sub") or "")
        self.lbl_prog.configure(text=state.get("prog") or "")
        for k, v in (state.get("tiles") or {}).items():
            if k in self.tiles:
                self.tiles[k].set(v)
        value, maximum = state.get("bar") or (0, 100)
        self.bar.configure(value=value, maximum=maximum)
        self._state()

    def _state(self, running=False):
        busy = self.app.busy
        self.btn_load.set_enabled(not busy)
        self.btn_start.set_enabled(self.loaded and not busy)
        self.btn_pause.set_enabled(running)

    def on_busy(self, busy):
        self._state(running=busy and self.app.task_name.startswith("Row export"))

    def on_stop(self):
        if self.runner:
            self.runner.request_stop()
            self.runner.resume()

    def load(self):
        try:
            s = self._settings()
        except ValueError as e:
            ui.tell(self.app, "Check the form", str(e), icon="warn")
            return
        runner = rx.Runner(s, log=lambda m: self.app._post_log(m))

        def work(stop, log):
            runner.attach(self.app.session.ensure(stop))
            return runner.load()

        def done(result):
            total, counts = result
            self.runner, self.loaded = runner, True
            self.tiles["found"].set(f"{total:,}")
            can = rx.count_link_rows(runner.rows, s.status_column, s.link_value)
            self.lbl_head.configure(text=f"{total:,} rows loaded - {can:,} to export")
            detail = "  ·  ".join(f"{k or '(blank)'} {v:,}" for k, v in counts.items())
            sort = (f"   ⚠ the G-MES list is SORTED by "
                    + ", ".join(f"{k} {v}" for k, v in runner.sorted_by.items())) if runner.sorted_by else ""
            self.lbl_sub.configure(text=f"{s.division} · {s.period_mode} {runner.period} · {detail}{sort}")
            picked, _ = rx.select_rows(runner.rows, s.status_column, s.link_value, s.start_row, s.count)
            self.tiles["todo"].set(f"{len(picked):,}")
            self._state()
        self.app.run_task("Row export: load", work, done)

    def start(self):
        try:
            s = self._settings()
        except ValueError as e:
            ui.tell(self.app, "Check the form", str(e), icon="warn")
            return
        r = self.runner
        if not r or not r.rows:
            return
        picked, other = rx.select_rows(r.rows, s.status_column, s.link_value, s.start_row, s.count)
        if not picked:
            ui.tell(self.app, "Nothing to export", "No row from there on.", icon="warn")
            return
        if not ui.ask(self.app, f"Export {len(picked):,} file(s)?",
                      f"Rows {picked[0] + 1:,} - {picked[-1] + 1:,}. Stop (or Esc) at any moment.",
                      yes="▶  Start", kind="success"):
            return
        r.s = s
        r._stop.clear()
        r.resume()
        self.btn_pause.set_text("❚❚  Pause")       # a run stopped while paused left "Resume" here
        self.bar.configure(value=0, maximum=len(picked))
        for k in ("ok", "skipped", "failed"):
            self.tiles[k].set("0")
        r.progress = lambda **kw: self.app.call_soon(self._progress, kw)

        def work(stop, log):
            r.attach(self.app.session.ensure(stop))
            return r.run()
        self.app.run_task("Row export", work, self._done)

    def _progress(self, kw):
        self.bar.configure(maximum=max(1, kw["total"]), value=kw["done"])
        self.tiles["ok"].set(f"{kw['ok']:,}")
        self.tiles["skipped"].set(f"{kw['skipped']:,}")
        self.tiles["failed"].set(f"{kw['failed']:,}")
        self.tiles["eta"].set(fmt_eta(kw["eta"]))
        self.lbl_prog.configure(text=f"{kw['done']:,} of {kw['total']:,} · last row {kw['row']:,}")

    def _done(self, summary):
        text = f"{summary['ok']:,} exported, {summary['skipped']:,} skipped, {summary['failed']:,} failed"
        self.lbl_head.configure(text=("Stopped - " if summary["stopped"] or summary["fatal"] else "Finished - ")
                                + text)
        if summary.get("next_row") and (summary["stopped"] or summary["fatal"]):
            self.v_start.set(str(summary["next_row"]))
            self.app.log(f"'Start at row No.' is now {summary['next_row']:,} - Start export carries on.", "info")
        if summary["fatal"]:
            ui.tell(self.app, "The run stopped", summary["fatal"], icon="err")

    def pause(self):
        if self.runner:
            if self.runner._pause.is_set():
                self.runner.resume()
                self.btn_pause.set_text("❚❚  Pause")
            else:
                self.runner.pause()
                self.btn_pause.set_text("▶  Resume")


# ==========================================================================
# History
# ==========================================================================
class HistoryPage(Page):
    key = "history"
    title = "History"
    subtitle = "Every run's report - batches, scheduled nights and runs from the Reports page."

    def build(self, body):
        split = ui.Split(body, "history", first=0.4)
        split.pack(fill="both", expand=True)
        left = ui.Card(split, "Runs", pad=12)
        split.add(left, minsize=340)
        self.runs = ui.Table(left.body, (("started", "Started", 150, "w"), ("name", "Batch", 110, "w"),
                                         ("result", "Result", 160, "w")), height=6, stretch="result")
        self.runs.pack(fill="both", expand=True)
        self.runs.tree.bind("<<TreeviewSelect>>", lambda _e: self.show_run())
        row = tk.Frame(left.body, bg=C["card"])
        row.pack(fill="x", side="bottom", pady=(S(8), 0), before=self.runs)
        ui.FlatButton(row, "Refresh", command=self.refresh, kind="secondary", font=F["label"],
                      padx=10, pady=5).pack(side="left")
        ui.FlatButton(row, "Self-test", command=self.selftest, kind="secondary", font=F["label"],
                      padx=10, pady=5).pack(side="left", padx=S(6))
        ui.FlatButton(row, "Support package", command=self.support, kind="ghost", font=F["label"],
                      padx=10, pady=5).pack(side="left")
        right = ui.Card(split, "Screens in the selected run", pad=12)
        split.add(right, minsize=400)
        self.detail = ui.Table(right.body, (("screen", "Screen", 100, "w"), ("status", "Status", 90, "w"),
                                            ("rows", "Rows", 70, "e"), ("dates", "Dates", 120, "w"),
                                            ("detail", "Detail", 320, "w")), height=6, stretch="detail")
        self.detail.pack(fill="both", expand=True)
        links = tk.Frame(right.body, bg=C["card"])
        links.pack(fill="x", side="bottom", pady=(S(8), 0), before=self.detail)
        ui.FlatButton(links, "Open the summary", command=self.open_summary, kind="ghost",
                      font=F["label"], padx=8, pady=3).pack(side="left")
        ui.FlatButton(links, "Open the files", command=self.open_files, kind="ghost",
                      font=F["label"], padx=8, pady=3).pack(side="left")
        self.history = []

    def on_show(self, **_kw):
        self.refresh()

    def refresh(self):
        self.history = service.gmes_library.run_history()
        rows = []
        for i, run in enumerate(self.history):
            c = run["counts"]
            ok = c.get("ok", 0)
            # Keyed by the report file, not the position: a new run moves every position
            # down one, and the kept selection then showed a different run.
            rows.append(({"i": run.get("path") or f"#{i}", "started": run["started"], "name": run["name"] or "-",
                          "result": f"{ok} of {run['total']} delivered"},
                         "ok" if ok == run["total"] else ("warn" if ok else "err")))
        self.runs.keys = ["started", "name", "result"]
        self.runs.fill(rows, iid_key="i")
        self.detail.fill([])
        self.show_run()                     # the kept selection's screens, not an empty table

    def _run(self):
        sel = self.runs.selected()
        if not sel:
            return None
        return next((r for i, r in enumerate(self.history) if (r.get("path") or f"#{i}") == sel[0]), None)

    def show_run(self):
        run = self._run()
        if not run:
            return
        rows = []
        for r in run["results"]:
            st = r.get("status", "")
            detail = (", ".join(os.path.basename(f) for f in r.get("files", [])) if st == "ok"
                      else service.plain(r.get("error") or ""))
            rows.append(({"screen": r.get("screen"), "status": st.replace("_", " "),
                          "rows": f"{int(r.get('rows') or 0):,}", "dates": r.get("dates") or "-",
                          "detail": detail}, {"ok": "ok", "failed": "err"}.get(st, "warn")))
        self.detail.fill(rows)

    def open_summary(self):
        run = self._run()
        if run:
            self.app.open_path(run.get("summary") or run.get("path"))

    def open_files(self):
        run = self._run()
        if run and run.get("output_dir") and os.path.isdir(run["output_dir"]):
            self.app.open_path(run["output_dir"])

    def selftest(self):
        def work(stop, log):
            import contextlib
            import io
            import sys
            # The running window IS gmes_app, loaded as __main__. Importing it by name
            # would load and run a second copy of the module (its start-up included).
            fn = getattr(sys.modules.get("__main__"), "selftest", None)
            if fn is None:
                import gmes_app
                fn = gmes_app.selftest
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = fn()
            return code, buf.getvalue()

        def done(result):
            code, text = result
            for line in text.splitlines():
                self.app.log(line, "ok" if code == 0 else "warn")
        self.app.run_task("Self-test", work, done, needs_session=False)

    def support(self):
        def done(path):
            self.app.log(f"Support package: {path} - logs and settings, never passwords.", "ok")
            if path:
                self.app.open_path(os.path.dirname(str(path)))
        self.app.run_task("Support package", lambda s, l: service.support_package(), done,
                          needs_session=False)


# ==========================================================================
# Account & Browser
# ==========================================================================
class AccountPage(Page):
    key = "account"
    title = "Account & Browser"
    subtitle = ("Each person saves their OWN Knox / G-MES login on their own PC, and chooses whose "
                "browser profile the automation starts from.")

    def build(self, outer):
        scroller = ui.ScrollFrame(outer, C["bg"])           # small laptop screens: nothing is cut off
        scroller.pack(fill="both", expand=True)
        body = tk.Frame(scroller.inner, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=(0, S(10)))
        ready = ui.Card(body, "This PC", subtitle="Everything a run needs, checked without signing in")
        ready.pack(fill="x", pady=(0, S(12)))
        self.ready_items = {}
        row = tk.Frame(ready.body, bg=C["card"])
        row.pack(fill="x")
        for i, (key, text) in enumerate((("login", "G-MES login"), ("browser", "Chrome / Edge"),
                                         ("copy", "Browser copy"), ("folder", "Data folder"))):
            cell = tk.Frame(row, bg=C["tile"], highlightthickness=1, highlightbackground=C["line"])
            cell.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else S(10), 0))
            row.grid_columnconfigure(i, weight=1, uniform="r")
            dot = tk.Canvas(cell, width=S(22), height=S(22), bg=C["tile"], highlightthickness=0)
            dot.pack(side="left", padx=(S(12), S(8)), pady=S(12))
            texts = tk.Frame(cell, bg=C["tile"])
            texts.pack(side="left", fill="x", expand=True, pady=S(8))
            tk.Label(texts, text=text, font=F["label"], bg=C["tile"], fg=C["text"], anchor="w").pack(fill="x")
            detail = tk.Label(texts, text="checking...", font=F["small"], bg=C["tile"], fg=C["muted"],
                              anchor="w", justify="left", wraplength=S(230))
            detail.pack(fill="x")
            self.ready_items[key] = (dot, detail)
        cols = tk.Frame(body, bg=C["bg"])
        cols.pack(fill="both", expand=True)
        cols.grid_columnconfigure(0, weight=1, uniform="a")
        cols.grid_columnconfigure(1, weight=1, uniform="a")
        cols.grid_rowconfigure(0, weight=1)

        card = ui.Card(cols, "G-MES login", step="A", subtitle="The Knox / G-MES account this PC signs in with")
        card.grid(row=0, column=0, sticky="nsew", padx=(0, S(6)))
        b = card.body
        b.grid_columnconfigure(0, weight=1)
        self.login_banner = ui.Banner(b, "", "info", wrap=440)
        self.login_banner.grid(row=0, column=0, sticky="we", pady=(0, S(12)))
        self.v_user, self.v_pw1, self.v_pw2 = tk.StringVar(), tk.StringVar(), tk.StringVar()
        grid_field(b, 1, "Knox / G-MES user ID", ttk.Entry(b, textvariable=self.v_user))
        pw = tk.Frame(b, bg=C["card"])
        self.ent_pw1 = ttk.Entry(pw, textvariable=self.v_pw1, show="•")
        self.ent_pw1.pack(side="left", fill="x", expand=True)
        self.btn_show = ui.FlatButton(pw, "Show", command=self._toggle, kind="secondary", font=F["label"],
                                      padx=12, pady=5)
        self.btn_show.pack(side="left", padx=(S(8), 0))
        grid_field(b, 3, "Password", pw)
        self.ent_pw2 = ttk.Entry(b, textvariable=self.v_pw2, show="•")
        grid_field(b, 5, "Password again", self.ent_pw2)
        btns = tk.Frame(b, bg=C["card"])
        btns.grid(row=7, column=0, sticky="w", pady=(S(4), S(10)))
        ui.FlatButton(btns, "Save login", command=self.save_login, kind="primary").pack(side="left")
        ui.FlatButton(btns, "Test sign-in", command=self.test, kind="secondary").pack(side="left", padx=S(10))
        ui.note(b, "Encrypted with Windows (DPAPI) for this Windows account only. It is never shown, "
                   "logged or written anywhere else, and only typed into the Samsung sign-in page.",
                wrap=460, fit=True).grid(row=8, column=0, sticky="we")

        card = ui.Card(cols, "Browser", step="B", subtitle="Whose browser profile the automation starts from")
        card.grid(row=0, column=1, sticky="nsew", padx=(S(6), 0))
        b = card.body
        b.grid_columnconfigure(0, weight=1)
        self.v_browser = tk.StringVar(value=load_settings().get("browser", "auto"))
        ui.Segmented(b, (("auto", "Automatic (Windows default)"), ("chrome", "Chrome"), ("edge", "Edge")),
                     self.v_browser, padx=12).grid(row=0, column=0, sticky="w", pady=(0, S(10)))
        self.rows_box = tk.Frame(b, bg=C["card"])
        self.rows_box.grid(row=1, column=0, sticky="we")
        self.browser_banner = ui.Banner(b, "Checking the browsers...", "info", wrap=440)
        self.browser_banner.grid(row=2, column=0, sticky="we", pady=(S(10), S(8)))
        ui.FlatButton(b, "Use this browser", command=self.apply_browser, kind="primary").grid(
            row=3, column=0, sticky="w")
        ui.note(b, "On the first run the tool makes its OWN copy of that browser's profile, once, so "
                   "an existing G-MES session comes along. The person's own browser is only read. "
                   "Their extensions are switched off in the automation browser.",
                wrap=460, fit=True).grid(row=4, column=0, sticky="we", pady=(S(10), 0))

    def on_show(self, **_kw):
        self.refresh()

    def refresh(self):
        user, problem = account.saved_login()
        self.user = user
        if user:
            self.login_banner.set(f"Saved for Windows user '{account.windows_user()}': Knox ID {user}. "
                                  "Type a new one below only to replace it.", "ok")
            self._ready("login", "ok", f"saved ({user})")
            self.app.nav["account"].set_badge("")
        else:
            self.login_banner.set(f"{problem}." if problem else "No login saved on this PC yet.", "warn")
            self._ready("login", "err", "not saved yet")
            self.app.nav["account"].set_badge("●")
        self._ready("folder", "ok", "data\\ beside the app")
        threading.Thread(target=lambda: self.app.call_soon(self._browsers, account.describe_browsers()),
                         daemon=True).start()

    def _ready(self, key, tone, text):
        dot, detail = self.ready_items[key]
        color = {"ok": C["ok"], "warn": C["warn"], "err": C["err"], "info": C["accent"]}[tone]
        dot.delete("all")
        dot.create_oval(S(2), S(2), S(20), S(20), fill=color, outline="")
        dot.create_text(S(11), S(11), text={"ok": "✓"}.get(tone, "!"),
                         fill=C["on_accent"] if tone == "info" else "#FFFFFF", font=F["badge"])
        detail.configure(text=text)

    def _browsers(self, info):
        for w in self.rows_box.winfo_children():
            w.destroy()
        for br in info["browsers"]:
            cell = tk.Frame(self.rows_box, bg=C["tile"], highlightthickness=1, highlightbackground=C["line"])
            cell.pack(fill="x", pady=(0, S(8)))
            top = tk.Frame(cell, bg=C["tile"])
            top.pack(fill="x", padx=S(12), pady=(S(8), 0))
            tk.Label(top, text=br["label"], font=F["label"], bg=C["tile"]).pack(side="left")
            if info["default"] == br["key"]:
                tk.Label(top, text="WINDOWS DEFAULT", font=F["tiny"], bg=C["accent_soft"], fg=C["accent"],
                         padx=S(6)).pack(side="left", padx=S(8))
            tk.Label(top, text="installed" if br["installed"] else "not installed", font=F["small"],
                     bg=C["tile"], fg=C["ok_text"] if br["installed"] else C["faint"]).pack(side="right")
            p = br["profiles"][0] if br["profiles"] else None
            text = (f"Profile to copy: '{p['name']}' · " + {True: "has used G-MES", False: "no G-MES use seen",
                                                             None: "G-MES use unknown"}[p["gmes"]]) if p else "-"
            tk.Label(cell, text=text, font=F["small"], bg=C["tile"], fg=C["muted"], anchor="w").pack(
                fill="x", padx=S(12), pady=(S(2), S(8)))
        state = info.get("state") or {}
        done = bool(state.get("completed") and info.get("same_machine"))
        self.browser_banner.set(account.setup_sentence(info), "ok" if done else "info")
        installed = [b for b in info["browsers"] if b["installed"]]
        self._ready("browser", "ok" if installed else "err",
                    ", ".join(b["label"].split()[-1] for b in installed) + " found" if installed else "none found")
        self._ready("copy", "ok" if done else "info", "ready" if done else "made on the first run")

    def _toggle(self):
        showing = self.ent_pw1.cget("show") == ""
        for e in (self.ent_pw1, self.ent_pw2):
            e.configure(show="•" if showing else "")
        self.btn_show.set_text("Show" if showing else "Hide")

    def save_login(self):
        u, p1, p2 = self.v_user.get(), self.v_pw1.get(), self.v_pw2.get()
        problems = account.check_new_login(u, p1, p2)
        if problems:
            ui.tell(self.app, "Check the login", "\n".join(problems), icon="warn")
            return
        if self.user and not ui.ask(self.app, "Replace the saved login?",
                                    f"Knox ID '{self.user}' is saved on this PC. Replace it with '{u.strip()}'?",
                                    yes="Replace", icon="warn"):
            return
        try:
            saved = account.save_login(u, p1, p2)
        except (ValueError, OSError) as e:
            ui.tell(self.app, "Not saved", str(e), icon="err")
            return
        self.v_pw1.set("")
        self.v_pw2.set("")
        self.app.log(f"Login saved for Knox ID {saved}.", "ok")
        self.refresh()

    def test(self):
        self.app.run_task("Test sign-in", lambda s, l: self.app.session.who or "signed in",
                          lambda who: self.app.log(f"Sign-in works ({who}).", "ok"))

    def apply_browser(self):
        if self.app.busy:
            ui.tell(self.app, "Busy", "Change the browser when nothing is running.", icon="warn")
            return
        choice = self.v_browser.get()
        self.app.session.close()
        plan = account.apply_browser_choice(choice)
        save_settings(browser=choice)
        self.app.log(f"Browser: {account.CHOICE_LABELS[choice]}"
                     + (" - a separate automation profile is used for it." if plan.get("GMES_PROFILE_DIR") else "."),
                     "ok")
        self.refresh()
