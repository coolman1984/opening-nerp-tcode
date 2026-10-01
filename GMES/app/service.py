"""Everything GMES Automation does, without a window - so every decision is testable.

    Session      one browser, one sign-in, one run lock for the whole app
    find()       search the G-MES screen catalogue
    describe()   what a screen offers (grids, filters, trees, options, date columns)
    record()     run a screen with the chosen scope and remember what it proved
    replay()     run a recorded screen with NOTHING but its code
    judge()      the record check: every item of AGENT_PLAYBOOK.md step 6, with evidence
    plan()/run_plan()   batches, as the engine's own gmes_batch does them
    schedules    Task Scheduler, through the engine's gmes_schedule, for THIS app

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
import gmes_schedule                   # noqa: E402


class Stopped(KeyboardInterrupt):
    """The person pressed Stop. A KeyboardInterrupt on purpose: the engine's batch
    runner already turns one into a clean, written report (gmes_batch.run_batch)."""


class Problem(RuntimeError):
    """Something the person has to act on; the message says what."""


def quiet(*_a, **_k):
    return None


# The engine speaks to the command-line tool's user ("--set", "--verify", "python
# gmes_open_screen.py --find X"). A person in the factory uses this window, so every
# message that reaches them is put in the window's words. Order matters: longer first.
PLAIN = (
    (re.compile(r"Check the code with:\s+python gmes_open_screen\.py --find (\S+)"),
     r"Use Find on the 'Record a screen' page with words from its name (\1)."),
    (re.compile(r"--verify COLUMN\[=VALUE\]"), "a Verify column"),
    (re.compile(r"was typed with --set"), "was typed into the screen"),
    (re.compile(r"\(--verify only runs with --from/--to\)"), "(only a Day(s) period is checked row by row)"),
    (re.compile(r"Pass --grid to be certain[^.]*\."), "Choose the Result grid on the Record page."),
    (re.compile(r"--division"), "the Division"),
    (re.compile(r"--verify"), "the Verify column"),
    (re.compile(r"--from/--to"), "the period"),
    (re.compile(r"--set"), "a typed filter"),
    (re.compile(r"--option"), "an option"),
    (re.compile(r"--grid"), "the Result grid"),
    (re.compile(r"--relearn"), "recording it again"),
    (re.compile(r"--close-tabs"), "a fresh screen"),
    (re.compile(r"--allow-password-login"), "a password sign-in"),
)


def plain(text):
    """An engine message in the window's words (never changes its meaning)."""
    out = str(text)
    for pattern, words in PLAIN:
        out = pattern.sub(words, out)
    return out


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
        """A live, signed-in connection; connects (and signs in) only when needed."""
        if self.alive():
            return self.ws
        if self.ws is not None:
            self.log("The connection to the browser dropped - connecting again...")
            self._drop_socket()
        if self.lock is None:
            try:
                self.lock = core.acquire_run_lock()
            except core.RunLocked as e:
                raise Problem(f"{e}\n\nIf a scheduled run is working right now, wait for it; "
                              "if another window of this app is open, close it.") from e
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

    def release(self):
        self._drop_socket()
        if self.lock is not None:
            core.release_run_lock(self.lock)
            self.lock = None

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
CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{3,5}[A-Z]{2}\d{2}$")


def normalise_code(text):
    return re.sub(r"\s+", "", str(text or "")).upper()


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
            verify_candidates = list(screen.candidate_verify_columns(chosen))
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
            "looks_monthly": bool(month), "profile": gmes_profile.load(screen.code)}


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
    if not desc.get("date_fields"):
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
    if desc.get("date_fields"):
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
# Record, replay, and the record check
# --------------------------------------------------------------------------
def yesterday(today=None):
    return ((today or datetime.now()) - timedelta(days=1)).strftime("%Y%m%d")


def build_spec(code, division="", date_from="", date_to="", sets=None, options=(), grid="",
               verify="", export="xlsx", out_dir="", tree=""):
    spec = {"screen_code": normalise_code(code), "division": division.strip() or None,
            "date_from": (date_from or "").strip() or None,
            "date_to": (date_to or date_from or "").strip() or None,
            "sets": {k: v for k, v in (sets or {}).items() if str(k).strip()},
            "options": [o for o in options if o], "grid_name": grid or None,
            "verify": verify.strip() or None, "export": export or None,
            "out_dir": out_dir.strip() or None, "tree": tree or None}
    return spec


def check_spec(spec):
    """Problems to fix before anything runs, or []."""
    problems = []
    if not CODE_RE.match(spec["screen_code"] or ""):
        problems.append(f"'{spec['screen_code']}' does not look like a full G-MES screen code "
                        "(e.g. P1112UM00). Use Find to look it up.")
    for key in ("date_from", "date_to"):
        v = spec.get(key)
        if v and not re.fullmatch(r"\d{6}|\d{8}", v):
            problems.append(f"{key.replace('_', ' ')} '{v}' must be YYYYMMDD (or YYYYMM for a month)")
    if spec.get("date_from") and spec.get("date_to") and spec["date_from"] > spec["date_to"]:
        problems.append("the start date is after the end date")
    if spec.get("date_from") and not spec.get("verify"):
        problems.append("a dated run needs the result column that holds the date (Verify) - "
                        "otherwise the tool cannot prove the right day came back")
    if spec.get("export") not in (None, "xlsx", "csv", "both", "none"):   # "both" = Excel (98.1)
        problems.append("export must be xlsx, csv, both or none")
    return problems


def record(ws, spec, log=print, dry_run=False):
    """Run with the chosen scope, learning the screen afresh (the old memory, if
    any, is superseded only by THIS run's own success - never deleted first)."""
    problems = check_spec(spec)
    if problems:
        raise Problem("\n".join(problems))
    kwargs = dict(spec)
    kwargs["trust_profile"] = False
    kwargs["dry_run"] = dry_run
    return core.run_screen(ws, log=log, **kwargs)


def replay(ws, code, log=print, export=None, out_dir=None):
    """The bare replay: the screen code and nothing else. If it needs anything the
    recording did not remember, the recording is not finished (AGENT_PLAYBOOK.md
    step 5)."""
    kwargs = {}
    if export:
        kwargs["export"] = export
    if out_dir:
        kwargs["out_dir"] = out_dir
    return core.run_screen(ws, normalise_code(code), log=log, **kwargs)


def _attempt(fn, *args, **kwargs):
    """run_screen raises on failure; the record check needs the failure as a result."""
    try:
        return fn(*args, **kwargs)
    except Stopped:
        raise
    except Exception as e:                                   # noqa: BLE001
        return {"ok": False, "error": str(e), "rows": 0, "files": [], "warnings": []}


def record_and_check(ws, spec, log=print, record_fn=None, replay_fn=None, plan_fn=None, now=None,
                     spread_fn=None):
    """Record, then the mandatory bare replay, then the batch check, then the record
    check - the owner's standing rule: a screen is not 'recorded' until its own bare
    replay has passed (AGENT_PLAYBOOK.md section 1)."""
    problems = check_spec(spec)
    if problems:
        raise Problem("\n".join(problems))
    rec = _attempt(record_fn or record, ws, spec, log=log)
    rep = item = None
    evidence = {}
    if rec.get("ok"):
        evidence = period_evidence(ws, spec, rec, log, spread_fn)
    if rec.get("ok") and rec.get("profile"):
        log("Record check: replaying it bare - the screen code and nothing else...")
        rep = _attempt(replay_fn or replay, ws, spec["screen_code"], log=log)
        policy = "yesterday" if spec.get("date_from") else "keep"
        try:
            item = (plan_fn or plan)([spec["screen_code"]], policy)[0]
        except Exception as e:                               # noqa: BLE001
            item = gmes_batch.PlanItem(code=spec["screen_code"], blocked=f"the batch plan failed: {e}")
    result = {"kind": "record", "spec": spec, "rec": rec, "rep": rep, "plan": item,
              "evidence": evidence}
    return finish(result, now)


def period_evidence(ws, spec, rec, log=print, spread_fn=None):
    """For a typed period: the rows' own dates (counts only) and the person's earlier
    confirmation for this screen, if any."""
    typed = typed_period(spec)
    if not typed:
        return {}
    prefer = (spec.get("verify") or "").partition("=")[0].strip() or None
    try:
        spread = (spread_fn or read_spread)(ws, spec["screen_code"], rec, typed, prefer)
    except Stopped:
        raise
    except Exception as e:                                   # noqa: BLE001
        log(f"  note: the rows' dates could not be read ({e})")
        spread = None
    if spread:
        log(f"  period   : {spread['column']} - {spread['inside']:,} of {spread['dated']:,} rows in "
            f"{typed[2]}" + (f", outside: {spread['outside']}" if spread["outside"] else ""))
    return {"spread": spread, "confirmation": confirmations().get(spec["screen_code"])}


def finish(result, now=None):
    """Judge, keep the certificate, say the verdict. Also used after a confirmation."""
    checks = judge(result["spec"], result["rec"], result.get("rep"), result.get("plan"),
                   result.get("evidence"))
    if result.get("kind") == "recheck" and result["rec"].get("ok"):
        checks.insert(1, _check("Bare replay (the code and nothing else) works", "ok",
                                f"{int(result['rec'].get('rows') or 0):,} rows"))
    result["checks"] = checks
    result["verdict"] = verdict(checks)
    result["certificate"] = save_certificate(result["spec"], checks, result["rec"], result.get("rep"),
                                             now=now)
    return result


def confirm_and_rejudge(result, by=None, now=None):
    """The person confirmed the typed period on the G-MES screen: keep that, judge again."""
    typed = typed_period(result["spec"])
    spread = (result.get("evidence") or {}).get("spread")
    if not typed or not spread:
        raise Problem("There is nothing to confirm for this check.")
    conf = confirm_period(result["spec"]["screen_code"], spread, typed, by=by, now=now)
    result["evidence"] = dict(result.get("evidence") or {}, confirmation=conf)
    return finish(result, now)


def spec_from_profile(code):
    """What a recording will do, as a spec - for re-checking a screen recorded earlier."""
    code = normalise_code(code)
    profile = gmes_profile.load(code)
    if not profile or not profile.get("learned"):
        raise Problem(f"{code} is not recorded on this PC yet - record it first.")
    v = gmes_profile.last_values(profile)
    return build_spec(code, v.get("division") or "", v.get("from") or "", v.get("to") or "",
                      v.get("sets") or {}, (), "", v.get("verify") or "",
                      profile.get("export") or core.DEFAULT_EXPORT, profile.get("output_dir") or "")


def recheck(ws, code, log=print, replay_fn=None, plan_fn=None, now=None, spread_fn=None):
    """The record check for a screen recorded earlier: one bare replay, judged."""
    spec = spec_from_profile(code)
    rep = _attempt(replay_fn or replay, ws, spec["screen_code"], log=log)
    item = None
    evidence = {}
    if rep.get("ok"):
        evidence = period_evidence(ws, spec, rep, log, spread_fn)
        try:
            item = (plan_fn or plan)([spec["screen_code"]],
                                     "yesterday" if spec.get("date_from") else "keep")[0]
        except Exception as e:                               # noqa: BLE001
            item = gmes_batch.PlanItem(code=spec["screen_code"], blocked=f"the batch plan failed: {e}")
    result = {"kind": "recheck", "spec": spec, "rec": rep, "rep": None, "plan": item,
              "evidence": evidence}
    return finish(result, now)


def _check(name, status, detail):
    return {"name": name, "status": status, "detail": plain(detail)}


def judge(spec, rec, rep=None, plan_item=None, evidence=None):
    """The record check - AGENT_PLAYBOOK.md step 6, item by item, from evidence.

    status: ok | warn | fail | info. A recording PASSES only with no fail; every
    warn is said in plain words, never hidden. `evidence` = {"spread": date_spread(),
    "confirmation": the person's confirmation for this screen} for a typed period."""
    checks = []
    code = spec["screen_code"]
    ok = bool(rec and rec.get("ok"))
    checks.append(_check("The run finished", "ok" if ok else "fail",
                         "completed" if ok else (rec or {}).get("error") or "it did not complete"))
    if not ok:
        return checks
    title = rec.get("title") or ""
    checks.append(_check("The screen that opened is the one asked for",
                         "ok" if str(rec.get("screen", "")).upper() == code else "fail",
                         f"{code} - {title}"))
    if spec.get("division"):
        seen = rec.get("division") or ""
        checks.append(_check("The division was ticked and the screen confirms it",
                             "ok" if seen else "fail", seen or "the division could not be confirmed"))
    else:
        checks.append(_check("Division", "info", "none asked for - the screen's own selection was used"))
    applied = rec.get("applied") or {}
    for key, value in (spec.get("sets") or {}).items():
        hit = any(str(key).lower() in str(k).lower() or str(k).lower() in str(key).lower()
                  for k in applied)
        checks.append(_check(f"Filter {key} applied and read back", "ok" if hit else "fail",
                             f"{value}" if hit else "the screen did not report it as set"))
    drift = [w for w in rec.get("warnings", []) if "did not take" in str(w)]
    for w in drift:
        checks.append(_check("A value did not take", "fail", w))
    rows = int(rec.get("rows") or 0)
    checks.append(_check("Rows came back", "ok" if rows > 0 else "fail",
                         f"{rows:,} rows from {rec.get('grid') or '?'}"))
    files = list(rec.get("files") or [])
    if spec.get("export") == "none":
        checks.append(_check("Files", "info", "export was switched off for this run"))
    elif not files:
        checks.append(_check("Files were written", "fail", "no file was produced"))
    for path in files:
        size = os.path.getsize(path) if os.path.isfile(path) else 0
        checks.append(_check(f"File {os.path.basename(path)}", "ok" if size > 512 else "fail",
                             f"{size:,} bytes" if size else "missing or empty"))
    if rec.get("csv_rows") is not None:
        same = int(rec["csv_rows"]) == rows
        checks.append(_check("CSV rows equal the Inquiry rows", "ok" if same else "warn",
                             f"CSV {rec['csv_rows']:,}, Inquiry {rows:,}"))
    typed = typed_period(spec)
    if rec.get("verified"):
        col, seen = next(iter(rec["verified"].items()))
        checks.append(_check("The result carries the requested date", "ok", f"{col} = {seen}"))
    elif spec.get("date_from"):
        checks.append(_check("The result carries the requested date", "fail",
                             "the date was not verified"))
    elif typed:
        checks.extend(judge_typed_period(spec, rec, typed, evidence))
    elif any("NOT checked" in str(w) for w in rec.get("warnings", [])):
        checks.append(_check("The result carries the requested date", "warn",
                             "the period was typed into the screen; the rows were not checked "
                             "against it - confirm on the screen once"))
    else:
        checks.append(_check("Date", "info", "no date was asked for"))
    for w in rec.get("warnings", []):
        if "did not take" in str(w) or "NOT checked" in str(w):
            continue
        checks.append(_check("Warning", "warn", str(w)))
    checks.append(_check("Remembered for next time", "ok" if rec.get("profile") else "fail",
                         "saved" if rec.get("profile") else
                         "not saved - read the warnings; a profile keeps only what a run proved"))
    if rep is not None:
        rep_ok = bool(rep.get("ok"))
        checks.append(_check("Bare replay (the code and nothing else) works",
                             "ok" if rep_ok else "fail",
                             f"{int(rep.get('rows') or 0):,} rows" if rep_ok else
                             rep.get("error") or "the replay did not complete"))
        if rep_ok:
            same = int(rep.get("rows") or 0) == rows
            checks.append(_check("The replay returns the same rows", "ok" if same else "warn",
                                 f"record {rows:,}, replay {int(rep.get('rows') or 0):,}"
                                 + ("" if same else " - data can change between runs; check once")))
    if plan_item is not None:
        checks.append(_check("Ready for batches and schedules",
                             "ok" if plan_item.ready else "fail",
                             "; ".join(plan_item.notes) or "ready" if plan_item.ready
                             else plan_item.blocked))
    return checks


# --------------------------------------------------------------------------
# A period TYPED into the screen (a month like 202609): what can be proven
# --------------------------------------------------------------------------
def typed_period(spec):
    """(start YYYYMMDD, end YYYYMMDD, label) of a period typed as filters, or None."""
    values = [re.sub(r"\D", "", str(v)) for k, v in (spec.get("sets") or {}).items()
              if gmes_batch.date_role(k, v)]
    values = [v for v in values if len(v) in (6, 8)]
    if not values:
        return None
    lo, hi = min(values), max(values)
    start = lo + "01" if len(lo) == 6 else lo
    if len(hi) == 6:
        y, m = int(hi[:4]), int(hi[4:])
        first_next = datetime(y + (m == 12), m % 12 + 1, 1)
        end = (first_next - timedelta(days=1)).strftime("%Y%m%d")
    else:
        end = hi
    label = (f"{lo[:4]}-{lo[4:6]}" if len(lo) == 6 and lo == hi else
             f"{start[:4]}-{start[4:6]}-{start[6:]} .. {end[:4]}-{end[4:6]}-{end[6:]}")
    return start, end, label


def _day(value):
    return datetime.strptime(value, "%Y%m%d")


def date_spread(rows, columns, period, prefer=None):
    """How the rows' own dates fall against the period: {column, rows, dated, inside,
    outside: {date: count}}. Counts only - nothing about the rows is kept.

    WHICH column is decided by a rule that does not look at the answer: the column the
    person named (Verify), else the FIRST date column in the dataset's own order. An
    earlier draft took the column that fitted the period best - a test caught it
    choosing a registration timestamp (all inside) over the plan date the period
    means, which would have turned the check green by picking the friendliest column."""
    start, end, _label = period
    candidates = core.date_named_columns(columns)
    if prefer and prefer in columns:
        candidates = [prefer] + [c for c in candidates if c != prefer]
    for col in candidates:
        values = []
        for r in rows:
            v = re.sub(r"\D", "", str(r.get(col) or ""))[:8]
            if len(v) == 8:
                values.append(v)
        if not values:
            continue                                         # a date-named column with no dates
        outside = {}
        for v in values:
            if not start <= v <= end:
                outside[v] = outside.get(v, 0) + 1
        return {"column": col, "rows": len(rows), "dated": len(values),
                "inside": len(values) - sum(outside.values()), "outside": dict(sorted(outside.items()))}
    return None


def outside_pattern(spread, period):
    """Where the rows outside the period sit, RELATIVE to it: {'before': [days before
    the start], 'after': [days after the end]} - so a confirmation made in September
    still fits October ('the day before the period starts')."""
    start, end = _day(period[0]), _day(period[1])
    before, after = set(), set()
    for v in (spread or {}).get("outside", {}):
        d = _day(v)
        if d < start:
            before.add((start - d).days)
        else:
            after.add((d - end).days)
    return {"before": sorted(before), "after": sorted(after)}


def read_spread(ws, code, rec, period, prefer=None):
    """The result's own dates against the period - read from the data layer, counts only."""
    import gmes_data
    dataset = str(rec.get("grid") or "").split("->")[-1].strip()
    if not dataset:
        return None
    data = gmes_data.read_dataset(ws, code, dataset, limit=-1)
    if not data.get("found", True):
        return None
    return date_spread(data.get("rows") or [], data.get("columns") or [], period, prefer)


CONFIRM_FILE = "confirmations.json"


def confirmations():
    try:
        with open(os.path.join(app_env.data_dir(), CONFIRM_FILE), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def confirm_period(code, spread, period, by=None, now=None):
    """The person looked at the G-MES screen and says the rows ARE the period as G-MES
    means it. Kept with the exact pattern they confirmed; a later run whose rows fall
    outside it differently is NOT covered and warns again."""
    data = confirmations()
    entry = {"by": by or os.environ.get("USERNAME") or "this user",
             "at": (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
             "column": (spread or {}).get("column"), "pattern": outside_pattern(spread, period),
             "seen": {"period": period[2], "inside": (spread or {}).get("inside"),
                      "outside": (spread or {}).get("outside")}}
    data[normalise_code(code)] = entry
    path = os.path.join(app_env.data_dir(), CONFIRM_FILE)
    with open(path + ".partial", "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(path + ".partial", path)
    return entry


def covered(confirmation, spread, period):
    """Does the person's confirmation cover THIS run's outside rows?"""
    if not confirmation or not spread:
        return False
    if confirmation.get("column") and confirmation["column"] != spread.get("column"):
        return False
    now = outside_pattern(spread, period)
    ok = confirmation.get("pattern") or {}
    return set(now["before"]) <= set(ok.get("before", [])) and set(now["after"]) <= set(ok.get("after", []))


def judge_typed_period(spec, rec, typed, evidence=None):
    """Three pieces of evidence, strongest first:
       1. the screen HOLDS the typed period (its fields were read back after typing);
       2. the rows' own dates fall in it (counted from the data layer);
       3. where some rows fall outside, a person confirmed on the G-MES screen that this
          is how G-MES means the period - tied to that exact pattern (e.g. 'the day
          before the start'), so a new, different pattern warns again."""
    evidence = evidence or {}
    out = []
    applied = {str(k).lower(): str(v) for k, v in (rec.get("applied") or {}).items()}
    keys = [k for k, v in (spec.get("sets") or {}).items() if gmes_batch.date_role(k, v)]
    held = [f"{k} = {applied.get(k.lower())}" for k in keys
            if re.sub(r"\D", "", applied.get(k.lower(), "")) == re.sub(r"\D", "", str(spec["sets"][k]))]
    out.append(_check("The screen holds the requested period",
                      "ok" if len(held) == len(keys) else "fail",
                      ", ".join(held) if len(held) == len(keys) else
                      f"the screen did not read back {', '.join(keys)} as asked"))
    spread = evidence.get("spread")
    label = typed[2]
    if not spread:
        out.append(_check("The rows carry the requested period", "warn",
                          f"the rows' dates could not be read - confirm {label} on the G-MES screen once"))
        return out
    detail = f"{spread['column']}: {spread['inside']:,} of {spread['dated']:,} rows in {label}"
    if not spread["outside"]:
        out.append(_check("The rows carry the requested period", "ok", detail + " - all of them"))
        return out
    shown = ", ".join(f"{d[:4]}-{d[4:6]}-{d[6:]} x{n}" for d, n in list(spread["outside"].items())[:4])
    detail += f"; outside: {shown}"
    conf = evidence.get("confirmation")
    if covered(conf, spread, typed):
        out.append(_check("The rows carry the requested period", "ok",
                          f"{detail} - G-MES lists these with the period; confirmed on its screen by "
                          f"{conf['by']} on {conf['at'][:10]}"))
    else:
        why = (" (a confirmation exists, but this run's outside dates are a NEW pattern)"
               if conf else "")
        out.append(dict(_check("The rows carry the requested period", "warn",
                               f"{detail}{why}. If the G-MES screen itself shows these rows for "
                               f"{label}, confirm it once and the check turns green."),
                        confirmable=True))
    return out


def verdict(checks):
    if any(c["status"] == "fail" for c in checks):
        return "FAILED"
    if any(c["status"] == "warn" for c in checks):
        return "PASSED WITH WARNINGS"
    return "PASSED"


def save_certificate(spec, checks, rec, rep=None, now=None):
    """The record check, kept: what was asked, what was proven, when."""
    now = now or datetime.now()
    data = {"screen": spec["screen_code"], "title": (rec or {}).get("title", ""),
            "checked_at": now.strftime("%Y-%m-%d %H:%M:%S"), "verdict": verdict(checks),
            "spec": {k: v for k, v in spec.items() if k != "out_dir"},
            "checks": checks, "record_rows": (rec or {}).get("rows"),
            "replay_rows": (rep or {}).get("rows") if rep else None,
            "files": [os.path.basename(f) for f in (rec or {}).get("files", [])]}
    folder = app_env.sub("certificates")
    path = os.path.join(folder, f"{spec['screen_code']}_{now:%Y%m%d_%H%M%S}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    return path


def certificates():
    """{code: newest certificate}"""
    folder = app_env.sub("certificates")
    best = {}
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        best[str(data.get("screen", "")).upper()] = data
    return best


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
    app) into this app's recordings. Never overwrites a newer recording here."""
    done, skipped = [], []
    target = gmes_profile.SCREENS_DIR
    os.makedirs(target, exist_ok=True)
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json") or not gmes_profile.looks_like_code(name[:-5]):
            continue
        src, dst = os.path.join(folder, name), os.path.join(target, name)
        try:
            with open(src, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            skipped.append(f"{name}: unreadable")
            continue
        if not isinstance(data, dict) or not data.get("screen"):
            skipped.append(f"{name}: not a recording")
            continue
        if os.path.isfile(dst):
            try:
                with open(dst, encoding="utf-8") as fh:
                    mine = json.load(fh)
                if str(mine.get("learned", "")) >= str(data.get("learned", "")):
                    skipped.append(f"{name}: the one here is the same or newer")
                    continue
            except (OSError, ValueError):
                pass
        shutil.copyfile(src, dst)
        done.append(name[:-5])
    return done, skipped


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


def schedule_create(batch, when):
    if batch not in batches():
        raise Problem(f"There is no saved batch called '{batch}'. Save the batch first.")
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
    tasks = gmes_schedule.list_tasks()
    for t in tasks:
        t["notes"] = gmes_schedule.assess_task(t)
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
