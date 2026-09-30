"""Command-line front end of the same Runner the window uses (for tests and support).

    python samir_cli.py --rows 5
    python samir_cli.py --rows 20 --start 100 --period 202609 --out D:\\some\\folder
    python samir_cli.py --rows 20 --stop-after 12        # proves the Stop mechanic
"""
import argparse
import os
import sys
import threading

import samir_env

samir_env.setup()

import samir_runner as sr              # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rows", type=int, default=0, help="number of rows to export (0 = all)")
    p.add_argument("--start", type=int, default=1, help="grid row number to start at")
    p.add_argument("--division", default="MAIN Part")
    p.add_argument("--mode", default="Monthly", choices=["Monthly", "Daily"])
    p.add_argument("--period", default="", help="YYYYMM or YYYYMMDD, or 'previous' "
                                               "(default: the current month / today)")
    p.add_argument("--filter", action="append", default=[], help="extra filter Name=Value")
    p.add_argument("--grids", default="grdPackInspArtList", help="dialog grids to tick, comma separated")
    p.add_argument("--single-file", choices=["yes", "no", "leave"], default="yes")
    p.add_argument("--out", default="")
    p.add_argument("--on-error", default="stop", choices=["stop", "skip"])
    p.add_argument("--no-skip-existing", action="store_true")
    p.add_argument("--stop-after", type=float, default=0, help="press Stop after this many seconds")
    p.add_argument("--load-only", action="store_true", help="open, Inquiry, count - export nothing")
    p.add_argument("--close-browser", action="store_true")
    p.add_argument("--trace", action="store_true", help="print the time each step of a row takes")
    a = p.parse_args(argv)
    if a.out and not os.path.isabs(a.out):
        a.out = os.path.join(samir_env.ORIGINAL_CWD, a.out)

    s = sr.Settings(division=a.division, period_mode=a.mode, period=a.period,
                    extra_filters=a.filter, start_row=a.start, count=a.rows,
                    dialog_grids=[g.strip() for g in a.grids.split(",") if g.strip()],
                    single_file={"yes": True, "no": False, "leave": None}[a.single_file],
                    out_dir=a.out, on_error=a.on_error, skip_existing=not a.no_skip_existing)
    problems = sr.validate_settings(s)
    if problems:
        print("\n".join("PROBLEM: " + x for x in problems))
        return 2
    runner = sr.Runner(s, log=print, trace=print if a.trace else None)
    try:
        runner.connect()
        runner.load()
        if a.load_only:
            return 0
        if a.stop_after:                       # counted from the start of the export
            threading.Timer(a.stop_after, runner.request_stop).start()
        summary = runner.run()
    except sr.StopRequested:
        print("Stopped before the export started.")
        return 1
    except (sr.FatalError, ValueError) as e:
        print(f"STOPPED: {e}")
        return 1
    finally:
        runner.close(close_browser=a.close_browser)
    print(summary)
    return 0 if not summary["fatal"] and not summary["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
