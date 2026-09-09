"""
Interactive orchestrator for the opening-nerp-tcode skill.

Prompts the user for a T-code and any number of filter fields/values, then
runs the full pipeline: launch Chrome w/ CDP (if not already running) ->
open the T-code -> fill filters & Execute -> export to Excel.

Run directly:
    python run_nerp_workflow.py

Or double-click NERP_Workflow.bat in the same folder.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

# Proxy bypass must be set before any cdp_common HTTP/websocket calls in
# this process - see SKILL.md gotcha #1 (corporate proxy blocks localhost
# CDP traffic without this).
os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"
os.environ["no_proxy"] = "localhost,127.0.0.1,::1"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cdp_common import get_tabs, wait_for_selection_screen_ready  # noqa: E402
import search_tcode  # noqa: E402
import execute_filters  # noqa: E402
import export_to_excel  # noqa: E402

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CDP_PORT = 9444


def ensure_chrome_running():
    """Always force a fresh Chrome restart rather than reusing whatever CDP
    session may already be listening. Repeated navigations across many runs
    accumulate stale duplicate tabs/iframes in a long-lived session (seen
    firsthand: 11+ duplicate "N-ERP Home" tabs after repeated manual
    testing), which slows down CDP's target enumeration and can cause
    get_webgui_tab()/page-tab lookups to pick the wrong, stale target. A
    clean restart with a dedicated profile guarantees a single-tab state.

    Deleting the profile directory (not just killing the process) matters:
    taskkill /F simulates a crash, and Chrome's session-restore can reopen
    an old, completely unrelated tab from a previous test on next launch if
    the same --user-data-dir is reused - silently landing every subsequent
    step on the wrong screen with no error at all."""
    print("Restarting Chrome with a clean CDP session...")
    subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)

    profile_dir = os.path.join(tempfile.gettempdir(), "chrome_cdp_profile")
    shutil.rmtree(profile_dir, ignore_errors=True)

    subprocess.Popen([
        CHROME_PATH,
        f"--remote-debugging-port={CDP_PORT}",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ])

    for _ in range(10):
        time.sleep(1)
        try:
            get_tabs()
            print("Chrome is up.")
            return
        except Exception:
            continue

    print("ERROR: Chrome did not become reachable on the CDP port in time.")
    sys.exit(1)


def clean_input(raw):
    """Strip whitespace and a stray leading BOM (U+FEFF), which can show up
    on the very first line read from certain piped/redirected stdin sources."""
    return raw.strip().lstrip("﻿").strip()


def prompt_tcode():
    while True:
        tcode = clean_input(input("Enter T-code (e.g. MB52): "))
        if tcode:
            return tcode
        print("T-code cannot be empty.")


def prompt_filters():
    print("Enter filters as 'Field Label=Value' (e.g. 'Material=BN96-63249A').")
    print("Press Enter on a blank line when done (or immediately for no filters).")
    filters = {}
    while True:
        line = clean_input(input(f"Filter {len(filters) + 1} (blank to finish): "))
        if not line:
            break
        if "=" not in line:
            print("  Format must be Label=Value - try again.")
            continue
        label, value = line.split("=", 1)
        label, value = label.strip(), value.strip()
        if not label or not value:
            print("  Both label and value are required - try again.")
            continue
        filters[label] = value
    return filters


def pause_before_exit():
    try:
        input("\nPress Enter to exit...")
    except EOFError:
        pass


USAGE = "Usage: run_nerp_workflow.py <T-code> [<Label> <Value> ...]"


def parse_cli_args(argv):
    """Parse sys.argv[1:] into (tcode, filters) for non-interactive mode.

    argv[0] is the T-code; the rest must be an even number of
    Label, Value pairs (each already a separate argv entry, so quoted
    labels/values with spaces or '=' arrive intact from the shell)."""
    tcode = argv[0]
    rest = argv[1:]
    if not tcode.strip() or len(rest) % 2 != 0:
        print(USAGE)
        sys.exit(2)
    filters = {}
    for i in range(0, len(rest), 2):
        filters[rest[i]] = rest[i + 1]
    return tcode, filters


def run_step(name, fn, *args):
    print(f"\n=== {name} ===")
    try:
        fn(*args)
        return True
    except SystemExit as e:
        if e.code not in (0, None):
            print(f"\n{name} failed (exit code {e.code}). Stopping.")
            return False
        return True
    except Exception as e:
        print(f"\n{name} raised an unexpected error: {e}")
        return False


def main():
    print("=" * 60)
    print("NERP T-code Workflow")
    print("=" * 60)

    ensure_chrome_running()

    cli_args = sys.argv[1:]
    interactive = not cli_args
    if interactive:
        tcode = prompt_tcode()
        filters = prompt_filters()
    else:
        tcode, filters = parse_cli_args(cli_args)

    def fail():
        if interactive:
            pause_before_exit()
        sys.exit(1)

    if not run_step(f"Opening t-code {tcode}", search_tcode.main, tcode):
        fail()

    print("\nWaiting for the T-code's selection screen to become ready...")
    try:
        wait_for_selection_screen_ready()
    except RuntimeError as e:
        print(f"ERROR: {e}")
        fail()

    if not run_step("Filling filters and executing", execute_filters.main, filters):
        fail()

    if not run_step("Exporting to Excel", export_to_excel.main, tcode):
        fail()

    print("\n" + "=" * 60)
    print("Done! Check the Chrome window / status bar for the download confirmation.")
    print("=" * 60)
    if interactive:
        pause_before_exit()


if __name__ == "__main__":
    main()
