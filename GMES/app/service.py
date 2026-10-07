"""Everything GMES Automation does, without a window - so every decision is testable.

    Session      one browser, one sign-in, one run lock for the whole app
    find()       search the G-MES screen catalogue
    describe()   what a screen offers (grids, filters, trees, options, date columns)
    record()     run a screen with the chosen scope and remember what it proved
    replay()     run a recorded screen with NOTHING but its code
    judge()      the record check: every item of AGENT_PLAYBOOK.md step 6, with evidence
    plan()/run_plan()   batches, as the engine's own gmes_batch does them
    schedules    Task Scheduler, through the engine's gmes_schedule, for THIS app

The record check itself (record, replay, judge, certificates, confirmations) is the
engine's `gmes_recordcheck` since HISTORY.md Phase 123, so GMES_Workflow.bat proves a
recording with the very same code; it is re-exported here under the names the window
has always used.

Nothing here writes to G-MES: Inquiry and export are reads (CLAUDE.md 2.5).
"""
import json
import os
import re
import shutil
import sys
import threading
import time
from datetime import datetime, timedelta

import app_env

app_env.setup()

import cdp_common                      # noqa: E402
import gmes_batch                      # noqa: E402
import gmes_browsers                   # noqa: E402
import gmes_common                     # noqa: E402
import gmes_core as core               # noqa: E402
import gmes_library                    # noqa: E402
import gmes_open_screen                # noqa: E402
import gmes_profile                    # noqa: E402
import gmes_recordcheck as rc          # noqa: E402
import gmes_schedule                   # noqa: E402
import gmes_twin                       # noqa: E402
from gmes_recordcheck import (         # noqa: E402,F401 - the window's names for them
    CODE_RE, CONFIRM_FILE, PLAIN, Problem, Stopped, build_spec, certificates, check_spec,
    confirm_and_rejudge, confirm_period, confirmations, covered, date_spread, finish, judge,
    judge_typed_period, month_bounds, normalise_code, outside_pattern, period_evidence, plain,
    read_spread, record, replay, save_certificate, spec_from_profile, typed_period, verdict,
    yesterday)


def quiet(*_a, **_k):
    return None


def stoppable(log, stop_event):
    """A log function that also ends the work the moment Stop is pressed. The engine
    logs between every step, so this is a stop point between every step.

    It raises ONCE: after that the engine's own clean-up (the batch runner's
    'INTERRUPTED ... writing what was done') logs through the same function, and a
    second raise there would lose the report of what was delivered."""
    raised = []

    def _log(*args, **kwargs):
        if stop_event is not None and stop_event.is_set() and not raised:
            raised.append(True)
            raise Stopped()
        text = " ".join(str(a) for a in args)
        log(text)
    return _log


# --------------------------------------------------------------------------
# The one session
# --------------------------------------------------------------------------
class Session:
    """One automation browser, signed in once, held for the whole app (the owner:
    browser restarts are unacceptable for end users). It also holds the engine's
    run lock, so a scheduled batch or the command-line tool cannot drive the same
    browser at the same time."""

    def __init__(self, log=print):
        self.log = log
        self.ws = None
        self.lock = None
        self.who = ""

    def alive(self):
        if self.ws is None:
            return False
        try:
            return cdp_common.evaluate(self.ws, "JSON.stringify(1+1)") == 2
        except Exception:                                   # noqa: BLE001
            return False

    def ensure(self, stop_event=None):
        """A live, signed-in connection; connects (and signs in) only when needed.

        The run lock is taken here, for the task about to run, and given back by
        `release_lock()` when it ends. The window used to hold it from its first task
        until it was closed, so every schedule that fired while it was open found the
        browser "held", waited 15 minutes, and failed (HISTORY.md Phase 122)."""
        if self.lock is None:
            try:
                self.lock = core.acquire_run_lock()
            except core.RunLocked as e:
                raise Problem("A scheduled run (or another window of this app) is using the "
                              "automation browser right now. Wait for it to finish - History "
                              f"shows it when it is done.\n\n({e})") from e
        if self.alive():
            return self.ws
        if self.ws is not None:
            self.log("The connection to the browser dropped - connecting again...")
            self._drop_socket()
        try:
            if stop_event is not None and stop_event.is_set():
                raise Stopped()
            self.prepare_browser_profile()
            self.log("Signing in to G-MES (or reusing the open session)...")
            if not core.sign_in():
                raise Problem("Sign-in did not complete. Look at the browser window. Do not retry "
                              "many times in a row - many sign-ins in a short time can stop the "
                              "Samsung sign-in window from opening.")
            self.ws = core.connect()
            self._focus_emulation()
            ok, who = gmes_common.is_logged_in(self.ws)
            self.who = who or ""
            return self.ws
        except BaseException:
            self.release()
            raise

    def prepare_browser_profile(self):
        """First use on a PC: the automation's own copy of the person's Chrome/Edge
        profile, as a step of its own (a browser holding its profile becomes 'close
        it once', not a vague failed sign-in). Nothing once the copy exists."""
        if gmes_browsers.recorded_profile_dir():
            return None
        self.log("First use on this PC: making the automation's own copy of your browser "
                 "profile. Your own browser is only read - never changed.")
        try:
            return gmes_browsers.ensure_bootstrapped(
                cdp_common.automation_profile_dir(), cdp_common._SEED_PREFERENCES, verbose=True)
        except gmes_browsers.ProfileLocked as e:
            raise Problem("Your browser has its profile open, so the one-time copy could not be "
                          "made. Close every window of that browser once, then try again.\n\n"
                          f"({e})") from e

    def _focus_emulation(self):
        """Without it every click waits 5.0 s while the automation window is in the
        background (GMES_SKILL.md gotcha 93)."""
        try:
            cdp_common.send(self.ws, "Emulation.setFocusEmulationEnabled", {"enabled": True})
        except Exception:                                   # noqa: BLE001 - slower, not wrong
            pass

    def reconnect(self):
        """For gmes_batch.run_batch: the browser died mid-batch - start it again."""
        self._drop_socket()
        if not core.sign_in():
            return None
        self.ws = core.connect()
        self._focus_emulation()
        return self.ws

    def _drop_socket(self):
        try:
            if self.ws is not None:
                self.ws.close()
        except Exception:                                   # noqa: BLE001
            pass
        self.ws = None

    def release_lock(self):
        """Between tasks: let a scheduled run use the browser. The connection stays."""
        if self.lock is not None:
            core.release_run_lock(self.lock)
            self.lock = None

    def release(self):
        self._drop_socket()
        self.release_lock()

    def close(self, close_browser=False):
        self.release()
        try:
            if close_browser:
                cdp_common.close_browser()
            else:
                cdp_common.stop_if_started_here(False)    # only a browser THIS app opened
        except Exception:                                   # noqa: BLE001
            pass


# --------------------------------------------------------------------------
# Catalogue and describe
# --------------------------------------------------------------------------
def find(ws, query):
    """[{code, title, menu, path}] from the account's own catalogue."""
    info = gmes_open_screen.catalogue(ws, query)
    if not info.get("found"):
        raise Problem("The screen catalogue is not loaded - is G-MES signed in?")
    out = []
    for row in info.get("rows", []):
        out.append({"code": str(row.get("screenId") or "").upper(),
                    "title": row.get("menuTitle") or row.get("korean") or "",
                    "menu": row.get("menuId") or "", "system": row.get("sysCode") or "",
                    "path": row.get("path") or ""})
    # The catalogue returns at most 60 rows; say so when more matched, never hide it
    # (CLAUDE.md 4.6 - a cap that hides data is worse than no cap).
    return {"total": info.get("total", 0), "matched": info.get("matched", len(out)),
            "truncated": bool(info.get("truncated")), "rows": out}


def describe(ws, code, log=quiet):
    """What the screen offers, as data. Opens the screen; changes nothing."""
    screen = core.open_screen(ws, code, log=log)
    info = screen.info
    chosen, rivals = core.choose_grid(info)
    grids = []
    for g in info.get("grids", []):
        ds = info.get("datasets", {}).get(g["dataset"], {})
        grids.append({"name": g["name"], "dataset": g["dataset"], "cols": ds.get("cols"),
                      "rows": ds.get("rows"), "visible": bool(g.get("visible")),
                      "suggested": bool(chosen and g["name"] == chosen["name"])})
    filters = []
    for f in info.get("filters", []):
        filters.append({"label": f.get("label") or "", "column": f.get("column") or "",
                        "control": f.get("control") or "", "value": f.get("value") or "",
                        "visible": bool(f.get("visible")), "date": bool(core.is_date_field(f))})
    unbound = [{"label": u.get("label") or "", "control": u.get("control") or "",
                "value": u.get("value") or ""} for u in info.get("unbound", [])]
    frm, to, singles = core.date_targets(info)
    date_fields = [f["column"] for f in (frm, to) if f] or [f["column"] for f in singles]
    trees, tree_error = [], ""
    try:
        for t in screen.trees():
            if t.get("settable"):
                trees.append({"form": t["form"], "dataset": t["dataset"], "rows": t.get("rows"),
                              "names": list(t.get("names", [])), "checked": t.get("checked")})
    except Exception as e:                                  # noqa: BLE001
        tree_error = str(e)
    options, option_error = [], ""
    try:
        for o in screen.options():
            options.append({"label": o.get("label") or "", "key": core.option_key(o.get("name")),
                            "state": o.get("state") or "", "enabled": o.get("enabled", True),
                            "kind": o.get("kind") or ""})
    except Exception as e:                                  # noqa: BLE001
        option_error = str(e)
    verify_candidates = []
    try:
        if chosen:
            # a business date (`deftCreYmd`) is offered before a clock time
            # (`deftCreDt`): a production day runs 08:00 to 08:00, so a timestamp
            # refuses its night-shift rows (Q2111WM00, HISTORY.md Phase 122.11)
            verify_candidates = sorted(
                screen.candidate_verify_columns(chosen),
                key=lambda c: 0 if re.search(r"(ymd|date|day)$", c.lower()) else 1)
    except Exception:                                       # noqa: BLE001
        pass
    month = any(f["date"] and re.fullmatch(r"\d{6}", re.sub(r"\D", "", f["value"]))
                for f in filters) or any(o["key"] in ("month",) and "selected" in o["state"]
                                         for o in options)
    return {"code": screen.code, "title": screen.title, "menu_id": screen.menu_id,
            "window": screen.win_id, "has_inquiry": bool(info.get("hasInquiry")),
            "has_excel": bool(info.get("hasExcel")), "grids": grids, "rivals": bool(rivals),
            "filters": filters, "unbound": unbound, "date_fields": date_fields,
            "trees": trees, "tree_error": tree_error, "options": options,
            "option_error": option_error, "verify_candidates": verify_candidates,
            "looks_monthly": bool(month), "profile": gmes_profile.load(screen.code),
            "typed_dates": {} if date_fields else typed_date_boxes(unbound)}


def typed_date_boxes(unbound):
    """The Period boxes a screen does NOT bind to a dataset (R3220UM00's mskFromDate /
    mskToDate): {"from", "to", "width"} or {}. The Record page's Period then types the
    dates into them - before, a person had to know the control names and write
    'mskFromDate=...; mskToDate=...' into More filters (HISTORY.md Phase 122)."""
    boxes = [u for u in unbound or [] if core.is_date_field(
        {"control": u.get("control"), "label": u.get("label"), "value": u.get("value")})]
    first = next((u for u in boxes if core.period_words(u["control"]) & core._FROM_WORDS), None)
    last = next((u for u in boxes if core.period_words(u["control"]) & core._PERIOD_END_WORDS), None)
    if not first:
        return {}
    digits = re.sub(r"\D", "", first.get("value") or "")
    return {"from": first["control"], "to": (last or first)["control"],
            "width": 6 if len(digits) == 6 else 8, "label": first.get("label") or "Period"}


def typed_sets(typed, date_from, date_to):
    """The `sets` that type a period into a screen's unbound Period boxes."""
    if not typed or not typed.get("from") or not date_from:
        return {}
    width = 6 if typed.get("width") == 6 else 8
    return {typed["from"]: date_from[:width], typed["to"]: (date_to or date_from)[:width]}


def five_questions(desc):
    """AGENT_PLAYBOOK.md section 4, answered from the describe result where the
    evidence allows it, and marked 'decide' where a person must look."""
    grids = desc.get("grids", [])
    suggested = next((g for g in grids if g["suggested"]), None)
    divisions = sorted({n for t in desc.get("trees", []) for n in t["names"]})
    out = []
    if len(grids) <= 1 or not desc.get("rivals"):
        out.append(("Which grid is the report?",
                    f"{suggested['name']} (the only real candidate)" if suggested else
                    "no result grid was found", "ok" if suggested else "warn"))
    else:
        out.append(("Which grid is the report?",
                    f"several grids are comparable; suggested {suggested['name'] if suggested else '-'} "
                    "- confirm with a look at the screen after Inquiry", "decide"))
    typed = desc.get("typed_dates") or {}
    if not desc.get("date_fields") and typed:
        out.append(("Is the period a date or a month?",
                    f"{'a MONTH' if typed.get('width') == 6 else 'a day range'} typed into the "
                    f"screen's {typed.get('label') or 'Period'} boxes - the Period below fills them", "ok"))
    elif not desc.get("date_fields"):
        out.append(("Is the period a date or a month?", "this screen has no date field", "ok"))
    else:
        out.append(("Is the period a date or a month?",
                    "looks like a MONTH period (type YYYYMM)" if desc.get("looks_monthly")
                    else "a day range (YYYYMMDD)", "ok"))
    if divisions:
        has_vd = any(n.upper() == "VD" for n in divisions)
        out.append(("Is there a division, and which?",
                    "the tree holds VD" if has_vd else
                    f"no VD in the tree ({', '.join(divisions[:6])}...) - choose, never substitute",
                    "ok" if has_vd else "decide"))
    else:
        out.append(("Is there a division, and which?", "no organisation tree on this screen", "ok"))
    if desc.get("date_fields") or typed:
        cands = desc.get("verify_candidates") or []
        out.append(("How can the date be verified?",
                    f"date columns in the result: {', '.join(cands)}" if cands else
                    "no date-named column in the result - the day may not be verifiable",
                    "ok" if cands else "warn"))
    else:
        out.append(("How can the date be verified?", "nothing to verify (no date)", "ok"))
    live = not desc.get("date_fields") and not desc.get("has_inquiry")
    out.append(("Is it a live monitor?",
                "probably: no date and no Inquiry button - a snapshot of now" if live
                else "no", "warn" if live else "ok"))
    return out


# --------------------------------------------------------------------------
# The record check (gmes_recordcheck), with this app's batch planner
# --------------------------------------------------------------------------
def record_and_check(ws, spec, log=print, record_fn=None, replay_fn=None, plan_fn=None, now=None,
                     spread_fn=None):
    return rc.record_and_check(ws, spec, log=log, record_fn=record_fn, replay_fn=replay_fn,
                               plan_fn=plan_fn or plan, now=now, spread_fn=spread_fn)


def recheck(ws, code, log=print, replay_fn=None, plan_fn=None, now=None, spread_fn=None):
    return rc.recheck(ws, code, log=log, replay_fn=replay_fn, plan_fn=plan_fn or plan, now=now,
                      spread_fn=spread_fn)


# --------------------------------------------------------------------------
# Library
# --------------------------------------------------------------------------
def library():
    """One card per screen this app knows (recorded here, or shipped structure)."""
    history = gmes_library.run_history()
    last = gmes_library.last_result_by_code(history)
    certs = certificates()
    cards = []
    for p in gmes_profile.known():
        if not isinstance(p, dict):
            continue
        card = gmes_library.report_card(p, last.get(str(p.get("screen", "")).upper()))
        card["replays"] = gmes_batch.describe_profile(p)
        card["learned"] = p.get("learned") or ""
        card["recorded"] = bool(p.get("learned"))
        cert = certs.get(card["code"].upper())
        card["check"] = cert.get("verdict") if cert else ""
        card["check_at"] = cert.get("checked_at") if cert else ""
        card["output_dir"] = p.get("output_dir") or ""
        cards.append(card)
    return cards


def unreadable_profiles():
    return gmes_profile.unreadable()


def import_recordings(folder):
    """Copy recordings (<CODE>.json made by the project's tool or another copy of this
    app) into this app's recordings. Never overwrites a newer recording here. The
    engine's own `gmes_twin.import_recordings`, which the command line uses too."""
    return gmes_twin.import_recordings(folder, gmes_profile.SCREENS_DIR)


def forget(code):
    """Remove THIS app's recording of a screen (the person confirmed it). The
    shipped structure, if any, stays."""
    return gmes_profile.forget(normalise_code(code))


# --------------------------------------------------------------------------
# Batches
# --------------------------------------------------------------------------
POLICIES = (("yesterday", "Yesterday"), ("today", "Today"), ("keep", "As recorded"))


def plan(codes, policy="yesterday", export=None, out_dir=None):
    gmes_batch.resolve_dates(policy)                        # a clear error now
    return gmes_batch.build_plan(list(codes), policy, core.effective_export(export), out_dir)


def run_plan(session, the_plan, policy, export=None, out_dir=None, log=print, stop_event=None,
             batch_name=None, on_start=None, on_result=None):
    """Run a plan like `gmes_batch.py run` does, and write its report. `on_start(code)`
    and `on_result(code, out)` report each screen as it goes (for the window)."""
    started = datetime.now()
    meta = {"started": started.strftime("%Y-%m-%d %H:%M:%S"), "policy": policy,
            "language": "en", "dates": gmes_batch.resolve_dates(policy),
            "screens": [i.code for i in the_plan], "export": core.effective_export(export),
            "output_dir": out_dir, "unattended": False, "batch": batch_name, "app": app_env.APP_NAME}
    ws = session.ensure(stop_event)
    the_log = stoppable(log, stop_event)
    results, note = gmes_batch.clock_gate(ws, the_plan, policy, log=log)
    if note:
        meta["warnings"] = [note]
    def run_one(ws_, log=None, **spec):
        code = spec.get("screen_code", "?")
        if on_start:
            on_start(code)
        try:
            out = core.run_screen(ws_, log=log, **spec)
        except Exception as e:                               # noqa: BLE001
            if on_result:
                on_result(code, {"ok": False, "error": str(e)})
            raise
        if on_result:
            on_result(code, out)
        return out

    if results is None:
        results = gmes_batch.run_batch(ws, the_plan, log=the_log, run=run_one,
                                       reconnect=session.reconnect)
    json_path, txt_path = gmes_batch.write_report_safely(results, meta, log=log)
    summary_path = (txt_path[:-len(".txt")] + "_summary.html") if txt_path else None
    return {"results": results, "counts": gmes_batch.summarise(results), "report": txt_path,
            "summary": summary_path if summary_path and os.path.isfile(summary_path) else None,
            "stopped": any("interrupted" in str(r.get("error") or "") for r in results)}


def batches():
    return gmes_batch.list_batches()


def save_batch(name, codes, policy, export=None, output_dir=None):
    if not gmes_batch.valid_name(name):
        raise Problem("A batch name is letters, digits, - or _ (at most 40).")
    return gmes_batch.save_batch(name, list(codes), policy, core.effective_export(export),
                                 output_dir=output_dir or None)


def delete_batch(name):
    return gmes_batch.delete_batch(name)


# --------------------------------------------------------------------------
# Schedules (this app's own tasks: GMES_App_<batch>)
# --------------------------------------------------------------------------
RETRY_WAIT_SECONDS = gmes_schedule.RETRY_WAIT_SECONDS
RETRIES = gmes_schedule.RETRIES


def program_command():
    """How Task Scheduler starts this app headless: the .exe, or Python + the script."""
    if app_env.FROZEN:
        return [sys.executable]
    return [sys.executable, os.path.join(app_env.HERE, "gmes_app.py")]


def launcher_text(batch, command=None, retry_wait=RETRY_WAIT_SECONDS, retries=RETRIES):
    """The .cmd the task runs - the engine launcher's rules (UTF-8, % doubled, no
    blocks, exit 3/4 retried) applied to this app. `start /wait` because a windowed
    .exe would otherwise return at once and its exit code would be lost."""
    command = command or program_command()
    gmes_schedule.task_name(batch)                          # validates the name
    quoted = " ".join(f'"{gmes_schedule._bat_literal(c)}"' for c in command)
    log = f"logs\\scheduled_{batch}.log"
    return "\r\n".join([
        "@echo off",
        "chcp 65001 >nul",
        'set "PYTHONIOENCODING=utf-8"',
        'cd /d "%~dp0.."',
        "if not exist logs mkdir logs",
        "set attempt=0",
        ":again",
        f'echo [%date% %time%] launcher: starting batch {batch} >> "{log}"',
        f'start "" /wait {quoted} --batch {batch} --unattended',
        "set code=%errorlevel%",
        f'echo [%date% %time%] launcher: finished with exit %code% >> "{log}"',
        "if %code%==3 goto retry",
        "if %code%==4 goto retry",
        "exit /b %code%",
        ":retry",
        "set /a attempt+=1",
        f"if %attempt% GTR {retries} exit /b %code%",
        f'echo [%date% %time%] launcher: exit %code%, waiting {retry_wait} s, then retry '
        f'%attempt% of {retries} >> "{log}"',
        f"ping -n {retry_wait + 1} 127.0.0.1 >nul",
        "goto again",
        ""])


POLICY_WORDS = {"yesterday": "yesterday's data", "today": "today's data",
                "keep": "the dates each screen was recorded with"}


def policy_text(policy):
    p = str(policy or "yesterday").strip().lower()
    return POLICY_WORDS.get(p, f"the fixed date {policy}")


def fixed_dates(policy):
    """A date rule that gives the SAME day on every run - pointless for a schedule."""
    p = str(policy or "yesterday").strip().lower()
    return not (p in ("yesterday", "today") or re.fullmatch(r"-\d+", p))


def schedule_create(batch, when, policy=None):
    """Create (or replace) the batch's schedule. `policy` - the date rule chosen on
    the Schedules page - is saved into the batch first, so the schedule decides which
    day it exports, in the same place it decides when (HISTORY.md Phase 122)."""
    saved = batches().get(batch)
    if not saved:
        raise Problem(f"There is no saved batch called '{batch}'. Save the batch first.")
    if policy and policy != saved.get("date"):
        gmes_batch.resolve_dates(policy)                       # a clear error, now
        save_batch(batch, saved.get("screens") or [], policy, saved.get("export"),
                   saved.get("output_dir") or None)
    os.makedirs(gmes_schedule.SCHEDULE_DIR, exist_ok=True)
    cmd_path = gmes_schedule.launcher_path(batch)
    with open(cmd_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(launcher_text(batch))
    vbs = gmes_schedule.write_hidden_wrapper(batch, cmd_path)
    rc, out, err = gmes_schedule._run_powershell(
        gmes_schedule.create_script(batch, when, vbs, app_env.data_dir()))
    if rc != 0:
        raise Problem((err or out or "Task Scheduler refused the task").strip())
    return gmes_schedule.task_name(batch)


def schedule_list():
    """Every schedule of this app, with WHAT it runs beside when it runs."""
    tasks = gmes_schedule.list_tasks()
    saved = batches()
    for t in tasks:
        # the launcher log holds only start/finish lines; which screen failed is in History
        t["notes"] = [n.replace(f"read logs\\scheduled_{t['batch']}.log",
                                "History shows which screens and why")
                      for n in gmes_schedule.assess_task(t)]
        b = saved.get(t["batch"])
        if b is None:
            t["screens"], t["policy"], t["dates"] = [], "", ""
            t["notes"].insert(0, "its batch was deleted - this schedule will fail; delete it, "
                                 "or save a batch with the same name")
            continue
        t["screens"] = list(b.get("screens") or [])
        t["policy"] = b.get("date") or "yesterday"
        t["dates"] = policy_text(t["policy"])
        if fixed_dates(t["policy"]):
            t["notes"].insert(0, f"it exports {t['dates']} on every run - choose Yesterday or "
                                 "Today and save the schedule again")
    return tasks


def headless_batch(name, unattended=True):
    """What a scheduled task runs: the engine's own batch command, pointed at this
    app's data. Returns the engine's exit code (0 ok, 1 some failed, 3 busy, 4 sign-in)."""
    args = ["run", "--batch", name]
    if unattended:
        args.append("--unattended")
    return gmes_batch.main(args)


def support_package():
    return gmes_library.support_package(root=app_env.base_dir(), out_dir=app_env.sub("support"),
                                        log_dir=os.path.join(app_env.data_dir(), "logs"))
