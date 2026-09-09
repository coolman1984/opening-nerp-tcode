"""
Interactive G-MES workflow - the counterpart to run_nerp_workflow.py.

    python run_gmes_workflow.py
    (or double-click GMES_Workflow.bat)

Asks for one or more UI numbers, shows what filters each screen actually
has, asks which to set, then runs and exports them one after another.

Unlike the N-ERP version it does not have to be told the fields in advance:
the screen is opened first and its own filters are read off it, so the
prompt lists real choices instead of asking you to guess a label.

Non-interactive use is gmes_report.py; this is the by-hand front end.
"""
import os
import sys

# Proxy bypass is applied by importing cdp_common - see SKILL.md gotcha #1.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cdp_common  # noqa: E402
import gmes_login  # noqa: E402
import gmes_open_screen  # noqa: E402
import gmes_report  # noqa: E402
from gmes_common import connect_gmes  # noqa: E402


def clean(raw):
    """Strip whitespace and a stray BOM, which shows up on the first line
    read from some piped stdin sources."""
    return raw.strip().lstrip("﻿").strip()


def ask(prompt, default=""):
    try:
        value = clean(input(prompt))
    except EOFError:
        return default
    return value or default


def pause():
    try:
        input("\nPress Enter to exit...")
    except EOFError:
        pass


def prompt_screens(ws):
    """Ask for UI numbers, and let the user search if they do not know one."""
    while True:
        raw = ask("UI number(s), space or comma separated "
                  "(or 'find <text>' to search): ")
        if not raw:
            print("  At least one UI number is required.")
            continue

        if raw.lower().startswith("find "):
            query = raw[5:].strip()
            info = gmes_open_screen.catalogue(ws, query)
            rows = info.get("rows", [])
            if not rows:
                print(f"  Nothing matches {query!r} in the {info.get('total')} screens.")
                continue
            print(f"\n  {len(rows)} match(es):")
            for r in rows[:15]:
                print(f"    {r['screenId']:<12} {r['menuTitle']}")
                print(f"    {'':<12} {r['path']}")
            print()
            continue

        codes = [c.upper() for c in raw.replace(",", " ").split() if c]
        return codes


def show_filters(ws, code):
    """Open the screen and print what it actually offers."""
    opened = gmes_open_screen.open_screen(ws, code)
    gmes_open_screen.activate_screen(ws, opened.get("winId", ""))
    info = gmes_report.discover(ws, code)
    if not info.get("found"):
        print(f"  Could not read {code}.")
        return None, None

    print(f"\n  {opened.get('title')}   [{code}]")
    grid = gmes_report.result_dataset(info)
    if grid:
        print(f"  results: {grid['dataset']}")

    settable = [f for f in info["filters"] if f["visible"]]
    hidden = [f for f in info["filters"] if not f["visible"]]
    if settable:
        print("\n  Filters on this screen:")
        for f in settable:
            print(f"    {(f['label'] or f['column']):<28} "
                  f"(column {f['column']}){'  = ' + f['value'] if f['value'] else ''}")
    if hidden:
        print(f"  ...and {len(hidden)} more not currently on screen "
              f"({', '.join(f['column'] for f in hidden[:6])})")
    if not info["filters"]:
        print("\n  This screen binds no filters - it can still be run and exported.")

    try:
        opts = gmes_report.left_options(ws)
        labels = [o["label"] for o in opts["options"]
                  if o["label"].lower() not in ("inquiry",)]
        if labels:
            print(f"\n  Left-panel options: {', '.join(labels[:14])}")
    except Exception:
        pass
    return info, opened


def prompt_filters(info):
    print("\n  Enter filters as 'Label=Value' (blank line when done).")
    sets = {}
    while True:
        line = ask(f"  Filter {len(sets) + 1} (blank to finish): ")
        if not line:
            return sets
        if "=" not in line:
            print("    The format must be Label=Value - try again.")
            continue
        key, value = (p.strip() for p in line.split("=", 1))
        if not key or not value:
            print("    Both a label and a value are required - try again.")
            continue
        match = gmes_report.match_filter(info, key)
        if match is None:
            print(f"    No filter matches {key!r} on this screen.")
            if any(w in key.lower() for w in ("division", "org", "category",
                                              "attribute", "plant", "std")):
                print("    That is an organisation choice, not a field: answer "
                      "the Division question below,")
                print("    or give Org / Prod / Fac / Proc or STD / PLANT at "
                      "the Options prompt.")
            else:
                names = ", ".join(f["label"] or f["column"]
                                  for f in info["filters"] if f["visible"])
                print(f"    Available: {names}")
            continue
        if isinstance(match, list):
            names = ", ".join(f["label"] or f["column"] for f in match[:6])
            print(f"    {key!r} is ambiguous ({names}) - be more specific.")
            continue
        sets[key] = value
        print(f"    ok: {match['label'] or match['column']} = {value}")


def prompt_options():
    print("\n  Left-panel options to click, e.g. PLANT, 'Create Date', "
          "'Detail Prod. Plan', Prod")
    options = []
    while True:
        line = ask(f"  Option {len(options) + 1} (blank to finish): ")
        if not line:
            return options
        options.append(line)


def main():
    print("=" * 60)
    print("G-MES Report Workflow")
    print("=" * 60)

    if gmes_login.main() != 0:
        print("\nSign-in failed. Nothing was run.")
        pause()
        return 1

    ws = connect_gmes()
    try:
        codes = prompt_screens(ws)

        # Ask per screen, because each one has different filters. The
        # answers are collected first so the run itself is unattended.
        plans = []
        for code in codes:
            info, opened = show_filters(ws, code)
            if info is None:
                continue
            sets = prompt_filters(info)
            options = prompt_options()
            plans.append({"code": code, "sets": sets, "options": options})

        if not plans:
            print("\nNothing to run.")
            pause()
            return 1

        division = ask("\nDivision (e.g. VD, blank for none): ")

        # Validate the date HERE, while the user is still at the keyboard.
        # Written through unchecked, "2026-09-07" reaches a filter that
        # stores YYYYMMDD and the query quietly answers something else.
        while True:
            raw_date = ask("Date YYYYMMDD or YYYY-MM-DD "
                           "(blank = leave the screen's own dates): ")
            try:
                date = gmes_report.normalise_date(raw_date)
                if date and date != raw_date:
                    print(f"  using {date}")
                break
            except ValueError as e:
                print(f"  {e}")

        export = ask("Export xlsx / csv / both / none [both]: ", "both").lower()
        if export not in ("xlsx", "csv", "both", "none"):
            print(f"  '{export}' is not a choice - using both")
            export = "both"

        out_dir = gmes_report.OUTPUT_DIR
        os.makedirs(out_dir, exist_ok=True)
        print(f"\nOutput folder: {out_dir}")
        print(f"Running {len(plans)} screen(s), one after another...")

        results = []
        for plan in plans:
            try:
                results.append(gmes_report.run_one(
                    ws, plan["code"], division or None, date or None,
                    plan["sets"], export, out_dir, plan["options"]))
            except Exception as e:
                print(f"  FAILED   : {e}")
                cdp_common.screenshot_on_failure(f"gmes_workflow_{plan['code']}")
                results.append({"screen": plan["code"], "ok": False, "rows": 0,
                                "files": [], "error": str(e)})

        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        for r in results:
            if r["ok"]:
                print(f"  {r['screen']:<12} ok      {r['rows']:>7} rows")
                for f in r["files"]:
                    print(f"  {'':<12}         {os.path.basename(f)}")
            else:
                print(f"  {r['screen']:<12} FAILED   {r['error']}")
        ok = sum(1 for r in results if r["ok"])
        print(f"\n  {ok}/{len(results)} succeeded")
        pause()
        return 0 if ok == len(results) else 1
    finally:
        ws.close()


if __name__ == "__main__":
    sys.exit(main())
