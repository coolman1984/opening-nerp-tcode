"""
Batch runs - replay several recorded screens together: all of them, a chosen
few, or a saved list; right now, or on a schedule.

    python gmes_batch.py list                          # what is recorded
    python gmes_batch.py plan all                      # what WOULD run, no browser
    python gmes_batch.py run all                       # everything, yesterday
    python gmes_batch.py run 1,3,5-7 --date today      # a chosen few
    python gmes_batch.py run all !Q2111UM00            # all except one
    python gmes_batch.py run @morning                  # a saved list
    python gmes_batch.py save morning 1,3,5-7          # save a list
    python gmes_batch.py schedule morning --at 06:30 --daily
    python gmes_batch.py schedules                     # what is scheduled
    python gmes_batch.py unschedule morning

Nothing here runs "everything" implicitly: `run` needs an explicit selection,
because a batch is many live queries against a production system.

Why this is not just `gmes_core.run_many()`
-------------------------------------------
`run_many()` stops at the first failure, because "the foreground screen can no
longer be proved safe for the next report" - right for a short chain someone is
watching. For "run all my recordings" it is wrong: one screen having no data on
a Friday would cancel the other seventeen. So each screen is isolated, and
between screens the session is HEALTH-CHECKED (popups cleared, still signed in,
a kicked session recovered); only a session that cannot be proved healthy, or
three failures in a row, stops the batch (HISTORY.md Phase 83).

Why the dates are handled here
------------------------------
A profile remembers the dates of the day it was recorded. Replaying it
unchanged asks the same old question forever - useless for a nightly job. So a
batch applies a DATE POLICY (yesterday by default) to every screen, including
the ones whose dates were typed with `--set` under names like `mskFromDate`,
`endYmd` or `aplyStartDt`, which live inside the profile's `sets`.

Nothing here runs in parallel: see `gmes_core.run_many()` for why.
"""
import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import cdp_common
import gmes_common
import gmes_core as core
import gmes_log
import gmes_open_screen
import gmes_profile

BATCH_DIR = os.path.join(gmes_profile.SCREENS_DIR, "batches")
REPORT_DIR = os.path.join(core.SCRIPT_DIR, "logs", "batches")

# Exit codes. A scheduler and a person both need to tell these apart.
EXIT_OK = 0
EXIT_FAILED = 1        # at least one screen failed or was not run
EXIT_USAGE = 2
EXIT_BUSY = 3          # another run holds the browser - nothing was attempted
EXIT_NO_SIGN_IN = 4

# Three failures in a row is a pattern, not bad luck: the session, the network
# or G-MES itself. Stopping protects an unattended run from hammering a system
# that is not answering.
MAX_CONSECUTIVE_FAILURES = 3

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}")


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def _split(text):
    return [t for t in re.split(r"[,\s;]+", text or "") if t]


def _expand_token(token, codes, batches):
    """One token -> a list of screen codes (from `codes`, in list order)."""
    low = token.lower()
    if low in ("all", "*"):
        return list(codes)
    if token.startswith("@"):
        name = token[1:]
        if name not in batches:
            raise ValueError(f"there is no saved batch called {name!r}"
                             + (f" (saved: {', '.join(sorted(batches))})" if batches else ""))
        return list(batches[name])
    if token.isdigit():
        n = int(token)
        if not 1 <= n <= len(codes):
            raise ValueError(f"{n} is not on the list (1 to {len(codes)})")
        return [codes[n - 1]]
    m = re.fullmatch(r"(\d+)-(\d+)", token)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a > b:
            raise ValueError(f"{token!r} runs backwards")
        if a < 1 or b > len(codes):
            raise ValueError(f"{token!r} is outside the list (1 to {len(codes)})")
        return codes[a - 1:b]
    for code in codes:
        if code.lower() == low:
            return [code]
    raise ValueError(f"{token!r} is not a recorded screen or a number on the list")


def parse_selection(text, codes, batches=None):
    """Turn what a person typed into an ordered list of screen codes.

    `codes` is the recorded screens in the order they are LISTED, since a
    number means "that row". Accepts, mixed freely: `all` / `*`, a number,
    a range `5-7`, a screen code, `@name` for a saved batch, and a leading
    `!` or `-` to remove something again (`all !3 !Q2111UM00`). Duplicates
    are dropped, first appearance wins. Raises ValueError with a message a
    person can act on - never guesses at what was meant."""
    batches = batches or {}
    tokens = _split(core.ascii_digits(text))
    if not tokens:
        raise ValueError("nothing was selected - say what to run: all, numbers "
                         "like 1,3,5-7, screen codes, or --batch NAME "
                         "(in PowerShell a saved list is written '@name' in quotes, "
                         "because a bare @name means something else there)")
    chosen, removed = [], []
    for token in tokens:
        if token[0] in "!-" and len(token) > 1:
            removed.extend(_expand_token(token[1:], codes, batches))
        else:
            chosen.extend(_expand_token(token, codes, batches))
    if not chosen:
        raise ValueError("only exclusions were given - nothing to run")
    out = []
    for code in chosen:
        if code not in removed and code not in out:
            out.append(code)
    if not out:
        raise ValueError("everything selected was also excluded")
    return out


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

POLICY_HELP = ("yesterday (default), today, -N (N days back), keep (each "
               "screen's own remembered dates), YYYYMMDD, or YYYYMMDD:YYYYMMDD")


MAX_DAYS_BACK = 3660           # about ten years; further back is a typo, not a report


def _days_back(today, n):
    try:
        d = today - timedelta(days=n)
    except OverflowError:
        raise ValueError(f"{n} days back is outside the calendar") from None
    return d.strftime("%Y%m%d"), d.strftime("%Y%m%d")


def resolve_dates(policy, today=None):
    """A date policy -> (date_from, date_to) as YYYYMMDD, or (None, None) for
    `keep`. `today` is injectable so this is testable without a clock.

    Digits of any script are accepted (`core.ascii_digits`), an absurd "N days
    back" is refused instead of returning a date in 1752, and nothing here can
    escape as an OverflowError - that used to surface as a raw traceback for
    `-99999999999` (HISTORY.md Phase 84.8)."""
    today = today or date.today()
    p = core.ascii_digits((policy or "yesterday").strip().lower())
    if p == "keep":
        return None, None
    if p == "yesterday":
        return _days_back(today, 1)
    if p == "today":
        return today.strftime("%Y%m%d"), today.strftime("%Y%m%d")
    m = re.fullmatch(r"-(\d+)", p)
    if m:
        n = int(m.group(1)) if len(m.group(1)) < 12 else MAX_DAYS_BACK + 1
        if n > MAX_DAYS_BACK:
            raise ValueError(f"{policy!r} is more than {MAX_DAYS_BACK} days back "
                             f"(about ten years) - is that a typo? Use {POLICY_HELP}")
        return _days_back(today, n)
    if ":" in p:
        a, _, b = p.partition(":")
        start, end = core.normalise_date(a), core.normalise_date(b)
        if not start or not end or start > end:
            raise ValueError(f"{policy!r} is not a valid range (want YYYYMMDD:YYYYMMDD, start first)")
        return start, end
    try:
        one = core.normalise_date(p)
    except ValueError as e:
        raise ValueError(f"{policy!r}: {e}. Use {POLICY_HELP}") from None
    if not one:
        raise ValueError(f"{policy!r} is not a date policy. Use {POLICY_HELP}")
    return one, one


def date_role(key, value):
    """Is this remembered `--set` a date, and which end of a period?

    Returns "from", "to", "single" or None. Judged on the NAME as well as the
    value: plenty of eight-digit codes are not dates (core.is_date_field's own
    warning), so an eight-digit value alone proves nothing, and `words()`
    keeps `paramVendorCode` from being read as containing "end"."""
    try:
        if not core.normalise_date(str(value)):
            return None
    except ValueError:
        return None
    w = core.words(key)
    if w & core._FROM_WORDS:
        return "from"
    if w & core._TO_WORDS:
        return "to"
    if w & core._DATE_WORDS:
        return "single"
    return None


@dataclass
class Retargeted:
    date_from: str = None
    date_to: str = None
    sets: dict = None            # None = leave the profile's own alone
    verify: str = None           # None = leave the profile's own alone
    dated: bool = False
    changed: list = field(default_factory=list)


def _retarget_verify(verify, old_from, old_to, date_from, date_to):
    """Follow a pinned `COLUMN=VALUE` verify to the new date, or leave it.

    A screen recorded with an explicit value (`--verify woPlanStartYmd=20260920`)
    saves that value verbatim (gmes_core.py `run_screen`'s profile write). Replayed
    later under a DIFFERENT date policy, `run_screen()` still reuses that frozen
    string unchanged (it only fills `verify` from the profile when the caller gave
    none) - so it verifies every future night against the day it was RECORDED, not
    the day it was RUN. That is not a weaker check, it is a check of the wrong
    thing: a correct new-day answer is refused (HISTORY.md, live 2026-09-22,
    R4351UM01: 1435 correct rows for 20260921 refused as "not exactly the
    requested 20260920"), and a query that silently never advanced past the old
    day would just as wrongly be reported as verified.

    Only a value that matches the OLD recorded from/to is touched - that is what
    proves it was tracking the date, not an unrelated column (P3111UM00 pins
    `plantCode=P701`, which is not a date at all and must survive untouched)."""
    column, sep, value = (verify or "").partition("=")
    if not sep:
        return None
    try:
        pinned = core.normalise_date(value)
    except ValueError:
        return None
    try:
        was_from = core.normalise_date(old_from) if old_from else None
    except ValueError:
        was_from = None
    try:
        was_to = core.normalise_date(old_to) if old_to else None
    except ValueError:
        was_to = None
    if pinned not in (was_from, was_to):
        return None
    return f"{column}={date_to if pinned == was_to else date_from}"


def retarget(values, date_from, date_to):
    """Apply a date policy to what a profile remembers.

    `--from/--to` dates are replaced; date-shaped entries inside the remembered
    `sets` are replaced too (a screen whose date fields are not bound to a
    dataset can only be given its dates that way); a `--verify COLUMN=VALUE`
    pinned to the OLD recorded date is replaced the same way. Everything else -
    division, other filters, options - is left exactly as recorded."""
    values = values or {}
    if not date_from:                       # policy "keep"
        return Retargeted()
    out = Retargeted()
    if values.get("from"):
        out.date_from, out.date_to, out.dated = date_from, date_to, True
    sets = dict(values.get("sets") or {})
    for key, value in sets.items():
        role = date_role(key, value)
        if role == "from":
            sets[key] = date_from
        elif role == "to":
            sets[key] = date_to
        elif role == "single":
            sets[key] = date_to if date_to != date_from else date_from
        else:
            continue
        out.changed.append(key)
    if out.changed:
        out.sets, out.dated = sets, True
    new_verify = _retarget_verify(values.get("verify"), values.get("from"),
                                  values.get("to"), date_from, date_to)
    if new_verify:
        out.verify, out.dated = new_verify, True
        out.changed.append("verify")
    return out


# ---------------------------------------------------------------------------
# The plan - decided BEFORE the browser is touched
# ---------------------------------------------------------------------------

@dataclass
class PlanItem:
    code: str
    title: str = ""
    spec: dict = None
    blocked: str = ""
    notes: list = field(default_factory=list)
    dates: str = ""

    @property
    def ready(self):
        return not self.blocked


def _describe_dates(df, dt):
    return "" if not df else (df if df == dt else f"{df}..{dt}")


def build_plan(codes, policy="yesterday", export="both", out_dir=None,
               profiles=None, today=None):
    """One PlanItem per selected screen: what will run, with which dates, or why
    it cannot run safely.

    Problems that can be known from the saved profile alone are reported HERE,
    not thirty minutes into a nightly run:
      * never recorded on this machine (only the shipped structure exists) -
        it would run with no division, which G-MES answers with zero rows and
        no error (GMES_SKILL.md gotcha #12);
      * remembers a date but no verify column - `run_screen()` refuses a
        date-constrained run it cannot check, so the replay is certain to fail.
    """
    date_from, date_to = resolve_dates(policy, today)
    by_code = {p.get("screen"): p for p in (profiles if profiles is not None
                                            else gmes_profile.known())
               if isinstance(p, dict)}
    plan = []
    for code in codes:
        profile = by_code.get(code)
        try:
            plan.append(_plan_one(code, profile, date_from, date_to, export, out_dir))
        except Exception as e:                               # noqa: BLE001
            # One profile that cannot be read must cost THAT screen its place in
            # the batch, not the whole plan (HISTORY.md Phase 84.7).
            plan.append(PlanItem(
                code=code, title=str((profile or {}).get("title") or "")
                if isinstance(profile, dict) else "",
                blocked=f"its saved profile could not be used ({type(e).__name__}: {e}) - "
                        "record it again"))
    return plan


def _plan_one(code, profile, date_from, date_to, export, out_dir):
    item = PlanItem(code=code, title=str((profile or {}).get("title") or ""))
    if profile is None:
        item.blocked = "not recorded - record it first"
        return item
    if not profile.get("learned"):
        item.blocked = ("only the shipped structure exists on this machine - "
                        "record it here first so a division and dates are remembered")
        return item
    values = gmes_profile.last_values(profile)
    r = retarget(values, date_from, date_to)
    remembered_range = bool(values.get("from"))
    if r.date_from and not values.get("verify"):
        item.blocked = ("it remembers a date but no verify column, so its "
                        "result could not be checked - record it again and "
                        "name a date column")
        return item
    if date_from is None and remembered_range and not values.get("verify"):
        item.blocked = "it remembers a date but no verify column - record it again"
        return item
    if date_from and not r.dated:
        item.notes.append("no date is remembered for this screen - it runs "
                          "on the screen's own dates")
    if r.sets is not None and not values.get("verify") and not r.date_from:
        item.notes.append("dates are typed, not verified against the rows")
    remembered_to = str(values.get("to") or "")
    if (r.date_from and remembered_to and remembered_to != str(values.get("from"))
            and r.date_from == r.date_to):
        # It was recorded over a period; a single-day policy collapses it to one
        # day. Visible here, before the run, because the result would otherwise
        # look complete (HISTORY.md Phase 84.7).
        item.notes.append(f"recorded over {values.get('from')}..{remembered_to} but this "
                          f"date policy runs ONE day ({r.date_from}) - use --date "
                          f"{values.get('from')}:{remembered_to} (or keep) for the period")
    spec = {"screen_code": code, "export": export, "close_after": True}
    if r.date_from:
        spec["date_from"], spec["date_to"] = r.date_from, r.date_to
    if r.sets is not None:
        spec["sets"] = r.sets
    if r.verify:
        spec["verify"] = r.verify
    if out_dir:
        spec["out_dir"] = out_dir
    item.spec = spec
    item.dates = _describe_dates(r.date_from or (date_from if r.sets is not None else None),
                                 r.date_to or (date_to if r.sets is not None else None))
    return item


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

def recover_between(ws, code, log=print):
    """Bring the session back to a known-good state after a failure. Returns
    (healthy, why-not).

    The screen that failed may have left a popup open, been kicked out of its
    session (HISTORY.md Phase 82.15), or still be sitting there half-filled.
    Each is cleared or recovered; the next screen only runs if the session is
    provably signed in afterwards."""
    try:
        core.recover_from_session_kick(ws, log=log)
    except Exception as e:                                   # noqa: BLE001
        return False, f"the session could not be recovered ({e})"
    try:
        gmes_common.close_child_popups(ws)
        signed_in, _who = gmes_common.is_logged_in(ws)
    except Exception as e:                                   # noqa: BLE001
        return False, f"G-MES could not be reached ({e})"
    if not signed_in:
        return False, "the session is signed out and could not be restored"
    try:                                # tidy: a failed screen is left open
        for row in gmes_open_screen.open_screens(ws).get("rows", []):
            if code.upper() in f"{row.get('pageUrl', '')} {row.get('menuId', '')}".upper():
                core.close_work_frame(ws, row["winId"])
    except Exception:                                        # noqa: BLE001
        pass                                # best effort - never fatal
    return True, ""


def _result(code, status, **kw):
    base = {"screen": code, "status": status, "ok": status == "ok", "rows": 0,
            "files": [], "error": None, "warnings": [], "seconds": 0.0, "dates": ""}
    base.update(kw)
    return base


MAX_RECONNECTS = 2


def run_batch(ws, plan, log=print, run=None, recover=None,
              max_consecutive_failures=MAX_CONSECUTIVE_FAILURES, clock=time.time,
              reconnect=None, max_reconnects=MAX_RECONNECTS):
    """Run the plan one screen at a time, isolating each.

    `run`, `recover` and `reconnect` are injectable so the decision logic is
    testable without a browser. Returns one result dict per PlanItem, always -
    a screen that was skipped or never reached is reported as such, never
    omitted.

    `reconnect()` -> a new connection (or None) is what lets a batch survive
    the automation browser dying mid-run (closed by a person, crashed, ended by
    security software): the remaining screens run in a fresh browser instead of
    being abandoned. At most `max_reconnects` times - a browser that keeps
    dying is a fault to report, not to paper over (HISTORY.md Phase 84.4).

    Ctrl+C ends the batch cleanly: the screen in progress is reported as
    interrupted, the rest as not run, and the caller still gets - and writes -
    a report of what was delivered."""
    run = run or core.run_screen
    recover = recover or recover_between
    results, streak, reconnects = [], 0, 0
    for index, item in enumerate(plan):
        if not item.ready:
            results.append(_result(item.code, "blocked", error=item.blocked,
                                   dates=item.dates))
            continue
        log(f"\n  [{index + 1}/{len(plan)}] {item.code}"
            + (f"  ({item.title})" if item.title else "")
            + (f"  dates {item.dates}" if item.dates else ""))
        started = clock()
        try:
            out = run(ws, log=log, **item.spec)
            res = _result(item.code, "ok" if out.get("ok") else "failed",
                          rows=out.get("rows", 0), files=list(out.get("files", [])),
                          warnings=list(out.get("warnings", [])),
                          error=out.get("error"), title=out.get("title", item.title))
            streak = 0 if res["ok"] else streak + 1
        except KeyboardInterrupt:
            log("  INTERRUPTED: stopping the batch and writing what was done")
            results.append(_result(item.code, "failed", error="interrupted by the user",
                                   title=item.title, dates=item.dates,
                                   seconds=round(clock() - started, 1)))
            for later in plan[index + 1:]:
                if later.ready:
                    results.append(_result(later.code, "not_run",
                                           error="not run: interrupted by the user",
                                           dates=later.dates))
                else:
                    results.append(_result(later.code, "blocked", error=later.blocked,
                                           dates=later.dates))
            return results
        except Exception as e:                               # noqa: BLE001
            log(f"  FAILED   : {e}")
            try:
                gmes_common.screenshot_on_failure(f"gmes_{item.code}")
            except Exception:                                # noqa: BLE001
                pass
            res = _result(item.code, "failed", error=str(e), title=item.title)
            streak += 1
        res["seconds"] = round(clock() - started, 1)
        res["dates"] = item.dates
        results.append(res)

        if res["ok"]:
            continue
        remaining = [p for p in plan[index + 1:]]
        gone = cdp_common.BROWSER_GONE_TEXT in (res.get("error") or "").lower()
        if gone and reconnect is not None and reconnects < max_reconnects and remaining:
            reconnects += 1
            log(f"  RECONNECT: the browser went away - starting it again and signing "
                f"in ({reconnects} of {max_reconnects})")
            try:
                new_ws = reconnect()
            except Exception as e:                           # noqa: BLE001
                new_ws = None
                log(f"  RECONNECT failed: {e}")
            if new_ws is not None:
                ws = new_ws
                healthy, why = True, ""
            else:
                healthy, why = False, "the browser went away and could not be restarted"
        else:
            healthy, why = recover(ws, item.code, log)
        stop = None
        if not healthy:
            stop = f"not run: {why}"
        elif streak >= max_consecutive_failures:
            stop = (f"not run: {streak} screens failed in a row, so the batch "
                    "stopped rather than keep querying a system that is not answering")
        if stop:
            for later in remaining:
                if later.ready:
                    results.append(_result(later.code, "not_run", error=stop,
                                           dates=later.dates))
                else:
                    results.append(_result(later.code, "blocked", error=later.blocked,
                                           dates=later.dates))
            log(f"  STOPPED  : {stop.replace('not run: ', '')}")
            break
    return results


def summarise(results):
    counts = {"ok": 0, "failed": 0, "blocked": 0, "not_run": 0}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return counts


def print_summary(results, log=print):
    log(f"\n{'=' * 78}\nBATCH SUMMARY\n{'=' * 78}")
    log(f"  {'SCREEN':<12} {'STATUS':<9} {'ROWS':>6}  {'DATES':<17} DETAIL")
    log("  " + "-" * 74)
    label = {"ok": "ok", "failed": "FAILED", "blocked": "skipped", "not_run": "not run"}
    for r in results:
        detail = (", ".join(os.path.basename(f) for f in r["files"]) if r["ok"]
                  else (r["error"] or ""))
        rows = r["rows"] if r["ok"] else "-"
        log(f"  {r['screen']:<12} {label[r['status']]:<9} {rows!s:>6}  "
            f"{r['dates'] or '-':<17} {detail}")
        for w in r.get("warnings", []):
            if "typed with --set" in w or "static content" in w or "client-side filter" in w:
                log(f"  {'':<12} {'':<9} {'':>6}  {'':<17} ! {w}")
    c = summarise(results)
    log(f"\n  {c['ok']} succeeded, {c['failed']} failed, {c['blocked']} skipped, "
        f"{c['not_run']} not run  (of {len(results)})")
    return c


def write_report(results, meta, directory=None):
    """A JSON record and a plain-text one of the batch, side by side. Returns
    the two paths. Written even when everything failed - an unattended 06:30
    run leaves nothing else to read."""
    directory = directory or REPORT_DIR
    os.makedirs(directory, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(directory, f"batch_{stamp}")
    payload = {"meta": meta, "summary": summarise(results), "results": results}
    with open(base + ".json", "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
    lines = [f"G-MES batch  {meta.get('started', '')}",
             f"  screens : {', '.join(meta.get('screens', []))}",
             f"  dates   : {meta.get('policy', '')}", ""]
    for r in results:
        lines.append(f"{r['screen']:<12} {r['status']:<8} rows={r['rows']:<6} {r['dates']}"
                     + (f"  {r['error']}" if r.get("error") else ""))
        for f in r.get("files", []):
            lines.append(f"{'':<12} {f}")
        for w in r.get("warnings", []):
            lines.append(f"{'':<12} ! {w}")
    with open(base + ".txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return base + ".json", base + ".txt"


def write_report_safely(results, meta, directory=None, log=print):
    """`write_report()`, but a report that cannot be written (disk full, a
    read-only or missing folder, a path that is a file) becomes a warning
    instead of a traceback. The run has already happened and its summary is
    printed; losing the exit code and the log line to a report failure would
    make an unattended night look like a crash (HISTORY.md Phase 84.6)."""
    try:
        return write_report(results, meta, directory)
    except Exception as e:                                   # noqa: BLE001
        log(f"  WARNING: the report could not be written ({type(e).__name__}: {e}) - "
            "the summary above is the only record of this run")
        return None, None


# ---------------------------------------------------------------------------
# Saved batches
# ---------------------------------------------------------------------------

def valid_name(name):
    return bool(name and _NAME.fullmatch(name))


def _batch_path(name):
    if not valid_name(name):
        raise ValueError("a batch name is letters, digits, - or _ (at most 40)")
    return os.path.join(BATCH_DIR, f"{name}.json")


def save_batch(name, codes, policy="yesterday", export="both", directory=None):
    """Remember a list of screens under a name. The date policy is remembered
    WITH it - what a schedule means by "yesterday" is a property of the batch,
    not of whoever creates the task."""
    if not codes:
        raise ValueError("a batch needs at least one screen")
    resolve_dates(policy)                                   # validate now, not at 06:30
    if export not in ("xlsx", "csv", "both"):
        raise ValueError(f"unknown export format: {export}")
    directory = directory or BATCH_DIR
    os.makedirs(directory, exist_ok=True)
    if not valid_name(name):
        raise ValueError("a batch name is letters, digits, - or _ (at most 40)")
    # Windows file names AND task names ignore case: saving "morning" beside an
    # existing "Morning" silently overwrote it (and would have replaced its
    # scheduled task too). Refuse, naming the one that exists (HISTORY.md 84.7).
    for existing in os.listdir(directory):
        if (existing.lower().endswith(".json") and existing[:-5] != name
                and existing[:-5].lower() == name.lower()):
            raise ValueError(f"a batch called {existing[:-5]!r} already exists - names "
                             f"are not case-sensitive, so {name!r} would overwrite it. "
                             "Use that spelling, or pick another name")
    data = {"name": name, "screens": list(codes), "date": policy, "export": export,
            "saved": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    path = os.path.join(directory, f"{name}.json")
    tmp = path + ".partial"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)
    return path


def load_batch(name, directory=None):
    directory = directory or BATCH_DIR
    if not valid_name(name):
        raise ValueError("a batch name is letters, digits, - or _ (at most 40)")
    path = os.path.join(directory, f"{name}.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise ValueError(f"there is no saved batch called {name!r}") from None


def list_batches(directory=None):
    """{name: batch dict}, skipping anything unreadable rather than failing."""
    directory = directory or BATCH_DIR
    out = {}
    try:
        names = os.listdir(directory)
    except OSError:
        return out
    for n in sorted(names):
        if n.lower().endswith(".json"):
            try:
                with open(os.path.join(directory, n), encoding="utf-8") as fh:
                    d = json.load(fh)
                if isinstance(d, dict) and d.get("screens"):
                    out[n[:-5]] = d
            except (OSError, ValueError):
                continue
    return out


def delete_batch(name, directory=None):
    directory = directory or BATCH_DIR
    if not valid_name(name):
        raise ValueError("a batch name is letters, digits, - or _ (at most 40)")
    try:
        os.unlink(os.path.join(directory, f"{name}.json"))
        return True
    except FileNotFoundError:
        return False


# ---------------------------------------------------------------------------
# Presenting the recorded screens
# ---------------------------------------------------------------------------

def describe_profile(profile):
    """One line of what a recording will do - shown next to its number, so a
    person choosing a batch can see what each entry means."""
    try:
        v = gmes_profile.last_values(profile)
        if v.get("from"):
            when = f"date {v['from']}" + (f"..{v['to']}" if v.get("to") and v["to"] != v["from"] else "")
        else:
            typed = [k for k, val in (v.get("sets") or {}).items() if date_role(k, val)]
            when = "typed date" if typed else "screen's own dates"
        return f"{v.get('division') or '-'}; {when}"
    except Exception:                                        # noqa: BLE001
        return "(its saved values could not be read)"


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def _recorded():
    profiles = gmes_profile.known()
    return profiles, [p["screen"] for p in profiles]


def resolve_request(selection, batch=None, policy=None, export=None):
    """Everything a run/plan/save/schedule needs decided from what was typed:
    (codes, policy, export). A saved batch supplies the defaults for the date
    policy and export format; anything typed beats it. Raises ValueError."""
    profiles, codes = _recorded()
    saved = list_batches()
    tokens = ([f"@{batch}"] if batch else []) + list(selection or [])
    if batch:
        load_batch(batch)                                   # a clear error if absent
    chosen = parse_selection(" ".join(tokens), codes,
                             {n: b["screens"] for n, b in saved.items()})
    base = saved.get(batch, {}) if batch else {}
    policy = policy or base.get("date") or "yesterday"
    export = export or base.get("export") or "both"
    resolve_dates(policy)                                   # fail now, not mid-batch
    return chosen, policy, export


def print_plan(plan, policy, log=print):
    date_from, date_to = resolve_dates(policy)
    what = ("each screen's own remembered dates" if date_from is None
            else (date_from if date_from == date_to else f"{date_from}..{date_to}"))
    log(f"\n  PLAN  -  {len(plan)} screen(s), dates: {what}\n")
    log(f"  {'#':>2}  {'SCREEN':<11} {'TITLE':<32} {'DATES':<17} WHAT")
    log("  " + "-" * 92)
    for n, item in enumerate(plan, start=1):
        what = (f"SKIPPED - {item.blocked}" if item.blocked
                else ("; ".join(item.notes) or "ready"))
        log(f"  {n:>2}  {item.code:<11} {item.title[:32]:<32} {item.dates or '-':<17} {what}")
    ready = sum(1 for i in plan if i.ready)
    log(f"\n  {ready} ready, {len(plan) - ready} skipped")
    return ready


def warn_unreadable(log=print):
    """Say which profile files were skipped and why. A recording that vanishes
    from the list with no word is the worst failure - "my recording
    disappeared" (HISTORY.md Phase 84.7)."""
    bad = gmes_profile.unreadable()
    if bad:
        log("\n  WARNING: these profile files could not be used and were skipped:")
        for path, why in bad:
            log(f"    {os.path.basename(path)}: {why}")


def cmd_list():
    profiles, _codes = _recorded()
    warn_unreadable()
    if not profiles:
        print("Nothing is recorded yet. Record a screen first with GMES_Workflow.bat.")
        return EXIT_OK
    print(f"\n  Recorded screens ({len(profiles)}):\n")
    print(f"  {'#':>2}  {'SCREEN':<11} {'TITLE':<34} WHAT IT REPLAYS")
    print("  " + "-" * 88)
    for n, p in enumerate(profiles, start=1):
        print(f"  {n:>2}  {p['screen']:<11} {(p.get('title') or '')[:34]:<34} {describe_profile(p)}")
    saved = list_batches()
    if saved:
        print(f"\n  Saved batches: " + ", ".join(
            f"{n} ({len(b['screens'])})" for n, b in saved.items()))
    return EXIT_OK


def _stop_browser(keep_open):
    cdp_common.stop_if_started_here(keep_open)


def cmd_run(args):
    try:
        codes, policy, export = resolve_request(args.selection, args.batch,
                                                args.date, args.export)
    except ValueError as e:
        print(f"ERROR: {e}")
        return EXIT_USAGE
    started = datetime.now()
    out_dir = args.output_dir
    if not out_dir and not args.flat:
        out_dir = os.path.join(core.OUTPUT_DIR, f"batch_{started:%Y%m%d_%H%M%S}")
    plan = build_plan(codes, policy, export, out_dir)
    ready = print_plan(plan, policy)
    warn_unreadable()
    meta = {"started": started.strftime("%Y-%m-%d %H:%M:%S"), "policy": policy,
            "dates": resolve_dates(policy), "screens": codes, "export": export,
            "output_dir": out_dir, "unattended": bool(args.unattended),
            "batch": args.batch}
    if args.dry_run:
        print("\n  (plan only - nothing was run)")
        return EXIT_OK

    gmes_log.start("gmes_batch" + (" (unattended)" if args.unattended else ""))
    if not ready:
        results = [_result(i.code, "blocked", error=i.blocked, dates=i.dates) for i in plan]
        print_summary(results)
        print("  report:", write_report_safely(results, meta)[1])
        gmes_log.finish("nothing could run")
        return EXIT_FAILED

    try:
        lock_token = core.acquire_run_lock()
    except core.RunLocked as e:
        print(f"ERROR: {e}")
        gmes_log.finish("skipped: another run holds the browser")
        return EXIT_BUSY
    try:
        # sign_in() starts a browser whether or not it succeeds, so the browser
        # is stopped on EVERY way out below - a failed sign-in at 06:30 must not
        # leave a Chrome behind for each night it fails (HISTORY.md Phase 83).
        try:
            if not core.sign_in():
                print("\nSign-in failed twice. Nothing was run.")
                gmes_log.finish("sign-in failed")
                return EXIT_NO_SIGN_IN
            live = []                       # every connection opened, so all get closed

            def reconnect():
                """A browser that died mid-batch: start it again, sign in, go on."""
                if not core.sign_in():
                    return None
                live.append(core.connect())
                return live[-1]

            try:
                live.append(core.connect())
                results = run_batch(live[0], plan, reconnect=reconnect)
            finally:
                for connection in live:
                    try:
                        connection.close()
                    except Exception:                        # noqa: BLE001
                        pass                # a dead browser's socket - nothing to do
        finally:
            _stop_browser(args.keep_open)
    finally:
        core.release_run_lock(lock_token)

    counts = print_summary(results)
    json_path, txt_path = write_report_safely(results, meta)
    print(f"\n  files  : {out_dir or core.OUTPUT_DIR}")
    if txt_path:
        print(f"  report : {txt_path}")
    all_ok = counts["ok"] == len(results)
    gmes_log.finish(f"{counts['ok']}/{len(results)} ok")
    return EXIT_OK if all_ok else EXIT_FAILED


def cmd_plan(args):
    try:
        codes, policy, export = resolve_request(args.selection, args.batch,
                                                args.date, args.export)
    except ValueError as e:
        print(f"ERROR: {e}")
        return EXIT_USAGE
    print_plan(build_plan(codes, policy, export), policy)
    warn_unreadable()
    return EXIT_OK


def cmd_save(args):
    try:
        codes, policy, export = resolve_request(args.selection, None,
                                                args.date, args.export)
        path = save_batch(args.name, codes, policy, export)
    except ValueError as e:
        print(f"ERROR: {e}")
        return EXIT_USAGE
    print(f"  saved batch {args.name!r}: {len(codes)} screen(s), dates {policy}, export {export}")
    print(f"  {', '.join(codes)}")
    return EXIT_OK


def cmd_batches():
    saved = list_batches()
    if not saved:
        print("No saved batches. Make one with:  python gmes_batch.py save NAME 1,3,5-7")
        return EXIT_OK
    for name, b in saved.items():
        print(f"  {name:<20} {len(b['screens']):>2} screen(s)  dates {b.get('date', 'yesterday'):<10} "
              f"export {b.get('export', 'both')}")
        print(f"  {'':<20} {', '.join(b['screens'])}")
    return EXIT_OK


def cmd_schedule(args):
    import gmes_schedule
    try:
        when = gmes_schedule.parse_when(args.at, args.daily, args.weekdays,
                                        args.days, args.once)
        if args.selection or args.date or args.export:
            # A typed selection DEFINES the batch (exactly like `save`) - it is
            # never merged with a saved one of the same name, or "schedule
            # morning 1,3" would quietly also run whatever @morning held.
            # Only --date/--export alone means "the saved screens, new policy".
            base = None if args.selection else args.name
            codes, policy, export = resolve_request(args.selection, base,
                                                    args.date, args.export)
            save_batch(args.name, codes, policy, export)
        else:
            load_batch(args.name)                           # must already exist
        gmes_schedule.create(args.name, when)
    except (ValueError, gmes_schedule.ScheduleError) as e:
        print(f"ERROR: {e}")
        return EXIT_USAGE
    b = load_batch(args.name)
    print(f"  scheduled {args.name!r}: {gmes_schedule.describe_when(when)}")
    print(f"  runs {len(b['screens'])} screen(s), dates {b.get('date', 'yesterday')}: "
          f"{', '.join(b['screens'])}")
    print("  It runs only while you are signed in to Windows (the saved credentials and the "
          "browser need your session).")
    print("  Change what it runs by re-saving the batch; remove it with:  "
          f"python gmes_batch.py unschedule {args.name}")
    return EXIT_OK


def cmd_schedules(tasks=None):
    """`tasks`, when given, is already-fetched (`gmes_schedule.list_tasks()`)
    - lets a caller that also needs the list itself (the interactive "View
    schedules" picker) print this exact table without a second Task
    Scheduler round trip."""
    import gmes_schedule
    if tasks is None:
        try:
            tasks = gmes_schedule.list_tasks()
        except gmes_schedule.ScheduleError as e:
            print(f"ERROR: {e}")
            return EXIT_USAGE
    if not tasks:
        print("Nothing is scheduled.")
        return EXIT_OK
    print(f"\n  {'BATCH':<18} {'STATE':<9} {'NEXT RUN':<20} {'LAST RUN':<20} LAST RESULT")
    print("  " + "-" * 86)
    warnings = []
    for t in tasks:
        last = "-" if not t["last_run"] else (
            f"{t['last_text']} ({t['last_hex']})" if t["last_ok"] is not True else "ok")
        print(f"  {t['batch']:<18} {t['state']:<9} {t['next_run'].replace('T', ' ') or '-':<20} "
              f"{t['last_run'].replace('T', ' ') or '-':<20} {last}")
        for note in gmes_schedule.assess_task(t):
            warnings.append(f"  ! {t['batch']}: {note}")
    if warnings:
        print("\n" + "\n".join(warnings))
    return EXIT_OK


def cmd_unschedule(args):
    import gmes_schedule
    try:
        removed = gmes_schedule.delete(args.name)
    except (ValueError, gmes_schedule.ScheduleError) as e:
        print(f"ERROR: {e}")
        return EXIT_USAGE
    print(f"  {'removed the schedule for' if removed else 'nothing was scheduled for'} {args.name!r} "
          "(the saved batch itself is kept)")
    return EXIT_OK


def cmd_run_scheduled(args):
    import gmes_schedule
    try:
        gmes_schedule.run_now(args.name)
    except (ValueError, gmes_schedule.ScheduleError) as e:
        print(f"ERROR: {e}")
        return EXIT_USAGE
    print(f"  started the scheduled task for {args.name!r}; follow it in logs\\scheduled_{args.name}.log")
    return EXIT_OK


def build_parser():
    parser = argparse.ArgumentParser(
        prog="gmes_batch.py",
        description="Replay several recorded G-MES screens together - now, a chosen "
                    "few, or on a schedule. Selection: all, 1,3,5-7, screen codes, "
                    "@savedbatch, and !X to exclude.")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, selection=True):
        if selection:
            p.add_argument("selection", nargs="*", help="what to run, e.g. all  |  1,3,5-7  |  Q2111UM00 P3111UM00  |  all !3")
        p.add_argument("--date", metavar="POLICY", help=f"dates to use: {POLICY_HELP}")
        p.add_argument("--export", choices=("xlsx", "csv", "both"), help="default: both")

    sub.add_parser("list", help="show the recorded screens, numbered")
    p = sub.add_parser("plan", help="show what would run - no browser, nothing touched")
    common(p)
    p.add_argument("--batch", help="start from a saved batch")

    p = sub.add_parser("run", help="run now")
    common(p)
    p.add_argument("--batch", help="start from a saved batch")
    p.add_argument("--output-dir", help="where the files go (default: a batch_<time> folder)")
    p.add_argument("--flat", action="store_true", help="put files straight in the usual output folder")
    p.add_argument("--dry-run", action="store_true", help="same as plan: show, do not run")
    p.add_argument("--keep-open", action="store_true", help="leave the browser open afterwards")
    p.add_argument("--unattended", action="store_true", help="marks the run as scheduled (recorded in the report)")

    p = sub.add_parser("save", help="save a list of screens under a name")
    p.add_argument("name")
    common(p)

    sub.add_parser("batches", help="show the saved batches")
    p = sub.add_parser("delete", help="delete a saved batch")
    p.add_argument("name")

    p = sub.add_parser("schedule", help="run a batch automatically on a schedule")
    p.add_argument("name", help="the batch name (created from the selection if given)")
    common(p)
    p.add_argument("--at", required=True, metavar="HH:MM", help="time of day, 24 hour")
    p.add_argument("--daily", action="store_true")
    p.add_argument("--weekdays", action="store_true", help="Monday to Friday")
    p.add_argument("--days", metavar="mon,wed,fri")
    p.add_argument("--once", metavar="YYYY-MM-DD")

    sub.add_parser("schedules", help="show what is scheduled")
    p = sub.add_parser("unschedule", help="remove a schedule (the batch is kept)")
    p.add_argument("name")
    p = sub.add_parser("run-scheduled", help="start a scheduled task right now")
    p.add_argument("name")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "delete":
        try:
            ok = delete_batch(args.name)
        except ValueError as e:
            print(f"ERROR: {e}")
            return EXIT_USAGE
        print(f"  {'deleted' if ok else 'there was no'} batch {args.name!r}")
        return EXIT_OK
    handlers = {"list": lambda: cmd_list(), "plan": lambda: cmd_plan(args),
                "run": lambda: cmd_run(args), "save": lambda: cmd_save(args),
                "batches": lambda: cmd_batches(), "schedule": lambda: cmd_schedule(args),
                "schedules": lambda: cmd_schedules(), "unschedule": lambda: cmd_unschedule(args),
                "run-scheduled": lambda: cmd_run_scheduled(args)}
    return handlers[args.command]()


if __name__ == "__main__":
    sys.exit(main())
