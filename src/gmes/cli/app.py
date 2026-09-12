"""The unified G-MES command-line surface.

Parsing and rendering live here. Each command makes one application operation;
the application owns authentication, CDP connection, capability, and cleanup.
"""
import argparse
import os
import sys

from ..application import facade as application


def _parser():
    parser = argparse.ArgumentParser(prog="gmes", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version", help="show the standalone package version")
    login = sub.add_parser("login", help="sign in to G-MES")
    login.add_argument("--assist", action="store_true")
    login.add_argument("--refresh-profile", action="store_true")
    credentials = sub.add_parser("credentials", help="explicitly set the local encrypted G-MES credential")
    credentials_sub = credentials.add_subparsers(dest="credentials_command", required=True)
    credentials_sub.add_parser("set", help="prompt for and save the local DPAPI credential")
    sub.add_parser("migrate", help="explicitly copy a legacy credential store if needed")
    sub.add_parser("doctor", help="read-only environment and runtime readiness report")
    run = sub.add_parser("run", help="run one or more screens sequentially")
    run.add_argument("screens", nargs="+", metavar="UI")
    run.add_argument("--division", "--org", dest="division")
    run.add_argument("--tree")
    run.add_argument("--from", dest="date_from")
    run.add_argument("--to", dest="date_to")
    run.add_argument("--date")
    run.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    run.add_argument("--option", action="append", default=[])
    run.add_argument("--grid")
    run.add_argument("--verify", metavar="COLUMN[=VALUE]")
    run.add_argument("--export", choices=("xlsx", "csv", "both", "none"), default="both")
    run.add_argument("--output-dir")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--close-tabs", action="store_true")
    run.add_argument("--no-profile", action="store_true")
    data = sub.add_parser("data", help="inspect a Nexacro dataset")
    data_sub = data.add_subparsers(dest="data_command", required=True)
    forms = data_sub.add_parser("forms", help="list forms and datasets")
    read = data_sub.add_parser("read", help="read rows from a dataset")
    read.add_argument("screen_code")
    read.add_argument("dataset")
    read.add_argument("--limit", type=int, default=20,
                      help="number of rows (use -1 only when a full read is intended)")
    read.add_argument("--offset", type=int, default=0)
    return parser


def _run(args):
    execution = application.execute_run_request(
        args.screens, division=args.division, tree=args.tree, date_from=args.date_from,
        date_to=args.date_to, date=args.date, sets=args.set, options=args.option,
        grid=args.grid, verify=args.verify, export=args.export, out_dir=args.output_dir,
        dry_run=args.dry_run, close_after=args.close_tabs, use_profile=not args.no_profile)
    if not execution.ok:
        print("Sign-in did not complete. Nothing was run.")
        return 1
    return 0 if _render_run_summary(execution.results) == len(execution.results) else 1


def _render_run_summary(results):
    print(f"\n{'=' * 70}\nSUMMARY\n{'=' * 70}")
    print(f"  {'SCREEN':<14} {'STATUS':<9} {'ROWS':>7}  FILES / ERROR")
    for result in results:
        detail = ", ".join(os.path.basename(path) for path in result.files) or "-" if result.ok else result.error
        status, rows = ("ok", str(result.rows)) if result.ok else ("FAILED", "-")
        print(f"  {result.screen:<14} {status:<9} {rows:>7}  {detail}")
    succeeded = sum(result.ok for result in results)
    print(f"\n  {succeeded}/{len(results)} succeeded")
    return succeeded


def _data(args):
    if args.data_command == "forms":
        execution = application.execute_data_forms()
        if not execution.ok:
            print("Sign-in did not complete. No forms were read.")
            return 1
        info = execution.value
        print(f"Open forms: {info.get('count', 0)}")
        for form in info.get("forms", []):
            print(f"  {form.get('file') or '(no file)'}: {', '.join(form.get('datasets', []))}")
        return 0
    execution = application.execute_data_read(args.screen_code, args.dataset,
                                               limit=args.limit, offset=args.offset)
    if not execution.ok:
        print("Sign-in did not complete. No dataset was read.")
        return 1
    result = execution.data
    if not result.get("found"):
        print(f"No dataset {args.dataset!r} on {args.screen_code!r}.")
        return 1
    print(f"Screen  : {result.get('file', '')}")
    print(f"Dataset : {args.dataset}   total rows: {result['total']}")
    print(f"Columns : {', '.join(result['columns'])}")
    for index, row in enumerate(result["rows"]):
        shown = {key: value for key, value in row.items()
                 if value and not key.startswith("_")}
        print(f"  [{index + args.offset}] {shown}")
    return 0


def main(argv=None):
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        if args.command == "version":
            print(application.package_version())
            return 0
        if args.command == "login":
            attempt = application.execute_login(assist=args.assist,
                                                refresh_profile=args.refresh_profile)
            return 0 if attempt.outcome.name == "OK" else 1
        if args.command == "migrate":
            message = application.migrate_credentials()
            print(message or "No legacy credentials needed migration.")
            return 0
        if args.command == "credentials":
            result = application.set_credentials()
            print(result.message)
            return 0 if result.saved else 1
        if args.command == "doctor":
            report = application.execute_doctor()
            print(report.render())
            return report.exit_code
        if args.command == "run":
            return _run(args)
        if args.command == "data":
            return _data(args)
    except ValueError as error:
        print(f"gmes: error: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
