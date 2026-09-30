"""Samir Export - the window.

    1. Connect & load rows   (sign in, open the screen, Inquiry, count rows)
    2. choose what to export (grids, link, file names)
    3. choose how many, press START.  STOP is always one click away.

Also:  SamirExport.exe --cli <options>   runs the same engine without a window,
       SamirExport.exe --selftest        checks that everything needed is present.
"""
import os
import queue
import sys
import threading
import time
import traceback
from datetime import datetime

import samir_env

if samir_env.FROZEN and sys.stdout is None:          # a windowed .exe has no console
    os.makedirs(os.path.join(samir_env.data_dir(), "logs"), exist_ok=True)
    _sink = open(os.path.join(samir_env.data_dir(), "logs", "console.txt"), "a", buffering=1,
                 encoding="utf-8")
    sys.stdout = sys.stderr = _sink

samir_env.setup()

import json                                   # noqa: E402
import tkinter as tk                          # noqa: E402
from tkinter import filedialog, messagebox, ttk   # noqa: E402

import cdp_common                             # noqa: E402
import gmes_credentials                       # noqa: E402
import samir_runner as sr                     # noqa: E402

SETTINGS_FILE = os.path.join(samir_env.data_dir(), "settings.json")
LOG_FILE = os.path.join(samir_env.data_dir(), "logs", f"samir_{datetime.now():%Y%m%d}.log")
TITLE = "Samir Export - G-MES Detail Inspection"


def load_saved():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as fh:
            return sr.Settings.from_dict(json.load(fh))
    except (OSError, ValueError):
        return sr.Settings()


def fmt_eta(seconds):
    if seconds <= 0:
        return "-"
    h, rest = divmod(int(seconds), 3600)
    m, s = divmod(rest, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"


class CredentialsDialog(tk.Toplevel):
    """Asks for the person's own G-MES login; it is stored by the engine's own
    Windows-encrypted store (readable only by this Windows account on this PC)."""

    def __init__(self, parent, default_user="", note=""):
        super().__init__(parent)
        self.title("Save your G-MES login")
        self.resizable(False, False)
        self.transient(parent)
        self.result = None
        ttk.Label(self, justify="left", foreground="#444",
                  text=(note + "\n" if note else "") +
                       "Your login is encrypted with your Windows account key\n"
                       "and can only be read back by you, on this PC.").grid(
            row=0, column=0, columnspan=2, padx=12, pady=(12, 8), sticky="w")
        self.user, self.pw1, self.pw2 = tk.StringVar(value=default_user), tk.StringVar(), tk.StringVar()
        for r, (label, var, show) in enumerate((("Knox / G-MES user ID:", self.user, ""),
                                                ("Password:", self.pw1, "*"),
                                                ("Password again:", self.pw2, "*")), start=1):
            ttk.Label(self, text=label).grid(row=r, column=0, padx=12, pady=4, sticky="e")
            ttk.Entry(self, textvariable=var, show=show, width=30).grid(row=r, column=1, padx=12, pady=4)
        row = ttk.Frame(self)
        row.grid(row=4, column=0, columnspan=2, pady=(8, 12))
        ttk.Button(row, text="Save", command=self._save).pack(side="left", padx=6)
        ttk.Button(row, text="Cancel", command=self.destroy).pack(side="left", padx=6)
        self.bind("<Return>", lambda _e: self._save())
        self.grab_set()
        self.wait_window(self)

    def _save(self):
        user, a, b = self.user.get().strip(), self.pw1.get(), self.pw2.get()
        if not user or not a:
            messagebox.showwarning("Missing", "Enter the user ID and the password.", parent=self)
        elif a != b:
            messagebox.showwarning("Mismatch", "The two passwords do not match.", parent=self)
        else:
            self.result = (user, a)
            self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(TITLE)
        self.geometry("980x800")
        self.minsize(900, 700)
        self.saved = load_saved()
        self.runner = None
        self.state = "idle"                     # idle | loading | loaded | running
        self.q = queue.Queue()
        self.worker = None
        self._build()
        self.after(100, self._pump)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._log("Ready. Step 1: check the filters, then press 'Connect & load rows'.")

    # ---- layout ---------------------------------------------------------
    def _build(self):
        s = self.saved
        pad = {"padx": 8, "pady": 3}
        top = ttk.LabelFrame(self, text="1. Filters  (what G-MES should show)")
        top.pack(fill="x", padx=10, pady=(10, 4))
        self.v_div = tk.StringVar(value=s.division)
        self.v_mode = tk.StringVar(value=s.period_mode)
        self.v_period = tk.StringVar(value=s.period)
        self.v_filters = tk.StringVar(value="; ".join(s.extra_filters))
        ttk.Label(top, text="Division / Org:").grid(row=0, column=0, sticky="e", **pad)
        ttk.Entry(top, textvariable=self.v_div, width=22).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(top, text="Period:").grid(row=0, column=2, sticky="e", **pad)
        ttk.Radiobutton(top, text="Monthly", value="Monthly", variable=self.v_mode,
                        command=self._mode_changed).grid(row=0, column=3, **pad)
        ttk.Radiobutton(top, text="Daily", value="Daily", variable=self.v_mode,
                        command=self._mode_changed).grid(row=0, column=4, **pad)
        self.period_entry = ttk.Entry(top, textvariable=self.v_period, width=12)
        self.period_entry.grid(row=0, column=5, **pad)
        self.period_hint = ttk.Label(top, foreground="#666")
        self.period_hint.grid(row=0, column=6, sticky="w", **pad)
        ttk.Label(top, text="Extra filters:").grid(row=1, column=0, sticky="e", **pad)
        ttk.Entry(top, textvariable=self.v_filters, width=70).grid(row=1, column=1, columnspan=5,
                                                                  sticky="we", **pad)
        ttk.Label(top, text='Name=Value; Name=Value   e.g.  Model=UA65M70;  SN No.=123',
                  foreground="#666").grid(row=2, column=1, columnspan=6, sticky="w", padx=8)
        self.btn_load = ttk.Button(top, text="Connect and load rows", command=self._on_load)
        self.btn_load.grid(row=0, column=7, rowspan=2, padx=10, sticky="ns")
        self.lbl_loaded = ttk.Label(top, text="Not loaded yet.", font=("Segoe UI", 10, "bold"))
        self.lbl_loaded.grid(row=3, column=0, columnspan=8, sticky="w", padx=8, pady=(4, 6))

        mid = ttk.LabelFrame(self, text="2. What to export")
        mid.pack(fill="x", padx=10, pady=4)
        self.v_grid = tk.StringVar(value=s.result_grid)
        self.v_linkcol = tk.StringVar(value=s.link_column)
        self.v_linkval = tk.StringVar(value=s.link_value)
        self.v_dlg = tk.StringVar(value=", ".join(s.dialog_grids))
        self.v_single = tk.StringVar(value={True: "Yes", False: "No", None: "Leave as it opens"}[s.single_file])
        self.v_pattern = tk.StringVar(value=s.name_pattern)
        self.v_skip = tk.BooleanVar(value=s.skip_existing)
        rows = (("Result grid:", self.v_grid, 18, "the table whose rows are clicked"),
                ("Click the text in column:", self.v_linkcol, 18, "the link column"),
                ("Only rows showing:", self.v_linkval, 12, "e.g. PASS - other rows are left alone"),
                ("Grids to save in Excel:", self.v_dlg, 40, "names in the 'Save to Excel' list, comma separated; "
                                                            "all others are unticked"))
        for r, (label, var, width, hint) in enumerate(rows):
            ttk.Label(mid, text=label).grid(row=r, column=0, sticky="e", **pad)
            ttk.Entry(mid, textvariable=var, width=width).grid(row=r, column=1, sticky="w", **pad)
            ttk.Label(mid, text=hint, foreground="#666").grid(row=r, column=2, sticky="w", **pad)
        ttk.Label(mid, text="Save a single file:").grid(row=4, column=0, sticky="e", **pad)
        ttk.Combobox(mid, textvariable=self.v_single, width=18, state="readonly",
                     values=["Yes", "No", "Leave as it opens"]).grid(row=4, column=1, sticky="w", **pad)
        ttk.Label(mid, text="File name:").grid(row=5, column=0, sticky="e", **pad)
        ttk.Entry(mid, textvariable=self.v_pattern, width=40).grid(row=5, column=1, columnspan=1, sticky="w", **pad)
        ttk.Label(mid, text="{plan} {model} {lot}  - a file is never overwritten",
                  foreground="#666").grid(row=5, column=2, sticky="w", **pad)
        ttk.Checkbutton(mid, text="Skip rows whose file already exists (lets you resume)",
                        variable=self.v_skip).grid(row=6, column=1, columnspan=2, sticky="w", **pad)

        low = ttk.LabelFrame(self, text="3. How many, and where")
        low.pack(fill="x", padx=10, pady=4)
        self.v_start = tk.StringVar(value=str(s.start_row))
        self.v_count = tk.StringVar(value=str(s.count))
        self.v_out = tk.StringVar(value=s.out_dir)
        self.v_onerr = tk.StringVar(value=s.on_error)
        self.v_pause = tk.StringVar(value=str(s.pause_between))
        ttk.Label(low, text="Start at row No.:").grid(row=0, column=0, sticky="e", **pad)
        ttk.Entry(low, textvariable=self.v_start, width=8).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(low, text="Number of rows:").grid(row=0, column=2, sticky="e", **pad)
        ttk.Entry(low, textvariable=self.v_count, width=8).grid(row=0, column=3, sticky="w", **pad)
        ttk.Label(low, text="(0 = all the rest)", foreground="#666").grid(row=0, column=4, sticky="w", **pad)
        ttk.Label(low, text="On error:").grid(row=0, column=5, sticky="e", **pad)
        ttk.Combobox(low, textvariable=self.v_onerr, width=6, state="readonly",
                     values=["stop", "skip"]).grid(row=0, column=6, sticky="w", **pad)
        ttk.Label(low, text="Pause between rows (s):").grid(row=0, column=7, sticky="e", **pad)
        ttk.Entry(low, textvariable=self.v_pause, width=5).grid(row=0, column=8, sticky="w", **pad)
        ttk.Label(low, text="Save files in:").grid(row=1, column=0, sticky="e", **pad)
        ttk.Entry(low, textvariable=self.v_out, width=78).grid(row=1, column=1, columnspan=7, sticky="we", **pad)
        ttk.Button(low, text="Browse...", command=self._browse).grid(row=1, column=8, **pad)
        ttk.Label(low, text="(empty = Mr.Samir\\data\\output\\<screen>_<period>)", foreground="#666").grid(
            row=2, column=1, columnspan=7, sticky="w", padx=8)

        ctl = ttk.Frame(self)
        ctl.pack(fill="x", padx=10, pady=6)
        self.btn_start = ttk.Button(ctl, text="START", command=self._on_start, state="disabled")
        self.btn_start.pack(side="left", padx=4, ipadx=16, ipady=4)
        self.btn_pause = ttk.Button(ctl, text="Pause", command=self._on_pause, state="disabled")
        self.btn_pause.pack(side="left", padx=4, ipady=4)
        self.btn_stop = tk.Button(ctl, text="STOP", command=self._on_stop, state="disabled",
                                  bg="#c62828", fg="white", activebackground="#8e0000",
                                  activeforeground="white", font=("Segoe UI", 10, "bold"), width=10)
        self.btn_stop.pack(side="left", padx=(16, 4), ipady=3)
        self.btn_now = tk.Button(ctl, text="STOP NOW (close browser)", command=self._on_stop_now,
                                 state="disabled", bg="#6d0000", fg="white",
                                 activebackground="#3e0000", activeforeground="white")
        self.btn_now.pack(side="left", padx=4, ipady=3)
        ttk.Button(ctl, text="Open output folder", command=self._open_out).pack(side="right", padx=4)

        prog = ttk.Frame(self)
        prog.pack(fill="x", padx=10)
        self.bar = ttk.Progressbar(prog, mode="determinate")
        self.bar.pack(fill="x")
        self.lbl_prog = ttk.Label(prog, text="")
        self.lbl_prog.pack(anchor="w", pady=(2, 4))

        logf = ttk.Frame(self)
        logf.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.log_text = tk.Text(logf, height=12, wrap="word", state="disabled", font=("Consolas", 9))
        sb = ttk.Scrollbar(logf, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for var in (self.v_div, self.v_mode, self.v_period, self.v_filters, self.v_grid, self.v_linkcol,
                    self.v_linkval):
            var.trace_add("write", lambda *_a: self._filters_changed())
        self._mode_changed(initial=True)

    # ---- helpers --------------------------------------------------------
    def _log(self, text):
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"{stamp}  {text}"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        try:
            os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    def _post(self, kind, **kw):
        self.q.put((kind, kw))

    def _pump(self):
        try:
            while True:
                kind, kw = self.q.get_nowait()
                getattr(self, "_on_" + kind + "_msg")(**kw)
        except queue.Empty:
            pass
        self.after(100, self._pump)

    def _mode_changed(self, initial=False):
        mode = self.v_mode.get()
        example = sr.default_period(mode)
        self.period_hint.configure(text=f"empty = now ({example}); type e.g. "
                                        f"{'202610' if mode == 'Monthly' else '20261001'}")
        if not initial:
            self.v_period.set("")

    def _filters_changed(self):
        if self.state == "loaded":
            self._set_state("idle")
            self.lbl_loaded.configure(text="Filters changed - load the rows again (step 1).")

    def _set_state(self, state):
        self.state = state
        running = state in ("loading", "running")
        self.btn_load.configure(state="disabled" if running else "normal")
        self.btn_start.configure(state="normal" if state == "loaded" else "disabled")
        self.btn_pause.configure(state="normal" if state == "running" else "disabled", text="Pause")
        self.btn_stop.configure(state="normal" if running else "disabled")
        self.btn_now.configure(state="normal" if running else "disabled")

    def _browse(self):
        folder = filedialog.askdirectory(title="Save the Excel files in")
        if folder:
            self.v_out.set(folder)

    def _open_out(self):
        path = (self.runner.out_dir if self.runner and self.runner.out_dir else self.v_out.get().strip()
                or os.path.join(samir_env.data_dir(), "output"))
        os.makedirs(path, exist_ok=True)
        os.startfile(path)                                   # noqa: S606 - the person's own folder

    def _collect(self, start_ok=False):
        """Settings from the fields, or raise ValueError with what to fix."""
        def num(var, name, kind=int):
            try:
                return kind(str(var.get()).strip() or 0)
            except ValueError:
                raise ValueError(f"{name} must be a number.") from None
        filters = [f.strip() for f in self.v_filters.get().split(";") if f.strip()]
        single = {"Yes": True, "No": False}.get(self.v_single.get())
        s = sr.Settings(
            division=self.v_div.get().strip(), period_mode=self.v_mode.get(),
            period=self.v_period.get().strip(), extra_filters=filters,
            result_grid=self.v_grid.get().strip(), link_column=self.v_linkcol.get().strip(),
            link_value=self.v_linkval.get().strip(),
            dialog_grids=[g.strip() for g in self.v_dlg.get().split(",") if g.strip()],
            single_file=single, name_pattern=self.v_pattern.get().strip(),
            skip_existing=self.v_skip.get(), start_row=num(self.v_start, "Start row"),
            count=num(self.v_count, "Number of rows"), out_dir=self.v_out.get().strip(),
            on_error=self.v_onerr.get(), pause_between=num(self.v_pause, "Pause", float))
        problems = sr.validate_settings(s)
        if problems:
            raise ValueError("\n".join(problems))
        return s

    def _save_settings(self, s):
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
                fh.write(s.to_json())
        except OSError:
            pass

    # ---- credentials ----------------------------------------------------
    def _ensure_credentials(self):
        user, _pw = gmes_credentials.load()
        if user:
            return True
        problem = gmes_credentials.LAST_PROBLEM
        if problem and not messagebox.askyesno(
                "Saved login cannot be used",
                f"{problem}.\n\nEnter your login again and replace it?", parent=self):
            return False
        dlg = CredentialsDialog(self, note="No G-MES login is saved for this Windows account yet.")
        if not dlg.result:
            return False
        gmes_credentials.save(*dlg.result)
        self._log("Your login was saved (encrypted for this Windows account).")
        return True

    # ---- step 1: connect and load --------------------------------------
    def _on_load(self):
        try:
            s = self._collect()
        except ValueError as e:
            messagebox.showwarning("Check the fields", str(e), parent=self)
            return
        if not self._ensure_credentials():
            return
        self._save_settings(s)
        self._set_state("loading")
        self.lbl_loaded.configure(text="Connecting to G-MES... (the first time this takes a minute)")
        if self.runner is not None:
            self.runner.close()
        self.runner = sr.Runner(s, log=lambda m: self._post("log", text=m))
        self.worker = threading.Thread(target=self._load_worker, daemon=True)
        self.worker.start()

    def _load_worker(self):
        r = self.runner
        try:
            r.connect()
            total, counts = r.load()
            self._post("loaded", total=total, counts=counts)
        except sr.StopRequested:
            self._post("failed", text="Stopped.")
        except (sr.FatalError, ValueError) as e:
            self._post("failed", text=str(e))
        except Exception as e:                               # noqa: BLE001
            self._post("failed", text=f"{type(e).__name__}: {e}")
            self._post("log", text=traceback.format_exc())

    def _on_log_msg(self, text):
        self._log(text)

    def _on_loaded_msg(self, total, counts):
        wanted = self.runner.s.link_value
        n = counts.get(wanted, total) if counts else total
        detail = "  ·  ".join(f"{k or '(blank)'}: {v}" for k, v in counts.items()) if counts else ""
        self.lbl_loaded.configure(text=f"Loaded {total} rows.   {detail}   ->   {n} rows can be exported.")
        self._set_state("loaded")

    def _on_failed_msg(self, text):
        self._log(f"PROBLEM: {text}")
        self.lbl_loaded.configure(text="Problem - see the log below.")
        self._set_state("idle")
        messagebox.showerror("Stopped", text, parent=self)

    # ---- step 3: run ----------------------------------------------------
    def _on_start(self):
        try:
            s = self._collect()
        except ValueError as e:
            messagebox.showwarning("Check the fields", str(e), parent=self)
            return
        loaded = self.runner.s
        if (s.division, s.period_mode, s.period, s.extra_filters, s.result_grid) != \
                (loaded.division, loaded.period_mode, loaded.period, loaded.extra_filters, loaded.result_grid):
            messagebox.showwarning("Load again", "The filters changed after the rows were loaded.", parent=self)
            self._set_state("idle")
            return
        self.runner.s = s
        self._save_settings(s)
        n = s.count or "all the remaining"
        if not messagebox.askyesno("Start", f"Export {n} rows starting at row {s.start_row}?\n\n"
                                            "You can press STOP at any moment.", parent=self):
            return
        self.bar.configure(value=0)
        self.lbl_prog.configure(text="Starting...")
        self._set_state("running")
        self.runner.progress = lambda **kw: self._post("progress", **kw)
        self.worker = threading.Thread(target=self._run_worker, daemon=True)
        self.worker.start()

    def _run_worker(self):
        try:
            self._post("done", summary=self.runner.run())
        except Exception as e:                               # noqa: BLE001
            self._post("failed", text=f"{type(e).__name__}: {e}")
            self._post("log", text=traceback.format_exc())

    def _on_progress_msg(self, done, total, ok, skipped, failed, row, eta):
        self.bar.configure(maximum=total, value=done)
        self.lbl_prog.configure(text=f"{done}/{total}   row {row}   ok {ok}   skipped {skipped}   "
                                     f"failed {failed}   time left ~ {fmt_eta(eta)}")

    def _on_done_msg(self, summary):
        text = (f"Finished: {summary['ok']} exported, {summary['skipped']} skipped, "
                f"{summary['failed']} failed of {summary['planned']}.")
        if summary["stopped"]:
            text = "STOPPED by you. " + text
        if summary["fatal"]:
            text = "STOPPED: " + summary["fatal"] + "  " + text
        self.lbl_prog.configure(text=text)
        self._log(text)
        if summary.get("csv"):
            self._log(f"Result list: {summary['csv']}")
        self._set_state("loaded" if self.runner and self.runner.ws is not None else "idle")
        if summary["fatal"]:
            messagebox.showerror("Stopped", summary["fatal"], parent=self)

    def _on_pause(self):
        if not self.runner:
            return
        if self.btn_pause.cget("text") == "Pause":
            self.runner.pause()
            self.btn_pause.configure(text="Resume")
            self._log("Paused (the current file finishes first).")
        else:
            self.runner.resume()
            self.btn_pause.configure(text="Pause")
            self._log("Resumed.")

    def _on_stop(self):
        if self.runner:
            self.runner.request_stop()
            self.runner.resume()
            self.btn_stop.configure(state="disabled")
            self._log("STOP pressed - stopping after the current click (a second or two)...")

    def _on_stop_now(self):
        self._log("STOP NOW - closing the automation browser.")
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
        if self.state in ("loading", "running"):
            if not messagebox.askyesno("Quit", "A run is active. Stop it and quit?", parent=self):
                return
            if self.runner:
                self.runner.request_stop()
                self.runner.resume()
            if self.worker:
                self.worker.join(timeout=8)
        if self.runner:
            self.runner.close()
        try:
            cdp_common.stop_if_started_here(False)          # only a browser THIS program opened
        except Exception:                                    # noqa: BLE001
            pass
        self.destroy()


def selftest():
    import sync_engine
    print("Samir Export self-test")
    print("  data folder :", samir_env.data_dir())
    print("  engine ok   :", sr.core.__name__, "/", cdp_common.__name__)
    print("  credentials :", "saved" if gmes_credentials.load()[0] else "not saved yet (asked on first Connect)")
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
