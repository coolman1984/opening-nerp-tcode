"""
What the interactive front end shows about things that are ALREADY on disk -
saved reports, past runs and their files - plus plain-language error
explanations. Offline by construction: nothing here imports a browser path,
signs in, or reads exported production data (only the run reports under the
git-ignored `logs/batches/`, which hold counts, codes and file names).

HISTORY.md Phase 93 (CLI_UI_IMPROVEMENT_PLAN.md Milestones B-C). Kept apart
from `run_gmes_workflow.py` so each rule here is a pure function with a test,
and so the same wording can be reused by any later surface. Presentation
only - nothing here decides how a report is RUN; that stays in gmes_core /
gmes_batch (CLAUDE.md section 0: there is one engine).
"""
import json
import os

import gmes_batch
import gmes_profile

# ---------------------------------------------------------------------------
# One status model, in the user's words (CLI_UI_IMPROVEMENT_PLAN.md,
# "Status language")
# ---------------------------------------------------------------------------

READY = "Ready"
READY_WARN = "Ready with warning"
LAST_FAILED = "Last run failed"
NOT_TRIED = "Not yet run here"


def run_history(directory=None):
    """Every past run report, newest first. Unreadable reports are skipped,
    never fatal - one damaged file must not hide the rest."""
    directory = directory or gmes_batch.REPORT_DIR
    try:
        names = sorted((n for n in os.listdir(directory)
                        if n.startswith("batch_") and n.endswith(".json")), reverse=True)
    except OSError:
        return []
    out = []
    for name in names:
        path = os.path.join(directory, name)
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            results = list(data["results"])
            counts = dict(data["summary"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        meta = data.get("meta") or {}
        summary = path[:-len(".json")] + "_summary.html"
        out.append({"path": path, "started": meta.get("started", ""),
                    "name": meta.get("batch") or "", "policy": meta.get("policy", ""),
                    "output_dir": meta.get("output_dir") or "",
                    "warnings": list(meta.get("warnings") or []),
                    "counts": counts, "total": len(results), "results": results,
                    "summary": summary if os.path.isfile(summary) else None})
    return out


def last_result_by_code(history):
    """{screen code: (started, result)} - the newest result each code has."""
    seen = {}
    for run in history:                               # newest first
        for r in run["results"]:
            code = str(r.get("screen", "")).upper()
            if code and code not in seen and r.get("status") in ("ok", "failed"):
                seen[code] = (run["started"], r)
    return seen


def report_card(profile, last=None):
    """A saved report as the person choosing it needs to see it:
    {code, title, status, why, settings, last_run}."""
    code = profile.get("screen", "?")
    try:
        values = gmes_profile.last_values(profile)
    except Exception:                                        # noqa: BLE001
        values = {}
    division = values.get("division") or ""
    if values.get("from"):
        period = values["from"] + (f" to {values['to']}"
                                   if values.get("to") and values["to"] != values["from"] else "")
        settings = f"date {period}"
    else:
        typed = [k for k, v in (values.get("sets") or {}).items() if gmes_batch.date_role(k, v)]
        settings = "a typed date" if typed else "the screen's own dates"
    if division:
        settings = f"{division}, {settings}"

    if values.get("from") and values.get("verify"):
        status, why = READY, "the report date is checked in the results"
    elif values.get("from"):
        status, why = READY_WARN, "will ask once which column holds the date"
    elif typed_date(values):
        status, why = READY_WARN, "the date is typed into the screen but not checked in the results"
    else:
        status, why = READY, "uses the dates the screen shows by itself"
    if not profile.get("learned"):
        status, why = NOT_TRIED, "shipped with the tool; the first run here sets it up"

    last_run = ""
    if last:
        started, r = last
        if r.get("status") == "ok":
            last_run = f"last run {started}: {int(r.get('rows') or 0):,} rows"
        else:
            status = LAST_FAILED
            why = explain_error(r.get("error") or "")[0]
            last_run = f"last run {started}: did not finish"
    return {"code": code, "title": profile.get("title") or "", "status": status,
            "why": why, "settings": settings, "last_run": last_run}


def typed_date(values):
    return any(gmes_batch.date_role(k, v) for k, v in (values.get("sets") or {}).items())


def search(cards, text):
    """Cards whose code, title or settings hold EVERY word typed, any case."""
    words = [w for w in (text or "").lower().split() if w]
    if not words:
        return list(cards)
    return [c for c in cards
            if all(w in f"{c['code']} {c['title']} {c['settings']}".lower() for w in words)]


def page_of(items, page, size=10):
    """(visible, first_number, last_number, total, page, pages) - a page never
    hides that more exists: the total always travels with it."""
    total = len(items)
    pages = max(1, -(-total // size))
    page = min(max(0, page), pages - 1)
    start = page * size
    visible = items[start:start + size]
    return visible, start + 1, start + len(visible), total, page, pages


# ---------------------------------------------------------------------------
# Errors, in words a person can act on (plan: "Error translation")
# ---------------------------------------------------------------------------

# (words to look for, what happened, what to do). First match wins, so the
# specific families come before the general ones. Matching is on the
# ENGINE's own English message - the message itself is always kept and shown
# underneath as the technical detail, never replaced.
_FAMILIES = (
    (("another g-mes run already", "lock held by"),
     "Another report is already running on this PC.",
     "Wait for it to finish, then try again."),
    (("pc's clock", "pc clock"),
     "This PC's date or time is wrong, so 'yesterday' would be the wrong day.",
     "Fix the date and time in Windows settings, then run again."),
    (("could not sign in", "sign-in failed", "ad sso", "samsung sso", "refused the credentials",
      "not signed in"),
     "Signing in to G-MES did not work.",
     "Try once more. If it keeps failing, check your password still works in G-MES itself."),
    (("connection to the automation browser was lost", "browser went away"),
     "The report window closed or crashed while it was working.",
     "Run the report again - nothing wrong was saved."),
    (("shape changed", "predates opening-shape", "controls have changed"),
     "G-MES has changed this screen since it was set up.",
     "Set the report up again: choose 'Set up a new report' and pick the same code."),
    (("refusing to export the wrong data", "the results carry", "outside the requested"),
     "The results did not match what was asked for (usually the date), so nothing was saved.",
     "Check the dates and run again. If it repeats, the screen may need setting up again."),
    (("interrupted by another pc", "session was interrupted"),
     "Someone signed in to G-MES with the same account on another PC.",
     "Run the report again once the other session is closed."),
    (("had not settled", "never finished building", "not answering",
      "failed in a row"),
     "G-MES was too slow or did not answer.",
     "Try again later - the system may be busy."),
    (("winerror 32", "being used by another process", "permissionerror",
      "access is denied"),
     "The file or folder is in use or cannot be written.",
     "Close the file if it is open in Excel, then run again."),
    (("no complete .xlsx", "save to excel", "excel download icon", "not an xlsx"),
     "The Excel download did not arrive.",
     "Run again. The CSV copy, when there is one, is still complete."),
    (("dialog opened instead of results",),
     "G-MES showed a message instead of results.",
     "Read the message in the details below - usually a filter or date needs changing."),
    (("no rows", "contains no rows", "no data"),
     "The report came back empty.",
     "Try a wider date range - there may simply be nothing for that day."),
    (("not run:",),
     "This report was not started, because the run stopped earlier.",
     "See the first failure in the list; fixing it usually fixes the rest."),
)


def explain_error(text):
    """(what happened, what to do) for an engine message, in plain words."""
    low = (text or "").lower()
    for words, what, do in _FAMILIES:
        if any(w in low for w in words):
            return what, do
    return ("The report stopped with a problem the tool does not recognise.",
            "Run it again once. If it fails again, send the log file to whoever supports this tool.")


# ---------------------------------------------------------------------------
# Opening a file or folder the tool produced
# ---------------------------------------------------------------------------

def open_path(path, opener=None):
    """Open a file or folder with Windows' own default program -> (ok, message).

    Only a path that exists is opened, and only through the operating
    system's file association (never the automation browser, never a shell
    command line built from text). Elsewhere, or if Windows refuses, the path
    is returned for the person to open themselves."""
    if not path or not os.path.exists(path):
        return False, f"not found: {path or '(nothing to open)'}"
    opener = opener or getattr(os, "startfile", None)
    if opener is None:
        return False, f"open it yourself: {path}"
    try:
        opener(path)
    except OSError as e:
        return False, f"Windows could not open it ({e}): {path}"
    return True, f"opened {path}"


# ---------------------------------------------------------------------------
# Help, by task rather than by module (plan: "Help and Support Package")
# ---------------------------------------------------------------------------

HELP_TOPICS = (
    ("Run yesterday's report",
     "Choose 1 (Run a saved report), pick it by number, and press Enter at "
     "'Run it?'. The date it uses is shown before anything runs."),
    ("Find a report when I do not know its code",
     "Choose 4 (Saved reports) and type any word from its name, e.g. 'plan'. "
     "For a report never used here, choose 2 and type: find <words>."),
    ("Change the date or division of a saved report",
     "Run it (1), and at 'Run it?' type change instead of pressing Enter."),
    ("Run several reports at once",
     "Choose 3. Pick numbers such as 1,3,5-7, or 'all'. Ten or more ask you "
     "to type a confirmation, so nothing big starts by accident."),
    ("Run reports every night by themselves",
     "Choose 3, pick the reports, then choose 'schedule'. The PC must be on "
     "and you must be signed in to Windows at that time. The next morning, "
     "the Home screen shows how the night went."),
    ("What does 'Ready with warning' mean?",
     "The report runs, but the tool cannot prove from the results that they "
     "are for the day you asked. Everything else is still checked."),
    ("Where are my files?",
     "Choose 6 (Recent runs and files) and pick a run - it can open the "
     "folder for you."),
    ("Something failed",
     "The message says what happened and what to do. The full detail is in "
     "the log file named at the top of the screen, for whoever supports this tool."),
)
