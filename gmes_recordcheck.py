"""The record check: is a recording really finished? Shared by BOTH front ends.

    record_and_check()   record with the chosen scope, then the mandatory bare replay,
                         the batch planner's verdict, judged item by item
    recheck()            the same check for a screen recorded earlier (one bare replay)
    check_recording()    the check for a recording a front end has just made itself
    judge()              AGENT_PLAYBOOK.md step 6, item by item, from evidence
    confirm_and_rejudge() a person confirmed a typed period on the G-MES screen

Every check is kept as a certificate (what was asked, what was proven, when).

This lived in GMES/app/service.py until HISTORY.md Phase 123, so only the window
(GMES_Automation.exe) could prove a recording; GMES_Workflow.bat could not. It is
engine code now: `gmes_report.py record|check|confirm` and the interactive tool use
it, and the window imports the very same functions from its synced engine copy
(CLAUDE.md section 0a - the two front ends stay at the same level).

Where it keeps things (both redirected by GMES/app/app_env.py for the window):
    certificates   screens/certificates/<CODE>_<time>.json
    confirmations  screens/confirmations.json

Nothing here writes to G-MES: Inquiry and export are reads (CLAUDE.md 2.5).
"""
import json
import os
import re
from datetime import datetime, timedelta

import gmes_batch
import gmes_core as core
import gmes_profile

# None = beside the recordings (gmes_profile.SCREENS_DIR), read at call time so a
# front end that moves SCREENS_DIR moves these with it.
CERT_DIR = None
CONFIRM_DIR = None
CONFIRM_FILE = "confirmations.json"


class Stopped(KeyboardInterrupt):
    """The person pressed Stop. A KeyboardInterrupt on purpose: the engine's batch
    runner already turns one into a clean, written report (gmes_batch.run_batch)."""


class Problem(RuntimeError):
    """Something the person has to act on; the message says what."""


def cert_dir():
    path = CERT_DIR or os.path.join(gmes_profile.SCREENS_DIR, "certificates")
    os.makedirs(path, exist_ok=True)
    return path


def confirm_path():
    folder = CONFIRM_DIR or gmes_profile.SCREENS_DIR
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, CONFIRM_FILE)


# The engine speaks to the command-line tool's user ("--set", "--verify", "python
# gmes_open_screen.py --find X"). The window's user never typed those, so its
# messages are put in the window's words. Order matters: longer first.
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


CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{3,5}[A-Z]{2}\d{2}$")


def normalise_code(text):
    return re.sub(r"\s+", "", str(text or "")).upper()


def yesterday(today=None):
    return ((today or datetime.now()) - timedelta(days=1)).strftime("%Y%m%d")


# --------------------------------------------------------------------------
# What is asked
# --------------------------------------------------------------------------
def build_spec(code, division="", date_from="", date_to="", sets=None, options=(), grid="",
               verify="", export="xlsx", out_dir="", tree=""):
    spec = {"screen_code": normalise_code(code), "division": (division or "").strip() or None,
            "date_from": (date_from or "").strip() or None,
            "date_to": (date_to or date_from or "").strip() or None,
            "sets": {k: v for k, v in (sets or {}).items() if str(k).strip()},
            "options": [o for o in options if o], "grid_name": grid or None,
            "verify": (verify or "").strip() or None, "export": export or None,
            "out_dir": (out_dir or "").strip() or None, "tree": tree or None}
    return spec


def month_bounds(date_from, date_to=""):
    """A Month period as the engine's day range: YYYYMM .. YYYYMM -> first day of the
    first month .. last day of the last month (YYYYMMDD).

    The engine takes only YYYYMMDD dates. The Record page's Month choice used to pass
    '202610' straight through, and the run then refused every row: the Verify step
    compared each row's day (20261005) with '202610' (HISTORY.md Phase 121). A month
    FIELD on the screen still gets six digits - the engine fits a date to the width
    the field holds (`fit_date_to_field`). Anything that is not YYYYMM is returned
    unchanged, for check_spec() to explain."""
    lo = re.sub(r"\D", "", date_from or "")
    hi = re.sub(r"\D", "", date_to or "") or lo
    if not (re.fullmatch(r"\d{6}", lo) and re.fullmatch(r"\d{6}", hi)):
        return date_from, date_to
    try:
        start = datetime.strptime(lo + "01", "%Y%m%d")
        last = datetime.strptime(hi + "01", "%Y%m%d")
    except ValueError:
        return date_from, date_to
    end = (last.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def check_spec(spec):
    """Problems to fix before anything runs, or []."""
    problems = []
    if not CODE_RE.match(spec["screen_code"] or ""):
        problems.append(f"'{spec['screen_code']}' does not look like a full G-MES screen code "
                        "(e.g. P1112UM00). Use Find to look it up.")
    dates_ok = True
    for key in ("date_from", "date_to"):
        v = spec.get(key)
        if not v:
            continue
        name = key.replace("_", " ")
        if not re.fullmatch(r"\d{8}", v):
            problems.append(f"{name} '{v}' must be a day, YYYYMMDD (choose Month for a month)")
            dates_ok = False
            continue
        try:
            datetime.strptime(v, "%Y%m%d")
        except ValueError:
            problems.append(f"{name} '{v}' is not a real calendar date")
            dates_ok = False
    if (dates_ok and spec.get("date_from") and spec.get("date_to")
            and spec["date_from"] > spec["date_to"]):
        problems.append("the start date is after the end date")
    if spec.get("date_from") and not spec.get("verify"):
        problems.append("a dated run needs the result column that holds the date (Verify) - "
                        "otherwise the tool cannot prove the right day came back")
    if spec.get("export") not in (None, "xlsx", "csv", "both", "none"):   # "both" = Excel (98.1)
        problems.append("export must be xlsx, csv, both or none")
    return problems


# --------------------------------------------------------------------------
# Record, replay, plan
# --------------------------------------------------------------------------
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


def plan(codes, policy="yesterday", export=None, out_dir=None):
    gmes_batch.resolve_dates(policy)                        # a clear error now
    return gmes_batch.build_plan(list(codes), policy, core.effective_export(export), out_dir)


def _attempt(fn, *args, **kwargs):
    """run_screen raises on failure; the record check needs the failure as a result."""
    try:
        return fn(*args, **kwargs)
    except Stopped:
        raise
    except Exception as e:                                   # noqa: BLE001
        return {"ok": False, "error": str(e), "rows": 0, "files": [], "warnings": []}


def _plan_item(code, spec, plan_fn):
    try:
        return (plan_fn or plan)([code], "yesterday" if spec.get("date_from") else "keep")[0]
    except Exception as e:                                   # noqa: BLE001
        return gmes_batch.PlanItem(code=code, blocked=f"the batch plan failed: {e}")


# --------------------------------------------------------------------------
# The record check
# --------------------------------------------------------------------------
def record_and_check(ws, spec, log=print, record_fn=None, replay_fn=None, plan_fn=None, now=None,
                     spread_fn=None):
    """Record, then the mandatory bare replay, then the batch check, then the record
    check - the owner's standing rule: a screen is not 'recorded' until its own bare
    replay has passed (AGENT_PLAYBOOK.md section 1)."""
    problems = check_spec(spec)
    if problems:
        raise Problem("\n".join(problems))
    rec = _attempt(record_fn or record, ws, spec, log=log)
    return check_recording(ws, spec, rec, log=log, replay_fn=replay_fn, plan_fn=plan_fn, now=now,
                           spread_fn=spread_fn)


def check_recording(ws, spec, rec, log=print, replay_fn=None, plan_fn=None, now=None,
                    spread_fn=None):
    """The record check of a recording run that has ALREADY happened (`rec` is its
    run_screen result). The interactive command line records through its own
    questions and then calls this, so its recordings are proven exactly like the
    window's."""
    rep = item = None
    evidence = {}
    if rec.get("ok"):
        evidence = period_evidence(ws, spec, rec, log, spread_fn)
    if rec.get("ok") and rec.get("profile"):
        log("Record check: replaying it bare - the screen code and nothing else...")
        rep = _attempt(replay_fn or replay, ws, spec["screen_code"], log=log)
        item = _plan_item(spec["screen_code"], spec, plan_fn)
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
                                             now=now, evidence=result.get("evidence"))
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


def confirm_from_certificate(code, by=None, now=None):
    """`confirm_and_rejudge()` for a front end that does not hold the last check in
    memory (the command line): the newest certificate of the screen carries what was
    proven and the date spread the person looked at."""
    code = normalise_code(code)
    cert = certificates().get(code)
    if not cert:
        raise Problem(f"{code} has no record check yet - run one first.")
    spread = (cert.get("evidence") or {}).get("spread")
    if not spread or not any(c.get("confirmable") for c in cert.get("checks") or []):
        raise Problem(f"The last record check of {code} ({cert.get('checked_at')}) has nothing to "
                      "confirm - only a typed period with rows outside it can be confirmed.")
    spec = dict(cert["spec"], out_dir=None)
    rec = {"ok": True, "screen": code, "title": cert.get("title", ""), "rows": cert.get("record_rows"),
           "files": [], "warnings": [], "notes": []}
    typed = typed_period(spec)
    conf = confirm_period(code, spread, typed, by=by, now=now)
    # Judge again from the certificate's own checks: only the period item changes.
    checks = []
    for c in cert.get("checks") or []:
        if c.get("confirmable"):
            c = judge_typed_period(spec, {"applied": {k: v for k, v in (spec.get("sets") or {}).items()},
                                          "notes": []}, typed, {"spread": spread, "confirmation": conf})[-1]
        checks.append(c)
    cert_path = save_certificate(spec, checks, dict(rec, rows=cert.get("record_rows")),
                                 {"rows": cert.get("replay_rows")} if cert.get("replay_rows") is not None
                                 else None, now=now, evidence={"spread": spread, "confirmation": conf})
    return {"kind": "confirm", "spec": spec, "checks": checks, "verdict": verdict(checks),
            "certificate": cert_path, "evidence": {"spread": spread, "confirmation": conf}}


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
        item = _plan_item(spec["screen_code"], spec, plan_fn)
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
    empty = bool(rec.get("empty"))
    if empty:
        # an empty answer on a grid earlier runs proved: G-MES has nothing for that
        # period - not a failure (HISTORY.md Phase 122)
        checks.append(_check("Rows came back", "ok",
                             "; ".join(rec.get("notes") or []) or "G-MES has no rows for this period"))
    else:
        checks.append(_check("Rows came back", "ok" if rows > 0 else "fail",
                             f"{rows:,} rows from {rec.get('grid') or '?'}"))
    files = list(rec.get("files") or [])
    if empty:
        checks.append(_check("Files", "info", "no file for an empty answer"))
    elif spec.get("export") == "none":
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
    if empty:
        checks.append(_check("Date", "info", "no rows, so no dates to check"))
    elif rec.get("verified"):
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


def confirmations():
    try:
        with open(confirm_path(), encoding="utf-8") as fh:
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
    path = confirm_path()
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
    if not spread and any("read back right before Inquiry" in str(n) for n in rec.get("notes") or []):
        # a summary with no date column (Q2251UM00): the read-back above is the proof
        # this screen has, not a missing check (HISTORY.md Phase 122)
        out.append(_check("The rows carry the requested period", "ok",
                          f"the result has no date column; {label} was read back from the "
                          "screen right before Inquiry"))
        return out
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
    if any("defines its own period" in str(n) for n in rec.get("notes") or []):
        # the recording says G-MES defines this period itself; the month was read back
        # from the screen. The spread is still shown, never hidden (HISTORY.md Phase 122)
        out.append(_check("The rows carry the requested period", "ok",
                          f"{detail} - G-MES's own {label}: the screen defines it, and it was "
                          "read back right before Inquiry"))
    elif covered(conf, spread, typed):
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


def save_certificate(spec, checks, rec, rep=None, now=None, evidence=None):
    """The record check, kept: what was asked, what was proven, when.

    The date spread (counts per day, no row content) is kept too, so a person can
    confirm a typed period later from the command line, which holds no check in
    memory between commands (`confirm_from_certificate`)."""
    now = now or datetime.now()
    spread = (evidence or {}).get("spread")
    data = {"screen": spec["screen_code"], "title": (rec or {}).get("title", ""),
            "checked_at": now.strftime("%Y-%m-%d %H:%M:%S"), "verdict": verdict(checks),
            "spec": {k: v for k, v in spec.items() if k != "out_dir"},
            "checks": checks, "record_rows": (rec or {}).get("rows"),
            "replay_rows": (rep or {}).get("rows") if rep else None,
            "files": [os.path.basename(f) for f in (rec or {}).get("files", [])]}
    if spread:
        data["evidence"] = {"spread": spread}
    path = os.path.join(cert_dir(), f"{spec['screen_code']}_{now:%Y%m%d_%H%M%S}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    return path


def certificates():
    """{code: newest certificate}"""
    folder = cert_dir()
    best = {}
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("screen"):
            best[str(data["screen"]).upper()] = data
    return best


# --------------------------------------------------------------------------
# Words for a terminal (the window draws the same checks itself)
# --------------------------------------------------------------------------
MARKS = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL", "info": "info"}


def check_lines(result):
    """The record check as plain text lines - for the command line and the logs."""
    lines = [f"Record check of {result['spec']['screen_code']}: {result['verdict']}"]
    for c in result["checks"]:
        lines.append(f"  [{MARKS.get(c['status'], c['status'])}] {c['name']}: {c['detail']}")
    if any(c.get("confirmable") for c in result["checks"]):
        lines.append("  -> if the G-MES screen itself lists these rows for the period, confirm it once:")
        lines.append(f"     python gmes_report.py confirm {result['spec']['screen_code']}")
    lines.append(f"  certificate: {result['certificate']}")
    return lines
