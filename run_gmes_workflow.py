"""
Interactive G-MES workflow - the counterpart to run_nerp_workflow.py.

    python run_gmes_workflow.py
    (or double-click GMES_Workflow.bat)

Asks for one or more UI numbers, opens each one and shows what it actually
offers - its filters, its category trees, its left-panel options and its
result grids - then asks which to set, and runs them one after another.

Unlike the N-ERP version it does not have to be told the fields in advance:
the screen is read off the screen, so the prompts list real choices instead
of asking you to guess a label. Everything that is asked here is validated
while you are still at the keyboard, because the alternative is a run that
answers the wrong question at 02:00 and looks fine.

Non-interactive use is gmes_report.py; all of the mechanism is gmes_core.py.
"""
import os
import sys

# Proxy bypass is applied by importing cdp_common - see SKILL.md gotcha #1.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cdp_common  # noqa: E402
import gmes_core as core  # noqa: E402
import gmes_open_screen  # noqa: E402


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

        return [c.upper() for c in raw.replace(",", " ").split() if c]


def show_screen(screen):
    """Print what this screen actually offers, in the terms it uses itself."""
    info = screen.info
    print(f"\n  {screen.title}   [{screen.code}]")

    try:
        grid, rivals = core.choose_grid(info)
        if grid:
            print(f"  results: {grid['dataset']} (grid {grid['name']})")
        if rivals:
            print(f"  NOTE   : {len(rivals) + 1} grids are comparable in size on "
                  "this screen; the largest visible one will be exported.")
    except Exception:
        pass

    visible = [f for f in info["filters"] if f["visible"]]
    hidden = [f for f in info["filters"] if not f["visible"]]
    if visible:
        print("\n  Filters on this screen:")
        for f in visible:
            now = f"  = {f['value']}" if f["value"] else ""
            date = "   (a date field)" if core.is_date_field(f) else ""
            print(f"    {(f['label'] or f['column']):<28} "
                  f"(column {f['column']}){now}{date}")
    if info["unbound"]:
        print("\n  Boxes this screen fills in code - they are typed into:")
        for u in info["unbound"]:
            now = f"  = {u['value']}" if u["value"] else ""
            print(f"    {(u['label'] or u['control']):<28} ({u['control']}){now}")
    if hidden:
        print(f"  ...and {len(hidden)} more not currently on screen "
              f"({', '.join(f['column'] for f in hidden[:6])})")
    if not info["filters"] and not info["unbound"]:
        print("\n  This screen exposes no filters - it can still be run and exported.")

    try:
        labels = [o["label"] for o in screen.options()
                  if o["label"].lower() not in ("inquiry",)]
        if labels:
            print(f"\n  Left-panel options: {', '.join(labels[:14])}")
    except Exception:
        pass

    try:
        names = sorted({n for t in screen.trees() if t["settable"] for n in t["names"]})
        if names:
            print(f"  Divisions available: {', '.join(names[:12])}"
                  + (" ..." if len(names) > 12 else ""))
    except Exception:
        pass


def prompt_filters(screen):
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
        match = core.match_filter(screen.info, key)
        if match is None:
            print(f"    No filter matches {key!r} on this screen.")
            if any(w in key.lower() for w in ("division", "org", "category",
                                              "attribute", "plant", "std")):
                print("    That is an organisation choice, not a field: answer "
                      "the Division question below,")
                print("    or give Org / Prod / Fac / Proc or STD / PLANT at "
                      "the Options prompt.")
            else:
                names = ", ".join(f["label"] or f["column"] or f["control"]
                                  for f in screen.info["filters"] if f["visible"])
                print(f"    Available: {names}")
            continue
        if isinstance(match, list):
            names = ", ".join(f["label"] or f["column"] or f["control"] for f in match[:6])
            print(f"    {key!r} is ambiguous ({names}) - be more specific.")
            continue
        sets[key] = value
        print(f"    ok: {match['label'] or match['column'] or match['control']} = {value}")


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

    if not core.sign_in():
        print("\nSign-in failed twice. Nothing was run.")
        pause()
        return 1

    ws = core.connect()
    try:
        codes = prompt_screens(ws)

        # Ask per screen, because each one is different. The answers are all
        # collected first, so the run itself needs nobody at the keyboard.
        plans = []
        for code in codes:
            try:
                screen = core.open_screen(ws, code)
            except RuntimeError as e:
                print(f"  Could not open {code}: {e}")
                continue
            show_screen(screen)
            plans.append({"screen_code": code,
                          "sets": prompt_filters(screen),
                          "options": prompt_options()})

        if not plans:
            print("\nNothing to run.")
            pause()
            return 1

        division = ask("\nDivision (e.g. VD, blank for none): ")

        # Both dates are typed by the user - nothing is worked out from
        # today's date. They are validated HERE, while the user can still fix
        # them: "2026-09-07" written through unchecked reaches a field that
        # stores YYYYMMDD and the query quietly answers something else.
        def ask_date(label):
            while True:
                raw = ask(f"{label} YYYYMMDD or YYYY-MM-DD "
                          "(blank = leave the screen's own dates): ")
                try:
                    value = core.normalise_date(raw)
                    if value and value != raw:
                        print(f"  using {value}")
                    return value
                except ValueError as e:
                    print(f"  {e}")

        date_from = ask_date("From date")
        date_to = ask_date("To date") if date_from else None
        if date_from and not date_to:
            date_to = date_from
            print(f"  to date not given - using {date_to}")

        export = ask("Export xlsx / csv / both / none [both]: ", "both").lower()
        if export not in ("xlsx", "csv", "both", "none"):
            print(f"  '{export}' is not a choice - using both")
            export = "both"

        out_dir = core.OUTPUT_DIR
        os.makedirs(out_dir, exist_ok=True)
        print(f"\nOutput folder: {out_dir}")
        print(f"Running {len(plans)} screen(s), one after another...")

        for plan in plans:
            plan.update({"division": division or None, "date_from": date_from,
                         "date_to": date_to, "export": export, "out_dir": out_dir})

        results = core.run_many(ws, plans)
        core.print_summary(results)
        pause()
        return 0 if all(r["ok"] for r in results) else 1
    finally:
        ws.close()


if __name__ == "__main__":
    sys.exit(main())
