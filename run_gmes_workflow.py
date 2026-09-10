"""
The G-MES report tool, for people - the front end behind GMES_Workflow.bat.

    python run_gmes_workflow.py
    (or double-click GMES_Workflow.bat)

Five short questions, then the work, narrated as numbered steps.

The one idea worth understanding
--------------------------------
The tool has a MEMORY. The first time a screen is used it works everything
out from the screen itself and, if the run fully succeeds, writes down the
two things it cannot work out again - which box is the "from" date, and which
table holds the results. That is the RECORDING phase, and it happens by
itself; there is no separate command.

Every run after that is the REPLAYING phase: it checks the screen still
matches what it wrote down, and reuses it. If anything has moved it says so
and reads the screen from scratch instead. It never quietly guesses.

The banner before the work says which of the two is about to happen.

All of the drawing lives in gmes_ui, which degrades to plain ASCII when the
console cannot do better. Presentation never decides anything.
"""
import os
import sys
import time

# Proxy bypass is applied by importing cdp_common - see SKILL.md gotcha #1.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cdp_common  # noqa: E402
import gmes_core as core  # noqa: E402
import gmes_open_screen  # noqa: E402
import gmes_profile  # noqa: E402
import gmes_ui as ui  # noqa: E402


# ---------------------------------------------------------------------------
# Asking
# ---------------------------------------------------------------------------

def clean(raw):
    """Strip whitespace and a stray BOM, which shows up on the first line
    read from some piped stdin sources."""
    return raw.strip().lstrip("﻿").strip()


def ask(label, hint="", default=""):
    """Ask one question and ECHO what came back.

    The echo is not decoration. It confirms what the tool understood - which
    is where a date typed 2026-09-09 is shown back as 20260909 - and it is
    the only way the answers are visible at all when this is driven from a
    script rather than a keyboard."""
    tail = f"  {ui.GREY}{hint}{ui.RESET}" if hint else ""
    try:
        value = clean(input(f"    {ui.CYAN}{ui.ARROW}{ui.RESET} {label}{tail}\n      "
                            f"{ui.BOLD}> {ui.RESET}")) or default
    except EOFError:
        value = default
    shown = value if value else "(skipped)"
    colour = ui.WHITE if value else ui.GREY
    print(f"      {ui.GREEN}{ui.TICK}{ui.RESET} {colour}{shown}{ui.RESET}\n")
    return value


class Questions:
    """Numbers the questions as they are actually asked.

    The numbers used to be written into the labels, so a screen with no date
    fields - where the "To date" question is never reached - counted 1, 2, 3,
    5. A visible gap in a numbered list reads as something having gone
    wrong."""

    def __init__(self):
        self.asked = 0

    def ask(self, label, hint="", default=""):
        self.asked += 1
        return ask(f"{self.asked}. {label}", hint, default)

    def again(self, label, hint="", default=""):
        """Re-ask after a bad answer. The number stays put - a mistyped date
        is not a new question, and renumbering makes it look like one."""
        return ask(f"{self.asked}. {label}", hint, default)


def pause():
    try:
        input(f"\n  {ui.GREY}Press Enter to close...{ui.RESET}")
    except EOFError:
        pass


# ---------------------------------------------------------------------------
# The run narration
#
# core.run_screen() reports each thing it does as "  key      : detail".
# This turns those into numbered steps in plain words. An unrecognised key is
# printed as-is rather than swallowed: a display layer must never be the
# reason something goes unseen.
# ---------------------------------------------------------------------------

STEP_LABELS = {
    "screen": "Open the screen",
    "filters": "Read what the screen offers",
    "results": "Find the results table",
    "option": "Set a screen option",
    "division": "Tick the division",
    "dates": "Type the dates in",
    "cleared": "Clear leftovers from last time",
    "filter": "Set a filter",
    "inquiry": "Press Inquiry and wait for the answer",
    "verified": "Check the rows really match",
    "dates in": "Dates that came back",
    "excel": "Download the Excel file",
    "csv": "Save a readable copy (CSV)",
    "tab": "Close the screen tab",
    "dry run": "Stop here - Inquiry NOT pressed",
}

MEMORY_KEYS = ("learned", "changed")
NOTE_KEYS = {"found": "found in the menu", "popups": "cleared popups"}


class Narrator:
    """Prints core's progress as numbered steps, with a time for each."""

    def __init__(self):
        self.step = 0
        self.last = time.time()

    def __call__(self, text):
        raw = (text or "").rstrip()
        if not raw.strip() or set(raw.strip()) <= {"=", "-"} or ":" not in raw:
            return                                  # core's own rules/banners
        key, _, detail = raw.partition(":")
        key, detail = key.strip(), detail.strip()

        if key in MEMORY_KEYS:
            self.memory(key, detail)
            return
        if key in NOTE_KEYS:
            ui.note(f"{NOTE_KEYS[key]}: {detail}")
            return
        if key == "warning":
            ui.note(detail, "warn")
            return
        if key == "FAILED":
            print()
            ui.note(f"STOPPED: {detail}", "bad")
            return

        label = STEP_LABELS.get(key)
        if label is None:
            print(f"      {ui.GREY}{raw.strip()}{ui.RESET}")   # unknown: show it
            return
        self.step += 1
        now = time.time()
        ui.step(self.step, label, detail, seconds=now - self.last)
        self.last = now

    def memory(self, key, detail):
        if key == "changed":
            ui.note(f"the screen changed: {detail}", "warn")
        elif detail.lower().startswith("saved to"):
            self.step += 1
            now = time.time()
            ui.step(self.step, "Remember this screen for next time", detail,
                    seconds=now - self.last)
            self.last = now
        elif detail.lower().startswith("ignored"):
            ui.note(detail, "warn")
        else:
            ui.note(f"using memory: {detail}")


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------

def question_screen(q, ws):
    """Which screen. Accepts 'find <words>' so a UI number is not required up
    front - not knowing the number is the most common way to be stuck."""
    first = True
    while True:
        prompt = q.ask if first else q.again
        first = False
        answer = prompt("Which screen?", "a UI number, or:  find <words>")
        if not answer:
            ui.note("A screen is needed to continue.", "warn")
            continue

        if answer.lower().startswith("find"):
            query = answer[4:].strip()
            if not query:
                ui.note("Try:  find production plan", "warn")
                continue
            found = gmes_open_screen.catalogue(ws, query)
            rows = found.get("rows", [])
            if not rows:
                ui.note(f"Nothing matches '{query}' in the "
                        f"{found.get('total')} screens you can open.", "warn")
                continue
            print()
            for row in rows[:12]:
                print(f"      {ui.CYAN}{row['screenId']:<12}{ui.RESET} {row['menuTitle']}")
            print()
            continue

        return answer.upper()


def question_dates(q):
    """Both dates are typed by the person. Nothing is worked out from today's
    date - that is a later feature, deliberately not guessed at now.

    They are validated here, while the keyboard is still in reach: a date
    written straight through unchecked reaches a field that stores YYYYMMDD
    and the query then quietly answers a different question."""
    def one(label):
        first = True
        while True:
            prompt = q.ask if first else q.again
            first = False
            raw = prompt(label, "YYYYMMDD or YYYY-MM-DD, blank = leave as-is")
            if not raw:
                return None
            try:
                value = core.normalise_date(raw)
                if value != raw:
                    ui.note(f"read as {value}")
                return value
            except ValueError as e:
                ui.note(str(e), "warn")

    date_from = one("From date")
    if not date_from:
        return None, None
    date_to = one("To date")
    if not date_to:
        date_to = date_from
        ui.note(f"no end date given - using {date_to}")
    return date_from, date_to


def question_filters(q):
    """Optional. Most runs need nothing here."""
    answer = q.ask("Any extra filter?",
                   "Name=Value, e.g. Production Order=011074232146, blank = none")
    if not answer or "=" not in answer:
        if answer:
            ui.note("That is not Name=Value - skipping it.", "warn")
        return {}
    key, value = (part.strip() for part in answer.split("=", 1))
    return {key: value} if key and value else {}


# ---------------------------------------------------------------------------

def sign_in_quietly():
    """Sign in, showing one line instead of the sign-in tool's own report.

    The detail is captured rather than discarded, and printed in full the
    moment anything goes wrong - a quiet front end must never be the reason a
    failure is harder to diagnose than it was before."""
    import io
    from contextlib import redirect_stdout

    ui.section("Connection")
    print(f"    {ui.GREY}Signing in to G-MES...{ui.RESET}")
    captured = io.StringIO()
    try:
        with redirect_stdout(captured):
            ok = core.sign_in()
    except Exception as e:
        print(captured.getvalue())
        ui.note(f"Could not sign in: {e}", "bad")
        return False

    if ok:
        who = ""
        for row in captured.getvalue().splitlines():
            if "igned in as" in row:            # "Signed in" / "Already signed in"
                who = row.split("as", 1)[1].strip().strip(".'\"")
        ui.field("Signed in", who or "yes")
        return True

    print(captured.getvalue())
    ui.note("Could not sign in. Nothing was run.", "bad")
    return False


def main():
    ui.banner("G-MES AUTOMATION", "Report extraction  -  answer 5 questions, "
                                  "the rest is automatic")

    if not sign_in_quietly():
        pause()
        return 1

    ws = core.connect()
    try:
        ui.section("What do you want?")
        print()
        q = Questions()
        code = question_screen(q, ws)
        division = q.ask("Division", "e.g. VD, blank = none")
        date_from, date_to = question_dates(q)
        sets = question_filters(q)

        ui.section("Plan")
        ui.field("Screen", code)
        ui.field("Division", division or "(none)")
        ui.field("Period", f"{date_from} to {date_to}" if date_from
                 else "(leave the screen's own dates)")
        for key, value in sets.items():
            ui.field("Filter", f"{key} = {value}")
        ui.field("Output", core.OUTPUT_DIR)

        profile = gmes_profile.load(code)
        ui.phase(profile is None, code, (profile or {}).get("learned", ""))

        if ask("Press Enter to start", "or type n to cancel",
               default="y").lower().startswith("n"):
            ui.note("Cancelled. Nothing was run.", "warn")
            pause()
            return 1

        ui.section("Execution")
        results = core.run_many(ws, [{
            "screen_code": code, "division": division or None,
            "date_from": date_from, "date_to": date_to, "sets": sets,
            "export": "both", "out_dir": core.OUTPUT_DIR,
        }], log=Narrator())

        r = results[0]
        if r["ok"]:
            ui.result(True, f"COMPLETE  {ui.DOT}  {r['rows']:,} rows", [
                f"{ui.GREY}in {r.get('seconds', '?')}s{ui.RESET}", ""]
                + [f"{ui.GREEN}{ui.TICK}{ui.RESET} {os.path.basename(p)}"
                   for p in r["files"]]
                + ["", f"{ui.GREY}{core.OUTPUT_DIR}{ui.RESET}", "",
                   (f"{ui.GREY}This screen is now learned - next time it "
                    f"replays.{ui.RESET}") if profile is None else
                   (f"{ui.GREY}Memory used, and refreshed.{ui.RESET}")])
        else:
            ui.result(False, "DID NOT FINISH", [
                r["error"], "",
                f"{ui.GREY}Nothing was saved. A screenshot of the failure is "
                f"in the project folder.{ui.RESET}"])
        pause()
        return 0 if r["ok"] else 1
    finally:
        ws.close()


if __name__ == "__main__":
    sys.exit(main())
