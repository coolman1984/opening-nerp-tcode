"""
Orchestrator for the opening-nerp-tcode skill.

Runs the whole pipeline: launch Chrome with CDP -> open the T-code -> fill
filters and Execute -> export to Excel.

Interactive (prompts for everything, pauses before exiting so a
double-clicked console window does not vanish):

    python run_nerp_workflow.py

Non-interactive (also what NERP_Workflow.bat forwards its arguments to):

    python run_nerp_workflow.py MB52 "Material Number=SM-A137FLBHMEB" "Plant=P703"
    python run_nerp_workflow.py MB52 "Material Number" SM-A137FLBHMEB Plant P703
    python run_nerp_workflow.py MB52 --no-export

Both argument styles work: Label=Value pairs (the same form execute_filters
takes) or alternating Label Value words.
"""
import os
import sys

# Proxy bypass must be in place before any CDP HTTP/websocket call in this
# process - see SKILL.md gotcha #1. Importing cdp_common applies it.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cdp_common  # noqa: E402
from cdp_common import CDP_PORT, launch_chrome  # noqa: E402
import search_tcode  # noqa: E402
import execute_filters  # noqa: E402
import export_to_excel  # noqa: E402


USAGE = (
    "Usage: run_nerp_workflow.py <T-code> [Label=Value ...] [--no-export] [--keep-chrome]\n"
    "   or: run_nerp_workflow.py <T-code> [Label Value ...] [--no-export] [--keep-chrome]\n"
    "   or: run_nerp_workflow.py            (interactive prompts)"
)

FLAGS = {"--no-export", "--keep-chrome", "--no-verify", "--strict", "-h", "--help"}


def ensure_chrome_running(kill_existing=True):
    """Start a clean CDP-enabled Chrome.

    Always a fresh restart rather than reusing whatever session is already
    listening: repeated navigations accumulate stale duplicate tabs and
    webgui iframes (11+ duplicate "N-ERP Home" tabs after one testing
    session), which slows target enumeration and makes tab lookups pick the
    wrong one (gotchas #12/#15). Deleting the profile matters as much as the
    kill - see launch_chrome's docstring for why."""
    print("Restarting Chrome with a clean CDP session..."
          if kill_existing else "Starting Chrome with a clean CDP session...")
    try:
        chrome = launch_chrome(port=CDP_PORT, kill_existing=kill_existing)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    print(f"Chrome is up ({chrome}), CDP on port {CDP_PORT}.")


def clean_input(raw):
    """Strip whitespace and a stray leading BOM (U+FEFF), which shows up on
    the first line read from some piped/redirected stdin sources."""
    return raw.strip().lstrip("﻿").strip()


def prompt_tcode():
    while True:
        tcode = clean_input(input("Enter T-code (e.g. MB52): "))
        if tcode:
            return tcode
        print("The T-code cannot be empty.")


def prompt_filters():
    print("Enter filters as 'Field Label=Value' (e.g. 'Material=BN96-63249A').")
    print("Press Enter on a blank line when done (or immediately for no filters).")
    filters = {}
    while True:
        line = clean_input(input(f"Filter {len(filters) + 1} (blank to finish): "))
        if not line:
            break
        if "=" not in line:
            print("  The format must be Label=Value - try again.")
            continue
        label, value = (part.strip() for part in line.split("=", 1))
        if not label or not value:
            print("  Both a label and a value are required - try again.")
            continue
        filters[label] = value
    return filters


def parse_cli_args(argv):
    """(tcode, filters) from argv. Accepts both Label=Value entries and
    alternating Label Value words, so neither calling habit is a footgun."""
    words = [a for a in argv if a not in FLAGS]
    if not words or not words[0].strip():
        print(USAGE)
        sys.exit(2)

    tcode, rest = words[0], words[1:]
    filters = {}

    if any("=" in item for item in rest):
        for item in rest:
            if "=" not in item:
                print(f"ERROR: mixed argument styles - {item!r} has no '='.\n{USAGE}")
                sys.exit(2)
            label, value = item.split("=", 1)
            filters[label.strip()] = value.strip()
    else:
        if len(rest) % 2 != 0:
            print(f"ERROR: filters must come in Label Value pairs "
                  f"(got {len(rest)} words after the T-code).\n{USAGE}")
            sys.exit(2)
        for i in range(0, len(rest), 2):
            filters[rest[i].strip()] = rest[i + 1].strip()

    return tcode, filters


def pause_before_exit():
    try:
        input("\nPress Enter to exit...")
    except EOFError:
        pass


def run_step(name, fn, *args, **kwargs):
    print(f"\n=== {name} ===")
    try:
        fn(*args, **kwargs)
        return True
    except SystemExit as e:
        if e.code not in (0, None):
            print(f"\n{name} failed (exit code {e.code}). Stopping.")
            return False
        return True
    except Exception as e:
        print(f"\n{name} raised an unexpected error: {e!r}")
        cdp_common.screenshot_on_failure("nerp_workflow_error")
        return False


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "-h" in argv or "--help" in argv:
        print(USAGE)
        return 0

    print("=" * 60)
    print("NERP T-code Workflow")
    print("=" * 60)

    ensure_chrome_running(kill_existing="--keep-chrome" not in argv)

    interactive = not [a for a in argv if a not in FLAGS]
    if interactive:
        tcode = prompt_tcode()
        filters = prompt_filters()
    else:
        tcode, filters = parse_cli_args(argv)

    def fail():
        if interactive:
            pause_before_exit()
        sys.exit(1)

    if not run_step(f"Opening t-code {tcode}", search_tcode.main, tcode,
                    verify="--no-verify" not in argv):
        fail()

    # execute_filters waits for the selection screen itself (gotcha #16), so
    # there is deliberately no second wait here - the original code called
    # wait_for_selection_screen_ready twice, once in each place.
    if not run_step("Filling filters and executing", execute_filters.main,
                    filters, strict="--strict" in argv):
        fail()

    if "--no-export" in argv:
        print("\n--no-export given: stopping after Execute. The result list is "
              "on screen in the Chrome window.")
    elif not run_step("Exporting to Excel", export_to_excel.main, tcode):
        fail()

    print("\n" + "=" * 60)
    print("Done. Check the Chrome window / status bar for the download confirmation.")
    print("=" * 60)
    if interactive:
        pause_before_exit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
