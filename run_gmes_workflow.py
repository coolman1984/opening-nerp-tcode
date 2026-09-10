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
import gmes_log  # noqa: E402
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


class InputClosed(Exception):
    """stdin has ended - there is nobody left to ask.

    A blank line and a closed stream are NOT the same thing, and treating
    them alike span forever: every re-ask loop (a wrong UI number, a bad
    date) saw the empty default, rejected it, and asked again - thousands of
    times, instantly. A blank line is an answer. A closed stream means stop.
    """


def ask(label, hint="", default=""):
    """Ask one question and ECHO what came back.

    The echo is not decoration. It confirms what the tool understood - which
    is where a date typed 2026-09-09 is shown back as 20260909 - and it is
    the only way the answers are visible at all when this is driven from a
    script rather than a keyboard."""
    tail = f"  {ui.GREY}{hint}{ui.RESET}" if hint else ""
    try:
        raw = input(f"    {ui.CYAN}{ui.ARROW}{ui.RESET} {label}{tail}\n      "
                    f"{ui.BOLD}> {ui.RESET}")
    except EOFError:
        raise InputClosed()
    value = clean(raw) or default
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

def question_mode(q):
    """Which way of working, chosen rather than inferred.

    The tool can tell for itself whether it has seen a screen before, and it
    still does - but being told, and being able to choose, is not the same as
    having it decided for you. RECORD is also the way to re-teach a screen
    that has changed, which was otherwise only reachable through --relearn."""
    print(f"    {ui.GREY}RECORD  - a screen you have not used before. It opens the")
    print(f"              screen, shows you every filter it has, and asks.")
    print(f"    REPLAY  - a screen it already knows. Just the UI number, your")
    print(f"              filter values, and Enter.{ui.RESET}\n")
    while True:
        answer = q.ask("Record or Replay?", "type R or P", default="P").lower()
        if answer.startswith("r"):
            return "record"
        if answer.startswith("p"):
            return "replay"
        ui.note("Type R for Record or P for Replay.", "warn")


def question_screen(q, ws, mode="replay"):
    """Which screen. Checked against the catalogue BEFORE anything is opened.

    In REPLAY the screens already recorded are listed and can be chosen by
    number, with the most recent as the default - the recordings are kept as
    JSON in `screens/` and never expire, so there is no reason to make anyone
    remember a UI number the tool already knows.

    A number that does not exist used to be accepted, passed to the browser,
    and then killed the whole session with a timeout - so a single typo meant
    starting again from the sign-in. The 809 screens this account can open are
    listed client-side, so a wrong number can be caught in milliseconds and
    the question asked again."""
    saved = gmes_profile.known() if mode == "replay" else []
    if saved:
        print(f"    {ui.GREY}Screens already recorded:{ui.RESET}")
        for n, p in enumerate(saved[:9], start=1):
            vals = gmes_profile.last_values(p)
            extra = ", ".join(f"{k}={v}" for k, v in vals.items()
                              if v and k != "sets")
            print(f"      {ui.CYAN}{n}{ui.RESET}  {p['screen']:<11} "
                  f"{(p.get('title') or '')[:34]:<34} {ui.GREY}{extra}{ui.RESET}")
        print()

    default = saved[0]["screen"] if saved else ""
    hint = ("a number from the list, a UI number, or:  find <words>"
            if saved else "a UI number, or:  find <words>")
    first = True
    while True:
        prompt = q.ask if first else q.again
        first = False
        answer = prompt("Which screen?", hint, default=default)
        if not answer:
            ui.note("A screen is needed. Type a UI number, or "
                    "'find production plan' to search.", "warn")
            continue

        # A single digit picks from the list above.
        if saved and answer.isdigit() and 1 <= int(answer) <= len(saved[:9]):
            chosen = saved[int(answer) - 1]
            print(f"      {ui.GREY}{chosen.get('title', '')}{ui.RESET}")
            return chosen["screen"]

        if answer.lower().startswith("find"):
            query = answer[4:].strip()
            if not query:
                ui.note("Try:  find production plan", "warn")
                continue
            found = gmes_open_screen.catalogue(ws, query)
            rows = found.get("rows", [])
            if not rows:
                ui.note(f"Nothing matches '{query}' in the "
                        f"{found.get('total')} screens you can open. "
                        f"Try different words.", "warn")
                continue
            print()
            for row in rows[:12]:
                print(f"      {ui.CYAN}{row['screenId']:<12}{ui.RESET} {row['menuTitle']}")
            print()
            ui.note("Type one of those UI numbers above.")
            continue

        code = answer.upper()
        try:
            found = gmes_open_screen.catalogue(ws, code)
        except Exception:
            return code             # catalogue unreadable; let the open try

        rows = found.get("rows", [])
        exact = [r for r in rows
                 if code in (r["screenId"].upper(), r["menuId"].upper())]
        if exact:
            print(f"      {ui.GREY}{exact[0]['menuTitle']}{ui.RESET}")
            return exact[0]["screenId"].upper()

        # Not a real UI number. Say so, offer whatever it did look like, and
        # ask again - never carry on and fail in the browser.
        ui.note(f"There is no screen '{code}'. Please try again.", "warn")
        if rows:
            print(f"      {ui.GREY}Did you mean:{ui.RESET}")
            for row in rows[:6]:
                print(f"        {ui.CYAN}{row['screenId']:<12}{ui.RESET} "
                      f"{row['menuTitle']}")
        else:
            print(f"      {ui.GREY}A UI number looks like P1112UM00 or "
                  f"M4151UM00. To search instead, type:  find <words>{ui.RESET}")


def show_screen_offer(screen):
    """Everything this screen actually has, before a single question is asked.

    Only shown the FIRST time a screen is used, and it is the whole point of
    the recording phase. Before this, the tool asked for a division and a date
    range on a screen nobody had looked at yet - so a person was being asked
    to name filters they could not see, on a screen that might not even have
    them. Work Calendar has no date fields at all, and was still being asked
    for two dates."""
    info = screen.info
    ui.section("What this screen has")
    ui.field("Name", screen.title)
    ui.field("UI number", f"{screen.code}   (menu {screen.menu_id})")

    try:
        grid, rivals = core.choose_grid(info)
        if grid:
            rows = info["datasets"].get(grid["dataset"], {}).get("rows", "?")
            ui.field("Results in", f"{grid['dataset']}   ({rows} rows on screen now)")
        if rivals:
            ui.note(f"{len(rivals) + 1} result tables are similar in size; the "
                    f"biggest visible one is used.", "warn")
    except Exception:
        ui.note("no result table found on this screen", "warn")

    qv = [q for q in info.get("quickViews", []) if q.get("screen")]
    if len(qv) > 1:
        print()
        print(f"    {ui.BOLD}Quick View{ui.RESET}  {ui.GREY}(each one is a "
              f"DIFFERENT screen, not a filter - this tool will not click "
              f"these){ui.RESET}")
        for q in qv:
            mark = f"{ui.GREEN}{ui.TICK}{ui.RESET}" if q["active"] else f"{ui.GREY}{ui.DOT}{ui.RESET}"
            tail = "this screen" if q["active"] else f"open {q['screen']} directly to run it"
            print(f"      {mark} {(q['name'] or q['screen']):<26} "
                  f"{ui.GREY}{q['screen']:<12} {tail}{ui.RESET}")

    frm, to, singles = core.date_targets(info)
    dates = [f for f in (frm, to) if f] or singles
    print()
    if dates:
        print(f"    {ui.BOLD}Date fields{ui.RESET}  {ui.GREY}"
              f"(what From/To will be typed into){ui.RESET}")
        for f in dates:
            role = "from" if f is frm else "to" if f is to else "date"
            now = f["value"] or "(empty)"
            print(f"      {ui.CYAN}{role:<5}{ui.RESET} {f['label'] or f['column']:<24} "
                  f"{ui.GREY}{f['column']:<18} now: {now}{ui.RESET}")
    else:
        print(f"    {ui.BOLD}Date fields{ui.RESET}  {ui.GREY}none - this screen "
              f"has no date range, so you will not be asked for one{ui.RESET}")

    others = [f for f in info["filters"] if f["visible"] and f not in dates]
    if others:
        print()
        print(f"    {ui.BOLD}Other filters you can set{ui.RESET}")
        for f in others:
            now = f["value"] or "(empty)"
            print(f"      {ui.CYAN}{ui.DOT}{ui.RESET} {(f['label'] or f['column']):<24} "
                  f"{ui.GREY}{f['column']:<18} now: {now}{ui.RESET}")
    if info["unbound"]:
        print(f"      {ui.GREY}...and {len(info['unbound'])} box(es) the screen "
              f"fills in code: "
              f"{', '.join((u['label'] or u['control']) for u in info['unbound'][:5])}"
              f"{ui.RESET}")

    try:
        names = sorted({n for t in screen.trees() if t["settable"] for n in t["names"]})
        print()
        if names:
            # ALL of them. This used to stop at 18 and print "...and 14 more",
            # which is the one thing this project has a rule against: a cap
            # that hides part of the answer is worse than no cap (CLAUDE.md
            # 4.5). You cannot choose a division you were not shown.
            print(f"    {ui.BOLD}Divisions available{ui.RESET}  "
                  f"{ui.GREY}({len(names)}){ui.RESET}")
            for chunk in [names[i:i + 5] for i in range(0, len(names), 5)]:
                print(f"      {ui.GREY}{',  '.join(chunk)}{ui.RESET}")
        else:
            print(f"    {ui.BOLD}Divisions{ui.RESET}  {ui.GREY}none - this screen "
                  f"has no organisation list{ui.RESET}")
    except Exception:
        pass

    try:
        opts = [o for o in screen.options() if o["label"].lower() != "inquiry"]
        if opts:
            print()
            print(f"    {ui.BOLD}Left-panel options{ui.RESET}  {ui.GREY}"
                  f"(these change what the query MEANS){ui.RESET}")
            for o in opts:
                on = o["state"] in ("selected", "checked")
                mark = f"{ui.GREEN}{ui.TICK}{ui.RESET}" if on else f"{ui.GREY}{ui.DOT}{ui.RESET}"
                print(f"      {mark} {o['label']:<26} {ui.GREY}{o['state']}{ui.RESET}")
            print(f"      {ui.GREY}e.g. 'Plan Date' vs 'Create Date' changes which "
                  f"date the period means.{ui.RESET}")
    except Exception:
        pass
    print()


def question_division(q, screen, default=""):
    """Ask for a division, but only if the screen has one, and show the
    real choices rather than expecting them to be known.

    `default` is what was used last time on this screen: pressing Enter
    accepts it."""
    try:
        names = sorted({n for t in screen.trees() if t["settable"] for n in t["names"]})
    except Exception:
        names = []
    if not names:
        return ""
    hint = (f"Enter for {default}, or one of: " + ", ".join(names[:3])
            if default else "e.g. " + ", ".join(names[:4]) + ", blank = none")
    first = True
    while True:
        prompt = q.ask if first else q.again
        first = False
        answer = prompt("Division", hint, default=default)
        if not answer:
            return ""
        if any(answer.strip().lower() == n.strip().lower() for n in names):
            return answer
        near = [n for n in names if answer.strip().lower() in n.lower()]
        ui.note(f"'{answer}' is not on this screen. Please try again."
                + (f" Did you mean: {', '.join(near[:5])}?" if near else ""), "warn")


def question_options(q, screen):
    """Offer the left-panel options, by name, on a screen being learned."""
    try:
        opts = [o for o in screen.options() if o["label"].lower() != "inquiry"]
    except Exception:
        return []
    if not opts:
        return []
    off = [o["label"] for o in opts if o["state"] not in ("selected", "checked")]
    if not off:
        return []
    answer = q.ask("Any left-panel option to switch on?",
                   "comma separated, blank = leave as they are")
    if not answer:
        return []
    wanted = [part.strip() for part in answer.split(",") if part.strip()]
    known = []
    for want in wanted:
        match = next((o["label"] for o in opts
                      if o["label"].lower() == want.lower()), None) or \
                next((o["label"] for o in opts
                      if want.lower() in o["label"].lower()), None)
        if match:
            known.append(match)
        else:
            ui.note(f"no option called '{want}' on this screen - ignored", "warn")
    return known


def question_dates(q, screen=None, defaults=None):
    """Both dates are typed by the person. Nothing is worked out from today's
    date - that is a later feature, deliberately not guessed at now.

    They are validated here, while the keyboard is still in reach: a date
    written straight through unchecked reaches a field that stores YYYYMMDD
    and the query then quietly answers a different question.

    A screen with no date fields is not asked at all. Work Calendar has none,
    and was still being asked for a range that could go nowhere."""
    defaults = defaults or {}
    if screen is not None:
        frm, to, singles = core.date_targets(screen.info)
        if not any((frm, to)) and not singles:
            return None, None

    def one(label, default=""):
        first = True
        while True:
            prompt = q.ask if first else q.again
            first = False
            hint = (f"Enter for {default}, or a new date"
                    if default else "YYYYMMDD or YYYY-MM-DD, blank = leave as-is")
            raw = prompt(label, hint, default=default)
            if not raw:
                return None
            try:
                value = core.normalise_date(raw)
                if value != raw:
                    ui.note(f"read as {value}")
                return value
            except ValueError as e:
                ui.note(f"{e} Please try again.", "warn")

    date_from = one("From date", defaults.get("from", ""))
    if not date_from:
        return None, None
    date_to = one("To date", defaults.get("to", ""))
    if not date_to:
        date_to = date_from
        ui.note(f"no end date given - using {date_to}")
    return date_from, date_to


def question_filters(q, defaults=None):
    """Optional. Most runs need nothing here."""
    remembered = "; ".join(f"{k}={v}" for k, v in (defaults or {}).items())
    answer = q.ask("Any extra filter?",
                   (f"Enter for {remembered}" if remembered else
                    "Name=Value, e.g. Production Order=011074232146, blank = none"),
                   default=remembered)
    if not answer or "=" not in answer:
        if answer:
            ui.note("That is not Name=Value - skipping it.", "warn")
        return {}
    key, value = (part.strip() for part in answer.split("=", 1))
    return {key: value} if key and value else {}


# ---------------------------------------------------------------------------

def sign_in_visibly():
    """Sign in, showing every step as it happens.

    An earlier version captured the sign-in output and printed one tidy line
    at the end. Signing in can take a minute - waiting on the SSO window, then
    G-MES's own login form - and during all of it the screen said nothing but
    "Signing in to G-MES...". The user reported it as frozen, and they were
    right to: a program that shows nothing for a minute IS frozen as far as
    anyone watching can tell.

    So nothing is hidden. It is less tidy and it is honest, and the moment
    something goes wrong the reason is already on screen."""
    ui.section("Connection")
    print(f"    {ui.GREY}Signing in. This can take up to a minute if the "
          f"session has expired.{ui.RESET}\n")
    try:
        ok = core.sign_in()
    except Exception as e:
        ui.note(f"Could not sign in: {e}", "bad")
        return False
    if not ok:
        ui.note("Could not sign in. Nothing was run.", "bad")
    return ok


def main():
    log_path = gmes_log.start("run_gmes_workflow (interactive)")
    ui.banner("G-MES AUTOMATION", "Report extraction  -  answer 5 questions, "
                                  "the rest is automatic")
    print(f"  {ui.GREY}log: {log_path}{ui.RESET}")

    if not sign_in_visibly():
        pause()
        return 1

    ws = core.connect()
    try:
        runs, ok = 0, True
        try:
            while True:
                runs += 1
                ok = one_run(ws)
                print()
                if ask("Another report?", "Enter for yes, or type n to close",
                       default="y").lower().startswith("n"):
                    break
        except InputClosed:
            print(f"\n  {ui.GREY}(no more input){ui.RESET}")
        print(f"\n  {ui.GREY}{runs} report(s) this session. "
              f"Files are in {core.OUTPUT_DIR}{ui.RESET}")
        print(f"  {ui.GREY}log: {gmes_log.path()}{ui.RESET}")
        gmes_log.finish(f"{runs} report(s), last ok={ok}")
        return 0 if ok else 1
    finally:
        ws.close()


def one_run(ws):
    """One report, start to finish. Returns True if it delivered files.

    Nothing here exits the program. A wrong UI number, a cancelled run or a
    failed query all come back here so the next question can be asked - the
    tool used to close on any of them, which meant signing in again to fix a
    typo."""
    try:
        ui.section("What do you want?")
        print()
        q = Questions()
        mode = question_mode(q)
        code = question_screen(q, ws, mode)
        profile = gmes_profile.load(code)

        # Chosen and actual can disagree, and the tool says so rather than
        # silently doing something else.
        if mode == "replay" and profile is None:
            ui.note(f"{code} has never been used, so there is nothing to "
                    f"replay. Recording it instead.", "warn")
            mode = "record"
        elif mode == "record" and profile is not None:
            ui.note(f"{code} was already learned on {profile.get('learned')}. "
                    f"Recording again replaces what it knows.", "warn")
            profile = None                      # teach it from scratch

        # The screen is opened BEFORE the rest of the questions, so they can
        # be about what it really has. Asked blind, the tool once wanted two
        # dates for a screen with no date fields, and a division for one with
        # no organisation list.
        print(f"    {ui.GREY}Opening {code} to see what it offers...{ui.RESET}")
        try:
            screen = core.open_screen(ws, code, log=lambda *_a, **_k: None)
        except RuntimeError as e:
            ui.note(f"{str(e)} Please try again.", "bad")
            return False

        ui.phase(mode == "record", code, (profile or {}).get("learned", ""))
        confirmed = False

        # What was used last time on this screen, offered back as the
        # defaults. Recording is supposed to mean not typing it all again;
        # remembering only the field NAMES and forgetting the values left the
        # user re-entering everything on a screen the tool "knew".
        last = gmes_profile.last_values(profile)
        options = []

        if mode == "record":
            show_screen_offer(screen)
            division = question_division(q, screen, last.get("division", ""))
            date_from, date_to = question_dates(q, screen, last)
            options = question_options(q, screen)
            sets = question_filters(q, last.get("sets"))

        elif any(v for k, v in last.items() if k != "sets") or last.get("sets"):
            # REPLAY, and everything is already known. Asking again is what
            # recording was supposed to remove: it is shown, and one keypress
            # runs it. Only someone who wants a DIFFERENT day has to type.
            ui.section("Remembered settings")
            ui.field("Division", last.get("division") or "(none)")
            ui.field("Period", (f"{last.get('from')} to {last.get('to')}"
                                if last.get("from") else "(the screen's own)"))
            for key, value in (last.get("sets") or {}).items():
                ui.field("Filter", f"{key} = {value}")
            if profile.get("options"):
                ui.field("Options", ", ".join(profile["options"]))
            print()
            if q.ask("Run it?", "Enter to run, or type c to change something",
                     default="run").lower().startswith("c"):
                division = question_division(q, screen, last.get("division", ""))
                date_from, date_to = question_dates(q, screen, last)
                sets = question_filters(q, last.get("sets"))
            else:
                division = last.get("division", "")
                date_from = last.get("from") or None
                date_to = last.get("to") or None
                sets = dict(last.get("sets") or {})
                # "Run it?" WAS the confirmation. Asking "Press Enter to
                # start" straight afterwards is a second gate on one decision,
                # and it cost a keypress on the shortest, most common path.
                confirmed = True

        else:
            # Recorded before values were remembered, and nothing could be
            # recovered from it. Ask once; it is saved from here on.
            # Accurate, rather than blaming the age of the recording: a
            # screen genuinely run with no division and no dates has nothing
            # to remember, and saying it was "recorded before values were
            # kept" is simply wrong for it.
            ui.note("nothing is remembered for this screen yet - answer once "
                    "and it will be kept.")
            division = question_division(q, screen, last.get("division", ""))
            date_from, date_to = question_dates(q, screen, last)
            sets = question_filters(q, last.get("sets"))

        ui.section("Plan")
        ui.field("Screen", code)
        ui.field("Division", division or "(none)")
        ui.field("Period", f"{date_from} to {date_to}" if date_from
                 else "(leave the screen's own dates)")
        for key, value in sets.items():
            ui.field("Filter", f"{key} = {value}")
        for label in options:
            ui.field("Option", label)
        ui.field("Output", core.OUTPUT_DIR)

        if not confirmed and ask("Press Enter to start", "or type n to cancel",
                                 default="y").lower().startswith("n"):
            ui.note("Cancelled. Nothing was run.", "warn")
            return False

        ui.section("Execution")
        results = core.run_many(ws, [{
            "screen_code": code, "division": division or None,
            "date_from": date_from, "date_to": date_to, "sets": sets,
            "options": options, "export": "both", "out_dir": core.OUTPUT_DIR,
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
        return bool(r["ok"])

    except (KeyboardInterrupt, InputClosed):
        raise                       # the session is ending, not this report
    except Exception as e:
        # One report failing must not end the session. Report it and come
        # back for the next question.
        ui.note(f"{type(e).__name__}: {e}", "bad")
        gmes_log.failure(e)
        cdp_common.screenshot_on_failure("gmes_workflow")
        return False


if __name__ == "__main__":
    sys.exit(main())
