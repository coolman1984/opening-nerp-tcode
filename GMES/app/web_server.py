"""GMES Automation's window: a page served from THIS PC to a browser app window.

The Tk window was slow (every theme or size change rebuilt hundreds of widgets) and
its console children flashed CMD windows. Now:

    this program   one local HTTP server on 127.0.0.1 (a free port), the engine,
                   one task at a time, an event list the page reads
    the page       web/index.html + app.js + app.css, shown in a Chrome/Edge APP window
                   that runs on its own small profile (data/ui-browser) - never the
                   person's own browser profile, and never the automation browser's

Nothing but the window may use the API: every call carries a random token that only
the page we opened knows, and a request whose Host is not ours is refused (another
web page cannot drive it). The server stops by itself when the window has been closed
and nothing is running.

Standard library only (CLAUDE.md 4.6).
"""
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import asdict, is_dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import app_env

app_env.setup()

import account                                   # noqa: E402
import app_settings                              # noqa: E402
import rowexport as rx                           # noqa: E402
import service                                   # noqa: E402
import themes                                    # noqa: E402

VERSION = "2.0"
SIGNED_IN = re.compile(r"[Ss]igned in as '([^']+)'")
IDLE_EXIT_SECONDS = 45          # no window polling for this long, nothing running -> exit
POLL_WAIT_SECONDS = 20          # how long one event request waits for news


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


def jsonable(obj):
    """Anything a task returns, as JSON data (plan items, paths, dates included)."""
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if is_dataclass(obj):
        data = asdict(obj)
        if hasattr(obj, "ready"):
            data["ready"] = obj.ready
        return jsonable(data)
    return str(obj)


def plan_view(the_plan):
    return [{"code": i.code, "dates": i.dates or "", "ready": i.ready, "blocked": i.blocked or "",
             "notes": list(i.notes or [])} for i in the_plan]


def check_view(result):
    """What the page shows of a record check (the full result stays here, for a
    later confirmation)."""
    if not result:
        return None
    spread = (result.get("evidence") or {}).get("spread") or {}
    typed = service.typed_period(result["spec"])
    rec = result.get("rec") or {}
    return {"kind": result.get("kind"), "verdict": result["verdict"], "certificate": result["certificate"],
            "code": result["spec"]["screen_code"],
            "checks": [{"name": c["name"], "status": c["status"], "detail": service.plain(c["detail"]),
                        "confirmable": bool(c.get("confirmable"))} for c in result["checks"]],
            "files": list(rec.get("files") or []), "rows": rec.get("rows"),
            "confirmable": any(c.get("confirmable") for c in result["checks"]),
            "period": typed[2] if typed else "",
            "spread": {"column": spread.get("column"), "inside": spread.get("inside"),
                       "dated": spread.get("dated"), "outside": spread.get("outside") or {}}}


class Busy(Exception):
    pass


# --------------------------------------------------------------------------
# The app's state: events, the one task, the one browser session
# --------------------------------------------------------------------------
class Hub:
    def __init__(self, selftest=None):
        self.cond = threading.Condition(threading.RLock())
        self.events = []
        self.next_id = 1
        self.boot = secrets.token_hex(4)
        self.busy = False
        self.task = None
        self.stop_event = threading.Event()
        self.session = service.Session(log=self.log)
        self.runner = None                  # a loaded Row export list, kept for Start
        self.active_runner = None           # the runner of the task now running (for Stop)
        self.last_check = None              # the full last record check (for Confirm)
        self.who = ""
        self.last_poll = time.time()
        self.polling = 0
        self.selftest = selftest
        self.log_file = os.path.join(app_env.data_dir(), "logs", f"app_{datetime.now():%Y%m%d}.log")

    # ---- events -------------------------------------------------------------
    def emit(self, kind, **data):
        with self.cond:
            event = dict(data, type=kind, id=self.next_id)
            self.next_id += 1
            self.events.append(event)
            if len(self.events) > 6000:
                del self.events[:1000]
            self.cond.notify_all()
        return event

    def log(self, text, tag=None):
        text = str(text).rstrip()
        if not text:
            return
        for line in text.splitlines():
            if not line.strip():
                continue
            self.emit("log", time=datetime.now().strftime("%H:%M:%S"), text=line,
                      tag=tag or classify(line))
        try:
            with open(self.log_file, "a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {text}\n")
        except OSError:
            pass

    def engine_line(self, line):
        """A line the engine printed (sys.stdout is redirected here)."""
        clean = line.strip()
        if not clean or set(clean) <= set("=-") or clean == "GMES login":
            return
        m = SIGNED_IN.search(clean)
        if m:
            self.who = m.group(1)
            self.emit("who", who=self.who)
        tag = classify(clean)
        self.log(clean, tag if tag in ("err", "ok", "warn") else "muted")

    def events_after(self, after, wait=POLL_WAIT_SECONDS):
        with self.cond:
            self.polling += 1
            self.last_poll = time.time()
            try:
                if after >= self.next_id:            # the page knew an older server
                    return {"reset": True, "boot": self.boot, "events": []}
                self.cond.wait_for(lambda: self.next_id - 1 > after, timeout=wait)
                return {"boot": self.boot, "events": [e for e in self.events if e["id"] > after]}
            finally:
                self.polling -= 1
                self.last_poll = time.time()

    # ---- the one task -------------------------------------------------------
    def start(self, name, work, needs_session=True, view=None):
        """Run `work(stop_event, log)` in a thread. One at a time: the browser is one."""
        with self.cond:
            if self.busy:
                raise Busy(f"'{self.task['name']}' is still running. Wait for it or press Stop.")
            self.busy = True
            self.stop_event = threading.Event()
            self.task = {"id": secrets.token_hex(6), "name": name, "started": time.time()}
            task = dict(self.task)
        self.emit("task", state="start", task_id=task["id"], name=name)

        def body():
            payload = {}
            try:
                if needs_session:
                    self.session.ensure(self.stop_event)
                    self.who = self.session.who or self.who
                    self.emit("who", who=self.who)
                result = work(self.stop_event, self.log)
                payload = {"state": "done", "result": jsonable(view(result) if view else result)}
            except service.Stopped:
                self.log("Stopped by you.", "warn")
                payload = {"state": "stopped"}
            except BaseException as e:                       # noqa: BLE001
                self.log(traceback.format_exc(), "muted")
                text = service.plain(e) or type(e).__name__
                self.log(f"PROBLEM: {text}", "err")
                payload = {"state": "failed", "error": text}
            finally:
                with self.cond:
                    self.busy = False
                    self.active_runner = None
                self.emit("task", task_id=task["id"], name=name,
                          took=round(time.time() - task["started"], 1),
                          connected=self.session.ws is not None, **payload)
        threading.Thread(target=body, daemon=True, name=f"task {name}").start()
        return task["id"]

    def stop(self):
        if not self.busy:
            return False
        self.stop_event.set()
        for r in (self.active_runner, self.runner):
            if r is not None:
                r.request_stop()
                r.resume()
        self.log("STOP pressed - stopping at the next step (a second or two)...", "warn")
        return True

    def state(self):
        with self.cond:
            task = dict(self.task) if self.busy and self.task else None
        return {"version": VERSION, "boot": self.boot, "busy": self.busy, "task": task,
                "who": self.who, "connected": self.session.ws is not None,
                "data_dir": app_env.data_dir(), "last_event": self.next_id - 1}

    def close(self):
        for r in (self.runner,):
            try:
                if r is not None:
                    r.close()
            except Exception:                                # noqa: BLE001
                pass
        self.session.close()


# --------------------------------------------------------------------------
# Small Windows helpers
# --------------------------------------------------------------------------
def pick_folder(title="Choose a folder"):
    """The Windows folder picker, in front of the app window. None if cancelled."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class BROWSEINFO(ctypes.Structure):
        _fields_ = [("hwndOwner", wintypes.HWND), ("pidlRoot", ctypes.c_void_p),
                    ("pszDisplayName", wintypes.LPWSTR), ("lpszTitle", wintypes.LPCWSTR),
                    ("ulFlags", wintypes.UINT), ("lpfn", ctypes.c_void_p),
                    ("lParam", wintypes.LPARAM), ("iImage", ctypes.c_int)]
    ole32, shell32, user32 = ctypes.windll.ole32, ctypes.windll.shell32, ctypes.windll.user32
    ole32.CoInitialize(None)
    try:
        name = ctypes.create_unicode_buffer(260)
        info = BROWSEINFO(user32.GetForegroundWindow(), None, name, title,
                          0x0001 | 0x0040, None, 0, 0)        # folders only, new dialog style
        shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
        pidl = shell32.SHBrowseForFolderW(ctypes.byref(info))
        if not pidl:
            return None
        path = ctypes.create_unicode_buffer(1024)
        ok = shell32.SHGetPathFromIDListW(ctypes.c_void_p(pidl), path)
        ole32.CoTaskMemFree(ctypes.c_void_p(pidl))
        return os.path.normpath(path.value) if ok and path.value else None
    finally:
        ole32.CoUninitialize()


def open_path(path):
    if not path or not os.path.exists(path):
        raise service.Problem(f"Not found: {path}")
    os.startfile(path)                                       # noqa: S606 - the person's own files


# --------------------------------------------------------------------------
# The API
# --------------------------------------------------------------------------
class Api:
    """Every call the page makes. GET reads; POST changes or starts something."""

    def __init__(self, hub):
        self.hub = hub

    # ---- reading --------------------------------------------------------------
    def get_state(self, q):
        return self.hub.state()

    def get_events(self, q):
        return self.hub.events_after(int((q.get("after") or ["0"])[0]))

    def get_settings(self, q):
        s = app_settings.load()
        families = themes.installed_families()
        return {"appearance": themes.resolve_appearance(s.get("appearance"), families),
                "themes": themes.THEMES, "defaults": themes.APPEARANCE_DEFAULTS,
                "fonts": [f for f in themes.UI_FONTS if f in families] or ["Segoe UI"],
                "monos": [f for f in themes.MONO_FONTS if f in families] or ["Consolas"],
                "sizes": list(themes.TEXT_SIZES), "panes": s.get("panes") or {},
                "activity": s.get("activity") or {}, "rowexport": s.get("rowexport") or {},
                "browser": s.get("browser", "auto")}

    def get_library(self, q):
        cards = service.library()
        bad = service.unreadable_profiles()
        return {"cards": cards, "unreadable": [os.path.basename(p) for p, _w in bad]}

    def get_batches(self, q):
        return {"batches": service.batches()}

    def get_schedules(self, q):
        # Windows PowerShell sometimes fails to start under load ("An error occurred
        # while creating the pipeline", seen once while another browser was starting);
        # a second try a moment later answered normally.
        try:
            return {"tasks": service.schedule_list()}
        except service.gmes_schedule.ScheduleError:
            time.sleep(1.5)
            return {"tasks": service.schedule_list()}

    def get_history(self, q):
        runs = service.gmes_library.run_history()
        return {"runs": [{"path": r["path"], "started": r["started"], "name": r["name"],
                          "total": r["total"], "counts": r["counts"], "results": r["results"],
                          "summary": r.get("summary"), "output_dir": r.get("output_dir")}
                         for r in runs]}

    def get_account(self, q):
        user, problem = account.saved_login()
        info = account.describe_browsers()
        state = info.get("state") or {}
        return {"user": user, "problem": problem, "windows_user": account.windows_user(),
                "browsers": info, "sentence": account.setup_sentence(info),
                "ready": bool(state.get("completed") and info.get("same_machine")),
                "choice": app_settings.load().get("browser", "auto"),
                "labels": account.CHOICE_LABELS}

    def get_rowexport(self, q):
        saved = rx.Settings.from_dict(app_settings.load().get("rowexport", {}))
        r = self.hub.runner
        loaded = None
        if r is not None and r.rows:
            loaded = {"total": r.total, "period": r.period, "counts": r.status_counts,
                      "sorted_by": r.sorted_by}
        return {"settings": asdict(saved), "loaded": loaded}

    # ---- simple changes --------------------------------------------------------
    def post_settings(self, body):
        allowed = {k: body[k] for k in ("appearance", "panes", "activity") if k in body}
        if "appearance" in allowed:
            allowed["appearance"] = themes.resolve_appearance(allowed["appearance"],
                                                              themes.installed_families())
        app_settings.save(**allowed)
        return {"ok": True}

    def post_stop(self, body):
        return {"stopping": self.hub.stop()}

    def post_open(self, body):
        what = body.get("what")
        path = {"data": app_env.data_dir(), "log": self.hub.log_file,
                "output": app_env.sub("output")}.get(what, body.get("path"))
        open_path(path)
        return {"ok": True}

    def post_pick_folder(self, body):
        return {"path": pick_folder(body.get("title") or "Choose a folder")}

    def post_import(self, body):
        folder = body.get("folder") or pick_folder("Folder with recordings (<CODE>.json)")
        if not folder:
            return {"cancelled": True}
        done, skipped = service.import_recordings(folder)
        self.hub.log(f"Imported {len(done)} recording(s): {', '.join(done) or '-'}", "ok" if done else "warn")
        for s in skipped:
            self.hub.log(f"  not imported: {s}", "muted")
        return {"done": done, "skipped": skipped}

    def post_forget(self, body):
        code = service.normalise_code(body.get("code"))
        service.forget(code)
        self.hub.log(f"Forgot the recording of {code}.", "warn")
        return {"ok": True}

    def post_spec(self, body):
        spec = self._spec(body)
        return {"spec": spec, "problems": service.check_spec(spec)}

    def post_plan(self, body):
        the_plan = service.plan(body.get("codes") or [], body.get("policy") or "yesterday",
                                body.get("export"), (body.get("out_dir") or "").strip() or None)
        return {"plan": plan_view(the_plan)}

    def post_batch_save(self, body):
        name = (body.get("name") or "").strip()
        service.save_batch(name, body.get("codes") or [], body.get("policy") or "yesterday",
                           body.get("export"), (body.get("out_dir") or "").strip())
        self.hub.log(f"Saved batch '{name}' ({len(body.get('codes') or [])} screens, {body.get('policy')}).", "ok")
        return {"batches": service.batches()}

    def post_batch_delete(self, body):
        service.delete_batch(body.get("name") or "")
        return {"batches": service.batches()}

    def post_when(self, body):
        when = self._when(body)
        return {"text": service.gmes_schedule.describe_when(when)}

    def post_login(self, body):
        user = account.save_login(body.get("user") or "", body.get("password") or "",
                                  body.get("confirm") or "")
        self.hub.log(f"Login saved for Knox ID {user}.", "ok")
        return {"user": user}

    def post_login_check(self, body):
        return {"problems": account.check_new_login(body.get("user"), body.get("password"),
                                                    body.get("confirm"))}

    def post_browser(self, body):
        if self.hub.busy:
            raise service.Problem("Change the browser when nothing is running.")
        choice = body.get("choice") or "auto"
        self.hub.session.close()
        plan = account.apply_browser_choice(choice)
        app_settings.save(browser=choice)
        self.hub.log(f"Browser: {account.CHOICE_LABELS[choice]}"
                     + (" - a separate automation profile is used for it." if plan.get("GMES_PROFILE_DIR")
                        else "."), "ok")
        return {"ok": True}

    def post_confirm(self, body):
        r = self.hub.last_check
        if not r:
            raise service.Problem("There is no record check to confirm - run it again.")
        judged = service.confirm_and_rejudge(r)
        who = ((judged.get("evidence") or {}).get("confirmation") or {}).get("by", "-")
        self.hub.log(f"Period confirmed for {r['spec']['screen_code']} by {who}.", "ok")
        self.hub.log(f"Record check {judged['verdict']} - certificate {judged['certificate']}",
                     {"PASSED": "ok", "FAILED": "err"}.get(judged["verdict"], "warn"))
        return {"check": check_view(judged)}

    def post_rowexport_pause(self, body):
        r = self.hub.active_runner or self.hub.runner
        if r is None:
            return {"paused": False}
        if body.get("pause"):
            r.pause()
            self.hub.log("Paused - the row being exported finishes first.", "warn")
        else:
            r.resume()
            self.hub.log("Resumed.", "info")
        return {"paused": bool(body.get("pause"))}

    # ---- tasks (POST /api/task/<name>) -------------------------------------------
    def task(self, name, body):
        hub = self.hub
        stoppable = service.stoppable
        if name == "find":
            query = (body.get("query") or "").strip()
            return hub.start(f"Find '{query}'", lambda s, log: service.find(hub.session.ensure(s), query))
        if name == "describe":
            code = service.normalise_code(body.get("code"))

            def work(s, log):
                desc = service.describe(hub.session.ensure(s), code, log=stoppable(service.quiet, s))
                profile = desc.get("profile") or {}
                desc["last"] = service.gmes_profile.last_values(profile) if profile else {}
                desc["questions"] = [{"q": q, "a": a, "tone": t} for q, a, t in service.five_questions(desc)]
                hub.log(f"Described {desc['code']} - {desc['title']}: {len(desc['grids'])} grid(s), "
                        f"{len(desc['filters'])} filter(s), {len(desc['trees'])} tree(s).", "ok")
                return desc
            return hub.start(f"Describe {code}", work)
        if name == "record":
            spec = self._spec(body)
            problems = service.check_spec(spec)
            if problems:
                raise service.Problem("\n".join(problems))
            if body.get("dry"):
                return hub.start(f"Dry run {spec['screen_code']}", lambda s, log: service.record(
                    hub.session.ensure(s), spec, log=stoppable(log, s), dry_run=True),
                    view=lambda out: {"ok": bool(out.get("ok")), "error": service.plain(out.get("error") or "")})
            return hub.start(f"Record {spec['screen_code']}", lambda s, log: self._keep_check(
                service.record_and_check(hub.session.ensure(s), spec, log=stoppable(log, s))),
                view=check_view)
        if name == "recheck":
            code = service.normalise_code(body.get("code"))
            return hub.start(f"Record check {code}", lambda s, log: self._keep_check(
                service.recheck(hub.session.ensure(s), code, log=stoppable(log, s))), view=check_view)
        if name == "batch":
            return self._batch(body)
        if name == "rowexport_load":
            return self._rowexport_load(body)
        if name == "rowexport_start":
            return self._rowexport_start(body)
        if name == "test_signin":
            return hub.start("Test sign-in", lambda s, log: hub.session.who or "signed in")
        if name == "selftest":
            return hub.start("Self-test", self._selftest, needs_session=False)
        if name == "support":
            return hub.start("Support package", lambda s, log: str(service.support_package()),
                             needs_session=False)
        if name == "schedule_create":
            batch, when = body.get("batch") or "", self._when(body)
            return hub.start("Create schedule", lambda s, log: service.schedule_create(batch, when),
                             needs_session=False)
        if name in ("schedule_run", "schedule_pause", "schedule_resume", "schedule_delete"):
            batch = body.get("batch") or ""
            sched = service.gmes_schedule
            fn = {"schedule_run": lambda: sched.run_now(batch),
                  "schedule_pause": lambda: sched.set_enabled(batch, False),
                  "schedule_resume": lambda: sched.set_enabled(batch, True),
                  "schedule_delete": lambda: sched.delete(batch)}[name]
            return hub.start({"schedule_run": "Start schedule", "schedule_delete": "Delete schedule"}
                             .get(name, "Change schedule"), lambda s, log: fn(), needs_session=False)
        raise service.Problem(f"unknown task {name}")

    def _keep_check(self, result):
        self.hub.last_check = result
        self.hub.log(f"Record check {result['verdict']} - certificate {result['certificate']}",
                     {"PASSED": "ok", "FAILED": "err"}.get(result["verdict"], "warn"))
        return result

    def _selftest(self, s, log):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = self.hub.selftest() if self.hub.selftest else 0
        for line in buf.getvalue().splitlines():
            log(line)
        return {"code": code}

    def _batch(self, body):
        hub = self.hub
        codes, policy = body.get("codes") or [], body.get("policy") or "yesterday"
        export = body.get("export")
        out_dir = (body.get("out_dir") or "").strip() or os.path.join(
            service.core.OUTPUT_DIR, f"batch_{datetime.now():%Y%m%d_%H%M%S}")
        the_plan = service.plan(codes, policy, export, out_dir)
        if not any(i.ready for i in the_plan):
            raise service.Problem("Nothing in the plan can run - the reason is on each line.")
        batch_name = body.get("batch_name") or None

        def on_start(code):
            hub.emit("batch_row", code=code, status="running...", tag="info")

        def on_result(code, out):
            ok = bool(out.get("ok"))
            hub.emit("batch_row", code=code, status="ok" if ok else "FAILED", tag="ok" if ok else "err",
                     rows=int(out.get("rows") or 0),
                     detail=(", ".join(os.path.basename(f) for f in out.get("files", [])) if ok
                             else service.plain(out.get("error") or "")))

        def work(s, log):
            out = service.run_plan(hub.session, the_plan, policy, export, out_dir, log=log, stop_event=s,
                                   batch_name=batch_name, on_start=on_start, on_result=on_result)
            out["out_dir"] = out_dir
            out["results"] = [dict(r, error=service.plain(r.get("error") or "")) for r in out["results"]]
            return out
        hub.emit("batch_plan", plan=plan_view(the_plan), out_dir=out_dir)
        return hub.start(f"Run {sum(1 for i in the_plan if i.ready)} screen(s)", work)

    def _rowexport_settings(self, body):
        saved = rx.Settings.from_dict(app_settings.load().get("rowexport", {}))
        data = asdict(saved)
        for key in ("screen_code", "division", "period_mode", "period", "link_value", "out_dir",
                    "on_error"):
            if key in body:
                data[key] = str(body[key] or "").strip()
        data["screen_code"] = service.normalise_code(data["screen_code"]) or "Q321KUM00"
        model = str(body.get("model") or "").strip()
        data["extra_filters"] = [f"Model={model}"] if model else []
        if "grids" in body:
            data["dialog_grids"] = [g.strip() for g in str(body["grids"]).split(",") if g.strip()]
        try:
            data["start_row"] = int(body.get("start_row") or 1)
            data["count"] = int(body.get("count") or 0)
        except (TypeError, ValueError):
            raise service.Problem("Start row and How many must be whole numbers.") from None
        data["skip_existing"] = bool(body.get("skip_existing", True))
        s = rx.Settings.from_dict(data)
        problems = rx.validate_settings(s)
        if problems:
            raise service.Problem("\n".join(problems))
        app_settings.save(rowexport=asdict(s))
        return s

    def _rowexport_load(self, body):
        hub = self.hub
        s = self._rowexport_settings(body)
        runner = rx.Runner(s, log=hub.log)

        def work(stop, log):
            hub.active_runner = runner
            runner.attach(hub.session.ensure(stop))
            total, counts = runner.load()
            hub.runner = runner
            picked, _ = rx.select_rows(runner.rows, s.status_column, s.link_value, s.start_row, s.count)
            return {"total": total, "counts": counts, "period": runner.period,
                    "can": rx.count_link_rows(runner.rows, s.status_column, s.link_value),
                    "todo": len(picked), "sorted_by": runner.sorted_by, "division": s.division,
                    "mode": s.period_mode}
        return hub.start("Row export: load", work)

    def _rowexport_start(self, body):
        hub = self.hub
        r = hub.runner
        if r is None or not r.rows:
            raise service.Problem("Load the list first.")
        s = self._rowexport_settings(body)
        picked, _ = rx.select_rows(r.rows, s.status_column, s.link_value, s.start_row, s.count)
        if not picked:
            raise service.Problem("Nothing to export from that row on.")
        r.s = s
        r._stop.clear()
        r.resume()
        r.progress = lambda **kw: hub.emit("progress", **jsonable(kw))

        def work(stop, log):
            hub.active_runner = r
            r.attach(hub.session.ensure(stop))
            return r.run()
        return hub.start("Row export", work)

    # ---- shared parsing -----------------------------------------------------------
    @staticmethod
    def _spec(body):
        mode = body.get("period") or "none"
        frm = to = ""
        if mode != "none":
            frm = re.sub(r"\D", "", body.get("from") or "")
            to = re.sub(r"\D", "", body.get("to") or "") or frm
        sets = {str(k).strip(): str(v).strip() for k, v in (body.get("sets") or {}).items()
                if str(k).strip() and str(v).strip()}
        for part in str(body.get("more") or "").split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                if k.strip():
                    sets[k.strip()] = v.strip()
        return service.build_spec(body.get("code") or "", body.get("division") or "", frm, to, sets,
                                  body.get("options") or [], body.get("grid") or "",
                                  (body.get("verify") or "") if frm else "", body.get("export") or "xlsx",
                                  body.get("out_dir") or "")

    @staticmethod
    def _when(body):
        kind = body.get("kind") or "daily"
        try:
            return service.gmes_schedule.parse_when(
                (body.get("time") or "").strip(), daily=kind == "daily", weekdays=kind == "weekdays",
                days=list(body.get("days") or []) if kind == "days" else None)
        except (ValueError, service.gmes_schedule.ScheduleError) as e:
            raise service.Problem(str(e)) from None


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".ico": "image/x-icon"}


def web_dir():
    for path in (app_env.resource("web"), os.path.join(app_env.HERE, "web")):
        if os.path.isdir(path):
            return path
    raise FileNotFoundError("the web folder is missing")


def make_handler(api, token, port_ref):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "GMESAutomation"

        def log_message(self, *_a):                  # no console, no noise
            pass

        def _host_ok(self):
            host = (self.headers.get("Host") or "").lower()
            return host in (f"127.0.0.1:{port_ref[0]}", f"localhost:{port_ref[0]}")

        def _send(self, code, body, ctype="application/json; charset=utf-8", cache=False):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _static(self, path):
            name = {"/": "index.html", "/favicon.ico": "gmes.ico"}.get(path, path.lstrip("/"))
            if name == "gmes.ico":
                full = next((p for p in (app_env.resource("assets", "gmes.ico"),
                                         os.path.join(app_env.HERE, "assets", "gmes.ico")) if os.path.isfile(p)), "")
            else:
                if not re.fullmatch(r"[a-z_]+\.(html|js|css)", name):
                    return self._send(404, {"error": "not found"})
                full = os.path.join(web_dir(), name)
            if not full or not os.path.isfile(full):
                return self._send(404, {"error": "not found"})
            with open(full, "rb") as fh:
                data = fh.read()
            # Never mimetypes: on Windows it reads the registry, where .js is often
            # "text/plain" - and with nosniff the browser then refuses to run the page's
            # script at all (seen: an empty, unstyled window).
            ctype = CONTENT_TYPES.get(os.path.splitext(full)[1].lower(), "application/octet-stream")
            self._send(200, data, ctype)

        def _api(self, method):
            if self.headers.get("X-Token") != token:
                return self._send(403, {"error": "not this app's window"})
            url = urlparse(self.path)
            name = url.path[len("/api/"):].replace("/", "_").replace("-", "_")
            try:
                if method == "GET":
                    fn = getattr(api, f"get_{name}", None)
                    if fn is None:
                        return self._send(404, {"error": "unknown"})
                    return self._send(200, jsonable(fn(parse_qs(url.query))))
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
                if name.startswith("task_"):
                    return self._send(200, {"task_id": api.task(name[len("task_"):], body)})
                fn = getattr(api, f"post_{name}", None)
                if fn is None:
                    return self._send(404, {"error": "unknown"})
                return self._send(200, jsonable(fn(body)))
            except Busy as e:
                return self._send(409, {"error": str(e)})
            except (service.Problem, ValueError, OSError, service.gmes_schedule.ScheduleError) as e:
                return self._send(400, {"error": service.plain(e)})
            except Exception as e:                           # noqa: BLE001
                api.hub.log(traceback.format_exc(), "muted")
                return self._send(500, {"error": f"{type(e).__name__}: {service.plain(e)}"})

        def do_GET(self):                                    # noqa: N802
            if not self._host_ok():
                return self._send(403, {"error": "wrong host"})
            path = urlparse(self.path).path
            if path.startswith("/api/"):
                return self._api("GET")
            return self._static(path)

        def do_POST(self):                                   # noqa: N802
            if not self._host_ok():
                return self._send(403, {"error": "wrong host"})
            if not urlparse(self.path).path.startswith("/api/"):
                return self._send(404, {"error": "not found"})
            return self._api("POST")
    return Handler


class QuietServer(ThreadingHTTPServer):
    """A window that closes mid-request is normal, not a problem. The standard server
    printed a full traceback for it, which reached the Activity console in red."""

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)


class OutputSink:
    """Everything the engine prints reaches the activity log as whole lines."""

    def __init__(self, target, fallback):
        self.target, self.fallback = target, fallback
        self._buffers, self._lock = {}, threading.Lock()

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


# --------------------------------------------------------------------------
# One server per PC user; the window
# --------------------------------------------------------------------------
def _instance_file():
    return os.path.join(app_env.data_dir(), "window.json")


def running_instance():
    """The URL of this app's server if one already runs (a second start opens a window
    on it instead of fighting it for the browser)."""
    import urllib.request
    try:
        with open(_instance_file(), encoding="utf-8") as fh:
            info = json.load(fh)
        req = urllib.request.Request(f"http://127.0.0.1:{int(info['port'])}/api/state",
                                     headers={"X-Token": info["token"]})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=2) as resp:
            if resp.status == 200:
                return info["url"]
    except Exception:                                        # noqa: BLE001
        return None
    return None


def window_browser():
    """Chrome or Edge for the app window: the Windows default first."""
    import gmes_browsers
    keys = []
    try:
        d = gmes_browsers.default_browser_key()
        if d:
            keys.append(d)
    except Exception:                                        # noqa: BLE001
        pass
    for k in ("edge", "chrome"):
        if k not in keys:
            keys.append(k)
    for k in keys:
        try:
            exe = gmes_browsers.find_executable(k)
        except Exception:                                    # noqa: BLE001
            exe = None
        if exe:
            return exe
    return None


def open_window(url):
    """The app window: a browser 'app' window (no tabs, no address bar) on its own small
    profile in data/ui-browser - not the person's profile, not the automation's."""
    exe = window_browser()
    if not exe:
        import webbrowser
        webbrowser.open(url)
        return None
    profile = os.path.join(app_env.data_dir(), "ui-browser")
    os.makedirs(profile, exist_ok=True)
    args = [exe, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run",
            "--no-default-browser-check", "--disable-sync", "--disable-features=Translate",
            "--window-size=1440,920"]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def serve(selftest=None, open_ui=True, port=0, idle_exit=IDLE_EXIT_SECONDS):
    """Start the server (and the window). Returns when the window has been closed and
    nothing is running."""
    existing = running_instance() if open_ui else None
    if existing:
        open_window(existing)
        return 0
    hub = Hub(selftest=selftest)
    api = Api(hub)
    token = secrets.token_urlsafe(24)
    port_ref = [0]
    server = QuietServer(("127.0.0.1", port), make_handler(api, token, port_ref))
    server.daemon_threads = True
    port_ref[0] = server.server_address[1]
    url = f"http://127.0.0.1:{port_ref[0]}/?t={token}"
    with open(_instance_file(), "w", encoding="utf-8") as fh:
        json.dump({"port": port_ref[0], "token": token, "url": url, "pid": os.getpid()}, fh)

    sink = OutputSink(hub.engine_line, sys.stdout)
    sys.stdout = sys.stderr = sink
    try:
        account.apply_browser_choice(app_settings.load().get("browser", "auto"))
    except Exception:                                        # noqa: BLE001
        account.apply_browser_choice("auto")
    hub.log(f"{app_env.APP_NAME} {VERSION} - files and logs: {app_env.data_dir()}", "muted")
    threading.Thread(target=server.serve_forever, daemon=True, name="http").start()
    hub.server, hub.url = server, url
    if open_ui:
        open_window(url)
    try:
        while True:
            time.sleep(1)
            idle = time.time() - hub.last_poll
            if idle_exit and hub.polling == 0 and idle > idle_exit and not hub.busy:
                break
    except KeyboardInterrupt:
        pass
    finally:
        hub.log("Window closed - closing the automation browser.", "muted")
        hub.close()
        server.shutdown()
        try:
            os.remove(_instance_file())
        except OSError:
            pass
        sys.stdout = sys.stderr = sink.fallback
    return 0
