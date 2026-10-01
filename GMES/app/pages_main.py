"""The three working pages: Reports (the library), Record (any UI number, with the full
record check) and Run & Batch."""
import os
import re
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, ttk

import service
import ui_kit as ui
from page_base import Page
from ui_kit import C, F, S

STATUS_TAG = {"Ready": "ok", "Ready with warning": "warn", "Last run failed": "err",
              "Not yet run here": "muted"}
VERDICT_TAG = {"PASSED": "ok", "PASSED WITH WARNINGS": "warn", "FAILED": "err"}
CHECK_ICON = {"ok": "✓", "warn": "!", "fail": "✕", "info": "·"}
CHECK_TAG = {"ok": "ok", "warn": "warn", "fail": "err", "info": "muted"}


def grid_field(parent, row, label, widget, hint=None, col=0, span=1, pad=10):
    ui.field_label(parent, label, hint).grid(row=row, column=col, columnspan=span, sticky="w")
    widget.grid(row=row + 1, column=col, columnspan=span, sticky="we", pady=(S(4), S(pad)))
    return widget


def show_checks(table, banner, result):
    rows = [({"s": CHECK_ICON[c["status"]], "check": c["name"], "detail": c["detail"]},
             CHECK_TAG[c["status"]]) for c in result["checks"]]
    table.fill(rows)
    v = result["verdict"]
    tone = {"PASSED": "ok", "PASSED WITH WARNINGS": "warn"}.get(v, "err")
    text = {"PASSED": "Record check PASSED - every item proven. The screen is ready for batches "
                      "and schedules.",
            "PASSED WITH WARNINGS": "Record check PASSED WITH WARNINGS - read every '!' line "
                                    "below; they are not hidden failures but things to know.",
            "FAILED": "Record check FAILED - the '✕' lines say what was not proven. The screen "
                      "is NOT ready; fix the scope and record again."}[v]
    banner.set(text, tone)


# ==========================================================================
# Reports
# ==========================================================================
class ReportsPage(Page):
    key = "reports"
    title = "Reports"
    subtitle = ("Every screen this app can run. 'Record check' is the proof a recording works: "
                "a bare replay plus every item of the playbook, kept as a certificate.")

    def build(self, body):
        bar = tk.Frame(body, bg=C["bg"])
        bar.pack(fill="x", pady=(0, S(10)))
        self.v_search = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.v_search, width=34)
        entry.pack(side="left")
        tk.Label(bar, text="  search code, title, division", font=F["small"], bg=C["bg"],
                 fg=C["faint"]).pack(side="left")
        self.v_search.trace_add("write", lambda *_a: self.refresh())
        self.v_view = tk.StringVar(value="all")
        ui.Segmented(bar, (("all", "All"), ("recorded", "Recorded here"), ("attention", "Needs attention")),
                     self.v_view, command=self.refresh, padx=12).pack(side="left", padx=(S(16), 0))
        ui.FlatButton(bar, "Import recordings...", command=self.import_recordings, kind="secondary",
                      font=F["label"], padx=12, pady=5).pack(side="right")
        ui.FlatButton(bar, "Refresh", command=self.refresh, kind="ghost", font=F["label"],
                      padx=10, pady=5).pack(side="right", padx=S(6))

        self.start_here = ui.Banner(body, "Start here: nothing is recorded on this PC yet. Record a screen "
                                          "(any UI number), or bring recordings from another PC or from "
                                          "the project's screens folder with 'Import recordings'.",
                                    "info", wrap=900, action=lambda: self.app.show("record"),
                                    action_text="Record a screen")
        split = tk.Frame(body, bg=C["bg"])
        split.pack(fill="both", expand=True)
        self.split = split
        split.grid_columnconfigure(0, weight=3)
        split.grid_columnconfigure(1, weight=2, minsize=S(380))
        split.grid_rowconfigure(0, weight=1)
        left = ui.Card(split, pad=12)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, S(12)))
        self.table = ui.Table(left.body, (("code", "Screen", 110, "w"), ("title", "Title", 260, "w"),
                                          ("status", "Status", 140, "w"), ("check", "Record check", 150, "w"),
                                          ("settings", "Replays with", 200, "w"),
                                          ("last", "Last run", 210, "w")),
                              height=14, select="extended", stretch="title")
        self.table.pack(fill="both", expand=True)
        self.table.tree.bind("<<TreeviewSelect>>", lambda _e: self.show_detail())
        self.table.tree.bind("<Double-1>", lambda _e: self.run_selected())
        self.lbl_count = ui.note(left.body, "", wrap=700)
        self.lbl_count.pack(fill="x", pady=(S(8), 0))

        right = ui.Card(split, "Selected screen", pad=16)
        right.grid(row=0, column=1, sticky="nsew")
        self.detail = tk.Frame(right.body, bg=C["card"])
        self.detail.pack(fill="both", expand=True)
        actions = tk.Frame(right.body, bg=C["card"])
        actions.pack(fill="x", pady=(S(10), 0))
        ui.field_label(actions, "Run for").grid(row=0, column=0, sticky="w")
        self.v_policy = tk.StringVar(value="keep")
        ui.Segmented(actions, (("keep", "As recorded"), ("yesterday", "Yesterday"), ("today", "Today")),
                     self.v_policy, padx=11).grid(row=1, column=0, columnspan=3, sticky="w",
                                                  pady=(S(4), S(10)))
        self.btn_run = ui.FlatButton(actions, "▶  Run selected", command=self.run_selected,
                                     kind="success", padx=16, pady=7)
        self.btn_run.grid(row=2, column=0, sticky="w")
        self.btn_check = ui.FlatButton(actions, "Record check", command=self.check_selected,
                                       kind="primary", padx=14, pady=7)
        self.btn_check.grid(row=2, column=1, sticky="w", padx=(S(8), 0))
        self.btn_rerecord = ui.FlatButton(actions, "Re-record", command=self.rerecord, kind="secondary",
                                          padx=12, pady=7)
        self.btn_rerecord.grid(row=2, column=2, sticky="w", padx=(S(8), 0))
        more = tk.Frame(actions, bg=C["card"])
        more.grid(row=3, column=0, columnspan=3, sticky="w", pady=(S(8), 0))
        ui.FlatButton(more, "Open output folder", command=self.open_output, kind="ghost",
                      font=F["label"], padx=8, pady=3).pack(side="left")
        ui.FlatButton(more, "Forget this recording", command=self.forget, kind="ghost",
                      font=F["label"], padx=8, pady=3).pack(side="left")
        self.cards = []

    def on_show(self, **_kw):
        self.refresh()

    def on_busy(self, busy):
        for b in (self.btn_run, self.btn_check, self.btn_rerecord):
            b.set_enabled(not busy)

    def refresh(self):
        try:
            self.cards = service.library()
        except Exception as e:                               # noqa: BLE001
            self.app.log(f"PROBLEM: the recordings could not be read ({e})", "err")
            self.cards = []
        words = [w for w in self.v_search.get().lower().split() if w]
        view = self.v_view.get()
        rows = []
        for c in self.cards:
            hay = f"{c['code']} {c['title']} {c['settings']}".lower()
            if words and not all(w in hay for w in words):
                continue
            if view == "recorded" and not c["recorded"]:
                continue
            if view == "attention" and c["status"] in ("Ready",) and c["check"] in ("PASSED", ""):
                continue
            check = (f"{c['check'].title()}  {c['check_at'][:10]}" if c["check"] else
                     ("not checked yet" if c["recorded"] else "-"))
            tag = (VERDICT_TAG.get(c["check"]) if c["check"] == "FAILED"
                   else STATUS_TAG.get(c["status"], ""))
            rows.append(({"code": c["code"], "title": c["title"], "status": c["status"],
                          "check": check, "settings": c["replays"], "last": c["last_run"] or "-"}, tag))
        self.table.fill(rows, iid_key="code")
        recorded = sum(1 for c in self.cards if c["recorded"])
        if recorded == 0 and not self.start_here.winfo_ismapped():
            self.start_here.pack(fill="x", pady=(0, S(10)), before=self.split)
        elif recorded and self.start_here.winfo_ismapped():
            self.start_here.pack_forget()
        bad = service.unreadable_profiles()
        text = f"{len(rows)} shown  ·  {recorded} recorded on this PC  ·  {len(self.cards)} known"
        if bad:
            text += f"  ·  ⚠ {len(bad)} recording file(s) could not be read: " + ", ".join(
                os.path.basename(p) for p, _w in bad[:4])
        self.lbl_count.configure(text=text)
        self.show_detail()

    def _selected_cards(self):
        codes = set(self.table.selected())
        return [c for c in self.cards if c["code"] in codes]

    def show_detail(self):
        for w in self.detail.winfo_children():
            w.destroy()
        picked = self._selected_cards()
        if not picked:
            ui.note(self.detail, "Choose a screen on the left. Double-click runs it.",
                    wrap=360).pack(anchor="w")
            return
        if len(picked) > 1:
            ui.note(self.detail, f"{len(picked)} screens selected - 'Run selected' runs them one after "
                                 "another in the same browser, like a batch.", wrap=360).pack(anchor="w")
            return
        c = picked[0]
        tk.Label(self.detail, text=f"{c['code']}", font=F["card_title"], bg=C["card"],
                 fg=C["text"], anchor="w").pack(fill="x")
        tk.Label(self.detail, text=c["title"], font=F["small"], bg=C["card"], fg=C["muted"],
                 anchor="w", wraplength=S(360), justify="left").pack(fill="x", pady=(0, S(10)))
        tone = {"Ready": "ok", "Ready with warning": "warn", "Last run failed": "err"}.get(c["status"], "info")
        ui.Banner(self.detail, f"{c['status']}: {c['why']}", tone, wrap=340).pack(fill="x", pady=(0, S(10)))
        for label, value in (("Replays with", c["replays"]),
                             ("Recorded", c["learned"] or "only the shipped structure - record it here"),
                             ("Last run", c["last_run"] or "-"),
                             ("Record check", f"{c['check']}  ({c['check_at']})" if c["check"] else "not yet"),
                             ("Files go to", c["output_dir"] or "the app's output folder")):
            row = tk.Frame(self.detail, bg=C["card"])
            row.pack(fill="x", pady=S(2))
            tk.Label(row, text=label, font=F["small"], bg=C["card"], fg=C["muted"], width=13,
                     anchor="w").pack(side="left")
            tk.Label(row, text=value, font=F["label"], bg=C["card"], fg=C["text"], anchor="w",
                     justify="left", wraplength=S(250)).pack(side="left", fill="x")

    def run_selected(self):
        picked = self._selected_cards()
        if not picked:
            return
        not_ready = [c["code"] for c in picked if not c["recorded"]]
        if not_ready:
            ui.tell(self.app, "Record it first", "These have only the shipped structure on this PC: "
                    + ", ".join(not_ready) + ". Record them here once (Re-record).", icon="warn")
            return
        self.app.pages["batch"].run_codes([c["code"] for c in picked], self.v_policy.get())

    def check_selected(self):
        picked = self._selected_cards()
        if len(picked) != 1:
            ui.tell(self.app, "Choose one screen", "The record check runs one screen at a time.", icon="info")
            return
        code = picked[0]["code"]
        if not ui.ask(self.app, f"Record check {code}?",
                      "The screen is replayed bare - its code and nothing else - and every item of "
                      "the check is proven again. It reads G-MES and exports one file.",
                      yes="Run the check", icon="ask"):
            return

        def work(stop, log):
            ws = self.app.session.ensure(stop)
            return service.recheck(ws, code, log=service.stoppable(log, stop))

        def done(result):
            self.refresh()
            self.app.show("record", result=result, code=code)
        self.app.run_task(f"Record check {code}", work, done)

    def rerecord(self):
        picked = self._selected_cards()
        if len(picked) != 1:
            return
        self.app.show("record", code=picked[0]["code"], describe=True)

    def open_output(self):
        picked = self._selected_cards()
        path = (picked[0]["output_dir"] if picked and picked[0]["output_dir"]
                else os.path.join(service.app_env.data_dir(), "output"))
        os.makedirs(path, exist_ok=True)
        self.app.open_path(path)

    def forget(self):
        picked = self._selected_cards()
        if len(picked) != 1 or not picked[0]["recorded"]:
            return
        code = picked[0]["code"]
        if not ui.ask(self.app, f"Forget {code}?",
                      "This app's recording of the screen is removed (scope, dates, filters). The "
                      "exported files are kept. You can record it again at any time.",
                      yes="Forget it", kind="danger", icon="warn"):
            return
        service.forget(code)
        self.app.log(f"Forgot the recording of {code}.", "warn")
        self.refresh()

    def import_recordings(self):
        project = os.path.join(os.path.dirname(service.app_env.base_dir()), "screens")
        folder = filedialog.askdirectory(title="Folder with recordings (<CODE>.json)", parent=self.app,
                                         initialdir=project if os.path.isdir(project) else None)
        if not folder:
            return
        done, skipped = service.import_recordings(folder)
        self.app.log(f"Imported {len(done)} recording(s): {', '.join(done) or '-'}", "ok" if done else "warn")
        for s in skipped:
            self.app.log(f"  not imported: {s}", "muted")
        ui.tell(self.app, "Import finished", f"{len(done)} imported, {len(skipped)} left as they were "
                                             "(see Activity).", icon="ok" if done else "info")
        self.refresh()


# ==========================================================================
# Record
# ==========================================================================
class RecordPage(Page):
    key = "record"
    title = "Record a screen"
    subtitle = ("Any UI number: find it, see what it offers, choose the scope, record. The record "
                "check then replays it bare and proves every item before it counts as recorded.")

    def build(self, body):
        body.grid_columnconfigure(0, weight=5, minsize=S(520))
        body.grid_columnconfigure(1, weight=4, minsize=S(420))
        body.grid_rowconfigure(0, weight=1)
        left = ui.ScrollFrame(body, C["bg"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, S(12)))
        self.col = left.inner
        right = tk.Frame(body, bg=C["bg"])
        right.grid(row=0, column=1, sticky="nsew")
        self.desc = None
        self._build_screen(self.col)
        self._build_offer(self.col)
        self._build_scope(self.col)
        self._build_export(self.col)
        self._build_results(right)

    # ---- step 1 ---------------------------------------------------------------
    def _build_screen(self, col):
        card = ui.Card(col, "Screen", step=1, subtitle="A UI number, or words from its name")
        card.pack(fill="x", pady=(0, S(12)))
        b = card.body
        row = tk.Frame(b, bg=C["card"])
        row.pack(fill="x")
        self.v_code = tk.StringVar()
        e = ttk.Entry(row, textvariable=self.v_code, width=22, font=("Segoe UI Semibold", 11))
        e.pack(side="left")
        e.bind("<Return>", lambda _e: self.describe())
        self.btn_find = ui.FlatButton(row, "Find", command=self.find, kind="secondary", padx=14, pady=6)
        self.btn_find.pack(side="left", padx=(S(8), 0))
        self.btn_describe = ui.FlatButton(row, "Describe", command=self.describe, kind="primary",
                                          padx=14, pady=6)
        self.btn_describe.pack(side="left", padx=(S(8), 0))
        ui.note(b, "Describe opens the screen and reads it - grids, filters, divisions, options, "
                   "date columns. It changes nothing in G-MES.", wrap=480).pack(fill="x", pady=(S(8), 0))
        self.find_table = ui.Table(b, (("code", "Screen", 110, "w"), ("title", "Name", 220, "w"),
                                       ("path", "Menu", 260, "w")), height=5, stretch="path")
        self.find_table.tree.bind("<Double-1>", lambda _e: self._pick_found(describe=True))
        self.find_table.tree.bind("<<TreeviewSelect>>", lambda _e: self._pick_found())
        self.lbl_find = ui.note(b, "", wrap=480)

    def _pick_found(self, describe=False):
        sel = self.find_table.selected()
        if sel:
            self.v_code.set(self.find_table.tree.set(sel[0], "code"))
            if describe:
                self.describe()

    def find(self):
        query = self.v_code.get().strip()
        if not query:
            return

        def work(stop, log):
            return service.find(self.app.session.ensure(stop), query)

        def done(found):
            rows = [({"code": r["code"], "title": r["title"], "path": r["path"]}, "") for r in found["rows"]]
            self.find_table.fill(rows, iid_key=None)
            self.find_table.pack(fill="x", pady=(S(10), 0))
            more = (f" - showing the first {len(rows)} of {found['matched']}; type more words"
                    if found["truncated"] else "")
            self.lbl_find.configure(text=f"{found['matched']} match(es) among {found['total']} screens"
                                         f"{more}. Double-click one to describe it.")
            self.lbl_find.pack(fill="x", pady=(S(6), 0))
        self.app.run_task(f"Find '{query}'", work, done)

    def describe(self):
        code = service.normalise_code(self.v_code.get())
        if not service.CODE_RE.match(code):
            if self.v_code.get().strip():
                self.find()
            return
        self.v_code.set(code)

        def work(stop, log):
            return service.describe(self.app.session.ensure(stop), code,
                                    log=service.stoppable(lambda m: None, stop))
        self.app.run_task(f"Describe {code}", work, self._described)

    # ---- step 2 ---------------------------------------------------------------
    def _build_offer(self, col):
        card = ui.Card(col, "What the screen offers", step=2,
                       subtitle="Read from the live screen - the five questions of the playbook")
        card.pack(fill="x", pady=(0, S(12)))
        self.offer = card.body
        ui.note(self.offer, "Describe a screen first.", wrap=480).pack(anchor="w")

    def _described(self, desc):
        self.desc = desc
        for w in self.offer.winfo_children():
            w.destroy()
        o = self.offer
        tk.Label(o, text=f"{desc['title']}", font=F["card_title"], bg=C["card"], fg=C["text"],
                 anchor="w").pack(fill="x")
        tk.Label(o, text=f"{desc['code']}  ·  menu {desc['menu_id']}  ·  Inquiry "
                         f"{'yes' if desc['has_inquiry'] else 'no'}  ·  Excel "
                         f"{'yes' if desc['has_excel'] else 'no'}", font=F["small"], bg=C["card"],
                 fg=C["muted"], anchor="w").pack(fill="x", pady=(0, S(8)))
        for question, answer, tone in service.five_questions(desc):
            row = tk.Frame(o, bg=C["card"])
            row.pack(fill="x", pady=S(2))
            color = {"ok": C["ok"], "warn": C["warn"], "decide": C["accent"]}[tone]
            tk.Label(row, text={"ok": "✓", "warn": "!", "decide": "?"}[tone], font=F["label"],
                     bg=C["card"], fg=color, width=2).pack(side="left", anchor="n")
            box = tk.Frame(row, bg=C["card"])
            box.pack(side="left", fill="x", expand=True)
            tk.Label(box, text=question, font=F["label"], bg=C["card"], fg=C["text"], anchor="w").pack(fill="x")
            tk.Label(box, text=answer, font=F["small"], bg=C["card"], fg=C["muted"], anchor="w",
                     justify="left", wraplength=S(440)).pack(fill="x")
        if desc.get("profile") and desc["profile"].get("learned"):
            ui.Banner(o, f"Already recorded here on {desc['profile']['learned']}. Recording again "
                         "replaces it only if the new recording succeeds.", "info",
                      wrap=460).pack(fill="x", pady=(S(10), 0))
        self._fill_scope(desc)
        self.app.log(f"Described {desc['code']} - {desc['title']}: {len(desc['grids'])} grid(s), "
                     f"{len(desc['filters'])} filter(s), {len(desc['trees'])} tree(s).", "ok")

    # ---- step 3 ---------------------------------------------------------------
    def _build_scope(self, col):
        card = ui.Card(col, "Scope", step=3, subtitle="What the recording will use every time it runs")
        card.pack(fill="x", pady=(0, S(12)))
        b = card.body
        b.grid_columnconfigure(0, weight=1)
        b.grid_columnconfigure(1, weight=1)
        self.v_grid = tk.StringVar()
        self.cmb_grid = ttk.Combobox(b, textvariable=self.v_grid, state="readonly")
        grid_field(b, 0, "Result grid", self.cmb_grid, hint="the table that IS the report", span=2)
        self.v_div = tk.StringVar(value="VD")
        self.cmb_div = ttk.Combobox(b, textvariable=self.v_div)
        grid_field(b, 2, "Division / organisation", self.cmb_div, hint="empty = the screen's own", span=2)
        ui.field_label(b, "Period").grid(row=4, column=0, columnspan=2, sticky="w")
        self.v_pmode = tk.StringVar(value="day")
        ui.Segmented(b, (("none", "No date"), ("day", "Day(s)"), ("month", "Month")), self.v_pmode,
                     command=self._period_mode, padx=12).grid(row=5, column=0, columnspan=2, sticky="w",
                                                              pady=(S(4), S(8)))
        self.v_from = tk.StringVar(value=service.yesterday())
        self.v_to = tk.StringVar(value=service.yesterday())
        self.ent_from = grid_field(b, 6, "From", ttk.Entry(b, textvariable=self.v_from),
                                   hint="YYYYMMDD", col=0)
        self.ent_to = grid_field(b, 6, "To", ttk.Entry(b, textvariable=self.v_to), col=1)
        quick = tk.Frame(b, bg=C["card"])
        quick.grid(row=8, column=0, columnspan=2, sticky="w", pady=(0, S(8)))
        for text, days in (("Yesterday", 1), ("Today", 0)):
            ui.FlatButton(quick, text, command=lambda d=days: self._quick(d), kind="chip",
                          font=F["label"], padx=10, pady=3).pack(side="left", padx=(0, S(6)))
        self.v_verify = tk.StringVar()
        self.cmb_verify = ttk.Combobox(b, textvariable=self.v_verify)
        grid_field(b, 9, "Verify: the result column that holds the date", self.cmb_verify,
                   hint="required for a dated run", span=2)
        ui.field_label(b, "Options", "left-panel choices to switch on").grid(row=11, column=0, columnspan=2,
                                                                             sticky="w")
        self.opt_box = tk.Frame(b, bg=C["card"])
        self.opt_box.grid(row=12, column=0, columnspan=2, sticky="we", pady=(S(4), S(8)))
        self.option_vars = {}
        ui.field_label(b, "Filters", "leave empty to keep the screen's value").grid(
            row=13, column=0, columnspan=2, sticky="w")
        self.flt_box = tk.Frame(b, bg=C["card"])
        self.flt_box.grid(row=14, column=0, columnspan=2, sticky="we", pady=(S(4), S(8)))
        self.filter_vars = {}
        self.v_more = tk.StringVar()
        grid_field(b, 15, "More filters", ttk.Entry(b, textvariable=self.v_more),
                   hint="Name=Value; Name=Value", span=2, pad=2)
        self._period_mode()

    def _period_mode(self):
        mode = self.v_pmode.get()
        state = "disabled" if mode == "none" else "normal"
        for e in (self.ent_from, self.ent_to):
            e.configure(state=state)
        if mode == "month":
            ym = datetime.now().strftime("%Y%m")
            if len(re.sub(r"\D", "", self.v_from.get())) != 6:
                self.v_from.set(ym)
                self.v_to.set(ym)
        elif mode == "day" and len(re.sub(r"\D", "", self.v_from.get())) != 8:
            self.v_from.set(service.yesterday())
            self.v_to.set(service.yesterday())

    def _quick(self, days):
        from datetime import timedelta
        d = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        self.v_pmode.set("day")
        self.v_from.set(d)
        self.v_to.set(d)
        self._period_mode()

    def _fill_scope(self, desc):
        names = [g["name"] for g in desc["grids"]]
        self.cmb_grid.configure(values=[f"{g['name']}  ({g['dataset']}, {g['cols']} cols)"
                                        + ("  - suggested" if g["suggested"] else "") for g in desc["grids"]])
        sug = next((i for i, g in enumerate(desc["grids"]) if g["suggested"]), 0 if names else None)
        self.v_grid.set(self.cmb_grid.cget("values")[sug] if sug is not None else "")
        divisions = sorted({n for t in desc["trees"] for n in t["names"]})
        self.cmb_div.configure(values=[""] + divisions)
        profile = desc.get("profile") or {}
        last = {}
        try:
            import gmes_profile
            last = gmes_profile.last_values(profile) if profile else {}
        except Exception:                                    # noqa: BLE001
            last = {}
        if last.get("division"):
            self.v_div.set(last["division"])
        elif divisions:
            self.v_div.set("VD" if "VD" in divisions else "")
        else:
            self.v_div.set("")
        if not desc["date_fields"]:
            self.v_pmode.set("none")
        elif desc.get("looks_monthly"):
            self.v_pmode.set("month")
        else:
            self.v_pmode.set("day")
        self._period_mode()
        self.cmb_verify.configure(values=desc["verify_candidates"])
        self.v_verify.set(last.get("verify") or (desc["verify_candidates"][0]
                                                 if desc["verify_candidates"] else ""))
        for w in self.opt_box.winfo_children():
            w.destroy()
        self.option_vars = {}
        if desc["options"]:
            for i, o in enumerate(desc["options"]):
                if o["kind"] != "button" and o["kind"] != "checkbox":
                    continue
                if o["label"].lower() in ("inquiry", "search"):
                    continue
                var = tk.BooleanVar(value=False)
                text = f"{o['label']}  ({o['state']}{'' if o['enabled'] else ', disabled'})"
                cb = ttk.Checkbutton(self.opt_box, text=text, variable=var)
                cb.grid(row=i // 2, column=i % 2, sticky="w", padx=(0, S(12)))
                if not o["enabled"]:
                    cb.state(["disabled"])
                self.option_vars[o["key"] or o["label"]] = var
        else:
            ui.note(self.opt_box, "none on this screen").pack(anchor="w")
        for w in self.flt_box.winfo_children():
            w.destroy()
        self.filter_vars = {}
        shown = [f for f in desc["filters"] if not f["date"] and f["visible"]]
        for i, f in enumerate(shown):
            key = f["label"] or f["column"]
            tk.Label(self.flt_box, text=key, font=F["small"], bg=C["card"], fg=C["muted"], anchor="w",
                     width=22).grid(row=i, column=0, sticky="w", pady=S(2))
            var = tk.StringVar(value=(last.get("sets") or {}).get(key, ""))
            ttk.Entry(self.flt_box, textvariable=var, width=26).grid(row=i, column=1, sticky="we", pady=S(2))
            tk.Label(self.flt_box, text=f"now: {f['value'][:18] or '-'}", font=F["tiny"], bg=C["card"],
                     fg=C["faint"]).grid(row=i, column=2, sticky="w", padx=S(8))
            self.filter_vars[key] = var
        if not shown:
            ui.note(self.flt_box, "no other visible filters").grid(row=0, column=0, sticky="w")

    # ---- step 4 ---------------------------------------------------------------
    def _build_export(self, col):
        card = ui.Card(col, "Export and record", step=4,
                       subtitle="Excel is the default (the owner's decision, HISTORY 98.1); the rows are verified against the data itself before any file is written")
        card.pack(fill="x", pady=(0, S(4)))
        b = card.body
        self.v_export = tk.StringVar(value="xlsx")
        ui.field_label(b, "Files").pack(anchor="w")
        ui.Segmented(b, (("xlsx", "Excel"), ("csv", "CSV only")), self.v_export,
                     padx=12).pack(anchor="w", pady=(S(4), S(10)))
        ui.field_label(b, "Save the files in", "empty = the app's output folder").pack(anchor="w")
        row = tk.Frame(b, bg=C["card"])
        row.pack(fill="x", pady=(S(4), S(12)))
        self.v_out = tk.StringVar()
        ttk.Entry(row, textvariable=self.v_out).pack(side="left", fill="x", expand=True)
        ui.FlatButton(row, "Browse", command=self._browse, kind="secondary", font=F["label"],
                      padx=12, pady=5).pack(side="left", padx=(S(8), 0))
        btns = tk.Frame(b, bg=C["card"])
        btns.pack(fill="x")
        self.btn_dry = ui.FlatButton(btns, "Dry run", command=lambda: self.record(dry=True),
                                     kind="secondary", padx=14, pady=8)
        self.btn_dry.pack(side="left")
        self.btn_record = ui.FlatButton(btns, "●  Record + check", command=self.record, kind="success",
                                        font=F["button_lg"], padx=20, pady=9)
        self.btn_record.pack(side="left", padx=(S(10), 0))
        ui.note(b, "Dry run applies everything and stops before Inquiry - to check the setup. "
                   "Record + check runs it, replays it bare, and proves every item.",
                wrap=480).pack(fill="x", pady=(S(10), 0))

    def _browse(self):
        folder = filedialog.askdirectory(title="Save the files in", parent=self.app)
        if folder:
            self.v_out.set(os.path.normpath(folder))

    # ---- results ----------------------------------------------------------------
    def _build_results(self, parent):
        card = ui.Card(parent, "Record check", subtitle="Every item of the playbook, from evidence")
        card.pack(fill="both", expand=True)
        b = card.body
        self.banner = ui.Banner(b, "Record a screen to see its check here.", "info", wrap=420)
        self.banner.pack(fill="x", pady=(0, S(10)))
        self.check_table = ui.Table(b, (("s", "", 34, "center"), ("check", "Check", 230, "w"),
                                        ("detail", "Evidence", 260, "w")), height=12, stretch="detail")
        self.check_table.pack(fill="both", expand=True)
        row = tk.Frame(b, bg=C["card"])
        row.pack(fill="x", pady=(S(10), 0))
        ui.FlatButton(row, "Open the files", command=self._open_files, kind="ghost", font=F["label"],
                      padx=8, pady=3).pack(side="left")
        ui.FlatButton(row, "Open the certificate", command=self._open_cert, kind="ghost",
                      font=F["label"], padx=8, pady=3).pack(side="left")
        ui.FlatButton(row, "Go to Reports", command=lambda: self.app.show("reports"), kind="ghost",
                      font=F["label"], padx=8, pady=3).pack(side="left")
        self.last_result = None

    def _open_files(self):
        r = self.last_result
        files = ((r or {}).get("rec") or {}).get("files") or []
        if files:
            self.app.open_path(os.path.dirname(files[0]))

    def _open_cert(self):
        if self.last_result and self.last_result.get("certificate"):
            self.app.open_path(self.last_result["certificate"])

    def on_show(self, code=None, describe=False, result=None, **_kw):
        if code:
            self.v_code.set(code)
        if result:
            self._recorded(result)
        if describe and code:
            self.describe()

    def on_busy(self, busy):
        for b in (self.btn_find, self.btn_describe, self.btn_dry, self.btn_record):
            b.set_enabled(not busy)

    def _spec(self):
        code = service.normalise_code(self.v_code.get())
        mode = self.v_pmode.get()
        frm = to = ""
        if mode != "none":
            frm, to = re.sub(r"\D", "", self.v_from.get()), re.sub(r"\D", "", self.v_to.get() or self.v_from.get())
        grid = self.v_grid.get().split("  (")[0].strip()
        if self.desc and self.desc["code"] == code:
            suggested = next((g["name"] for g in self.desc["grids"] if g["suggested"]), "")
            if grid == suggested:
                grid = ""                     # the engine's own choice - remembered as such
        sets = {k: v.get().strip() for k, v in self.filter_vars.items() if v.get().strip()}
        for part in self.v_more.get().split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                if k.strip():
                    sets[k.strip()] = v.strip()
        options = [k for k, v in self.option_vars.items() if v.get()]
        return service.build_spec(code, self.v_div.get(), frm, to, sets, options, grid,
                                  self.v_verify.get() if frm else "", self.v_export.get(),
                                  self.v_out.get())

    def record(self, dry=False):
        spec = self._spec()
        problems = service.check_spec(spec)
        if problems:
            ui.tell(self.app, "Check the scope", "\n".join(problems), icon="warn")
            return
        if self.desc is None or self.desc["code"] != spec["screen_code"]:
            if not ui.ask(self.app, "Not described yet",
                          f"{spec['screen_code']} has not been described in this session. The "
                          "playbook describes first, so the scope is chosen from evidence. Record "
                          "anyway?", yes="Record anyway", icon="warn"):
                return
        details = [("Screen", spec["screen_code"]), ("Division", spec["division"] or "(screen's own)"),
                   ("Period", f"{spec['date_from']} - {spec['date_to']}" if spec["date_from"] else "(no date)"),
                   ("Verify", spec["verify"] or "-"),
                   ("Filters", ", ".join(f"{k}={v}" for k, v in spec["sets"].items()) or "-"),
                   ("Options", ", ".join(spec["options"]) or "-"), ("Files", spec["export"])]
        if not dry and not ui.ask(self.app, f"Record {spec['screen_code']}?",
                                  "It runs the screen with this scope (read-only), then replays it "
                                  "bare and checks every item. Stop is always one click away.",
                                  yes="●  Record + check", kind="success", details=details):
            return

        if dry:
            def work(stop, log):
                ws = self.app.session.ensure(stop)
                return service.record(ws, spec, log=service.stoppable(log, stop), dry_run=True)

            def done(out):
                ok = out.get("ok")
                self.banner.set("Dry run: everything was applied and Inquiry was NOT clicked. Read the "
                                "Activity lines - every value is read back." if ok else
                                f"Dry run did not finish: {out.get('error')}", "ok" if ok else "err")
            self.app.run_task(f"Dry run {spec['screen_code']}", work, done)
            return

        def work(stop, log):
            ws = self.app.session.ensure(stop)
            return service.record_and_check(ws, spec, log=service.stoppable(log, stop))
        self.app.run_task(f"Record {spec['screen_code']}", work, self._recorded)

    def _recorded(self, result):
        self.last_result = result
        show_checks(self.check_table, self.banner, result)
        self.app.log(f"Record check {result['verdict']} - certificate {result['certificate']}",
                     VERDICT_TAG.get(result["verdict"], "info"))
        self.app.pages["reports"].refresh()


# ==========================================================================
# Run & Batch
# ==========================================================================
class BatchPage(Page):
    key = "batch"
    title = "Run & Batch"
    subtitle = ("Several recorded screens, one after another, in ONE browser session. Save the "
                "choice as a batch to run it again or to schedule it.")

    def build(self, body):
        body.grid_columnconfigure(0, weight=1, minsize=S(430))
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)
        left = ui.Card(body, "Screens", subtitle="Ctrl / Shift to choose several", pad=14)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, S(12)))
        b = left.body
        row = tk.Frame(b, bg=C["card"])
        row.pack(fill="x", pady=(0, S(8)))
        self.v_batch = tk.StringVar()
        self.cmb_batch = ttk.Combobox(row, textvariable=self.v_batch, state="readonly", width=20)
        self.cmb_batch.pack(side="left")
        self.cmb_batch.bind("<<ComboboxSelected>>", lambda _e: self.load_batch())
        ui.FlatButton(row, "Save as batch...", command=self.save_batch, kind="secondary",
                      font=F["label"], padx=10, pady=5).pack(side="left", padx=(S(8), 0))
        ui.FlatButton(row, "Delete", command=self.delete_batch, kind="ghost", font=F["label"],
                      padx=8, pady=5).pack(side="left", padx=(S(4), 0))
        self.table = ui.Table(b, (("code", "Screen", 100, "w"), ("title", "Title", 200, "w"),
                                  ("replays", "Replays with", 170, "w")), height=16, select="extended",
                              stretch="title")
        self.table.pack(fill="both", expand=True)
        self.table.tree.bind("<<TreeviewSelect>>", lambda _e: self._count())
        self.lbl_sel = ui.note(b, "", wrap=380)
        self.lbl_sel.pack(fill="x", pady=(S(8), 0))

        right = tk.Frame(body, bg=C["bg"])
        right.grid(row=0, column=1, sticky="nsew")
        how = ui.Card(right, "How to run them", pad=14)
        how.pack(fill="x", pady=(0, S(12)))
        h = how.body
        ui.field_label(h, "Dates").grid(row=0, column=0, sticky="w")
        self.v_policy = tk.StringVar(value="yesterday")
        ui.Segmented(h, (("yesterday", "Yesterday"), ("today", "Today"), ("keep", "As recorded"),
                         ("date", "Choose...")), self.v_policy, padx=11).grid(row=1, column=0, sticky="w",
                                                                              pady=(S(4), S(8)))
        self.v_date = tk.StringVar(value=service.yesterday())
        ttk.Entry(h, textvariable=self.v_date, width=22).grid(row=1, column=1, sticky="w", padx=S(10))
        tk.Label(h, text="YYYYMMDD or YYYYMMDD:YYYYMMDD", font=F["tiny"], bg=C["card"],
                 fg=C["faint"]).grid(row=2, column=1, sticky="w", padx=S(10))
        ui.field_label(h, "Files").grid(row=2, column=0, sticky="w")
        self.v_export = tk.StringVar(value="xlsx")
        ui.Segmented(h, (("xlsx", "Excel"), ("csv", "CSV only")), self.v_export,
                     padx=11).grid(row=3, column=0, sticky="w", pady=(S(4), S(8)))
        ui.field_label(h, "Save the files in", "empty = a new batch_<time> folder").grid(row=4, column=0,
                                                                                          sticky="w")
        out = tk.Frame(h, bg=C["card"])
        out.grid(row=5, column=0, columnspan=2, sticky="we", pady=(S(4), S(10)))
        h.grid_columnconfigure(1, weight=1)
        self.v_out = tk.StringVar()
        ttk.Entry(out, textvariable=self.v_out).pack(side="left", fill="x", expand=True)
        ui.FlatButton(out, "Browse", command=self._browse, kind="secondary", font=F["label"],
                      padx=12, pady=5).pack(side="left", padx=(S(8), 0))
        btns = tk.Frame(h, bg=C["card"])
        btns.grid(row=6, column=0, columnspan=2, sticky="w")
        self.btn_plan = ui.FlatButton(btns, "Plan (no browser)", command=self.make_plan, kind="secondary",
                                      padx=14, pady=8)
        self.btn_plan.pack(side="left")
        self.btn_run = ui.FlatButton(btns, "▶  Run", command=self.run, kind="success",
                                     font=F["button_lg"], padx=22, pady=9)
        self.btn_run.pack(side="left", padx=(S(10), 0))

        res = ui.Card(right, "Plan and results", pad=14)
        res.pack(fill="both", expand=True)
        r = res.body
        self.banner = ui.Banner(r, "Choose screens on the left, then Plan or Run.", "info", wrap=620)
        self.banner.pack(fill="x", pady=(0, S(10)))
        self.result = ui.Table(r, (("code", "Screen", 100, "w"), ("dates", "Dates", 140, "w"),
                                   ("status", "Status", 110, "w"), ("rows", "Rows", 70, "e"),
                                   ("detail", "Detail", 320, "w")), height=10, stretch="detail")
        self.result.pack(fill="both", expand=True)
        links = tk.Frame(r, bg=C["card"])
        links.pack(fill="x", pady=(S(8), 0))
        ui.FlatButton(links, "Open the summary", command=self._open_summary, kind="ghost",
                      font=F["label"], padx=8, pady=3).pack(side="left")
        ui.FlatButton(links, "Open the files", command=self._open_files, kind="ghost",
                      font=F["label"], padx=8, pady=3).pack(side="left")
        self.last = None

    def on_show(self, **_kw):
        self.refresh()

    def on_busy(self, busy):
        self.btn_run.set_enabled(not busy)

    def refresh(self):
        cards = [c for c in service.library() if c["recorded"]]
        self.table.fill([({"code": c["code"], "title": c["title"], "replays": c["replays"]}, "")
                         for c in cards], iid_key="code")
        names = sorted(service.batches())
        self.cmb_batch.configure(values=names)
        self.recorded_count = len(cards)
        self._count()

    def _count(self):
        n = len(self.table.selected())
        if not getattr(self, "recorded_count", 0):
            self.lbl_sel.configure(text="Nothing is recorded on this PC yet - record a screen first, or "
                                        "import recordings on the Reports page.")
            return
        self.lbl_sel.configure(text=f"{n} chosen" if n else "Nothing chosen yet.")

    def _browse(self):
        folder = filedialog.askdirectory(title="Save the files in", parent=self.app)
        if folder:
            self.v_out.set(os.path.normpath(folder))

    def _policy(self):
        p = self.v_policy.get()
        return self.v_date.get().strip() if p == "date" else p

    def load_batch(self):
        b = service.batches().get(self.v_batch.get())
        if not b:
            return
        self.table.tree.selection_set([c for c in b["screens"] if self.table.tree.exists(c)])
        missing = [c for c in b["screens"] if not self.table.tree.exists(c)]
        pol = b.get("date") or "yesterday"
        if pol in ("yesterday", "today", "keep"):
            self.v_policy.set(pol)
        else:
            self.v_policy.set("date")
            self.v_date.set(pol)
        self.v_export.set("csv" if b.get("export") == "csv" else "xlsx")   # "both" = Excel (98.1)
        self.v_out.set(b.get("output_dir") or "")
        if missing:
            self.app.log(f"Batch {self.v_batch.get()}: not recorded here - {', '.join(missing)}", "warn")

    def save_batch(self):
        codes = self.table.selected()
        if not codes:
            ui.tell(self.app, "Choose screens", "Choose the screens of the batch first.", icon="info")
            return
        name = ask_text(self.app, "Save as batch", "A name - letters, digits, - or _", self.v_batch.get())
        if not name:
            return
        try:
            service.save_batch(name, codes, self._policy(), self.v_export.get(), self.v_out.get().strip())
        except (ValueError, service.Problem) as e:
            ui.tell(self.app, "Not saved", str(e), icon="warn")
            return
        self.app.log(f"Saved batch '{name}' ({len(codes)} screens, {self._policy()}).", "ok")
        self.refresh()
        self.v_batch.set(name)

    def delete_batch(self):
        name = self.v_batch.get()
        if not name:
            return
        if not ui.ask(self.app, f"Delete batch '{name}'?", "Only the saved list is removed; recordings "
                      "and files stay. A schedule that runs it will fail until the batch exists again.",
                      yes="Delete", kind="danger", icon="warn"):
            return
        service.delete_batch(name)
        self.v_batch.set("")
        self.refresh()

    def _show_plan(self, the_plan):
        rows = []
        for item in the_plan:
            rows.append(({"code": item.code, "dates": item.dates or "-",
                          "status": "ready" if item.ready else "skipped",
                          "rows": "", "detail": item.blocked or "; ".join(item.notes) or "ready"},
                         "" if item.ready else "warn"))
        self.result.fill(rows, iid_key="code")

    def make_plan(self):
        codes = self.table.selected()
        if not codes:
            return None
        try:
            the_plan = service.plan(codes, self._policy(), self.v_export.get(), self.v_out.get().strip() or None)
        except (ValueError, service.Problem) as e:
            ui.tell(self.app, "Check the dates", str(e), icon="warn")
            return None
        self._show_plan(the_plan)
        ready = sum(1 for i in the_plan if i.ready)
        self.banner.set(f"Plan: {ready} ready, {len(the_plan) - ready} skipped (the reason is on its line). "
                        "Nothing was run.", "info" if ready else "warn")
        return the_plan

    def run_codes(self, codes, policy):
        """Run screens chosen on the Reports page."""
        self.app.show("batch")
        self.table.tree.selection_set([c for c in codes if self.table.tree.exists(c)])
        if policy in ("yesterday", "today", "keep"):
            self.v_policy.set(policy)
        self.run(confirm=False)

    def run(self, confirm=True):
        the_plan = self.make_plan()
        if not the_plan:
            return
        ready = [i for i in the_plan if i.ready]
        if not ready:
            return
        policy, export = self._policy(), self.v_export.get()
        out_dir = self.v_out.get().strip() or os.path.join(
            service.core.OUTPUT_DIR, f"batch_{datetime.now():%Y%m%d_%H%M%S}")
        if confirm and not ui.ask(self.app, f"Run {len(ready)} screen(s)?",
                                  "One after another in one browser session; each is checked on its own, "
                                  "and a report is written at the end. Stop is always one click away.",
                                  yes="▶  Run", kind="success",
                                  details=[("Dates", policy), ("Files", export), ("Folder", out_dir)]):
            return
        self.out_dir = out_dir

        def on_start(code):
            self.app.call_soon(self.result.set_cell, code, "status", "running...", "info")

        def on_result(code, out):
            ok = out.get("ok")
            self.app.call_soon(self.result.set_cell, code, "status", "ok" if ok else "FAILED",
                               "ok" if ok else "err")
            self.app.call_soon(self.result.set_cell, code, "rows", f"{int(out.get('rows') or 0):,}")
            detail = (", ".join(os.path.basename(f) for f in out.get("files", [])) if ok
                      else service.plain(out.get("error") or ""))
            self.app.call_soon(self.result.set_cell, code, "detail", detail)

        batch_name = self.v_batch.get() or None     # read here: Tk is touched only on its own thread

        def work(stop, log):
            return service.run_plan(self.app.session, the_plan, policy, export, out_dir, log=log,
                                    stop_event=stop, batch_name=batch_name,
                                    on_start=on_start, on_result=on_result)
        self.banner.set(f"Running {len(ready)} screen(s)...", "info")
        self.app.run_task(f"Run {len(ready)} screen(s)", work, self._done)

    def _done(self, outcome):
        self.last = outcome
        counts = outcome["counts"]
        for r in outcome["results"]:
            if r["status"] != "ok":
                self.result.set_cell(r["screen"], "status", r["status"].replace("_", " "),
                                     "err" if r["status"] == "failed" else "warn")
                self.result.set_cell(r["screen"], "detail", service.plain(r.get("error") or ""))
        total = len(outcome["results"])
        tone = "ok" if counts.get("ok") == total else ("warn" if counts.get("ok") else "err")
        self.banner.set(f"{counts.get('ok', 0)} of {total} delivered"
                        + (f", {counts.get('failed', 0)} failed" if counts.get("failed") else "")
                        + (f", {counts.get('not_run', 0)} not run" if counts.get("not_run") else "")
                        + (f", {counts.get('blocked', 0)} skipped" if counts.get("blocked") else "")
                        + ("  -  stopped by you" if outcome.get("stopped") else "")
                        + ".  The report is in History.", tone)
        self.app.pages["reports"].refresh()

    def _open_summary(self):
        if self.last and (self.last.get("summary") or self.last.get("report")):
            self.app.open_path(self.last.get("summary") or self.last.get("report"))

    def _open_files(self):
        path = getattr(self, "out_dir", "")
        if path and os.path.isdir(path):
            self.app.open_path(path)


def ask_text(parent, title, prompt, default=""):
    """A one-line question in the app's own style. Returns the text or None."""
    top = tk.Toplevel(parent)
    top.withdraw()
    top.title(title)
    top.configure(bg=C["card"])
    top.transient(parent)
    top.resizable(False, False)
    tk.Label(top, text=title, font=F["card_title"], bg=C["card"], fg=C["text"]).pack(
        anchor="w", padx=S(22), pady=(S(18), S(4)))
    tk.Label(top, text=prompt, font=F["small"], bg=C["card"], fg=C["muted"]).pack(anchor="w", padx=S(22))
    var = tk.StringVar(value=default)
    e = ttk.Entry(top, textvariable=var, width=36)
    e.pack(padx=S(22), pady=S(12), fill="x")
    out = {"v": None}

    def ok(_e=None):
        out["v"] = var.get().strip() or None
        top.destroy()
    row = tk.Frame(top, bg=C["card"])
    row.pack(fill="x", padx=S(22), pady=(0, S(16)))
    ui.FlatButton(row, "OK", command=ok, kind="primary").pack(side="right")
    ui.FlatButton(row, "Cancel", command=top.destroy, kind="secondary").pack(side="right", padx=S(8))
    top.bind("<Return>", ok)
    top.bind("<Escape>", lambda _e: top.destroy())
    top.update_idletasks()
    top.geometry(f"+{parent.winfo_rootx() + parent.winfo_width() // 2 - top.winfo_reqwidth() // 2}"
                 f"+{parent.winfo_rooty() + parent.winfo_height() // 3}")
    top.deiconify()
    top.grab_set()
    e.focus_set()
    top.wait_window(top)
    return out["v"]
