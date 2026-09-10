"""
The G-MES report tool, for people - the front end behind GMES_Workflow.bat.

    python run_gmes_workflow.py
    (or double-click GMES_Workflow.bat)

It asks five short questions, then does the work and narrates it as numbered
steps, so it is always clear what is happening and how far along it is.

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

The banner before each run says which of the two is about to happen.

Everything is printed in plain ASCII on purpose: this runs in cmd.exe on
locked-down corporate machines, where a fancy box-drawing character can
arrive as a question mark or crash the print outright.
"""
import os
import sys

# Proxy bypass is applied by importing cdp_common - see SKILL.md gotcha #1.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cdp_common  # noqa: E402
import gmes_core as core  # noqa: E402
import gmes_open_screen  # noqa: E402
import gmes_profile  # noqa: E402

WIDTH = 72


# ---------------------------------------------------------------------------
# Small presentation helpers
# ---------------------------------------------------------------------------

def line(char="-"):
    print("  " + char * (WIDTH - 4))


def banner(title, subtitle=""):
    print()
    line("=")
    print(f"   {title}")
    if subtitle:
        print(f"   {subtitle}")
    line("=")


def clean(raw):
    """Strip whitespace and a stray BOM, which shows up on the first line
    read from some piped stdin sources."""
    return raw.strip().lstrip("﻿").strip()


def ask(label, hint="", default=""):
    """Ask one question and ECHO what came back.

    The echo is not decoration. It confirms what the tool understood, which
    is where a date like 2026-09-09 gets shown back as 20260909 - and it is
    the only way the answers are visible at all when this is driven from a
    script rather than a keyboard."""
    prompt = f"    {label}"
    if hint:
        prompt += f"  ({hint})"
    prompt += ": "
    try:
        value = clean(input(prompt)) or default
    except EOFError:
        value = default
    print(f"      -> {value if value else '(skipped)'}")
    return value


def pause():
    try:
        input("\n  Press Enter to close...")
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

# Said once, loudly, rather than as a step: these are the memory.
MEMORY_KEYS = ("learned", "changed")

# Worth showing, but not a step of its own - they would pad the list without
# telling anyone anything they need to act on.
NOTE_KEYS = {"found": "found in the menu", "popups": "cleared popups"}


class Narrator:
    """Prints core's progress as numbered steps."""

    def __init__(self):
        self.step = 0

    def __call__(self, text):
        raw = (text or "").rstrip()
        if not raw.strip() or set(raw.strip()) <= {"=", "-"}:
            return                                  # core's own rules/banners
        if ":" not in raw:
            return
        key, _, detail = raw.partition(":")
        key, detail = key.strip(), detail.strip()

        if key in MEMORY_KEYS:
            self.memory(key, detail)
            return
        if key in NOTE_KEYS:
            print(f"      [i] {NOTE_KEYS[key]}: {detail}")
            return
        if key == "warning":
            print(f"      note: {detail}")
            return
        if key == "FAILED":
            print()
            print(f"    [X] STOPPED: {detail}")
            return

        label = STEP_LABELS.get(key)
        if label is None:
            print(f"    {raw.strip()}")            # unknown - show it anyway
            return
        self.step += 1
        dots = "." * max(3, 40 - len(label))
        print(f"    {self.step:>2}. {label} {dots} {detail}")

    def memory(self, key, detail):
        if key == "changed":
            print(f"      [!] the screen changed: {detail}")
        elif detail.lower().startswith("saved to"):
            self.step += 1
            label = "Remember this screen for next time"
            dots = "." * max(3, 40 - len(label))
            print(f"    {self.step:>2}. {label} {dots} {detail}")
        elif detail.lower().startswith("ignored"):
            print(f"      [!] {detail}")
        else:
            print(f"      [i] using memory: {detail}")


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------

def question_screen(ws):
    """Which screen. Accepts 'find <words>' so a UI number is not required
    up front - not knowing the number is the most common way to be stuck."""
    while True:
        answer = ask("1. Which screen?", "UI number, or: find <words>")
        if not answer:
            print("      A screen is needed to continue.")
            continue

        if answer.lower().startswith("find"):
            query = answer[4:].strip()
            if not query:
                print("      Try: find production plan")
                continue
            found = gmes_open_screen.catalogue(ws, query)
            rows = found.get("rows", [])
            if not rows:
                print(f"      Nothing matches '{query}' "
                      f"in the {found.get('total')} screens you can open.")
                continue
            print(f"\n      {len(rows)} match(es):")
            for row in rows[:12]:
                print(f"        {row['screenId']:<12} {row['menuTitle']}")
            print()
            continue

        return answer.upper()


def question_dates():
    """Both dates are typed by the person. Nothing is worked out from today's
    date - that is a later feature, deliberately not guessed at now.

    They are validated here, while the keyboard is still in reach: a date
    written straight through unchecked reaches a field that stores YYYYMMDD
    and the query then quietly answers a different question."""
    def one(label):
        while True:
            raw = ask(label, "YYYYMMDD or YYYY-MM-DD, blank = leave as-is")
            if not raw:
                return None
            try:
                value = core.normalise_date(raw)
                if value != raw:
                    print(f"          (read as {value})")
                return value
            except ValueError as e:
                print(f"      {e}")

    date_from = one("3. From date")
    if not date_from:
        return None, None
    date_to = one("4. To date")
    if not date_to:
        date_to = date_from
        print(f"          (no end date given - using {date_to})")
    return date_from, date_to


def question_filters(screen_code):
    """Optional. Most runs need nothing here."""
    answer = ask("5. Any extra filter?",
                 "e.g. Production Order=011074232146, blank = none")
    if not answer or "=" not in answer:
        if answer:
            print("      That is not Name=Value - skipping it.")
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

    print("\n  Signing in to G-MES...")
    captured = io.StringIO()
    try:
        with redirect_stdout(captured):
            ok = core.sign_in()
    except Exception as e:                      # keep the captured detail
        print(captured.getvalue())
        print(f"  Could not sign in: {e}")
        return False

    if ok:
        who = ""
        for row in captured.getvalue().splitlines():
            if "igned in as" in row:            # "Signed in" / "Already signed in"
                who = row.split("as", 1)[1].strip().strip(".'\"")
        print(f"  Signed in{' as ' + who if who else ''}.")
        return True

    print(captured.getvalue())
    print("  Could not sign in. Nothing was run.")
    return False


def memory_banner(code):
    """Say plainly which phase is about to happen. This is the whole point of
    the two-phase design, so it is stated before the work, not inferred from
    the log afterwards."""
    profile = gmes_profile.load(code)
    line()
    if profile:
        print(f"   REPLAYING - {code} was learned on {profile.get('learned')}.")
        print("   It will check the screen still matches, then reuse what it knows.")
    else:
        print(f"   RECORDING - {code} is new.")
        print("   It will work the screen out as it goes, and remember it")
        print("   afterwards IF the whole run succeeds.")
    line()
    return bool(profile)


def main():
    banner("G-MES REPORT TOOL",
           "Answer 5 questions. Everything after that is automatic.")

    if not sign_in_quietly():
        pause()
        return 1

    ws = core.connect()
    try:
        banner("WHAT DO YOU WANT?")
        print()
        code = question_screen(ws)
        division = ask("2. Division", "e.g. VD, blank = none")
        date_from, date_to = question_dates()
        sets = question_filters(code)

        banner("READY")
        print()
        print(f"    Screen    : {code}")
        print(f"    Division  : {division or '(none)'}")
        print(f"    Dates     : {date_from or '(left as-is)'}"
              + (f"  to  {date_to}" if date_from else ""))
        if sets:
            for key, value in sets.items():
                print(f"    Filter    : {key} = {value}")
        print(f"    Saving to : {core.OUTPUT_DIR}")
        print()
        was_known = memory_banner(code)

        if ask("Press Enter to start", "or type n to cancel",
               default="y").lower().startswith("n"):
            print("\n  Cancelled. Nothing was run.")
            pause()
            return 1
        print()

        results = core.run_many(ws, [{
            "screen_code": code, "division": division or None,
            "date_from": date_from, "date_to": date_to, "sets": sets,
            "export": "both", "out_dir": core.OUTPUT_DIR,
        }], log=Narrator())

        result = results[0]
        banner("FINISHED" if result["ok"] else "DID NOT FINISH")
        print()
        if result["ok"]:
            print(f"    {result['rows']:,} rows found, in {result.get('seconds', '?')}s")
            print()
            for path in result["files"]:
                print(f"    saved: {os.path.basename(path)}")
            print(f"\n    folder: {core.OUTPUT_DIR}")
            print()
            if was_known:
                print("    The memory of this screen was used, and refreshed.")
            else:
                print("    This screen has now been LEARNED. Next time it will")
                print("    replay, which is faster and safer.")
        else:
            print(f"    {result['error']}")
            print("\n    Nothing was saved. A screenshot of the failure is in")
            print("    the project folder.")
        print()
        pause()
        return 0 if result["ok"] else 1
    finally:
        ws.close()


if __name__ == "__main__":
    sys.exit(main())
