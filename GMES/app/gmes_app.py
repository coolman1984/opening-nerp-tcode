"""GMES Automation - the window.

    Reports      every recorded screen: status, last run, record check; run, re-record
    Record       any UI number: find, describe, choose scope, record + full record check
    Run & Batch  several screens in one browser session; save as a named batch
    Schedules    run a saved batch every day / on weekdays (Windows Task Scheduler)
    Row export   one Excel per row of a list (double-click a cell -> popup -> Excel)
    History      every run report; support package; self-test
    Account      the person's own G-MES login and which browser profile is used

Headless:   GMES_Automation.exe --batch NAME [--unattended]   (what a schedule runs)
            GMES_Automation.exe --selftest
"""
import os
import queue
import re
import sys
import threading
import traceback
from datetime import datetime

import app_env

if app_env.FROZEN and sys.stdout is None:            # a windowed .exe has no console
    os.makedirs(os.path.join(app_env.data_dir(), "logs"), exist_ok=True)
    _console = open(os.path.join(app_env.data_dir(), "logs", "console.txt"), "a", buffering=1,
                    encoding="utf-8")
    sys.stdout = sys.stderr = _console

app_env.setup()

import tkinter as tk                          # noqa: E402
from collections import deque                 # noqa: E402

import app_settings                           # noqa: E402
import service                                # noqa: E402
from page_base import Page                     # noqa: E402,F401
import ui_kit as ui                           # noqa: E402
from ui_kit import C, F, S                    # noqa: E402

VERSION = "1.0"
LOG_FILE = os.path.join(app_env.data_dir(), "logs", f"app_{datetime.now():%Y%m%d}.log")
SIGNED_IN = re.compile(r"[Ss]igned in as '([^']+)'")


class OutputSink:
    """Everything the engine prints reaches the activity console as whole lines, from
    any thread, and still goes to the console file. The engine never prints a password."""

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
    if re.search(r"fail|stopped|problem|error|refus|could not|cannot|not found|gone|drifted", t):
        return "err"
    if re.search(r"\bok\b|exported|signed in as|passed|verified|ready|saved|copied|complete", t):
        return "ok"
    if re.search(r"note|warning|skipped|already exists|paused|stop pressed|first use", t):
        return "warn"
    if text.startswith(("  ", "  |")):
        return "muted"
    return "info"


def fmt_secs(seconds):
    if not seconds or seconds <= 0:
        return "-"
    h, rest = divmod(int(seconds), 3600)
    m, s = divmod(rest, 60)
    return f"{h}h {m:02d}m" if h else (f"{m}m {s:02d}s" if m else f"{s}s")


class App(tk.Tk):
    def __init__(self):
        ui.make_dpi_aware()
        super().__init__()
        ui.Split.store = (app_settings.pane, app_settings.set_pane)
        ui.setup_theme(self, app_settings.appearance())
        self.log_lines = deque(maxlen=3000)          # replayed into the console after a rebuild
        self.current = "reports"
        self.title(f"{app_env.APP_NAME}")
        self.configure(bg=C["bg"])
        self._set_icon()
        w = min(S(1440), self.winfo_screenwidth() - S(40))
        h = min(S(920), self.winfo_screenheight() - S(90))
        self.geometry(f"{w}x{h}+{max(0, (self.winfo_screenwidth() - w) // 2)}+"
                      f"{max(0, (self.winfo_screenheight() - h) // 3)}")
        self.minsize(min(S(1180), w), min(S(700), h))

        self.q = queue.Queue()
        self.busy = False
        self.task_name = ""
        self.stop_event = threading.Event()
        self.worker = None
        self.task_started = None
        self.session = service.Session(log=lambda m: self._post_log(m))

        self.sink = OutputSink(sys.stdout)
        self.sink.target = lambda line: self.q.put(("engine", line))
        sys.stdout = self.sink
        sys.stderr = self.sink

        import account
        try:
            account.apply_browser_choice(account_choice())
        except Exception:                                    # noqa: BLE001
            account.apply_browser_choice("auto")

        self._build()
        self.bind("<Escape>", lambda _e: self.stop() if self.busy else None)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._pump)
        self.after(1000, self._tick)
        self.log(f"{app_env.APP_NAME} {VERSION} - files and logs: {app_env.data_dir()}", "muted")
        self.show("reports")

    def _set_icon(self):
        for path in (app_env.resource("assets", "gmes.ico"),
                     os.path.join(app_env.HERE, "assets", "gmes.ico")):
            if os.path.isfile(path):
                try:
                    self.iconbitmap(default=path)
                except tk.TclError:
                    pass
                return

    # ---- layout -------------------------------------------------------------
    def _build(self):
        from pages_main import ReportsPage, RecordPage, BatchPage
        from pages_more import SchedulesPage, RowExportPage, HistoryPage, AccountPage

        side = tk.Frame(self, bg=C["header"],
                        width=S(int(232 * max(1.0, ui.APPEARANCE["size"] / 100.0))))
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        brand = tk.Frame(side, bg=C["header"])
        brand.pack(fill="x", padx=S(18), pady=(S(18), S(22)))
        logo = tk.Canvas(brand, width=S(38), height=S(38), bg=C["header"], highlightthickness=0)
        logo.create_rectangle(0, 0, S(38), S(38), fill=C["accent"], outline="")
        logo.create_polygon(S(38), 0, S(38), S(38), S(14), S(38), fill=C["logo2"], outline="")
        logo.create_text(S(19), S(19), text="G", fill=C["on_accent"], font=F["status"])
        logo.pack(side="left")
        names = tk.Frame(brand, bg=C["header"])
        names.pack(side="left", padx=(S(12), 0))
        tk.Label(names, text="GMES", font=F["brand"], bg=C["header"], fg="#FFFFFF",
                 anchor="w").pack(anchor="w")
        tk.Label(names, text="Automation", font=F["small"], bg=C["header"], fg=C["header_muted"],
                 anchor="w").pack(anchor="w")

        self.pages, self.nav = {}, {}
        main = tk.Frame(self, bg=C["bg"])
        main.pack(side="left", fill="both", expand=True)
        self._build_topbar(main)
        # The pages and the Activity console share the height; the person drags the gap
        # between them (double-click it to go back to the original size).
        self.vsplit = ui.Split(main, "activity", first=None, orient="vertical", tail=210)
        self.vsplit.pack(fill="both", expand=True)
        self.content = tk.Frame(self.vsplit, bg=C["bg"])
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)
        self.vsplit.add(self.content, minsize=280, stretch="always")
        self.vsplit.add(self._build_activity(self.vsplit), minsize=44, stretch="never")

        from pages_settings import AppearancePage
        groups = (("WORK", (("reports", "▤", "Reports", ReportsPage),
                            ("record", "●", "Record a screen", RecordPage),
                            ("batch", "▶", "Run & Batch", BatchPage),
                            ("schedules", "◷", "Schedules", SchedulesPage),
                            ("rowexport", "≡", "Row export", RowExportPage))),
                  ("SYSTEM", (("history", "↺", "History", HistoryPage),
                              ("account", "◉", "Account & Browser", AccountPage),
                              ("appearance", "◐", "Appearance", AppearancePage))))
        for group, items in groups:
            tk.Label(side, text=group, font=F["tiny"], bg=C["header"], fg=C["nav_group"],
                     anchor="w").pack(fill="x", padx=S(22), pady=(S(10), S(4)))
            for key, glyph, text, cls in items:
                item = ui.NavItem(side, glyph, text, command=lambda k=key: self.show(k))
                item.pack(fill="x")
                self.nav[key] = item
                page = cls(self, self.content)
                page.grid(row=0, column=0, sticky="nsew")
                self.pages[key] = page
        tk.Label(side, text=f"v{VERSION}  ·  read-only in G-MES", font=F["tiny"], bg=C["header"],
                 fg=C["nav_group"]).pack(side="bottom", pady=S(14))
        if app_settings.load().get("activity_folded"):
            self.after_idle(self._fold)

    def _build_topbar(self, main):
        bar = tk.Frame(main, bg=C["card"], height=S(54))
        bar.pack(fill="x")
        bar.pack_propagate(False)
        tk.Frame(main, bg=C["border"], height=1).pack(fill="x")
        self.lbl_task = tk.Label(bar, text="", font=F["label"], bg=C["card"], fg=C["text"], anchor="w")
        self.lbl_task.pack(side="left", padx=S(24))
        self.btn_stop = ui.FlatButton(bar, "■  Stop", command=self.stop, kind="danger",
                                      font=F["button"], padx=16, pady=6)
        self.btn_stop.pack(side="right", padx=(S(8), S(20)))
        self.btn_stop.set_enabled(False)
        self.pill = ui.Pill(bar)
        self.pill.pack(side="right", padx=S(8))
        self.lbl_user = tk.Label(bar, text="", font=F["small"], bg=C["card"], fg=C["muted"])
        self.lbl_user.pack(side="right", padx=S(8))

    def _build_activity(self, parent):
        wrap = tk.Frame(parent, bg=C["bg"])
        head = tk.Frame(wrap, bg=C["bg"])
        head.pack(fill="x", padx=S(24))
        self.activity_head = head
        tk.Label(head, text="Activity", font=F["card_title"], bg=C["bg"], fg=C["text"]).pack(side="left")
        for text, cmd in (("Clear", self._clear_log), ("Log file", lambda: self.open_path(LOG_FILE)),
                          ("Data folder", lambda: self.open_path(app_env.data_dir()))):
            ui.FlatButton(head, text, command=cmd, kind="ghost", font=F["label"], padx=10,
                          pady=3).pack(side="right")
        self.activity_open = tk.BooleanVar(value=True)
        self.btn_fold = ui.FlatButton(head, "Hide", command=self._fold, kind="ghost", font=F["label"],
                                      padx=10, pady=3)
        self.btn_fold.pack(side="right")
        box = tk.Frame(wrap, bg=C["console"])
        box.pack(fill="both", expand=True, padx=S(24), pady=(S(6), S(14)))
        self.console_box = box
        self.log_text = tk.Text(box, wrap="word", state="disabled", font=F["mono"], bg=C["console"],
                                fg=C["console_text"], relief="flat", bd=0, padx=S(14), pady=S(8),
                                height=3, selectbackground=C["console_sel"])
        from tkinter import ttk
        sb = ttk.Scrollbar(box, command=self.log_text.yview, style="Console.Vertical.TScrollbar")
        self.log_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)
        for tag in ("time", "info", "muted", "ok", "warn", "err"):
            self.log_text.tag_configure(tag, foreground=C["log_" + tag])
        return wrap

    def _fold(self):
        """Hide / show the console. Hidden, only its title row stays and the pages get
        the height; the choice is remembered."""
        opening = not self.activity_open.get()
        if opening:
            self.console_box.pack(fill="both", expand=True, padx=S(24), pady=(S(6), S(14)))
            self.vsplit.pinned_tail = None
            self.btn_fold.set_text("Hide")
        else:
            self.console_box.pack_forget()
            self.update_idletasks()
            self.vsplit.pinned_tail = self.activity_head.winfo_reqheight() + S(10)
            self.btn_fold.set_text("Show")
        self.activity_open.set(opening)
        self.vsplit.place_sash()
        app_settings.save(activity_folded=not opening)

    # ---- navigation ---------------------------------------------------------
    def show(self, key, **kwargs):
        for k, item in self.nav.items():
            item.set_active(k == key)
        page = self.pages[key]
        page.tkraise()
        self.current = key
        try:
            page.on_show(**kwargs)
        except Exception as e:                               # noqa: BLE001
            self.log(f"(page problem: {type(e).__name__}: {e})", "muted")

    # ---- log ----------------------------------------------------------------
    def log(self, text, tag=None):
        text = str(text).rstrip()
        if not text:
            return
        tag = tag or classify(text)
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_lines.append((stamp, text, tag))
        self._show_line(stamp, text, tag)
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {text}\n")
        except OSError:
            pass

    def _show_line(self, stamp, text, tag):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", stamp + "  ", "time")
        self.log_text.insert("end", text + "\n", tag)
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > 5000:
            self.log_text.delete("1.0", f"{lines - 4000}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _post_log(self, text, tag=None):
        self.q.put(("log", (text, tag)))

    def _clear_log(self):
        self.log_lines.clear()
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # ---- appearance -----------------------------------------------------------
    def apply_appearance(self, **changes):
        """Save a new theme / font / text size and rebuild the window with it at once.
        Not while a task runs: the task's callbacks belong to the pages a rebuild replaces."""
        if self.busy:
            ui.tell(self, "Busy", f"'{self.task_name}' is running. Change the appearance when it ends.",
                    icon="warn")
            return False
        chosen = dict(ui.APPEARANCE)
        chosen.update(changes)
        app_settings.save(appearance=chosen)
        self.rebuild()
        return True

    def rebuild(self):
        current, user = self.current, self.lbl_user.cget("text")
        kept = {}
        for key, page in self.pages.items():
            try:
                kept[key] = page.keep()
            except Exception:                                # noqa: BLE001 - never block a rebuild
                pass
        for child in self.winfo_children():
            child.destroy()
        ui.setup_theme(self, app_settings.appearance())
        self.configure(bg=C["bg"])
        self._build()
        self.lbl_user.configure(text=user)
        alive = self.session.ws is not None
        self.pill.set("ready" if alive else "idle", "Connected" if alive else "Not connected")
        for stamp, text, tag in self.log_lines:
            self._show_line(stamp, text, tag)
        self.show(current)
        for key, state in kept.items():
            if state and key in self.pages:
                try:
                    self.pages[key].restore(state)
                except Exception as e:                       # noqa: BLE001
                    self.log(f"(could not restore the {key} page: {e})", "muted")

    def open_path(self, path):
        if not path:
            return
        try:
            os.startfile(path)                               # noqa: S606 - the person's own files
        except OSError as e:
            ui.tell(self, "Cannot open", f"{path}\n\n{e}", icon="warn")

    # ---- one task at a time ---------------------------------------------------
    def run_task(self, name, work, done=None, failed=None, needs_session=True):
        """Run `work(stop_event, log)` in a worker thread; `done(result)` / `failed(exc)`
        run on the window thread. One task at a time - the browser is one."""
        if self.busy:
            ui.tell(self, "Busy", f"'{self.task_name}' is still running. Wait for it or press Stop.",
                    icon="warn")
            return False
        self.busy, self.task_name = True, name
        self.stop_event = threading.Event()
        self.task_started = datetime.now()
        self.btn_stop.set_enabled(True)
        self.pill.set("busy", name)
        self.lbl_task.configure(text=f"{name}...")
        for page in self.pages.values():
            page.on_busy(True)

        def log(text):
            self._post_log(text)

        def body():
            try:
                if needs_session:
                    self.session.ensure(self.stop_event)
                    self.q.put(("signed_in", self.session.who))
                result = work(self.stop_event, log)
                self.q.put(("done", (done, result)))
            except service.Stopped:
                self.q.put(("failed", (failed, service.Stopped())))
            except BaseException as e:                       # noqa: BLE001
                self.q.put(("trace", traceback.format_exc()))
                self.q.put(("failed", (failed, e)))
        self.worker = threading.Thread(target=body, daemon=True)
        self.worker.start()
        return True

    def background(self, work, done=None):
        """A quick read that needs no browser (schedules, files): no Stop, no busy state."""
        def body():
            try:
                result = work()
                if done:
                    self.call_soon(done, result)
            except Exception as e:                           # noqa: BLE001
                self._post_log(f"PROBLEM: {e}", "err")
        threading.Thread(target=body, daemon=True).start()

    def stop(self):
        if self.busy:
            self.stop_event.set()
            self.btn_stop.set_enabled(False)
            self.pill.set("stop", "Stopping")
            self.log("STOP pressed - stopping at the next step (a second or two)...", "warn")
            for page in self.pages.values():
                hook = getattr(page, "on_stop", None)
                if hook:
                    hook()

    def _finish(self):
        self.busy = False
        self.btn_stop.set_enabled(False)
        alive = self.session.ws is not None
        self.pill.set("ready" if alive else "idle", "Connected" if alive else "Not connected")
        took = (datetime.now() - self.task_started).total_seconds() if self.task_started else 0
        self.lbl_task.configure(text=f"Last: {self.task_name} ({fmt_secs(took)})")
        for page in self.pages.values():
            page.on_busy(False)

    def _pump(self):
        try:
            for _ in range(400):
                try:
                    kind, payload = self.q.get_nowait()
                except queue.Empty:
                    break
                try:
                    self._handle(kind, payload)
                except Exception as e:                       # noqa: BLE001
                    self.log(f"(display problem: {type(e).__name__}: {e})", "muted")
        finally:
            self.after(80, self._pump)

    def _handle(self, kind, payload):
        if kind == "log":
            self.log(*payload)
        elif kind == "engine":
            clean = payload.strip()
            if not clean or set(clean) <= set("=-") or clean == "GMES login":
                return
            m = SIGNED_IN.search(clean)
            if m:
                self.lbl_user.configure(text=f"Signed in as {m.group(1)}")
            tag = classify(clean)
            self.log(clean, tag if tag in ("err", "ok", "warn") else "muted")
        elif kind == "signed_in":
            if payload:
                self.lbl_user.configure(text=f"Signed in as {payload}")
        elif kind == "trace":
            self.log(payload, "muted")
        elif kind == "done":
            callback, result = payload
            self._finish()
            if callback:
                callback(result)
        elif kind == "failed":
            callback, exc = payload
            self._finish()
            if isinstance(exc, service.Stopped):
                self.log("Stopped by you.", "warn")
            else:
                self.log(f"PROBLEM: {service.plain(exc)}", "err")
            if callback:
                callback(exc)
            elif not isinstance(exc, service.Stopped):
                ui.tell(self, "Something needs your attention", service.plain(exc), icon="err")
        elif kind == "call":
            fn, args = payload
            try:
                fn(*args)
            except tk.TclError:
                pass        # a quick background read finished after its page was rebuilt

    def call_soon(self, fn, *args):
        """From a worker thread: run fn on the window thread."""
        self.q.put(("call", (fn, args)))

    def _tick(self):
        if self.busy and self.task_started:
            took = (datetime.now() - self.task_started).total_seconds()
            self.lbl_task.configure(text=f"{self.task_name}...   {fmt_secs(took) if took >= 1 else '0s'}")
        self.after(1000, self._tick)

    def destroy(self):
        try:
            for after_id in self.tk.splitlist(self.tk.call("after", "info")):
                try:
                    self.after_cancel(after_id)
                except tk.TclError:
                    pass
        except tk.TclError:
            pass
        super().destroy()

    def _on_close(self):
        if self.busy:
            if not ui.ask(self, "Quit while it works?", f"'{self.task_name}' is running. Stop it and quit?",
                          yes="Stop and quit", kind="danger", icon="warn"):
                return
            self.stop_event.set()
            if self.worker:
                self.worker.join(timeout=15)
        for page in self.pages.values():
            hook = getattr(page, "on_close", None)
            if hook:
                try:
                    hook()
                except Exception:                            # noqa: BLE001
                    pass
        self.session.close()
        sys.stdout, sys.stderr = self.sink.fallback, self.sink.fallback
        self.destroy()


def account_choice():
    return app_settings.load().get("browser", "auto")


# --------------------------------------------------------------------------
def selftest():
    import account
    import sync_engine
    print(f"{app_env.APP_NAME} {VERSION} self-test")
    print("  data folder  :", app_env.data_dir())
    user, problem = account.saved_login()
    print("  login        :", f"saved ({user})" if user else (problem or "not saved yet (Account page)"))
    info = account.describe_browsers()
    found = [b["label"] for b in info["browsers"] if b["installed"]]
    print("  browsers     :", ", ".join(found) or "none found", "| default:", info["default"])
    print("  browser copy :", account.setup_sentence(info))
    print("  recordings   :", sum(1 for c in service.library() if c["recorded"]), "recorded here,",
          len(service.library()), "known")
    if not app_env.FROZEN:
        problems = sync_engine.check()
        print("  engine copy  :", "identical to the project" if not problems else problems)
    try:
        import websocket                                     # noqa: F401
        print("  websocket    : ok")
    except ImportError:
        print("  websocket    : MISSING")
        return 1
    return 0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    if "--batch" in argv:
        i = argv.index("--batch")
        if i + 1 >= len(argv):
            print("--batch needs the name of a saved batch")
            return 2
        return service.headless_batch(argv[i + 1], unattended="--unattended" in argv)
    App().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
